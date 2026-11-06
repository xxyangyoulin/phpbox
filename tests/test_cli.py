import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core import cli
from core.docker import DockerManager, DockerResult
from core.environment import EnvironmentManager, PhpEnvironment
from core.process import run_attached
from core.project import ProjectManager
from core.runtime import logs_args


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / 'projects'
        self.path = self.base / 'demo'
        self.code = self.path / 'demo'
        (self.code / 'sub').mkdir(parents=True)
        (self.path / 'docker-compose.yml').write_text('services:\n  php:\n    image: php:8.4-fpm\n  nginx:\n    image: nginx\n    ports:\n      - "8080:80"\n')
        (self.path / 'Dockerfile').write_text('FROM php:8.4-fpm\n')
        for target, value in (
            ('core.project.BASE_DIR', self.base), ('core.config.BASE_DIR', self.base),
            ('core.environment.BASE_DIR', self.base),
            ('core.environment.ENVIRONMENTS_DIR', Path(self.temp.name) / 'environments'),
            ('core.docker.DockerManager._compose_checked', True),
            ('core.docker.DockerManager._compose_cmd', ['docker', 'compose']),
        ):
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch('core.project.ensure_base_dir')
        p.start()
        self.addCleanup(p.stop)
        cwd = Path.cwd()
        os.chdir(self.base.parent)
        self.addCleanup(os.chdir, cwd)

    def invoke(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.run_cli(cli.parse_args(argv))
        return code, out.getvalue(), err.getvalue()

    def test_forwarded_arguments_are_unchanged(self):
        cases = [
            ('php', ['-r', 'echo "hello world";', '', '$HOME', 'a;b']),
            ('php', ['-d', 'memory_limit=1G', '-r', 'echo 1;']),
            ('composer', ['--working-dir', 'directory with spaces', 'install']),
            ('artisan', ['--env=testing', 'migrate']), ('think', ['--help']),
        ]
        for command, argv in cases:
            for separator in ([], ['--']):
                with self.subTest(command=command, separator=separator):
                    args = cli.parse_args(['-p', 'demo', command] + separator + argv)
                    self.assertEqual(args.args, argv)
                    with patch('core.process.run_attached', return_value=7) as run:
                        self.assertEqual(cli.dispatch(args), 7)
                    executed = run.call_args.args[0]
                    prefix = ['php', command] if command in ('artisan', 'think') else [command]
                    self.assertEqual(executed[-len(prefix + argv):], prefix + argv)

    def test_project_and_directory_selection_and_framework_workdir(self):
        with patch('core.process.run_attached', return_value=0) as run:
            cli.dispatch(cli.parse_args(['-C', str(self.code / 'sub'), 'php', '-v']))
            command = run.call_args.args[0]
            self.assertEqual(command[command.index('-w') + 1], '/var/www/html/sub')
            cli.dispatch(cli.parse_args(['artisan', 'migrate']))
            command = run.call_args.args[0]
            self.assertEqual(command[command.index('-w') + 1], '/var/www/html')
        code, _, error = self.invoke(['status', 'demo', '-p', 'other'])
        self.assertEqual(code, 1)
        self.assertIn('不一致', error)

    def test_project_lookup_does_not_scan_or_query_docker_for_exec(self):
        with patch.object(ProjectManager, 'get_all_projects', side_effect=AssertionError('scanned')), \
             patch('core.project.subprocess.run', side_effect=AssertionError('queried Docker')), \
             patch('core.process.run_attached', return_value=0):
            self.assertEqual(cli.dispatch(cli.parse_args(['-p', 'demo', 'php', '-v'])), 0)

    def test_tty_redirect_and_explicit_overrides(self):
        for options, stdin, stdout, tty in (([], True, False, False), ([], False, True, False),
                                            ([], True, True, True), (['-T'], True, True, False),
                                            (['-t'], False, False, True)):
            with self.subTest(options=options, stdin=stdin, stdout=stdout), \
                 patch.object(sys.stdin, 'isatty', return_value=stdin), \
                 patch.object(sys.stdout, 'isatty', return_value=stdout), \
                 patch('core.process.run_attached', return_value=0) as run:
                cli.dispatch(cli.parse_args(['-p', 'demo'] + options + ['php', '-v']))
                self.assertEqual(run.call_args.kwargs['tty'], tty)
                self.assertEqual('-T' in run.call_args.args[0], not tty)

    def test_exec_options_and_empty_command_error(self):
        with patch('core.process.run_attached', return_value=23) as run:
            code = cli.dispatch(cli.parse_args(['-p', 'demo', 'exec', '-T', '-u', '123:456', '-w', '/tmp', 'php', '--', 'printf', '%s', '']))
        self.assertEqual(code, 23)
        command = run.call_args.args[0]
        self.assertEqual(command[-3:], ['printf', '%s', ''])
        self.assertIn('123:456', command)
        self.assertIn('/tmp', command)
        for argv in (['exec', 'php'], ['exec', 'php', '--'], ['shell', '-w', 'relative'],
                     ['--hide', 'list'], ['list', '--json', '-q'], ['status', 'demo', '--all']):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                cli.parse_args(argv)
            self.assertEqual(exc.exception.code, 2)

    def test_json_status_marks_docker_failure_unknown_and_fails(self):
        result = subprocess.CompletedProcess([], 1, '', 'Cannot connect to Docker daemon')
        with patch('core.project.subprocess.run', return_value=result):
            code, output, error = self.invoke(['status', 'demo', '--json'])
        self.assertEqual(code, 1)
        data = json.loads(output)
        self.assertEqual(data['status'], 'unknown')
        self.assertIsNone(data['services']['php'])
        self.assertIn('Docker daemon', error)

    def test_stopped_status_only_fails_when_check_requested(self):
        with patch('core.project.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            self.assertEqual(self.invoke(['status', 'demo'])[0], 0)
            self.assertEqual(self.invoke(['status', 'demo', '--check'])[0], 1)

    def test_running_but_unhealthy_fails_health_check(self):
        output = 'phpdev-demo-php\tUp 1 hour (unhealthy)\nphpdev-demo-nginx\tUp 1 hour\n'
        with patch('core.project.subprocess.run', return_value=subprocess.CompletedProcess([], 0, output, '')):
            code, result, _ = self.invoke(['status', 'demo', '--check', '--json'])
        self.assertEqual(code, 1)
        data = json.loads(result)
        self.assertEqual(data['status'], 'partial')
        self.assertIn('php', data['error'])

    def test_names_are_metadata_only(self):
        with patch('core.project.subprocess.run', side_effect=AssertionError('queried Docker')):
            code, output, error = self.invoke(['list', '-q'])
        self.assertEqual((code, output, error), (0, 'demo\n', ''))

    def test_doctor_missing_compose_returns_failure_with_valid_json(self):
        def result(command, **kwargs):
            if command[-1] == 'version':
                return subprocess.CompletedProcess(command, 1, '', 'Compose missing')
            return subprocess.CompletedProcess(command, 0, 'Docker available', '')
        with patch('shutil.which', return_value='/usr/bin/docker'), patch('core.cli.subprocess.run', side_effect=result):
            code, output, error = self.invoke(['doctor', '--json'])
        self.assertEqual(code, 1)
        data = json.loads(output)
        self.assertFalse(data['ok'])
        self.assertFalse(next(check for check in data['checks'] if check['name'] == 'compose')['ok'])
        self.assertIn('compose', error)

    def test_restart_keeps_containers_and_recreate_applies_images(self):
        docker = DockerManager(self.path)
        with patch.object(docker, '_run_command', return_value=DockerResult(True)) as run:
            self.assertTrue(docker.restart().success)
            self.assertEqual(run.call_args.args[0], ['restart'])
            self.assertTrue(docker.recreate().success)
            self.assertEqual(run.call_args.args[0], ['up', '-d', '--no-build', '--force-recreate'])

    def test_log_defaults_and_options(self):
        args = cli.parse_args(['logs'])
        self.assertFalse(args.follow)
        self.assertEqual(args.tail, '200')
        command = logs_args(self.path, 'cron', True, 'all', '1h', True, True)
        self.assertEqual(command, ['docker', 'compose', 'logs', '-f', '--tail', 'all', '--since', '1h', '--timestamps', '--no-color', 'cron'])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.parse_args(['logs', '--tail', '-1'])

    def test_shared_logs_include_project_and_environment(self):
        env = SimpleNamespace(name='php84')
        project = SimpleNamespace(path=self.path)
        with patch('core.environment.read_binding', return_value={'environment_id': 'a' * 32}), \
             patch.object(EnvironmentManager, 'load', return_value=env), \
             patch('core.runtime.logs_args', side_effect=lambda path, service, *args: [sys.executable, '-c', 'print(' + repr(service or 'nginx') + ')']) as commands:
            args = cli.parse_args(['logs'])
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(cli._run_logs(args, project), 0)
        self.assertEqual(set(out.getvalue().splitlines()), {'nginx', 'php'})
        self.assertEqual([call.args[1] for call in commands.call_args_list], [None, 'php'])
        self.assertIn('共享环境', err.getvalue())

    def test_environment_confirm_and_unique_names(self):
        env = PhpEnvironment('a' * 32, 'php84', '8.4', [])
        with patch.object(EnvironmentManager, 'list', return_value=[env]), \
             patch.object(EnvironmentManager, 'bindings', return_value=[self.path]), \
             patch.object(EnvironmentManager, 'stop') as stop, patch.object(sys.stdin, 'isatty', return_value=False):
            code, _, error = self.invoke(['env', 'stop', 'php84'])
            self.assertEqual(code, 1)
            self.assertIn('--yes', error)
            stop.assert_not_called()
            self.assertEqual(self.invoke(['env', 'stop', 'php84', '--yes'])[0], 0)
            stop.assert_called_once_with(env)
        manager = Mock()
        manager.list.return_value = [env, PhpEnvironment('b' * 32, 'php84', '8.4', [])]
        with self.assertRaisesRegex(ValueError, '不唯一'):
            cli._environment(manager, 'php84')
        self.assertEqual(cli._environment(manager, 'a' * 32), env)

    def test_environment_query_never_exposes_proxy_credentials(self):
        env = PhpEnvironment('a' * 32, 'php84', '8.4', ['redis'], 'http://secret:password@proxy:7890')
        with patch.object(EnvironmentManager, 'list', return_value=[env]), \
             patch.object(EnvironmentManager, 'bindings', return_value=[self.path]), patch('core.cli._docker_running', return_value={env.container}):
            code, output, _ = self.invoke(['env', 'inspect', 'php84', '--json'])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output)['proxy_configured'])
        self.assertNotIn('secret', output)
        self.assertNotIn('password', output)

    def test_environment_build_uses_cache_option_and_create_uses_standard_builder(self):
        env = PhpEnvironment('a' * 32, 'php84', '8.4', ['redis'])
        with patch('core.cli._environment', return_value=env), \
             patch.object(EnvironmentManager, 'bindings', return_value=[]), \
             patch.object(EnvironmentManager, 'build') as build, \
             patch.object(EnvironmentManager, 'create', return_value=env) as create, \
             patch.object(EnvironmentManager, 'start') as start:
            self.assertEqual(self.invoke(['env', 'rebuild', 'php84', '--no-cache'])[0], 0)
            build.assert_called_once_with(env, no_cache=True)
            self.assertEqual(self.invoke(['env', 'create', 'php84', '--php', '8.4', '--extension', 'redis', '--start'])[0], 0)
            create.assert_called_once_with('php84', '8.4', ['redis'], '')
            start.assert_called_once_with(env)

    def test_use_check_does_not_switch_and_downgrade_uses_existing_runtime(self):
        env = PhpEnvironment('a' * 32, 'php72', '7.2', [])
        with patch.object(EnvironmentManager, 'list', return_value=[env]), patch('core.runtime.ProjectRuntime') as factory:
            runtime = factory.return_value
            runtime.preview.return_value = {'php': '7.2'}
            self.assertEqual(self.invoke(['-p', 'demo', 'use', 'php72', '--check', '--json'])[0], 0)
            runtime.check.assert_called_once_with(env)
            runtime.switch.assert_not_called()
            self.assertEqual(self.invoke(['-p', 'demo', 'use', 'php72'])[0], 0)
            runtime.switch.assert_called_once_with(env)

    def test_signal_exit_codes_without_tracebacks(self):
        for error, expected in ((KeyboardInterrupt(), 130), (cli.Terminated(), 143)):
            with patch('core.cli.dispatch', side_effect=error):
                code, output, err = self.invoke(['list'])
            self.assertEqual(code, expected)
            self.assertNotIn('Traceback', err)
        with patch('core.cli.dispatch', return_value=-15):
            self.assertEqual(self.invoke(['list'])[0], 143)

    def test_attached_child_is_reaped_after_interrupt(self):
        process = Mock()
        process.wait.side_effect = [KeyboardInterrupt(), 0]
        process.poll.return_value = None
        process.pid = 98765
        with patch('core.process.subprocess.Popen', return_value=process), patch('core.process.os.killpg') as kill:
            with self.assertRaises(KeyboardInterrupt):
                run_attached(['example'])
            kill.assert_called_once_with(98765, signal.SIGTERM)
            self.assertEqual(process.wait.call_count, 2)

    def test_complete_help_covers_every_command_and_default(self):
        parser = cli.build_parser()
        for name, child in cli._children(parser).items():
            self.assertTrue(child.description, name)
            self.assertTrue(child.epilog, name)
            for subname, sub in cli._children(child).items():
                self.assertIn('示例', sub.epilog, name + ' ' + subname)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
            cli.parse_args(['help', '--all'])
        self.assertEqual(stopped.exception.code, 0)
        text = output.getvalue()
        for value in ('env create', '--extension', '--proxy', '--no-cache', '--tail', '--since', '--check',
                      '--workdir', '--user', 'composer.json', '容器可写层', '130', 'recreate'):
            self.assertIn(value, text)


class CliEntrypointTests(unittest.TestCase):
    def test_help_and_version_need_no_qt_or_docker(self):
        root = Path(__file__).resolve().parents[1]
        code = '''import runpy, sys
class DenyImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('PyQt6', 'qfluentwidgets', 'core.project', 'core.logger', 'core.docker')):
            raise AssertionError('unexpected import: ' + fullname)
sys.meta_path.insert(0, DenyImports())
sys.argv = ['pbox', sys.argv[1]]
runpy.run_path('main.py', run_name='__main__')
'''
        for arg in ('--help', '--version'):
            result = subprocess.run([sys.executable, '-c', code, arg], cwd=str(root), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(result.stderr)

    def test_pipe_closure_has_no_python_traceback(self):
        root = Path(__file__).resolve().parents[1]
        code = '''import sys
from unittest.mock import patch
from core import cli
def output(args):
    for i in range(10000):
        print('line ' + str(i), flush=True)
    return 0
with patch.object(cli, 'dispatch', side_effect=output):
    sys.exit(cli.run_cli(cli.parse_args(['list'])))
'''
        process = subprocess.Popen([sys.executable, '-c', code], cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertTrue(process.stdout.readline())
            process.stdout.close()
            process.wait(timeout=5)
            err = process.stderr.read()
            self.assertEqual(process.returncode, 141, err)
            self.assertNotIn(b'Traceback', err)
            self.assertNotIn(b'Exception ignored', err)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
            process.stderr.close()

    def test_attached_command_preserves_input_streams_and_exit_status(self):
        root = Path(__file__).resolve().parents[1]
        code = '''import sys
from core.process import run_attached
child = "import sys; print(sys.stdin.read(), end=''); print('diagnostic', file=sys.stderr); sys.exit(23)"
sys.exit(run_attached([sys.executable, '-c', child]))
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=str(root), input='input data\n', capture_output=True, text=True)
        self.assertEqual(result.returncode, 23)
        self.assertEqual(result.stdout, 'input data\n')
        self.assertEqual(result.stderr, 'diagnostic\n')

    def test_real_sigterm_reaps_attached_child(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / 'pid'
            code = '''import sys
from pathlib import Path
from unittest.mock import patch
from core import cli
from core.process import run_attached
child = "import os, time; from pathlib import Path; Path(" + repr(sys.argv[1]) + ").write_text(str(os.getpid())); time.sleep(60)"
with patch.object(cli, 'dispatch', side_effect=lambda args: run_attached([sys.executable, '-c', child])):
    sys.exit(cli.run_cli(cli.parse_args(['list'])))
'''
            process = subprocess.Popen([sys.executable, '-c', code, str(pid_file)], cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                import time
                deadline = time.monotonic() + 5
                while not pid_file.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(pid_file.exists())
                child = int(pid_file.read_text())
                process.send_signal(signal.SIGTERM)
                _, err = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 143, err)
                self.assertNotIn(b'Traceback', err)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child, 0)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()


if __name__ == '__main__':
    unittest.main()
