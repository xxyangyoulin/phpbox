#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
version=${1:?Usage: build-deb.sh VERSION}
command -v dpkg-deb >/dev/null 2>&1 || { echo '构建 deb 需要 dpkg-deb'; exit 1; }
test -x dist/phpbox/phpbox
test -d dist/phpbox/_internal
if [ "$(dist/phpbox/phpbox --version)" != "pbox $version" ]; then
    echo '程序版本与安装包版本不一致，请先重新构建二进制' >&2
    exit 1
fi

package_dir=$(mktemp -d)
trap 'rm -rf "$package_dir"' EXIT HUP INT TERM
chmod 755 "$package_dir"
mkdir -p "$package_dir/DEBIAN" "$package_dir/opt/phpbox" "$package_dir/usr/bin"
cat > "$package_dir/DEBIAN/control" <<EOF
Package: phpbox
Version: $version
Section: devel
Priority: optional
Architecture: amd64
Depends: docker-ce | docker.io
Maintainer: phpbox <noreply@github.com>
Description: PHP Development Environment Manager
 A GUI application to manage PHP Docker development environments.
 Supports multiple PHP versions, extensions, and projects.
EOF

cp -r dist/phpbox/. "$package_dir/opt/phpbox/"
cat > "$package_dir/usr/bin/phpbox" <<'EOF'
#!/bin/sh
exec /opt/phpbox/phpbox "$@"
EOF
chmod 755 "$package_dir/usr/bin/phpbox"
ln -s phpbox "$package_dir/usr/bin/pbox"
install -Dm644 phpbox.desktop "$package_dir/usr/share/applications/phpbox.desktop"
install -Dm644 resources/icons/phpbox-256.png "$package_dir/usr/share/icons/hicolor/256x256/apps/phpbox.png"
sh resources/install-cli.sh "$package_dir/usr"

package="dist/phpbox_${version}_amd64.deb"
dpkg-deb --root-owner-group -Zgzip --build "$package_dir" "$package"
dpkg-deb --info "$package"
dpkg-deb --contents "$package" > /dev/null
dpkg-deb --extract "$package" "$package_dir/check"
cmp resources/icons/phpbox-256.png "$package_dir/check/usr/share/icons/hicolor/256x256/apps/phpbox.png"
echo ">>> .deb 构建完成: $package"
