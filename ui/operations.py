from collections import deque

from PyQt6.QtCore import QTimer, Qt, QSize
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidgetItem
from qfluentwidgets import (TitleLabel, CaptionLabel, StrongBodyLabel, PushButton,
                            PrimaryPushButton, ListWidget, FluentIcon as FIF, setCustomStyleSheet)
from ui.styles import LogTextEdit, SurfaceCard, StatusBadge


class OperationsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("operations")
        self.records = []
        self._displayed_record = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(TitleLabel("后台操作"))
        subtitle = CaptionLabel("构建与安装可在后台继续，选择记录可查看日志或重新打开操作窗口。")
        subtitle.setWordWrap(True)
        subtitle.setTextColor(QColor("#606060"), QColor("#cecece"))
        layout.addWidget(subtitle)
        toolbar = QHBoxLayout()
        self.summary = CaptionLabel("暂无操作记录")
        toolbar.addWidget(self.summary, 1)
        clear = PushButton(FIF.DELETE, "清除已完成记录")
        clear.clicked.connect(self.clear_finished)
        toolbar.addWidget(clear)
        layout.addLayout(toolbar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(12)
        list_card = SurfaceCard()
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(8, 12, 8, 8)
        self.list = ListWidget()
        self.list.setMinimumWidth(190)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        setCustomStyleSheet(self.list, "QListWidget { background: transparent; border: none; }",
                            "QListWidget { background: transparent; border: none; }")
        list_layout.addWidget(self.list)
        self.splitter.addWidget(list_card)

        detail_card = SurfaceCard()
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(16, 16, 16, 16)
        detail_layout.setSpacing(12)
        self.operation_title = StrongBodyLabel("操作日志")
        self.operation_title.setWordWrap(True)
        detail_layout.addWidget(self.operation_title)
        self.state_badge = StatusBadge("未选择")
        detail_layout.addWidget(self.state_badge, 0, Qt.AlignmentFlag.AlignLeft)
        self.logs = LogTextEdit()
        self.logs.setReadOnly(True)
        self.logs.document().setMaximumBlockCount(2000)
        detail_layout.addWidget(self.logs, 1)
        buttons = QHBoxLayout()
        self.open_window = PrimaryPushButton(FIF.LINK, "打开操作窗口")
        self.open_window.clicked.connect(self.open_current_window)
        buttons.addWidget(self.open_window)
        self.cancel = PushButton("取消操作")
        self.cancel.clicked.connect(self.cancel_current)
        buttons.addWidget(self.cancel)
        buttons.addStretch()
        detail_layout.addLayout(buttons)
        self.splitter.addWidget(detail_card)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        layout.addWidget(self.splitter, 1)
        self.list.currentRowChanged.connect(self.refresh)
        self.list.itemDoubleClicked.connect(self.open_current_window)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(200)
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        orientation = Qt.Orientation.Vertical if self.width() < 780 else Qt.Orientation.Horizontal
        if self.splitter.orientation() != orientation:
            self.splitter.setOrientation(orientation)
            self.splitter.setSizes([160, 380] if orientation == Qt.Orientation.Vertical else [260, 520])

    def is_busy(self, key):
        return any(r["key"] == key and r["state"] in ("执行中", "正在取消") for r in self.records)

    def track(self, worker, title, key="", cancellable=False, dialog=None):
        record = dict(worker=worker, title=title, key=key, state="执行中",
                      logs=deque(maxlen=2000), cancellable=cancellable, dialog=dialog)
        if dialog is not None:
            dialog.destroyed.connect(lambda: record.update(dialog=None))
        self.records.append(record)
        item = QListWidgetItem(title + "\n执行中")
        item.setSizeHint(QSize(180, 64))
        item.setToolTip(title)
        self.list.addItem(item)
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
        active = sum(r["state"] in ("执行中", "正在取消") for r in self.records)
        self.summary.setText(f"{len(self.records)} 条记录 · {active} 项进行中" if self.records else "暂无操作记录")
        for i, record in enumerate(self.records):
            text = record["title"] + "\n" + record["state"]
            item = self.list.item(i)
            if item.text() != text:
                item.setText(text)
        index = self.list.currentRow()
        record = self.records[index] if 0 <= index < len(self.records) else None
        content = "\n".join(record["logs"]) if record else "选择操作查看日志；切换页面不会取消操作。"
        changed = record is not self._displayed_record
        if changed or content != self.logs.toPlainText():
            bar = self.logs.verticalScrollBar()
            position = bar.value()
            follow = changed or position >= bar.maximum() - 2
            self.logs.setPlainText(content)
            bar.setValue(bar.maximum() if follow else position)
        title = record["title"] if record else "操作日志"
        state = record["state"] if record else "未选择"
        self.operation_title.setText(title)
        if state != self.state_badge.text():
            self.state_badge.setText(state)
            self.state_badge.setTone("accent" if state == "执行中" else "success" if state == "已完成"
                                    else "warning" if state in ("未完成", "正在取消") else "neutral")
        self._displayed_record = record
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
        for record in self.records:
            item = QListWidgetItem(record["title"] + "\n" + record["state"])
            item.setSizeHint(QSize(180, 64))
            item.setToolTip(record["title"])
            self.list.addItem(item)
        self.list.setCurrentRow(0 if self.records else -1)
        self.list.blockSignals(False)
        self.refresh()
