"""代理检测模块"""
import os
import subprocess
import re
from typing import Optional


def detect_system_proxy() -> Optional[str]:
    """检测系统代理设置"""
    # 检查环境变量
    for var in ['http_proxy', 'HTTP_PROXY']:
        if os.environ.get(var):
            return os.environ[var]
    return None


def get_host_ip_for_docker() -> Optional[str]:
    """获取宿主机 IP (用于 Docker 容器访问宿主机代理)"""
    try:
        # 尝试从 docker0 获取
        result = subprocess.run(
            ["ip", "addr", "show", "docker0"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
            if match:
                return match.group(1)
    except Exception:
        pass

    try:
        # 回退：从默认路由获取网关 IP
        result = subprocess.run(
            ["ip", "route"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("default"):
                    parts = line.split()
                    if len(parts) >= 3:
                        return parts[2]
    except Exception:
        pass

    return None


def convert_proxy_for_docker(proxy_url: str) -> Optional[str]:
    """将代理地址转换为 Docker 容器可访问的地址"""
    if not proxy_url:
        return None

    host_ip = get_host_ip_for_docker()
    if not host_ip:
        return proxy_url

    # 替换 127.0.0.1 和 localhost
    converted = proxy_url
    converted = re.sub(r'127\.0\.0\.1', host_ip, converted)
    converted = re.sub(r'localhost', host_ip, converted)

    return converted
