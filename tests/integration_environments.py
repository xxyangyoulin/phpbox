"""显式运行：QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.integration_environments"""
import json
import os
import shlex
import subprocess
import tempfile
import time
import uuid
import yaml
from pathlib import Path
from unittest.mock import patch

from core import config, environment, project, runtime
from core.docker import DockerManager
from core.tasks import TaskDefinition, TaskManager
from ui.dialogs.create_project import CreateProjectDialog
from core.templates import generate_dockerfile
from core.proxy import convert_proxy_for_docker


def scaffold(root, name, port):
    path = root / name
    for directory in (name, 'php', 'nginx', 'logs/nginx'):
        (path / directory).mkdir(parents=True, exist_ok=True)
    (path / 'Dockerfile').write_text(generate_dockerfile(name, '8.4', [], ''))
    (path / 'docker-compose.yml').write_text(CreateProjectDialog.generate_compose(None, name, port, '', name, None, None))
    (path / 'nginx/default.conf').write_text(CreateProjectDialog.generate_nginx_config(None))
    (path / '.env.phpbox').write_text('PHPBOX_HTTP_PORT=' + str(port) + '\n')
    (path / name / 'index.php').write_text('<?php echo basename(getcwd()) . ":" . PHP_VERSION;')
    docker = DockerManager(path)
    if not docker.copy_config_from_image('nginx:alpine', '/etc/nginx/nginx.conf', path / 'nginx/nginx.conf'):
        raise RuntimeError('复制测试 Nginx 配置失败')
    return path


def verify_migration(manager, first, second, projects, paths):
    path = scaffold(projects, 'phpbox-legacy-' + uuid.uuid4().hex[:8], 19872)
    paths.append(path)
    file = path / 'docker-compose.yml'
    compose = yaml.safe_load(file.read_text())
    # 使用本次验收生成的镜像提供旧项目的 PHP 运行时。
    image = compose['name'] + '-php:latest'
    fixture = path / '.phpbox/legacy-test.Dockerfile'
    environment.atomic_write(fixture, 'FROM ' + first.container + ':latest\nCMD ["php-fpm", "-F"]\n')
    manager.command(['docker', 'build', '-t', image, '-f', str(fixture), str(path)])
    php = compose['services']['php']
    for source, target in [('/usr/local/etc/php/php.ini-development', 'php.ini'),
                           ('/usr/local/etc/php-fpm.conf', 'php-fpm.conf'),
                           ('/usr/local/etc/php-fpm.d/www.conf', 'www.conf')]:
        assert DockerManager(path).copy_config_from_image(image, source, path / 'php' / target)
    compose['services']['redis'] = {'image': 'redis:7', 'container_name': 'phpdev-' + path.name + '-redis',
                                   'volumes': ['redis_data:/data'], 'networks': ['app']}
    compose['services']['nginx']['environment'] = {
        'http_proxy': 'http://127.0.0.1:7890', 'HTTP_PROXY': 'http://127.0.0.1:7890',
        'no_proxy': '127.0.0.0/8', 'NO_PROXY': '127.0.0.0/8'}
    compose['volumes'] = {'redis_data': None}
    environment.atomic_write(file, yaml.safe_dump(compose, sort_keys=False))
    result = DockerManager(path)._run_command(['up', '-d', '--no-build'])
    assert result.success, result.error
    proxied = DockerManager(path)._run_command(['exec', '-T', 'nginx', 'wget', '-q', '-O', '-', '-T', '2', 'http://127.0.0.1/'])
    assert not proxied.success and 'Connection refused' in proxied.raw_error, proxied
    redis = compose['services']['redis']['container_name']
    manager.command(['docker', 'exec', redis, 'redis-cli', 'SET', 'phpbox-sentinel', path.name])
    before = manager.command(['docker', 'inspect', '-f', '{{.Id}}', redis]).strip()
    active = runtime.ProjectRuntime(path)
    active.switch(second)
    assert manager.command(['docker', 'inspect', '-f', '{{.Id}}', redis]).strip() == before
    binding = environment.read_binding(path)
    host = 'redis-' + binding['id']
    output = manager.command(runtime.exec_args(path, 'php', ['php', '-r',
        '$r=new Redis();$r->connect($argv[1],6379);echo $r->get("phpbox-sentinel");', host]))
    assert output == path.name, output
    active.probe_route(second)
    active.switch(first)
    assert manager.command(['docker', 'exec', redis, 'redis-cli', 'GET', 'phpbox-sentinel']).strip() == path.name
    print('PASS: 带旧代理的项目迁移及路由验证、Redis 容器 ID / 数据保持、共享 PHP 通过唯一地址连接数据库', flush=True)


def run():
    root = Path(tempfile.mkdtemp(prefix='phpbox-environments-test-'))
    projects = root / 'projects'
    projects.mkdir()
    network = 'phpbox-test-' + uuid.uuid4().hex[:12]
    patches = [patch.object(config, 'BASE_DIR', projects), patch.object(project, 'BASE_DIR', projects),
               patch.object(environment, 'BASE_DIR', projects), patch.object(environment, 'ENVIRONMENTS_DIR', root / 'environments'),
               patch.object(environment, 'NETWORK', network), patch.object(runtime, 'NETWORK', network)]
    for item in patches:
        item.start()
    environments = []
    paths = []
    manager = environment.EnvironmentManager(on_output=lambda line: print(line, flush=True))
    try:
        for version in ('8.4', '8.2', '8.4'):
            env = manager.create('验收 PHP ' + version, version, ['pdo_mysql', 'redis'], os.environ.get('PHPBOX_TEST_PROXY', ''))
            environments.append(env)
            manager.build(env)
            manager.start(env)
            code = '$v=[];foreach(["memory_limit","log_errors","error_reporting","display_errors","upload_max_filesize","post_max_size","date.timezone"] as $k){$v[$k]=ini_get($k);}echo json_encode($v);'
            actual = manager.command(['docker', 'exec', env.container, 'php', '-r', code])
            expected = manager.command(['docker', 'exec', env.container, 'php', '-c', '/usr/local/etc/php/php.ini-development', '-r', code])
            assert actual == expected, (actual, expected)
            assert manager.command(['docker', 'exec', env.container, 'php', '-r', 'echo php_ini_loaded_file();']) == '/usr/local/etc/php/php.ini'
            proxy_check = ('proxy && [[ "$http_proxy" == ' + shlex.quote(convert_proxy_for_docker(env.proxy)) + ' ]]'
                           if env.proxy else '! proxy')
            shell = ('set -e; [[ "$PROJECT_NAME" == phpbox-shell-check ]]; '
                     '[[ -z "$http_proxy$https_proxy$HTTP_PROXY$HTTPS_PROXY" ]]; '
                     'for plugin in git-open zsh-autosuggestions zsh-syntax-highlighting; do '
                     '[[ -d "$HOME/.oh-my-zsh/custom/plugins/$plugin" ]]; done; '
                     'whence -w proxy noproxy ckproxy; ' + proxy_check + '; '
                     'noproxy; [[ -z "$http_proxy$https_proxy$HTTP_PROXY$HTTPS_PROXY" ]]')
            manager.command(['docker', 'exec', '-u', f'{os.getuid()}:{os.getgid()}',
                             '-e', 'PROJECT_NAME=phpbox-shell-check', '-e', 'TERM=xterm-256color',
                             env.container, 'zsh', '-ic', shell])
            print('PASS: PHP ' + version + ' 开发默认配置、终端插件、项目提示符及代理开关', flush=True)
        first, second, alternate = environments
        manager.update(alternate, alternate.extensions, alternate.proxy, 'memory_limit=384M\ndate.timezone=Asia/Shanghai\n')
        for index in range(2):
            path = scaffold(projects, 'phpbox-it-' + uuid.uuid4().hex[:8], 19870 + index)
            paths.append(path)
            runtime.ProjectRuntime(path).switch(first, new_project=True)
            runtime.ProjectRuntime(path).lifecycle('up')
        ids = [manager.command(['docker', 'inspect', '-f', '{{.Id}}', env.container]).strip() for env in environments]
        composer = paths[0] / paths[0].name / 'composer.json'
        lock = composer.with_name('composer.lock')
        requirements = {'php': '^8.4', 'ext-missing': '*'}
        composer.write_text(json.dumps({'require': requirements}))
        for locked in (False, True):
            if locked:
                lock.write_text(json.dumps({'packages': [], 'platform': requirements}))
            before = {file: file.read_bytes() for file in (composer, lock) if file.exists()}
            runtime.ProjectRuntime(paths[0]).check(second)
            runtime.ProjectRuntime(paths[0]).switch(second)
            runtime.ProjectRuntime(paths[0]).probe_route(second)
            runtime.ProjectRuntime(paths[0]).switch(first)
            assert {file: file.read_bytes() for file in before} == before
            assert lock.exists() == locked
        composer.unlink()
        lock.unlink()
        print('PASS: 有无锁文件时均忽略 Composer 平台要求，切换不修改依赖文件', flush=True)
        for path in paths:
            output = manager.command(runtime.exec_args(path, 'php', ['php', '-r', 'echo getcwd();']))
            assert output == environment.container_workdir(path), output
        active = runtime.ProjectRuntime(paths[0])
        active.switch(alternate)
        assert manager.info(alternate)['memory_limit'] == '384M'
        active.switch(first)
        active.switch(second)
        active.probe_route(second)
        runtime.ProjectRuntime(paths[1]).probe_route(first)
        assert ids == [manager.command(['docker', 'inspect', '-f', '{{.Id}}', env.container]).strip() for env in environments]
        model = project.Project(paths[0].name, paths[0])
        tasks = TaskManager([model])
        task = TaskDefinition('integration', '验收任务', model.name, '自定义', '', '* * * * *', 'user',
                              'php -r \'echo PHP_VERSION;\'', True, '', '')
        tasks.save_task(task)
        with environment.operation_lock(second.path):
            manager.sync_cron(second)
        command = runtime.exec_args(paths[0], 'cron', ['setsid', environment.container_workdir(paths[0]) + '/.phpbox/tasks/run_task.sh',
                                                    task.id, '--manual', 'it-' + uuid.uuid4().hex], user='root')
        manager.command(command)
        state = tasks.get_task_state(model, task.id)
        assert state.environment_id == second.id, state
        task.command = 'sleep 4; php -r \'echo PHP_VERSION;\''
        tasks.save_task(task)
        run_id = 'it-' + uuid.uuid4().hex
        command[-1] = run_id
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 10
        while not (tasks.get_state_dir(model) / (run_id + '.pid')).exists():
            assert time.monotonic() < deadline
            time.sleep(.05)
        active.switch(first)
        assert not project.ProjectManager().rename_project(model, model.name + '-busy')
        assert not project.ProjectManager().delete_project(model)
        assert child.wait(timeout=15) == 0
        state = tasks.get_task_state(model, task.id)
        assert state.environment_id == second.id, state
        assert '8.2.' in tasks.read_recent_task_logs(model, task.id)
        task.enabled = False
        tasks.save_task(task)
        with environment.operation_lock(first.path):
            manager.sync_cron(first)
        original = environment.read_binding(paths[0])
        with patch.object(active, 'probe_route', side_effect=RuntimeError('injected route failure')):
            try:
                active.switch(second)
            except RuntimeError:
                pass
            else:
                raise AssertionError('应当回滚失败的切换')
        assert environment.read_binding(paths[0]) == original
        active.probe_route(first)
        active.lifecycle('stop')
        assert manager.running(first)
        runtime.ProjectRuntime(paths[1]).probe_route(first)
        renamed = paths[0].name + '-renamed'
        assert project.ProjectManager().rename_project(model, renamed)
        paths[0] = projects / renamed
        runtime.ProjectRuntime(paths[0]).lifecycle('up')
        runtime.ProjectRuntime(paths[0]).probe_route(first)
        verify_migration(manager, first, second, projects, paths)
        # 真正等待 Cron 触发；整个验收没有启动桌面应用。
        model = project.Project(paths[0].name, paths[0])
        tasks = TaskManager([model])
        automatic = TaskDefinition('automatic', '自动调度验收', model.name, '自定义', '', '* * * * *', 'user',
                                   'php -r \'echo PHP_VERSION;\'', True, '', '')
        tasks.save_task(automatic)
        with environment.operation_lock(first.path):
            manager.sync_cron(first)
        print('等待环境 Cron 自动调度（最多 75 秒）...', flush=True)
        deadline = time.monotonic() + 75
        while tasks.get_task_state(model, automatic.id).last_status != 'success':
            assert time.monotonic() < deadline, 'Cron 没有触发任务'
            time.sleep(.5)
        assert tasks.get_task_state(model, automatic.id).environment_id == first.id
        automatic.enabled = False
        tasks.save_task(automatic)
        with environment.operation_lock(first.path):
            manager.sync_cron(first)
        # 模拟环境替换后的新 IP，验证 Nginx Docker DNS 自动重新解析。
        manager.compose(first, ['up', '-d', '--no-build', '--force-recreate'])
        manager.verify(first)
        runtime.ProjectRuntime(paths[1]).probe_route(first)
        print('PASS: 同版本不同配置、应用未启动时的 Cron 调度、环境替换后的动态 DNS', flush=True)
        print('PASS: 共享项目、不同 PHP 版本切换、容器 ID 保持、工作目录、任务跨切换、回滚、停止隔离、重命名', flush=True)
    finally:
        manager.cancel = None
        for path in paths:
            DockerManager(path)._run_command(['down', '--volumes', '--remove-orphans'])
            if path.name.startswith('phpbox-legacy-'):
                subprocess.run(['docker', 'image', 'rm', 'phpdev-' + path.name + '-php:latest'], capture_output=True)
        for env in environments:
            manager.compose(env, ['down', '--rmi', 'all'])
        subprocess.run(['docker', 'network', 'rm', network], capture_output=True)
        for item in reversed(patches):
            item.stop()
        print('验收文件及日志保留于：' + str(root), flush=True)


if __name__ == '__main__':
    run()
