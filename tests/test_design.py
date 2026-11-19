import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog
from core.project import Project
from ui.main_window import (
    ModernDashboardWidget, AVAILABLE_EXTENSION_IDS, get_project_color, make_project_icon,
)
from ui.operations import OperationsPage
from ui.environments import EnvironmentsPage
from ui.styles import FluentDialog, LogTextEdit, StatusBadge, apply_theme, get_fluent_theme
from ui.worker import OperationWorker

APP = QApplication.instance() or QApplication([])


class DesignTests(unittest.TestCase):
    def test_hidden_tabs_do_not_add_scrollable_blank_space(self):
        with patch('ui.main_window.threading.Thread'):
            dashboard = ModernDashboardWidget()
            self.addCleanup(dashboard.deleteLater)
            dashboard.resize(1000, 700)
            dashboard.update_project(Project('demo', Path('/nonexistent/phpbox-demo'),
                                             php_running=True, nginx_running=True, is_running=True))
            dashboard.update_php_info({'extensions': AVAILABLE_EXTENSION_IDS[:30]})
            dashboard.show()
            QTest.qWait(30)
            self.assertEqual(dashboard.verticalScrollBar().maximum(), 0)
            dashboard.tabs.setCurrentItem('config')
            dashboard.advanced_config_btn.click()
            dashboard.installed_ext_toggle_btn.click()
            dashboard.missing_ext_toggle_btn.click()
            QTest.qWait(30)
            self.assertGreater(dashboard.verticalScrollBar().maximum(), 0)
            for tab in ('overview', 'tools'):
                dashboard.tabs.setCurrentItem(tab)
                QTest.qWait(30)
                self.assertEqual(dashboard.verticalScrollBar().maximum(), 0)
                self.assertFalse(dashboard.config_card.isVisible())

    def test_stopped_project_icons_have_gray_overlay(self):
        with patch.dict('ui.main_window._project_colors', {}, clear=True):
            colors = [get_project_color('api-' + str(index)) for index in range(12)]
            self.assertEqual(len(set(colors)), 12)
            self.assertEqual(get_project_color('api-0'), colors[0])
            running = make_project_icon('api-0', True).pixmap(80, 80).toImage()
            stopped = make_project_icon('api-0', False).pixmap(80, 80).toImage()
            partial = make_project_icon('api-0', False, True).pixmap(80, 80).toImage()
            self.assertNotEqual(running.pixelColor(15, 25), stopped.pixelColor(15, 25))
            self.assertLess(stopped.pixelColor(15, 25).saturation(), running.pixelColor(15, 25).saturation())
            self.assertEqual(stopped.pixelColor(15, 25).saturation(), 0)
            self.assertEqual(running.pixelColor(15, 25), partial.pixelColor(15, 25))
            self.assertEqual(stopped.pixelColor(0, 0).alpha(), 0)
            self.assertNotEqual(running.pixelColor(68, 68), stopped.pixelColor(68, 68))

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
            dashboard.tabs.setCurrentItem("config")
            QTest.qWait(50)

            actions = [
                ('more config', dashboard.advanced_config_btn.click),
                ('more installed', dashboard.installed_ext_toggle_btn.click),
                ('more missing', dashboard.missing_ext_toggle_btn.click),
                ('smaller window', lambda: dashboard.resize(500, 300)),
                ('fewer installed', dashboard.installed_ext_toggle_btn.click),
                ('fewer missing', dashboard.missing_ext_toggle_btn.click),
                ('fewer config', dashboard.advanced_config_btn.click),
                ('overview tab', lambda: dashboard.tabs.setCurrentItem("overview")),
                ('config tab', lambda: dashboard.tabs.setCurrentItem("config")),
                ('refresh', lambda: dashboard.update_php_info(info)),
            ]
            for stage, action in actions:
                action()
                QTest.qWait(50)
                with self.subTest(stage=stage):
                    for button in dashboard._header_actions:
                        self.assertTrue(button.parentWidget().rect().contains(button.geometry()))
                    for key, name, _ in dashboard._config_grid_widgets:
                        if not name.isVisible():
                            continue
                        for label in (name, dashboard.config_labels[key]):
                            self.assertGreaterEqual(
                                label.height(), label.minimumSizeHint().height(),
                                f'{key}: {label.text()}'
                            )
                    if dashboard.tabs.currentRouteKey() == "config":
                        for layout in (dashboard.installed_ext_layout, dashboard.missing_ext_layout):
                            for index in range(layout.count()):
                                badge = layout.itemAt(index).widget()
                                self.assertTrue(badge.parentWidget().rect().contains(badge.geometry()))

    def test_badges_and_dialog_follow_theme_round_trip(self):
        theme = get_fluent_theme().value.lower()
        self.addCleanup(lambda: apply_theme(APP, theme))
        badge = StatusBadge('PHP 8.4', tone='accent')
        dialog = FluentDialog()
        log = LogTextEdit()
        self.addCleanup(badge.deleteLater)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(log.deleteLater)
        badge.resize(100, 32)
        dialog.resize(160, 100)
        badge.show()
        dialog.show()
        log.resize(200, 100)
        log.show()
        samples = []
        for mode in ('light', 'dark', 'light'):
            apply_theme(APP, mode)
            QTest.qWait(20)
            samples.append((badge.grab().toImage().pixelColor(6, 6).name(),
                            dialog.grab().toImage().pixelColor(20, 20).name()))
            self.assertEqual(badge.text(), 'PHP 8.4')
            self.assertLess(log.grab().toImage().pixelColor(30, 30).value(), 80)
        self.assertNotEqual(samples[0][0], samples[1][0])
        self.assertNotEqual(samples[0][1], samples[1][1])
        self.assertEqual(samples[0], samples[2])

    def test_environment_actions_fit_after_hidden_page_is_shown(self):
        page = EnvironmentsPage()
        self.addCleanup(page.deleteLater)
        env = SimpleNamespace(id='a', name='PHP 8.4', php_version='8.4',
                              path=Path('/example/php84'), extensions=['redis', 'gd'])
        page.loaded([(env, True, {'version': '8.4.14', 'memory_limit': '512M'}, [])])
        page.resize(560, 700)
        page.show()
        for width in (560, 1000, 560):
            page.resize(width, 700)
            QTest.qWait(30)
            for button in page.actions:
                self.assertTrue(button.isVisible())
                self.assertTrue(button.parentWidget().rect().contains(button.geometry()))
            self.assertEqual(page.selected_id, 'a')
            self.assertEqual(page.version_badge.text(), 'PHP 8.4.14')

    def test_live_logs_keep_reading_position(self):
        panel = OperationsPage()
        worker = OperationWorker(lambda: None)
        self.addCleanup(panel.deleteLater)
        self.addCleanup(worker.deleteLater)
        panel.resize(1000, 700)
        panel.show()
        panel.track(worker, '构建环境')
        record = panel.records[0]
        panel._append_logs(record, '\n'.join(str(i) for i in range(300)))
        panel.refresh()
        QTest.qWait(30)
        bar = panel.logs.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(0)
        panel._append_logs(record, '新增输出')
        panel.refresh()
        self.assertEqual(bar.value(), 0)
        bar.setValue(bar.maximum())
        panel._append_logs(record, '继续输出')
        panel.refresh()
        self.assertEqual(bar.value(), bar.maximum())

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

    def test_background_logs_append_in_batches_without_full_text_reads(self):
        panel = OperationsPage()
        worker = OperationWorker(lambda: None)
        self.addCleanup(panel.deleteLater)
        self.addCleanup(worker.deleteLater)
        panel.show()
        panel.track(worker, '构建环境')
        record = panel.records[0]
        panel._append_logs(record, 'first')
        panel.refresh()
        with patch.object(panel.logs, 'setPlainText', wraps=panel.logs.setPlainText) as reset, \
                patch.object(panel.logs, 'toPlainText', wraps=panel.logs.toPlainText) as read:
            for i in range(100):
                panel._append_logs(record, str(i))
            self.assertTrue(panel.timer.isActive())
            self.assertEqual(panel.logs.document().blockCount(), 1)
            QTest.qWait(250)
            self.assertEqual(panel.logs.document().blockCount(), 101)
            self.assertFalse(panel.timer.isActive())
            panel.refresh()
            reset.assert_not_called()
            read.assert_not_called()
        self.assertEqual(panel.logs.toPlainText(), 'first\n' + '\n'.join(map(str, range(100))))

    def test_hidden_logs_only_render_on_return_and_remain_bounded(self):
        panel = OperationsPage()
        worker = OperationWorker(lambda: None)
        self.addCleanup(panel.deleteLater)
        self.addCleanup(worker.deleteLater)
        panel.show()
        panel.track(worker, '构建环境')
        record = panel.records[0]
        panel._append_logs(record, 'first')
        panel.hide()
        self.assertFalse(panel.timer.isActive())
        with patch.object(panel.logs, 'setPlainText', wraps=panel.logs.setPlainText) as reset:
            for i in range(2100):
                panel._append_logs(record, str(i))
            panel.finish(record, True, 'done\n<literal>')
            panel.refresh()
            self.assertFalse(panel.timer.isActive())
            reset.assert_not_called()
        self.assertEqual(len(record['logs']), 2000)
        panel.show()
        self.assertEqual(panel.logs.document().blockCount(), 2000)
        self.assertEqual(panel.logs.toPlainText(), '\n'.join(record['logs']))
        panel._append_logs(record, 'next\nlast')
        panel.refresh()
        self.assertEqual(panel.logs.document().blockCount(), 2000)
        self.assertEqual(panel.logs.toPlainText(), '\n'.join(record['logs']))

    def test_log_selection_switch_and_clear_show_correct_content(self):
        panel = OperationsPage()
        worker = OperationWorker(lambda: None)
        self.addCleanup(panel.deleteLater)
        self.addCleanup(worker.deleteLater)
        panel.show()
        panel.track(worker, 'first')
        first = panel.records[0]
        panel._append_logs(first, 'one')
        panel.track(worker, 'second')
        second = panel.records[1]
        panel._append_logs(second, 'two')
        panel.refresh()
        panel._append_logs(first, 'three')
        self.assertFalse(panel.timer.isActive())
        self.assertEqual(panel.logs.toPlainText(), 'two')
        panel.list.setCurrentRow(0)
        self.assertEqual(panel.logs.toPlainText(), 'one\nthree')
        panel.finish(first, True, 'done')
        panel.clear_finished()
        self.assertEqual(panel.logs.toPlainText(), 'two')
        panel.finish(second, True, 'done')
        panel.clear_finished()
        self.assertIn('选择操作查看日志', panel.logs.toPlainText())

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
            self.assertEqual(dashboard.tabs.widget('overview').text(), '概览')
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
        panel.show()
        self.assertIn('docker unavailable', panel.logs.toPlainText())
        self.assertFalse(panel.cancel.isEnabled())
        panel.clear_finished()
        self.assertEqual(panel.list.count(), 0)
        panel.deleteLater()
