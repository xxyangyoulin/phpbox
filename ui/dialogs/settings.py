"""设置对话框"""
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QApplication
from PyQt6.QtCore import Qt

from qfluentwidgets import (
    SubtitleLabel, BodyLabel, CaptionLabel, LineEdit,
    PushButton, PrimaryPushButton, CheckBox, ComboBox,
    CardWidget, StrongBodyLabel, FluentIcon as FIF,
    InfoBar, InfoBarPosition, MessageBox
)

from ui.worker import OperationWorker
from core.settings import Settings
from core.proxy import detect_system_proxy, sync_all_projects_proxy, validate_proxy_url
from ui.dialogs.environment_diagnostics import EnvironmentDiagnosticsDialog
from ui.styles import FluentDialog, apply_theme


class SettingsDialog(FluentDialog):
    """设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = Settings()
        self.setWindowTitle("设置")
        self.setMinimumSize(450, 350)
        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # 代理设置卡片
        proxy_card = CardWidget(self)
        proxy_layout = QVBoxLayout(proxy_card)
        proxy_layout.setSpacing(12)

        proxy_layout.addWidget(StrongBodyLabel("代理设置"))

        # 启用代理
        self.proxy_enabled_cb = CheckBox("启用代理")
        self.proxy_enabled_cb.stateChanged.connect(self.on_proxy_enabled_changed)
        proxy_layout.addWidget(self.proxy_enabled_cb)

        # 代理配置
        host_layout = QHBoxLayout()
        host_layout.addWidget(BodyLabel("代理地址:"))
        self.proxy_host_input = LineEdit()
        self.proxy_host_input.setPlaceholderText("127.0.0.1")
        host_layout.addWidget(self.proxy_host_input, 1)
        host_layout.addWidget(BodyLabel(":"))
        self.proxy_port_input = LineEdit()
        self.proxy_port_input.setPlaceholderText("7890")
        self.proxy_port_input.setFixedWidth(80)
        host_layout.addWidget(self.proxy_port_input)
        proxy_layout.addLayout(host_layout)

        # 检测到的系统代理
        self.system_proxy_label = CaptionLabel()
        proxy_layout.addWidget(self.system_proxy_label)

        # 使用系统代理按钮
        use_system_btn = PushButton("使用系统代理")
        use_system_btn.clicked.connect(self.use_system_proxy)
        proxy_layout.addWidget(use_system_btn)

        # 说明
        hint = CaptionLabel(
            "提示: 代理用于 Docker 构建时下载 PHP 扩展，\n"
            "仅在建项目和安装扩展时生效。"
        )
        proxy_layout.addWidget(hint)

        layout.addWidget(proxy_card)

        # 主题设置卡片
        theme_card = CardWidget(self)
        theme_layout = QVBoxLayout(theme_card)
        theme_layout.setSpacing(12)

        theme_layout.addWidget(StrongBodyLabel("主题设置"))

        theme_row = QHBoxLayout()
        theme_row.addWidget(BodyLabel("主题:"))
        self.theme_combo = ComboBox()
        self.theme_combo.addItems(["跟随系统", "浅色主题", "深色主题"])
        theme_row.addWidget(self.theme_combo)
        theme_row.addStretch()
        theme_layout.addLayout(theme_row)


        layout.addWidget(theme_card)

        # 环境诊断卡片
        diagnostics_card = CardWidget(self)
        diagnostics_layout = QVBoxLayout(diagnostics_card)
        diagnostics_layout.setSpacing(12)

        diagnostics_layout.addWidget(StrongBodyLabel("环境诊断"))
        diagnostics_layout.addWidget(CaptionLabel("检查 Docker、Compose、终端、系统打开器与代理设置。"))

        diagnostics_btn = PushButton("查看诊断")
        diagnostics_btn.clicked.connect(self.open_diagnostics)
        diagnostics_layout.addWidget(diagnostics_btn)

        layout.addWidget(diagnostics_card)

        layout.addStretch()

        # GitHub 说明
        github_label = CaptionLabel("如果你有任何建议和使用问题，欢迎到 GitHub 上提交 issue")
        github_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(github_label)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        reset_btn = PushButton("恢复默认")
        reset_btn.clicked.connect(self.reset_settings)
        btn_layout.addWidget(reset_btn)

        cancel_btn = PushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        self.save_btn = PrimaryPushButton(FIF.SAVE, "保存")
        self.save_btn.clicked.connect(self.save_settings)
        self.save_btn.setDefault(True)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)

        # 检测系统代理
        self.detect_system_proxy()

    def detect_system_proxy(self):
        """检测并显示系统代理"""
        proxy = detect_system_proxy()
        if proxy:
            self.system_proxy_label.setText(f"检测到: {proxy}")
            self.system_proxy_label.setStyleSheet("color: #22c55e;")
            self._system_proxy = proxy
        else:
            self.system_proxy_label.setText("未检测到系统代理")
            self.system_proxy_label.setStyleSheet("color: #888;")
            self._system_proxy = None

    def use_system_proxy(self):
        """使用系统代理"""
        if self._system_proxy:
            # 解析代理地址
            import re
            match = re.search(r'http://([^:]+):(\d+)', self._system_proxy)
            if match:
                self.proxy_host_input.setText(match.group(1))
                self.proxy_port_input.setText(match.group(2))
                self.proxy_enabled_cb.setChecked(True)
        else:
            InfoBar.info(
                title="提示",
                content="未检测到系统代理设置",
                orient=Qt.Orientation.Horizontal,
                parent=self
            )

    def on_proxy_enabled_changed(self, state):
        """代理启用状态改变"""
        enabled = state == Qt.CheckState.Checked.value
        self.proxy_host_input.setEnabled(enabled)
        self.proxy_port_input.setEnabled(enabled)

    def load_settings(self):
        """加载设置"""
        # 代理设置
        self.proxy_enabled_cb.setChecked(self.settings.is_proxy_enabled())
        self.proxy_host_input.setText(self.settings.get_proxy_host())
        self.proxy_port_input.setText(self.settings.get_proxy_port())

        # 主题设置
        theme = self.settings.get_theme()
        if theme == "light":
            self.theme_combo.setCurrentIndex(1)
        elif theme == "dark":
            self.theme_combo.setCurrentIndex(2)
        else:
            self.theme_combo.setCurrentIndex(0)

        self.on_proxy_enabled_changed(self.proxy_enabled_cb.checkState().value)

    def save_settings(self):
        """保存设置"""
        # 验证代理设置
        if self.proxy_enabled_cb.isChecked():
            host = self.proxy_host_input.text().strip()
            port = self.proxy_port_input.text().strip()
            if not host or not port:
                InfoBar.error(
                    title="验证失败",
                    content="请填写完整的代理地址和端口",
                    orient=Qt.Orientation.Horizontal,
                    parent=self
                )
                return
            if not port.isdigit() or not 1 <= int(port) <= 65535:
                InfoBar.error(
                    title="验证失败",
                    content="端口必须是 1–65535 之间的整数",
                    orient=Qt.Orientation.Horizontal,
                    parent=self
                )
                return

            try:
                validate_proxy_url(f"http://{host}:{port}")
            except ValueError as exc:
                InfoBar.error(title="代理格式无效", content=str(exc), parent=self)
                return

        # 保存代理设置
        self.settings.set_proxy(
            self.proxy_host_input.text().strip(),
            self.proxy_port_input.text().strip(),
            self.proxy_enabled_cb.isChecked()
        )
        current_proxy = self.settings.get_proxy()


        # 保存并立即应用主题
        theme_index = self.theme_combo.currentIndex()
        themes = ["auto", "light", "dark"]
        theme = themes[theme_index]
        self.settings.set_theme(theme)

        app = QApplication.instance()
        if theme == "auto":
            from ui.styles import detect_system_theme
            apply_theme(app, detect_system_theme())
        else:
            apply_theme(app, theme)

        self.save_btn.setEnabled(False)
        self.operation_worker = OperationWorker(lambda: sync_all_projects_proxy(current_proxy))
        self.operation_worker.succeeded.connect(self._on_proxy_synced)
        self.operation_worker.failed.connect(self._on_proxy_sync_failed)
        self.operation_worker.start()

    def _on_proxy_synced(self, result):
        self.save_btn.setEnabled(True)
        InfoBar.success(title="设置已保存", content=f"已同步 {result['dockerfiles']} 个配置和 {result['running_containers']} 个容器", parent=self.window())
        self.accept()

    def _on_proxy_sync_failed(self, message):
        self.save_btn.setEnabled(True)
        InfoBar.warning(title="设置已保存，但同步失败", content=message, parent=self)

    def reset_settings(self):
        """恢复默认设置"""
        w = MessageBox(
            "确认",
            "确定要恢复默认设置吗？",
            self
        )
        if w.exec():
            self.proxy_enabled_cb.setChecked(False)
            self.proxy_host_input.clear()
            self.proxy_port_input.clear()
            self.theme_combo.setCurrentIndex(0)

    def open_diagnostics(self):
        """打开环境诊断对话框"""
        EnvironmentDiagnosticsDialog(self).exec()
