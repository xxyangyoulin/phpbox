"""创建项目对话框"""
import os
import shutil
from typing import List, Optional
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QApplication, QStackedWidget, QWidget, QFileDialog
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from pathlib import Path

from qfluentwidgets import (
    SubtitleLabel, BodyLabel, CaptionLabel, StrongBodyLabel,
    LineEdit, PushButton, PrimaryPushButton, CheckBox,
    ComboBox, SpinBox, CardWidget, TextEdit, FluentIcon as FIF,
    InfoBar, InfoBarPosition, Pivot, SegmentedWidget
)

from core.config import BASE_DIR, PHP_VERSIONS, DEFAULT_PORT, ensure_base_dir
from core.config import EXT_VERSION_PHP72, EXT_VERSION_PHP74, EXT_VERSION_PHP83
from core.project import ProjectManager, get_port_usage, find_available_port
from core.proxy import detect_system_proxy, convert_proxy_for_docker
from core.docker import DockerManager
from core.settings import Settings
from ui.widgets.extension_selector import ExtensionSelector
from ui.styles import FluentDialog
from ui.dialogs.build_progress import BuildProgressDialog


class BuildWorker(QThread):
    """构建镜像工作线程"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str, list)  # success, message, logs

    def __init__(self, project_path: Path, proxy: str = None):
        super().__init__()
        self.project_path = project_path
        self.proxy = proxy
        self.logs = []
        self._running = True
        self.process = None

    def run(self):
        import subprocess
        self.logs = []
        try:
            env = os.environ.copy()
            if self.proxy:
                env["HTTP_PROXY"] = self.proxy
                env["HTTPS_PROXY"] = self.proxy
                self.logs.append(f"使用代理: {self.proxy}")
                self.logs.append("")

            cmd = ["docker", "compose", "build", "--no-cache"]
            self.process = subprocess.Popen(
                cmd,
                cwd=str(self.project_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env
            )

            for line in self.process.stdout:
                if not self._running:
                    break
                stripped = line.rstrip()
                self.logs.append(stripped)
                self.progress.emit(stripped)

            self.process.wait()
            
            if not self._running:
                self.finished.emit(False, "构建已取消", self.logs)
                return

            if self.process.returncode == 0:
                self.finished.emit(True, "构建完成", self.logs)
            else:
                self.finished.emit(False, "构建失败", self.logs)
        except Exception as e:
            if self._running:
                self.logs.append(f"错误: {str(e)}")
                self.finished.emit(False, str(e), self.logs)

    def stop(self):
        """停止构建进程"""
        self._running = False
        if self.process:
            self.process.terminate()
            try:
                import subprocess
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()


class CreateProjectDialog(FluentDialog):
    """创建项目对话框 - 三步向导式"""

    # 信号：项目创建成功
    project_created = pyqtSignal(str)  # project_name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("创建新项目")
        self.setMinimumSize(700, 600)
        self.project_manager = ProjectManager()
        self._current_step = 0
        self._created_project_name: Optional[str] = None
        self.setup_ui()
        self.auto_assign_port()  # 自动分配可用端口
        self.detect_proxy()

    def get_created_project_name(self) -> Optional[str]:
        """获取成功创建的项目名"""
        return self._created_project_name

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 24)

        # 顶部步骤指示器
        self.pivot = Pivot(self)
        self.pivot.addItem(routeKey="basic", text="1. 基本信息", onClick=lambda: self._switch_to(0))
        self.pivot.addItem(routeKey="proxy", text="2. 代理配置", onClick=lambda: self._switch_to(1))
        self.pivot.addItem(routeKey="extensions", text="3. PHP 扩展", onClick=lambda: self._switch_to(2))
        layout.addWidget(self.pivot)

        # 页面容器
        self.stacked_widget = QStackedWidget()
        layout.addWidget(self.stacked_widget, 1)

        # 创建三个页面
        self.stacked_widget.addWidget(self._create_basic_page())
        self.stacked_widget.addWidget(self._create_proxy_page())
        self.stacked_widget.addWidget(self._create_extensions_page())

        # 底部导航按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.prev_btn = PushButton("上一步")
        self.prev_btn.clicked.connect(self._prev_step)
        self.prev_btn.setVisible(False)

        self.next_btn = PrimaryPushButton("下一步")
        self.next_btn.clicked.connect(self._next_step)

        self.cancel_btn = PushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)

        self.create_btn = PrimaryPushButton(FIF.ADD, "创建项目")
        self.create_btn.clicked.connect(self.create_project)
        self.create_btn.setVisible(False)

        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.prev_btn)
        btn_layout.addWidget(self.next_btn)
        btn_layout.addWidget(self.create_btn)
        layout.addLayout(btn_layout)

        # 初始状态
        self._update_buttons()
        self.pivot.setCurrentItem("basic")

    def _create_basic_page(self) -> QWidget:
        """创建基本信息页面"""
        from PyQt6.QtWidgets import QFileDialog
        import shutil

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        card = CardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(16)
        card_layout.setContentsMargins(20, 20, 20, 20)

        # 项目类型选择
        type_layout = QHBoxLayout()
        type_layout.addWidget(BodyLabel("项目类型:"))
        self.project_type_segment = SegmentedWidget()
        self.project_type_segment.addItem("new", "新建项目", lambda: self.on_project_type_changed(0))
        self.project_type_segment.addItem("import", "导入已有项目", lambda: self.on_project_type_changed(1))
        self.project_type_segment.setCurrentItem("new")
        type_layout.addWidget(self.project_type_segment)
        type_layout.addStretch()
        card_layout.addLayout(type_layout)

        # 导入源目录（仅导入时显示）
        self.src_dir_layout = QHBoxLayout()
        self.src_dir_label = BodyLabel("源目录:")
        self.src_dir_layout.addWidget(self.src_dir_label)
        self.src_dir_input = LineEdit()
        self.src_dir_input.setPlaceholderText("选择要导入的 PHP 项目目录")
        self.src_dir_input.setReadOnly(True)
        self.src_dir_layout.addWidget(self.src_dir_input, 1)
        self.src_dir_btn = PushButton("浏览")
        self.src_dir_btn.clicked.connect(self.browse_src_directory)
        self.src_dir_layout.addWidget(self.src_dir_btn)
        card_layout.addLayout(self.src_dir_layout)

        # 项目名
        name_layout = QHBoxLayout()
        name_layout.addWidget(BodyLabel("项目名称:"))
        self.name_input = LineEdit()
        self.name_input.setPlaceholderText("仅允许字母、数字、下划线和连字符")
        self.name_input.textChanged.connect(self.check_port)  # 名称改变时重新检查端口
        name_layout.addWidget(self.name_input, 1)
        card_layout.addLayout(name_layout)

        # PHP 版本
        php_layout = QHBoxLayout()
        php_layout.addWidget(BodyLabel("PHP 版本:"))
        self.php_combo = ComboBox()
        self.php_combo.addItems(PHP_VERSIONS)
        self.php_combo.setCurrentText("8.2")
        php_layout.addWidget(self.php_combo)
        php_layout.addStretch()
        card_layout.addLayout(php_layout)

        # 框架选择（仅新建时显示）
        self.framework_layout = QHBoxLayout()
        self.framework_label = BodyLabel("框架:")
        self.framework_layout.addWidget(self.framework_label)
        self.framework_combo = ComboBox()
        self.framework_combo.addItems(["通用", "Laravel", "ThinkPHP"])
        self.framework_layout.addWidget(self.framework_combo)
        self.framework_layout.addStretch()
        card_layout.addLayout(self.framework_layout)

        # 端口
        port_layout = QHBoxLayout()
        port_layout.addWidget(BodyLabel("端口:"))
        self.port_spin = SpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(DEFAULT_PORT)
        self.port_spin.valueChanged.connect(self.on_port_changed)
        self.port_auto_btn = PushButton("自动分配")
        self.port_auto_btn.clicked.connect(self.auto_assign_port)
        self.port_status = CaptionLabel()
        port_layout.addWidget(self.port_spin)
        port_layout.addWidget(self.port_auto_btn)
        port_layout.addWidget(self.port_status)
        port_layout.addStretch()
        card_layout.addLayout(port_layout)

        layout.addWidget(card)
        layout.addStretch()

        # 初始状态：隐藏导入相关控件
        self.on_project_type_changed(0)

        return page

    def on_project_type_changed(self, index: int):
        """项目类型改变时切换显示"""
        is_import = index == 1

        # 显示/隐藏源目录
        self.src_dir_label.setVisible(is_import)
        self.src_dir_input.setVisible(is_import)
        self.src_dir_btn.setVisible(is_import)

        # 导入时自动填充项目名
        if is_import and self.src_dir_input.text():
            src_path = Path(self.src_dir_input.text())
            self.name_input.setText(src_path.name)

    def browse_src_directory(self):
        """浏览选择源目录"""
        dialog = QFileDialog(self)
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        dialog.setDirectory(str(Path.home()))

        if dialog.exec():
            selected = dialog.selectedFiles()
            if selected:
                path = selected[0]
                self.src_dir_input.setText(path)
                # 自动填充项目名
                dir_name = Path(path).name
                self.name_input.setText(dir_name)

    def _create_proxy_page(self) -> QWidget:
        """创建代理配置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        card = CardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(16)
        card_layout.setContentsMargins(20, 20, 20, 20)

        # 提示
        hint = CaptionLabel("代理用于加速 Docker 构建时下载 PHP 扩展，如无需要可跳过")
        hint.setStyleSheet("color: #64748b;")
        card_layout.addWidget(hint)

        # 使用设置中的代理
        self.use_settings_proxy_cb = CheckBox("使用全局设置中的代理")
        self.use_settings_proxy_cb.stateChanged.connect(self.on_use_settings_proxy_changed)
        card_layout.addWidget(self.use_settings_proxy_cb)

        # 使用系统代理
        self.auto_proxy_cb = CheckBox("使用系统代理")
        self.auto_proxy_cb.stateChanged.connect(self.on_auto_proxy_changed)
        card_layout.addWidget(self.auto_proxy_cb)

        # 手动配置
        manual_layout = QHBoxLayout()
        manual_layout.addWidget(BodyLabel("手动配置:"))
        self.proxy_input = LineEdit()
        self.proxy_input.setPlaceholderText("例如: http://127.0.0.1:7890")
        manual_layout.addWidget(self.proxy_input, 1)
        card_layout.addLayout(manual_layout)

        self.proxy_converted = CaptionLabel()
        card_layout.addWidget(self.proxy_converted)

        self.proxy_input.textChanged.connect(self.update_proxy_info)

        layout.addWidget(card)
        layout.addStretch()
        return page

    def _create_extensions_page(self) -> QWidget:
        """创建扩展选择页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        card = CardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)
        card_layout.setContentsMargins(20, 20, 20, 20)

        hint = CaptionLabel("选择需要预装的 PHP 扩展，后续也可在容器内安装")
        hint.setStyleSheet("color: #64748b;")
        card_layout.addWidget(hint)

        self.ext_selector = ExtensionSelector()
        card_layout.addWidget(self.ext_selector)

        layout.addWidget(card, 1)
        return page

    def _switch_to(self, step: int):
        """切换到指定步骤"""
        self._current_step = step
        self.stacked_widget.setCurrentIndex(step)
        self._update_buttons()
        self._update_pivot()

    def _next_step(self):
        """下一步"""
        if self._current_step < 2:
            self._switch_to(self._current_step + 1)

    def _prev_step(self):
        """上一步"""
        if self._current_step > 0:
            self._switch_to(self._current_step - 1)

    def _update_buttons(self):
        """更新按钮状态"""
        self.prev_btn.setVisible(self._current_step > 0)
        self.next_btn.setVisible(self._current_step < 2)
        self.create_btn.setVisible(self._current_step == 2)

    def _update_pivot(self):
        """更新步骤指示器"""
        keys = ["basic", "proxy", "extensions"]
        self.pivot.setCurrentItem(keys[self._current_step])

    def detect_proxy(self):
        """检测并加载代理设置"""
        settings = Settings()

        # 检查设置中的代理
        settings_proxy = settings.get_proxy()
        if settings_proxy:
            self.use_settings_proxy_cb.setText(f"使用全局设置中的代理 ({settings_proxy})")
            self.use_settings_proxy_cb.setChecked(True)
            self.proxy_input.setText(settings_proxy)
            self.proxy_input.setEnabled(False)
            self.auto_proxy_cb.setEnabled(False)
        else:
            self.use_settings_proxy_cb.setText("使用全局设置中的代理 (未配置)")
            self.use_settings_proxy_cb.setEnabled(False)

            # 检测系统代理
            proxy = detect_system_proxy()
            if proxy:
                self.auto_proxy_cb.setText(f"使用系统代理 ({proxy})")
                self.auto_proxy_cb.setChecked(True)
                self.update_proxy_info()

    def on_use_settings_proxy_changed(self, state):
        """使用设置中的代理复选框状态改变"""
        if state == Qt.CheckState.Checked.value:
            settings = Settings()
            proxy = settings.get_proxy()
            if proxy:
                self.proxy_input.setText(proxy)
                self.proxy_input.setEnabled(False)
                self.auto_proxy_cb.setChecked(False)
                self.auto_proxy_cb.setEnabled(False)
        else:
            self.proxy_input.setEnabled(True)
            self.proxy_input.clear()
            self.auto_proxy_cb.setEnabled(True)

    def on_auto_proxy_changed(self, state):
        """自动代理复选框状态改变"""
        if state == Qt.CheckState.Checked.value:
            proxy = detect_system_proxy()
            if proxy:
                self.proxy_input.setText(proxy)
                self.proxy_input.setEnabled(False)
        else:
            self.proxy_input.setEnabled(True)
            self.proxy_input.clear()

    def update_proxy_info(self):
        """更新代理信息"""
        proxy = self.proxy_input.text()
        if proxy:
            docker_proxy = convert_proxy_for_docker(proxy)
            if docker_proxy != proxy:
                self.proxy_converted.setText(f"Docker 代理: {docker_proxy}")
            else:
                self.proxy_converted.setText("")
        else:
            self.proxy_converted.setText("")

    def check_port(self):
        """检查端口占用"""
        port = self.port_spin.value()
        # 获取当前项目名（用于排除自己）
        current_name = self.name_input.text().strip()
        process = get_port_usage(port, current_name if current_name else None)
        if process:
            self.port_status.setText(f"❌ 被 {process} 占用，点击「自动分配」")
        else:
            self.port_status.setText("✓ 可用")

    def on_port_changed(self):
        """端口值改变时检查"""
        self.check_port()

    def auto_assign_port(self):
        """自动分配可用端口"""
        # 获取当前项目名（用于排除自己）
        current_name = self.name_input.text().strip()
        port = find_available_port(self.port_spin.value(), 100, current_name if current_name else None)
        self.port_spin.setValue(port)
        self.port_status.setText("✓ 已自动分配")

    def create_project(self):
        """创建项目"""
        # 检查是否为导入项目
        is_import = self.project_type_segment.currentItem() == "import"
        src_dir = self.src_dir_input.text().strip() if is_import else None

        # 导入项目时验证源目录
        if is_import:
            if not src_dir:
                InfoBar.error(
                    title="错误",
                    content="请选择要导入的源目录",
                    orient=Qt.Orientation.Horizontal,
                    parent=self
                )
                return
            if not Path(src_dir).exists():
                InfoBar.error(
                    title="错误",
                    content="源目录不存在",
                    orient=Qt.Orientation.Horizontal,
                    parent=self
                )
                return

        # 验证输入
        name = self.name_input.text().strip()
        valid, msg = self.project_manager.is_valid_name(name)
        if not valid:
            InfoBar.error(
                title="验证失败",
                content=msg,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return

        if self.project_manager.project_exists(name):
            InfoBar.error(
                title="错误",
                content=f"项目 '{name}' 已存在",
                orient=Qt.Orientation.Horizontal,
                parent=self
            )
            return

        # 检查端口
        port = self.port_spin.value()
        process = get_port_usage(port, name)
        if process:
            InfoBar.error(
                title="端口冲突",
                content=f"端口 {port} 被 {process} 占用",
                orient=Qt.Orientation.Horizontal,
                parent=self
            )
            return

        php_version = self.php_combo.currentText()
        extensions = self.ext_selector.get_selected_extensions()
        proxy = self.proxy_input.text().strip()
        framework = self.framework_combo.currentText()
        src_path = Path(src_dir) if is_import else None

        # 保存项目名用于创建成功后选中
        self._creating_project_name = name

        # 创建进度对话框
        self.progress_dialog = BuildProgressDialog(name, self)
        self.progress_dialog.show()
        QApplication.processEvents()
        self.hide()  # 隐藏创建对话框

        # 创建项目目录
        project_path = BASE_DIR / name
        try:
            self.progress_dialog.append_log(f"项目名称: {name}")
            self.progress_dialog.append_log(f"PHP 版本: {php_version}")
            self.progress_dialog.append_log(f"端口: {port}")
            if extensions:
                self.progress_dialog.append_log(f"扩展: {', '.join(extensions)}")
            if proxy:
                self.progress_dialog.append_log(f"代理: {proxy}")
            self.progress_dialog.append_log("")
            self.progress_dialog.append_log("正在创建项目文件...")

            self.create_project_files(project_path, name, php_version, port, extensions, proxy, src_path, framework)
            self.progress_dialog.append_log("✓ 项目文件创建完成")
            self.progress_dialog.append_log("")

            # 构建镜像
            self.build_and_start(project_path, proxy)
        except Exception as e:
            self.progress_dialog.append_log(f"❌ 错误: {str(e)}")
            self.progress_dialog.append_log("正在清理...")
            self._cleanup_failed_project(project_path)
            self.progress_dialog.set_finished(False, str(e))
            self.progress_dialog.accepted.connect(self.reject)

    def create_project_files(self, project_path: Path, project_name: str,
                             php_version: str, port: int, extensions: List[str], proxy: str,
                             src_path: Path = None, framework: str = "通用"):
        """创建项目文件"""
        # 创建目录结构
        for subdir in ['src', 'nginx', 'php', 'logs/nginx', 'logs/php-fpm']:
            (project_path / subdir).mkdir(parents=True, exist_ok=True)

        # 生成 Dockerfile
        dockerfile = self.generate_dockerfile(project_name, php_version, extensions, proxy)
        (project_path / "Dockerfile").write_text(dockerfile)

        # 生成 docker-compose.yml
        compose = self.generate_compose(project_name, port, proxy)
        (project_path / "docker-compose.yml").write_text(compose)

        # 生成 src 目录内容
        if src_path:
            # 导入项目：复制源代码
            for item in src_path.iterdir():
                if item.is_dir():
                    shutil.copytree(item, project_path / "src" / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, project_path / "src" / item.name)
        else:
            # 新建项目：生成 index.php
            (project_path / "src" / "index.php").write_text("<?php\nphpinfo();\n")

        # 生成 nginx 配置
        nginx_conf = self.generate_nginx_config(framework)
        (project_path / "nginx" / "default.conf").write_text(nginx_conf)

    def generate_dockerfile(self, project_name: str, php_version: str,
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
                f'ENV http_proxy="{docker_proxy}"',
                f'ENV https_proxy="{docker_proxy}"',
                f'ENV HTTP_PROXY="{docker_proxy}"',
                f'ENV HTTPS_PROXY="{docker_proxy}"',
                "",
            ])

        lines.extend([
            "# install-php-extensions 自动处理各 PHP 版本扩展兼容性",
            "ADD https://github.com/mlocati/docker-php-extension-installer/releases/latest/download/install-php-extensions /usr/local/bin/",
            "RUN chmod +x /usr/local/bin/install-php-extensions",
            "",
            "# 安装 Composer",
            "COPY --from=composer:latest /usr/bin/composer /usr/bin/composer",
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
            "# 安装基础工具 (包含 git, openssh-client, zsh)",
            "RUN apt-get update && apt-get install -y unzip git openssh-client zsh curl wget sudo && rm -rf /var/lib/apt/lists/*",
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
            install_lines = self.generate_ext_install_lines(php_version, extensions)
            lines.extend(install_lines)

        # 清除代理
        if docker_proxy:
            lines.extend([
                "",
                "# 清除代理，避免运行时影响业务",
                "ENV http_proxy=''",
                "ENV https_proxy=''",
            ])

        return "\n".join(lines) + "\n"

    def generate_ext_install_lines(self, php_version: str,
                                    extensions: List[str]) -> List[str]:
        """生成扩展安装命令"""
        # 优先安装的扩展
        priority = ["igbinary", "msgpack"]

        # 根据版本选择扩展名
        def get_ext_name(ext: str) -> str:
            if php_version == "7.2" and ext in EXT_VERSION_PHP72:
                return EXT_VERSION_PHP72[ext]
            elif php_version in ["7.3", "7.4", "8.0", "8.1", "8.2"] and ext in EXT_VERSION_PHP74:
                return EXT_VERSION_PHP74[ext]
            elif ext in EXT_VERSION_PHP83:
                return EXT_VERSION_PHP83[ext]
            return ext

        priority_exts = []
        normal_exts = []

        for ext in extensions:
            name = get_ext_name(ext)
            if ext in priority:
                priority_exts.append(name)
            else:
                normal_exts.append(name)

        lines = []
        if priority_exts:
            lines.append(f"RUN install-php-extensions {' '.join(priority_exts)}")
        if normal_exts:
            lines.append(f"RUN install-php-extensions {' '.join(normal_exts)}")
        return lines

    def generate_compose(self, project_name: str, port: int, proxy: str) -> str:
        """生成 docker-compose.yml 内容"""
        uid = os.getuid()
        gid = os.getgid()
        uid_gid = f"{uid}:{gid}"
        docker_proxy = convert_proxy_for_docker(proxy) if proxy else None

        # 项目名前缀
        prefix = f"phpdev-{project_name}"

        # 构建参数
        build_args = f"""      args:
        USER_UID: {uid}
        USER_GID: {gid}"""

        if docker_proxy:
            build_args += f"""
        HTTP_PROXY: {docker_proxy}
        HTTPS_PROXY: {docker_proxy}"""

        content = f"""name: {prefix}

services:
  php:
    container_name: {prefix}-php
    build:
      context: .
      dockerfile: Dockerfile
{build_args}
    restart: unless-stopped
    user: "{uid_gid}"
    environment:
      - PROJECT_NAME={project_name}
    volumes:
      - ./src:/var/www/html
      - ./php/php.ini:/usr/local/etc/php/php.ini
      - ./php/php-fpm.conf:/usr/local/etc/php-fpm.conf
      - ./php/www.conf:/usr/local/etc/php-fpm.d/www.conf
      - ./logs/php-fpm:/var/log/php-fpm
      # SSH 密钥 - 用于访问私有 Git 仓库
      - ~/.ssh:/home/user/.ssh:ro
      # Git 配置 - 保持与宿主机一致的用户信息
      - ~/.gitconfig:/home/user/.gitconfig:ro
    networks:
      - app

  nginx:
    container_name: {prefix}-nginx
    image: nginx:alpine
    restart: unless-stopped
    entrypoint: ["nginx", "-g", "daemon off;"]
    ports:
      - "{port}:80"
    volumes:
      - ./src:/var/www/html
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf
      - ./logs/nginx:/var/log/nginx
    depends_on:
      - php
    networks:
      - app

networks:
  app:
"""
        return content

    def generate_nginx_config(self, framework: str = "通用") -> str:
        """生成 nginx 配置"""

        if framework == "Laravel":
            return """server {
    listen       80;
    server_name  localhost;
    root         /var/www/html/public;
    index        index.php index.html;

    # Laravel 伪静态
    location / {
        try_files $uri $uri/ /index.php?$query_string;
    }

    location ~ \\.php$ {
        fastcgi_pass   php:9000;
        fastcgi_index  index.php;
        include        fastcgi_params;
        fastcgi_param  SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_param  PATH_INFO       $fastcgi_path_info;
    }

    # 禁止访问隐藏文件
    location ~ /\\. {
        deny all;
    }

    # 禁止访问敏感文件
    location ~ /\\.(env|git|editorconfig) {
        deny all;
    }

    error_page  404              /404.html;
    error_page  500 502 503 504  /50x.html;
    location = /50x.html {
        root /usr/share/nginx/html;
    }
}
"""

        elif framework == "ThinkPHP":
            return """server {
    listen       80;
    server_name  localhost;
    root         /var/www/html/public;
    index        index.php index.html;

    # ThinkPHP 伪静态
    location / {
        if (!-e $request_filename) {
            rewrite ^(.*)$ /index.php?s=$1 last;
        }
    }

    location ~ \\.php$ {
        fastcgi_pass   php:9000;
        fastcgi_index  index.php;
        include        fastcgi_params;
        fastcgi_param  SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_param  PATH_INFO       $fastcgi_path_info;
        fastcgi_param  REQUEST_URI     $request_uri;
    }

    # 禁止访问隐藏文件
    location ~ /\\. {
        deny all;
    }

    error_page  404              /404.html;
    error_page  500 502 503 504  /50x.html;
    location = /50x.html {
        root /usr/share/nginx/html;
    }
}
"""

        else:  # 通用
            return """server {
    listen       80;
    server_name  localhost;
    root         /var/www/html;
    index        index.php index.html;

    # 静态文件直接返回，找不到时走 @php
    location / {
        try_files $uri $uri/ @php;
    }

    location ~ \\.php$ {
        fastcgi_pass   php:9000;
        fastcgi_index  index.php;
        include        fastcgi_params;
        fastcgi_param  SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_param  PATH_INFO       $fastcgi_path_info;
    }

    # 框架路由兜底
    location @php {
        rewrite ^ /index.php last;
    }

    # 禁止访问隐藏文件
    location ~ /\\. {
        deny all;
    }

    error_page  404              /404.html;
    error_page  500 502 503 504  /50x.html;
    location = /50x.html {
        root /usr/share/nginx/html;
    }
}
"""

    def build_and_start(self, project_path: Path, proxy: str):
        """构建并启动服务"""
        self.progress_dialog.set_building()
        self.progress_dialog.append_log("开始构建 Docker 镜像...")
        self.progress_dialog.append_log("")

        self.build_worker = BuildWorker(project_path, convert_proxy_for_docker(proxy) if proxy else None)
        self.build_worker.progress.connect(self._on_build_progress)
        self.build_worker.finished.connect(lambda success, msg, logs: self._on_build_finished(success, msg, logs, project_path))
        
        # 监听对话框关闭，以便终止构建进程
        self.progress_dialog.rejected.connect(self._on_progress_dialog_rejected)
        
        self.build_worker.start()

    def _on_progress_dialog_rejected(self):
        """进度对话框被取消或关闭"""
        if hasattr(self, 'build_worker') and self.build_worker and self.build_worker.isRunning():
            self.progress_dialog.append_log("正在终止构建操作...")
            self.build_worker.stop()
            self.build_worker.wait()

    def _on_build_progress(self, msg: str):
        """构建进度回调"""
        if self.progress_dialog and not self.progress_dialog.cancelled:
            self.progress_dialog.append_log(msg)

    def _cleanup_failed_project(self, project_path: Path):
        """清理失败的项目：删除容器、镜像和项目文件"""
        import shutil

        # 删除容器和镜像
        if project_path.exists():
            docker = DockerManager(project_path)
            docker.down(remove_images=True)
            self.progress_dialog.append_log("已清理容器和镜像")

        # 删除项目文件
        if project_path.exists():
            shutil.rmtree(project_path)
            self.progress_dialog.append_log("已删除项目文件")

    def _on_build_finished(self, success: bool, msg: str, logs: list, project_path: Path):
        """构建完成回调"""
        if self.progress_dialog.cancelled:
            # 用户取消了构建
            self.progress_dialog.append_log("正在清理...")
            self._cleanup_failed_project(project_path)
            self.progress_dialog.accepted.connect(self.reject)
            return

        if not success:
            self.progress_dialog.append_log("")
            self.progress_dialog.append_log(f"❌ 构建失败: {msg}")
            self.progress_dialog.append_log("正在清理...")
            self._cleanup_failed_project(project_path)
            self.progress_dialog.set_finished(False, msg)
            self.progress_dialog.accepted.connect(self.reject)
            return

        self.progress_dialog.append_log("")
        self.progress_dialog.append_log("✓ 镜像构建完成")
        self.progress_dialog.append_log("正在复制配置文件...")

        # 复制配置文件
        try:
            self.copy_configs(project_path)
            self.progress_dialog.append_log("✓ 配置文件复制完成")
        except Exception as e:
            self.progress_dialog.append_log(f"❌ 配置文件复制失败: {str(e)}")
            self.progress_dialog.append_log("正在清理...")
            self._cleanup_failed_project(project_path)
            self.progress_dialog.set_finished(False, str(e))
            self.progress_dialog.accepted.connect(self.reject)
            return

        # 启动服务
        self.progress_dialog.append_log("正在启动服务...")
        docker = DockerManager(project_path)
        result = docker.up()

        if result.success:
            self.progress_dialog.append_log("等待容器就绪...")
            if not docker.wait_until_running("php", timeout=30):
                self.progress_dialog.append_log("⚠ 容器启动超时，服务可能尚未就绪")
            self.progress_dialog.append_log(f"✓ 服务已启动: http://localhost:{self.port_spin.value()}")
            self.progress_dialog.set_finished(True)
            self._created_project_name = self._creating_project_name
            # 发送信号并关闭
            self.project_created.emit(self._created_project_name)
            self.accept()  # 关闭创建项目对话框
        else:
            self.progress_dialog.append_log(f"❌ 服务启动失败: {result.error}")
            self.progress_dialog.append_log("正在清理...")
            self._cleanup_failed_project(project_path)
            self.progress_dialog.set_finished(False, f"启动失败: {result.error}")
            self.progress_dialog.accepted.connect(self.reject)

    def copy_configs(self, project_path: Path):
        """从镜像复制配置文件，失败时抛出异常"""
        docker = DockerManager(project_path)
        image = docker.get_image_name()

        # 复制 PHP 配置
        if not docker.copy_config_from_image(image, "/usr/local/etc/php/php.ini-development",
                                       project_path / "php" / "php.ini"):
            raise Exception("复制 php.ini 失败")
        if not docker.copy_config_from_image(image, "/usr/local/etc/php-fpm.conf",
                                       project_path / "php" / "php-fpm.conf"):
            raise Exception("复制 php-fpm.conf 失败")
        if not docker.copy_config_from_image(image, "/usr/local/etc/php-fpm.d/www.conf",
                                       project_path / "php" / "www.conf"):
            raise Exception("复制 www.conf 失败")

        # 复制 nginx 配置
        if not docker.copy_config_from_image("nginx:alpine", "/etc/nginx/nginx.conf",
                                       project_path / "nginx" / "nginx.conf"):
            raise Exception("复制 nginx.conf 失败")
