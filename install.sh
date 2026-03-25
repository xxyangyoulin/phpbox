#!/bin/bash
# 安装脚本 - 支持 Deepin、Arch、Ubuntu 等发行版

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DIST_DIR="$SCRIPT_DIR/dist"
INSTALL_DIR="/opt/phpbox"

# 检测发行版
detect_distro() {
    if [ -f /etc/deepin-version ]; then
        echo "deepin"
    elif [ -f /etc/arch-release ]; then
        echo "arch"
    elif [ -f /etc/lsb-release ] && grep -q "Ubuntu" /etc/lsb-release 2>/dev/null; then
        echo "ubuntu"
    elif [ -f /etc/debian_version ]; then
        echo "debian"
    else
        echo "unknown"
    fi
}

# 安装到系统
install_system() {
    echo ">>> 安装 PHP 开发环境管理器..."

    # 安装程序目录
    sudo rm -rf "$INSTALL_DIR"
    sudo mkdir -p "$INSTALL_DIR"
    sudo cp -r "$DIST_DIR/phpbox/." "$INSTALL_DIR/"

    # 创建启动脚本
    sudo tee /usr/local/bin/phpbox >/dev/null << EOF
#!/bin/bash
exec "$INSTALL_DIR/phpbox" "\$@"
EOF
    sudo chmod +x /usr/local/bin/phpbox

    # 复制 desktop 文件
    sudo cp "$SCRIPT_DIR/phpbox.desktop" /usr/share/applications/
    sudo chmod 644 /usr/share/applications/phpbox.desktop

    # 安装图标
    if [ -f "$SCRIPT_DIR/resources/icons/phpbox-256.png" ]; then
        sudo mkdir -p "/usr/share/icons/hicolor/256x256/apps/"
        sudo cp "$SCRIPT_DIR/resources/icons/phpbox-256.png" "/usr/share/icons/hicolor/256x256/apps/phpbox.png"
        # 更新图标缓存
        sudo gtk-update-icon-cache -f /usr/share/icons/hicolor/ 2>/dev/null || true
    fi

    # 更新桌面数据库
    sudo update-desktop-database /usr/share/applications/ 2>/dev/null || true

    echo ""
    echo "=== 安装完成! ==="
    echo "可在应用菜单中找到「PHP 开发环境管理器」"
    echo "或运行: phpbox"
}

# 卸载
uninstall() {
    echo ">>> 卸载 PHP 开发环境管理器..."
    sudo rm -f /usr/local/bin/phpbox
    sudo rm -rf "$INSTALL_DIR"
    sudo rm -f /usr/share/applications/phpbox.desktop
    sudo rm -f /usr/share/icons/hicolor/*/apps/phpbox.png
    sudo gtk-update-icon-cache -f /usr/share/icons/hicolor/ 2>/dev/null || true
    sudo update-desktop-database /usr/share/applications/ 2>/dev/null || true
    echo "卸载完成"
}

# 创建 AppImage
create_appimage() {
    echo ">>> 创建 AppImage..."

    if [ ! -x "$DIST_DIR/phpbox/phpbox" ]; then
        echo "错误: 未找到目录式构建产物 $DIST_DIR/phpbox/phpbox"
        echo "请先运行 ./build.sh --bin"
        exit 1
    fi

    # 检查 appimagetool
    if ! command -v appimagetool &> /dev/null; then
        echo "安装 appimagetool..."
        wget -q https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage -O /tmp/appimagetool
        chmod +x /tmp/appimagetool
        APPIMAGETOOL=/tmp/appimagetool
    else
        APPIMAGETOOL=appimagetool
    fi

    # 创建 AppDir 结构
    APPDIR="$SCRIPT_DIR/AppDir"
    rm -rf "$APPDIR"
    mkdir -p "$APPDIR/usr/bin"
    mkdir -p "$APPDIR/usr/share/applications"
    mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

    # 复制文件
    cp -r "$DIST_DIR/phpbox/." "$APPDIR/usr/bin/"
    cp "$SCRIPT_DIR/phpbox.desktop" "$APPDIR/usr/share/applications/"
    ln -sf "$APPDIR/usr/share/applications/phpbox.desktop" "$APPDIR/phpbox.desktop"

    # 创建启动脚本
    cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/bash
SELF=$(readlink -f "$0")
HERE=${SELF%/*}
export PATH="${HERE}/usr/bin:${PATH}"
exec "${HERE}/usr/bin/phpbox" "$@"
EOF
    chmod +x "$APPDIR/AppRun"

    # 如果有图标
    if [ -f "$SCRIPT_DIR/resources/icons/phpbox-256.png" ]; then
        cp "$SCRIPT_DIR/resources/icons/phpbox-256.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/phpbox.png"
        cp "$SCRIPT_DIR/resources/icons/phpbox-256.png" "$APPDIR/phpbox.png"
    fi

    # 构建 AppImage
    ARCH=x86_64 $APPIMAGETOOL "$APPDIR" "$SCRIPT_DIR/dist/phpbox-x86_64.AppImage"

    echo "AppImage 创建完成: $SCRIPT_DIR/dist/phpbox-x86_64.AppImage"
}

# 主菜单
main() {
    distro=$(detect_distro)
    echo "检测到发行版: $distro"
    echo ""
    echo "PHP 开发环境管理器 - 安装工具"
    echo "================================"
    echo "1) 安装到系统"
    echo "2) 卸载"
    echo "3) 创建 AppImage (通用 Linux 格式)"
    echo "4) 退出"
    echo ""
    read -p "请选择 [1-4]: " choice

    case $choice in
        1) install_system ;;
        2) uninstall ;;
        3) create_appimage ;;
        4) exit 0 ;;
        *) echo "无效选择"; exit 1 ;;
    esac
}

# 如果有参数，直接执行
case "${1:-}" in
    install) install_system ;;
    uninstall) uninstall ;;
    appimage) create_appimage ;;
    *) main ;;
esac
