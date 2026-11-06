#!/usr/bin/env python3
"""PHP 开发环境管理器 - 程序入口"""
import os
import sys
import subprocess
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

if (
    not os.environ.get("QT_QPA_PLATFORM")
    and (
        os.environ.get("WAYLAND_DISPLAY")
        or os.environ.get("XDG_SESSION_TYPE") == "wayland"
    )
):
    os.environ["QT_QPA_PLATFORM"] = "wayland;xcb"

from core.cli import parse_args, run_cli
from core.version import VERSION


_SUPPRESSED_QT_WARNINGS = (
    "QPainter::",
    "QWidgetEffectSourcePrivate::",
)


def _qt_message_handler(msg_type, context, message):
    from PyQt6.QtCore import QtMsgType

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
    args = parse_args()
    if args.command and args.command != 'gui':
        sys.exit(run_cli(args))
    if args.directory:
        os.chdir(Path(args.directory).expanduser())

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt, QSettings, qInstallMessageHandler
    from ui.main_window import MainWindow
    from ui.styles import apply_theme, ThemeWatcher
    from ui.single_instance import SingleInstance

    qInstallMessageHandler(_qt_message_handler)

    # 高 DPI 支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("PHP 开发环境管理器")
    app.setApplicationVersion(VERSION)
    app.setOrganizationName("phpbox")
    app.setQuitOnLastWindowClosed(False)  # 关闭窗口不退出，托盘运行

    request = "hide" if args.hide else ("new-project" if args.new_project else "show")
    instance = SingleInstance(request, app)
    if not instance.is_primary:
        return
    app.aboutToQuit.connect(instance.close)

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
    docker_ready = True
    docker_error = ""
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True, timeout=10, check=True
        )
    except Exception as e:
        docker_ready = False
        docker_error = str(e) or "无法连接到 Docker 守护进程，请确认 Docker 已安装并正在运行。"

    window = MainWindow(docker_ready=docker_ready, docker_error=docker_error)

    def activate_existing(request):
        if request not in {"show", "new-project"}:
            return
        window.showNormal()
        window.raise_()
        window.activateWindow()
        if request == "new-project":
            window.create_project()

    instance.requested.connect(activate_existing)

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

    if window.restart_args is not None:
        # aboutToQuit 已释放单实例地址；替换当前进程，避免新旧实例竞争。
        command = [sys.executable]
        env = os.environ.copy()
        if getattr(sys, "frozen", False):
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        else:
            command.append(str(Path(__file__).resolve()))
        os.execve(sys.executable, command + window.restart_args, env)

    sys.exit(result)


if __name__ == "__main__":
    main()
