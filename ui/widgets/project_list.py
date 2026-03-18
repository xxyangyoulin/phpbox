"""项目列表组件 - 侧栏版"""
from typing import List, Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal

from qfluentwidgets import (
    LineEdit, CaptionLabel, FluentIcon as FIF,
    isDarkTheme, StrongBodyLabel, PrimaryPushButton, ToolButton
)

from .status_indicator import ProjectListItem
from core.project import Project


class ProjectListWidget(QWidget):
    """项目列表组件 - 适用于侧栏"""

    project_selected = pyqtSignal(str)  # 项目名
    refresh_requested = pyqtSignal()
    add_project_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.projects = []
        self._selected_name = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 标题行
        header = QHBoxLayout()
        header.setSpacing(8)
        title = StrongBodyLabel("项目")
        title.setStyleSheet("font-size: 15px;")
        header.addWidget(title)
        header.addStretch()

        # 新建按钮
        self.add_btn = ToolButton(FIF.ADD)
        self.add_btn.setFixedSize(30, 30)
        self.add_btn.setToolTip("新建项目")
        self.add_btn.clicked.connect(self.add_project_requested.emit)
        header.addWidget(self.add_btn)

        # 刷新按钮
        self.refresh_btn = ToolButton(FIF.SYNC)
        self.refresh_btn.setFixedSize(30, 30)
        self.refresh_btn.setToolTip("刷新列表")
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self.refresh_btn)

        layout.addLayout(header)

        # 项目列表滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                width: 4px;
                background: transparent;
            }
            QScrollBar::handle:vertical {
                background: rgba(128, 128, 128, 0.3);
                border-radius: 2px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(128, 128, 128, 0.5);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        self.list_container = QWidget()
        self.list_container.setStyleSheet("background-color: transparent;")
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(4)
        self.list_layout.addStretch()

        self.scroll_area.setWidget(self.list_container)
        layout.addWidget(self.scroll_area)

        # 底部统计
        self.status_label = CaptionLabel("共 0 个项目")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: rgba(128, 128, 128, 0.7); padding: 4px;")
        layout.addWidget(self.status_label)

        # 存储列表项
        self.list_items = []

    def set_projects(self, projects: List[Project]):
        """设置项目列表"""
        self.projects = projects
        self.refresh_list()

    def refresh_list(self):
        """刷新列表显示"""
        # 清除旧的列表项
        for item in self.list_items:
            item.deleteLater()
        self.list_items.clear()

        for project in self.projects:
            item = ProjectListItem(
                project.name,
                project.php_version,
                project.port,
                project.is_running
            )
            item.clicked.connect(self.on_project_clicked)
            self.list_layout.insertWidget(self.list_layout.count() - 1, item)
            self.list_items.append(item)

            # 恢复选中状态
            if self._selected_name and project.name == self._selected_name:
                item.setSelected(True)

        running = sum(1 for p in self.projects if p.is_running)
        total = len(self.projects)
        if running > 0:
            self.status_label.setText(f"共 {total} 个项目 · {running} 个运行中")
        else:
            self.status_label.setText(f"共 {total} 个项目")



    def on_project_clicked(self, project_name: str):
        """项目点击"""
        self._selected_name = project_name
        # 更新选中状态
        for item in self.list_items:
            item.setSelected(item.project_name == project_name)
        self.project_selected.emit(project_name)

    def get_selected_project(self) -> Optional[str]:
        """获取选中的项目名"""
        return self._selected_name

    def select_first_project(self):
        """选中第一个项目"""
        if self.list_items:
            first_item = self.list_items[0]
            self._selected_name = first_item.project_name
            first_item.setSelected(True)
            self.project_selected.emit(first_item.project_name)
