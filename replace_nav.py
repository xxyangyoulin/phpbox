import re

with open('ui/main_window.py', 'r') as f:
    content = f.read()

# Replace ProjectNavigationItem definition
target_nav = re.search(r'class ProjectNavigationItem\(BaseNavigationPushButton\):.*?        painter\.end\(\)', content, re.DOTALL).group(0)

replacement_nav = '''class ProjectNavigationItem(BaseNavigationPushButton):
    """自定义项目导航项，使用更大的图标"""

    def __init__(self, project, parent=None):
        self.project_name = project.name
        self.project_port = project.port
        self.project_color = get_project_color(project.name)
        text = f"{project.name}  :{project.port}"
        super().__init__(make_project_icon(project.name), text, True, parent)

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
        color = QColor(self.project_color)

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

# Replace ProjectNavigationItem instantiation
content = content.replace('nav_item = ProjectNavigationItem(project.name)', 'nav_item = ProjectNavigationItem(project)')

with open('ui/main_window.py', 'w') as f:
    f.write(content)

print("Replacement done.")
