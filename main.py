#!/usr/bin/env python3
"""PHP 开发环境管理器 - 程序入口"""
import sys
import subprocess
import argparse
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt, QSettings, qInstallMessageHandler, QtMsgType
from ui.main_window import MainWindow
from ui.styles import apply_theme, ThemeWatcher
from core.logger import logger


_SUPPRESSED_QT_WARNINGS = (
    "QPainter::",
    "QWidgetEffectSourcePrivate::",
)


def _qt_message_handler(msg_type, context, message):
    if msg_type == QtMsgType.QtWarningMsg and any(
        message.startswith(p) for p in _SUPPRESSED_QT_WARNINGS
    ):
        return
    if msg_type == QtMsgType.QtCriticalMsg:
        print(f"Qt Critical: {message}", file=sys.stderr)
    elif msg_type == QtMsgType.QtFatalMsg:
        print(f"Qt Fatal: {message}", file=sys.stderr)


def main():
    """主函数"""
    # 命令行参数解析
    parser = argparse.ArgumentParser(description="PHP 开发环境管理器")
    parser.add_argument("--hide", action="store_true", help="启动时隐藏主窗口，只显示托盘图标")
    parser.add_argument("--new-project", action="store_true", help="打开新建项目对话框")
    args = parser.parse_args()

    qInstallMessageHandler(_qt_message_handler)

    # 高 DPI 支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("PHP 开发环境管理器")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("phpbox")
    app.setQuitOnLastWindowClosed(False)  # 关闭窗口不退出，托盘运行

    # 加载设置
    settings = QSettings()
    theme_setting = settings.value("theme", "auto")

    # 创建主题监听器（仅在 auto 模式下启用）
    theme_watcher = None

    def on_theme_changed(new_theme: str):
        """主题变化回调"""
        apply_theme(app, new_theme)

    if theme_setting == "auto":
        theme_watcher = ThemeWatcher()
        theme_watcher.themeChanged.connect(on_theme_changed)
        theme = theme_watcher.current_theme()
    else:
        theme = theme_setting

    # 应用 Fluent 主题
    apply_theme(app, theme)

    # 检查 Docker 是否可用
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True, timeout=10, check=True
        )
    except Exception:
        QMessageBox.critical(
            None, "Docker 未就绪",
            "无法连接到 Docker 守护进程。\n请确认 Docker 已安装并正在运行。"
        )
        sys.exit(1)

    window = MainWindow()

    # 根据参数决定是否显示窗口
    if args.hide:
        # 启动时隐藏窗口，只显示托盘图标
        window.hide()
    elif args.new_project:
        # 打开新建项目对话框
        window.show()
        window.create_project()
    else:
        window.show()

    result = app.exec()

    # 清理
    if theme_watcher:
        theme_watcher.stop()

    sys.exit(result)


if __name__ == "__main__":
    main()
