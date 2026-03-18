"""状态指示器组件"""
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, QTimer, pyqtProperty
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QLinearGradient, QFont

from qfluentwidgets import BodyLabel, StrongBodyLabel, CaptionLabel, isDarkTheme


class ProjectAvatar(QWidget):
    """首字母图标，带状态指示点"""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)
        self.name = name
        self.letter = name[0].upper() if name else "?"
        self._is_running = False
        
        # 根据首字母分配颜色
        colors = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#14b8a6"]
        idx = ord(self.letter) % len(colors)
        self.bg_color = QColor(colors[idx])

    def set_running(self, running: bool):
        self._is_running = running
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制背景圆形
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self.bg_color))
        painter.drawEllipse(0, 0, 36, 36)

        # 绘制字母
        painter.setPen(QPen(Qt.GlobalColor.white))
        font = QFont("Segoe UI", 16, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(0, 0, 36, 36, Qt.AlignmentFlag.AlignCenter, self.letter)

        # 绘制状态小圆点
        dot_radius = 5
        dot_x = 36 - dot_radius * 2
        dot_y = 36 - dot_radius * 2
        
        # 挖除背景让状态点有描边效果
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.drawEllipse(dot_x - 1, dot_y - 1, dot_radius * 2 + 2, dot_radius * 2 + 2)
        
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        status_color = QColor("#22c55e") if self._is_running else QColor("#94a3b8")
        painter.setBrush(QBrush(status_color))
        painter.drawEllipse(dot_x, dot_y, dot_radius * 2, dot_radius * 2)


class ProjectListItem(QFrame):
    """项目列表项 - 现代化卡片样式"""

    clicked = pyqtSignal(str)

    def __init__(self, project_name: str, php_version: str,
                 port: str, is_running: bool, parent=None):
        super().__init__(parent)
        self.project_name = project_name
        self._is_selected = False
        self._is_running = is_running
        self.setup_ui(project_name, php_version, port, is_running)

    def setup_ui(self, name: str, php_version: str, port: str, is_running: bool):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # 状态指示器
        self.status_dot = ProjectAvatar(name)
        self.status_dot.set_running(is_running)
        layout.addWidget(self.status_dot)

        # 项目信息 - 双行布局
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        self.name_label = StrongBodyLabel(name)
        info_layout.addWidget(self.name_label)

        # 副标题行
        subtitle = CaptionLabel(f"PHP {php_version}  ·  :{port}")
        subtitle.setObjectName("subtitle")
        info_layout.addWidget(subtitle)

        layout.addLayout(info_layout, 1)

        # 状态标签
        if is_running:
            status_badge = QLabel("运行中")
            status_badge.setObjectName("statusBadge")
            status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status_badge.setFixedHeight(22)
            status_badge.setStyleSheet("""
                QLabel#statusBadge {
                    background-color: rgba(34, 197, 94, 0.15);
                    color: #22c55e;
                    border-radius: 11px;
                    padding: 2px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
            """)
            layout.addWidget(status_badge)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(56)
        self._apply_style(False)

    def mousePressEvent(self, event):
        self.clicked.emit(self.project_name)
        super().mousePressEvent(event)

    def update_status(self, is_running: bool):
        self._is_running = is_running
        self.status_dot.set_running(is_running)

    def setSelected(self, selected: bool):
        """设置选中状态"""
        self._is_selected = selected
        self._apply_style(selected)

    def _apply_style(self, selected: bool):
        """应用样式"""
        dark = isDarkTheme()

        if selected:
            if dark:
                bg = "rgba(0, 120, 212, 0.18)"
                hover_bg = "rgba(0, 120, 212, 0.22)"
                border = "rgba(0, 120, 212, 0.45)"
            else:
                bg = "rgba(0, 120, 212, 0.08)"
                hover_bg = "rgba(0, 120, 212, 0.12)"
                border = "rgba(0, 120, 212, 0.3)"
        else:
            if dark:
                bg = "transparent"
                hover_bg = "rgba(255, 255, 255, 0.06)"
                border = "transparent"
            else:
                bg = "transparent"
                hover_bg = "rgba(0, 0, 0, 0.04)"
                border = "transparent"

        self.setStyleSheet(f"""
            ProjectListItem {{
                background-color: {bg};
                border-radius: 8px;
                border: 1px solid {border};
            }}
            ProjectListItem:hover {{
                background-color: {hover_bg};
            }}
        """)
