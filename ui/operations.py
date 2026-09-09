from collections import deque

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import TitleLabel, PushButton, ListWidget, TextEdit


class OperationsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("operationsPage")
        self.records = []
        layout = QVBoxLayout(self)
        layout.addWidget(TitleLabel("后台操作"))
        self.list = ListWidget()
        layout.addWidget(self.list)
        self.logs = TextEdit()
        self.logs.setReadOnly(True)
        self.logs.document().setMaximumBlockCount(2000)
        layout.addWidget(self.logs, 1)
        buttons = QHBoxLayout()
        self.open_window = PushButton("打开操作窗口")
        self.open_window.clicked.connect(self.open_current_window)
        buttons.addWidget(self.open_window)
        self.cancel = PushButton("取消操作")
        self.cancel.clicked.connect(self.cancel_current)
        buttons.addWidget(self.cancel)
        clear = PushButton("清除已完成记录")
        clear.clicked.connect(self.clear_finished)
        buttons.addWidget(clear)
        layout.addLayout(buttons)
        self.list.currentRowChanged.connect(self.refresh)
        self.list.itemDoubleClicked.connect(self.open_current_window)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(200)

    def is_busy(self, key):
        return any(r["key"] == key and r["state"] in ("执行中", "正在取消") for r in self.records)

    def track(self, worker, title, key="", cancellable=False, dialog=None):
        record = dict(worker=worker, title=title, key=key, state="执行中",
                      logs=deque(maxlen=2000), cancellable=cancellable, dialog=dialog)
        if dialog is not None:
            dialog.destroyed.connect(lambda: record.update(dialog=None))
        self.records.append(record)
        self.list.addItem(title + " · 执行中")
        self.list.setCurrentRow(len(self.records) - 1)
        if hasattr(worker, "progress"):
            worker.progress.connect(lambda line: record["logs"].append(str(line)[-4096:]))
        if hasattr(worker, "succeeded"):
            worker.succeeded.connect(lambda result: self.finish(record, True, getattr(result, "output", "")))
            worker.failed.connect(lambda message: self.finish(record, False, message))
        else:
            worker.finished.connect(lambda success, message, logs: self.finish(record, success, message))

    def finish(self, record, success, message):
        record["state"] = "已完成" if success else "未完成"
        record["logs"].append(str(message)[-65536:])
        record["worker"] = None
        self.refresh()

    def refresh(self, *args):
        for i, record in enumerate(self.records):
            self.list.item(i).setText(record["title"] + " · " + record["state"])
        index = self.list.currentRow()
        record = self.records[index] if 0 <= index < len(self.records) else None
        content = "\n".join(record["logs"]) if record else "选择操作查看日志；切换页面不会取消操作。"
        if content != self.logs.toPlainText():
            self.logs.setPlainText(content)
            self.logs.verticalScrollBar().setValue(self.logs.verticalScrollBar().maximum())
        self.cancel.setEnabled(bool(record and record["cancellable"] and record["state"] == "执行中"))
        self.open_window.setEnabled(bool(record and record["dialog"] is not None))

    def open_current_window(self, *args):
        index = self.list.currentRow()
        if not 0 <= index < len(self.records):
            return
        dialog = self.records[index]["dialog"]
        if dialog is not None:
            dialog.showNormal()
            dialog.raise_()
            dialog.activateWindow()

    def cancel_current(self):
        record = self.records[self.list.currentRow()]
        record["state"] = "正在取消"
        record["worker"].stop()
        self.refresh()

    def clear_finished(self):
        self.list.blockSignals(True)
        self.records = [r for r in self.records if r["worker"] is not None]
        self.list.clear()
        self.list.addItems([r["title"] for r in self.records])
        self.list.blockSignals(False)
        self.refresh()
