"""项目管理核心逻辑"""
import errno
import json
import os
import re
import time
import socket
import subprocess
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Tuple, Set
from .config import BASE_DIR, ensure_base_dir
from .docker import DockerManager

LEGACY_CODE_DIR_NAME = "src"


def get_project_code_dir_name(project_name: str) -> str:
    """返回新项目默认使用的代码目录名"""
    return project_name


def get_project_code_path(project_path: Path, project_name: str) -> Path:
    """获取项目代码目录，兼容历史 src 结构"""
    new_code_path = project_path / get_project_code_dir_name(project_name)
    legacy_code_path = project_path / LEGACY_CODE_DIR_NAME

    if new_code_path.exists():
        return new_code_path
    if legacy_code_path.exists():
        return legacy_code_path
    return new_code_path


@dataclass
class Project:
    """项目数据类"""
    name: str
    path: Path
    php_version: str = "未知"
    port: str = "未知"
    is_running: bool = False
    php_running: bool = False
    nginx_running: bool = False
    mysql_running: bool = False
    redis_running: bool = False
    cron_running: bool = False
    auto_restart: bool = True  # 是否开机自启

    @property
    def status_text(self) -> str:
        if self.health_status == "healthy":
            return "运行中"
        if self.php_running or self.nginx_running or self.mysql_running or self.redis_running or self.cron_running:
            return "部分运行"
        return "已停止"

    @property
    def health_status(self) -> str:
        services = ["php", "nginx"] + [name for name in ("mysql", "redis", "cron") if self.has_service(name)]
        if all(getattr(self, name + "_running") for name in services):
            return "healthy"
        if self.php_running or self.nginx_running or self.mysql_running or self.redis_running or self.cron_running:
            return "partial"
        return "stopped"

    @property
    def health_summary(self) -> str:
        php_text = "运行" if self.php_running else "停止"
        nginx_text = "运行" if self.nginx_running else "停止"
        parts = [f"PHP {php_text}", f"Nginx {nginx_text}"]
        if self.has_service("mysql"):
            parts.append(f"MySQL {'运行' if self.mysql_running else '停止'}")
        if self.has_service("redis"):
            parts.append(f"Redis {'运行' if self.redis_running else '停止'}")
        if self.has_service("cron"):
            parts.append(f"Cron {'运行' if self.cron_running else '停止'}")
        return " / ".join(parts)

    def has_service(self, service: str) -> bool:
        compose_file = self.path / "docker-compose.yml"
        if not compose_file.exists():
            return False
        try:
            content = compose_file.read_text()
        except Exception:
            return False
        return re.search(rf"^  {re.escape(service)}:\n", content, re.MULTILINE) is not None


class ProjectManager:
    """项目管理器"""

    def __init__(self):
        ensure_base_dir()
        self._running_containers: Set[str] = set()
        self._running_containers_ts: float = 0

    def get_all_projects(self) -> List[Project]:
        """获取所有项目列表"""
        projects = []
        if not BASE_DIR.exists():
            return projects

        for item in sorted(BASE_DIR.iterdir()):
            if item.is_dir():
                project = self._load_project(item)
                if project:
                    projects.append(project)
        return projects

    def _load_project(self, path: Path) -> Optional[Project]:
        """加载单个项目信息"""
        compose_file = path / "docker-compose.yml"
        if not compose_file.exists():
            return None

        name = path.name
        php_version = self._get_php_version(path)
        port = self._get_port(path)
        php_running = self._check_service_running(path, "php")
        nginx_running = self._check_service_running(path, "nginx")
        mysql_running = self._check_service_running(path, "mysql")
        redis_running = self._check_service_running(path, "redis")
        is_running = php_running and nginx_running
        auto_restart = self._get_auto_restart(path)

        return Project(
            name=name,
            path=path,
            php_version=php_version,
            port=port,
            is_running=is_running,
            php_running=php_running,
            nginx_running=nginx_running,
            mysql_running=mysql_running,
            redis_running=redis_running,
            cron_running=self._check_service_running(path, "cron"),
            auto_restart=auto_restart
        )

    def _get_php_version(self, path: Path) -> str:
        """获取项目 PHP 版本"""
        dockerfile = path / "Dockerfile"
        if not dockerfile.exists():
            return "未知"

        try:
            content = dockerfile.read_text()
            match = re.search(r'FROM php:([0-9.]+)-fpm', content)
            if match:
                return match.group(1)
        except Exception:
            pass
        return "未知"

    def _get_port(self, path: Path) -> str:
        """获取项目端口"""
        compose_file = path / "docker-compose.yml"
        if not compose_file.exists():
            return "未知"

        try:
            content = compose_file.read_text()
            match = re.search(r'"(\d+):80"', content)
            if match:
                return match.group(1)
        except Exception:
            pass
        return "未知"

    def _get_auto_restart(self, path: Path) -> bool:
        """获取是否开机自启"""
        compose_file = path / "docker-compose.yml"
        if not compose_file.exists():
            return True

        try:
            content = compose_file.read_text()
            # 检查是否有 restart: unless-stopped 或 restart: always
            if re.search(r'restart:\s*(unless-stopped|always)', content):
                return True
        except Exception:
            pass
        return False

    def _refresh_running_containers(self):
        """刷新运行中的容器缓存（TTL 2秒）"""
        now = time.monotonic()
        if now - self._running_containers_ts < 2:
            return
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=phpdev-",
                 "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=5
            )
            self._running_containers = set(result.stdout.strip().splitlines())
        except Exception:
            self._running_containers = set()
        self._running_containers_ts = now

    def _check_service_running(self, path: Path, service: str) -> bool:
        """检查项目某个服务是否在运行"""
        self._refresh_running_containers()
        container_name = f"phpdev-{path.name}-{service}"
        return container_name in self._running_containers

    def project_exists(self, name: str) -> bool:
        """检查项目是否存在"""
        return (BASE_DIR / name).exists()

    def is_valid_name(self, name: str) -> Tuple[bool, str]:
        """验证项目名称"""
        if not name:
            return False, "项目名不能为空"
        if not re.match(r'^[a-zA-Z0-9_-]+$', name):
            return False, "项目名只能包含字母、数字、下划线和连字符"
        return True, ""

    def set_auto_restart(self, project: Project, enabled: bool) -> bool:
        """设置项目开机自启

        Args:
            project: 项目对象
            enabled: 是否启用

        Returns:
            是否成功
        """
        compose_file = project.path / "docker-compose.yml"
        if not compose_file.exists():
            return False

        try:
            content = compose_file.read_text()

            if enabled:
                # 添加或替换 restart: unless-stopped
                if 'restart:' in content:
                    # 替换现有的 restart 值
                    content = re.sub(r'    restart:\s*\S+', '    restart: unless-stopped', content)
                else:
                    # 在 php 服务的 user: 之前添加 restart
                    content = re.sub(
                        r'(  php:\n(?:.*\n)*?)(    user:)',
                        r'\1    restart: unless-stopped\n\2',
                        content
                    )
                    # 在 nginx 服务的 entrypoint: 之前添加 restart
                    content = re.sub(
                        r'(  nginx:\n(?:.*\n)*?)(    entrypoint:)',
                        r'\1    restart: unless-stopped\n\2',
                        content
                    )
            else:
                # 移除 restart 行
                content = re.sub(r'    restart:.*?\n', '', content)

            compose_file.write_text(content)
            return True
        except Exception as e:
            print(f"设置自启动失败: {e}")
            return False

    def delete_project(self, project: Project) -> bool:
        """删除项目"""
        try:
            docker = DockerManager(project.path)
            result = docker._run_command(["down", "--volumes"])
            if not result.success:
                print(f"停止容器失败，保留项目目录: {result.error}")
                return False
            # 删除目录
            shutil.rmtree(project.path)
            return True
        except Exception as e:
            print(f"删除项目失败: {e}")
            return False

    def rename_project(self, project: Project, new_name: str) -> bool:
        valid, _ = self.is_valid_name(new_name)
        if not valid or self.project_exists(new_name):
            return False

        old_path = project.path
        new_path = old_path.parent / new_name
        code_path = get_project_code_path(old_path, project.name)
        rename_code = code_path.name == project.name and code_path.is_dir()
        snapshots = {}
        moved = False
        code_moved = False
        running_services = []
        docker = DockerManager(old_path)
        try:
            status = docker._run_command(["ps", "--status", "running", "--format", "{{.Service}}"])
            if not status.success:
                raise RuntimeError(status.error)
            running_services = status.output.splitlines()
            for relative in [Path("docker-compose.yml"), Path("Dockerfile"),
                             code_path.relative_to(old_path) / ".phpbox/tasks/tasks.json"]:
                file = old_path / relative
                if file.exists():
                    snapshots[relative] = file.read_bytes()
            result = docker.down()
            if not result.success:
                raise RuntimeError(result.error)

            old_path.rename(new_path)
            moved = True
            if rename_code:
                (new_path / project.name).rename(new_path / new_name)
                code_moved = True

            compose_file = new_path / "docker-compose.yml"
            content = compose_file.read_text()
            # 保持 Compose 项目标识，继续使用原数据库卷和网络。
            if not re.search(r"^name:", content, re.MULTILINE):
                content = f"name: {project.name.lower()}\n" + content
            content = re.sub(
                rf"(container_name:\s*)phpdev-{re.escape(project.name)}-",
                rf"\g<1>phpdev-{new_name}-", content
            )
            if rename_code:
                content = content.replace(f"./{project.name}:", f"./{new_name}:")
            content = content.replace(f"PROJECT_NAME={project.name}", f"PROJECT_NAME={new_name}")
            compose_file.write_text(content)
            dockerfile = new_path / "Dockerfile"
            if dockerfile.exists():
                content = dockerfile.read_text()
                content = re.sub(r'PROJECT_NAME="[^"]*"', f'PROJECT_NAME="{new_name}"', content)
                dockerfile.write_text(content)
            tasks_file = new_path / (new_name if rename_code else code_path.name) / ".phpbox/tasks/tasks.json"
            if tasks_file.exists():
                tasks = json.loads(tasks_file.read_text())
                for task in tasks:
                    task["project_name"] = new_name
                tasks_file.write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n")

            if running_services:
                result = DockerManager(new_path)._run_command(["up", "-d", "--no-deps"] + running_services)
                if not result.success:
                    raise RuntimeError(result.error)
            return True
        except Exception as exc:
            print(f"重命名失败: {exc}")
            if moved:
                cleanup = DockerManager(new_path).down()
                if not cleanup.success:
                    print(f"停止新容器失败，保留当前目录以便恢复: {new_path}: {cleanup.error}")
                    return False
                if code_moved:
                    (new_path / new_name).rename(new_path / project.name)
                new_path.rename(old_path)
                for relative, data in snapshots.items():
                    (old_path / relative).write_bytes(data)
                if running_services:
                    restored = DockerManager(old_path)._run_command(["up", "-d", "--no-deps"] + running_services)
                    if not restored.success:
                        print(f"目录已恢复，但容器恢复失败: {restored.error}")
            return False

    def set_port(self, project: Project, new_port: int) -> bool:
        """修改项目端口

        Args:
            project: 项目对象
            new_port: 新端口号

        Returns:
            是否成功
        """
        compose_file = project.path / "docker-compose.yml"
        env_file = project.path / ".env"

        if not compose_file.exists():
            return False

        try:
            # 修改 docker-compose.yml 中的端口映射
            content = compose_file.read_text()
            content = re.sub(r'"(\d+):80"', f'"{new_port}:80"', content)
            compose_file.write_text(content)

            # 修改 .env 文件中的 PORT
            if env_file.exists():
                env_content = env_file.read_text()
                env_content = re.sub(r'PORT=\d+', f'PORT={new_port}', env_content)
                env_file.write_text(env_content)

            # 更新 project 对象
            project.port = str(new_port)
            return True
        except Exception as e:
            print(f"修改端口失败: {e}")
            return False


def get_port_usage(
    port: int,
    exclude_project_name: Optional[str] = None,
    include_configured_projects: bool = True
) -> Optional[str]:
    """检查端口占用情况，返回占用进程名或 None

    Args:
        port: 要检查的端口号
        exclude_project_name: 排除的项目名（用于创建项目时不检测自己）
        include_configured_projects: 是否将已存在项目的端口配置也视为冲突
    """
    # 首先检查已存在项目的配置端口
    if include_configured_projects and BASE_DIR.exists():
        for item in sorted(BASE_DIR.iterdir()):
            if item.is_dir():
                # 排除当前项目
                if exclude_project_name and item.name == exclude_project_name:
                    continue
                project_port = None

                # 优先检查项目的 .env 文件中的端口配置
                env_file = item / ".env"
                if env_file.exists():
                    try:
                        with open(env_file, "r") as f:
                            for line in f:
                                if line.startswith("PORT="):
                                    value = line.strip().split("=", 1)[1]
                                    if value.isdigit():
                                        project_port = int(value)
                                        break
                    except Exception:
                        pass

                # 回退检查 docker-compose.yml 中的端口映射
                if project_port is None:
                    compose_file = item / "docker-compose.yml"
                    if compose_file.exists():
                        try:
                            content = compose_file.read_text()
                            match = re.search(r'"(\d+):80"', content)
                            if match:
                                project_port = int(match.group(1))
                        except Exception:
                            pass

                if project_port == port:
                    return f"项目「{item.name}」"

    # 检查系统中实际占用的端口（排除 docker 容器）
    try:
        # 获取所有 docker 容器的端口映射
        docker_result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}} {{.Ports}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        docker_ports = {}  # port -> container_name
        for line in docker_result.stdout.strip().splitlines():
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                container_name = parts[0]
                ports_str = parts[1]
                # 解析端口映射，兼容 IPv4/IPv6 输出
                for match in re.finditer(r'(?:0\.0\.0\.0|\[::\]|::):(\d+)->', ports_str):
                    docker_port = int(match.group(1))
                    docker_ports[docker_port] = container_name

        # 如果端口被 docker 容器占用
        if port in docker_ports:
            container_name = docker_ports[port]
            # 如果是当前项目的容器，不算冲突
            if exclude_project_name and container_name.startswith(f"phpdev-{exclude_project_name}-"):
                return None
            # 其他 docker 容器占用
            return f"Docker 容器「{container_name}」"

        # 检查非 docker 进程占用的端口，按常见 Linux 工具逐级回退
        port_commands = [
            (["ss", "-H", "-tlnp"], lambda line: re.search(r'users:\(\("([^"]+)"', line)),
            (["netstat", "-tlnp"], lambda line: re.search(r'\b\d+/([^\s/]+)', line)),
            (["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], lambda line: re.match(r'([^\s]+)', line)),
        ]

        exact_port_pattern = re.compile(rf'(?<!\d):{port}\b')

        for cmd, process_parser in port_commands:
            if not shutil.which(cmd[0]):
                continue
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0 and not result.stdout.strip():
                continue

            for line in result.stdout.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith(("State", "Proto", "COMMAND")):
                    continue

                if not exact_port_pattern.search(stripped):
                    continue

                process_match = process_parser(stripped)
                if process_match:
                    process_name = process_match.group(1)
                else:
                    process_name = "系统监听进程（当前权限不足，无法识别名称）"

                if 'docker' in process_name.lower():
                    continue
                return process_name

        # 最后用 socket bind 做一次兜底探测，避免命令输出异常时误判为空闲
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("0.0.0.0", port))
            except OSError as e:
                # 低端口（<1024）在非 root 下 bind 会因权限失败，不能误判为端口占用
                if e.errno in (errno.EACCES, errno.EPERM):
                    return None
                return "系统监听进程（当前权限不足，无法识别名称）"
        return None
    except Exception:
        return None


def find_available_port(
    start_port: int = 8080,
    max_attempts: int = 100,
    exclude_project_name: Optional[str] = None,
    include_configured_projects: bool = True
) -> int:
    """查找可用端口，从 start_port 开始向上搜索

    Args:
        start_port: 起始端口
        max_attempts: 最大尝试次数
        exclude_project_name: 排除的项目名（用于创建项目时不检测自己）
        include_configured_projects: 是否避开已配置但未运行的项目端口
    """
    for port in range(start_port, start_port + max_attempts):
        if get_port_usage(port, exclude_project_name, include_configured_projects) is None:
            return port
    return start_port
