from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout
from qfluentwidgets import BodyLabel, CaptionLabel, HyperlinkButton, PushButton, StrongBodyLabel

from core.updates import REPOSITORY_URL
from core.version import VERSION
from ui.styles import SurfaceCard


class AboutCard(SurfaceCard):
    def __init__(self, checker, parent=None):
        super().__init__(parent)
        self.checker = checker
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        header = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(QPixmap(str(Path(__file__).resolve().parents[2] / 'resources/icons/phpbox-256.png')).scaled(
            48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        header.addWidget(icon)
        title = QVBoxLayout()
        title.addWidget(StrongBodyLabel('关于 PHPBox'))
        title.addWidget(CaptionLabel('当前版本：' + VERSION))
        header.addLayout(title)
        header.addStretch()
        layout.addLayout(header)
        layout.addWidget(HyperlinkButton(REPOSITORY_URL, REPOSITORY_URL, self))
        description = CaptionLabel('欢迎在 GitHub 查看源码、提交问题或获取最新版本。')
        description.setWordWrap(True)
        layout.addWidget(description)
        self.status = BodyLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        hint = CaptionLabel('启动后自动检查更新，之后每 6 小时检查一次；发现新版本时发送系统通知。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        self.check_button = PushButton('检查更新')
        self.check_button.clicked.connect(checker.check)
        buttons.addWidget(self.check_button)
        self.release_button = PushButton('查看发布页')
        self.release_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(checker.release_url)))
        buttons.addWidget(self.release_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        checker.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.status.setText(self.checker.status)
        self.check_button.setEnabled(self.checker.reply is None)
