import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QApplication, QWidget

from core.docker import DockerResult
from core.environment import EnvironmentManager, write_binding
from core.project import Project
from ui.dialogs.config_editor import ConfigEditorDialog
from ui.dialogs.php_config_dialog import PhpConfigDialog
from ui.main_window import ProjectDashboardPage
from ui.operations import OperationsPage


APP = QApplication.instance() or QApplication([])


class EnvironmentConfigTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.projects = root / 'projects'
        self.projects.mkdir()
        for target, value in [('core.environment.BASE_DIR', self.projects),
                              ('core.environment.ENVIRONMENTS_DIR', root / 'environments')]:
            patched = patch(target, value)
            patched.start()
            self.addCleanup(patched.stop)
        for target in ('core.docker.DockerManager._detect_compose',
                       'ui.dialogs.config_editor.InfoBar', 'ui.dialogs.php_config_dialog.InfoBar'):
            patched = patch(target)
            patched.start()
            self.addCleanup(patched.stop)
        self.manager = EnvironmentManager()
        self.environment = self.manager.create('PHP 8.4', '8.4', ['redis'])
        self.ini = self.environment.path / 'php/php.ini'
        self.ini.write_text('memory_limit = 128M\n')
        for name, identity in [('demo', '1'), ('other', '2')]:
            path = self.projects / name
            path.mkdir()
            write_binding(path, {'id': identity * 32, 'environment_id': self.environment.id, 'enabled': True})
        self.path = self.projects / 'demo'
        (self.path / 'php').mkdir()
        self.legacy = self.path / 'php/php.ini'
        self.legacy.write_text('memory_limit = 64M\n')
        (self.path / 'nginx').mkdir()
        (self.path / 'nginx/default.conf').write_text('server {}\n')

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.01)
        APP.processEvents()
        self.assertTrue(predicate())

    def test_project_parameter_click_opens_editor_without_navigation(self):
        with patch('ui.main_window.ProjectManager'), patch('ui.main_window.PhpConfigDialog') as editor:
            page = ProjectDashboardPage()
            self.addCleanup(page.deleteLater)
            page.current_project = Project('demo', self.path, is_running=True, environment_id=self.environment.id)
            page.dashboard._config_current_values = {'memory_limit': '128M'}
            editor.return_value.exec.return_value = 1
            with patch.object(page, 'manage_environment') as navigate, \
                    patch.object(page, '_refresh_php_info') as refresh:
                page._on_php_config_clicked('memory_limit')
                refresh.assert_not_called()
                editor.return_value.config_applied.connect.call_args.args[0]()
                refresh.assert_called_once()
            navigate.assert_not_called()
            editor.assert_called_once_with(self.path, 'demo', {'memory_limit': '128M'}, page)

    def test_parameter_editor_saves_environment_without_touching_legacy_config(self):
        dialog = PhpConfigDialog(self.path, 'demo', {'memory_limit': '128M'})
        self.addCleanup(dialog.deleteLater)
        dialog.inputs['memory_limit'].setText('512M')
        with patch('ui.dialogs.php_config_dialog.MessageBox') as confirmation, \
                patch.object(EnvironmentManager, 'running', return_value=False), \
                patch.object(EnvironmentManager, '_build') as build, \
                patch.object(dialog.docker, 'restart_service') as restart:
            confirmation.return_value.exec.return_value = 1
            dialog.save_config()
            self.wait_for(lambda: dialog.save_btn.isEnabled())
            build.assert_not_called()
            restart.assert_not_called()
            self.assertIn('other', confirmation.call_args.args[1])
        self.assertIn('memory_limit = 512M', self.ini.read_text())
        self.assertEqual(self.legacy.read_text(), 'memory_limit = 64M\n')

    def test_parameter_editor_cancel_does_not_write_config(self):
        dialog = PhpConfigDialog(self.path, 'demo', {})
        self.addCleanup(dialog.deleteLater)
        dialog.inputs['memory_limit'].setText('512M')
        with patch('ui.dialogs.php_config_dialog.MessageBox') as confirmation:
            confirmation.return_value.exec.return_value = 0
            dialog.save_config()
        self.assertEqual(self.ini.read_text(), 'memory_limit = 128M\n')
        self.assertFalse(hasattr(dialog, 'operation_worker'))

    def test_active_task_prevents_parameter_change(self):
        dialog = PhpConfigDialog(self.path, 'demo', {})
        self.addCleanup(dialog.deleteLater)
        applied = Mock()
        dialog.config_applied.connect(applied)
        dialog.inputs['memory_limit'].setText('512M')
        with patch('ui.dialogs.php_config_dialog.MessageBox') as confirmation, \
                patch.object(EnvironmentManager, 'running', return_value=True), \
                patch.object(EnvironmentManager, 'active_tasks', return_value='running-task.pid'), \
                patch.object(EnvironmentManager, 'compose') as compose:
            confirmation.return_value.exec.return_value = 1
            dialog.save_config()
            self.wait_for(lambda: dialog.save_btn.isEnabled())
            compose.assert_not_called()
        self.assertEqual(self.ini.read_text(), 'memory_limit = 128M\n')
        applied.assert_not_called()

    def test_slow_apply_closes_editor_before_completion_and_notifies_main_window(self):
        window = QWidget()
        window.operations_page = OperationsPage(window)
        self.addCleanup(window.deleteLater)
        dialog = PhpConfigDialog(self.path, 'demo', {}, window)
        applied = Mock()
        dialog.config_applied.connect(applied)
        started, release = threading.Event(), threading.Event()

        def slow_update(*args):
            started.set()
            if not release.wait(3):
                raise RuntimeError('test timed out')

        dialog.show()
        APP.processEvents()
        with patch('ui.dialogs.php_config_dialog.MessageBox') as confirmation, \
                patch('ui.dialogs.php_config_dialog.InfoBar') as info, \
                patch.object(EnvironmentManager, 'update', side_effect=slow_update):
            confirmation.return_value.exec.return_value = 1
            try:
                dialog.save_config()
                self.wait_for(started.is_set)
                self.assertFalse(dialog.isVisible())
                self.assertFalse(dialog.save_btn.isEnabled())
                self.assertEqual(window.operations_page.records[0]['state'], '执行中')
                applied.assert_not_called()
                info.success.assert_not_called()
                self.assertIs(info.info.call_args.kwargs['parent'], window)
            finally:
                release.set()
                self.wait_for(lambda: dialog.save_btn.isEnabled())
            applied.assert_called_once()
            self.assertEqual(window.operations_page.records[0]['state'], '已完成')
            self.assertIs(info.success.call_args.kwargs['parent'], window)

    def test_restart_failure_after_close_is_reported_and_editor_can_be_reopened(self):
        (self.path / '.phpbox/project.json').unlink()
        window = QWidget()
        window.operations_page = OperationsPage(window)
        self.addCleanup(window.deleteLater)
        dialog = PhpConfigDialog(self.path, 'demo', {}, window)
        dialog.inputs['memory_limit'].setText('512M')
        applied = Mock()
        dialog.config_applied.connect(applied)
        dialog.show()
        with patch.object(dialog.docker, 'restart_service', return_value=DockerResult(False, error='restart failed')), \
                patch('ui.dialogs.php_config_dialog.InfoBar') as info:
            dialog.save_config()
            self.assertFalse(dialog.isVisible())
            self.wait_for(lambda: dialog.save_btn.isEnabled())
            applied.assert_not_called()
            info.success.assert_not_called()
            self.assertIs(info.warning.call_args.kwargs['parent'], window)
        record = window.operations_page.records[0]
        self.assertEqual(record['state'], '未完成')
        self.assertIn('restart failed', '\n'.join(record['logs']))
        window.operations_page.open_current_window()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.inputs['memory_limit'].text(), '512M')
        dialog.hide()

    def test_shared_xdebug_opens_environment_editor_in_project_page(self):
        with patch('ui.main_window.ProjectManager'), patch('ui.main_window.EnvironmentEditor') as editor:
            page = ProjectDashboardPage()
            self.addCleanup(page.deleteLater)
            page.current_project = Project('demo', self.path, is_running=True, environment_id=self.environment.id)
            with patch.object(page, 'manage_environment') as navigate:
                page.configure_xdebug()
            navigate.assert_not_called()
            self.assertIs(editor.call_args.args[0], page)
            self.assertEqual(editor.call_args.args[1].id, self.environment.id)
            editor.return_value.show.assert_called_once()

    def test_file_editor_routes_php_and_nginx_to_their_owners(self):
        dialog = ConfigEditorDialog(self.path, 'demo')
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.current_file, self.ini)
        self.assertIn('other', dialog.scope_label.text())
        self.assertEqual(dialog.file_combo.findData(str(self.legacy)), -1)
        dialog.editor.setPlainText('memory_limit = 768M\n')
        with patch('ui.dialogs.config_editor.MessageBox') as confirmation, \
                patch.object(EnvironmentManager, 'running', return_value=False):
            confirmation.return_value.exec.return_value = 1
            dialog.save_file()
            self.wait_for(lambda: not dialog._saving)
        self.assertFalse(dialog.has_unsaved_changes)
        self.assertEqual(self.ini.read_text(), 'memory_limit = 768M\n')
        self.assertEqual(self.legacy.read_text(), 'memory_limit = 64M\n')

        nginx = self.path / 'nginx/default.conf'
        dialog.file_combo.setCurrentIndex(dialog.file_combo.findData(str(nginx)))
        dialog.editor.setPlainText('server { listen 8080; }\n')
        with patch.object(EnvironmentManager, 'update') as update:
            self.assertTrue(dialog.save_file())
            update.assert_not_called()
        self.assertEqual(nginx.read_text(), 'server { listen 8080; }\n')
        self.assertEqual(self.ini.read_text(), 'memory_limit = 768M\n')

    def test_file_editor_failed_apply_rolls_back_and_keeps_edits(self):
        dialog = ConfigEditorDialog(self.path, 'demo')
        self.addCleanup(dialog.deleteLater)
        dialog.editor.setPlainText('memory_limit = 1024M\n')
        with patch('ui.dialogs.config_editor.MessageBox') as confirmation, \
                patch.object(EnvironmentManager, 'running', return_value=True), \
                patch.object(EnvironmentManager, 'active_tasks', return_value=''), \
                patch.object(EnvironmentManager, 'command', side_effect=RuntimeError('invalid config')), \
                patch.object(EnvironmentManager, 'compose'):
            confirmation.return_value.exec.return_value = 1
            dialog.save_file()
            self.wait_for(lambda: not dialog._saving)
        self.assertEqual(self.ini.read_text(), 'memory_limit = 128M\n')
        self.assertTrue(dialog.has_unsaved_changes)
        self.assertEqual(dialog.editor.toPlainText(), 'memory_limit = 1024M\n')
        self.assertTrue(dialog.save_btn.isEnabled())

    def test_cancel_shared_save_keeps_file_selection_and_edits(self):
        dialog = ConfigEditorDialog(self.path, 'demo')
        self.addCleanup(dialog.deleteLater)
        dialog.editor.setPlainText('memory_limit = 512M\n')
        with patch('ui.dialogs.config_editor.UnsavedChangesDialog') as unsaved, \
                patch('ui.dialogs.config_editor.MessageBox') as confirmation:
            unsaved.return_value.exec.return_value = 1
            confirmation.return_value.exec.return_value = 0
            dialog.file_combo.setCurrentIndex(1)
        self.assertEqual(dialog.current_file, self.ini)
        self.assertEqual(dialog.file_combo.currentData(), str(self.ini))
        self.assertEqual(dialog.editor.toPlainText(), 'memory_limit = 512M\n')
        self.assertEqual(self.ini.read_text(), 'memory_limit = 128M\n')

    def test_independent_project_keeps_original_config_and_restart(self):
        (self.path / '.phpbox/project.json').unlink()
        dialog = PhpConfigDialog(self.path, 'demo', {})
        self.addCleanup(dialog.deleteLater)
        dialog.inputs['memory_limit'].setText('256M')
        with patch.object(dialog.docker, 'restart_service', return_value=DockerResult(True)) as restart:
            dialog.save_config()
            self.wait_for(lambda: dialog.save_btn.isEnabled())
            restart.assert_called_once_with('php')
        self.assertIn('memory_limit = 256M', self.legacy.read_text())
        self.assertEqual(self.ini.read_text(), 'memory_limit = 128M\n')


if __name__ == '__main__':
    unittest.main()
