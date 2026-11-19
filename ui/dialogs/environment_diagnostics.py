"""环境诊断对话框"""
import shutil
from typing import List, Tuple

from PyQt6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt

from qfluentwidgets import (
    BodyLabel, CaptionLabel, PrimaryPushButton,
    PushButton, ScrollArea, StrongBodyLabel, FluentIcon as FIF, InfoBar
)

from core.docker import collect_environment_diagnostics
from core.proxy import detect_system_proxy
from core.settings import Settings
from ui.styles import SurfaceCard, FluentDialog, themed_color
from ui.worker import OperationWorker


class DiagnosticRow(QWidget):
    """单条诊断行"""

    def __init__(self, label: str, value: str, ok: bool, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(2)
        title = StrongBodyLabel(label)
        detail = CaptionLabel(value)
        detail.setWordWrap(True)
        detail.setTextColor(QColor("#606060"), QColor("#cecece"))
        left.addWidget(title)
        left.addWidget(detail)
        layout.addLayout(left, 1)

        badge = BodyLabel("正常" if ok else "异常")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedWidth(64)
        badge.setStyleSheet(
            "background-color: #22c55e; color: white; border-radius: 12px; padding: 4px 8px;"
            if ok else
            "background-color: #f59e0b; color: white; border-radius: 12px; padding: 4px 8px;"
        )
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)


class EnvironmentDiagnosticsDialog(FluentDialog):
    """环境诊断对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("环境诊断")
        self.setMinimumSize(680, 560)
        self._checking = False
        self._setup_ui()
        self.refresh_diagnostics()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        summary_card = SurfaceCard(self)
        summary_layout = QHBoxLayout(summary_card)
        summary_layout.setContentsMargins(18, 16, 18, 16)
        summary_layout.setSpacing(20)

        text_wrap = QVBoxLayout()
        text_wrap.setSpacing(4)
        text_wrap.addWidget(StrongBodyLabel("系统环境诊断"))
        hint = CaptionLabel("用于排查 Docker、Compose、终端、系统打开器、代理和日志目录问题。")
        hint.setTextColor(QColor("#606060"), QColor("#cecece"))
        text_wrap.addWidget(hint)
        summary_layout.addLayout(text_wrap, 1)

        self.summary_label = BodyLabel("--")
        self.summary_label.setStyleSheet(f"color: {themed_color('#0f172a', '#e2e8f0')}; font-weight: 600;")
        summary_layout.addWidget(self.summary_label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(summary_card)

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("ScrollArea { background: transparent; border: none; }")
        self.container = QWidget()
        self.scroll_layout = QVBoxLayout(self.container)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(12)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll, 1)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.refresh_btn = PushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_diagnostics)
        btn_layout.addWidget(self.refresh_btn)

        self.copy_btn = PushButton("复制结果")
        self.copy_btn.clicked.connect(self.copy_result)
        btn_layout.addWidget(self.copy_btn)

        close_btn = PrimaryPushButton(FIF.ACCEPT, "关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def _add_group(self, title: str, rows: List[Tuple[str, str, bool]]):
        card = SurfaceCard(self)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(4)
        card_layout.addWidget(StrongBodyLabel(title))

        for label, value, ok in rows:
            card_layout.addWidget(DiagnosticRow(label, value, ok, card))

        self.scroll_layout.addWidget(card)

    def refresh_diagnostics(self):
        if self._checking:
            return
        self._checking = True
        self.refresh_btn.setEnabled(False)
        self.copy_btn.setEnabled(False)
        self.summary_label.setText('正在检查环境…')
        self.diagnostics_worker = OperationWorker(self._collect_diagnostics)
        self.diagnostics_worker.succeeded.connect(self._show_diagnostics)
        self.diagnostics_worker.failed.connect(self._diagnostics_failed)
        self.diagnostics_worker.start()

    @staticmethod
    def _collect_diagnostics():
        settings = Settings()
        base_rows = []
        all_rows = collect_environment_diagnostics()
        for label, value in all_rows:
            ok = value.startswith("正常")
            base_rows.append((label, value, ok))

        system_proxy = detect_system_proxy()
        proxy = settings.get_proxy()
        docker = shutil.which("docker")
        proxy_rows = [
            ("系统代理", system_proxy or "未检测到", bool(system_proxy)),
            ("全局代理", proxy or "未配置", bool(proxy)),
            ("主题设置", settings.get_theme(), True),
            ("PATH 中的 docker", docker or "未找到", bool(docker)),
        ]
        return base_rows, proxy_rows

    def _show_diagnostics(self, result):
        self._checking = False
        self.refresh_btn.setEnabled(True)
        self.copy_btn.setEnabled(True)
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        base_rows, proxy_rows = result
        ok_count = sum(1 for _, _, ok in base_rows + proxy_rows if ok)
        total = len(base_rows) + len(proxy_rows)
        self.summary_label.setText(f"{ok_count}/{total} 项状态正常")

        self._add_group("运行环境", base_rows)
        self._add_group("代理与应用设置", proxy_rows)
        self.scroll_layout.addStretch(1)

    def _diagnostics_failed(self, message):
        self._checking = False
        self.refresh_btn.setEnabled(True)
        self.summary_label.setText('检查失败，请重试')
        if self.isVisible():
            InfoBar.error('环境诊断失败', message, parent=self)

    def copy_result(self):
        lines = [self.summary_label.text()]
        for i in range(self.scroll_layout.count()):
            item = self.scroll_layout.itemAt(i)
            card = item.widget()
            if not card:
                continue
            texts = card.findChildren(CaptionLabel) + card.findChildren(StrongBodyLabel)
            extracted = [t.text() for t in texts if t.text()]
            if extracted:
                lines.extend(extracted)
                lines.append("")
        QApplication.clipboard().setText("\n".join(lines).strip())
        InfoBar.success(
            title="已复制",
            content="诊断结果已复制到剪贴板",
            orient=Qt.Orientation.Horizontal,
            parent=self
        )
