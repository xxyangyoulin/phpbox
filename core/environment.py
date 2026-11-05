import fcntl
import json
import os
import re
import shutil
import uuid
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
from pathlib import Path

import yaml

from core.config import BASE_DIR, PHP_VERSIONS
from core.process import run_process
from core.proxy import convert_proxy_for_docker
from core.templates import generate_dockerfile

ENVIRONMENTS_DIR = BASE_DIR.parent / 'environments'
NETWORK = 'phpbox-environments'
PROXY_KEYS = ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY',
              'all_proxy', 'ALL_PROXY', 'ftp_proxy', 'FTP_PROXY', 'no_proxy', 'NO_PROXY')


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(content, encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_binding(path):
    file = Path(path) / '.phpbox/project.json'
    if not file.exists():
        return None
    data = json.loads(file.read_text())
    if (not isinstance(data, dict) or
            any(not isinstance(data.get(key), str) or not re.fullmatch(r'[a-f0-9]{32}', data[key])
                for key in ('id', 'environment_id')) or not isinstance(data.get('enabled'), bool)):
        raise ValueError(f'{file}: 无效的 PHP 环境绑定')
    return data


def write_binding(path, data):
    atomic_write(Path(path) / '.phpbox/project.json', json.dumps(data, ensure_ascii=False, indent=2) + '\n')


@contextmanager
def operation_lock(path):
    if not Path(path).is_dir():
        raise ValueError('项目或环境目录已不存在，请刷新列表')
    directory = Path(path) / '.phpbox'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'operation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('该项目或环境已有操作进行中，请稍后重试')
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def code_directory(path):
    from core.project import get_project_code_path
    return get_project_code_path(Path(path), Path(path).name)


def container_workdir(path):
    return '/workspaces/' + code_directory(path).resolve().relative_to(BASE_DIR.resolve()).as_posix()


@contextmanager
def environment_locks(environments):
    with ExitStack() as stack:
        for path in sorted({env.path for env in environments}):
            stack.enter_context(operation_lock(path))
        yield


@dataclass
class PhpEnvironment:
    id: str
    name: str
    php_version: str
    extensions: list
    proxy: str = ''

    @property
    def path(self):
        return ENVIRONMENTS_DIR / self.id

    @property
    def container(self):
        return 'phpbox-env-' + self.id


class EnvironmentManager:
    def __init__(self, cancel=None, on_output=None):
        self.cancel = cancel
        self.on_output = on_output

    def command(self, args, cwd=None, timeout=300):
        result = run_process(args, cwd=str(cwd) if cwd else None, cancel=self.cancel,
                             on_output=self.on_output, timeout=timeout)
        if result.returncode:
            raise RuntimeError(result.stdout[-4000:] or 'Docker 操作失败')
        return result.stdout

    def load(self, environment_id):
        if not re.fullmatch(r'[a-f0-9]{32}', environment_id):
            raise ValueError('无效的环境 ID')
        file = ENVIRONMENTS_DIR / environment_id / 'environment.json'
        data = json.loads(file.read_text())
        if data.get('id') != environment_id:
            raise ValueError('环境 ID 与目录不一致')
        return PhpEnvironment(**data)

    def list(self):
        if not ENVIRONMENTS_DIR.exists():
            return []
        return [self.load(file.parent.name) for file in sorted(ENVIRONMENTS_DIR.glob('*/environment.json'))]

    def save(self, environment):
        atomic_write(environment.path / 'environment.json', json.dumps(environment.__dict__, ensure_ascii=False, indent=2) + '\n')
        (environment.path / 'environment.json').chmod(0o600)

    def busy(self, environment):
        file = environment.path / '.phpbox/operation.lock'
        if not file.exists():
            return False
        with file.open('r') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return False
            except BlockingIOError:
                return True

    def bindings(self, environment_id):
        return [path for path in BASE_DIR.iterdir() if path.is_dir()
                and (read_binding(path) or {}).get('environment_id') == environment_id] if BASE_DIR.exists() else []

    def compose(self, environment, args):
        from core.docker import DockerManager
        prefix = DockerManager(environment.path).get_compose_command()
        if not prefix:
            raise RuntimeError('未检测到 Docker Compose')
        return self.command(prefix + args, environment.path, timeout=3600)

    def ensure_network(self):
        result = run_process(['docker', 'network', 'inspect', NETWORK], cancel=self.cancel)
        if result.returncode:
            self.command(['docker', 'network', 'create', NETWORK])

    def create(self, name, version, extensions, proxy=''):
        if not name.strip() or version not in PHP_VERSIONS:
            raise ValueError('请填写环境名称并选择支持的 PHP 版本')
        if any(not re.fullmatch(r'[a-zA-Z0-9_]+(?:-[a-zA-Z0-9.^@]+)?', item) for item in extensions):
            raise ValueError('扩展名称格式无效')
        if proxy:
            convert_proxy_for_docker(proxy)
        environment = PhpEnvironment(uuid.uuid4().hex, name.strip(), version, list(dict.fromkeys(extensions)), proxy)
        environment.path.mkdir(parents=True)
        self.generate_files(environment)
        self.save(environment)
        return environment

    def generate_files(self, environment):
        uid, gid = os.getuid(), os.getgid()
        # 共享终端由 exec 注入项目名，镜像中只设置无项目时的默认提示符。
        dockerfile = generate_dockerfile('${PROJECT_NAME:-PHP}', environment.php_version,
                                        environment.extensions, environment.proxy)
        dockerfile += '''
RUN sed -i 's/^user = .*/user = user/; s/^group = .*/group = user/' /usr/local/etc/php-fpm.d/www.conf
COPY entrypoint.sh /usr/local/bin/phpbox-environment
RUN chmod +x /usr/local/bin/phpbox-environment
WORKDIR /workspaces
CMD ["/usr/local/bin/phpbox-environment"]
'''
        atomic_write(environment.path / 'Dockerfile', dockerfile)
        atomic_write(environment.path / 'entrypoint.sh', '''#!/bin/bash
set -e
crontab /phpbox/scheduler/cron
cron -f &
cron_pid=$!
php-fpm -F &
php_pid=$!
trap 'kill -TERM "$cron_pid" "$php_pid" 2>/dev/null || true; wait || true' EXIT
trap 'exit 0' TERM INT
wait -n "$cron_pid" "$php_pid"
exit 1
''')
        config = environment.path / 'php/php.ini'
        if not config.exists():
            atomic_write(config, '; Overrides for the PHP php.ini-development defaults.\n')
        if not (environment.path / 'scheduler/cron').exists():
            atomic_write(environment.path / 'scheduler/cron', '\n')
        (environment.path / 'scheduler/gate').touch(exist_ok=True)
        compose = {'name': environment.container, 'services': {'php': {
            'container_name': environment.container, 'hostname': environment.container,
            'image': environment.container + ':latest',
            'build': {'context': '.', 'dockerfile': 'Dockerfile', 'args': {'USER_UID': uid, 'USER_GID': gid}},
            'restart': 'unless-stopped',
            'environment': {**dict.fromkeys(PROXY_KEYS, ''), 'PHPBOX_ENVIRONMENT_ID': environment.id},
            'volumes': [f'{BASE_DIR}:/workspaces', './php:/usr/local/etc/php/phpbox:ro', './scheduler:/phpbox/scheduler:ro'],
            'extra_hosts': ['host.docker.internal:host-gateway'],
            'networks': {'shared': {'aliases': [environment.container]}},
            'healthcheck': {'test': ['CMD-SHELL', 'pgrep -x cron >/dev/null && php-fpm -t >/dev/null 2>&1'],
                            'interval': '10s', 'timeout': '5s', 'retries': 3},
        }}, 'networks': {'shared': {'external': True, 'name': NETWORK}}}
        compose['services']['php']['environment']['PHP_INI_SCAN_DIR'] = '/usr/local/etc/php/conf.d:/usr/local/etc/php/phpbox'
        for source, target in ((Path.home() / '.ssh', '/home/user/.ssh'), (Path.home() / '.gitconfig', '/home/user/.gitconfig')):
            if source.exists():
                compose['services']['php']['volumes'].append(str(source) + ':' + target + ':ro')
        atomic_write(environment.path / 'docker-compose.yml', yaml.safe_dump(compose, sort_keys=False, allow_unicode=True))

    def running(self, environment):
        result = run_process(['docker', 'inspect', '-f', '{{.State.Running}}', environment.container], timeout=10)
        return result.returncode == 0 and result.stdout.strip() == 'true'

    def info(self, environment):
        output = self.command(['docker', 'exec', environment.container, 'php', '-r',
            '$e=[];foreach(get_loaded_extensions() as $n){$e[$n]=phpversion($n)?:"built-in";}'
            'echo json_encode(["version"=>PHP_VERSION,"extensions"=>$e,"memory_limit"=>ini_get("memory_limit"),"timezone"=>ini_get("date.timezone")]);'])
        return json.loads(output)

    def active_tasks(self, environment):
        return self.command(['docker', 'exec', environment.container, 'sh', '-c',
            'for f in /workspaces/*/*/.phpbox/tasks/state/*.pid; do '
            '[ -f "$f" ] || continue; [ "$(cat "${f%.pid}.environment" 2>/dev/null)" = "$PHPBOX_ENVIRONMENT_ID" ] || continue; p=$(cat "$f"); '
            '[ -r "/proc/$p/cmdline" ] && tr "\\0" " " <"/proc/$p/cmdline" | grep -q run_task.sh && echo "$f"; done; true'])

    def assert_project_idle(self, path):
        states = code_directory(path) / '.phpbox/tasks/state'
        ids = set()
        for file in states.glob('*.environment'):
            try:
                ids.add(file.read_text().strip())
            except FileNotFoundError:
                continue
        prefix = container_workdir(path) + '/.phpbox/tasks/state/'
        for environment_id in ids - {''}:
            try:
                environment = self.load(environment_id)
            except FileNotFoundError:
                continue
            if self.running(environment) and prefix in self.active_tasks(environment):
                raise RuntimeError('此项目仍有任务在原环境或当前环境执行，请结束后再删除或重命名')

    @contextmanager
    def maintenance(self, environment):
        marker = environment.path / 'scheduler/maintenance'
        atomic_write(marker, 'maintenance\n')
        try:
            with (environment.path / 'scheduler/gate').open('a') as gate:
                fcntl.flock(gate, fcntl.LOCK_EX)
                if self.running(environment) and self.active_tasks(environment).strip():
                    raise RuntimeError('环境内有任务正在执行，请等待完成后重试')
                yield
        finally:
            marker.unlink(missing_ok=True)

    def build(self, environment):
        with operation_lock(environment.path):
            self._build(environment)

    def update(self, environment, extensions, proxy, config):
        if any(not re.fullmatch(r'[a-zA-Z0-9_]+(?:-[a-zA-Z0-9.^@]+)?', item) for item in extensions):
            raise ValueError('扩展名称格式无效')
        if proxy:
            convert_proxy_for_docker(proxy)
        with operation_lock(environment.path):
            original = self.load(environment.id)
            file = environment.path / 'php/php.ini'
            previous = file.read_text()
            environment.extensions = list(dict.fromkeys(extensions))
            environment.proxy = proxy
            if environment.extensions != original.extensions or environment.proxy != original.proxy:
                try:
                    self._build(environment)
                    self.save(environment)
                    original = self.load(environment.id)
                except Exception:
                    self.generate_files(original)
                    raise
            with self.maintenance(environment):
                try:
                    atomic_write(file, config)
                    if self.running(environment):
                        self.command(['docker', 'exec', environment.container, 'php-fpm', '-t'])
                        self.compose(environment, ['restart'])
                        self.verify(environment)
                    self.save(environment)
                except Exception:
                    atomic_write(file, previous)
                    self.generate_files(original)
                    recovery = EnvironmentManager(on_output=self.on_output)
                    if recovery.running(environment):
                        recovery.compose(environment, ['restart'])
                    raise

    def _build(self, environment):
        with self.maintenance(environment):
            running = self.running(environment)
            previous = run_process(['docker', 'image', 'inspect', '-f', '{{.Id}}', environment.container + ':latest'], timeout=15)
            self.generate_files(environment)
            proxy = convert_proxy_for_docker(environment.proxy) if environment.proxy else ''
            args = ['build']
            for key in PROXY_KEYS:
                args += ['--build-arg', key + '=' + (proxy if key.lower() in ('http_proxy', 'https_proxy') else '')]
            try:
                self.compose(environment, args)
                if running:
                    self._start(environment)
            except Exception as exc:
                if previous.returncode == 0:
                    recovery = EnvironmentManager(on_output=self.on_output)
                    recovery.command(['docker', 'tag', previous.stdout.strip(), environment.container + ':latest'])
                    recovery.generate_files(recovery.load(environment.id))
                    if running:
                        try:
                            recovery._start(environment)
                        except Exception as rollback:
                            raise RuntimeError(f'{exc}；恢复环境失败：{rollback}') from exc
                raise

    def start(self, environment):
        with operation_lock(environment.path):
            if not self.running(environment):
                self._start(environment)
            self.verify(environment)

    def _start(self, environment):
        self.ensure_network()
        self.sync_cron(environment)
        self.compose(environment, ['up', '-d', '--no-build'])
        self.verify(environment)

    def verify(self, environment):
        self.command(['docker', 'exec', environment.container, 'php-fpm', '-t'])
        self.command(['docker', 'exec', environment.container, 'pgrep', '-x', 'cron'])
        self.command(['docker', 'exec', environment.container, 'php', '-r',
                      'for($i=0;$i<30;$i++){if(@fsockopen("127.0.0.1",9000)){exit(0);}usleep(100000);}exit(1);'])
        return self.info(environment)

    def stop(self, environment):
        with operation_lock(environment.path):
            with self.maintenance(environment):
                self.compose(environment, ['stop'])

    def delete(self, environment):
        with operation_lock(environment.path):
            if self.bindings(environment.id):
                raise ValueError('环境仍被项目绑定，请先切换项目环境')
            with self.maintenance(environment):
                self.compose(environment, ['down'])
            shutil.rmtree(environment.path)

    def rename(self, environment, name):
        if not name.strip():
            raise ValueError('环境名称不能为空')
        with operation_lock(environment.path):
            environment.name = name.strip()
            self.save(environment)

    def sync_cron(self, environment):
        from core.project import Project
        from core.tasks import TaskManager
        lines = ['SHELL=/bin/sh', 'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                 'PHPBOX_ENVIRONMENT_ID=' + environment.id]
        for path in self.bindings(environment.id):
            data = read_binding(path)
            if not data.get('enabled'):
                continue
            project = Project(path.name, path)
            manager = TaskManager([project])
            manager.ensure_runner_script(project)
            runner = container_workdir(path) + '/.phpbox/tasks/run_task.sh'
            for task in manager.load_project_tasks(project):
                if task.enabled:
                    schedule = manager.resolve_cron_expression(task)
                    if not manager.is_valid_cron_expression(schedule):
                        raise ValueError('无效的定时任务表达式: ' + task.name)
                    lines.append(schedule + ' ' + manager.shell_quote(runner) + ' ' + manager.shell_quote(task.id))
        atomic_write(environment.path / 'scheduler/cron', '\n'.join(lines) + '\n')
        if self.running(environment):
            self.command(['docker', 'exec', '-u', '0', environment.container, 'crontab', '/phpbox/scheduler/cron'])
