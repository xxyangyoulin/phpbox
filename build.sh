#!/bin/bash
# PHP 开发环境管理器打包脚本

set -e

cd "$(dirname "$0")"

echo "=== PHP 开发环境管理器 - 打包工具 ==="
echo ""

# 显示帮助
show_help() {
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  --all       构建所有格式 (默认)"
    echo "  --bin       仅构建二进制文件"
    echo "  --appimage  构建 AppImage"
    echo "  --deb       构建 .deb 包 (需要 dpkg-deb)"
    echo "  --help      显示帮助"
    echo ""
}

# 检查虚拟环境
check_venv() {
    if [ ! -d ".venv" ]; then
        echo "错误: 未找到虚拟环境 .venv"
        echo "请先运行: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
        exit 1
    fi
    source .venv/bin/activate
}

# 构建二进制
build_bin() {
    echo ">>> 构建二进制文件..."

    # 安装/更新依赖
    pip install -r requirements.txt --quiet

    # 清理旧的构建文件
    rm -rf build/

    # 使用 PyInstaller 打包
    pyinstaller phpbox.spec --noconfirm

    if [ -f "dist/phpbox" ]; then
        echo ">>> 二进制构建完成: dist/phpbox"
    else
        echo "错误: 打包失败"
        exit 1
    fi
}

# 构建 AppImage
build_appimage() {
    echo ">>> 构建 AppImage..."

    if [ ! -f "dist/phpbox" ]; then
        build_bin
    fi

    # 检查 appimagetool
    APPIMAGETOOL=""
    if command -v appimagetool &> /dev/null; then
        APPIMAGETOOL=appimagetool
    elif [ -f /tmp/appimagetool ]; then
        APPIMAGETOOL=/tmp/appimagetool
    else
        echo "下载 appimagetool..."
        wget -q https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage -O /tmp/appimagetool
        chmod +x /tmp/appimagetool
        APPIMAGETOOL=/tmp/appimagetool
    fi

    # 创建 AppDir
    APPDIR="AppDir"
    rm -rf "$APPDIR"
    mkdir -p "$APPDIR/usr/bin"
    mkdir -p "$APPDIR/usr/share/applications"
    mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

    # 复制文件
    cp dist/phpbox "$APPDIR/usr/bin/"
    cp phpbox.desktop "$APPDIR/usr/share/applications/"
    ln -sf usr/share/applications/phpbox.desktop "$APPDIR/phpbox.desktop"

    # 创建 AppRun
    cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/bash
SELF=$(readlink -f "$0")
HERE=${SELF%/*}
export PATH="${HERE}/usr/bin:${PATH}"
exec "${HERE}/usr/bin/phpbox" "$@"
EOF
    chmod +x "$APPDIR/AppRun"

    # 创建占位图标
    if [ -f "resources/icons/phpbox-256.png" ]; then
        cp resources/icons/phpbox-256.png "$APPDIR/phpbox.png"
    else
        # 使用 convert (ImageMagick) 创建简单图标
        if command -v convert &> /dev/null; then
            convert -size 256x256 xc:'#4a90d9' -gravity center -pointsize 72 -fill white -annotate 0 'PHP' "$APPDIR/phpbox.png" 2>/dev/null || true
        fi
        # 备用：创建空图标
        [ ! -f "$APPDIR/phpbox.png" ] && touch "$APPDIR/phpbox.png"
    fi

    # 构建 AppImage
    ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" dist/phpbox-x86_64.AppImage

    rm -rf "$APPDIR"
    echo ">>> AppImage 构建完成: dist/phpbox-x86_64.AppImage"
}

# 构建 deb 包
build_deb() {
    echo ">>> 构建 .deb 包..."

    if [ ! -f "dist/phpbox" ]; then
        build_bin
    fi

    DEB_DIR="deb_package"
    VERSION="1.0.0"
    ARCH="amd64"

    rm -rf "$DEB_DIR"
    mkdir -p "$DEB_DIR/DEBIAN"
    mkdir -p "$DEB_DIR/usr/bin"
    mkdir -p "$DEB_DIR/usr/share/applications"

    # 控制文件
    cat > "$DEB_DIR/DEBIAN/control" << EOF
Package: phpbox
Version: $VERSION
Section: devel
Priority: optional
Architecture: $ARCH
Depends: docker-ce | docker.io, docker-compose-plugin
Maintainer: Your Name <your@email.com>
Description: PHP Development Environment Manager
 A GUI application to manage PHP Docker development environments.
 Supports multiple PHP versions, extensions, and projects.
EOF

    # 复制文件
    cp dist/phpbox "$DEB_DIR/usr/bin/"
    cp phpbox.desktop "$DEB_DIR/usr/share/applications/"

    # 构建
    dpkg-deb --build "$DEB_DIR" "dist/phpbox_${VERSION}_${ARCH}.deb"

    rm -rf "$DEB_DIR"
    echo ">>> .deb 构建完成: dist/phpbox_${VERSION}_${ARCH}.deb"
}

# 解析参数
BUILD_BIN=false
BUILD_APPIMAGE=false
BUILD_DEB=false

if [ $# -eq 0 ]; then
    BUILD_BIN=true
    BUILD_APPIMAGE=true
else
    while [ $# -gt 0 ]; do
        case $1 in
            --all) BUILD_BIN=true; BUILD_APPIMAGE=true ;;
            --bin) BUILD_BIN=true ;;
            --appimage) BUILD_APPIMAGE=true ;;
            --deb) BUILD_DEB=true ;;
            --help) show_help; exit 0 ;;
            *) echo "未知选项: $1"; show_help; exit 1 ;;
        esac
        shift
    done
fi

# 确保至少构建二进制
if [ "$BUILD_APPIMAGE" = true ] || [ "$BUILD_DEB" = true ]; then
    BUILD_BIN=true
fi

# 执行构建
check_venv

[ "$BUILD_BIN" = true ] && build_bin
[ "$BUILD_APPIMAGE" = true ] && build_appimage
[ "$BUILD_DEB" = true ] && build_deb

echo ""
echo "=== 构建完成! ==="
echo "输出目录: dist/"
ls -lh dist/
