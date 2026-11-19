import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import QApplication

from core.project import Project
from core.settings import Settings
from ui.main_window import MainWindow, ProjectDashboardPage
from ui.styles import apply_theme_preference


APP = QApplication.instance() or QApplication([])


class ProjectWorkflowTests(unittest.TestCase):
    def test_uncached_config_query_keeps_ui_responsive_and_discards_old_project(self):
        started, release = threading.Event(), threading.Event()

        def query():
            started.set()
            release.wait(3)
            return {'memory_limit': '128M'}

        with patch('ui.main_window.ProjectManager'), \
                patch('ui.main_window.DockerManager') as docker, \
                patch('ui.main_window.PhpConfigDialog') as dialog:
            docker.return_value.get_php_info.side_effect = query
            page = ProjectDashboardPage()
            self.addCleanup(page.deleteLater)
            first = Project('first', Path('/nonexistent/first'), is_running=True)
            second = Project('second', Path('/nonexistent/second'), is_running=True)
            page.show_project(first, loading=True)
            page._on_php_config_clicked('memory_limit')
            worker = page.config_worker
            try:
                self.assertTrue(started.wait(1))
                tick = []
                QTimer.singleShot(0, lambda: tick.append(True))
                APP.processEvents()
                self.assertEqual(tick, [True])
                dialog.assert_not_called()
                page._on_php_config_clicked('memory_limit')
                docker.return_value.get_php_info.assert_called_once()
                page.show_project(second, loading=True)
            finally:
                release.set()
                worker.wait(3000)
                APP.processEvents()
            dialog.assert_not_called()
            docker.return_value.get_php_info.side_effect = None
            docker.return_value.get_php_info.return_value = {'memory_limit': '256M'}
            page._on_php_config_clicked('memory_limit')
            page.config_worker.wait(3000)
            APP.processEvents()
            dialog.assert_called_once_with(second.path, second.name, {'memory_limit': '256M'}, page)

    def test_failed_config_query_can_be_retried(self):
        with patch('ui.main_window.ProjectManager'), \
                patch('ui.main_window.DockerManager') as docker, \
                patch('ui.main_window.InfoBar.error') as error, \
                patch('ui.main_window.PhpConfigDialog') as dialog:
            docker.return_value.get_php_info.return_value = {}
            page = ProjectDashboardPage()
            self.addCleanup(page.deleteLater)
            page.current_project = Project('demo', Path('/nonexistent/demo'), is_running=True)
            page._on_php_config_clicked('memory_limit')
            page.config_worker.wait(3000)
            APP.processEvents()
            self.assertFalse(page._config_loading)
            error.assert_called_once()
            dialog.assert_not_called()

    def test_config_result_is_discarded_after_environment_switch(self):
        with patch('ui.main_window.ProjectManager'), \
                patch('ui.main_window.InfoBar.warning') as warning, \
                patch('ui.main_window.PhpConfigDialog') as dialog:
            page = ProjectDashboardPage()
            self.addCleanup(page.deleteLater)
            previous = Project('demo', Path('/nonexistent/demo'), php_version='8.4',
                               environment_id='a' * 32, is_running=True)
            page.current_project = Project('demo', previous.path, php_version='7.2',
                                           environment_id='b' * 32, is_running=True)
            page._config_loading = True
            page._open_php_config(previous, page._php_config_request, {'memory_limit': '128M'})
            dialog.assert_not_called()
            warning.assert_called_once()
            self.assertFalse(page._config_loading)

    def test_refresh_updates_all_icons_tooltips_and_preserves_selection(self):
        with patch('ui.main_window.ProjectManager'), patch.object(MainWindow, 'load_projects'), \
                patch.object(MainWindow, 'setup_tray'), patch('ui.main_window.QTimer'):
            window = MainWindow()
            self.addCleanup(window.deleteLater)
            first = Project('a', Path('/nonexistent/a'))
            second = Project('b', Path('/nonexistent/b'), is_running=True, php_running=True, nginx_running=True)
            window._on_projects_loaded([first, second], select_project='b')
            self.assertEqual(window._project_nav_keys, ['proj_b', 'proj_a'])
            updated_first = Project('a', first.path, php_version='8.4', is_running=True,
                                    php_running=True, nginx_running=True)
            updated_second = Project('b', second.path)
            window.dashboard_page._on_reload_current([updated_first, updated_second])
            self.assertEqual(window._project_nav_keys, ['proj_a', 'proj_b'])
            self.assertTrue(window._project_nav_items['proj_a'].is_running)
            self.assertFalse(window._project_nav_items['proj_b'].is_running)
            self.assertIn('PHP 8.4', window._project_nav_items['proj_a'].toolTip())
            self.assertEqual(window.dashboard_page.current_project.name, 'b')
            window.on_project_clicked(first)
            self.assertIs(window.dashboard_page.current_project, updated_first)
            window.switchTo(window.operations_page)
            window._on_projects_loaded([updated_second, updated_first])
            self.assertEqual(window.dashboard_page.current_project.name, 'a')
            self.assertIs(window.stackedWidget.currentWidget(), window.operations_page)

    def test_theme_preference_persists_and_switches_system_watcher(self):
        with tempfile.TemporaryDirectory() as directory:
            config = QSettings(str(Path(directory) / 'settings.ini'), QSettings.Format.IniFormat)
            with patch('core.settings.QSettings', return_value=config), \
                    patch('ui.styles.detect_system_theme', return_value='dark'), \
                    patch('ui.styles.apply_theme') as apply:
                Settings().set_theme('light')
                self.assertEqual(Settings().get_theme(), 'light')
                apply_theme_preference(APP, Settings().get_theme())
                self.assertIsNone(getattr(APP, 'theme_watcher', None))
                apply_theme_preference(APP, 'auto')
                watcher = APP.theme_watcher
                self.assertTrue(watcher._timer.isActive())
                apply.assert_called_with(APP, 'dark')
                apply_theme_preference(APP, 'light')
                self.assertFalse(watcher._timer.isActive())
                self.assertIsNone(APP.theme_watcher)
                apply.assert_called_with(APP, 'light')
