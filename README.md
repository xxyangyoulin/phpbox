# phpbox

在 Linux 上做 PHP 开发，最麻烦的通常不是写代码，而是维护环境：
不同项目要不同的 PHP 版本，不同扩展组合，日志、容器、端口、Xdebug 和构建过程又分散在一堆 Docker 命令里。

`phpbox` 用 Docker 为每个项目提供独立运行环境，并通过 GUI 和 CLI 把项目管理、命令执行、日志查看、镜像构建和调试入口统一起来。

![Python](https://img.shields.io/badge/python-3.8+-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

![Screenshot](screenshot.png)

## 特性

- 支持 PHP `7.2` 到 `8.4`
- 支持 `60+` PHP 扩展
- 图形化创建、管理、启动、停止项目
- 内置 Xdebug 配置能力
- 支持查看日志、进入容器、执行命令
- 支持 Wayland 与 X11 环境
- 提供面向日常开发的 CLI

## 环境要求

- Linux
- Docker
- `docker compose` 或 `docker-compose`
- Python `3.8+`

如果你主要使用 CLI，也建议先确保：

```bash
docker info
docker compose version
```

## 安装与运行

### 从源码运行

```bash
git clone https://github.com/xxyangyoulin/phpbox.git
cd phpbox

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python main.py
```

### 构建可执行文件

```bash
./build.sh --bin
```

构建完成后，主程序位于：

```bash
dist/phpbox/phpbox
```

### 安装到系统

如果你已经构建好目录式产物，可以执行：

```bash
./install.sh install
```

安装后：

- 程序主体位于 `/opt/phpbox`
- 启动命令为 `phpbox`

## GUI 功能

图形界面适合这些操作：

- 创建新项目
- 选择 PHP 版本
- 选择并安装 PHP 扩展
- 可选启用 MySQL / Redis
- 修改项目配置
- 管理 Xdebug
- 查看项目状态、运行日志和访问地址

典型流程：

1. 点击“新建项目”
2. 输入项目名称
3. 选择 PHP 版本和端口
4. 按需选择 PHP 扩展
5. 如有需要，启用 MySQL / Redis
6. 创建并启动项目

### 可选服务

新建项目时可以额外启用：

- MySQL
- Redis

默认连接方式如下：

#### MySQL

- Host: `127.0.0.1`
- Port: 你在创建项目时设置的端口，默认 `3306`
- Database: 默认使用项目名
- User: 默认 `app`
- Password: 默认 `app`

#### Redis

- Host: `127.0.0.1`
- Port: 你在创建项目时设置的端口，默认 `6379`

## CLI

phpbox 的 CLI 适合高频终端操作。它有两个核心设计：

- 在任意目录下，可以通过项目名管理项目
- 在项目目录或其子目录下，可以省略项目名，自动作用于当前项目

### 项目管理命令

```bash
phpbox list
phpbox ps
phpbox status [项目名]

phpbox start [项目名]
phpbox stop [项目名]
phpbox restart [项目名]

phpbox up [项目名]
phpbox down [项目名]
```

说明：

- `phpbox ps` 是 `status` 的快捷写法
- `phpbox up` 是 `start` 的快捷写法
- `phpbox stop` 只停止容器
- `phpbox down` 会执行 `docker compose down`，停止并移除项目容器

### 日志与诊断

```bash
phpbox logs [项目名]
phpbox logs [项目名] --service php
phpbox logs [项目名] --service nginx
phpbox logs [项目名] --service mysql
phpbox logs [项目名] --service redis
phpbox logs [项目名] --no-follow

phpbox doctor
```

说明：

- `phpbox logs` 默认持续追踪日志
- 如果只想看当前日志，不持续输出，使用 `--no-follow`
- `doctor` 会检查 Docker、Compose、终端环境和日志目录等基础条件

### 构建镜像

```bash
phpbox build [项目名]
phpbox build [项目名] --no-cache

phpbox rebuild [项目名]
phpbox rebuild [项目名] --no-cache
```

说明：

- `build` 会执行当前项目的 `docker compose build`
- `rebuild` 当前也执行构建，但通常语义上表示“重新构建”
- `--no-cache` 会强制忽略 Docker 层缓存
- 构建时会实时输出日志
- 构建成功后不会自动重启容器

如果你希望新镜像生效，通常还需要执行：

```bash
phpbox restart
```

或者：

```bash
phpbox down
phpbox up
```

### 进入容器与执行命令

```bash
phpbox shell
phpbox shell php
phpbox shell nginx
phpbox shell mysql
phpbox shell redis

phpbox exec php -- php -v
phpbox exec php -- ls -la
phpbox exec nginx -- nginx -t
phpbox exec mysql -- mysql --version
phpbox exec redis -- redis-cli ping
```

说明：

- `phpbox shell` 默认进入 `php` 容器
- `phpbox shell nginx` 可进入 `nginx` 容器
- `phpbox shell mysql|redis` 可进入对应服务容器
- `phpbox exec` 适合执行一次性命令

### PHP / Composer / 框架命令

```bash
phpbox php -v
phpbox php -m

phpbox composer install
phpbox composer update

phpbox artisan migrate
phpbox artisan route:list

phpbox think queue:listen
phpbox think route:list
```

说明：

- 这些命令都要求你当前位于项目目录或其子目录中
- 对 `php` 容器命令，phpbox 会尽量把当前代码子目录映射到容器中的对应工作目录

### 在项目目录中直接执行

如果当前目录属于某个项目，以下命令会自动选中当前项目：

```bash
phpbox ps
phpbox status
phpbox up
phpbox stop
phpbox down
phpbox restart
phpbox logs
phpbox logs --no-follow
phpbox build
phpbox rebuild --no-cache
phpbox shell
phpbox shell nginx
phpbox php -v
phpbox composer install
phpbox artisan migrate
phpbox think queue:listen
phpbox exec php -- php -m
```

这也是 phpbox CLI 最推荐的使用方式。

## 常见工作流

### 查看所有项目

```bash
phpbox list
```

### 启动一个指定项目

```bash
phpbox up myproject
```

### 在项目目录中执行 Composer

```bash
cd ~/php-dev/projects/myproject/myproject
phpbox composer install
```

### 在项目目录中执行 Laravel Artisan

```bash
cd ~/php-dev/projects/myproject/myproject
phpbox artisan migrate
```

### 在项目目录中执行 ThinkPHP 命令

```bash
cd ~/php-dev/projects/myproject/myproject
phpbox think queue:listen
```

### 重新构建镜像并重启

```bash
phpbox rebuild --no-cache
phpbox restart
```

### 查看 PHP 服务日志

```bash
phpbox logs --service php
```

## 构建与发布

### 本地构建

```bash
./build.sh --bin
./build.sh --appimage
./build.sh --deb
```

说明：

- `--bin` 生成目录式可执行产物
- `--appimage` 构建 AppImage
- `--deb` 构建 `.deb` 包，需要系统中存在 `dpkg-deb`

在 Arch Linux 上，`dpkg-deb` 来自：

```bash
sudo pacman -S dpkg
```

### GitHub Actions

项目已配置 GitHub Actions 构建流程。推送版本 tag 后会自动构建并发布：

```bash
git tag v1.0.14
git push origin v1.0.14
```

## Wayland 与 tmux

项目已支持 Wayland。若在 Hyprland 等环境下出现“明明在 Wayland 中却像走了 XWayland”的情况，先检查当前 shell 环境：

```bash
echo "$XDG_SESSION_TYPE"
echo "$WAYLAND_DISPLAY"
```

如果你通过旧的 `tmux` session 进入图形环境，可能会继承到 `tty` 环境变量。此时建议：

```bash
tmux kill-server
tmux
```

并在 `~/.tmux.conf` 中加入：

```tmux
set -g update-environment "DISPLAY WAYLAND_DISPLAY XAUTHORITY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS"
```

## 技术栈

| 技术 | 版本 |
|------|------|
| PyQt6 | >= 6.5.0 |
| PyQt6-Fluent-Widgets | >= 1.4.0 |
| Docker & Docker Compose | - |

## 许可证

MIT License
