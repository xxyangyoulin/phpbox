import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from core.docker import DockerResult
from core.project import Project
from ui.dialogs.environment_diagnostics import EnvironmentDiagnosticsDialog
from ui.main_window import MainWindow


APP = QApplication.instance() or QApplication([])


class BackgroundUiTests(unittest.TestCase):
    def assert_ui_responds(self):
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        APP.processEvents()
        self.assertEqual(ticks, [True])

    def test_diagnostics_runs_in_background_and_can_close_while_waiting(self):
        entered, release = threading.Event(), threading.Event()
        thread_ids = []

        def collect():
            thread_ids.append(threading.get_ident())
            entered.set()
            release.wait(3)
            return [('Docker 命令', '正常 · docker')]

        with patch('ui.dialogs.environment_diagnostics.collect_environment_diagnostics', side_effect=collect) as check, \
                patch('ui.dialogs.environment_diagnostics.detect_system_proxy', return_value=None) as proxy, \
                patch('ui.dialogs.environment_diagnostics.Settings') as settings:
            settings.return_value.get_proxy.return_value = None
            settings.return_value.get_theme.return_value = 'light'
            dialog = EnvironmentDiagnosticsDialog()
            self.addCleanup(dialog.deleteLater)
            worker = dialog.diagnostics_worker
            try:
                self.assertTrue(entered.wait(1))
                self.assertNotEqual(thread_ids[0], threading.get_ident())
                dialog.show()
                self.assert_ui_responds()
                self.assertFalse(dialog.refresh_btn.isEnabled())
                self.assertFalse(dialog.copy_btn.isEnabled())
                dialog.refresh_diagnostics()
                check.assert_called_once()
                dialog.reject()
                self.assertFalse(dialog.isVisible())
                self.assertTrue(dialog._checking)
            finally:
                release.set()
                worker.wait(3000)
                APP.processEvents()
            self.assertFalse(dialog._checking)
            self.assertTrue(dialog.refresh_btn.isEnabled())
            self.assertTrue(dialog.copy_btn.isEnabled())
            self.assertIn('项状态正常', dialog.summary_label.text())
            proxy.assert_called_once()

    def test_failed_diagnostics_can_retry(self):
        with patch('ui.dialogs.environment_diagnostics.collect_environment_diagnostics', side_effect=RuntimeError('failed')) as check, \
                patch('ui.dialogs.environment_diagnostics.detect_system_proxy', return_value=None), \
                patch('ui.dialogs.environment_diagnostics.Settings') as settings:
            settings.return_value.get_proxy.return_value = None
            settings.return_value.get_theme.return_value = 'light'
            dialog = EnvironmentDiagnosticsDialog()
            self.addCleanup(dialog.deleteLater)
            dialog.diagnostics_worker.wait(3000)
            APP.processEvents()
            self.assertFalse(dialog._checking)
            self.assertTrue(dialog.refresh_btn.isEnabled())
            self.assertFalse(dialog.copy_btn.isEnabled())
            self.assertIn('检查失败', dialog.summary_label.text())
            check.side_effect = None
            check.return_value = [('Docker 命令', '正常')]
            dialog.refresh_diagnostics()
            dialog.diagnostics_worker.wait(3000)
            APP.processEvents()
            self.assertTrue(dialog.copy_btn.isEnabled())
            self.assertIn('项状态正常', dialog.summary_label.text())

    def test_batch_queries_and_port_checks_do_not_block_or_repeat(self):
        query_entered, query_release = threading.Event(), threading.Event()
        port_entered, port_release = threading.Event(), threading.Event()
        thread_ids = []
        project = Project('demo', Path('/nonexistent/demo'), port='8080')

        def projects():
            thread_ids.append(threading.get_ident())
            query_entered.set()
            query_release.wait(3)
            return [project]

        def port(*args, **kwargs):
            thread_ids.append(threading.get_ident())
            port_entered.set()
            port_release.wait(3)
            return None

        with patch('ui.main_window.ProjectManager') as manager, \
                patch('ui.main_window.DockerManager') as docker, \
                patch('ui.main_window.get_port_usage', side_effect=port), \
                patch.object(MainWindow, 'load_projects'), patch.object(MainWindow, 'setup_tray'), \
                patch.object(MainWindow, '_notify'), patch('ui.main_window.QTimer'):
            manager.return_value.get_all_projects.side_effect = projects
            docker.return_value.up.return_value = DockerResult(True)
            window = MainWindow()
            self.addCleanup(window.deleteLater)
            window.start_all_projects()
            worker = window.batch_worker
            cancel = worker.cancel_event
            try:
                self.assertTrue(query_entered.wait(1))
                self.assert_ui_responds()
                self.assertTrue(window._batch_busy)
                self.assertTrue(all(not action.isEnabled() for action in window._batch_actions))
                window.start_all_projects()
                window.stop_all_projects()
                manager.return_value.get_all_projects.assert_called_once()
                query_release.set()
                self.assertTrue(port_entered.wait(1))
                self.assert_ui_responds()
                docker.assert_not_called()
            finally:
                query_release.set()
                port_release.set()
                worker.wait(3000)
                APP.processEvents()
            self.assertTrue(all(value != threading.get_ident() for value in thread_ids))
            docker.assert_called_once_with(project.path, cancel=cancel)
            docker.return_value.up.assert_called_once()
            self.assertFalse(window._batch_busy)
            self.assertTrue(all(action.isEnabled() for action in window._batch_actions))

    def test_failed_batch_preparation_restores_actions_and_allows_retry(self):
        with patch('ui.main_window.ProjectManager') as manager, \
                patch.object(MainWindow, 'load_projects'), patch.object(MainWindow, 'setup_tray'), \
                patch.object(MainWindow, '_notify') as notify, patch('ui.main_window.QTimer'):
            window = MainWindow()
            self.addCleanup(window.deleteLater)
            manager.return_value.get_all_projects.side_effect = RuntimeError('Docker unavailable')
            window.load_projects.reset_mock()
            window.stop_all_projects()
            window.batch_worker.wait(3000)
            APP.processEvents()
            self.assertFalse(window._batch_busy)
            self.assertTrue(all(action.isEnabled() for action in window._batch_actions))
            notify.assert_any_call('批量停止失败', 'Docker unavailable', 'error')
            window.load_projects.assert_called_once()
            manager.return_value.get_all_projects.side_effect = None
            manager.return_value.get_all_projects.return_value = []
            window.stop_all_projects()
            window.batch_worker.wait(3000)
            APP.processEvents()
            self.assertFalse(window._batch_busy)
            notify.assert_any_call('提示', '没有可停止的项目', 'warning')

    def test_batch_filters_conflicts_and_stopped_projects(self):
        stopped = Project('stopped', Path('/nonexistent/stopped'), port='8080')
        running = Project('running', Path('/nonexistent/running'), is_running=True)
        with patch('ui.main_window.ProjectManager') as manager, \
                patch('ui.main_window.get_port_usage', return_value='nginx') as port, \
                patch('ui.main_window.DockerManager') as docker:
            manager.return_value.get_all_projects.return_value = [stopped, running]
            result = MainWindow._run_batch_operation('up', threading.Event())
            self.assertIn(('stopped', '端口 8080 被 nginx 占用'), result.skipped)
            self.assertIn(('running', '已在运行'), result.skipped)
            self.assertFalse(result.success)
            docker.assert_not_called()
            port.reset_mock()
            docker.return_value.stop.return_value = DockerResult(True)
            result = MainWindow._run_batch_operation('stop', threading.Event())
            self.assertEqual(result.succeeded, ['running'])
            self.assertTrue(result.success)
            self.assertEqual(docker.call_args.args[0], running.path)
            docker.return_value.stop.assert_called_once()
            port.assert_not_called()

    def test_batch_stop_includes_partial_projects_but_preserves_idle_shared_environment(self):
        projects = [
            Project('partial-php', Path('/nonexistent/partial-php'), php_running=True),
            Project('partial-mysql', Path('/nonexistent/partial-mysql'), mysql_running=True),
            Project('partial-shared', Path('/nonexistent/partial-shared'),
                    environment_id='a' * 32, nginx_running=True),
            Project('idle-shared', Path('/nonexistent/idle-shared'),
                    environment_id='a' * 32, php_running=True, cron_running=True),
            Project('stopped', Path('/nonexistent/stopped')),
        ]
        with patch('ui.main_window.ProjectManager') as manager, \
                patch('ui.main_window.DockerManager') as docker:
            manager.return_value.get_all_projects.return_value = projects
            docker.return_value.stop.return_value = DockerResult(True)
            result = MainWindow._run_batch_operation('stop', threading.Event())
        self.assertEqual(result.succeeded, ['partial-php', 'partial-mysql', 'partial-shared'])
        self.assertEqual(result.skipped, [('idle-shared', '已停止'), ('stopped', '已停止')])
        self.assertEqual([call.args[0] for call in docker.call_args_list],
                         [project.path for project in projects[:3]])
        self.assertTrue(result.success)

    def test_batch_retains_each_result_and_continues_after_project_failure(self):
        projects = [Project(name, Path('/nonexistent') / name, port='8080')
                    for name in ('good', 'failed', 'exception', 'conflict', 'last')]
        with patch('ui.main_window.ProjectManager') as manager, \
                patch('ui.main_window.get_port_usage', side_effect=[None, None, None, 'nginx', None]), \
                patch('ui.main_window.DockerManager') as docker:
            manager.return_value.get_all_projects.return_value = projects
            docker.return_value.up.side_effect = [DockerResult(True),
                                                  DockerResult(False, error='image missing'),
                                                  RuntimeError('connection failed'), DockerResult(True)]
            result = MainWindow._run_batch_operation('up', threading.Event())
        self.assertEqual(result.succeeded, ['good', 'last'])
        self.assertEqual(result.failed, [('failed', 'image missing'), ('exception', 'connection failed')])
        self.assertEqual(result.skipped, [('conflict', '端口 8080 被 nginx 占用')])
        self.assertFalse(result.success)
        self.assertIn('成功 2 个，失败 2 个，跳过 1 个', result.output)
        self.assertIn('[失败] failed：image missing', result.output)
        self.assertIn('[成功] last', result.output)
        window = Mock()
        MainWindow._on_batch_operation_result(window, result, 'up')
        self.assertEqual(window._notify.call_args.args[0], '批量启动部分失败')
        self.assertEqual(window._notify.call_args.args[2], 'warning')

    def test_batch_cancel_preserves_completed_results_and_skips_remaining(self):
        projects = [Project(name, Path('/nonexistent') / name, is_running=True)
                    for name in ('done', 'cancelled', 'pending')]
        cancel = threading.Event()

        def stop():
            if docker.return_value.stop.call_count == 1:
                return DockerResult(True)
            cancel.set()
            return DockerResult(False, error='操作已取消')

        with patch('ui.main_window.ProjectManager') as manager, \
                patch('ui.main_window.DockerManager') as docker:
            manager.return_value.get_all_projects.return_value = projects
            docker.return_value.stop.side_effect = stop
            result = MainWindow._run_batch_operation('stop', cancel)
            self.assertEqual(docker.return_value.stop.call_count, 2)
        self.assertEqual(result.succeeded, ['done'])
        self.assertEqual(result.failed, [('cancelled', '操作已取消')])
        self.assertEqual(result.skipped, [('pending', '操作已取消，未执行')])
        self.assertTrue(result.cancelled)
        self.assertFalse(result.success)

    def test_failed_batch_results_remain_in_background_log(self):
        with patch('ui.main_window.ProjectManager') as manager, \
                patch('ui.main_window.DockerManager') as docker, \
                patch.object(MainWindow, 'load_projects'), patch.object(MainWindow, 'setup_tray'), \
                patch.object(MainWindow, '_notify') as notify, patch('ui.main_window.QTimer'):
            manager.return_value.get_all_projects.return_value = [
                Project('demo', Path('/nonexistent/demo'), is_running=True)]
            docker.return_value.stop.return_value = DockerResult(False, error='Docker unavailable')
            window = MainWindow()
            self.addCleanup(window.deleteLater)
            window.stop_all_projects()
            self.assertTrue(window.batch_worker.wait(3000))
            APP.processEvents()
            record = window.operations_page.records[0]
            self.assertEqual(record['state'], '未完成')
            self.assertIn('[失败] demo：Docker unavailable', '\n'.join(record['logs']))
            self.assertEqual(notify.call_args.args[0], '批量停止失败')
            self.assertEqual(notify.call_args.args[2], 'error')
