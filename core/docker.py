"""Docker 操作模块"""
import subprocess
import os
from pathlib import Path
from typing import List, Optional, Callable
from dataclasses import dataclass


@dataclass
class DockerResult:
    """Docker 命令执行结果"""
    success: bool
    output: str = ""
    error: str = ""


class DockerManager:
    """Docker 管理器"""

    def __init__(self, project_path: Path):
        self.project_path = project_path

    def _run_command(self, args: List[str], capture: bool = True,
                     env: Optional[dict] = None) -> DockerResult:
        """执行 docker compose 命令"""
        cmd = ["docker", "compose"] + args
        try:
            run_env = os.environ.copy()
            if env:
                run_env.update(env)

            result = subprocess.run(
                cmd,
                cwd=str(self.project_path),
                capture_output=capture,
                text=True,
                timeout=300,
                env=run_env
            )
            if result.returncode == 0:
                return DockerResult(success=True, output=result.stdout)
            else:
                return DockerResult(success=False, error=result.stderr)
        except subprocess.TimeoutExpired:
            return DockerResult(success=False, error="命令执行超时")
        except Exception as e:
            return DockerResult(success=False, error=str(e))

    def up(self, build: bool = False) -> DockerResult:
        """启动服务"""
        args = ["up", "-d"]
        if build:
            args.insert(1, "--build")
        return self._run_command(args)

    def stop(self) -> DockerResult:
        """停止服务"""
        return self._run_command(["stop"])

    def restart(self) -> DockerResult:
        """重启服务"""
        return self._run_command(["restart"])

    def down(self, remove_images: bool = False) -> DockerResult:
        """删除服务"""
        args = ["down"]
        if remove_images:
            args.append("--rmi")
            args.append("local")
        return self._run_command(args)

    def build(self, proxy: Optional[str] = None) -> DockerResult:
        """构建镜像"""
        env = {}
        if proxy:
            env["HTTP_PROXY"] = proxy
            env["HTTPS_PROXY"] = proxy
        return self._run_command(["build"], env=env)

    def get_logs(self, service: Optional[str] = None,
                 follow: bool = False) -> subprocess.Popen:
        """获取日志 (返回 Popen 对象用于实时输出)"""
        cmd = ["docker", "compose", "logs"]
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
                ["docker", "compose", "images", "php", "--format", "json"],
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
