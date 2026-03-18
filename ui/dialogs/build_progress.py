"""构建进度对话框"""
import html
import re
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from PyQt6.QtCore import Qt, QTimer

from qfluentwidgets import (
    SubtitleLabel, BodyLabel, CaptionLabel,
    ProgressBar, PushButton, CardWidget,
    TextEdit, FluentIcon as FIF, IconWidget
)

from ui.styles import FluentDialog


class BuildProgressDialog(FluentDialog):
    """Fluent 风格的构建进度对话框"""

    # 构建阶段定义
    STAGES = [
        ("准备构建环境", FIF.PLAY),
        ("下载镜像 & 安装扩展", FIF.DOWNLOAD),
        ("配置容器", FIF.SETTING),
        ("启动服务", FIF.POWER_BUTTON),
    ]

    def __init__(self, project_name: str, parent=None):
        super().__init__(parent)
        self.project_name = project_name
        self.setWindowTitle("构建项目")
        self.setMinimumSize(650, 500)
        self.resize(700, 550)
        # 设置为窗口模态，避免被窗口管理器识别为独立窗口
        self.setWindowModality(Qt.WindowModality.WindowModal)

        self._current_stage = 0
        self._log_count = 0
        self._cancelled = False
        self._progress_value = 0

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 24)

        # 标题区域
        title_layout = QHBoxLayout()
        self.spinner = IconWidget(FIF.SYNC, self)
        self.spinner.setFixedSize(24, 24)
        self.title_label = SubtitleLabel(f"正在构建「{self.project_name}」")
        title_layout.addWidget(self.spinner)
        title_layout.addWidget(self.title_label)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        # 阶段指示器
        self.stage_widget = self._create_stage_indicator()
        layout.addWidget(self.stage_widget)

        # 日志区域卡片
        log_card = CardWidget(self)
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(12, 12, 12, 12)
        log_layout.setSpacing(8)

        # 日志标题行
        log_header = QHBoxLayout()
        log_header.addWidget(BodyLabel("构建日志"))
        self.log_count_label = CaptionLabel("0 行")
        log_header.addStretch()
        log_header.addWidget(self.log_count_label)
        log_layout.addLayout(log_header)

        # 日志文本区域
        self.log_text = TextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("等待构建输出...")
        self.log_text.setMinimumHeight(200)
        self.log_text.setStyleSheet("""
            TextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
                font-size: 12px;
                padding: 8px;
            }
        """)
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_card, 1)

        # 进度条区域
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(8)

        self.progress_bar = ProgressBar()
        self.progress_bar.setMinimumHeight(8)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        # 进度信息行
        info_layout = QHBoxLayout()
        self.progress_label = CaptionLabel("0%")
        self.status_label = CaptionLabel("准备中...")
        info_layout.addWidget(self.status_label)
        info_layout.addStretch()
        info_layout.addWidget(self.progress_label)
        progress_layout.addLayout(info_layout)
        layout.addLayout(progress_layout)

        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.cancel_btn = PushButton(FIF.CANCEL, "取消构建")
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        # 启动旋转动画
        self._spin_angle = 0
        self._spin_timer = QTimer()
        self._spin_timer.timeout.connect(self._animate_spinner)
        self._spin_timer.start(50)

    def _create_stage_indicator(self) -> QWidget:
        """创建阶段指示器"""
        widget = QWidget()
        widget.setMinimumHeight(50)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(0)

        self.stage_labels = []

        for i, (text, icon) in enumerate(self.STAGES):
            # 阶段容器
            stage_layout = QVBoxLayout()
            stage_layout.setSpacing(6)

            # 文字
            label = CaptionLabel(text)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            label.setMinimumHeight(32)
            label.setEnabled(False)
            self.stage_labels.append(label)
            stage_layout.addWidget(label)

            layout.addLayout(stage_layout, 1)

            # 连接线（除了最后一个）
            if i < len(self.STAGES) - 1:
                line = QWidget()
                line.setFixedHeight(2)
                line.setStyleSheet("background-color: #3c3c3c;")
                layout.addWidget(line, 1)

        # 激活第一阶段
        self._set_stage(0)

        return widget

    def _set_stage(self, stage: int):
        """设置当前阶段"""
        self._current_stage = stage

        # 激活样式
        active_style = "color: #0078d4; font-weight: bold;"
        done_style = "color: #22c55e;"
        inactive_style = "color: #64748b;"

        for i, label in enumerate(self.stage_labels):
            if i < stage:
                # 已完成
                label.setStyleSheet(done_style)
            elif i == stage:
                # 当前进行中
                label.setStyleSheet(active_style)
            else:
                # 未开始
                label.setStyleSheet(inactive_style)

    def _animate_spinner(self):
        """旋转动画"""
        if self._cancelled:
            return
        self._spin_angle = (self._spin_angle + 15) % 360
        # 简单的旋转效果通过透明度变化模拟
        opacity = 0.5 + 0.5 * abs((self._spin_angle % 180) - 90) / 90
        self.spinner.setStyleSheet(f"opacity: {opacity};")

    def append_log(self, line: str):
        """追加日志行"""
        self._log_count += 1
        self.log_count_label.setText(f"{self._log_count} 行")

        # 颜色判断
        lower_line = line.lower()
        if "error" in lower_line or "fatal" in lower_line or "failed" in lower_line:
            color = "#f44747"  # 红色 - 错误
        elif "warn" in lower_line:
            color = "#dcdcaa"  # 黄色 - 警告
        elif "success" in lower_line or "installed" in lower_line or "done" in lower_line:
            color = "#22c55e"  # 绿色 - 成功
        elif "#" in line and ("[" in line or "]" in line):
            color = "#569cd6"  # 蓝色 - Docker 构建步骤
        else:
            color = "#d4d4d4"  # 默认灰色

        escaped = html.escape(line)
        self.log_text.append(f'<span style="color: {color};">{escaped}</span>')

        # 自动滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        # 根据日志内容推断阶段
        self._infer_stage_from_log(line)

        # 更新进度
        self._update_progress_from_log(line)

    def _infer_stage_from_log(self, line: str):
        """根据日志内容推断当前阶段"""
        lower = line.lower()

        if "install-php-extensions" in lower or "downloading" in lower or "fetch" in lower:
            if self._current_stage < 1:
                self._set_stage(1)
                self.status_label.setText("正在下载和安装扩展...")
        elif "configuring" in lower or "copying" in lower:
            if self._current_stage < 2:
                self._set_stage(2)
                self.status_label.setText("正在配置容器...")
        elif "starting" in lower or "up-to-date" in lower:
            if self._current_stage < 3:
                self._set_stage(3)
                self.status_label.setText("正在启动服务...")

    def _update_progress_from_log(self, line: str):
        """根据日志更新进度条"""
        # 尝试从 Docker 构建输出中提取进度
        # 格式如: #12 [stage-1 3/5] RUN ...
        match = re.search(r'#(\d+)\s+(?:DONE|ERROR)', line)
        if match:
            step = int(match.group(1))
            # 假设最多 30 步
            progress = min(95, int((step / 30) * 100))
            self._progress_value = progress
            self.progress_bar.setValue(progress)
            self.progress_label.setText(f"{progress}%")

    def set_progress(self, value: int, status: str = None):
        """手动设置进度"""
        self._progress_value = min(100, max(0, value))
        self.progress_bar.setValue(self._progress_value)
        self.progress_label.setText(f"{self._progress_value}%")
        if status:
            self.status_label.setText(status)

    def set_building(self):
        """设置为构建中状态"""
        self._set_stage(1)
        self.status_label.setText("正在构建镜像...")

    def set_finished(self, success: bool, message: str = None):
        """设置完成状态"""
        self._spin_timer.stop()

        if success:
            self._set_stage(3)
            self.progress_bar.setValue(100)
            self.progress_label.setText("100%")
            self.status_label.setText("构建完成!")
            self.title_label.setText(f"「{self.project_name}」构建完成")
            self.spinner.setIcon(FIF.COMPLETED)
            self.spinner.setStyleSheet("color: #22c55e;")
            self.cancel_btn.setText("关闭")
            self.cancel_btn.setIcon(FIF.ACCEPT)
        else:
            self.title_label.setText(f"「{self.project_name}」构建失败")
            self.spinner.setIcon(FIF.INFO)
            self.spinner.setStyleSheet("color: #f44747;")
            self.status_label.setText(message or "构建失败")
            self.cancel_btn.setText("关闭")

    def _on_cancel(self):
        """取消/关闭按钮"""
        if self._cancelled:
            # 已经在取消中，直接关闭
            self.reject()
            return

        if self.progress_bar.value() >= 100 or self.title_label.text().endswith("构建失败"):
            # 已完成或失败，直接关闭
            self.accept()
            return

        # 取消构建
        self._cancelled = True
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("正在取消...")
        self.status_label.setText("正在取消构建...")
        self.reject()

    @property
    def cancelled(self) -> bool:
        return self._cancelled
