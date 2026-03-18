"""重命名项目对话框"""
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal, QThread

from qfluentwidgets import (
    BodyLabel, LineEdit, PrimaryPushButton, PushButton,
    CardWidget, StrongBodyLabel, FluentIcon as FIF,
    InfoBar, ProgressRing
)

from core.project import Project, ProjectManager
from ui.styles import FluentDialog


class RenameWorker(QThread):
    """重命名项目工作线程"""
    finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, project: Project, new_name: str):
        super().__init__()
        self.project = project
        self.new_name = new_name
        self.project_manager = ProjectManager()

    def run(self):
        try:
            success = self.project_manager.rename_project(self.project, self.new_name)
            if success:
                self.finished.emit(True, self.new_name)
            else:
                self.finished.emit(False, "重命名失败，请查看日志")
        except Exception as e:
            self.finished.emit(False, str(e))


class RenameProjectDialog(FluentDialog):
    """重命名项目对话框"""

    # 信号：重命名成功 (old_name, new_name)
    project_renamed = pyqtSignal(str, str)

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self.project_manager = ProjectManager()
        self.worker = None
        self.setWindowTitle("重命名项目")
        self.setMinimumSize(400, 200)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # 卡片
        card = CardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)

        card_layout.addWidget(StrongBodyLabel("重命名项目"))

        # 当前名称
        current_layout = QHBoxLayout()
        current_layout.addWidget(BodyLabel("当前名称:"))
        self.current_label = BodyLabel(self.project.name)
        self.current_label.setStyleSheet("color: #64748b;")
        current_layout.addWidget(self.current_label)
        current_layout.addStretch()
        card_layout.addLayout(current_layout)

        # 新名称输入
        name_layout = QHBoxLayout()
        name_layout.addWidget(BodyLabel("新名称:"))
        self.name_input = LineEdit()
        self.name_input.setText(self.project.name)
        self.name_input.setPlaceholderText("仅允许字母、数字、下划线和连字符")
        name_layout.addWidget(self.name_input, 1)
        card_layout.addLayout(name_layout)

        # 进度指示器（默认隐藏）
        self.progress_layout = QHBoxLayout()
        self.progress_ring = ProgressRing()
        self.progress_ring.setFixedSize(30, 30)
        self.progress_label = BodyLabel("正在重命名...")
        self.progress_layout.addWidget(self.progress_ring)
        self.progress_layout.addWidget(self.progress_label)
        self.progress_layout.addStretch()
        card_layout.addLayout(self.progress_layout)
        self.progress_ring.setVisible(False)
        self.progress_label.setVisible(False)

        # 提示
        self.hint = BodyLabel("注意: 重命名会停止正在运行的容器")
        self.hint.setStyleSheet("color: #f59e0b; font-size: 12px;")
        card_layout.addWidget(self.hint)

        layout.addWidget(card)
        layout.addStretch()

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = PushButton("取消")
        self.cancel_btn.clicked.connect(self.cancel)
        btn_layout.addWidget(self.cancel_btn)

        self.rename_btn = PrimaryPushButton(FIF.EDIT, "重命名")
        self.rename_btn.clicked.connect(self.rename_project)
        self.rename_btn.setDefault(True)
        btn_layout.addWidget(self.rename_btn)

        layout.addLayout(btn_layout)

    def rename_project(self):
        """执行重命名"""
        new_name = self.name_input.text().strip()

        # 验证新名称
        valid, msg = self.project_manager.is_valid_name(new_name)
        if not valid:
            InfoBar.error(
                title="验证失败",
                content=msg,
                orient=Qt.Orientation.Horizontal,
                parent=self
            )
            return

        # 检查名称是否变化
        if new_name == self.project.name:
            self.reject()
            return

        # 检查新名称是否已存在
        if self.project_manager.project_exists(new_name):
            InfoBar.error(
                title="错误",
                content=f"项目 '{new_name}' 已存在",
                orient=Qt.Orientation.Horizontal,
                parent=self
            )
            return

        # 显示处理中状态
        self._set_processing(True)

        # 启动后台线程
        self.worker = RenameWorker(self.project, new_name)
        self.worker.finished.connect(self._on_rename_finished)
        self.worker.start()

    def _set_processing(self, processing: bool):
        """设置处理中状态"""
        self.progress_ring.setVisible(processing)
        self.progress_label.setVisible(processing)
        self.hint.setVisible(not processing)
        self.rename_btn.setEnabled(not processing)
        self.cancel_btn.setEnabled(not processing)

        if processing:
            self.rename_btn.setText("处理中...")
        else:
            self.rename_btn.setText("重命名")

    def _on_rename_finished(self, success: bool, message: str):
        """重命名完成回调"""
        self._set_processing(False)

        if success:
            self.project_renamed.emit(self.project.name, message)
            InfoBar.success(
                title="成功",
                content=f"项目已重命名为 '{message}'",
                orient=Qt.Orientation.Horizontal,
                parent=self.window()
            )
            self.accept()
        else:
            InfoBar.error(
                title="错误",
                content=message,
                orient=Qt.Orientation.Horizontal,
                parent=self
            )

    def cancel(self):
        """取消操作"""
        if self.worker and self.worker.isRunning():
            # 正在处理中，禁止取消
            return
        self.reject()
