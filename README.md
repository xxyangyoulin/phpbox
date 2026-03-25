# phpbox

PHP Docker 开发环境管理器 —— 图形化管理 PHP 容器环境

![Python](https://img.shields.io/badge/python-3.8+-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

![Screenshot](screenshot.png)

## 特性

- PHP **7.2 - 8.4** 多版本支持
- **60+** PHP 扩展，按分类选择
- Docker 容器启停、日志查看、命令执行
- Xdebug 一键配置
- 现代化 UI，浅色/深色主题
- 系统托盘常驻

## 安装

```bash
# 克隆仓库
git clone https://github.com/yourusername/phpbox.git
cd phpbox

# 安装依赖
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 运行
python main.py
```

## 使用

1. 点击 **新建项目**，输入项目名称
2. 选择 PHP 版本和端口
3. 勾选需要的 PHP 扩展
4. 点击创建，自动生成 Docker 配置并启动容器

## 命令行

phpbox 同时提供常用 CLI，适合在终端里快速管理项目。

### 常用命令

```bash
phpbox list
phpbox ps
phpbox status test
phpbox up test
phpbox stop test
phpbox down test
phpbox restart test
phpbox logs test
phpbox build test
phpbox rebuild test --no-cache
phpbox doctor
```

### 在项目目录中直接执行

如果当前目录位于某个项目目录或其子目录中，以下命令会自动选中当前项目：

```bash
phpbox ps
phpbox up
phpbox stop
phpbox down
phpbox restart
phpbox logs
phpbox logs --no-follow
phpbox shell
phpbox shell nginx
phpbox php -v
phpbox composer install
phpbox artisan migrate
phpbox think queue:listen
phpbox build
phpbox rebuild --no-cache
```

这意味着你不需要再额外输入项目名称，直接在项目目录里执行即可。

- `phpbox up` 等价于启动项目
- `phpbox stop` 仅停止容器
- `phpbox down` 会执行 `docker compose down`，停止并移除项目容器
- `phpbox logs` 默认持续追踪日志，若只查看当前日志可加 `--no-follow`

## 构建

```bash
./build.sh --bin        # 二进制
./build.sh --appimage   # AppImage
./build.sh --deb        # deb 包
```

## 技术栈

| 技术 | 版本 |
|------|------|
| PyQt6 | >= 6.5.0 |
| PyQt6-Fluent-Widgets | >= 1.4.0 |
| Docker & Docker Compose | - |

## 许可证

MIT License
