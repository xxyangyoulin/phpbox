import re

with open('ui/main_window.py', 'r') as f:
    content = f.read()

# 1. Update make_project_icon to accept is_running
target_make_icon = re.search(r'def make_project_icon\(name: str\) -> QIcon:.*?    return QIcon\(pixmap\)', content, re.DOTALL).group(0)
replacement_make_icon = '''def make_project_icon(name: str, is_running: bool = True) -> QIcon:
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

    return QIcon(pixmap)'''

content = content.replace(target_make_icon, replacement_make_icon)

# 2. Update ProjectNavigationItem to store is_running and paint differently
target_nav = re.search(r'class ProjectNavigationItem\(BaseNavigationPushButton\):.*?        painter\.end\(\)', content, re.DOTALL).group(0)

replacement_nav = '''class ProjectNavigationItem(BaseNavigationPushButton):
    """自定义项目导航项，使用更大的图标"""

    def __init__(self, project, parent=None):
        self.project_name = project.name
        self.project_port = project.port
        self.is_running = project.is_running
        self.project_color = get_project_color(project.name)
        text = f"{project.name}  :{project.port}"
        super().__init__(make_project_icon(project.name, self.is_running), text, True, parent)

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

        painter.end()'''

content = content.replace(target_nav, replacement_nav)

# 3. Update ModernDashboardWidget.update_project to set gray text and icon
target_update_proj = re.search(r'    def update_project\(self, project: Project, loading: bool = False, animate: bool = False\):.*?        # 更新头像\n        self\.avatar_label\.setPixmap\(make_project_icon\(project\.name\)\.pixmap\(48, 48\)\)', content, re.DOTALL).group(0)

replacement_update_proj = '''    def update_project(self, project: Project, loading: bool = False, animate: bool = False):
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
        self.avatar_label.setPixmap(make_project_icon(project.name, is_running).pixmap(48, 48))'''

content = content.replace(target_update_proj, replacement_update_proj)

# 4. In MainWindow._on_refresh_single_project, we must update ProjectNavigationItem
target_refresh_single = re.search(r'    def _on_refresh_single_project\(self, updated\):.*?        for i, p in enumerate\(self\.projects\):\n            if p\.name == project_name:\n                self\.projects\[i\] = updated\n                break', content, re.DOTALL).group(0)

replacement_refresh_single = '''    def _on_refresh_single_project(self, updated):
        """单个项目刷新完成回调"""
        project_name = updated.name
        # 更新 self.projects 中的对应项目
        for i, p in enumerate(self.projects):
            if p.name == project_name:
                self.projects[i] = updated
                break

        # 更新侧边栏项目的状态
        route_key = f"proj_{project_name}"
        if route_key in self.navigationInterface.widget().routes:
            nav_item = self.navigationInterface.widget().routes[route_key]
            if hasattr(nav_item, 'set_running_state'):
                nav_item.set_running_state(updated.is_running)'''

content = content.replace(target_refresh_single, replacement_refresh_single)


with open('ui/main_window.py', 'w') as f:
    f.write(content)

print("Replacement done.")
