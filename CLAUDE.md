# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PHP Development Environment Manager (phpbox) is a PyQt6 GUI application for managing PHP Docker development environments. It allows users to create, manage, and interact with PHP projects running in Docker containers with support for multiple PHP versions (7.2-8.4) and 60+ PHP extensions.

## Commands

### Development
```bash
# Activate virtual environment and run
source .venv/bin/activate
python main.py

# Run with options
python main.py --hide          # Start hidden (tray only)
python main.py --new-project   # Open new project dialog on startup
```

### Building
```bash
source .venv/bin/activate

./build.sh --bin        # Build binary only (dist/phpbox)
./build.sh --appimage   # Build AppImage (dist/phpbox-x86_64.AppImage)
./build.sh --deb        # Build .deb package
./build.sh --all        # Build all formats (default)
```

## Architecture

### Core Modules (`core/`)
- **`config.py`** - PHP versions, extension definitions (categorized), version-specific extension compatibility
- **`docker.py`** - `DockerManager` class wraps `docker compose` commands (up, stop, restart, logs, exec)
- **`project.py`** - `ProjectManager` handles project discovery/CRUD; `Project` dataclass holds project state
- **`settings.py`** - App settings via QSettings (theme, proxy)
- **`proxy.py`** - Proxy configuration for Docker builds

### UI Structure (`ui/`)
- **`main_window.py`** - `MainWindow` (FluentWindow) with navigation sidebar; `ProjectDashboardPage` shows project details
- **`styles.py`** - Theme management (light/dark/auto) using PyQt6-Fluent-Widgets
- **`dialogs/`** - Modal dialogs: `create_project`, `log_viewer`, `install_ext`, `settings`, `config_editor`, `xdebug_dialog`
- **`widgets/`** - Reusable components: `project_list`, `extension_selector`, `status_indicator`

### Data Flow
1. Projects stored as directories in `~/php-dev/projects/{project_name}/`
2. Each project contains: `docker-compose.yml`, `Dockerfile`, `.env`
3. `ProjectManager` scans BASE_DIR to discover projects
4. `DockerManager(project_path)` executes compose commands for a project
5. UI polls every 5 seconds to refresh project status

### Key Dependencies
- PyQt6 >= 6.5.0
- PyQt6-Fluent-Widgets >= 1.4.0 (Fluent Design UI components)
- PyInstaller >= 6.0.0 (for building)

## Important Notes

- UI text is in Chinese (简体中文)
- App uses system tray (`setQuitOnLastWindowClosed(False)`) - closing window hides, doesn't quit
- Extension installation uses `install-php-extensions` script inside containers
- Terminal support: Kitty, Alacritty, GNOME Terminal, Konsole, xterm (tried in order)
