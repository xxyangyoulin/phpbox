import threading

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication


_workers = set()


def register_worker(worker, title=None, dialog=None):
    _workers.add(worker)
    worker.setParent(QApplication.instance())
    # 部分 worker 覆盖了 finished；原始信号才代表线程已真正退出。
    QThread.finished.__get__(worker, QThread).connect(lambda: _workers.discard(worker))
    worker.destroyed.connect(lambda: _workers.discard(worker))
    if title:
        for window in QApplication.topLevelWidgets():
            if hasattr(window, "operations_page"):
                window.operations_page.track(worker, title, str(worker.project_path), cancellable=True, dialog=dialog)
                break


def running_workers():
    for worker in list(_workers):
        try:
            if not worker.isRunning():
                _workers.discard(worker)
        except RuntimeError:
            _workers.discard(worker)
    return list(_workers)


class OperationWorker(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, operation):
        super().__init__(QApplication.instance())
        register_worker(self)
        self.operation = operation
        self.cancel_event = threading.Event()
        self.finished.connect(self.deleteLater)

    def run(self):
        try:
            if self.cancel_event.is_set():
                raise InterruptedError("操作已取消")
            result = self.operation()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(result)

    def stop(self):
        self.cancel_event.set()
