"""日志查看器对话框"""
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget
from PyQt6.QtCore import QThread, pyqtSignal, QTimer
from pathlib import Path
import subprocess
import html
import threading
from collections import deque
from core.process import run_process
from ui.worker import register_worker

from qfluentwidgets import (
    PushButton, ComboBox, SearchLineEdit, TextEdit,
    BodyLabel, ToolButton, FluentIcon as FIF
)
from core.docker import DockerManager
from ui.styles import FluentDialog, themed_color


class LogReaderThread(QThread):
    error_occurred = pyqtSignal(str)

    def __init__(self, project_path: Path, service: str = None):
        super().__init__()
        register_worker(self)
        self.project_path = project_path
        self.service = service
        self.cancel_event = threading.Event()
        self.chunks = deque(maxlen=64)

    def run(self):
        try:
            command = DockerManager(self.project_path).get_compose_command()
            if not command:
                raise RuntimeError("未检测到 Docker Compose")
            command += ["logs", "-f", "--tail", "200"]
            if self.service:
                command.append(self.service)
            result = run_process(command, cwd=str(self.project_path), cancel=self.cancel_event,
                                 on_output=lambda text: self.chunks.append(text[-16384:]), timeout=86400)
            if result.returncode:
                self.error_occurred.emit(result.stdout[-2000:])
        except InterruptedError:
            pass
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def stop(self):
        self.cancel_event.set()


class LogViewerDialog(FluentDialog):
    """日志查看器对话框"""

    def __init__(self, project_path: Path, project_name: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.project_name = project_name
        self.log_thread = None
        self._reader_generation = 0

        self.setWindowTitle(f"日志查看器 - {project_name}")
        self.setMinimumSize(900, 600)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 工具栏
        toolbar = QHBoxLayout()

        # 服务选择
        toolbar.addWidget(BodyLabel("服务:"))
        self.service_combo = ComboBox()
        self.service_combo.addItems(["全部", "php", "nginx", "mysql", "redis", "cron"])
        self.service_combo.currentTextChanged.connect(self.change_service)
        toolbar.addWidget(self.service_combo)

        # 搜索
        self.search_input = SearchLineEdit()
        self.search_input.setPlaceholderText("搜索...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.filter_logs)
        toolbar.addWidget(self.search_input, 1)

        # 自动滚动
        self.auto_scroll_btn = ToolButton(FIF.SCROLL)
        self.auto_scroll_btn.setCheckable(True)
        self.auto_scroll_btn.setChecked(True)
        self.auto_scroll_btn.setToolTip("自动滚动")
        toolbar.addWidget(self.auto_scroll_btn)

        # 清空
        clear_btn = ToolButton(FIF.DELETE)
        clear_btn.clicked.connect(self.clear_logs)
        clear_btn.setToolTip("清空显示（保留日志文件）")
        toolbar.addWidget(clear_btn)

        layout.addLayout(toolbar)

        # 日志文本框
        self.log_text = TextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(f"""
            TextEdit {{
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
                border: 1px solid {themed_color('#ddd', '#3c3c3c')};
                border-radius: 4px;
            }}
        """)
        layout.addWidget(self.log_text)

        # 关闭按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = PushButton("关闭")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        # 开始读取日志
        self.log_text.document().setMaximumBlockCount(2000)
        self.flush_timer = QTimer(self)
        self.flush_timer.timeout.connect(self._flush_logs)
        self.flush_timer.start(100)
        self.start_log_reader()

    def start_log_reader(self, service: str = None):
        self._reader_generation += 1
        generation = self._reader_generation
        if self.log_thread and self.log_thread.isRunning():
            self.log_thread.stop()
            QTimer.singleShot(100, lambda: self._restart_reader(generation, service))
            return
        self.log_thread = LogReaderThread(self.project_path, service)
        self.log_thread.error_occurred.connect(self.on_error)
        self.log_thread.start()

    def _restart_reader(self, generation, service):
        if generation == self._reader_generation:
            self.start_log_reader(service)

    def _flush_logs(self):
        if not self.log_thread:
            return
        chunks = []
        while self.log_thread.chunks and len(chunks) < 8:
            chunks.append(self.log_thread.chunks.popleft())
        if chunks:
            self.log_text.append("".join("<p>" + html.escape(line[:4096]) + "</p>" for line in "".join(chunks).splitlines()))
            if self.auto_scroll_btn.isChecked():
                scrollbar = self.log_text.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())

    def on_error(self, error: str):
        """错误处理"""
        self.log_text.append(f'<span style="color: #f44747">Error: {html.escape(error)}</span>')

    def change_service(self, service: str):
        """切换服务"""
        self.clear_logs()
        if service == "全部":
            self.start_log_reader(None)
        else:
            self.start_log_reader(service)

    def filter_logs(self, text: str):
        """过滤日志 (简单实现)"""
        # TODO: 实现日志过滤
        pass

    def clear_logs(self):
        self.log_text.clear()
        if self.log_thread:
            self.log_thread.chunks.clear()

    def reject(self):
        self._reader_generation += 1
        if self.log_thread:
            self.log_thread.stop()
        super().reject()
