"""环境诊断对话框"""
import shutil

from PyQt6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout
from PyQt6.QtCore import Qt

from qfluentwidgets import (
    BodyLabel, CaptionLabel, CardWidget, PrimaryPushButton,
    PushButton, StrongBodyLabel, TextEdit, FluentIcon as FIF, InfoBar
)

from core.docker import collect_environment_diagnostics
from core.proxy import detect_system_proxy
from core.settings import Settings
from ui.styles import FluentDialog


class EnvironmentDiagnosticsDialog(FluentDialog):
    """环境诊断对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("环境诊断")
        self.setMinimumSize(620, 480)
        self._setup_ui()
        self.refresh_diagnostics()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        card = CardWidget(self)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)
        card_layout.addWidget(StrongBodyLabel("系统环境"))

        hint = CaptionLabel("用于排查 Docker、Compose、终端、系统打开器和代理配置问题。")
        hint.setStyleSheet("color: #64748b;")
        card_layout.addWidget(hint)

        self.text = TextEdit()
        self.text.setReadOnly(True)
        self.text.setMinimumHeight(320)
        card_layout.addWidget(self.text)

        layout.addWidget(card)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        refresh_btn = PushButton("刷新")
        refresh_btn.clicked.connect(self.refresh_diagnostics)
        btn_layout.addWidget(refresh_btn)

        copy_btn = PushButton("复制结果")
        copy_btn.clicked.connect(self.copy_result)
        btn_layout.addWidget(copy_btn)

        close_btn = PrimaryPushButton(FIF.ACCEPT, "关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def refresh_diagnostics(self):
        settings = Settings()
        diagnostics = collect_environment_diagnostics()
        diagnostics.extend([
            ("系统代理", detect_system_proxy() or "未检测到"),
            ("全局代理", settings.get_proxy() or "未配置"),
            ("主题设置", settings.get_theme()),
            ("PATH 中的 docker", shutil.which("docker") or "未找到"),
        ])

        lines = []
        for label, value in diagnostics:
            lines.append(f"{label}\n  {value}")
        self.text.setPlainText("\n\n".join(lines))

    def copy_result(self):
        QApplication.clipboard().setText(self.text.toPlainText())
        InfoBar.success(
            title="已复制",
            content="诊断结果已复制到剪贴板",
            orient=Qt.Orientation.Horizontal,
            parent=self
        )
