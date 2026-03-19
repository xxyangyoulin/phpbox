"""项目设置对话框"""
import threading

from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal, QThread

from qfluentwidgets import (
    BodyLabel, LineEdit, PrimaryPushButton, PushButton,
    CardWidget, StrongBodyLabel, CheckBox, FluentIcon as FIF,
    InfoBar, ProgressRing
)

from core.project import Project, ProjectManager, get_port_usage
from core.docker import DockerManager
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
    """项目设置对话框"""

    # 信号：重命名成功 (old_name, new_name)
    project_renamed = pyqtSignal(str, str)
    # 信号：设置已更改
    settings_changed = pyqtSignal()

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self.project_manager = ProjectManager()
        self.worker = None
        self.setWindowTitle("项目设置")
        self.setMinimumSize(400, 280)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # 重命名卡片
        card1 = CardWidget()
        card1_layout = QVBoxLayout(card1)
        card1_layout.setSpacing(12)

        card1_layout.addWidget(StrongBodyLabel("重命名项目"))

        # 当前名称
        current_layout = QHBoxLayout()
        current_layout.addWidget(BodyLabel("当前名称:"))
        self.current_label = BodyLabel(self.project.name)
        self.current_label.setStyleSheet("color: #64748b;")
        current_layout.addWidget(self.current_label)
        current_layout.addStretch()
        card1_layout.addLayout(current_layout)

        # 新名称输入
        name_layout = QHBoxLayout()
        name_layout.addWidget(BodyLabel("新名称:"))
        self.name_input = LineEdit()
        self.name_input.setText(self.project.name)
        self.name_input.setPlaceholderText("仅允许字母、数字、下划线和连字符")
        name_layout.addWidget(self.name_input, 1)
        card1_layout.addLayout(name_layout)

        # 进度指示器（默认隐藏）
        self.progress_layout = QHBoxLayout()
        self.progress_ring = ProgressRing()
        self.progress_ring.setFixedSize(30, 30)
        self.progress_label = BodyLabel("正在重命名...")
        self.progress_layout.addWidget(self.progress_ring)
        self.progress_layout.addWidget(self.progress_label)
        self.progress_layout.addStretch()
        card1_layout.addLayout(self.progress_layout)
        self.progress_ring.setVisible(False)
        self.progress_label.setVisible(False)

        # 提示
        self.hint = BodyLabel("注意: 重命名会停止正在运行的容器")
        self.hint.setStyleSheet("color: #f59e0b; font-size: 12px;")
        card1_layout.addWidget(self.hint)

        layout.addWidget(card1)

        # 容器设置卡片
        card2 = CardWidget()
        card2_layout = QVBoxLayout(card2)
        card2_layout.setSpacing(12)

        card2_layout.addWidget(StrongBodyLabel("容器设置"))

        # 开机自启
        self.auto_restart_cb = CheckBox("开机自启")
        self.auto_restart_cb.setChecked(self.project.auto_restart)
        self.auto_restart_cb.setToolTip("容器随 Docker 服务自动启动")
        card2_layout.addWidget(self.auto_restart_cb)

        layout.addWidget(card2)
        layout.addStretch()

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = PushButton("取消")
        self.cancel_btn.clicked.connect(self.cancel)
        btn_layout.addWidget(self.cancel_btn)

        self.save_btn = PrimaryPushButton(FIF.SAVE, "保存")
        self.save_btn.clicked.connect(self.save_settings)
        self.save_btn.setDefault(True)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)

    def save_settings(self):
        """保存设置"""
        # 先保存开机自启设置
        new_auto_restart = self.auto_restart_cb.isChecked()
        if new_auto_restart != self.project.auto_restart:
            if self.project_manager.set_auto_restart(self.project, new_auto_restart):
                self.project.auto_restart = new_auto_restart
                self.settings_changed.emit()

                # 如果项目正在运行，需要执行 docker compose up -d 来应用更改
                if self.project.is_running:
                    threading.Thread(
                        target=self._async_apply_restart_policy,
                        args=(str(self.project.path),),
                        daemon=True
                    ).start()
            else:
                InfoBar.error(
                    title="错误",
                    content="无法保存开机自启设置",
                    orient=Qt.Orientation.Horizontal,
                    parent=self
                )
                return

        # 然后处理重命名
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
            # 名称没变，只保存了其他设置
            InfoBar.success(
                title="成功",
                content="设置已保存",
                orient=Qt.Orientation.Horizontal,
                parent=self.window()
            )
            self.accept()
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
        self.save_btn.setEnabled(not processing)
        self.cancel_btn.setEnabled(not processing)

        if processing:
            self.save_btn.setText("处理中...")
        else:
            self.save_btn.setText("保存")

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

    def _async_apply_restart_policy(self, project_path: str):
        """异步应用 restart 策略"""
        try:
            docker = DockerManager(project_path)
            compose_cmd = docker.get_compose_command()
            if not compose_cmd:
                return
            # 检查端口是否被占用
            port = None
            try:
                port = int(self.project.port)
            except (ValueError, AttributeError):
                pass

            if port:
                usage = get_port_usage(port, self.project.name, include_configured_projects=False)
                if usage:
                    print(f"端口 {port} 已被 {usage} 占用，跳过重启")
                    return

            docker.up()
        except Exception as e:
            print(f"应用 restart 策略失败: {e}")
