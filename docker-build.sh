#!/bin/bash
# Docker 打包脚本 - 在 Ubuntu 20.04 容器中构建，兼容更多系统

set -e

cd "$(dirname "$0")"

IMAGE_NAME="phpbox-builder"
CONTAINER_NAME="phpbox-build"

echo "=== Docker 环境打包 (Ubuntu 20.04) ==="
echo ""

# 获取宿主机 IP (用于容器访问代理)
get_host_ip() {
    # 方法1: 从 docker0 获取
    local ip=$(ip addr show docker0 2>/dev/null | grep -oP 'inet \K[\d.]+')
    if [ -n "$ip" ]; then
        echo "$ip"
        return
    fi
    # 方法2: 从默认路由获取
    ip=$(ip route | grep default | awk '{print $3}')
    if [ -n "$ip" ]; then
        echo "$ip"
        return
    fi
    # 方法3: 使用 host.docker.internal (Docker Desktop)
    echo "host.docker.internal"
}

# 转换代理地址为容器可访问的地址
convert_proxy_for_docker() {
    local proxy="$1"
    local host_ip=$(get_host_ip)
    # 替换 127.0.0.1 和 localhost 为宿主机 IP
    echo "$proxy" | sed "s/127\.0\.0\.1/$host_ip/g" | sed "s/localhost/$host_ip/g"
}

# 获取代理设置
get_proxy() {
    echo "${http_proxy:-${HTTP_PROXY:-}}"
}

# 构建 Docker 镜像
build_image() {
    echo ">>> 构建 Docker 镜像..."

    local host_proxy=$(get_proxy)
    local build_args=""

    if [ -n "$host_proxy" ]; then
        local docker_proxy=$(convert_proxy_for_docker "$host_proxy")
        echo ">>> 检测到代理: $host_proxy"
        echo ">>> 容器代理: $docker_proxy"
        build_args="--build-arg http_proxy=$docker_proxy --build-arg https_proxy=$docker_proxy"
    fi

    docker build $build_args -t $IMAGE_NAME -f- . << 'DOCKERFILE'
ARG http_proxy
ARG https_proxy

FROM ubuntu:20.04

# 传递代理参数
ARG http_proxy
ARG https_proxy

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

# 设置代理环境变量
ENV http_proxy=${http_proxy}
ENV https_proxy=${https_proxy}

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libxcb-xinerama0 \
    wget \
    file \
    && rm -rf /var/lib/apt/lists/*

# 清除代理（避免后续问题）
ENV http_proxy=
ENV https_proxy=

# 创建工作目录
WORKDIR /build

# 设置 Python 虚拟环境
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 预安装 PyInstaller 和项目依赖
RUN pip install --upgrade pip && pip install pyinstaller

# 复制 requirements.txt 并安装依赖
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt && rm /tmp/requirements.txt

# 设置入口
CMD ["/bin/bash"]
DOCKERFILE

    echo ">>> 镜像构建完成"
}

# 在容器中打包
build_in_container() {
    echo ">>> 在容器中执行打包..."

    local host_proxy=$(get_proxy)
    local run_args=""

    if [ -n "$host_proxy" ]; then
        local docker_proxy=$(convert_proxy_for_docker "$host_proxy")
        run_args="-e http_proxy=$docker_proxy -e https_proxy=$docker_proxy"
    fi

    # 清理可能存在的旧容器
    docker rm -f $CONTAINER_NAME 2>/dev/null || true

    # 复制项目到容器并打包
    docker run --rm \
        $run_args \
        --name $CONTAINER_NAME \
        -v "$(pwd):/src:ro" \
        -v "$(pwd)/dist:/build/dist" \
        $IMAGE_NAME \
        bash -c '
set -e
cd /build

echo ">>> 复制源代码..."
cp -r /src/* . 2>/dev/null || true

echo ">>> 激活虚拟环境..."
source /opt/venv/bin/activate

echo ">>> 清理旧构建..."
rm -rf build/

echo ">>> 执行 PyInstaller 打包..."
pyinstaller phpbox.spec --noconfirm

# 检查结果
if [ -f "dist/phpbox" ]; then
    echo ">>> 构建成功!"
    chmod +x dist/phpbox

    # 显示信息
    echo ""
    echo "=== 构建信息 ==="
    file dist/phpbox
    ldd --version | head -1
    ls -lh dist/
else
    echo "错误: 构建失败"
    exit 1
fi
'
}

# 构建 AppImage
build_appimage() {
    echo ">>> 构建 AppImage..."

    # 清理可能存在的旧容器
    docker rm -f ${CONTAINER_NAME}-appimage 2>/dev/null || true

    # 检查 appimagetool
    if [ ! -f /tmp/appimagetool ]; then
        echo "下载 appimagetool..."
        local host_proxy=$(get_proxy)
        if [ -n "$host_proxy" ]; then
            wget -e use_proxy=yes -e http_proxy="$host_proxy" -e https_proxy="$host_proxy" \
                -q https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage \
                -O /tmp/appimagetool
        else
            wget -q https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage \
                -O /tmp/appimagetool
        fi
        chmod +x /tmp/appimagetool
    fi

    # 在容器中构建 AppImage
    docker run --rm \
        --name ${CONTAINER_NAME}-appimage \
        -v "$(pwd):/src:ro" \
        -v "$(pwd)/dist:/build/dist" \
        -v /tmp/appimagetool:/tmp/appimagetool:ro \
        $IMAGE_NAME \
        bash -c '
set -e
cd /build

# AppDir 结构
APPDIR="AppDir"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/applications"

# 复制文件
cp dist/phpbox "$APPDIR/usr/bin/"
cp /src/phpbox.desktop "$APPDIR/usr/share/applications/"
ln -sf usr/share/applications/phpbox.desktop "$APPDIR/phpbox.desktop"

# AppRun
cat > "$APPDIR/AppRun" << "APPRUN"
#!/bin/bash
SELF=$(readlink -f "$0")
HERE=${SELF%/*}
export PATH="${HERE}/usr/bin:${PATH}"
exec "${HERE}/usr/bin/phpbox" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# 图标
if [ -f /src/resources/icons/phpbox-256.png ]; then
    cp /src/resources/icons/phpbox-256.png "$APPDIR/phpbox.png"
else
    touch "$APPDIR/phpbox.png"
fi

# 构建 AppImage
ARCH=x86_64 /tmp/appimagetool "$APPDIR" dist/phpbox-x86_64.AppImage

rm -rf "$APPDIR"
echo ">>> AppImage 构建完成"
'
}

# 构建 .deb 包
build_deb() {
    echo ">>> 构建 .deb 包..."

    VERSION="${VERSION:-1.0.0}"
    ARCH="amd64"

    # 清理可能存在的旧容器
    docker rm -f ${CONTAINER_NAME}-deb 2>/dev/null || true

    # 在容器中构建 .deb
    docker run --rm \
        --name ${CONTAINER_NAME}-deb \
        -v "$(pwd):/src:ro" \
        -v "$(pwd)/dist:/build/dist" \
        $IMAGE_NAME \
        bash -c "
set -e
cd /build

VERSION='${VERSION}'
ARCH='${ARCH}'
DEB_DIR='deb_package'

# 复制源代码（包括 desktop 文件）
cp /src/*.desktop . 2>/dev/null || true

rm -rf \$DEB_DIR
mkdir -p \$DEB_DIR/DEBIAN
mkdir -p \$DEB_DIR/usr/bin
mkdir -p \$DEB_DIR/usr/share/applications
mkdir -p \$DEB_DIR/usr/share/doc/phpbox

# 控制文件
cat > \$DEB_DIR/DEBIAN/control << EOF
Package: phpbox
Version: \$VERSION
Section: devel
Priority: optional
Architecture: \$ARCH
Depends: docker-ce | docker.io | docker-ce-cli, docker-compose-plugin | docker-compose
Maintainer: PHPDev <noreply@example.com>
Description: PHP Development Environment Manager
 A GUI application to manage PHP Docker development environments.
 Supports multiple PHP versions (7.2-8.4), extensions management,
 and project lifecycle management.
 .
 Features:
  - Create and manage PHP projects with Docker
  - Multiple PHP versions support
  - PHP extensions management
  - Dark/Light theme support
  - System tray integration
EOF

# 复制可执行文件
cp dist/phpbox \$DEB_DIR/usr/bin/
chmod 755 \$DEB_DIR/usr/bin/phpbox

# 复制 desktop 文件
cp phpbox.desktop \$DEB_DIR/usr/share/applications/

# 安装图标
mkdir -p \$DEB_DIR/usr/share/icons/hicolor/256x256/apps
mkdir -p \$DEB_DIR/usr/share/pixmaps

if [ -f /src/resources/icons/phpbox-256.png ]; then
    cp /src/resources/icons/phpbox-256.png \$DEB_DIR/usr/share/icons/hicolor/256x256/apps/phpbox.png
    cp /src/resources/icons/phpbox-256.png \$DEB_DIR/usr/share/pixmaps/phpbox.png
fi

# 创建自启动目录并复制自启动文件
mkdir -p \$DEB_DIR/etc/xdg/autostart
cp phpbox-autostart.desktop \$DEB_DIR/etc/xdg/autostart/phpbox.desktop

# 构建 .deb
dpkg-deb --build \$DEB_DIR dist/phpbox_\${VERSION}_\${ARCH}.deb

rm -rf \$DEB_DIR
echo '>>> .deb 构建完成'
"
}

# 显示帮助
show_help() {
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  --all       构建所有格式 (二进制 + AppImage + deb)"
    echo "  --bin       仅构建二进制文件 (默认)"
    echo "  --appimage  构建 AppImage"
    echo "  --deb       构建 .deb 包"
    echo "  --rebuild   重新构建 Docker 镜像"
    echo "  --help      显示帮助"
    echo ""
    echo "环境变量:"
    echo "  VERSION     设置版本号 (默认: 1.0.0)"
    echo "  http_proxy  代理设置"
    echo ""
    echo "示例:"
    echo "  $0                    # 仅构建二进制"
    echo "  $0 --appimage         # 构建 AppImage"
    echo "  $0 --deb              # 构建 .deb"
    echo "  $0 --all              # 构建所有格式"
    echo "  VERSION=2.0.0 $0 --deb  # 指定版本号"
}

# 解析参数
BUILD_APPIMAGE=false
BUILD_DEB=false
REBUILD_IMAGE=false

for arg in "$@"; do
    case $arg in
        --appimage) BUILD_APPIMAGE=true ;;
        --deb) BUILD_DEB=true ;;
        --all) BUILD_APPIMAGE=true; BUILD_DEB=true ;;
        --rebuild) REBUILD_IMAGE=true ;;
        --help) show_help; exit 0 ;;
    esac
done

# 执行
if [ "$REBUILD_IMAGE" = true ]; then
    docker rmi $IMAGE_NAME 2>/dev/null || true
fi

echo ">>> 检查 Docker 镜像..."
if ! docker image inspect $IMAGE_NAME &>/dev/null; then
    build_image
fi

build_in_container

if [ "$BUILD_APPIMAGE" = true ]; then
    build_appimage
fi

if [ "$BUILD_DEB" = true ]; then
    build_deb
fi

echo ""
echo "=== 打包完成! ==="
echo "输出目录: dist/"
echo ""
echo "兼容性: Ubuntu 20.04+, Debian 11+, Arch Linux 等"
ls -lh dist/
