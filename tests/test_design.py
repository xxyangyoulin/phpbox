import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog
from core.project import Project
from ui.main_window import ModernDashboardWidget, AVAILABLE_EXTENSION_IDS
from ui.operations import OperationsPage
from ui.worker import OperationWorker

APP = QApplication.instance() or QApplication([])


class DesignTests(unittest.TestCase):
    def test_php_config_text_keeps_its_height_after_tab_switch_and_expansion(self):
        with tempfile.TemporaryDirectory() as tmp, patch('ui.main_window.threading.Thread'):
            root = Path(tmp)
            (root / 'docker-compose.yml').write_text('services:\n  php:\n  nginx:\n')
            dashboard = ModernDashboardWidget()
            self.addCleanup(dashboard.deleteLater)
            self.addCleanup(dashboard.close)
            dashboard.resize(700, 500)
            dashboard.update_project(Project(
                'demo', root, php_running=True, nginx_running=True, is_running=True
            ))
            dashboard.show()
            QTest.qWait(50)
            info = {
                'memory_limit': '512M', 'upload_max_filesize': '128M',
                'post_max_size': '128M', 'max_execution_time': '30',
                'max_input_time': '60', 'max_file_uploads': '20',
                'display_errors': 'On', 'error_reporting': '32767',
                'date.timezone': 'Asia/Shanghai',
                'extensions': AVAILABLE_EXTENSION_IDS[:30],
            }
            dashboard.update_php_info(info)
            QTest.qWait(50)
            dashboard.tabs.setCurrentIndex(1)
            QTest.qWait(50)

            actions = [
                ('more config', dashboard.advanced_config_btn.click),
                ('more installed', dashboard.installed_ext_toggle_btn.click),
                ('more missing', dashboard.missing_ext_toggle_btn.click),
                ('smaller window', lambda: dashboard.resize(500, 300)),
                ('fewer installed', dashboard.installed_ext_toggle_btn.click),
                ('fewer missing', dashboard.missing_ext_toggle_btn.click),
                ('fewer config', dashboard.advanced_config_btn.click),
                ('overview tab', lambda: dashboard.tabs.setCurrentIndex(0)),
                ('config tab', lambda: dashboard.tabs.setCurrentIndex(1)),
                ('refresh', lambda: dashboard.update_php_info(info)),
            ]
            for stage, action in actions:
                action()
                QTest.qWait(50)
                with self.subTest(stage=stage):
                    for key, name, _ in dashboard._config_grid_widgets:
                        if not name.isVisible():
                            continue
                        for label in (name, dashboard.config_labels[key]):
                            self.assertGreaterEqual(
                                label.height(), label.minimumSizeHint().height(),
                                f'{key}: {label.text()}'
                            )
                    if dashboard.tabs.currentIndex() == 1:
                        for layout in (dashboard.installed_ext_layout, dashboard.missing_ext_layout):
                            for index in range(layout.count()):
                                badge = layout.itemAt(index).widget()
                                self.assertTrue(badge.parentWidget().rect().contains(badge.geometry()))

    def test_hidden_operation_window_can_be_reopened(self):
        panel = OperationsPage()
        dialog = QDialog()
        worker = OperationWorker(lambda: None)
        panel.track(worker, 'demo · 创建项目', dialog=dialog)
        dialog.show()
        dialog.hide()
        panel.open_window.click()
        self.assertTrue(dialog.isVisible())
        dialog.hide()
        panel.finish(panel.records[0], True, 'done')
        panel.open_window.click()
        self.assertTrue(dialog.isVisible())
        dialog.hide()
        worker.deleteLater()
        dialog.deleteLater()
        panel.deleteLater()

    def test_enabled_database_affects_health_and_service_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'docker-compose.yml').write_text('services:\n  php:\n  nginx:\n  mysql:\n')
            project = Project('demo', root, php_running=True, nginx_running=True, is_running=True)
            self.assertEqual(project.health_status, 'partial')
            with patch('ui.main_window.threading.Thread'):
                dashboard = ModernDashboardWidget()
                dashboard.update_project(project)
            self.assertEqual(dashboard.status_badge.text(), '部分运行')
            self.assertFalse(dashboard.service_rows['mysql'][0].isHidden())
            self.assertTrue(dashboard.service_rows['redis'][0].isHidden())
            self.assertEqual(dashboard.tabs.tabText(0), '概览')
            project.mysql_running = True
            self.assertEqual(project.health_status, 'healthy')
            dashboard.deleteLater()

    def test_background_failure_survives_navigation_and_can_be_cleared(self):
        panel = OperationsPage()
        def fail():
            raise RuntimeError('docker unavailable')
        worker = OperationWorker(fail)
        panel.track(worker, 'demo · 启动', '/demo')
        self.assertTrue(panel.is_busy('/demo'))
        panel.hide()
        worker.start()
        deadline = time.monotonic() + 3
        while panel.is_busy('/demo') and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.01)
        self.assertFalse(panel.is_busy('/demo'))
        self.assertIn('docker unavailable', panel.logs.toPlainText())
        self.assertFalse(panel.cancel.isEnabled())
        panel.clear_finished()
        self.assertEqual(panel.list.count(), 0)
        panel.deleteLater()
