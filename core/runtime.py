import base64
import json
import os
import re
import shlex
import uuid
import time
import fcntl
from contextlib import ExitStack
from pathlib import Path

import yaml

from core.environment import (EnvironmentManager, NETWORK, atomic_write, code_directory,
                              container_workdir, environment_locks, operation_lock, read_binding, write_binding)


def exec_args(path, service, command, user=None, tty=False, workdir=None):
    from core.docker import DockerManager
    path = Path(path)
    binding = read_binding(path)
    if (path / '.phpbox/switch.json').exists():
        raise RuntimeError('项目环境切换尚未完成，请先恢复或等待切换完成')
    if binding and service in ('php', 'cron'):
        environment = EnvironmentManager().load(binding['environment_id'])
        args = ['docker', 'exec']
        if tty:
            args.append('-it')
        else:
            args.append('-i')
        args += ['-u', user or f'{os.getuid()}:{os.getgid()}', '-w', workdir or container_workdir(path),
                 '-e', 'PROJECT_NAME=' + path.name, environment.container]
    else:
        args = DockerManager(path).get_compose_command() + ['exec']
        if not tty:
            args.append('-T')
        if user:
            args += ['-u', user]
        if workdir:
            args += ['-w', workdir]
        args.append(service)
    return args + list(command)


def logs_args(path, service=None, follow=True, tail=200):
    from core.docker import DockerManager
    binding = read_binding(path)
    if binding and service in ('php', 'cron'):
        environment = EnvironmentManager().load(binding['environment_id'])
        return ['docker', 'logs'] + (['-f'] if follow else []) + ['--tail', str(tail), environment.container]
    return DockerManager(path).get_compose_command() + ['logs'] + (['-f'] if follow else []) + ['--tail', str(tail)] + ([service] if service else [])


class ProjectRuntime:
    def __init__(self, path, cancel=None, on_output=None):
        self.path = Path(path)
        self.manager = EnvironmentManager(cancel, on_output)

    def _document_root(self, content):
        roots = {root.strip() for root in re.findall(r'\broot\s+([^;]+);', content)}
        roots.discard('/usr/share/nginx/html')
        if len(roots) != 1:
            raise ValueError('仅支持使用单一明确 root 路径的站点配置')
        root = roots.pop()
        base = container_workdir(self.path) if read_binding(self.path) else '/var/www/html'
        if '$' in root or not (root == base or root.startswith(base + '/')):
            raise ValueError('Nginx root 不在项目代码目录内')
        if '..' in Path(root).parts:
            raise ValueError('Nginx root 不能包含上级路径')
        return root

    def preview(self, environment):
        content = (self.path / 'nginx/default.conf').read_text()
        binding = read_binding(self.path)
        if binding and not (re.search(r'fastcgi_pass\s+php:9000;', content) or (
                re.search(r'fastcgi_pass\s+\$phpbox_backend;', content) and
                re.search(r'set\s+\$phpbox_backend\s+[^;]+;', content))):
            raise ValueError('无法识别受管理的 PHP 上游配置，请先整理 Nginx 配置')
        compose = yaml.safe_load((self.path / 'docker-compose.yml').read_text())
        if not binding:
            dockerfile = (self.path / 'Dockerfile').read_text()
            if not re.match(r'FROM php:[0-9.]+-fpm\s', dockerfile) or len(re.findall(r'^FROM ', dockerfile, re.M)) != 1:
                raise ValueError('该项目不是标准 PHP-FPM Dockerfile，需手动整理后迁移')
            if set(compose['services']) - {'php', 'cron', 'nginx', 'mysql', 'redis'}:
                raise ValueError('项目包含自定义服务，请先检查自定义服务对独立 PHP 容器的依赖')
            allowed_mounts = ['/var/www/html', '/usr/local/etc/php/php.ini', '/usr/local/etc/php-fpm.conf',
                              '/usr/local/etc/php-fpm.d/www.conf', '/var/log/php-fpm', '/home/user/.ssh', '/home/user/.gitconfig']
            for mount in compose['services']['php'].get('volumes', []):
                if not isinstance(mount, str) or mount.split(':')[1] not in allowed_mounts:
                    raise ValueError('PHP 服务含自定义挂载，请先检查并配置目标环境')
            php = compose['services']['php']
            if set(php) - {'container_name', 'build', 'restart', 'user', 'environment', 'volumes', 'networks', 'extra_hosts'}:
                raise ValueError('PHP 服务包含自定义启动或运行设置，无法自动迁移')
            env_vars = php.get('environment', {})
            keys = set(env_vars) if isinstance(env_vars, dict) else {v.split('=', 1)[0] for v in env_vars}
            from core.environment import PROXY_KEYS
            if keys - set(PROXY_KEYS) - {'PROJECT_NAME'}:
                raise ValueError('PHP 服务含自定义环境变量，请先将其配置到目标环境')
            instructions = re.sub(r'\\\n\s*', ' ', dockerfile)
            for line in instructions.splitlines():
                if line.startswith(('COPY ', 'ADD ')) and not (
                    re.fullmatch(r'COPY --from=composer:(latest|2) /usr/bin/composer /usr/bin/composer', line) or
                    line == 'ADD https://github.com/mlocati/docker-php-extension-installer/releases/latest/download/install-php-extensions /usr/local/bin/'):
                    raise ValueError('Dockerfile 含自定义文件或系统依赖，无法自动迁移：' + line)
                if line.startswith('RUN apt-get ') and not re.fullmatch(
                        r'RUN apt-get update && apt-get install -y unzip git openssh-client zsh curl wget sudo(?: cron(?: procps util-linux)?)? && rm -rf /var/lib/apt/lists/\*', line):
                    raise ValueError('Dockerfile 含自定义系统包，请先准备对应的 PHP 环境')
            from core.templates import generate_dockerfile, EXTENSION_INSTALLER_URL, EXTENSION_INSTALLER_COMMAND
            from core.proxy import build_shell_proxy_block, validate_proxy_url
            version = re.match(r'FROM php:([0-9.]+)-fpm', dockerfile).group(1)
            reference = generate_dockerfile(self.path.name, version, [], '')
            def managed_proxy(match):
                try:
                    block = match.group('heredoc')
                    if block is None:
                        block = base64.b64decode(match.group('encoded'), validate=True).decode('utf-8')
                    address = re.search(r'^    export http_proxy=(.+)$', block, re.M)
                    expected = build_shell_proxy_block(None)
                    if address:
                        value = shlex.split(address[1])
                        if len(value) != 1 or shlex.quote(value[0]) != address[1]:
                            raise ValueError('代理地址不是字符串常量')
                        validate_proxy_url(value[0])
                        placeholder = 'http://phpbox-proxy.invalid'
                        block = block[:address.start(1)] + placeholder + block[address.end(1):]
                        expected = build_shell_proxy_block(placeholder)
                    if block != expected:
                        raise ValueError('代理助手内容与标准模板不同')
                except ValueError as exc:
                    raise ValueError('Dockerfile 中的代理助手含自定义或损坏的指令，无法自动迁移') from exc
                return ''

            def managed_lines(text):
                # 旧版使用 heredoc，新版使用 base64；仅忽略内容仍是标准模板的代理助手。
                text = re.sub(
                    r"^RUN cat <<'EOF' >> /home/user/\.zshrc\n(?P<heredoc>.*?)\nEOF$|"
                    r"^RUN echo '(?P<encoded>[A-Za-z0-9+/=]+)' \| base64 -d >> /home/user/\.zshrc$",
                    managed_proxy, text, flags=re.M | re.S)
                text = re.sub(r'\\\n\s*', ' ', text)
                lines = []
                for line in text.splitlines():
                    line = line.strip()
                    if not line or line.startswith('#') or line.startswith('RUN install-php-extensions '):
                        continue
                    if re.fullmatch(r'(ARG (HTTP_PROXY|HTTPS_PROXY)|ENV (http_proxy|https_proxy|HTTP_PROXY|HTTPS_PROXY)=.*)', line):
                        continue
                    if line in {EXTENSION_INSTALLER_COMMAND,
                                'ADD ' + EXTENSION_INSTALLER_URL + ' /usr/local/bin/',
                                'RUN chmod +x /usr/local/bin/install-php-extensions',
                                'RUN cp /usr/local/etc/php/php.ini-development /usr/local/etc/php/php.ini'}:
                        continue
                    lines.append(line.replace('composer:2 ', 'composer:latest ')
                                 .replace(' cron procps util-linux ', ' cron ').replace(' sudo cron ', ' sudo '))
                return lines
            if managed_lines(dockerfile) != managed_lines(reference):
                raise ValueError('Dockerfile 与 PHPBox 标准模板不同，无法可靠迁移自定义指令；请先整理项目或保留独立模式')
            if 'fastcgi_pass   php:9000;' not in content and not re.search(r'fastcgi_pass\s+php:9000;', content):
                raise ValueError('无法识别项目的 PHP 上游配置')
        self._document_root(content)
        info = {'environment': environment.name, 'php': environment.php_version,
                'code_path': container_workdir(self.path), 'databases': [], 'extensions': []}
        if not binding:
            info['extensions'] = re.findall(r'^RUN install-php-extensions (.+)$', dockerfile, re.M)
        if binding:
            project_id = binding['id']
        else:
            identity = self.path / '.phpbox/project-id'
            identity.parent.mkdir(parents=True, exist_ok=True)
            with identity.open('a+') as file:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                file.seek(0)
                project_id = file.read().strip()
                if not project_id:
                    project_id = uuid.uuid4().hex
                    file.write(project_id + '\n')
                elif not re.fullmatch(r'[a-f0-9]{32}', project_id):
                    raise ValueError('项目 ID 文件损坏，请检查 ' + str(identity))
        info['project_id'] = project_id
        info['target_extensions'] = environment.extensions
        info['config_files'] = [str(p) for p in (self.path / 'php').glob('*') if p.is_file()]
        for service in ('mysql', 'redis'):
            if service in compose['services']:
                info['databases'].append(service + ' → ' + service + '-' + project_id)
        return info

    def check(self, environment):
        with operation_lock(self.path), operation_lock(environment.path):
            if not self.manager.running(environment):
                self.manager._start(environment)
            return self._check(environment)

    def _check(self, environment):
        info = self.manager.verify(environment)
        if not info['version'].startswith(environment.php_version + '.'):
            raise RuntimeError('环境配置版本与实际 PHP 版本不符，请先重建环境')
        directory = container_workdir(self.path)
        self.manager.command(['docker', 'exec', '-u', f'{os.getuid()}:{os.getgid()}', environment.container,
                              'sh', '-c', 'test -r "$1" && test -x "$1"', 'sh', directory])
        code = code_directory(self.path)
        directories = [p for p in (code / 'storage', code / 'runtime', code / 'bootstrap/cache') if p.is_dir()]
        for path in directories:
            target = directory + '/' + path.relative_to(code).as_posix()
            self.manager.command(['docker', 'exec', '-u', f'{os.getuid()}:{os.getgid()}', environment.container, 'test', '-w', target])
        return info

    def _nginx(self, args):
        from core.docker import DockerManager
        result = DockerManager(self.path)._run_command(['exec', '-T', 'nginx', 'nginx'] + args)
        if not result.success:
            raise RuntimeError(result.error)

    def switch(self, environment, new_project=False):
        from core.docker import DockerManager
        with operation_lock(self.path), ExitStack() as tasks:
            old = read_binding(self.path)
            if not old:
                from core.project import Project
                from core.tasks import TaskManager
                project = Project(self.path.name, self.path)
                task_manager = TaskManager([project])
                for task in task_manager.load_project_tasks(project):
                    file = task_manager.get_state_dir(project) / (task.id + '.lock')
                    file.parent.mkdir(parents=True, exist_ok=True)
                    if not file.exists():
                        file.touch()
                    handle = tasks.enter_context(file.open('r'))
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise RuntimeError('旧任务正在执行，请结束后迁移')
            environments = [environment]
            if old:
                environments.append(self.manager.load(old['environment_id']))
            with environment_locks(environments):
                self._switch(environment, old, new_project)

    def _switch(self, environment, old, new_project):
        from core.docker import DockerManager
        if (self.path / '.phpbox/switch.json').exists():
            raise RuntimeError('存在未完成切换，请先恢复原环境')
        preview = self.preview(environment)
        if not self.manager.running(environment):
            self.manager._start(environment)
        self._check(environment)
        if old and old['environment_id'] == environment.id:
            return
        docker = DockerManager(self.path)
        state = docker._run_command(['ps', '--status', 'running', '--format', '{{.Service}}'])
        if not state.success:
            raise RuntimeError(state.error)
        running = state.output.splitlines()
        if not old and 'cron' in running:
            active = docker.exec_command('cron', ['sh', '-c',
                'for f in /var/www/html/.phpbox/tasks/state/*.pid; do [ -f "$f" ] || continue; '
                'p=$(cat "$f"); [ -r /proc/$p/cmdline ] && tr "\\0" " " </proc/$p/cmdline | grep -q run_task.sh && echo "$f"; done; true'])
            if not active.success or active.output.strip():
                raise RuntimeError('旧 Cron 容器有任务正在运行或无法检查，请稍后迁移')
        files = ['docker-compose.yml', 'nginx/default.conf', '.env.phpbox', 'Dockerfile']
        files += [str(p.relative_to(self.path)) for p in (self.path / 'php').glob('*') if p.is_file()]
        task_root = code_directory(self.path).relative_to(self.path) / '.phpbox/tasks'
        files += [str(task_root / name) for name in ('run_task.sh', 'generated.cron')]
        snapshot = {name: (self.path / name).read_text() if (self.path / name).exists() else None for name in files}
        identities = docker._run_command(['images', '--format', 'json'])
        record = {'binding': old, 'files': snapshot, 'running': running, 'target': environment.id,
                  'images': identities.output if identities.success else '', 'connected': []}
        marker = self.path / '.phpbox/switch.json'
        atomic_write(marker, json.dumps(record, ensure_ascii=False))
        try:
            data = dict(old) if old else {'id': preview['project_id'], 'enabled': 'nginx' in running}
            data['environment_id'] = environment.id
            if not old:
                backup = self.path / '.phpbox/independent-backup.json'
                atomic_write(backup, json.dumps(record, ensure_ascii=False))
                self._migrate_config(data, new_project)
                # 数据库只加入共享网络，保持原容器及数据卷；之后 up 会按新配置管理网络。
                original = yaml.safe_load(snapshot['docker-compose.yml'])
                for service in ('mysql', 'redis'):
                    if service in running:
                        container = original['services'][service]['container_name']
                        record['connected'].append(container)
                        atomic_write(marker, json.dumps(record, ensure_ascii=False))
                        self.manager.command(['docker', 'network', 'connect', '--alias', service + '-' + data['id'], NETWORK, container])
            nginx = (self.path / 'nginx/default.conf').read_text()
            nginx = re.sub(r'fastcgi_pass\s+php:9000;',
                'resolver 127.0.0.11 valid=5s ipv6=off;\n        set $phpbox_backend ' + environment.container + ':9000;\n        fastcgi_pass $phpbox_backend;', nginx)
            nginx = re.sub(r'set \$phpbox_backend [^;]+;', 'set $phpbox_backend ' + environment.container + ':9000;', nginx)
            # Nginx 的配置文件是单文件绑定挂载，保持 inode 才能被原容器看到。
            (self.path / 'nginx/default.conf').write_text(nginx)
            if not old and 'nginx' in running:
                self._compose(['up', '-d', '--no-build', '--no-deps', '--force-recreate', 'nginx'])
            if 'nginx' in running:
                self._nginx(['-t'])
                self._nginx(['-s', 'reload'])
            write_binding(self.path, data)
            self.manager.sync_cron(environment)
            if old:
                self.manager.sync_cron(self.manager.load(old['environment_id']))
            elif not new_project:
                # 旧 PHP/Cron 容器不在新 Compose 中，通过明确名称停止，保留镜像和数据。
                for service in ('php', 'cron'):
                    if service in running:
                        self.manager.command(['docker', 'stop', f'phpdev-{self.path.name}-{service}'])
            if 'nginx' in running:
                self.probe_route(environment)
            marker.unlink()
        except Exception as exc:
            self.manager.cancel = None
            try:
                self._restore(record)
                marker.unlink()
            except Exception as rollback:
                raise RuntimeError(f'{exc}；恢复失败：{rollback}。已保留切换记录，请点击“恢复原环境”。') from exc
            raise

    def _compose(self, args):
        from core.docker import DockerManager
        result = DockerManager(self.path, cancel=self.manager.cancel)._run_command(args)
        if not result.success:
            raise RuntimeError(result.error)
        return result.output

    def probe_route(self, environment):
        config = (self.path / 'nginx/default.conf').read_text()
        root = self._document_root(config)
        base = container_workdir(self.path)
        suffix = Path(root).relative_to(base)
        token = uuid.uuid4().hex
        file = code_directory(self.path) / suffix / ('.phpbox-probe-' + token + '.php')
        # 普通 PHP 路由的随机文件，仅返回版本和容器身份，不触发业务入口。
        file = file.with_name(file.name.lstrip('.'))
        try:
            file.write_text('<?php echo "' + token + ':" . gethostname() . ":" . PHP_VERSION;')
            file.chmod(0o644)
            for attempt in range(20):
                from core.docker import DockerManager
                result = DockerManager(self.path)._run_command(['exec', '-T', 'nginx', 'wget', '-Y', 'off', '-q', '-O', '-', '-T', '2', 'http://127.0.0.1/' + file.name])
                expected = token + ':' + environment.container + ':' + environment.php_version + '.'
                if result.success and result.output.startswith(expected):
                    return
                time.sleep(0.25)
            detail = ('HTTP 请求成功，但返回内容与目标 PHP 容器或版本不符' if result.success
                      else (result.raw_error or result.error).strip()[-1500:])
            raise RuntimeError('Nginx 到目标 PHP 环境的路由验证未通过：' + detail)
        finally:
            file.unlink(missing_ok=True)

    def _migrate_config(self, data, new_project=False):
        file = self.path / 'docker-compose.yml'
        compose = yaml.safe_load(file.read_text())
        compose.setdefault('name', self.path.name.lower())
        if new_project:
            compose['name'] = 'phpbox-project-' + data['id']
        services = compose['services']
        services.pop('php', None)
        services.pop('cron', None)
        compose.setdefault('networks', {})['phpbox'] = {'external': True, 'name': NETWORK}
        code = container_workdir(self.path)
        nginx = services['nginx']
        nginx.pop('depends_on', None)
        nginx['volumes'] = [v.replace(':/var/www/html', ':' + code) if isinstance(v, str) else v for v in nginx.get('volumes', [])]
        for name, service in services.items():
            networks = service.get('networks', ['default'])
            if isinstance(networks, list):
                networks = {key: {} for key in networks}
            networks['phpbox'] = {'aliases': [name + '-' + data['id']]}
            service['networks'] = networks
        atomic_write(file, yaml.safe_dump(compose, sort_keys=False, allow_unicode=True))
        conf = self.path / 'nginx/default.conf'
        conf.write_text(conf.read_text().replace('/var/www/html', code))
        env = self.path / '.env.phpbox'
        if env.exists():
            content = env.read_text()
            for service in ('mysql', 'redis'):
                if service in services:
                    key = 'DB_HOST' if service == 'mysql' else 'REDIS_HOST'
                    value = f'{key}={service}-{data["id"]}'
                    if re.search(r'^' + key + '=', content, re.M):
                        content = re.sub(r'^' + key + '=.*$', value, content, flags=re.M)
                    else:
                        content += '\n' + value + '\n'
            env.write_text(content)

    def _restore(self, record):
        for name, content in record['files'].items():
            file = self.path / name
            if content is not None:
                if file.name == 'run_task.sh':
                    atomic_write(file, content)
                    file.chmod(0o755)
                else:
                    file.write_text(content)
            elif file.exists():
                file.unlink()
        if record['binding']:
            write_binding(self.path, record['binding'])
        else:
            (self.path / '.phpbox/project.json').unlink(missing_ok=True)
        for container in record.get('connected', []):
            from core.process import run_process
            run_process(['docker', 'network', 'disconnect', NETWORK, container], timeout=30)
        if record['running']:
            self._compose(['up', '-d', '--no-build', '--no-deps'] + record['running'])
            if 'nginx' in record['running']:
                self._nginx(['-t'])
                self._nginx(['-s', 'reload'])
        ids = {record['target']}
        if record['binding']:
            ids.add(record['binding']['environment_id'])
        for environment_id in ids:
            self.manager.sync_cron(self.manager.load(environment_id))

    def recover(self):
        with operation_lock(self.path):
            file = self.path / '.phpbox/switch.json'
            if not file.exists():
                raise ValueError('没有未完成的切换')
            record = json.loads(file.read_text())
            ids = {record['target']}
            if record['binding']:
                ids.add(record['binding']['environment_id'])
            with environment_locks([self.manager.load(i) for i in ids]):
                self._restore(record)
                file.unlink()

    def lifecycle(self, action):
        with operation_lock(self.path):
            if (self.path / '.phpbox/switch.json').exists():
                raise RuntimeError('存在未完成切换，请先恢复原环境')
            data = read_binding(self.path)
            environment = self.manager.load(data['environment_id'])
            with operation_lock(environment.path):
                if action in ('up', 'restart'):
                    if not self.manager.running(environment):
                        self.manager._start(environment)
                    self._compose(['up', '-d', '--no-build'])
                    if action == 'restart':
                        self._compose(['restart'])
                    self._nginx(['-t'])
                    self.probe_route(environment)
                    data['enabled'] = True
                else:
                    data['enabled'] = False
                    write_binding(self.path, data)
                    self.manager.sync_cron(environment)
                    self._compose([action])
                write_binding(self.path, data)
                self.manager.sync_cron(environment)
