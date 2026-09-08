"""代理检测模块"""
import os
import subprocess
import re
import shlex
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path
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


def validate_proxy_url(proxy_url: str):
    parsed = urlsplit(proxy_url)
    if (parsed.scheme not in {"http", "https", "socks5", "socks5h"}
            or not parsed.hostname or re.search(r"[\s\x00-\x1f]", proxy_url)
            or not re.fullmatch(r"[a-zA-Z0-9.:-]+", parsed.hostname)
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("代理地址格式无效")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("代理端口必须在 1–65535 之间")
    return parsed


def convert_proxy_for_docker(proxy_url: str) -> Optional[str]:
    if not proxy_url:
        return None
    parsed = validate_proxy_url(proxy_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return proxy_url
    host_ip = get_host_ip_for_docker()
    if not host_ip:
        return proxy_url
    auth = parsed.netloc.rsplit("@", 1)[0] + "@" if "@" in parsed.netloc else ""
    netloc = auth + host_ip + (f":{parsed.port}" if parsed.port is not None else "")
    return urlunsplit(parsed._replace(netloc=netloc))


SHELL_PROXY_BEGIN = "# >>> phpbox proxy helpers >>>"
SHELL_PROXY_END = "# <<< phpbox proxy helpers <<<"
DOCKERFILE_PROXY_BEGIN = "# BEGIN_PHPBOX_PROXY_HELPERS"
DOCKERFILE_PROXY_END = "# END_PHPBOX_PROXY_HELPERS"


def build_shell_proxy_block(proxy_url: Optional[str]) -> str:
    docker_proxy = convert_proxy_for_docker(proxy_url) if proxy_url else None
    if docker_proxy:
        proxy_func = f"""proxy () {{
    export http_proxy={shlex.quote(docker_proxy)}
    export https_proxy="$http_proxy"
    export HTTP_PROXY="$http_proxy"
    export HTTPS_PROXY="$http_proxy"
    echo "HTTP Proxy on"
}}"""
    else:
        proxy_func = """proxy () {
    echo "Global proxy not configured"
    return 1
}"""

    return "\n".join([
        SHELL_PROXY_BEGIN,
        proxy_func,
        "",
        """noproxy () {
    unset http_proxy
    unset https_proxy
    unset HTTP_PROXY
    unset HTTPS_PROXY
    echo "HTTP Proxy off"
}""",
        "",
        """ckproxy () {
    curl ipinfo.io
}""",
        SHELL_PROXY_END,
    ])


def build_dockerfile_proxy_snippet(proxy_url: Optional[str]) -> str:
    block = build_shell_proxy_block(proxy_url)
    return "\n".join([
        DOCKERFILE_PROXY_BEGIN,
        "RUN cat <<'EOF' >> /home/user/.zshrc",
        block,
        "EOF",
        DOCKERFILE_PROXY_END,
    ])


def upsert_proxy_block(content: str, start_marker: str, end_marker: str, replacement: str) -> str:
    pattern = re.compile(
        rf"{re.escape(start_marker)}.*?{re.escape(end_marker)}",
        re.DOTALL
    )
    if pattern.search(content):
        return pattern.sub(lambda match: replacement, content, count=1)

    stripped = content.rstrip() + "\n\n"
    return stripped + replacement + "\n"


def sync_project_dockerfile_proxy(project_path: Path, proxy_url: Optional[str]) -> bool:
    dockerfile = project_path / "Dockerfile"
    if not dockerfile.exists():
        return False
    try:
        content = dockerfile.read_text(encoding="utf-8")
        updated = upsert_proxy_block(
            content,
            DOCKERFILE_PROXY_BEGIN,
            DOCKERFILE_PROXY_END,
            build_dockerfile_proxy_snippet(proxy_url)
        )
        if updated != content:
            dockerfile.write_text(updated, encoding="utf-8")
            return True
    except OSError as exc:
        raise RuntimeError(f"同步 {dockerfile} 失败: {exc}") from exc
    return False


def sync_running_container_proxy(project_path: Path, proxy_url: Optional[str]) -> bool:
    try:
        from core.docker import DockerManager
        import base64
        import json

        docker = DockerManager(project_path)
        if not docker.is_service_running("php"):
            return False

        block = build_shell_proxy_block(proxy_url)
        block_b64 = base64.b64encode(block.encode("utf-8")).decode("ascii")
        cmd = f"""cat >/tmp/phpbox-sync-proxy.php <<'PHP'
<?php
$f = getenv("HOME") . "/.zshrc";
$begin = {json.dumps(SHELL_PROXY_BEGIN)};
$end = {json.dumps(SHELL_PROXY_END)};
$block = base64_decode({json.dumps(block_b64)});
$c = @file_get_contents($f);
if ($c === false) {{
    $c = "";
}}
$p = '/' . preg_quote($begin, '/') . '.*?' . preg_quote($end, '/') . '/s';
$updated = preg_replace($p, $block, $c, -1, $count);
if (!$count) {{
    $updated = rtrim($c) . PHP_EOL . PHP_EOL . $block . PHP_EOL;
}}
if (file_put_contents($f, $updated) === false) {{ exit(1); }}
PHP
php /tmp/phpbox-sync-proxy.php || exit $?
rm -f /tmp/phpbox-sync-proxy.php"""
        result = docker.exec_command("php", ["sh", "-lc", cmd])
        if not result.success:
            raise RuntimeError(result.error)
        return True
    except Exception as exc:
        raise RuntimeError(f"同步 {project_path.name} 容器代理失败: {exc}") from exc


def sync_all_projects_proxy(proxy_url: Optional[str]) -> dict:
    from core.config import BASE_DIR

    updated_dockerfiles = 0
    updated_running = 0

    if not BASE_DIR.exists():
        return {"dockerfiles": 0, "running_containers": 0}

    for item in BASE_DIR.iterdir():
        if not item.is_dir():
            continue
        compose_file = item / "docker-compose.yml"
        if not compose_file.exists():
            continue
        if sync_project_dockerfile_proxy(item, proxy_url):
            updated_dockerfiles += 1
        if sync_running_container_proxy(item, proxy_url):
            updated_running += 1

    return {
        "dockerfiles": updated_dockerfiles,
        "running_containers": updated_running,
    }
