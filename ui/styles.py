"""主题管理模块 - Fluent Design"""
import os
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from qfluentwidgets import setTheme, Theme
from core.logger import logger


def themed_color(light: str, dark: str) -> str:
    """根据当前主题返回对应颜色"""
    from qfluentwidgets import isDarkTheme
    return dark if isDarkTheme() else light


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
        self._apply_theme_background()

    def _apply_theme_background(self):
        """根据当前主题设置背景色"""
        from qfluentwidgets import isDarkTheme
        if isDarkTheme():
            self.setStyleSheet("QDialog { background-color: #1e1e1e; }")
        else:
            self.setStyleSheet("QDialog { background-color: #ffffff; }")
