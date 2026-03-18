import re

with open('ui/main_window.py', 'r') as f:
    content = f.read()

# 1. Add QLabel to imports
content = content.replace(
'''from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QSystemTrayIcon, QApplication, QGridLayout, QSizePolicy,
    QGraphicsOpacityEffect
)''',
'''from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QSystemTrayIcon, QApplication, QGridLayout, QSizePolicy,
    QGraphicsOpacityEffect, QLabel
)''')

# 2. Replace setup_ui until config_card
target_setup_ui = re.search(r'    def setup_ui\(self\):.*?        # --- PHP 配置信息卡片 ---', content, re.DOTALL).group(0)

replacement_setup_ui = '''    def setup_ui(self):
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(32, 24, 32, 32)
        layout.setSpacing(24)

        # --- 顶部信息卡片 ---
        self.header_card = CardWidget()
        h_layout = QVBoxLayout(self.header_card)
        h_layout.setContentsMargins(24, 24, 24, 24)
        h_layout.setSpacing(16)

        # 顶部主要区域
        top_main_layout = QHBoxLayout()
        top_main_layout.setSpacing(16)

        # 头像
        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(48, 48)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_main_layout.addWidget(self.avatar_label)
        top_main_layout.setAlignment(self.avatar_label, Qt.AlignmentFlag.AlignTop)

        # 项目信息区域
        info_layout = QVBoxLayout()
        info_layout.setSpacing(6)

        # 标题和状态
        title_status_layout = QHBoxLayout()
        title_status_layout.setSpacing(10)
        self.name_label = TitleLabel("...")
        self.status_badge = BodyLabel("未知")
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setFixedSize(72, 26)
        title_status_layout.addWidget(self.name_label)
        title_status_layout.addWidget(self.status_badge)
        title_status_layout.addStretch(1)
        info_layout.addLayout(title_status_layout)

        # 路径
        self.path_label = CaptionLabel("...")
        self.path_label.setStyleSheet("color: #64748b; font-family: Consolas, monospace;")
        info_layout.addWidget(self.path_label)

        # 统计数据行
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(32)

        def create_stat_item(label_text):
            item_layout = QVBoxLayout()
            item_layout.setSpacing(4)
            lbl = CaptionLabel(label_text)
            lbl.setStyleSheet("color: #64748b;")
            val = BodyLabel("...")
            val.setStyleSheet("font-weight: 500;")
            item_layout.addWidget(lbl)
            item_layout.addWidget(val)
            return item_layout, val

        php_layout, self.stat_php_val = create_stat_item("PHP 版本")
        port_layout, self.stat_port_val = create_stat_item("端口")
        dir_layout, self.stat_dir_val = create_stat_item("目录大小")
        log_layout, self.stat_log_val = create_stat_item("日志大小")

        stats_layout.addLayout(php_layout)
        stats_layout.addLayout(port_layout)
        stats_layout.addLayout(dir_layout)
        stats_layout.addLayout(log_layout)
        stats_layout.addStretch(1)

        info_layout.addLayout(stats_layout)
        top_main_layout.addLayout(info_layout, 1)

        # 顶部操作按钮 (停止/重启/编辑/删除)
        top_actions_layout = QHBoxLayout()
        top_actions_layout.setSpacing(8)

        self.toggle_btn = PillPushButton(FIF.PLAY, "启动")
        self.toggle_btn.setMinimumHeight(32)
        self.toggle_btn.setCheckable(False)
        self.restart_btn = PillPushButton(FIF.SYNC, "重启")
        self.restart_btn.setMinimumHeight(32)
        self.restart_btn.setCheckable(False)
        
        self.rename_btn = TransparentToolButton(FIF.EDIT)
        self.rename_btn.setToolTip("项目设置")
        self.rename_btn.setFixedSize(32, 32)
        self.delete_btn = TransparentToolButton(FIF.DELETE)
        self.delete_btn.setToolTip("删除项目")
        self.delete_btn.setFixedSize(32, 32)

        top_actions_layout.addWidget(self.toggle_btn)
        top_actions_layout.addWidget(self.restart_btn)
        top_actions_layout.addWidget(self.rename_btn)
        top_actions_layout.addWidget(self.delete_btn)

        top_main_layout.addLayout(top_actions_layout, 0)
        top_main_layout.setAlignment(top_actions_layout, Qt.AlignmentFlag.AlignTop)

        h_layout.addLayout(top_main_layout)

        # 底部操作栏 (Action bar)
        action_bar_layout = QHBoxLayout()
        action_bar_layout.setSpacing(12)

        self.browser_btn = PillPushButton(FIF.GLOBE, "打开浏览器")
        self.browser_btn.setCheckable(False)
        self.log_btn_header = PillPushButton(FIF.DOCUMENT, "查看日志")
        self.log_btn_header.setCheckable(False)
        self.folder_btn_header = PillPushButton(FIF.FOLDER, "打开目录")
        self.folder_btn_header.setCheckable(False)

        for btn in [self.browser_btn, self.log_btn_header, self.folder_btn_header]:
            btn.setMinimumHeight(32)

        action_bar_layout.addWidget(self.browser_btn)
        action_bar_layout.addWidget(self.log_btn_header)
        action_bar_layout.addWidget(self.folder_btn_header)
        action_bar_layout.addStretch(1)

        h_layout.addLayout(action_bar_layout)
        layout.addWidget(self.header_card)

        # --- 工具与操作卡片 ---
        self.tools_card = CardWidget()
        tools_layout = QVBoxLayout(self.tools_card)
        tools_layout.setContentsMargins(24, 20, 24, 20)
        tools_layout.setSpacing(16)

        tools_header = QHBoxLayout()
        tools_header.addWidget(StrongBodyLabel("工具与操作"))
        tools_header.addStretch()
        tools_layout.addLayout(tools_header)

        tools_content_layout = QVBoxLayout()
        tools_content_layout.setSpacing(16)

        # 工具组
        self.terminal_btn = PillPushButton(FIF.COMMAND_PROMPT, "进入终端")
        self.docker_btn = PillPushButton(FIF.OEM, "进入容器")
        self.config_btn = PillPushButton(FIF.SETTING, "编辑配置")
        self.alias_btn = PillPushButton(FIF.COPY, "复制 alias")
        
        self.composer_install_btn = PillPushButton(FIF.DOWNLOAD, "Composer Install")
        self.composer_update_btn = PillPushButton(FIF.SYNC, "Composer Update")
        self.composer_require_btn = PillPushButton(FIF.ADD, "Composer Require")
        self.install_ext_btn = PillPushButton(FIF.APPLICATION, "安装扩展")
        
        self.xdebug_btn = PillPushButton(FIF.BUG, "Xdebug 配置")
        self.code_log_btn = PillPushButton(FIF.DOCUMENT, "代码日志")
        self.clear_logs_btn = PillPushButton(FIF.DELETE, "清理日志")

        def create_tool_group(title, buttons):
            group_layout = QVBoxLayout()
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(8)
            lbl = CaptionLabel(title)
            lbl.setStyleSheet("color: #64748b; font-weight: 500;")
            
            wrapper = QWidget()
            btn_layout = FlowLayout(wrapper, isTight=True)
            btn_layout.setSpacing(8)
            btn_layout.setContentsMargins(0, 0, 0, 0)
            
            for btn in buttons:
                btn.setMinimumHeight(34)
                btn.setCheckable(False)
                btn_layout.addWidget(btn)
                
            group_layout.addWidget(lbl)
            group_layout.addWidget(wrapper)
            return group_layout

        env_group = create_tool_group("环境", [self.terminal_btn, self.docker_btn, self.config_btn, self.alias_btn])
        deps_group = create_tool_group("依赖管理", [self.composer_install_btn, self.composer_update_btn, self.composer_require_btn, self.install_ext_btn])
        debug_group = create_tool_group("调试与日志", [self.xdebug_btn, self.code_log_btn, self.clear_logs_btn])

        tools_content_layout.addLayout(env_group)
        tools_content_layout.addLayout(deps_group)
        tools_content_layout.addLayout(debug_group)

        tools_layout.addLayout(tools_content_layout)
        layout.addWidget(self.tools_card)

        # --- PHP 配置信息卡片 ---'''

content = content.replace(target_setup_ui, replacement_setup_ui)

# 3. Replace update_project
target_update_project = re.search(r'    def update_project\(self, project: Project, loading: bool = False, animate: bool = False\):.*?        if loading:', content, re.DOTALL).group(0)

replacement_update_project = '''    def update_project(self, project: Project, loading: bool = False, animate: bool = False):
        """更新项目显示

        Args:
            project: 项目对象
            loading: 是否正在加载中
            animate: 是否触发淡入动画
        """
        self.name_label.setText(project.name)
        self.name_label.setStyleSheet(f"color: {get_project_color(project.name)};")

        # 更新头像
        self.avatar_label.setPixmap(make_project_icon(project.name).pixmap(48, 48))

        # 计算目录大小和日志大小
        project_path = Path(project.path)
        total_size = get_dir_size(project_path)
        logs_path = project_path / "logs"
        logs_size = get_dir_size(logs_path) if logs_path.exists() else 0

        self.stat_php_val.setText(project.php_version)
        self.stat_port_val.setText(str(project.port))
        self.stat_dir_val.setText(format_size(total_size))
        self.stat_log_val.setText(format_size(logs_size))
        self.path_label.setText(str(project.path))

        if loading:'''

content = content.replace(target_update_project, replacement_update_project)

with open('ui/main_window.py', 'w') as f:
    f.write(content)

print("Replacement done.")
