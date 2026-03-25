#!/usr/bin/env python3
"""PHP 开发环境管理器 - 程序入口"""
import os
import sys
import subprocess
import argparse
import shlex
import unicodedata
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

from core.logger import logger
from core.project import ProjectManager, get_project_code_path
from core.docker import DockerManager, collect_environment_diagnostics
from core.settings import Settings


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


def _build_parser():
    parser = argparse.ArgumentParser(description="PHP 开发环境管理器")
    parser.add_argument("--hide", action="store_true", help="启动时隐藏主窗口，只显示托盘图标")
    parser.add_argument("--new-project", action="store_true", help="打开新建项目对话框")

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list", help="列出所有项目")
    subparsers.add_parser("ps", help="快速查看项目状态")

    status_parser = subparsers.add_parser("status", help="查看项目状态")
    status_parser.add_argument("name", nargs="?", help="项目名称")

    command_help = {
        "start": "启动项目",
        "stop": "停止项目",
        "restart": "重启项目",
        "up": "快速启动项目",
        "down": "停止并移除项目容器",
    }
    for command in ("start", "stop", "restart", "up", "down"):
        command_parser = subparsers.add_parser(command, help=command_help[command])
        command_parser.add_argument("name", nargs="?", help="项目名称")

    for command, help_text in (("build", "构建项目镜像"), ("rebuild", "重新构建项目镜像")):
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument("name", nargs="?", help="项目名称")
        command_parser.add_argument("--no-cache", action="store_true", help="构建时不使用缓存")

    logs_parser = subparsers.add_parser("logs", help="查看项目日志")
    logs_parser.add_argument("name", nargs="?", help="项目名称")
    logs_parser.add_argument("--service", choices=["php", "nginx", "mysql", "redis"], help="指定服务")
    logs_parser.add_argument("--follow", "-f", action="store_true", default=True, help="持续追踪日志输出")
    logs_parser.add_argument("--no-follow", action="store_false", dest="follow", help="只输出当前日志，不持续追踪")

    shell_parser = subparsers.add_parser("shell", help="进入当前项目容器")
    shell_parser.add_argument("service", nargs="?", choices=["php", "nginx", "mysql", "redis"], default="php", help="容器服务名")

    exec_parser = subparsers.add_parser("exec", help="在当前项目容器中执行命令")
    exec_parser.add_argument("service", choices=["php", "nginx", "mysql", "redis"], help="容器服务名")
    exec_parser.add_argument("args", nargs=argparse.REMAINDER, help="要执行的命令，使用 -- 与 phpbox 参数分隔")

    php_parser = subparsers.add_parser("php", help="在当前项目中执行 php 命令")
    php_parser.add_argument("args", nargs=argparse.REMAINDER, help="传给 php 的参数")

    composer_parser = subparsers.add_parser("composer", help="在当前项目中执行 composer 命令")
    composer_parser.add_argument("args", nargs=argparse.REMAINDER, help="传给 composer 的参数")

    artisan_parser = subparsers.add_parser("artisan", help="在当前项目中执行 php artisan 命令")
    artisan_parser.add_argument("args", nargs=argparse.REMAINDER, help="传给 artisan 的参数")

    think_parser = subparsers.add_parser("think", help="在当前项目中执行 php think 命令")
    think_parser.add_argument("args", nargs=argparse.REMAINDER, help="传给 think 的参数")

    subparsers.add_parser("doctor", help="检查运行环境")
    return parser


def _find_project(manager: ProjectManager, name: str):
    for project in manager.get_all_projects():
        if project.name == name:
            return project
    return None


def _find_project_by_cwd(manager: ProjectManager, cwd: Path):
    cwd = cwd.resolve()
    for project in manager.get_all_projects():
        try:
            cwd.relative_to(project.path.resolve())
            return project
        except ValueError:
            continue
    return None


def _resolve_target_project(manager: ProjectManager, name: str | None):
    if name:
        return _find_project(manager, name)
    return _find_project_by_cwd(manager, Path.cwd())


def _print_project_not_found(name: str):
    print(f"未找到项目: {name}", file=sys.stderr)
    print("可执行 `phpbox list` 查看可用项目。", file=sys.stderr)


def _print_project_context_required():
    print("当前目录不在任何项目内，且未指定项目名称。", file=sys.stderr)
    print("请切换到项目目录后重试，或显式传入项目名称。", file=sys.stderr)
    print("可执行 `phpbox list` 查看可用项目。", file=sys.stderr)


def _print_action_result(result, success_message: str) -> int:
    if result.success:
        if result.output.strip():
            print(result.output.strip())
        else:
            print(success_message)
        return 0

    print(result.error, file=sys.stderr)
    return 1


def _resolve_container_workdir(project, cwd: Path) -> str:
    code_path = get_project_code_path(project.path, project.name)
    try:
        relative = cwd.resolve().relative_to(code_path.resolve())
    except ValueError:
        return "/var/www/html"
    return "/var/www/html" if str(relative) == "." else f"/var/www/html/{relative.as_posix()}"


def _run_project_command(project, command_name: str, command_args) -> int:
    docker = DockerManager(project.path)
    compose_cmd = docker.get_compose_command()
    if not compose_cmd:
        print("未检测到 docker compose 或 docker-compose", file=sys.stderr)
        return 1

    workdir = _resolve_container_workdir(project, Path.cwd())
    inner_parts = [f"cd {shlex.quote(workdir)}", command_name]
    inner_parts.extend(shlex.quote(arg) for arg in command_args)
    inner_command = " && ".join([inner_parts[0], " ".join(inner_parts[1:])])

    result = subprocess.run(
        compose_cmd + ["exec", "php", "sh", "-lc", inner_command],
        cwd=str(project.path)
    )
    return result.returncode


def _run_project_shell(project, service: str) -> int:
    docker = DockerManager(project.path)
    compose_cmd = docker.get_compose_command()
    if not compose_cmd:
        print("未检测到 docker compose 或 docker-compose", file=sys.stderr)
        return 1

    if service == "php":
        shell_command = (
            f"cd {shlex.quote(_resolve_container_workdir(project, Path.cwd()))} && "
            "if command -v zsh >/dev/null 2>&1; then exec zsh; "
            "elif command -v bash >/dev/null 2>&1; then exec bash; "
            "else exec sh; fi"
        )
    else:
        shell_command = "if command -v sh >/dev/null 2>&1; then exec sh; else exec ash; fi"

    result = subprocess.run(
        compose_cmd + ["exec", service, "sh", "-lc", shell_command],
        cwd=str(project.path)
    )
    return result.returncode


def _run_project_exec(project, service: str, command_args) -> int:
    if not command_args:
        print("请提供要执行的命令，例如 `phpbox exec php -- php -v`。", file=sys.stderr)
        return 1

    docker = DockerManager(project.path)
    compose_cmd = docker.get_compose_command()
    if not compose_cmd:
        print("未检测到 docker compose 或 docker-compose", file=sys.stderr)
        return 1

    args = list(command_args)
    if args and args[0] == "--":
        args = args[1:]
    if not args:
        print("请提供要执行的命令，例如 `phpbox exec php -- php -v`。", file=sys.stderr)
        return 1

    exec_args = compose_cmd + ["exec"]
    if service == "php":
        exec_args.extend(["-w", _resolve_container_workdir(project, Path.cwd())])
    exec_args.append(service)
    exec_args.extend(args)

    result = subprocess.run(exec_args, cwd=str(project.path))
    return result.returncode


def _format_table(rows):
    widths = [max(_display_width(str(row[i])) for row in rows) for i in range(len(rows[0]))]
    return "\n".join(
        "  ".join(_pad_cell(str(cell), widths[i]) for i, cell in enumerate(row))
        for row in rows
    )


def _display_width(text: str) -> int:
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


def _pad_cell(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def _print_project(project):
    url = f"http://localhost:{project.port}" if project.port.isdigit() else "-"
    return (
        project.name,
        project.status_text,
        f"PHP {project.php_version}",
        f"端口 {project.port}",
        url,
    )


def _print_project_detail(project):
    print(f"名称: {project.name}")
    print(f"路径: {project.path}")
    print(f"状态: {project.status_text}")
    print(f"健康: {project.health_summary}")
    print(f"PHP: {project.php_version}")
    print(f"端口: {project.port}")
    print(f"自启动: {'开启' if project.auto_restart else '关闭'}")
    print(f"服务状态: PHP {'运行' if project.php_running else '停止'} / Nginx {'运行' if project.nginx_running else '停止'}")
    if project.has_service("mysql"):
        print(f"MySQL: {'运行' if project.mysql_running else '停止'}")
    if project.has_service("redis"):
        print(f"Redis: {'运行' if project.redis_running else '停止'}")
    if project.port.isdigit():
        print(f"访问地址: http://localhost:{project.port}")


def _run_cli(args) -> int:
    manager = ProjectManager()
    command = args.command
    target_name = getattr(args, "name", None)

    if command == "ps":
        command = "status"
    elif command == "up":
        command = "start"

    if command == "list":
        projects = manager.get_all_projects()
        if not projects:
            print("暂无项目")
            return 0
        rows = [("名称", "状态", "PHP", "端口", "URL")]
        rows.extend(_print_project(project) for project in projects)
        print(_format_table(rows))
        return 0

    if command == "status":
        if target_name:
            project = _find_project(manager, target_name)
            if not project:
                _print_project_not_found(target_name)
                return 1
            _print_project_detail(project)
            return 0

        current_project = _find_project_by_cwd(manager, Path.cwd())
        if current_project:
            _print_project_detail(current_project)
            return 0

        projects = manager.get_all_projects()
        if not projects:
            print("暂无项目")
            return 0
        rows = [("名称", "状态", "PHP", "端口", "健康")]
        rows.extend(
            (
                project.name,
                project.status_text,
                f"PHP {project.php_version}",
                project.port,
                project.health_summary,
            )
            for project in projects
        )
        print(_format_table(rows))
        return 0

    if command in {"start", "stop", "restart", "down", "logs", "build", "rebuild"}:
        project = _resolve_target_project(manager, target_name)
        if not project:
            if target_name:
                _print_project_not_found(target_name)
            else:
                _print_project_context_required()
            return 1

        docker = DockerManager(project.path)

        if command == "start":
            result = docker.up_with_port_check(project.name)
            return _print_action_result(result, "启动成功")

        if command == "stop":
            result = docker.stop()
            return _print_action_result(result, "停止成功")

        if command == "restart":
            result = docker.restart()
            return _print_action_result(result, "重启成功")

        if command == "down":
            result = docker.down()
            return _print_action_result(result, "已停止并移除容器")

        if command in {"build", "rebuild"}:
            proxy = Settings().get_proxy()
            returncode = docker.build_live(proxy=proxy, no_cache=args.no_cache)
            if returncode == 0:
                print("构建成功")
            return returncode

        try:
            process = docker.get_logs(service=args.service, follow=args.follow)
            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="")
            return process.wait()
        except KeyboardInterrupt:
            return 130
        except Exception as e:
            print(str(e), file=sys.stderr)
            return 1

    if args.command in {"shell", "exec", "php", "composer", "artisan", "think"}:
        project = _find_project_by_cwd(manager, Path.cwd())
        if not project:
            _print_project_context_required()
            return 1
        if args.command == "shell":
            return _run_project_shell(project, args.service)
        if args.command == "exec":
            return _run_project_exec(project, args.service, args.args)
        if args.command == "artisan":
            return _run_project_command(project, "php", ["artisan", *args.args])
        if args.command == "think":
            return _run_project_command(project, "php", ["think", *args.args])
        return _run_project_command(project, args.command, args.args)

    if args.command == "doctor":
        diagnostics = collect_environment_diagnostics()
        for label, detail in diagnostics:
            print(f"{label}: {detail}")

        docker_ready = True
        docker_error = ""
        try:
            subprocess.run(["docker", "info"], capture_output=True, timeout=10, check=True)
        except Exception as e:
            docker_ready = False
            docker_error = str(e) or "无法连接到 Docker 守护进程"

        print(f"Docker 服务: {'正常' if docker_ready else '异常'}")
        if docker_error:
            print(f"详情: {docker_error}")
        return 0 if docker_ready else 1

    return -1


def main():
    """主函数"""
    parser = _build_parser()
    args, unknown_args = parser.parse_known_args()

    if args.command in {"exec", "php", "composer", "artisan", "think"}:
        args.args = list(getattr(args, "args", [])) + unknown_args
    elif unknown_args:
        parser.error(f"unrecognized arguments: {' '.join(unknown_args)}")

    if args.command:
        sys.exit(_run_cli(args))

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt, QSettings, qInstallMessageHandler
    from ui.main_window import MainWindow
    from ui.styles import apply_theme, ThemeWatcher

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
