import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QApplication

import main
from ui.main_window import MainWindow
from ui.single_instance import SingleInstance


APP = QApplication.instance() or QApplication([])


class AppRestartTests(unittest.TestCase):
    def test_restart_preserves_window_visibility(self):
        for visible in (True, False):
            with self.subTest(visible=visible), patch('ui.main_window.running_workers', return_value=[]):
                window = Mock(restart_args=None)
                window.isVisible.return_value = visible
                MainWindow.restart_app(window)
                self.assertEqual(window.restart_args, [] if visible else ['--hide'])
                window.quit_app.assert_called_once()

    def test_restart_does_not_interrupt_background_operations(self):
        worker = Mock()
        window = Mock(restart_args=None)
        with patch('ui.main_window.running_workers', return_value=[worker]):
            MainWindow.restart_app(window)
        self.assertIsNone(window.restart_args)
        window.quit_app.assert_not_called()
        worker.stop.assert_not_called()
        window._notify.assert_called_once()

    def test_relaunch_releases_single_instance_and_uses_correct_entrypoint(self):
        for frozen, restart_args in ((False, []), (False, ['--hide']), (True, []), (True, ['--hide']), (False, None)):
            with self.subTest(frozen=frozen, restart_args=restart_args), \
                    patch('sys.argv', [main.__file__, '--new-project']), \
                    patch('sys.frozen', frozen, create=True), \
                    patch('ui.single_instance.os.getuid', return_value=f'restart-test-{os.getpid()}'), \
                    patch('PyQt6.QtWidgets.QApplication') as application, \
                    patch('PyQt6.QtCore.qInstallMessageHandler'), \
                    patch('PyQt6.QtCore.QSettings') as settings, \
                    patch('ui.styles.apply_theme'), \
                    patch('ui.main_window.MainWindow') as window_factory, \
                    patch('ui.single_instance.SingleInstance') as instance_factory, \
                    patch('main.subprocess.run'), \
                    patch('main.os.execve') as execute:
                settings.return_value.value.return_value = 'light'
                window_factory.return_value.restart_args = restart_args

                def create_instance(request, parent):
                    instance = SingleInstance(request)
                    self.addCleanup(instance.close)
                    return instance

                instance_factory.side_effect = create_instance
                app = application.return_value

                def quit_event_loop():
                    app.aboutToQuit.connect.call_args.args[0]()
                    return 0

                def check_released(*args):
                    replacement = SingleInstance('show')
                    self.addCleanup(replacement.close)
                    self.assertTrue(replacement.is_primary)
                    replacement.close()

                app.exec.side_effect = quit_event_loop
                execute.side_effect = check_released
                with self.assertRaises(SystemExit) as stopped:
                    main.main()
                self.assertEqual(stopped.exception.code, 0)
                if restart_args is None:
                    execute.assert_not_called()
                    continue
                execute.assert_called_once()
                executable, command, env = execute.call_args.args
                self.assertEqual(executable, sys.executable)
                entrypoint = [] if frozen else [str(Path(main.__file__).resolve())]
                self.assertEqual(command, [sys.executable] + entrypoint + restart_args)
                if frozen:
                    self.assertEqual(env['PYINSTALLER_RESET_ENVIRONMENT'], '1')
