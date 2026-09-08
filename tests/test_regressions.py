import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from core.docker import DockerManager, DockerResult
from core.process import run_process
from core.project import Project, ProjectManager, get_project_code_path
from core.proxy import build_shell_proxy_block, convert_proxy_for_docker, validate_proxy_url
from core.tasks import TaskDefinition, TaskManager
from ui.dialogs.create_project import CreateProjectDialog
from ui.dialogs.php_config_dialog import PhpConfigDialog
from ui.dialogs.task_center import TaskRuntimeWorker
from ui.main_window import ProjectDashboardPage

APP = QApplication.instance() or QApplication([])


def task(project='old', enabled=True):
    return TaskDefinition('abc123', 'test', project, '自定义', '', '* * * * *',
                          'root', 'printf hello', enabled, '', '')


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.old = self.root / 'old'
        (self.old / 'old').mkdir(parents=True)
        (self.old / 'old' / 'index.php').write_text('source')
        (self.old / 'docker-compose.yml').write_text('name: phpdev-old\nservices:\n  php:\n    container_name: phpdev-old-php\n    volumes:\n      - ./old:/var/www/html\nvolumes:\n  mysql_data:\n')
        self.project = Project('old', self.old)
        self.manager = ProjectManager.__new__(ProjectManager)
        self.base = patch('core.project.BASE_DIR', self.root)
        self.base.start()
        self.addCleanup(self.base.stop)

    def test_rename_preserves_volume_identity_and_moves_code_tasks(self):
        TaskManager([self.project]).save_task(task())
        with patch('core.project.DockerManager') as factory:
            factory.return_value._run_command.return_value = DockerResult(True, '')
            factory.return_value.down.return_value = DockerResult(True)
            self.assertTrue(self.manager.rename_project(self.project, 'new'))
        renamed = Project('new', self.root / 'new')
        self.assertTrue((get_project_code_path(renamed.path, 'new') / 'index.php').exists())
        text = (renamed.path / 'docker-compose.yml').read_text()
        self.assertIn('name: phpdev-old\n', text)
        self.assertIn('container_name: phpdev-new-php', text)
        self.assertIn('./new:/var/www/html', text)
        self.assertEqual(len(TaskManager([renamed]).load_all_tasks()), 1)

    def test_rename_rolls_back_on_start_failure(self):
        original = (self.old / 'docker-compose.yml').read_bytes()
        with patch('core.project.DockerManager') as factory:
            factory.return_value.down.return_value = DockerResult(True)
            factory.return_value._run_command.side_effect = [DockerResult(True, 'php\n'), DockerResult(False, error='failed'), DockerResult(True)]
            self.assertFalse(self.manager.rename_project(self.project, 'new'))
        self.assertEqual((self.old / 'docker-compose.yml').read_bytes(), original)
        self.assertTrue((self.old / 'old' / 'index.php').exists())

    def test_delete_failure_keeps_source(self):
        with patch('core.project.DockerManager') as factory:
            factory.return_value._run_command.return_value = DockerResult(False, error='down failed')
            self.assertFalse(self.manager.delete_project(self.project))
        self.assertTrue((self.old / 'old' / 'index.php').exists())

    def test_delete_success(self):
        with patch('core.project.DockerManager') as factory:
            factory.return_value._run_command.return_value = DockerResult(True)
            self.assertTrue(self.manager.delete_project(self.project))
        self.assertFalse(self.old.exists())


class ProcessTests(unittest.TestCase):
    def test_cancel_silent_process(self):
        event = threading.Event()
        timer = threading.Timer(0.15, event.set)
        timer.start()
        start = time.monotonic()
        with self.assertRaises(InterruptedError):
            run_process([sys.executable, '-c', 'import time; time.sleep(30)'], cancel=event)
        timer.join()
        self.assertLess(time.monotonic() - start, 2)

    def test_output_is_bounded_and_stderr_consumed(self):
        result = run_process([sys.executable, '-c', "import sys; sys.stderr.write('x'*2000000)"])
        self.assertEqual(result.returncode, 0)
        self.assertLessEqual(len(result.stdout), 1048576)

    def test_timeout(self):
        with self.assertRaises(TimeoutError):
            run_process([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=.1)


class BoundaryTests(unittest.TestCase):
    def test_cron(self):
        for expression in ['* * * * *', '*/5 0-23 1,15 jan mon-fri', '0 0 1 12 7']:
            self.assertTrue(TaskManager.is_valid_cron_expression(expression), expression)
        for expression in ['99 99 99 99 99', '*/0 * * * *', '* * * *', '* * * * *\n', '0 0 0 0 0', '0 0 * * 9', '1-0 * * * *']:
            self.assertFalse(TaskManager.is_valid_cron_expression(expression), expression)

    def test_compose_password_roundtrip(self):
        for password in ['abc # def', 'a: b', '123456', 'pa$WORD', 'x"y', 'a\nb']:
            config = dict(port=3306, database='db', user='app', password=password, root_password=password)
            text = CreateProjectDialog.generate_compose(None, 'demo', 8080, '', 'demo', config, None)
            scalar = re.search(r'      MYSQL_PASSWORD: (.*)', text).group(1)
            self.assertEqual(json.loads(scalar).replace('$$', '$'), password)

    def test_proxy_is_quoted_and_conversion_only_changes_host(self):
        url = 'http://user:pa$(printf_injection)@example.com:8080'
        script = build_shell_proxy_block(url) + '\nproxy >/dev/null\nprintf "%s" "$http_proxy"'
        result = subprocess.run(['sh', '-c', script], capture_output=True, text=True)
        self.assertEqual(result.stdout, url)
        with patch('core.proxy.get_host_ip_for_docker', return_value='172.17.0.1'):
            self.assertEqual(convert_proxy_for_docker('http://localhost:secret@127.0.0.1:80'), 'http://localhost:secret@172.17.0.1:80')
        for url in ['http://host:99999', 'http://host name:80', 'file:///tmp/a', 'http://host\n:80']:
            with self.assertRaises(ValueError):
                validate_proxy_url(url)

    def test_php_config_valid_constants_and_limits(self):
        with patch('ui.dialogs.php_config_dialog.DockerManager'):
            dialog = PhpConfigDialog(Path('/tmp'), 'demo', {})
        dialog.inputs['memory_limit'].setText('-1')
        dialog.inputs['post_max_size'].setText('0')
        dialog.inputs['upload_max_filesize'].setText('2M')
        for value in ['E_ALL', 'E_ALL & ~E_NOTICE', '32767']:
            dialog.inputs['error_reporting'].setText(value)
            self.assertTrue(dialog.validate_input()[0], value)
        for value in ['E_BOGUS', '__import__("os")', 'E_ALL &']:
            dialog.inputs['error_reporting'].setText(value)
            self.assertFalse(dialog.validate_input()[0], value)

    def test_stale_php_info_is_ignored(self):
        page = SimpleNamespace(current_project=SimpleNamespace(path=Path('/b'), is_running=True), _php_info_request=2, dashboard=Mock())
        ProjectDashboardPage._on_php_info_loaded(page, '/a', 1, {'memory_limit': 'wrong'})
        ProjectDashboardPage._on_php_info_loaded(page, '/b', 1, {'memory_limit': 'old'})
        page.dashboard.update_php_info.assert_not_called()
        ProjectDashboardPage._on_php_info_loaded(page, '/b', 2, {'memory_limit': 'correct'})
        page.dashboard.update_php_info.assert_called_once_with({'memory_limit': 'correct'})


class TaskTests(unittest.TestCase):
    def test_disable_reload_failure_is_reported(self):
        project = Project('old', Path('/tmp/old'))
        worker = TaskRuntimeWorker([project], 'old', 'disable', task_id='abc123')
        results = []
        worker.task_finished.connect(lambda *args: results.append(args))
        with patch('ui.dialogs.task_center.TaskManager') as manager, patch('ui.dialogs.task_center.DockerManager'), patch.object(worker, '_sync_existing', side_effect=RuntimeError('reload failed')):
            manager.return_value.get_project.return_value = project
            worker.run()
            manager.return_value.set_task_enabled.assert_called_once_with('abc123', False)
        self.assertFalse(results[0][1])
        self.assertIn('reload failed', results[0][2])

    def test_move_syncs_both_projects(self):
        projects = [Project('old', Path('/tmp/old')), Project('new', Path('/tmp/new'))]
        worker = TaskRuntimeWorker(projects, 'new', 'save', task=task('new', False), original_project_name='old')
        with patch('ui.dialogs.task_center.TaskManager') as manager, patch('ui.dialogs.task_center.DockerManager'), patch.object(worker, '_sync_existing') as sync:
            manager.return_value.get_project.side_effect = lambda name: projects[0 if name == 'old' else 1]
            worker.run()
            self.assertEqual(sync.call_count, 2)

    @unittest.skipUnless(shutil.which('php') and shutil.which('flock'), 'PHP and flock required')
    def test_runner_multiline_disabled_and_unique_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = Project('demo', root)
            code = root / 'demo'
            code.mkdir()
            manager = TaskManager([project])
            definition = task('demo')
            definition.command = '# comment\nprintf "hello\\n"\nprintf "world\\n"'
            manager.save_task(definition)
            runner = manager.build_runner_script_content().replace('/var/www/html', str(code)).replace('su -s /bin/sh "$TASK_USER" --session-command', 'sh -c')
            file = root / 'runner.sh'
            file.write_text(runner)
            for _ in range(2):
                result = subprocess.run(['sh', str(file), definition.id], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            logs = manager.get_task_log_files(project, definition.id)
            self.assertEqual(len(logs), 2)
            self.assertIn('hello\nworld', logs[0].read_text())
            manager.set_task_enabled(definition.id, False)
            result = subprocess.run(['sh', str(file), definition.id], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(manager.get_task_log_files(project, definition.id)), 2)



class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        script = Path('install.sh').read_text()
        script = script.replace('/opt', str(self.root / 'opt')).replace('/usr/local', str(self.root / 'local')).replace('/usr/share', str(self.root / 'share'))
        self.script = self.root / 'install.sh'
        self.script.write_text(script)
        for relative in ['opt/phpbox', 'local/bin', 'share/applications', 'bin', 'dist/phpbox/_internal']:
            (self.root / relative).mkdir(parents=True)
        (self.root / 'opt/phpbox/old').write_text('old installation')
        self.binary = self.root / 'dist/phpbox/phpbox'
        self.binary.write_text('#!/bin/sh\nexit 0\n')
        self.binary.chmod(0o755)
        (self.root / 'phpbox.desktop').write_text('[Desktop Entry]\nName=phpbox\n')
        sudo = self.root / 'bin/sudo'
        sudo.write_text('#!/bin/sh\nif [ "$PHPBOX_TEST_FAIL_COPY" = 1 ] && [ "$1" = cp ]; then exit 1; fi\nexec "$@"\n')
        sudo.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root / 'bin') + ':' + os.environ['PATH'])

    def test_missing_binary_keeps_old_installation(self):
        self.binary.unlink()
        result = subprocess.run(['bash', str(self.script), 'install'], env=self.env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.root / 'opt/phpbox/old').exists())

    def test_copy_failure_rolls_back(self):
        self.env['PHPBOX_TEST_FAIL_COPY'] = '1'
        result = subprocess.run(['bash', str(self.script), 'install'], env=self.env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.root / 'opt/phpbox/old').exists(), result.stderr)
        self.assertFalse(list((self.root / 'opt').glob('.phpbox-*')))

    def test_complete_installation(self):
        result = subprocess.run(['bash', str(self.script), 'install'], env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / 'opt/phpbox/_internal').is_dir())
        self.assertFalse((self.root / 'opt/phpbox/old').exists())
        self.assertFalse(list((self.root / 'opt').glob('.phpbox-*')))


class MoreTaskTests(unittest.TestCase):
    def test_task_move_write_failure_keeps_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            projects = [Project('old', root / 'old'), Project('new', root / 'new')]
            manager = TaskManager(projects)
            definition = task()
            manager.save_task(definition)
            definition.project_name = 'new'
            with patch.object(manager, 'write_generated_cron', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    manager.save_task(definition, 'old')
            self.assertEqual(len(manager.load_project_tasks(projects[0])), 1)
            self.assertEqual(manager.load_project_tasks(projects[1]), [])

    def test_corrupt_task_file_is_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Project('old', Path(tmp))
            manager = TaskManager([project])
            manager.ensure_project_task_dirs(project)
            file = manager.get_tasks_file(project)
            file.write_text('{broken')
            with self.assertRaises(ValueError):
                manager.save_task(task())
            self.assertEqual(file.read_text(), '{broken')

    def test_log_read_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Project('old', Path(tmp))
            manager = TaskManager([project])
            logs = manager.get_logs_dir(project) / 'abc123'
            logs.mkdir(parents=True)
            (logs / 'a.log').write_bytes(b'x' * 200000 + b'end')
            result = manager.read_recent_task_logs(project, 'abc123')
            self.assertLess(len(result), 66000)
            self.assertTrue(result.endswith('end'))

    @unittest.skipUnless(shutil.which('php') and shutil.which('flock'), 'PHP and flock required')
    def test_task_overlap_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = Project('old', root)
            manager = TaskManager([project])
            definition = task()
            definition.command = 'touch started; sleep 0.4; printf done'
            manager.save_task(definition)
            code = root / 'old'
            runner = manager.build_runner_script_content().replace('/var/www/html', str(code)).replace('su -s /bin/sh "$TASK_USER" --session-command', 'sh -c')
            file = root / 'runner.sh'
            file.write_text(runner)
            first = subprocess.Popen(['sh', str(file), definition.id], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 3
                while not (code / 'started').exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue((code / 'started').exists())
                second = subprocess.run(['sh', str(file), definition.id], capture_output=True, text=True)
                self.assertIn('跳过', second.stdout)
                self.assertEqual(first.wait(timeout=3), 0)
                self.assertEqual(len(manager.get_task_log_files(project, definition.id)), 1)
            finally:
                if first.poll() is None:
                    first.kill()
                first.communicate()


class UiResponsivenessTests(unittest.TestCase):
    def test_background_operation_does_not_block_timer(self):
        from PyQt6.QtCore import QTimer
        from ui.worker import OperationWorker
        result = []
        ticks = []
        worker = OperationWorker(lambda: time.sleep(.15))
        worker.succeeded.connect(lambda value: result.append(True))
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(10)
        worker.start()
        deadline = time.monotonic() + 2
        while not result and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(.002)
        timer.stop()
        self.assertTrue(result)
        self.assertGreater(len(ticks), 5)

    def test_close_requests_cancel_without_waiting(self):
        from ui.styles import FluentDialog
        dialog = FluentDialog()
        worker = Mock()
        worker.isRunning.return_value = True
        dialog.worker = worker
        start = time.monotonic()
        dialog.reject()
        self.assertLess(time.monotonic() - start, .05)
        worker.stop.assert_called_once()
        worker.wait.assert_not_called()
        worker.isRunning.return_value = False
        dialog.reject()


if __name__ == '__main__':
    unittest.main()
