"""主窗口"""
import os
import shlex
import subprocess
import threading
import time as _time
import webbrowser
import functools
from pathlib import Path
from typing import Optional, List

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QSystemTrayIcon, QApplication, QGridLayout, QSizePolicy,
    QGraphicsOpacityEffect, QLabel
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QIcon, QAction, QPainter, QColor, QBrush, QPen, QFont, QPixmap, QCursor

from qfluentwidgets import (
    FluentWindow, NavigationItemPosition,
    PushButton, PrimaryPushButton, PillPushButton, TransparentToolButton,
    BodyLabel, StrongBodyLabel, CaptionLabel, TitleLabel, ImageLabel,
    CardWidget, ScrollArea, FlowLayout, HorizontalSeparator,
    FluentIcon as FIF, InfoBar, InfoBarPosition, MessageBox,
    SystemTrayMenu, Action, RoundMenu, IconWidget
)

from core.project import ProjectManager, Project, get_port_usage
from core.docker import DockerManager
from ui.dialogs.change_port_dialog import ChangePortDialog
from ui.dialogs.create_project import CreateProjectDialog
from ui.dialogs.log_viewer import LogViewerDialog
from ui.dialogs.install_ext import InstallExtDialog
from ui.dialogs.settings import SettingsDialog
from core.settings import Settings
from ui.dialogs.config_editor import ConfigEditorDialog
from ui.dialogs.xdebug_dialog import XdebugDialog
from ui.dialogs.php_config_dialog import PhpConfigDialog, EDITABLE_CONFIGS
from ui.dialogs.rename_project_dialog import RenameProjectDialog
from ui.styles import themed_color


_dir_size_cache: dict = {}  # {path: (timestamp, size)}

def get_dir_size(path: Path) -> int:
    """获取目录大小（字节），缓存 60 秒"""
    now = _time.monotonic()
    cached = _dir_size_cache.get(path)
    if cached and now - cached[0] < 60:
        return cached[1]
    total = 0
    try:
        for entry in path.rglob('*'):
            if entry.is_file():
                total += entry.stat().st_size
    except (PermissionError, OSError):
        pass
    _dir_size_cache[path] = (now, total)
    return total


def format_size(size_bytes: int) -> str:
    """格式化大小为人类可读格式"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}" if unit != 'B' else f"{size_bytes}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}PB"


# 项目图标颜色表
PROJECT_COLORS = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b",
                  "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"]


def get_project_color(name: str) -> str:
    """根据项目首字母获取颜色"""
    letter = name[0].upper() if name else "?"
    return PROJECT_COLORS[ord(letter) % len(PROJECT_COLORS)]


def make_project_icon(name: str, is_running: bool = True) -> QIcon:
    """根据项目首字母生成彩色圆形图标"""
    letter = name[0].upper() if name else "?"
    color = get_project_color(name) if is_running else "#8a8a8a"

    # 使用更高分辨率避免模糊
    size = 80
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor(color)))
    painter.drawEllipse(4, 4, size-8, size-8)

    painter.setPen(QPen(QColor("white")))
    font = QFont()
    font.setPixelSize(36)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(0, 0, size, size, Qt.AlignmentFlag.AlignCenter, letter)
    painter.end()

    return QIcon(pixmap)


# 导入 NavigationPushButton 用于自定义导航项
from qfluentwidgets import NavigationPushButton as BaseNavigationPushButton
from qfluentwidgets.common.config import isDarkTheme


class ProjectNavigationItem(BaseNavigationPushButton):
    """自定义项目导航项，使用更大的图标 + 右侧端口和版本"""

    def __init__(self, project, parent=None):
        self.project_name = project.name
        self.project_port = project.port
        self.project_php_version = project.php_version
        self.is_running = project.is_running
        self.project_color = get_project_color(project.name)
        super().__init__(make_project_icon(project.name, self.is_running), project.name, True, parent)

    def set_running_state(self, is_running: bool):
        if self.is_running != is_running:
            self.is_running = is_running
            self._icon = make_project_icon(self.project_name, self.is_running)
            self.update()

    def paintEvent(self, e):
        """重写绘制事件，绘制更大的图标"""
        from PyQt6.QtCore import QRectF

        # 先调用父类绘制背景、指示器和文字
        super().paintEvent(e)

        # 获取 margin（与其他导航项对齐）
        m = self._margins()
        pl = m.left()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # 绘制更大的图标 (24x24 而不是 16x16)
        icon_size = 24
        default_icon_size = 16
        default_icon_left = 11.5 + pl
        default_icon_top = 10

        icon_left = default_icon_left - (icon_size - default_icon_size) / 2
        icon_top = default_icon_top - (icon_size - default_icon_size) / 2
        icon_rect = QRectF(icon_left, icon_top, icon_size, icon_size)

        letter = self.project_name[0].upper() if self.project_name else "?"
        color = QColor(self.project_color if self.is_running else "#8a8a8a")

        # 绘制圆形背景
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(icon_rect)

        # 绘制字母
        painter.setPen(QPen(QColor("white")))
        font = QFont()
        font.setPixelSize(14)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(icon_rect.toRect(), Qt.AlignmentFlag.AlignCenter, letter)

        # 右侧绘制端口和版本（仅在展开时绘制）
        if not self.isCompacted:
            right_margin = 12
            right_x = self.width() - right_margin

            # 端口（右上）
            port_font = QFont()
            port_font.setPixelSize(11)
            port_font.setBold(True)
            painter.setFont(port_font)
            port_color = QColor(themed_color('#475569', '#b0bec5'))
            painter.setPen(QPen(port_color))
            port_text = f":{self.project_port}"
            port_w = painter.fontMetrics().horizontalAdvance(port_text)
            painter.drawText(int(right_x - port_w), 16, port_text)

            # PHP 版本（右下）
            ver_font = QFont()
            ver_font.setPixelSize(10)
            painter.setFont(ver_font)
            ver_color = QColor(themed_color('#94a3b8', '#64748b'))
            painter.setPen(QPen(ver_color))
            ver_text = f"PHP {self.project_php_version}"
            ver_w = painter.fontMetrics().horizontalAdvance(ver_text)
            painter.drawText(int(right_x - ver_w), 30, ver_text)

        painter.end()


class ToolCard(QWidget):
    clicked = pyqtSignal()
    def __init__(self, icon: FIF, title: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 12, 0)
        layout.setSpacing(6)

        self.icon_widget = IconWidget(icon)
        self.icon_widget.setFixedSize(18, 18)

        self.label = CaptionLabel(title)
        self.label.setStyleSheet(f"color: {themed_color('#475569', '#b0bec5')}; font-weight: 500;")

        layout.addWidget(self.icon_widget)
        layout.addWidget(self.label)

    def _update_style(self):
        hover_bg = themed_color('rgba(100, 116, 139, 0.1)', 'rgba(180, 200, 220, 0.1)')
        self.setStyleSheet(f"""
            ToolCard {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
            }}
            ToolCard:hover {{
                background-color: {hover_bg};
            }}
        """)

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        opacity = 1.0 if enabled else 0.4
        self.icon_widget.setEnabled(enabled)
        self.label.setStyleSheet(
            f"color: {themed_color('#475569', '#b0bec5')}; font-weight: 500;"
            if enabled else
            f"color: {themed_color('#c0c0c0', '#555555')}; font-weight: 500;"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ForbiddenCursor)

    def mousePressEvent(self, e):
        if not self.isEnabled():
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            press_bg = themed_color('rgba(100, 116, 139, 0.15)', 'rgba(180, 200, 220, 0.15)')
            self.setStyleSheet(f"""
                ToolCard {{
                    background-color: {press_bg};
                    border: 1px solid transparent;
                    border-radius: 6px;
                }}
            """)

    def mouseReleaseEvent(self, e):
        if not self.isEnabled():
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self._update_style()


class ModernDashboardWidget(ScrollArea):
    """现代项目仪表盘"""

    # PHP 配置点击信号
    config_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setStyleSheet(
            "ScrollArea { background-color: transparent; border: none; }"
            "QWidget#container { background-color: transparent; }"
        )
        self.container = QWidget()
        self.container.setObjectName("container")
        self.setup_ui()
        self.setWidget(self.container)

        # 设置透明度效果用于淡入动画
        self.opacity_effect = QGraphicsOpacityEffect(self.container)
        self.container.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(1.0)

        # 淡入动画
        self.fade_animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_animation.setDuration(200)
        self.fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def fade_in(self):
        """执行淡入动画"""
        self.opacity_effect.setOpacity(0.0)
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.start()

    def setup_ui(self):
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
        self.status_badge.setFixedSize(80, 28)
        title_status_layout.addWidget(self.name_label)
        title_status_layout.addWidget(self.status_badge)
        title_status_layout.addStretch(1)
        info_layout.addLayout(title_status_layout)

        # 路径（点击复制）
        self.path_label = CaptionLabel("...")
        self.path_label.setStyleSheet(f"color: {themed_color('#64748b', '#8b95a5')}; font-family: Consolas, monospace;")
        self.path_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.path_label.setToolTip("点击复制路径")
        self.path_label.mousePressEvent = self._copy_path
        info_layout.addWidget(self.path_label)

        # 统计信息内联文字
        self.stats_line = CaptionLabel("...")
        self.stats_line.setStyleSheet(f"color: {themed_color('#64748b', '#8b95a5')};")
        info_layout.addWidget(self.stats_line)
        top_main_layout.addLayout(info_layout, 1)

        # 顶部操作按钮 (停止/重启/编辑/删除)
        top_actions_layout = QHBoxLayout()
        top_actions_layout.setSpacing(8)

        self.toggle_btn = PrimaryPushButton(FIF.PLAY, "启动")
        self.toggle_btn.setMinimumHeight(32)
        self.toggle_btn.setCheckable(False)
        self.restart_btn = PushButton(FIF.SYNC, "重启")
        self.restart_btn.setMinimumHeight(32)
        self.restart_btn.setCheckable(False)
        
        # 更多操作按钮 (重命名、删除被收纳至此)
        self.more_btn = TransparentToolButton(FIF.MORE)
        self.more_btn.setFixedSize(32, 32)

        self.more_menu = RoundMenu(parent=self.more_btn)
        self.rename_action = Action(FIF.EDIT, "项目设置")
        self.change_port_action = Action(FIF.GLOBE, "修改端口")
        self.delete_action = Action(FIF.DELETE, "删除项目")
        self.more_menu.addAction(self.rename_action)
        self.more_menu.addAction(self.change_port_action)
        self.more_menu.addAction(self.delete_action)
        self.more_btn.clicked.connect(
            lambda: self.more_menu.exec(self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft()))
        )

        top_actions_layout.addWidget(self.toggle_btn)
        top_actions_layout.addWidget(self.restart_btn)
        top_actions_layout.addWidget(self.more_btn)

        top_main_layout.addLayout(top_actions_layout, 0)
        top_main_layout.setAlignment(top_actions_layout, Qt.AlignmentFlag.AlignTop)

        h_layout.addLayout(top_main_layout)

        # 底部操作栏 (Action bar)
        action_bar_layout = QHBoxLayout()
        action_bar_layout.setSpacing(12)

        self.log_btn_header = PrimaryPushButton(FIF.DOCUMENT, "查看日志")
        self.log_btn_header.setCheckable(False)
        self.folder_btn_header = PushButton(FIF.FOLDER, "打开目录")
        self.folder_btn_header.setCheckable(False)
        self.browser_btn = PushButton(FIF.GLOBE, "打开浏览器")
        self.browser_btn.setCheckable(False)

        for btn in [self.log_btn_header, self.folder_btn_header, self.browser_btn]:
            btn.setMinimumHeight(32)

        action_bar_layout.addWidget(self.log_btn_header)
        action_bar_layout.addWidget(self.folder_btn_header)
        action_bar_layout.addWidget(self.browser_btn)
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
        self.terminal_btn = ToolCard(FIF.COMMAND_PROMPT, "进入终端")
        self.docker_btn = ToolCard(FIF.CODE, "进入容器")
        self.config_btn = ToolCard(FIF.SETTING, "编辑配置")
        self.alias_btn = ToolCard(FIF.COPY, "复制 alias")
        
        self.composer_install_btn = ToolCard(FIF.DOWNLOAD, "安装依赖")
        self.composer_update_btn = ToolCard(FIF.SYNC, "更新依赖")
        self.composer_require_btn = ToolCard(FIF.ADD, "添加依赖")
        self.install_ext_btn = ToolCard(FIF.APPLICATION, "安装扩展")
        
        self.xdebug_btn = ToolCard(FIF.DEVELOPER_TOOLS, "Xdebug")
        self.code_log_btn = ToolCard(FIF.DOCUMENT, "Runtime 日志")
        self.clear_logs_btn = ToolCard(FIF.DELETE, "清理日志")

        # 需要容器运行才可用的按钮
        self._running_required_btns = [
            self.docker_btn, self.install_ext_btn, self.xdebug_btn,
            self.clear_logs_btn, self.composer_install_btn,
            self.composer_update_btn, self.composer_require_btn,
        ]

        def create_tool_group(title, buttons):
            group_layout = QVBoxLayout()
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(8)
            lbl = CaptionLabel(title)
            lbl.setStyleSheet(f"color: {themed_color('#64748b', '#8b95a5')}; font-weight: 500;")
            
            wrapper = QWidget()
            btn_layout = FlowLayout(wrapper, isTight=True)
            btn_layout.setSpacing(12)
            btn_layout.setContentsMargins(0, 0, 0, 0)
            
            for btn in buttons:
                btn_layout.addWidget(btn)
                
            group_layout.addWidget(lbl)
            group_layout.addWidget(wrapper)
            return group_layout

        env_group = create_tool_group("环境", [self.terminal_btn, self.docker_btn, self.config_btn, self.alias_btn])
        deps_group = create_tool_group("依赖管理", [self.composer_install_btn, self.composer_update_btn, self.composer_require_btn, self.install_ext_btn])
        debug_group = create_tool_group("调试与日志", [self.xdebug_btn, self.code_log_btn, self.clear_logs_btn])

        tools_content_layout.addLayout(env_group)
        tools_content_layout.addWidget(HorizontalSeparator())
        tools_content_layout.addLayout(deps_group)
        tools_content_layout.addWidget(HorizontalSeparator())
        tools_content_layout.addLayout(debug_group)

        tools_layout.addLayout(tools_content_layout)
        layout.addWidget(self.tools_card)

        # --- PHP 配置信息卡片 ---
        self.config_card = CardWidget()
        config_layout = QVBoxLayout(self.config_card)
        config_layout.setContentsMargins(24, 16, 24, 16)
        config_layout.setSpacing(12)

        # 标题行
        config_header = QHBoxLayout()
        config_header.addWidget(StrongBodyLabel("PHP 配置信息"))
        self.config_refresh_btn = TransparentToolButton(FIF.SYNC)
        self.config_refresh_btn.setToolTip("刷新配置")
        self.config_refresh_btn.setFixedSize(28, 28)
        config_header.addStretch()
        config_header.addWidget(self.config_refresh_btn)
        config_layout.addLayout(config_header)

        # 配置网格（2 列）
        self.config_grid = QGridLayout()
        self.config_grid.setSpacing(16)
        self.config_grid.setColumnStretch(1, 1)
        self.config_grid.setColumnStretch(3, 1)

        # 配置项标签（初始化为空，等待更新）
        self.config_labels = {}
        self._config_current_values = {}  # 存储当前配置值
        config_items = [
            ("memory_limit", "内存限制"),
            ("max_execution_time", "最大执行时间"),
            ("max_input_time", "最大输入时间"),
            ("upload_max_filesize", "上传文件大小"),
            ("post_max_size", "POST 大小"),
            ("max_file_uploads", "最大上传数量"),
            ("display_errors", "显示错误"),
            ("error_reporting", "错误报告"),
            ("date.timezone", "时区"),
        ]

        for i, (key, label) in enumerate(config_items):
            row = i // 2
            col = (i % 2) * 2
            name_label = CaptionLabel(f"{label}:")
            name_label.setStyleSheet(f"color: {themed_color('#64748b', '#8b95a5')};")
            name_label.setToolTip(key)
            value_label = CaptionLabel("--")

            if key in EDITABLE_CONFIGS:
                value_container = QWidget()
                val_layout = QHBoxLayout(value_container)
                val_layout.setContentsMargins(0, 0, 0, 0)
                val_layout.setSpacing(6)

                value_label.setStyleSheet("font-weight: bold;")
                edit_icon = IconWidget(FIF.EDIT)
                edit_icon.setFixedSize(14, 14)

                op = QGraphicsOpacityEffect(edit_icon)
                op.setOpacity(0.5)
                edit_icon.setGraphicsEffect(op)

                val_layout.addWidget(value_label)
                val_layout.addWidget(edit_icon)
                val_layout.addStretch(1)

                value_container.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                value_container.mousePressEvent = self._create_config_click_handler(key)

                grid_widget = value_container
            else:
                value_label.setStyleSheet("font-weight: bold;")
                grid_widget = value_label

            self.config_grid.addWidget(name_label, row, col)
            self.config_grid.addWidget(grid_widget, row, col + 1)
            self.config_labels[key] = value_label

        config_layout.addLayout(self.config_grid)

        # Xdebug / OPCache 状态行
        status_row = QHBoxLayout()
        status_row.setSpacing(24)
        for key, label_text in [("xdebug_status", "Xdebug"), ("opcache_status", "OPCache")]:
            name_lbl = CaptionLabel(f"{label_text}:")
            name_lbl.setStyleSheet(f"color: {themed_color('#64748b', '#8b95a5')};")
            val_lbl = CaptionLabel("--")
            val_lbl.setStyleSheet("font-weight: bold;")
            self.config_labels[key] = val_lbl
            status_row.addWidget(name_lbl)
            status_row.addWidget(val_lbl)
        status_row.addStretch(1)
        config_layout.addLayout(status_row)

        # 已安装扩展
        ext_header = QHBoxLayout()
        ext_header.addWidget(BodyLabel("已安装扩展"))
        self.ext_count_label = CaptionLabel("0 个")
        self.ext_count_label.setStyleSheet(f"color: {themed_color('#64748b', '#8b95a5')};")
        ext_header.addStretch()
        ext_header.addWidget(self.ext_count_label)
        config_layout.addLayout(ext_header)

        # 扩展标签容器
        self.ext_container = QWidget()
        self.ext_layout = FlowLayout(self.ext_container, isTight=True)
        self.ext_layout.setSpacing(6)
        self.ext_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.addWidget(self.ext_container)

        layout.addWidget(self.config_card)

        layout.addStretch(1)

    def _copy_path(self, event):
        """点击复制项目路径"""
        if event.button() == Qt.MouseButton.LeftButton:
            path = self.path_label.text()
            if path and path != "...":
                QApplication.clipboard().setText(path)
                InfoBar.success(
                    title="已复制",
                    content=path,
                    orient=Qt.Orientation.Horizontal,
                    duration=2000,
                    parent=self
                )

    def _create_config_click_handler(self, config_key: str):
        """创建配置项点击处理器"""
        def handler(event):
            if event.button() == Qt.MouseButton.LeftButton:
                self.config_clicked.emit(config_key)
        return handler

    def update_project(self, project: Project, loading: bool = False, animate: bool = False):
        """更新项目显示

        Args:
            project: 项目对象
            loading: 是否正在加载中
            animate: 是否触发淡入动画
        """
        self.name_label.setText(project.name)
        
        # 正在加载时颜色不变，不运行时变为灰色
        is_running = loading or project.is_running
        display_color = get_project_color(project.name) if is_running else "#8a8a8a"
        self.name_label.setStyleSheet(f"color: {display_color};")

        # 更新头像
        self.avatar_label.setPixmap(make_project_icon(project.name, is_running).pixmap(48, 48))

        # 计算目录大小和日志大小
        project_path = Path(project.path)
        total_size = get_dir_size(project_path)
        logs_path = project_path / "logs"
        logs_size = get_dir_size(logs_path) if logs_path.exists() else 0

        self.stats_line.setText(
            f"PHP {project.php_version}  ·  :{project.port}  ·  {format_size(total_size)}  ·  日志 {format_size(logs_size)}"
        )
        self.stats_line.setStyleSheet(f"color: {themed_color('#64748b', '#8b95a5')};")
        self.path_label.setText(str(project.path))

        if loading:
            self.status_badge.setText("刷新中...")
            self.status_badge.setStyleSheet(
                "background-color: #f59e0b; color: white; border-radius: 14px; font-weight: bold;"
            )
            self.toggle_btn.setEnabled(False)
        elif project.is_running:
            self.status_badge.setText("运行中")
            self.status_badge.setStyleSheet(
                "background-color: #22c55e; color: white; border-radius: 14px; font-weight: bold;"
            )
            self.toggle_btn.setText("停止")
            self.toggle_btn.setIcon(FIF.PAUSE)
            self.toggle_btn.setEnabled(True)
        else:
            self.status_badge.setText("已停止")
            self.status_badge.setStyleSheet(
                "background-color: #94a3b8; color: white; border-radius: 14px; font-weight: bold;"
            )
            self.toggle_btn.setText("启动")
            self.toggle_btn.setIcon(FIF.PLAY)
            self.toggle_btn.setEnabled(True)

        # 项目未运行时，配置卡片显示提示，并禁用需要容器的按钮
        if not project.is_running:
            self._clear_php_info()
        for btn in self._running_required_btns:
            btn.setEnabled(project.is_running)
            btn.setToolTip("" if project.is_running else "需要先启动项目")

        # 触发淡入动画（仅在切换项目时）
        if animate:
            self.fade_in()

    def _clear_php_info(self):
        """清空 PHP 配置显示"""
        self._config_current_values = {}
        for key, label in self.config_labels.items():
            label.setText("--")
            # 可编辑项恢复样式
            if key in EDITABLE_CONFIGS:
                label.setStyleSheet("font-weight: bold;")
        self.ext_count_label.setText("0 个")
        # 清空扩展标签
        while self.ext_layout.count():
            item = self.ext_layout.takeAt(0)
            if hasattr(item, 'widget') and callable(item.widget):
                widget = item.widget()
                if widget:
                    widget.deleteLater()
            elif hasattr(item, 'deleteLater'):
                item.deleteLater()

    def update_php_info(self, info: dict):
        """更新 PHP 配置信息显示"""
        if not info:
            self._clear_php_info()
            return

        # 存储当前配置值
        self._config_current_values = info.copy()

        # 更新配置项
        editable_style = "font-weight: bold;"
        for key in ["memory_limit", "max_execution_time", "max_input_time",
                     "upload_max_filesize", "post_max_size", "max_file_uploads",
                     "display_errors", "error_reporting", "date.timezone"]:
            self.config_labels[key].setText(info.get(key, "--"))
            self.config_labels[key].setStyleSheet(editable_style)

        # Xdebug 状态
        xdebug_enabled = info.get("xdebug_enabled", False)
        self.config_labels["xdebug_status"].setText("启用" if xdebug_enabled else "禁用")
        self.config_labels["xdebug_status"].setStyleSheet(
            "color: #22c55e; font-weight: bold;" if xdebug_enabled else "color: #94a3b8; font-weight: bold;"
        )

        # OPCache 状态
        opcache_enabled = info.get("opcache_enabled", False)
        self.config_labels["opcache_status"].setText("启用" if opcache_enabled else "禁用")
        self.config_labels["opcache_status"].setStyleSheet(
            "color: #22c55e; font-weight: bold;" if opcache_enabled else "color: #94a3b8; font-weight: bold;"
        )

        # 清空旧扩展标签
        self.ext_layout.takeAllWidgets()

        # 添加扩展标签
        extensions = info.get("extensions", [])
        self.ext_count_label.setText(f"{len(extensions)} 个")

        # 常用扩展高亮
        important_exts = {
            "pdo", "pdo_mysql", "mysqli", "mysqlnd", "redis", "memcached",
            "gd", "imagick", "zip", "curl", "mbstring", "json", "xml",
            "opcache", "xdebug", "intl", "bcmath", "exif", "fileinfo",
            "openssl", "tokenizer", "ctype", "session", "filter", "hash"
        }

        for ext in sorted(extensions):
            if not ext or ext.startswith("["):
                continue
            label = CaptionLabel(ext)
            label.setFixedHeight(22)
            if ext.lower() in important_exts or ext.lower().replace("_", "") in important_exts:
                label.setStyleSheet(
                    f"background-color: {themed_color('#dbeafe', 'rgba(59,130,246,0.15)')}; "
                    f"color: {themed_color('#1d4ed8', '#60a5fa')}; "
                    "border-radius: 4px; padding: 2px 8px; font-weight: bold;"
                )
            else:
                label.setStyleSheet(
                    f"background-color: {themed_color('#f1f5f9', 'rgba(148,163,184,0.12)')}; "
                    f"color: {themed_color('#475569', '#94a3b8')}; "
                    "border-radius: 4px; padding: 2px 8px;"
                )
            self.ext_layout.addWidget(label)

        # 延迟触发布局重新计算，确保 widget 完成渲染
        QTimer.singleShot(0, lambda: self.ext_layout._doLayout(self.ext_container.rect(), True))


class ProjectDashboardPage(QWidget):
    """项目仪表盘页面（右侧内容区）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ProjectDashboardPage")
        self.current_project: Optional[Project] = None
        self.project_manager = ProjectManager()
        self.projects: List[Project] = []

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 空状态提示容器
        self.empty_container = QWidget()
        empty_layout = QVBoxLayout(self.empty_container)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(16)
        
        # 使用图标替代插画
        empty_icon = IconWidget(FIF.IOT)
        empty_icon.setFixedSize(72, 72)
        
        # 淡色装饰
        op = QGraphicsOpacityEffect(empty_icon)
        op.setOpacity(0.3)
        empty_icon.setGraphicsEffect(op)
        
        empty_text = TitleLabel("尚未选择项目")
        empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_text.setStyleSheet(f"color: {themed_color('#64748b', '#8b95a5')}; font-weight: bold;")

        empty_desc = BodyLabel("← 请从左侧边栏选择环境加载详细面板")
        empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_desc.setStyleSheet(f"color: {themed_color('#94a3b8', '#64748b')};")
        
        empty_layout.addStretch(1)
        empty_layout.addWidget(empty_icon, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addSpacing(8)
        empty_layout.addWidget(empty_text, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addWidget(empty_desc, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(1)
        
        layout.addWidget(self.empty_container, 1)

        # 仪表盘
        self.dashboard = ModernDashboardWidget()
        # 连接按钮
        self.dashboard.toggle_btn.clicked.connect(self.toggle_running)
        self.dashboard.restart_btn.clicked.connect(self.restart_project)
        self.dashboard.config_btn.clicked.connect(self.edit_config)
        self.dashboard.install_ext_btn.clicked.connect(self.install_extension)
        self.dashboard.browser_btn.clicked.connect(self.open_browser)
        self.dashboard.log_btn_header.clicked.connect(self.view_logs)
        self.dashboard.terminal_btn.clicked.connect(self.open_terminal)
        self.dashboard.docker_btn.clicked.connect(self.open_docker_terminal)
        self.dashboard.delete_action.triggered.connect(self.delete_project)
        self.dashboard.folder_btn_header.clicked.connect(self.open_folder)
        self.dashboard.alias_btn.clicked.connect(self.copy_alias)
        self.dashboard.xdebug_btn.clicked.connect(self.configure_xdebug)
        self.dashboard.config_refresh_btn.clicked.connect(self._refresh_php_info)
        self.dashboard.config_clicked.connect(self._on_php_config_clicked)
        self.dashboard.composer_install_btn.clicked.connect(self.composer_install)
        self.dashboard.composer_update_btn.clicked.connect(self.composer_update)
        self.dashboard.composer_require_btn.clicked.connect(self.composer_require)
        self.dashboard.clear_logs_btn.clicked.connect(self.clear_logs)
        self.dashboard.code_log_btn.clicked.connect(self.open_code_log_terminal)
        self.dashboard.rename_action.triggered.connect(self.rename_project)
        self.dashboard.change_port_action.triggered.connect(self.change_port)
        layout.addWidget(self.dashboard, 1)

        self.show_project_view(False)

    def show_project_view(self, show: bool):
        self.dashboard.setVisible(show)
        self.empty_container.setVisible(not show)

    def show_project(self, project: Project, loading: bool = False):
        """显示项目

        Args:
            project: 项目对象
            loading: 是否正在加载中
        """
        self.current_project = project
        self.dashboard.update_project(project, loading=loading, animate=True)
        self.show_project_view(True)

        # 滚动到顶部
        self.dashboard.verticalScrollBar().setValue(0)

        # 如果项目正在运行，异步获取 PHP 配置
        if project.is_running and not loading:
            QTimer.singleShot(100, self._refresh_php_info)

    def refresh_status(self):
        if self.current_project and self.projects:
            for p in self.projects:
                if p.name == self.current_project.name:
                    self.current_project = p
                    self.dashboard.update_project(p)
                    # 通知主窗口刷新对应的侧边栏图标状态
                    main_win = self.window()
                    if hasattr(main_win, 'update_sidebar_item_state'):
                        main_win.update_sidebar_item_state(p.name, p.is_running)
                    # 项目运行中时刷新 PHP 配置
                    if p.is_running:
                        QTimer.singleShot(100, self._refresh_php_info)
                    break

    # ---- 项目操作 ----
    def toggle_running(self):
        """启动或停止项目"""
        if not self.current_project:
            return
        if self.current_project.is_running:
            self.stop_project()
        else:
            self.start_project()

    def start_project(self):
        if not self.current_project:
            return

        # 端口冲突检测
        try:
            port = int(self.current_project.port)
        except ValueError:
            port = 8080

        # 异步检查端口并启动
        project = self.current_project
        threading.Thread(
            target=self._async_check_port_and_start,
            args=(project.path, project.name, port),
            daemon=True
        ).start()

    def _async_check_port_and_start(self, path: str, name: str, port: int):
        """异步检查端口并启动"""
        # 检查端口是否被占用
        usage = get_port_usage(port, name)
        if usage:
            QTimer.singleShot(0, functools.partial(
                self._notify, "端口冲突", f"端口 {port} 已被 {usage} 占用", "error"
            ))
            return

        # 启动服务
        result = DockerManager(path).up()
        QTimer.singleShot(0, functools.partial(self._on_docker_operation_result, result, name, "up"))

    # 操作名 -> (成功标题, 成功动词, 失败标题)
    _OP_LABELS = {
        "up":      ("服务启动", "已启动", "启动失败"),
        "stop":    ("服务停止", "已停止", "停止失败"),
        "restart": ("服务重启", "已重启", "重启失败"),
    }

    def _async_docker_operation(self, path: str, name: str, operation: str):
        """异步执行 docker 操作（up/stop/restart）"""
        result = getattr(DockerManager(path), operation)()
        QTimer.singleShot(0, functools.partial(
            self._on_docker_operation_result, result, name, operation))

    def _on_docker_operation_result(self, result, name: str, operation: str):
        """docker 操作结果回调"""
        ok_title, ok_verb, fail_title = self._OP_LABELS[operation]
        if result.success:
            self._notify(ok_title, f"{name} {ok_verb}", "success")
            QTimer.singleShot(500, self._reload_current)
        else:
            self._notify(fail_title, str(result.error), "error")

    def stop_project(self):
        if not self.current_project:
            return
        project = self.current_project
        threading.Thread(
            target=self._async_docker_operation,
            args=(project.path, project.name, "stop"),
            daemon=True
        ).start()

    def restart_project(self):
        """重启项目（restart 不需要检查端口，因为只是重启容器内的进程）"""
        if not self.current_project:
            return
        project = self.current_project
        threading.Thread(
            target=self._async_docker_operation,
            args=(project.path, project.name, "restart"),
            daemon=True
        ).start()

    def _reload_current(self):
        """异步刷新当前项目状态"""
        threading.Thread(
            target=self._async_reload_current,
            daemon=True
        ).start()

    def _async_reload_current(self):
        """异步获取项目列表并刷新"""
        projects = self.project_manager.get_all_projects()
        QTimer.singleShot(0, functools.partial(self._on_reload_current, projects))

    def _on_reload_current(self, projects: list):
        """刷新完成回调"""
        self.projects = projects
        self.refresh_status()

    def view_logs(self):
        if not self.current_project:
            return
        LogViewerDialog(self.current_project.path, self.current_project.name, self).show()

    def open_terminal(self):
        if not self.current_project:
            return
        p = str(self.current_project.path)

        # 获取用户默认终端
        terminal = os.environ.get("TERMINAL") or "x-terminal-emulator"

        self._launch_terminal([
            [terminal, "-e", "sh", "-c", f"cd {shlex.quote(p)} && exec $SHELL"],
            ["deepin-terminal", "--work-directory", p],
            ["kitty", "--directory", p],
            ["alacritty", "--working-directory", p],
            ["gnome-terminal", "--working-directory", p],
            ["konsole", "--workdir", p],
            ["xfce4-terminal", "--working-directory", p],
        ])

    def open_docker_terminal(self):
        if not self.current_project:
            return
        if not self.current_project.is_running:
            InfoBar.warning(
                title="提示",
                content="项目未运行，请先启动项目",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            return
        p = str(self.current_project.path)
        # 使用 zsh 进入容器
        cmd = f"cd {shlex.quote(p)} && docker compose exec php zsh"
        self._launch_terminal([
            ["deepin-terminal", "-C", cmd],
            ["kitty", "--directory", p, "docker", "compose", "exec", "php", "zsh"],
            ["alacritty", "--working-directory", p, "-e", "docker", "compose", "exec", "php", "zsh"],
            ["gnome-terminal", "--working-directory", p, "--", "docker", "compose", "exec", "php", "zsh"],
            ["konsole", "--workdir", p, "-e", "docker", "compose", "exec", "php", "zsh"],
            ["xfce4-terminal", "--working-directory", p, "-e", "docker compose exec php zsh"],
            ["xterm", "-e", "sh", "-c", cmd],
        ])

    def _launch_terminal(self, cmds):
        """启动终端，避免 PyInstaller 打包后的库冲突"""
        for cmd in cmds:
            try:
                # 清除 LD_LIBRARY_PATH 避免与系统库冲突
                env = os.environ.copy()
                env.pop('LD_LIBRARY_PATH', None)
                env.pop('XDG_DATA_DIRS', None)
                subprocess.Popen(cmd, env=env)
                return
            except FileNotFoundError:
                continue
        InfoBar.error(
            title="错误",
            content="未找到可用的终端模拟器",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self
        )

    def delete_project(self):
        if not self.current_project:
            return
        w = MessageBox(
            "确认删除",
            f"确定要删除项目 '{self.current_project.name}' 吗？\n\n这将删除所有容器和数据卷！",
            self.window()
        )
        if w.exec():
            if self.project_manager.delete_project(self.current_project):
                self.current_project = None
                self.show_project_view(False)
                self._notify("项目删除", "项目已删除")
                # 通知父级刷新列表
                parent = self.parent()
                while parent and not isinstance(parent, MainWindow):
                    parent = parent.parent()
                if parent:
                    parent.load_projects()
            else:
                InfoBar.error(
                    title="删除失败",
                    content="无法删除项目文件夹或容器",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=self
                )

    def rename_project(self):
        """打开项目设置对话框"""
        if not self.current_project:
            return

        dialog = RenameProjectDialog(self.current_project, self)
        dialog.project_renamed.connect(self._on_project_renamed)
        dialog.settings_changed.connect(self._reload_current)
        dialog.exec()

    def _on_project_renamed(self, old_name: str, new_name: str):
        """项目重命名成功回调"""
        # 通知父级刷新列表
        parent = self.parent()
        while parent and not isinstance(parent, MainWindow):
            parent = parent.parent()
        if parent:
            parent.load_projects(select_project=new_name)

    def change_port(self):
        """修改项目端口"""
        if not self.current_project:
            return

        dialog = ChangePortDialog(self.current_project, self)
        dialog.port_changed.connect(self._on_port_changed)
        dialog.exec()

    def _on_port_changed(self, new_port: int):
        """端口修改成功回调"""
        # 刷新当前项目显示
        self._reload_current()

    def open_browser(self):
        if not self.current_project:
            return
        url = f"http://localhost:{self.current_project.port}"
        try:
            # 清除库路径避免冲突
            env = os.environ.copy()
            env.pop('LD_LIBRARY_PATH', None)
            subprocess.Popen(["xdg-open", url], env=env)
        except FileNotFoundError:
            # 回退到 webbrowser 模块
            webbrowser.open(url)

    def open_folder(self):
        if not self.current_project:
            return
        try:
            env = os.environ.copy()
            env.pop('LD_LIBRARY_PATH', None)
            subprocess.Popen(["xdg-open", str(self.current_project.path)], env=env)
        except Exception as e:
            InfoBar.error(
                title="错误",
                content=f"无法打开目录: {e}",
                parent=self
            )

    def copy_alias(self):
        if not self.current_project:
            return
        name, path = self.current_project.name, self.current_project.path
        aliases = (
            f"# PHP 项目: {name}\n"
            f"alias {name}='cd {path} && docker compose'\n"
            f"alias {name}-php='cd {path} && docker compose exec php php'\n"
            f"alias {name}-composer='cd {path} && docker compose exec php composer'\n"
            f"alias {name}-zsh='cd {path} && docker compose exec php zsh'"
        )
        QApplication.clipboard().setText(aliases)
        InfoBar.success(
            title="复制成功",
            content="Alias 命令已复制到剪贴板。可用于终端快速操作。",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self
        )

    def clear_logs(self):
        """清理项目日志"""
        if not self.current_project:
            return

        # 检查项目是否在运行
        if not self.current_project.is_running:
            InfoBar.warning(
                title="提示",
                content="请先启动项目后再清理日志",
                orient=Qt.Orientation.Horizontal,
                parent=self
            )
            return

        logs_path = Path(self.current_project.path) / "logs"
        if not logs_path.exists():
            InfoBar.warning(
                title="提示",
                content="日志目录不存在",
                orient=Qt.Orientation.Horizontal,
                parent=self
            )
            return

        # 计算日志总大小
        total_size = get_dir_size(logs_path)
        size_str = format_size(total_size)

        # 确认对话框
        w = MessageBox(
            "确认清理",
            f"确定要清空日志文件吗？\n\n当前日志大小: {size_str}\n\n此操作不可撤销。",
            self
        )
        if not w.exec():
            return

        project_path = str(self.current_project.path)

        try:
            # 通过 docker exec 在容器内清空日志
            # 清空 nginx 日志
            subprocess.run(
                ["docker", "compose", "exec", "-T", "nginx", "sh", "-c",
                 "for f in /var/log/nginx/*.log; do echo -n > \"$f\" 2>/dev/null; done"],
                cwd=project_path,
                capture_output=True,
                timeout=30
            )
            # 清空 php-fpm 日志
            subprocess.run(
                ["docker", "compose", "exec", "-T", "php", "sh", "-c",
                 "for f in /var/log/php-fpm/*.log; do echo -n > \"$f\" 2>/dev/null; done"],
                cwd=project_path,
                capture_output=True,
                timeout=30
            )

            InfoBar.success(
                title="清理完成",
                content=f"已清空日志文件，释放 {size_str}",
                orient=Qt.Orientation.Horizontal,
                parent=self
            )
            self._reload_current()
        except Exception as e:
            InfoBar.error(
                title="清理失败",
                content=str(e),
                orient=Qt.Orientation.Horizontal,
                parent=self
            )

    def open_code_log_terminal(self):
        """打开代码日志终端（tail -f src/runtime/*.log）"""
        if not self.current_project:
            return

        runtime_path = Path(self.current_project.path) / "src" / "runtime"
        if not runtime_path.exists():
            InfoBar.warning(
                title="提示",
                content="runtime 目录不存在",
                orient=Qt.Orientation.Horizontal,
                parent=self
            )
            return

        p = str(runtime_path)
        cmd = f"cd '{p}' && find . -type f -name '*.log' -exec tail -F {{}} +"
        terminal = os.environ.get("TERMINAL") or "x-terminal-emulator"

        self._launch_terminal([
            [terminal, "-e", "sh", "-c", cmd],
            ["deepin-terminal", "-C", cmd],
            ["kitty", "--directory", p, "sh", "-c", cmd],
            ["alacritty", "--working-directory", p, "-e", "sh", "-c", cmd],
            ["gnome-terminal", "--working-directory", p, "--", "sh", "-c", cmd],
            ["konsole", "--workdir", p, "-e", "sh", "-c", cmd],
            ["xfce4-terminal", "--working-directory", p, "-e", cmd],
            ["xterm", "-e", "sh", "-c", cmd],
        ])

    def edit_config(self):
        if not self.current_project:
            return
        ConfigEditorDialog(self.current_project.path, self.current_project.name, self).exec()

    def configure_xdebug(self):
        if not self.current_project:
            return
        if not self.current_project.is_running:
            InfoBar.warning(
                title="提示",
                content="项目未运行，请先启动项目",
                orient=Qt.Orientation.Horizontal,
                parent=self
            )
            return
        XdebugDialog(self.current_project.path, self.current_project.name, self).exec()

    def install_extension(self):
        if not self.current_project:
            return
        InstallExtDialog(
            self.current_project.path,
            self.current_project.name,
            self
        ).exec()

    def _refresh_php_info(self):
        """异步刷新 PHP 配置信息"""
        if not self.current_project or not self.current_project.is_running:
            self.dashboard._clear_php_info()
            return

        # 显示加载状态
        for key, label in self.dashboard.config_labels.items():
            label.setText("加载中...")
        self.dashboard.ext_count_label.setText("加载中...")

        # 异步获取 PHP 信息
        project_path = str(self.current_project.path)
        threading.Thread(
            target=self._async_get_php_info,
            args=(project_path,),
            daemon=True
        ).start()

    def _async_get_php_info(self, project_path: str):
        """异步获取 PHP 配置信息"""
        docker = DockerManager(project_path)
        info = docker.get_php_info()
        QTimer.singleShot(0, functools.partial(self._on_php_info_loaded, info))

    def _on_php_info_loaded(self, info: dict):
        """PHP 信息加载完成回调"""
        self.dashboard.update_php_info(info)

    def _on_php_config_clicked(self, config_key: str):
        """PHP 配置项点击处理"""
        if not self.current_project:
            return
        if not self.current_project.is_running:
            InfoBar.warning(
                title="提示",
                content="项目未运行，请先启动项目",
                orient=Qt.Orientation.Horizontal,
                parent=self
            )
            return

        # 获取当前配置值
        current_config = self.dashboard._config_current_values.copy()
        if not current_config:
            # 如果没有缓存，重新获取
            docker = DockerManager(self.current_project.path)
            current_config = docker.get_php_info()

        # 打开配置编辑对话框
        dialog = PhpConfigDialog(
            self.current_project.path,
            self.current_project.name,
            current_config,
            self
        )
        if dialog.exec():
            # 对话框保存成功后刷新配置显示
            QTimer.singleShot(500, self._refresh_php_info)

    def _run_composer_command(self, command: str, package: str = ""):
        """在终端中执行 Composer 命令"""
        if not self.current_project:
            return
        if not self.current_project.is_running:
            InfoBar.warning(
                title="提示",
                content="项目未运行，请先启动项目",
                orient=Qt.Orientation.Horizontal,
                parent=self
            )
            return

        # 检查 composer.json 是否存在
        composer_json = self.current_project.path / "src" / "composer.json"
        if not composer_json.exists():
            InfoBar.warning(
                title="提示",
                content="项目中不存在 composer.json 文件",
                orient=Qt.Orientation.Horizontal,
                parent=self
            )
            return

        full_cmd = f"composer {command}"
        if package:
            full_cmd += f" {package}"

        p = str(self.current_project.path)
        # 在终端中执行 composer 命令
        self._launch_terminal([
            ["kitty", "--directory", p, "docker", "compose", "exec", "php", "zsh", "-c", full_cmd],
            ["alacritty", "--working-directory", p, "-e", "docker", "compose", "exec", "php", "zsh", "-c", full_cmd],
            ["gnome-terminal", "--working-directory", p, "--", "docker", "compose", "exec", "php", "zsh", "-c", full_cmd],
            ["konsole", "--workdir", p, "-e", "docker", "compose", "exec", "php", "zsh", "-c", full_cmd],
        ])

    def composer_install(self):
        """执行 composer install"""
        self._run_composer_command("install")

    def composer_update(self):
        """执行 composer update"""
        self._run_composer_command("update")

    def composer_require(self):
        """执行 composer require（弹出输入框让用户输入包名）"""
        from qfluentwidgets import MessageBoxBase, LineEdit

        if not self.current_project:
            return
        if not self.current_project.is_running:
            InfoBar.warning(
                title="提示",
                content="项目未运行，请先启动项目",
                orient=Qt.Orientation.Horizontal,
                parent=self
            )
            return

        # 创建输入对话框
        box = MessageBoxBase(self.window())
        box.titleLabel = StrongBodyLabel("Composer Require")
        box.contentLabel = BodyLabel("请输入要安装的包名（支持版本号，如：laravel/framework:^10.0）")

        box.package_input = LineEdit(box)
        box.package_input.setPlaceholderText("vendor/package")
        box.package_input.setClearButtonEnabled(True)
        box.viewLayout.addWidget(box.contentLabel)
        box.viewLayout.addWidget(box.package_input)

        box.yesButton.setText("安装")
        box.cancelButton.setText("取消")

        if box.exec():
            package = box.package_input.text().strip()
            if package:
                self._run_composer_command("require", package)

    def _notify(self, title: str, msg: str, notify_type: str = "success"):
        """发送通知（InfoBar + 系统托盘）

        Args:
            title: 通知标题
            msg: 通知内容
            notify_type: 通知类型，可选值: "success", "error", "warning", "info"
        """
        # 获取主窗口并调用其通知方法
        main_window = self.window()
        if hasattr(main_window, '_notify'):
            main_window._notify(title, msg, notify_type)


class MainWindow(FluentWindow):
    """主窗口  —— 使用 FluentWindow 标准侧边栏展示项目列表"""

    def __init__(self):
        super().__init__()
        self.project_manager = ProjectManager()
        self.projects: List[Project] = []

        # 确保折叠按钮显示在顶部，且隐藏多余的返回按钮
        self.navigationInterface.setMenuButtonVisible(True)
        self.navigationInterface.setReturnButtonVisible(False)
        self.navigationInterface.setExpandWidth(220)  # 侧边栏宽度
        self._project_nav_keys: List[str] = []
        self._project_nav_items = {}

        self.setWindowTitle("PHP 开发环境管理器")
        self.setMinimumSize(800, 600)

        # 直接将仪表盘页加入 stackedWidget
        self.dashboard_page = ProjectDashboardPage(self)
        self.stackedWidget.addWidget(self.dashboard_page)
        self.stackedWidget.setCurrentWidget(self.dashboard_page)

        # 底部操作项
        self.navigationInterface.addItem(
            routeKey='new_project', icon=FIF.ADD, text="新建项目",
            onClick=self.create_project, position=NavigationItemPosition.BOTTOM,
            selectable=False
        )
        self.navigationInterface.addItem(
            routeKey='start_all', icon=FIF.PLAY, text="启动全部",
            onClick=self.start_all_projects, position=NavigationItemPosition.BOTTOM,
            selectable=False
        )
        self.navigationInterface.addItem(
            routeKey='stop_all', icon=FIF.PAUSE, text="停止全部",
            onClick=self.stop_all_projects, position=NavigationItemPosition.BOTTOM,
            selectable=False
        )
        self.navigationInterface.addSeparator(position=NavigationItemPosition.BOTTOM)
        self.navigationInterface.addItem(
            routeKey='refresh', icon=FIF.SYNC, text="刷新",
            onClick=self._refresh_all_projects, position=NavigationItemPosition.BOTTOM,
            selectable=False
        )
        self.navigationInterface.addItem(
            routeKey='settings', icon=FIF.SETTING, text="设置",
            onClick=self.open_settings, position=NavigationItemPosition.BOTTOM,
            selectable=False
        )

        self._project_nav_keys: List[str] = []
        self._project_nav_items = {}

        self.setup_tray()

        # 定时刷新
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._auto_refresh)
        self.refresh_timer.start(10000)

        # 初始加载
        self.load_projects()

        # 首次启动代理提示（窗口渲染完成后再弹）
        QTimer.singleShot(800, self._check_first_launch_proxy)

    def update_sidebar_item_state(self, project_name: str, is_running: bool):
        """更新侧边栏某一项的运行状态颜色"""
        route_key = f"proj_{project_name}"
        if route_key in self._project_nav_items:
            nav_item = self._project_nav_items[route_key]
            if hasattr(nav_item, 'set_running_state'):
                nav_item.set_running_state(is_running)

    def load_projects(self, select_project: str = None):
        """异步加载项目列表

        Args:
            select_project: 可选，指定要选中的项目名
        """
        # 移除旧项目导航项
        for key in self._project_nav_keys:
            try:
                self.navigationInterface.removeWidget(key)
            except Exception:
                pass
        self._project_nav_keys.clear()
        self._project_nav_items.clear()

        # 异步加载项目
        threading.Thread(
            target=self._async_load_projects,
            args=(select_project,),
            daemon=True
        ).start()

    def _async_load_projects(self, select_project: str = None):
        """异步获取项目列表"""
        projects = self.project_manager.get_all_projects()
        callback = functools.partial(self._on_projects_loaded, projects, select_project)
        QTimer.singleShot(0, callback)

    def _on_projects_loaded(self, projects: list, select_project: str = None):
        """项目列表加载完成回调"""
        self.projects = projects
        self.dashboard_page.projects = self.projects

        # 在 SCROLL 区域插入项目导航项
        for idx, project in enumerate(self.projects):
            route_key = f"proj_{project.name}"
            p = project

            # 创建自定义导航项
            nav_item = ProjectNavigationItem(project)

            self.navigationInterface.insertWidget(
                index=idx,
                routeKey=route_key,
                widget=nav_item,
                onClick=lambda checked=False, proj=p: self.on_project_clicked(proj),
                position=NavigationItemPosition.SCROLL,
                tooltip=f"PHP {project.php_version} | 端口:{project.port}"
            )
            self._project_nav_keys.append(route_key)
            self._project_nav_items[route_key] = nav_item

        # 选中指定项目或第一个
        if self.projects:
            if select_project:
                for project in self.projects:
                    if project.name == select_project:
                        self.on_project_clicked(project)
                        return
            # 默认选中第一个
            self.on_project_clicked(self.projects[0])
        else:
            self.dashboard_page.show_project_view(False)

    def on_project_clicked(self, project: Project):
        """导航项点击 —— 更新仪表盘"""
        route_key = f"proj_{project.name}"
        self.navigationInterface.setCurrentItem(route_key)

        # 先显示项目（带加载状态）
        self.dashboard_page.show_project(project, loading=True)
        self.switchTo(self.dashboard_page)

        # 异步刷新该项目状态（立即执行）
        callback = functools.partial(self._refresh_single_project, project.name)
        QTimer.singleShot(0, callback)

    def _refresh_single_project(self, project_name: str):
        """异步刷新单个项目的状态"""
        from core.config import BASE_DIR

        project_path = BASE_DIR / project_name
        if project_path.exists():
            threading.Thread(
                target=self._async_refresh_single_project,
                args=(project_name, project_path),
                daemon=True
            ).start()

    def _async_refresh_single_project(self, project_name: str, project_path):
        """异步获取单个项目状态"""
        updated = self.project_manager._load_project(project_path)
        if updated:
            QTimer.singleShot(0, functools.partial(self._on_refresh_single_project, updated))

    def _on_refresh_single_project(self, updated):
        """单个项目刷新完成回调"""
        project_name = updated.name
        # 更新 self.projects 中的对应项目
        for i, p in enumerate(self.projects):
            if p.name == project_name:
                self.projects[i] = updated
                break

        # 更新侧边栏项目的状态
        route_key = f"proj_{project_name}"
        if route_key in self._project_nav_items:
            nav_item = self._project_nav_items[route_key]
            if hasattr(nav_item, 'set_running_state'):
                nav_item.set_running_state(updated.is_running)

        # 如果是当前显示的项目，更新仪表盘
        if self.dashboard_page.current_project and self.dashboard_page.current_project.name == project_name:
            self.dashboard_page.dashboard.update_project(updated, loading=False)
            self.dashboard_page.current_project = updated
            # 如果项目运行中，刷新 PHP 配置
            if updated.is_running:
                QTimer.singleShot(100, self.dashboard_page._refresh_php_info)

    def _auto_refresh(self):
        """定时刷新当前项目状态"""
        if self.dashboard_page.current_project:
            self.dashboard_page._reload_current()

    def setup_tray(self):
        """设置系统托盘"""
        self.tray_icon = QSystemTrayIcon(self)
        icon_path = Path(__file__).parent.parent / "resources" / "icons" / "phpbox-tray.png"
        if icon_path.exists():
            self.tray_icon.setIcon(QIcon(str(icon_path)))
        else:
            self.tray_icon.setIcon(self.style().standardIcon(
                self.style().StandardPixmap.SP_ComputerIcon
            ))
        self.tray_icon.setToolTip("PHP 开发环境管理器")

        tray_menu = SystemTrayMenu(parent=self)
        tray_menu.addAction(Action(FIF.VIEW, "显示主窗口", triggered=self.show))
        tray_menu.addAction(Action(FIF.ADD, "新建项目", triggered=self.create_project))
        tray_menu.addSeparator()
        tray_menu.addAction(Action(FIF.CLOSE, "退出", triggered=self.quit_app))

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # 左键单击
            self.show()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            # 双击
            self.show()

    def create_project(self):
        dialog = CreateProjectDialog(self)
        dialog.project_created.connect(self._on_project_created)
        dialog.show()

    def _on_project_created(self, project_name: str):
        """项目创建成功回调"""
        self.load_projects(select_project=project_name)
        self._notify("创建成功", f"项目「{project_name}」已创建并启动", "success")

    def open_settings(self):
        SettingsDialog(self).exec()

    def _check_first_launch_proxy(self):
        """首次启动时提示配置代理"""
        s = Settings()
        if not s.is_first_launch():
            return
        # 已配置过代理则不提示
        if s.get_proxy():
            s.mark_proxy_prompted()
            return

        s.mark_proxy_prompted()

        bar = InfoBar.warning(
            title="建议配置代理",
            content="首次使用建议配置 HTTP 代理，以加速 Docker 构建时的 PHP 扩展下载。",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=12000,
            parent=self
        )
        # 在 InfoBar 上追加一个"去设置"按钮
        from qfluentwidgets import HyperlinkButton
        btn = PushButton("去设置")
        btn.setFixedHeight(28)
        btn.clicked.connect(lambda: (bar.close(), self.open_settings()))
        bar.addWidget(btn)

    def start_all_projects(self):
        """启动所有已停止的项目"""
        # 先刷新项目状态
        self.projects = self.project_manager.get_all_projects()

        if not self.projects:
            self._notify("提示", "没有可启动的项目", "warning")
            return

        stopped_projects = [p for p in self.projects if not p.is_running]
        if not stopped_projects:
            self._notify("提示", "所有项目已在运行中", "info")
            return

        # 过滤端口冲突的项目
        to_start = []
        conflict_ports = []
        for project in stopped_projects:
            try:
                port = int(project.port)
            except ValueError:
                port = 8080
            usage = get_port_usage(port, project.name)
            if usage:
                conflict_ports.append((project.name, project.port, usage))
            else:
                to_start.append(project)

        if conflict_ports:
            msg = "、".join([f"{name}({port})被{usage}占用" for name, port, usage in conflict_ports])
            self._notify("端口冲突", f"以下项目端口被占用: {msg}", "warning")

        if not to_start:
            return

        # 异步启动所有项目
        threading.Thread(
            target=self._async_batch_operation,
            args=(to_start, "up"),
            daemon=True
        ).start()

    def _async_batch_operation(self, projects: list, operation: str):
        """异步批量执行 docker 操作"""
        success_count = 0
        for project in projects:
            result = getattr(DockerManager(project.path), operation)()
            if result.success:
                success_count += 1
        ok_title, ok_verb, _ = ProjectDashboardPage._OP_LABELS[operation]
        label = "批量启动" if operation == "up" else "批量停止"
        QTimer.singleShot(0, functools.partial(
            self._on_batch_operation_result, success_count, label))

    def stop_all_projects(self):
        """停止所有正在运行的项目"""
        # 先刷新项目状态
        self.projects = self.project_manager.get_all_projects()

        if not self.projects:
            self._notify("提示", "没有可停止的项目", "warning")
            return

        running_projects = [p for p in self.projects if p.is_running]
        if not running_projects:
            self._notify("提示", "没有正在运行的项目", "info")
            return

        # 异步停止所有项目
        threading.Thread(
            target=self._async_batch_operation,
            args=(running_projects, "stop"),
            daemon=True
        ).start()

    def _on_batch_operation_result(self, success_count: int, label: str):
        """批量操作结果回调"""
        if success_count > 0:
            verb = "启动" if "启动" in label else "停止"
            self._notify(label, f"已{verb} {success_count} 个项目")
            QTimer.singleShot(500, self._refresh_all_projects)

    def _refresh_all_projects(self):
        """刷新所有项目状态"""
        self.load_projects()

    def _notify(self, title: str, msg: str, notify_type: str = "success"):
        """发送通知（InfoBar + 系统托盘）

        Args:
            title: 通知标题
            msg: 通知内容
            notify_type: 通知类型，可选值: "success", "error", "warning", "info"
        """
        # 获取当前显示的页面作为 InfoBar 的 parent
        current_widget = self.stackedWidget.currentWidget()
        if not current_widget:
            current_widget = self

        # 根据 notify_type 选择对应的 InfoBar 方法
        info_bar_methods = {
            "success": InfoBar.success,
            "error": InfoBar.error,
            "warning": InfoBar.warning,
            "info": InfoBar.info,
        }
        method = info_bar_methods.get(notify_type, InfoBar.success)
        method(
            title=title,
            content=msg,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=current_widget
        )

        # 只在错误或警告时发送系统托盘通知
        if notify_type in ("error", "warning"):
            tray_icons = {
                "error": QSystemTrayIcon.MessageIcon.Critical,
                "warning": QSystemTrayIcon.MessageIcon.Warning,
            }
            tray_icon_type = tray_icons.get(notify_type, QSystemTrayIcon.MessageIcon.Warning)
            self.tray_icon.showMessage(title, msg, tray_icon_type, 3000)

    def quit_app(self):
        self.tray_icon.hide()
        QApplication.quit()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
