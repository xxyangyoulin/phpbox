"""主题管理模块 - Fluent Design"""
import os
from PyQt6.QtWidgets import QApplication, QDialog, QLabel
from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QFontDatabase
from qfluentwidgets import (
    CustomStyleSheet, InfoBar, SimpleCardWidget, TextEdit, Theme, setCustomStyleSheet,
    setFont, setTheme, setThemeColor,
)
from core.logger import logger


DEFAULT_INFOBAR_DURATION = 5000


def _patch_infobar_duration():
    """为所有 InfoBar 设置默认自动关闭时长"""
    if getattr(InfoBar, "_phpbox_duration_patched", False):
        return

    def make_wrapper(method):
        def wrapper(*args, **kwargs):
            duration = kwargs.get("duration")
            if duration is None or duration <= 0:
                kwargs["duration"] = DEFAULT_INFOBAR_DURATION
            return method(*args, **kwargs)

        return wrapper

    for name in ("success", "error", "warning", "info"):
        setattr(InfoBar, name, staticmethod(make_wrapper(getattr(InfoBar, name))))

    InfoBar._phpbox_duration_patched = True


_patch_infobar_duration()


def themed_color(light: str, dark: str) -> str:
    """根据当前主题返回对应颜色"""
    from qfluentwidgets import isDarkTheme
    return dark if isDarkTheme() else light


class SurfaceCard(SimpleCardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBorderRadius(12)


class LogTextEdit(TextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setFamilies(["Cascadia Mono", "JetBrains Mono", "DejaVu Sans Mono", "Noto Sans CJK SC"])
        font.setPixelSize(13)
        self.setFont(font)
        base = "border-radius: 8px; padding: 8px;"
        active = "TextEdit:hover, TextEdit:focus { background: #1e1e1e; color: #d4d4d4; }"
        setCustomStyleSheet(
            self,
            f"TextEdit {{ background: #1e1e1e; color: #d4d4d4; border: 1px solid #d1d1d1; {base} }}" + active,
            f"TextEdit {{ background: #1e1e1e; color: #d4d4d4; border: 1px solid #3c3c3c; {base} }}" + active,
        )


class StatusBadge(QLabel):
    COLORS = {
        "accent": ("#e5f1fb", "#005fb8", "#153c5b", "#60cdff"),
        "success": ("#dff6dd", "#0f7b0f", "#223c22", "#6ccb5f"),
        "warning": ("#fff4ce", "#9d5d00", "#433519", "#fce100"),
        "neutral": ("#f0f0f0", "#606060", "#333333", "#cecece"),
    }

    def __init__(self, text="", parent=None, tone="neutral"):
        super().__init__(parent=parent)
        self.setText(text)
        setFont(self, 12)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        CustomStyleSheet(self).apply(self)
        self.setTone(tone)

    def setTone(self, tone):
        light_bg, light_fg, dark_bg, dark_fg = self.COLORS[tone]
        base = "border-radius: 5px; padding: 4px 9px; font-weight: 600;"
        setCustomStyleSheet(
            self,
            f"QLabel {{ background: {light_bg}; color: {light_fg}; {base} }}",
            f"QLabel {{ background: {dark_bg}; color: {dark_fg}; {base} }}",
        )


def detect_system_theme() -> str:
    """检测系统主题"""
    try:
        # 检查 GTK 主题
        result = os.popen("gsettings get org.gnome.desktop.interface gtk-theme 2>/dev/null").read().strip()
        if "dark" in result.lower():
            return "dark"
    except Exception:
        pass

    try:
        # 检查 KDE 主题
        result = os.popen("kreadconfig5 --group KDE --key LookAndFeelPackage 2>/dev/null").read().strip()
        if "dark" in result.lower():
            return "dark"
    except Exception:
        pass

    try:
        # 检查 color-scheme (GNOME 42+)
        result = os.popen("gsettings get org.gnome.desktop.interface color-scheme 2>/dev/null").read().strip()
        if "dark" in result.lower():
            return "dark"
        if "light" in result.lower():
            return "light"
    except Exception:
        pass

    return "light"


def apply_theme(app: QApplication, theme: str = "light"):
    """应用 Fluent 主题

    Args:
        app: QApplication 实例
        theme: 主题名称 ("light" 或 "dark")
    """
    setThemeColor("#0078d4")
    if theme == "dark":
        setTheme(Theme.DARK)
    else:
        setTheme(Theme.LIGHT)
    logger.debug(f"主题已切换为: {theme}")


def get_fluent_theme() -> Theme:
    """获取当前 Fluent 主题"""
    from qfluentwidgets import qconfig
    return qconfig.theme


class ThemeWatcher(QObject):
    """系统主题监听器"""

    themeChanged = pyqtSignal(str)  # 主题变化信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_theme = detect_system_theme()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check_theme)
        self._timer.start(1000)  # 每秒检查一次
        logger.debug(f"主题监听器已启动，当前主题: {self._current_theme}")

    def _check_theme(self):
        """检查系统主题是否变化"""
        new_theme = detect_system_theme()
        if new_theme != self._current_theme:
            logger.debug(f"检测到主题变化: {self._current_theme} -> {new_theme}")
            self._current_theme = new_theme
            self.themeChanged.emit(new_theme)

    def current_theme(self) -> str:
        """获取当前系统主题"""
        return self._current_theme

    def stop(self):
        """停止监听"""
        self._timer.stop()


class FluentDialog(QDialog):
    """自动适应主题的对话框基类"""

    def __init__(self, parent=None):
        super().__init__(parent)
        CustomStyleSheet(self).setCustomStyleSheet(
            "QDialog { background-color: #f3f3f3; }",
            "QDialog { background-color: #202020; }",
        ).apply(self)

    def reject(self):
        from PyQt6.QtCore import QTimer
        active = []
        for name in ("worker", "build_worker", "operation_worker", "prepare_worker", "log_thread"):
            worker = getattr(self, name, None)
            if worker is not None:
                try:
                    if worker.isRunning():
                        active.append(worker)
                except RuntimeError:
                    pass
        if active:
            for worker in active:
                if hasattr(worker, "stop"):
                    worker.stop()
            QTimer.singleShot(100, self.reject)
            return
        super().reject()

    def closeEvent(self, event):
        self.reject()
        event.ignore()
