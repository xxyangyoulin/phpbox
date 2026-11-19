import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QEvent, QThread, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from core.process import run_process
from ui.dialogs.build_progress import BuildProgressDialog
from ui.main_window import MainWindow
from ui.operations import OperationsPage
from ui.styles import FluentDialog
from ui.worker import OperationWorker, register_worker, _workers


APP = QApplication.instance() or QApplication([])


class CancellationTests(unittest.TestCase):
    def tearDown(self):
        self.doCleanups()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    def test_cancel_and_timeout_after_output_pipe_closes(self):
        command = [sys.executable, '-c',
                   'import os,time; os.close(1); os.close(2); time.sleep(2)']
        for cancelled in (True, False):
            with self.subTest(cancelled=cancelled):
                event = threading.Event()
                timer = threading.Timer(.2, event.set)
                if cancelled:
                    timer.start()
                start = time.monotonic()
                try:
                    with self.assertRaises(InterruptedError if cancelled else TimeoutError):
                        run_process(command, cancel=event, timeout=3 if cancelled else .2)
                finally:
                    if cancelled:
                        timer.join()
                self.assertLess(time.monotonic() - start, 1.5)

    def test_dialog_close_cancels_once_and_waits_without_blocking(self):
        dialog = FluentDialog()
        self.addCleanup(dialog.deleteLater)
        dialog.setWindowTitle('测试操作')
        worker = Mock()
        worker.isRunning.return_value = True
        dialog.worker = worker
        rejected = Mock()
        dialog.rejected.connect(rejected)
        dialog.show()
        dialog.reject()
        dialog.reject()
        QTest.qWait(250)
        worker.stop.assert_called_once()
        worker.wait.assert_not_called()
        rejected.assert_not_called()
        self.assertTrue(dialog.isVisible())
        self.assertIn('正在取消', dialog.windowTitle())
        worker.isRunning.return_value = False
        QTest.qWait(150)
        rejected.assert_called_once()
        self.assertFalse(dialog._close_timer.isActive())
        self.assertEqual(dialog.windowTitle(), '测试操作')

    def test_cancelled_build_can_be_closed_after_completion(self):
        dialog = BuildProgressDialog('demo')
        self.addCleanup(dialog.deleteLater)
        rejected, accepted = Mock(), Mock()
        dialog.rejected.connect(rejected)
        dialog.accepted.connect(accepted)
        dialog._on_cancel()
        dialog._on_cancel()
        rejected.assert_called_once()
        self.assertFalse(dialog.cancel_btn.isEnabled())
        dialog.set_finished(False, '操作已取消')
        self.assertTrue(dialog.cancel_btn.isEnabled())
        self.assertIn('已取消', dialog.title_label.text())
        dialog.cancel_btn.click()
        accepted.assert_called_once()

    def test_accept_stops_pending_dialog_close(self):
        dialog = FluentDialog()
        self.addCleanup(dialog.deleteLater)
        dialog.worker = Mock()
        dialog.worker.isRunning.return_value = True
        rejected = Mock()
        dialog.rejected.connect(rejected)
        dialog.reject()
        dialog.accept()
        self.assertFalse(dialog._close_timer.isActive())
        QTest.qWait(150)
        rejected.assert_not_called()

    def test_operation_cancel_is_idempotent_and_has_distinct_state(self):
        panel = OperationsPage()
        worker = OperationWorker(lambda: None)
        self.addCleanup(panel.deleteLater)
        self.addCleanup(worker.deleteLater)
        panel.cancel_current()
        panel.track(worker, 'demo', cancellable=True)
        with patch.object(worker, 'stop', wraps=worker.stop) as stop:
            panel.cancel_current()
            panel.cancel_current()
            stop.assert_called_once()
        self.assertTrue(worker.cancel_event.is_set())
        self.assertFalse(panel.cancel.isEnabled())
        panel.finish(panel.records[0], False, '操作已取消')
        self.assertEqual(panel.records[0]['state'], '已取消')

    def test_cancelled_worker_does_not_start_operation(self):
        operation = Mock()
        worker = OperationWorker(operation)
        failure = Mock()
        worker.failed.connect(failure)
        worker.stop()
        worker.start()
        self.assertTrue(worker.wait(1000))
        APP.processEvents()
        operation.assert_not_called()
        failure.assert_called_once_with('操作已取消')
        self.assertNotIn(worker, _workers)

    def test_worker_registry_waits_for_actual_thread_exit(self):
        entered, release = threading.Event(), threading.Event()

        class Worker(QThread):
            finished = pyqtSignal(bool)

            def run(self):
                self.finished.emit(True)
                entered.set()
                release.wait(3)

        worker = Worker()
        self.addCleanup(worker.deleteLater)
        register_worker(worker)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            APP.processEvents()
            self.assertIn(worker, _workers)
        finally:
            release.set()
            self.assertTrue(worker.wait(1000))
            APP.processEvents()
        self.assertNotIn(worker, _workers)

    def test_exit_waits_cancels_once_and_can_return_to_app(self):
        with patch('ui.main_window.ProjectManager'), \
                patch.object(MainWindow, 'load_projects'), patch.object(MainWindow, 'setup_tray'), \
                patch.object(MainWindow, '_notify'), \
                patch('ui.main_window.running_workers') as running, \
                patch('ui.main_window.QApplication.quit') as quit_app:
            window = MainWindow()
            window.stackedWidget.setAnimationEnabled(False)
            self.addCleanup(window.deleteLater)
            window.tray_icon = Mock()
            worker = Mock()
            running.return_value = [worker]
            window.quit_app()
            dialog = window._quit_dialog
            window.quit_app()
            window._quit_started -= 11
            window._poll_quit()
            worker.stop.assert_called_once()
            worker.wait.assert_not_called()
            quit_app.assert_not_called()
            self.assertIs(window._quit_dialog, dialog)
            self.assertIn('等待时间较长', window._quit_status.text())
            dialog.reject()
            self.assertIsNone(window._quit_dialog)
            self.assertFalse(window._quit_timer.isActive())
            running.return_value = []
            window._poll_quit()
            quit_app.assert_not_called()
            self.assertTrue(window.isVisible())
            self.assertIs(window.stackedWidget.currentWidget(), window.operations_page)
            window.hide()

    def test_exit_only_finishes_when_all_workers_end(self):
        with patch('ui.main_window.ProjectManager'), \
                patch.object(MainWindow, 'load_projects'), patch.object(MainWindow, 'setup_tray'), \
                patch('ui.main_window.running_workers') as running, \
                patch('ui.main_window.QApplication.quit') as quit_app:
            window = MainWindow()
            window.stackedWidget.setAnimationEnabled(False)
            self.addCleanup(window.deleteLater)
            window.tray_icon = Mock()
            first, second = Mock(), Mock()
            running.return_value = [first]
            window.quit_app()
            running.return_value = [first, second]
            window._poll_quit()
            first.stop.assert_called_once()
            second.stop.assert_called_once()
            quit_app.assert_not_called()
            running.return_value = []
            window._poll_quit()
            quit_app.assert_called_once()
            window.tray_icon.hide.assert_called_once()
            self.assertFalse(window._quit_timer.isActive())
