from typing import List

from core.proxy import convert_proxy_for_docker, build_dockerfile_proxy_snippet

EXTENSION_INSTALLER_URL = 'https://github.com/mlocati/docker-php-extension-installer/releases/latest/download/install-php-extensions'
EXTENSION_INSTALLER_COMMAND = ('RUN curl -fsSL --retry 3 --connect-timeout 20 ' + EXTENSION_INSTALLER_URL +
                               ' -o /usr/local/bin/install-php-extensions && chmod +x /usr/local/bin/install-php-extensions')


def generate_dockerfile(project_name: str, php_version: str,
                        extensions: List[str], proxy: str) -> str:
    """生成 Dockerfile 内容"""
    lines = [f"FROM php:{php_version}-fpm", ""]

    # 用户构建参数
    lines.extend([
        "# 用户 UID/GID 构建参数",
        "ARG USER_UID=1000",
        "ARG USER_GID=1000",
        "",
    ])

    # 代理配置
    docker_proxy = convert_proxy_for_docker(proxy) if proxy else None
    if docker_proxy:
        lines.extend([
            "# 构建时代理（仅 build 阶段生效）",
            "ARG HTTP_PROXY",
            "ARG HTTPS_PROXY",
            'ENV http_proxy=${HTTP_PROXY}',
            'ENV https_proxy=${HTTPS_PROXY}',
            'ENV HTTP_PROXY=${HTTP_PROXY}',
            'ENV HTTPS_PROXY=${HTTPS_PROXY}',
            "",
        ])

    lines.extend([
        "# install-php-extensions 自动处理各 PHP 版本扩展兼容性",
        EXTENSION_INSTALLER_COMMAND,
        "",
        "# 安装 Composer",
        "COPY --from=composer:latest /usr/bin/composer /usr/bin/composer",
        "",
        "RUN cp /usr/local/etc/php/php.ini-development /usr/local/etc/php/php.ini",
        "",
    ])

    # PHP 7.2 特殊处理
    if php_version == "7.2":
        lines.extend([
            "# Debian Buster 官方源已 EOL，切换归档源",
            'RUN echo "deb http://archive.debian.org/debian buster main" > /etc/apt/sources.list && \\',
            '    echo "deb http://archive.debian.org/debian-security buster/updates main" >> /etc/apt/sources.list',
            "",
        ])

    lines.extend([
        "# 安装基础工具 (包含 git, openssh-client, zsh, cron)",
        "RUN apt-get update && apt-get install -y unzip git openssh-client zsh curl wget sudo cron procps util-linux && rm -rf /var/lib/apt/lists/*",
        "",
        "# 创建用户 (与宿主机 UID/GID 一致)",
        "RUN groupadd -g ${USER_GID} user && \\",
        "    useradd -m -u ${USER_UID} -g ${USER_GID} -s /bin/zsh user && \\",
        "    echo 'user ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers",
        "",
        "# 设置用户环境变量",
        "ENV HOME=/home/user",
        "ENV USER=user",
        "",
        "# Composer 缓存目录",
        "ENV COMPOSER_HOME=/home/user/.composer",
        "RUN mkdir -p ${COMPOSER_HOME} && chown -R user:user ${COMPOSER_HOME}",
        "",
        "# SSH 目录 (用于访问私有 Git 仓库)",
        "RUN mkdir -p /home/user/.ssh && chmod 700 /home/user/.ssh && chown user:user /home/user/.ssh",
        "",
        "# 为用户安装 Oh My Zsh",
        "USER user",
        "WORKDIR /home/user",
        'RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" || true',
        "",
        "# 安装 zsh 插件",
        "RUN git clone https://github.com/paulirish/git-open.git ~/.oh-my-zsh/custom/plugins/git-open && \\",
        "    git clone https://github.com/zsh-users/zsh-autosuggestions ~/.oh-my-zsh/custom/plugins/zsh-autosuggestions && \\",
        "    git clone https://github.com/zsh-users/zsh-syntax-highlighting.git ~/.oh-my-zsh/custom/plugins/zsh-syntax-highlighting",
        "",
        "# 配置 zsh 插件",
        'RUN sed -i "s/plugins=(git)/plugins=(git git-open z zsh-autosuggestions zsh-syntax-highlighting extract command-not-found copypath)/" ~/.zshrc',
        "",
        "# 自定义提示符 - 显示项目名称",
        f'RUN echo \'# 自定义提示符\\n'
        f'export PROJECT_NAME="{project_name}"\\n'
        f'PROMPT="%{{\\033[38;5;39m%}}$PROJECT_NAME %{{\\033[38;5;208m%}}➜%{{\\033[0m%}}  %{{\\033[38;5;81m%}}%c%{{\\033[0m%}} "\' >> ~/.zshrc',
        "",
        "# 代理快捷命令",
        build_dockerfile_proxy_snippet(proxy),
        "",
        "# 禁用 Oh My Zsh 自动更新",
        'RUN sed -i "s/# DISABLE_AUTO_UPDATE/DISABLE_AUTO_UPDATE/" ~/.zshrc && \\',
        '    echo "DISABLE_AUTO_UPDATE=true" >> ~/.zshrc',
        "",
        "# 切回 root 用户，运行时由 docker-compose 指定用户",
        "USER root",
        "WORKDIR /var/www/html",
    ])

    # 扩展安装
    if extensions:
        lines.extend(["", "# 安装 PHP 扩展"])
        install_lines = generate_ext_install_lines(extensions)
        lines.extend(install_lines)

    # 清除代理
    if docker_proxy:
        lines.extend([
            "",
            "# 清除代理，避免运行时影响业务",
            "ENV http_proxy=''",
            "ENV https_proxy=''",
            "ENV HTTP_PROXY=''",
            "ENV HTTPS_PROXY=''",
        ])

    return "\n".join(lines) + "\n"

def generate_ext_install_lines(extensions: List[str]) -> List[str]:
    """生成扩展安装命令"""
    # 优先安装的扩展
    priority = ["igbinary", "msgpack"]

    priority_exts = []
    normal_exts = []

    for ext in extensions:
        if ext in priority:
            priority_exts.append(ext)
        else:
            normal_exts.append(ext)

    lines = []
    if priority_exts:
        lines.append(f"RUN install-php-extensions {' '.join(priority_exts)}")
    if normal_exts:
        lines.append(f"RUN install-php-extensions {' '.join(normal_exts)}")
    return lines
