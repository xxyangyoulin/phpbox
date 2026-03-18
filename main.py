#!/usr/bin/env python3
"""PHP 开发环境管理器 - 程序入口"""
import sys
import argparse
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QSettings
from ui.main_window import MainWindow
from ui.styles import apply_theme, ThemeWatcher
from core.logger import logger


def main():
    """主函数"""
    # 命令行参数解析
    parser = argparse.ArgumentParser(description="PHP 开发环境管理器")
    parser.add_argument("--hide", action="store_true", help="启动时隐藏主窗口，只显示托盘图标")
    parser.add_argument("--new-project", action="store_true", help="打开新建项目对话框")
    args = parser.parse_args()

    # 高 DPI 支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("PHP 开发环境管理器")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("PHPDev")
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
