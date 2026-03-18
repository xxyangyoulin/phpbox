"""日志查看器对话框"""
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from pathlib import Path
import subprocess

from qfluentwidgets import (
    PushButton, ComboBox, SearchLineEdit, TextEdit,
    BodyLabel, ToolButton, FluentIcon as FIF
)
from ui.styles import FluentDialog


class LogReaderThread(QThread):
    """日志读取线程"""
    line_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, project_path: Path, service: str = None):
        super().__init__()
        self.project_path = project_path
        self.service = service
        self.process = None
        self._running = True

    def run(self):
        cmd = ["docker", "compose", "logs", "-f"]
        if self.service:
            cmd.append(self.service)

        self.process = subprocess.Popen(
            cmd,
            cwd=str(self.project_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        try:
            for line in self.process.stdout:
                if not self._running:
                    break
                self.line_received.emit(line.rstrip())
        except Exception as e:
            self.error_occurred.emit(str(e))

    def stop(self):
        self._running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()


class LogViewerDialog(FluentDialog):
    """日志查看器对话框"""

    def __init__(self, project_path: Path, project_name: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.project_name = project_name
        self.log_thread = None

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
        self.service_combo.addItems(["全部", "php", "nginx"])
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
        clear_btn.setToolTip("清空日志")
        toolbar.addWidget(clear_btn)

        layout.addLayout(toolbar)

        # 日志文本框
        self.log_text = TextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            TextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
            }
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
        self.start_log_reader()

    def start_log_reader(self, service: str = None):
        """启动日志读取"""
        if self.log_thread:
            self.log_thread.stop()
            self.log_thread.wait()

        self.log_thread = LogReaderThread(self.project_path, service)
        self.log_thread.line_received.connect(self.append_log)
        self.log_thread.error_occurred.connect(self.on_error)
        self.log_thread.start()

    def append_log(self, line: str):
        """追加日志行"""
        # 简单的颜色处理
        color = "#d4d4d4"
        if "error" in line.lower() or "fatal" in line.lower():
            color = "#f44747"
        elif "warn" in line.lower():
            color = "#dcdcaa"
        elif "info" in line.lower():
            color = "#3794ff"

        self.log_text.append(f'<span style="color: {color}">{line}</span>')

        if self.auto_scroll_btn.isChecked():
            scrollbar = self.log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def on_error(self, error: str):
        """错误处理"""
        self.log_text.append(f'<span style="color: #f44747">Error: {error}</span>')

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
        """清空日志"""
        self.log_text.clear()

    def closeEvent(self, event):
        """关闭事件"""
        if self.log_thread:
            self.log_thread.stop()
            self.log_thread.wait()
        super().closeEvent(event)
