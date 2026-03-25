"""Docker 操作模块"""
import re
import time
import subprocess
import os
import shutil
from pathlib import Path
from typing import List, Optional, Callable, Tuple
from dataclasses import dataclass


def summarize_docker_error(error: str) -> str:
    """将原始 Docker 错误摘要为更易读的中文提示"""
    raw = (error or "").strip()
    if not raw:
        return "Docker 操作失败"

    lower = raw.lower()
    if "address already in use" in lower or "port is already allocated" in lower:
        match = re.search(r'(?<!\d)(\d{2,5})(?:->|:)', raw)
        port_text = f"端口 {match.group(1)} " if match else ""
        return f"{port_text}已被占用，请修改项目端口或停止冲突服务。"
    if "permission denied" in lower and "docker.sock" in lower:
        return "当前用户没有访问 Docker 的权限，请确认已加入 docker 用户组。"
    if "cannot connect to the docker daemon" in lower or "is the docker daemon running" in lower:
        return "无法连接到 Docker 服务，请确认 Docker 已启动。"
    if "pull access denied" in lower or "repository does not exist" in lower:
        return "镜像拉取失败，请检查镜像名称、网络或仓库访问权限。"
    if "build failed" in lower or "failed to solve" in lower:
        return "Docker 镜像构建失败，请检查 Dockerfile、网络和扩展下载日志。"
    if "no such service" in lower:
        return "Compose 配置中的服务不存在，请检查 docker-compose.yml。"
    if "yaml" in lower or "compose file" in lower or "parsing" in lower:
        return "Compose 配置解析失败，请检查 docker-compose.yml 格式。"
    if "manifest" in lower and "not found" in lower:
        return "镜像标签不存在，请检查 PHP 版本或基础镜像标签。"

    first_line = raw.splitlines()[0].strip()
    return first_line or "Docker 操作失败"


def collect_environment_diagnostics() -> List[Tuple[str, str]]:
    """收集 Linux 环境诊断信息"""
    diagnostics: List[Tuple[str, str]] = []

    def add_check(label: str, ok: bool, detail: str = ""):
        prefix = "正常" if ok else "缺失/异常"
        diagnostics.append((label, f"{prefix} · {detail}" if detail else prefix))

    docker_bin = shutil.which("docker")
    add_check("Docker 命令", bool(docker_bin), docker_bin or "未找到 docker")

    compose_detail = "未检测到 docker compose 或 docker-compose"
    compose_ok = False
    for cmd in (["docker", "compose", "version"], ["docker-compose", "version"]):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                compose_ok = True
                compose_detail = " ".join(cmd[:-1])
                break
        except Exception:
            continue
    add_check("Compose", compose_ok, compose_detail)

    terminal = os.environ.get("TERMINAL") or "x-terminal-emulator"
    available_terminal = next(
        (t for t in [terminal, "kitty", "alacritty", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"] if shutil.which(t)),
        None
    )
    add_check("终端模拟器", bool(available_terminal), available_terminal or "未找到常见终端")

    opener = next((c for c in ["xdg-open", "gio", "kioclient5", "kde-open5"] if shutil.which(c)), None)
    add_check("系统打开器", bool(opener), opener or "未找到 xdg-open/gio")

    try:
        log_dir = Path.home() / ".phpbox" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        test_file = log_dir / ".diagnose-write"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        add_check("日志目录", True, str(log_dir))
    except Exception:
        add_check("日志目录", False, str(Path.home() / ".phpbox" / "logs"))

    return diagnostics


@dataclass
class DockerResult:
    """Docker 命令执行结果"""
    success: bool
    output: str = ""
    error: str = ""
    raw_error: str = ""
    port_conflict: bool = False  # 是否是端口冲突
    port_conflict_detail: str = ""  # 端口冲突详情


class DockerManager:
    """Docker 管理器"""

    # compose 命令前缀（自动检测新版插件或旧版独立命令)
    _COMPOSE_CMD_NEW = ["docker", "compose"]      # 新版插件
    _COMPOSE_CMD_OLD = ["docker-compose"]           # 旧版独立

    _compose_cmd: List[str] = []
    _compose_checked: bool = False
    _APP_SERVICES = ["php", "nginx"]

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self._detect_compose()

    def _detect_compose(self):
        """检测可用的 docker compose 命令"""
        if self._compose_checked:
            return

        # 优先新版插件语法
        try:
            result = subprocess.run(
                self._COMPOSE_CMD_NEW + ["version"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                self._compose_cmd = self._COMPOSE_CMD_NEW
                self._compose_checked = True
                return
        except Exception:
            pass

        # 回退旧版独立命令
        try:
            result = subprocess.run(
                self._COMPOSE_CMD_OLD + ["version"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                self._compose_cmd = self._COMPOSE_CMD_OLD
                self._compose_checked = True
                return
        except Exception:
            pass

        self._compose_checked = True  # 标记已检测过

    def get_compose_command(self) -> List[str]:
        """获取当前可用的 compose 命令前缀"""
        self._detect_compose()
        return list(self._compose_cmd)

    def get_compose_command_text(self) -> str:
        """获取当前可用的 compose 命令文本"""
        compose_cmd = self.get_compose_command()
        if compose_cmd:
            return " ".join(compose_cmd)
        return "docker compose"

    def _run_command(self, args: List[str], capture: bool = True,
                     env: Optional[dict] = None) -> DockerResult:
        """执行 docker compose 命令"""
        if not self._compose_cmd:
            return DockerResult(
                success=False,
                error="未检测到 docker compose 或 docker-compose，请安装其中之一",
                raw_error="未检测到 docker compose 或 docker-compose，请安装其中之一"
            )

        try:
            run_env = os.environ.copy()
            if env:
                run_env.update(env)

            result = subprocess.run(
                self._compose_cmd + args,
                cwd=str(self.project_path),
                capture_output=capture,
                text=True,
                timeout=300,
                env=run_env
            )
            if result.returncode == 0:
                return DockerResult(success=True, output=result.stdout)
            else:
                raw_error = result.stderr.strip() or result.stdout.strip()
                return DockerResult(
                    success=False,
                    error=summarize_docker_error(raw_error),
                    raw_error=raw_error
                )
        except subprocess.TimeoutExpired:
            return DockerResult(success=False, error="命令执行超时", raw_error="命令执行超时")
        except Exception as e:
            raw_error = str(e)
            return DockerResult(success=False, error=summarize_docker_error(raw_error), raw_error=raw_error)

    def up(self, build: bool = False) -> DockerResult:
        """启动服务"""
        args = ["up", "-d"]
        if build:
            args.insert(1, "--build")
        result = self._run_command(args)
        if result.success:
            validation = self.ensure_services_running(self._APP_SERVICES, timeout=12)
            if validation.success:
                return result

            cleanup_result = self.down()
            cleanup_message = "已自动回滚并清理残留容器。" if cleanup_result.success else (
                f"自动回滚失败，请手动执行 {self.get_compose_command_text()} down。"
            )
            return DockerResult(
                success=False,
                error=f"{validation.error}\n\n{cleanup_message}",
                port_conflict=validation.port_conflict,
                port_conflict_detail=validation.port_conflict_detail,
            )

        cleanup_result = self.down()
        if cleanup_result.success:
            cleanup_message = "已自动回滚并清理残留容器。"
        else:
            cleanup_error = cleanup_result.error.strip() or "未知原因"
            cleanup_message = f"自动回滚失败，请手动执行 docker compose down。回滚错误: {cleanup_error}"

        error = result.error.strip() or "docker compose up 执行失败"
        return DockerResult(
            success=False,
            error=f"{error}\n\n{cleanup_message}",
            port_conflict=result.port_conflict,
            port_conflict_detail=result.port_conflict_detail,
        )

    def get_project_port(self) -> Optional[int]:
        """获取项目配置的端口

        Returns:
            端口号，如果无法获取则返回 None
        """
        compose_file = self.project_path / "docker-compose.yml"
        if compose_file.exists():
            try:
                content = compose_file.read_text()
                match = re.search(r'"(\d+):80"', content)
                if match:
                    return int(match.group(1))
            except Exception:
                pass
        return None

    def up_with_port_check(self, project_name: str, build: bool = False) -> DockerResult:
        """启动服务（带端口冲突检查）

        Args:
            project_name: 项目名称（用于排除自身的端口占用）
            build: 是否重新构建

        Returns:
            DockerResult，如果端口冲突则 port_conflict=True
        """
        from core.project import get_port_usage

        port = self.get_project_port()
        if port:
            usage = get_port_usage(port, project_name, include_configured_projects=False)
            if usage:
                return DockerResult(
                    success=False,
                    error=f"端口 {port} 已被 {usage} 占用",
                    port_conflict=True,
                    port_conflict_detail=f"端口 {port} 已被 {usage} 占用"
                )

        return self.up(build)

    def stop(self) -> DockerResult:
        """停止服务"""
        return self._run_command(["stop"])

    def restart(self) -> DockerResult:
        """重启服务"""
        port = self.get_project_port()
        if port:
            from core.project import get_port_usage

            project_name = self.project_path.name
            usage = get_port_usage(port, project_name, include_configured_projects=False)
            if usage:
                return DockerResult(
                    success=False,
                    error=f"端口 {port} 已被 {usage} 占用，无法重启项目",
                    port_conflict=True,
                    port_conflict_detail=f"端口 {port} 已被 {usage} 占用"
                )

        down_result = self.down()
        if not down_result.success:
            return DockerResult(
                success=False,
                error=down_result.error.strip() or "停止现有容器失败，无法继续重启"
            )

        return self.up()

    def down(self, remove_images: bool = False) -> DockerResult:
        """删除服务"""
        args = ["down"]
        if remove_images:
            args.append("--rmi")
            args.append("local")
        return self._run_command(args)

    def build(self, proxy: Optional[str] = None, no_cache: bool = False) -> DockerResult:
        """构建镜像"""
        env = {}
        if proxy:
            env["HTTP_PROXY"] = proxy
            env["HTTPS_PROXY"] = proxy
        args = ["build"]
        if no_cache:
            args.append("--no-cache")
        return self._run_command(args, env=env)

    def build_live(self, proxy: Optional[str] = None, no_cache: bool = False) -> int:
        """实时输出构建日志"""
        if not self._compose_cmd:
            print("未检测到 docker compose 或 docker-compose", file=sys.stderr)
            return 1

        env = os.environ.copy()
        if proxy:
            env["HTTP_PROXY"] = proxy
            env["HTTPS_PROXY"] = proxy

        args = ["build"]
        if no_cache:
            args.append("--no-cache")

        result = subprocess.run(
            self._compose_cmd + args,
            cwd=str(self.project_path),
            env=env
        )
        return result.returncode

    def get_logs(self, service: Optional[str] = None,
                 follow: bool = False) -> subprocess.Popen:
        """获取日志 (返回 Popen 对象用于实时输出)"""
        cmd = self.get_compose_command() + ["logs"]
        if not cmd:
            raise RuntimeError("未检测到 docker compose 或 docker-compose")
        if follow:
            cmd.append("-f")
        if service:
            cmd.append(service)

        return subprocess.Popen(
            cmd,
            cwd=str(self.project_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

    def exec_command(self, service: str, command: List[str],
                     user: Optional[str] = None) -> DockerResult:
        """在容器中执行命令"""
        args = ["exec"]
        if user:
            args.extend(["-u", user])
        args.append(service)
        args.extend(command)
        return self._run_command(args)

    def install_extensions(self, extensions: List[str]) -> DockerResult:
        """安装 PHP 扩展"""
        return self.exec_command(
            "php",
            ["install-php-extensions"] + extensions,
            user="root"
        )

    def restart_service(self, service: str) -> DockerResult:
        """重启单个服务"""
        return self._run_command(["restart", service])

    def get_image_name(self) -> str:
        """获取 PHP 镜像名称"""
        try:
            result = subprocess.run(
                self.get_compose_command() + ["images", "php", "--format", "json"],
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
                timeout=10
            )
            import json
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                if isinstance(data, list) and data:
                    return data[0].get("Repository", "")
                elif isinstance(data, dict):
                    return data.get("Repository", "")
        except Exception:
            pass

        # 回退：使用 docker-compose 项目名格式 (phpdev-{project_name}-php)
        return f"phpdev-{self.project_path.name.lower()}-php"

    def copy_config_from_image(self, image: str, container_path: str,
                               local_path: Path) -> bool:
        """从镜像复制配置文件"""
        try:
            result = subprocess.run(
                ["docker", "run", "--rm", image, "cat", container_path],
                capture_output=True,
                timeout=30
            )
            if result.returncode == 0:
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_bytes(result.stdout)
                return True
            else:
                print(f"复制配置失败: {image}:{container_path} - {result.stderr.decode()}")
        except Exception as e:
            print(f"复制配置失败: {e}")
        return False

    def get_php_info(self) -> dict:
        """获取 PHP 配置信息

        Returns:
            dict: 包含 PHP 配置信息的字典，获取失败返回空字典
        """
        info = {}
        try:
            # 获取 php -i 输出
            result = self.exec_command("php", ["php", "-i"])
            if not result.success:
                return info

            output = result.output
            lines = output.split("\n")

            # 解析配置项
            config_map = {
                "memory_limit": "memory_limit",
                "max_execution_time": "max_execution_time",
                "max_input_time": "max_input_time",
                "upload_max_filesize": "upload_max_filesize",
                "post_max_size": "post_max_size",
                "max_file_uploads": "max_file_uploads",
                "display_errors": "display_errors",
                "error_reporting": "error_reporting",
                "date.timezone": "date.timezone",
            }

            for line in lines:
                for key, config_key in config_map.items():
                    if line.startswith(f"{key} =>") or line.startswith(f"{key}="):
                        parts = line.split("=>") if "=>" in line else line.split("=")
                        if len(parts) >= 2:
                            value = parts[1].strip()
                            info[config_key] = value

            # 获取已安装扩展
            ext_result = self.exec_command("php", ["php", "-m"])
            if ext_result.success:
                extensions = [e.strip() for e in ext_result.output.split("\n") if e.strip()]
                # 过滤掉 [PHP Modules] 和 [Zend Modules] 这样的标题
                extensions = [e for e in extensions if not e.startswith("[")]
                # 去重
                extensions = list(dict.fromkeys(extensions))
                info["extensions"] = extensions

            # 检查 Xdebug 状态
            info["xdebug_enabled"] = "xdebug" in info.get("extensions", [])

            # 检查 OPCache 状态
            info["opcache_enabled"] = "Zend OPcache" in info.get("extensions", [])

        except Exception as e:
            print(f"获取 PHP 配置失败: {e}")

        return info

    def wait_until_running(self, service: str = "php", timeout: int = 30) -> bool:
        """等待容器进入运行状态

        Args:
            service: 服务名
            timeout: 超时秒数

        Returns:
            容器是否已运行
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                result = subprocess.run(
                    self.get_compose_command() + [
                        "ps", "--status", "running",
                        "--format", "{{.Service}}", service
                    ],
                    cwd=str(self.project_path),
                    capture_output=True, text=True, timeout=5
                )
                if service in result.stdout:
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def ensure_services_running(self, services: List[str], timeout: int = 12) -> DockerResult:
        """确认指定服务都已进入 running 状态"""
        missing = []
        for service in services:
            if not self.wait_until_running(service, timeout=timeout):
                missing.append(service)

        if not missing:
            return DockerResult(success=True)

        detail = ", ".join(missing)
        error = f"服务未完全启动成功，未运行的容器: {detail}"

        port = self.get_project_port()
        if "nginx" in missing and port:
            error += f"\n\n可能原因: 宿主机端口 {port} 冲突，或 nginx 配置启动失败。"
            return DockerResult(
                success=False,
                error=error,
                port_conflict=True,
                port_conflict_detail=f"宿主机端口 {port} 可能冲突",
            )

        return DockerResult(success=False, error=error)
