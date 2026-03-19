"""修改端口对话框"""

import subprocess
import threading

from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal, QThread

from qfluentwidgets import (
    BodyLabel, SpinBox, PrimaryPushButton, PushButton,
    StrongBodyLabel, FluentIcon as FIF,
    InfoBar, InfoBarPosition, ProgressRing
)

from core.project import Project, ProjectManager, get_port_usage
from ui.styles import FluentDialog


class RestartWorker(QThread):
    """重启容器工作线程"""
    finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, project_path: str):
        super().__init__()
        self.project_path = project_path

    def run(self):
        try:
            # 先停止
            subprocess.run(
                ["docker", "compose", "down"],
                cwd=self.project_path,
                capture_output=True,
                timeout=60
            )
            # 再启动
            result = subprocess.run(
                ["docker", "compose", "up", "-d"],
                cwd=self.project_path,
                capture_output=True,
                timeout=120
            )
            if result.returncode == 0:
                self.finished.emit(True, "容器已重启")
            else:
                self.finished.emit(False, result.stderr.decode()[:200] if result.stderr else "重启失败")
        except subprocess.TimeoutExpired:
            self.finished.emit(False, "操作超时")
        except Exception as e:
            self.finished.emit(False, str(e))


class ChangePortDialog(FluentDialog):
    """修改端口对话框"""

    # 信号：端口修改成功
    port_changed = pyqtSignal(int)

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self.project_manager = ProjectManager()
        self.worker = None
        self.setWindowTitle("修改端口")
        self.setMinimumSize(360, 220)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 20)

        # 当前端口
        current_layout = QHBoxLayout()
        current_layout.addWidget(BodyLabel("当前端口:"))
        self.current_label = BodyLabel(self.project.port)
        self.current_label.setStyleSheet("color: #64748b; font-weight: bold;")
        current_layout.addWidget(self.current_label)
        current_layout.addStretch()
        layout.addLayout(current_layout)

        # 新端口
        port_layout = QHBoxLayout()
        port_layout.addWidget(BodyLabel("新端口:"))
        self.port_spin = SpinBox()
        self.port_spin.setRange(1, 65535)
        try:
            self.port_spin.setValue(int(self.project.port))
        except ValueError:
            self.port_spin.setValue(8080)
        self.port_spin.valueChanged.connect(self._check_port)
        port_layout.addWidget(self.port_spin, 1)

        # 端口状态
        self.port_status = BodyLabel()
        self.port_status.setStyleSheet("color: #10b981;")
        port_layout.addWidget(self.port_status)
        port_layout.addStretch()
        layout.addLayout(port_layout)

        # 提示（如果容器运行中）
        if self.project.is_running:
            hint = BodyLabel("修改端口后将自动重启容器")
            hint.setStyleSheet("color: #3b82f6; font-size: 12px;")
        else:
            hint = BodyLabel("容器未运行，修改后需手动启动")
            hint.setStyleSheet("color: #f59e0b; font-size: 12px;")
        layout.addWidget(hint)

        # 进度指示器（默认隐藏）
        self.progress_layout = QHBoxLayout()
        self.progress_ring = ProgressRing()
        self.progress_ring.setFixedSize(24, 24)
        self.progress_label = BodyLabel("正在重启容器...")
        self.progress_layout.addWidget(self.progress_ring)
        self.progress_layout.addWidget(self.progress_label)
        self.progress_layout.addStretch()
        layout.addLayout(self.progress_layout)
        self.progress_ring.setVisible(False)
        self.progress_label.setVisible(False)

        layout.addStretch()

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = PushButton("取消")
        self.cancel_btn.clicked.connect(self._cancel)
        btn_layout.addWidget(self.cancel_btn)

        self.save_btn = PrimaryPushButton(FIF.SAVE, "保存")
        self.save_btn.clicked.connect(self._save)
        self.save_btn.setDefault(True)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)

        # 初始检查端口（在按钮创建后）
        self._check_port()

    def _check_port(self):
        """检查端口是否可用"""
        port = self.port_spin.value()
        # 排除当前项目
        process = get_port_usage(port, self.project.name)
        if process:
            self.port_status.setText(f"❌ 被 {process} 占用")
            self.port_status.setStyleSheet("color: #ef4444;")
            self.save_btn.setEnabled(False)
        else:
            self.port_status.setText("✓ 可用")
            self.port_status.setStyleSheet("color: #10b981;")
            self.save_btn.setEnabled(True)

    def _set_processing(self, processing: bool):
        """设置处理中状态"""
        self.progress_ring.setVisible(processing)
        self.progress_label.setVisible(processing)
        self.save_btn.setEnabled(not processing)
        self.cancel_btn.setEnabled(not processing)
        if processing:
            self.save_btn.setText("处理中...")
        else:
            self.save_btn.setText("保存")

    def _save(self):
        """保存端口设置"""
        new_port = self.port_spin.value()

        # 检查端口是否变化
        if str(new_port) == self.project.port:
            InfoBar.success(
                title="提示",
                content="端口未变化",
                orient=Qt.Orientation.Horizontal,
                parent=self.window()
            )
            return

        # 再次检查端口可用性
        process = get_port_usage(new_port, self.project.name)
        if process:
            InfoBar.error(
                title="错误",
                content=f"端口 {new_port} 被 {process} 占用",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                parent=self
            )
            return

        # 修改端口
        if self.project_manager.set_port(self.project, new_port):
            # 如果容器正在运行，自动重启
            if self.project.is_running:
                self._set_processing(True)
                self.worker = RestartWorker(str(self.project.path))
                self.worker.finished.connect(self._on_restart_finished)
                self.worker.start()
            else:
                self.port_changed.emit(new_port)
                InfoBar.success(
                    title="成功",
                    content=f"端口已修改为 {new_port}",
                    orient=Qt.Orientation.Horizontal,
                    duration=3000,
                    parent=self.window()
                )
                self.accept()
        else:
            InfoBar.error(
                title="错误",
                content="修改端口失败",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                parent=self
            )

    def _on_restart_finished(self, success: bool, message: str):
        """重启完成回调"""
        self._set_processing(False)
        new_port = self.port_spin.value()

        if success:
            self.port_changed.emit(new_port)
            InfoBar.success(
                title="成功",
                content=f"端口已修改为 {new_port}，容器已重启",
                orient=Qt.Orientation.Horizontal,
                duration=3000,
                parent=self.window()
            )
            self.accept()
        else:
            InfoBar.error(
                title="重启失败",
                content=f"端口已修改但容器重启失败: {message}",
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )
            # 仍然关闭对话框，因为端口已经修改
            self.accept()

    def _cancel(self):
        """取消操作"""
        if self.worker and self.worker.isRunning():
            return  # 正在处理中，禁止取消
        self.reject()
