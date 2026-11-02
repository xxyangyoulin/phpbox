import base64
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from core.docker import DockerManager, DockerResult
from core.environment import (EnvironmentManager, NETWORK, atomic_write, container_workdir,
                              environment_locks, operation_lock, read_binding, write_binding)
from core.project import Project, ProjectManager
from core.proxy import build_dockerfile_proxy_snippet, build_shell_proxy_block
from core.runtime import ProjectRuntime, exec_args
from core.tasks import TaskManager
from tests.test_regressions import task
from core.templates import generate_dockerfile, EXTENSION_INSTALLER_URL, EXTENSION_INSTALLER_COMMAND


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.projects = self.root / 'projects'
        self.projects.mkdir()
        for target, value in [('core.environment.BASE_DIR', self.projects),
                              ('core.project.BASE_DIR', self.projects),
                              ('core.environment.ENVIRONMENTS_DIR', self.root / 'environments')]:
            patched = patch(target, value)
            patched.start()
            self.addCleanup(patched.stop)
        self.manager = EnvironmentManager()
        self.first = self.manager.create('PHP A', '8.4', ['redis', 'igbinary'])
        self.second = self.manager.create('PHP B', '8.2', ['redis'])
        self.path = self.projects / 'demo'
        for subdir in ('demo', 'nginx', 'php'):
            (self.path / subdir).mkdir(parents=True)
        self.project = Project('demo', self.path)
        (self.path / 'Dockerfile').write_text(generate_dockerfile('demo', '8.4', ['redis'], ''))
        (self.path / '.env.phpbox').write_text('DB_HOST=mysql\nREDIS_HOST=redis\n')
        (self.path / 'nginx/default.conf').write_text('server { root /var/www/html; location ~ \\.php$ { fastcgi_pass php:9000; } }\n')
        compose = {'name': 'phpdev-original', 'services': {
            'php': {'container_name': 'phpdev-demo-php', 'volumes': ['./demo:/var/www/html']},
            'nginx': {'container_name': 'phpdev-demo-nginx', 'volumes': ['./demo:/var/www/html'],
                      'depends_on': ['php'], 'ports': ['18080:80']},
            'mysql': {'container_name': 'phpdev-demo-mysql', 'volumes': ['mysql_data:/var/lib/mysql']},
            'redis': {'container_name': 'phpdev-demo-redis', 'volumes': ['redis_data:/data']},
        }, 'volumes': {'mysql_data': {'name': 'original-mysql'}, 'redis_data': None}}
        atomic_write(self.path / 'docker-compose.yml', yaml.safe_dump(compose))

    def bind(self, environment=None, enabled=True):
        write_binding(self.path, {'id': '1' * 32, 'environment_id': (environment or self.first).id, 'enabled': enabled})
        conf = self.path / 'nginx/default.conf'
        conf.write_text(conf.read_text().replace('/var/www/html', container_workdir(self.path)))

    def runtime(self, running=''):
        result = ProjectRuntime(self.path)
        result.manager.running = Mock(return_value=True)
        result.manager.verify = Mock(return_value={'version': '8.2.12', 'extensions': {'redis': '6'}})
        result.manager.command = Mock(return_value='')
        result.manager.sync_cron = Mock()
        docker = patch.object(DockerManager, '_run_command', return_value=DockerResult(True, running))
        docker.start()
        self.addCleanup(docker.stop)
        return result

    def test_same_version_environments_have_independent_identity(self):
        other = self.manager.create('PHP A', '8.4', [])
        self.assertNotEqual(self.first.container, other.container)
        previous = self.first.container
        self.manager.rename(self.first, '重命名')
        self.assertEqual(self.manager.load(self.first.id).container, previous)

    def test_generated_environment_does_not_publish_fpm_or_keep_proxy(self):
        compose = yaml.safe_load((self.first.path / 'docker-compose.yml').read_text())
        service = compose['services']['php']
        self.assertNotIn('ports', service)
        self.assertEqual(service['environment']['HTTP_PROXY'], '')
        self.assertIn('./scheduler:/phpbox/scheduler:ro', service['volumes'])
        text = (self.first.path / 'Dockerfile').read_text()
        self.assertLess(text.index('install-php-extensions igbinary'), text.index('install-php-extensions redis'))
        self.assertEqual(compose['networks']['shared']['name'], NETWORK)

    def test_exec_uses_binding_workdir_uid_and_does_not_fallback_when_missing(self):
        self.bind()
        args = exec_args(self.path, 'php', ['php', '-v'])
        self.assertEqual(args[:2], ['docker', 'exec'])
        self.assertIn('-i', args)
        self.assertIn(f'{os.getuid()}:{os.getgid()}', args)
        self.assertIn('/workspaces/demo/demo', args)
        self.assertIn(self.first.container, args)
        (self.first.path / 'environment.json').unlink()
        with self.assertRaises(FileNotFoundError):
            exec_args(self.path, 'php', ['php'])

    def test_bindings_reject_corrupt_identity(self):
        atomic_write(self.path / '.phpbox/project.json', '{"environment_id":"../wrong"}')
        with self.assertRaises(ValueError):
            read_binding(self.path)

    def test_switch_to_php72_ignores_composer_requirements(self):
        target = self.manager.create('PHP 7.2', '7.2', [])
        composer = self.path / 'demo/composer.json'
        lock = self.path / 'demo/composer.lock'
        requirements = {'php': '^8.4', 'ext-missing': '*'}
        composer.write_text(json.dumps({'require': requirements}))
        for locked in (False, True):
            with self.subTest(locked=locked):
                if locked:
                    lock.write_text(json.dumps({'packages': [], 'platform': requirements}))
                before = {file: file.read_bytes() for file in (composer, lock) if file.exists()}
                self.bind()
                rt = self.runtime()
                rt.manager.verify.return_value = {'version': '7.2.34', 'extensions': {}}
                def command(args):
                    self.assertNotIn('composer', ' '.join(args).lower())
                    return ''
                rt.manager.command.side_effect = command
                self.assertEqual(rt.check(target)['version'], '7.2.34')
                rt.switch(target)
                self.assertEqual(read_binding(self.path)['environment_id'], target.id)
                self.assertEqual({file: file.read_bytes() for file in before}, before)
                self.assertEqual(lock.exists(), locked)

    def test_migration_preserves_volume_identity_and_preview_aliases(self):
        rt = self.runtime()
        preview = rt.preview(self.second)
        rt.switch(self.second)
        compose = yaml.safe_load((self.path / 'docker-compose.yml').read_text())
        binding = read_binding(self.path)
        self.assertEqual(binding['id'], preview['project_id'])
        self.assertFalse(binding['enabled'])
        self.assertEqual(compose['name'], 'phpdev-original')
        self.assertEqual(compose['volumes']['mysql_data']['name'], 'original-mysql')
        self.assertNotIn('php', compose['services'])
        self.assertNotIn('cron', compose['services'])
        self.assertIn('mysql-' + binding['id'], compose['services']['mysql']['networks']['phpbox']['aliases'])
        managed_env = (self.path / '.env.phpbox').read_text()
        self.assertIn('DB_HOST=mysql-' + binding['id'], managed_env)
        self.assertIn('REDIS_HOST=redis-' + binding['id'], managed_env)
        self.assertTrue((self.path / '.phpbox/independent-backup.json').exists())
        self.assertEqual(ProjectManager.__new__(ProjectManager)._get_port(self.path), '18080')

    def test_reusing_renamed_directory_gets_a_new_project_identity(self):
        rt = ProjectRuntime(self.path)
        original = rt.preview(self.first)['project_id']
        self.assertEqual(original, rt.preview(self.first)['project_id'])
        (self.path / '.phpbox').rename(self.path / '.phpbox-renamed')
        self.assertNotEqual(original, rt.preview(self.first)['project_id'])

    def test_migration_accepts_legacy_proxy_helpers_in_place_or_appended(self):
        template = (self.path / 'Dockerfile').read_text()
        template = template.replace(EXTENSION_INSTALLER_COMMAND,
                                    'ADD ' + EXTENSION_INSTALLER_URL + ' /usr/local/bin/\nRUN chmod +x /usr/local/bin/install-php-extensions')
        template = template.replace('RUN cp /usr/local/etc/php/php.ini-development /usr/local/etc/php/php.ini\n', '')
        template = template.replace(' cron procps util-linux ', ' cron ')
        current = build_dockerfile_proxy_snippet('')
        for proxy in ('', 'http://127.0.0.1:7890', 'http://user:pass@172.17.0.1:7890'):
            with patch('core.proxy.get_host_ip_for_docker', return_value=None):
                block = build_shell_proxy_block(proxy)
            legacy = "# BEGIN_PHPBOX_PROXY_HELPERS\nRUN cat <<'EOF' >> /home/user/.zshrc\n" + block + '\nEOF\n# END_PHPBOX_PROXY_HELPERS'
            for appended in (False, True):
                with self.subTest(proxy=proxy, appended=appended):
                    content = (template.replace(current, '') + '\n' + legacy + '\n' if appended
                               else template.replace(current, legacy))
                    (self.path / 'Dockerfile').write_text(content)
                    preview = ProjectRuntime(self.path).preview(self.second)
                    self.assertEqual(preview['extensions'], ['redis'])
                    self.assertEqual((self.path / 'Dockerfile').read_text(), content)
        self.runtime().switch(self.second)
        self.assertEqual(read_binding(self.path)['environment_id'], self.second.id)

    def test_migration_rejects_custom_commands_inside_proxy_helpers(self):
        template = (self.path / 'Dockerfile').read_text()
        current = build_dockerfile_proxy_snippet('')
        standard = build_shell_proxy_block('http://172.17.0.1:7890')
        for block in (standard.replace('curl ipinfo.io', 'curl custom.invalid'),
                      standard.replace('http://172.17.0.1:7890', 'http://172.17.0.1:7890; touch /custom'),
                      standard + '\ntouch /custom'):
            encoded = base64.b64encode(block.encode()).decode()
            for snippet in ("RUN cat <<'EOF' >> /home/user/.zshrc\n" + block + '\nEOF',
                            f"RUN echo '{encoded}' | base64 -d >> /home/user/.zshrc"):
                with self.subTest(snippet=snippet):
                    (self.path / 'Dockerfile').write_text(template.replace(current, snippet))
                    with self.assertRaisesRegex(ValueError, '代理助手'):
                        ProjectRuntime(self.path).preview(self.second)
                    self.assertFalse((self.path / '.phpbox/project.json').exists())

    def test_environment_regeneration_preserves_php_configuration(self):
        config = self.first.path / 'php/php.ini'
        config.write_text('memory_limit=512M\ndate.timezone=UTC\n')
        self.manager.generate_files(self.first)
        self.assertEqual(config.read_text(), 'memory_limit=512M\ndate.timezone=UTC\n')

    def test_environment_proxy_change_rebuilds_shell_helpers(self):
        with patch.object(self.manager, '_build') as build, patch.object(self.manager, 'running', return_value=False):
            self.manager.update(self.first, self.first.extensions, 'http://172.17.0.1:7890', 'memory_limit=128M\n')
        build.assert_called_once_with(self.first)
        self.assertEqual(self.manager.load(self.first.id).proxy, 'http://172.17.0.1:7890')

    def test_migration_rejects_custom_mounts_and_dependencies(self):
        file = self.path / 'docker-compose.yml'
        compose = yaml.safe_load(file.read_text())
        compose['services']['php']['volumes'].append('/etc:/custom')
        atomic_write(file, yaml.safe_dump(compose))
        with self.assertRaisesRegex(ValueError, '自定义挂载'):
            ProjectRuntime(self.path).preview(self.second)
        compose['services']['php']['volumes'].pop()
        atomic_write(file, yaml.safe_dump(compose))
        (self.path / 'Dockerfile').write_text('FROM php:8.4-fpm\nRUN apt-get install -y custom-package\n')
        with self.assertRaisesRegex(ValueError, '自定义系统包'):
            ProjectRuntime(self.path).preview(self.second)
        self.bind()
        conf = self.path / 'nginx/default.conf'
        conf.write_text(conf.read_text().replace('php:9000', 'custom-server:9000'))
        with self.assertRaisesRegex(ValueError, 'PHP 上游'):
            ProjectRuntime(self.path).preview(self.second)

    def test_ready_switch_does_not_recreate_php_and_rolls_back_on_sync_failure(self):
        self.bind()
        rt = self.runtime('nginx\n')
        rt.probe_route = Mock()
        rt._nginx = Mock()
        rt.manager.compose = Mock()
        before = (self.path / 'nginx/default.conf').read_text()
        rt.manager.sync_cron.side_effect = [RuntimeError('scheduler failure'), None, None]
        with self.assertRaisesRegex(RuntimeError, 'scheduler failure'):
            rt.switch(self.second)
        self.assertEqual(read_binding(self.path)['environment_id'], self.first.id)
        self.assertEqual((self.path / 'nginx/default.conf').read_text(), before)
        rt.manager.compose.assert_not_called()
        self.assertFalse((self.path / '.phpbox/switch.json').exists())

    def test_route_probe_reports_request_failures_and_cleans_up(self):
        self.bind()
        error = 'wget: server returned error: HTTP/1.1 502 Bad Gateway'
        with patch.object(DockerManager, '_run_command', return_value=DockerResult(False, error=error, raw_error=error)), patch('core.runtime.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, '502 Bad Gateway'):
                ProjectRuntime(self.path).probe_route(self.first)
        self.assertEqual(list((self.path / 'demo').glob('phpbox-probe-*.php')), [])

    def test_route_probe_rejects_a_response_from_the_wrong_environment(self):
        self.bind()
        def respond(args):
            token = args[-1].rsplit('phpbox-probe-', 1)[1][:-4]
            return DockerResult(True, token + ':' + self.second.container + ':8.2.30')
        with patch.object(DockerManager, '_run_command', side_effect=respond), patch('core.runtime.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, '目标 PHP 容器或版本不符'):
                ProjectRuntime(self.path).probe_route(self.first)
        self.assertEqual(list((self.path / 'demo').glob('phpbox-probe-*.php')), [])

    def test_failed_rollback_keeps_record_and_blocks_commands_until_recovery(self):
        self.bind()
        rt = self.runtime()
        rt.manager.sync_cron.side_effect = RuntimeError('scheduler failure')
        with self.assertRaisesRegex(RuntimeError, '恢复失败'):
            rt.switch(self.second)
        with self.assertRaisesRegex(RuntimeError, '切换尚未完成'):
            exec_args(self.path, 'php', ['php'])
        rt.manager.sync_cron.side_effect = None
        rt.recover()
        self.assertFalse((self.path / '.phpbox/switch.json').exists())
        self.assertEqual(read_binding(self.path)['environment_id'], self.first.id)

    def test_project_stop_keeps_shared_environment_running_and_status_stopped(self):
        self.bind()
        rt = self.runtime()
        rt.manager.compose = Mock()
        rt.lifecycle('stop')
        rt.manager.compose.assert_not_called()
        self.assertFalse(read_binding(self.path)['enabled'])
        model = Project('demo', self.path, php_running=True, cron_running=True, environment_id=self.first.id)
        self.assertEqual(model.status_text, '已停止')

    def test_operation_lock_rejects_concurrent_mutations(self):
        with operation_lock(self.path):
            with self.assertRaises(RuntimeError):
                ProjectRuntime(self.path).switch(self.second)
        with environment_locks([self.second, self.first, self.first]):
            with self.assertRaises(RuntimeError):
                self.manager.delete(self.first)

    def test_environment_delete_refuses_bindings(self):
        self.bind(enabled=False)
        with self.assertRaisesRegex(ValueError, '绑定'):
            self.manager.delete(self.first)
        self.assertTrue(self.first.path.exists())

    def test_active_task_from_previous_environment_blocks_project_removal(self):
        self.bind()
        atomic_write(self.path / 'demo/.phpbox/tasks/state/old-run.environment', self.second.id)
        with patch.object(self.manager, 'running', return_value=True), patch.object(self.manager, 'active_tasks', return_value='/workspaces/demo/demo/.phpbox/tasks/state/old-run.pid'):
            with self.assertRaisesRegex(RuntimeError, '原环境'):
                self.manager.assert_project_idle(self.path)

    def test_cron_aggregation_keeps_both_projects(self):
        self.bind()
        TaskManager([self.project]).save_task(task('demo'))
        other = self.projects / 'other'
        other.mkdir()
        write_binding(other, {'id': '2' * 32, 'environment_id': self.first.id, 'enabled': True})
        second = Project('other', other)
        TaskManager([second]).save_task(task('other'))
        with patch.object(self.manager, 'running', return_value=False):
            self.manager.sync_cron(self.first)
        content = (self.first.path / 'scheduler/cron').read_text()
        self.assertIn('/workspaces/demo/demo/.phpbox/tasks/run_task.sh', content)
        self.assertIn('/workspaces/other/other/.phpbox/tasks/run_task.sh', content)

    def test_shared_task_runner_rejects_stale_binding_and_records_execution_target(self):
        self.bind()
        manager = TaskManager([self.project])
        definition = task('demo')
        manager.save_task(definition)
        script = manager.get_runner_script(self.project).read_text()
        script = script.replace('/workspaces', str(self.projects)).replace('/phpbox/scheduler', str(self.first.path / 'scheduler'))
        script = script.replace('su -s /bin/sh "$TASK_USER" --session-command', 'sh -c')
        file = self.root / 'runner.sh'
        file.write_text(script)
        env = dict(os.environ, PHPBOX_ENVIRONMENT_ID=self.second.id)
        result = subprocess.run(['sh', str(file), definition.id], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(manager.get_task_log_files(self.project, definition.id), [])
        env['PHPBOX_ENVIRONMENT_ID'] = self.first.id
        result = subprocess.run(['sh', str(file), definition.id], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = manager.get_task_state(self.project, definition.id)
        self.assertEqual(state.environment_id, self.first.id)
        self.assertTrue(state.container_id)
        self.assertTrue(state.run_id)


if __name__ == '__main__':
    unittest.main()
