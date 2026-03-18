"""项目管理核心逻辑"""
import os
import re
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Tuple
from .config import BASE_DIR, ensure_base_dir


@dataclass
class Project:
    """项目数据类"""
    name: str
    path: Path
    php_version: str = "未知"
    port: str = "未知"
    is_running: bool = False
    auto_restart: bool = True  # 是否开机自启

    @property
    def status_text(self) -> str:
        return "运行中" if self.is_running else "已停止"


class ProjectManager:
    """项目管理器"""

    def __init__(self):
        ensure_base_dir()

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
        is_running = self._check_running(path)
        auto_restart = self._get_auto_restart(path)

        return Project(
            name=name,
            path=path,
            php_version=php_version,
            port=port,
            is_running=is_running,
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

    def _check_running(self, path: Path) -> bool:
        """检查项目是否在运行"""
        try:
            project_name = path.name
            container_name = f"phpdev-{project_name}-php"
            result = subprocess.run(
                ["docker", "ps", "--filter", f"name={container_name}",
                 "--filter", "status=running", "-q"],
                capture_output=True,
                text=True,
                timeout=3  # 减少超时时间
            )
            return bool(result.stdout.strip())
        except Exception:
            return False

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
            # 停止并删除容器
            subprocess.run(
                ["docker", "compose", "down", "--volumes"],
                cwd=str(project.path),
                capture_output=True,
                timeout=60
            )
            # 删除目录
            subprocess.run(["rm", "-rf", str(project.path)], check=True)
            return True
        except Exception as e:
            print(f"删除项目失败: {e}")
            return False

    def rename_project(self, project: Project, new_name: str) -> bool:
        """重命名项目"""
        import time
        try:
            # 检查新名称是否已存在
            if self.project_exists(new_name):
                return False

            # 如果项目正在运行，先停止
            was_running = project.is_running
            if was_running:
                subprocess.run(
                    ["docker", "compose", "down"],
                    cwd=str(project.path),
                    capture_output=True,
                    timeout=60
                )

            # 重命名目录
            new_path = project.path.parent / new_name
            project.path.rename(new_path)

            # 更新 docker-compose.yml 中的项目名
            compose_file = new_path / "docker-compose.yml"
            if compose_file.exists():
                content = compose_file.read_text()
                # 替换 name: phpdev-{old_name}
                old_prefix = f"phpdev-{project.name}"
                new_prefix = f"phpdev-{new_name}"
                content = content.replace(old_prefix, new_prefix)
                compose_file.write_text(content)

            # 更新 Dockerfile 中的项目名（用于下次重建镜像）
            dockerfile = new_path / "Dockerfile"
            if dockerfile.exists():
                content = dockerfile.read_text()
                # 替换 PROJECT_NAME="{old_name}"
                content = re.sub(r'PROJECT_NAME="([^"]*)"', f'PROJECT_NAME="{new_name}"', content)
                dockerfile.write_text(content)

            # 如果之前是运行状态，重新启动并更新容器内的 zsh 提示符
            if was_running:
                # 启动容器
                subprocess.run(
                    ["docker", "compose", "up", "-d"],
                    cwd=str(new_path),
                    capture_output=True,
                    timeout=120
                )

                # 等待容器启动
                time.sleep(3)

                # 直接在容器中修改 .zshrc 的提示符
                sed_cmd = f'sed -i \'s/export PROJECT_NAME=.*/export PROJECT_NAME="{new_name}"/\' ~/.zshrc'
                subprocess.run(
                    ["docker", "compose", "exec", "-T", "php", "sh", "-c", sed_cmd],
                    cwd=str(new_path),
                    capture_output=True,
                    timeout=30
                )

            return True
        except Exception as e:
            print(f"重命名项目失败: {e}")
            return False


def get_port_usage(port: int, exclude_project_name: Optional[str] = None) -> Optional[str]:
    """检查端口占用情况，返回占用进程名或 None

    Args:
        port: 要检查的端口号
        exclude_project_name: 排除的项目名（用于创建项目时不检测自己）
    """
    # 首先检查已存在项目的配置端口
    if BASE_DIR.exists():
        for item in sorted(BASE_DIR.iterdir()):
            if item.is_dir():
                # 排除当前正在创建的项目
                if exclude_project_name and item.name == exclude_project_name:
                    continue
                # 检查项目的 .env 文件中的端口配置
                env_file = item / ".env"
                if env_file.exists():
                    try:
                        with open(env_file, "r") as f:
                            for line in f:
                                if line.startswith("PORT="):
                                    project_port = line.strip().split("=")[1]
                                    if project_port.isdigit() and int(project_port) == port:
                                        return f"项目「{item.name}」"
                    except Exception:
                        pass

    # 检查系统中实际占用的端口
    try:
        result = subprocess.run(
            ["ss", "-tlnp"],
            capture_output=True,
            text=True,
            timeout=5
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and not f":{port}0" in line:
                # 提取进程名
                match = re.search(r'users:\(\("([^"]+)"', line)
                if match:
                    return match.group(1)
                return "未知进程"
        return None
    except Exception:
        return None


def find_available_port(start_port: int = 8080, max_attempts: int = 100, exclude_project_name: Optional[str] = None) -> int:
    """查找可用端口，从 start_port 开始向上搜索

    Args:
        start_port: 起始端口
        max_attempts: 最大尝试次数
        exclude_project_name: 排除的项目名（用于创建项目时不检测自己）
    """
    for port in range(start_port, start_port + max_attempts):
        if get_port_usage(port, exclude_project_name) is None:
            return port
    return start_port
