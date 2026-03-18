"""扩展选择器组件"""
from typing import List
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame
from PyQt6.QtCore import Qt, pyqtSignal

from qfluentwidgets import (
    PushButton, BodyLabel, CaptionLabel, CheckBox,
    CardWidget, StrongBodyLabel, ScrollArea, SearchLineEdit
)
from core.config import EXTENSIONS


class ExtensionSelector(QWidget):
    """扩展选择器组件"""

    selection_changed = pyqtSignal(list)  # 选中的扩展列表

    def __init__(self, parent=None):
        super().__init__(parent)
        self.checkboxes = {}  # {ext_id: CheckBox}
        self.category_items = {} # {category_name: (CardWidget, [ext_id])}
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 快捷操作
        quick_layout = QHBoxLayout()
        select_all_btn = PushButton("全选")
        select_all_btn.clicked.connect(self.select_all)
        deselect_all_btn = PushButton("取消全选")
        deselect_all_btn.clicked.connect(self.deselect_all)
        select_default_btn = PushButton("恢复默认")
        select_default_btn.clicked.connect(self.select_default)
        quick_layout.addWidget(select_all_btn)
        quick_layout.addWidget(deselect_all_btn)
        quick_layout.addWidget(select_default_btn)
        quick_layout.addStretch()
        layout.addLayout(quick_layout)

        # 统计标签
        self.count_label = CaptionLabel("已选: 0 个扩展")
        
        # 搜索框
        self.search_input = SearchLineEdit()
        self.search_input.setPlaceholderText("搜索扩展名称或 ID...")
        self.search_input.textChanged.connect(self.filter_extensions)
        
        layout.addWidget(self.count_label)
        layout.addWidget(self.search_input)

        # 滚动区域
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")

        # 扩展列表容器
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(12)

        for category, exts in EXTENSIONS.items():
            # 使用卡片包装每个分类
            category_card = CardWidget()
            category_layout = QVBoxLayout(category_card)
            category_layout.setSpacing(8)

            category_layout.addWidget(StrongBodyLabel(category))

            cat_ext_ids = []
            for ext in exts:
                cb = CheckBox(f"{ext['name']} ({ext['id']})")
                cb.setChecked(ext['default'])
                cb.stateChanged.connect(self.on_checkbox_changed)
                category_layout.addWidget(cb)
                self.checkboxes[ext['id']] = cb
                cat_ext_ids.append(ext['id'])

            container_layout.addWidget(category_card)
            self.category_items[category] = (category_card, cat_ext_ids)

        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

        self.update_count()

    def on_checkbox_changed(self, state):
        """复选框状态改变"""
        self.update_count()
        self.selection_changed.emit(self.get_selected_extensions())

    def filter_extensions(self, text: str):
        """搜索过滤"""
        text = text.lower().strip()
        
        for category, (card, ext_ids) in self.category_items.items():
            visible_count = 0
            for ext_id in ext_ids:
                cb = self.checkboxes[ext_id]
                # 检查名称或 ID 是否匹配
                is_match = not text or text in cb.text().lower() or text in ext_id.lower()
                cb.setVisible(is_match)
                if is_match:
                    visible_count += 1
            
            # 如果分类中没有可见的条目，隐藏整个卡片
            card.setVisible(visible_count > 0)
            
    def update_count(self):
        """更新计数"""
        count = sum(1 for cb in self.checkboxes.values() if cb.isChecked())
        self.count_label.setText(f"已选: {count} 个扩展")

    def get_selected_extensions(self) -> List[str]:
        """获取选中的扩展 ID 列表"""
        return [
            ext_id for ext_id, cb in self.checkboxes.items()
            if cb.isChecked()
        ]

    def select_all(self):
        """全选"""
        for cb in self.checkboxes.values():
            cb.setChecked(True)

    def deselect_all(self):
        """取消全选"""
        for cb in self.checkboxes.values():
            cb.setChecked(False)

    def select_default(self):
        """恢复默认选择"""
        for category, exts in EXTENSIONS.items():
            for ext in exts:
                if ext['id'] in self.checkboxes:
                    self.checkboxes[ext['id']].setChecked(ext['default'])

    def set_selected(self, extensions: List[str]):
        """设置选中的扩展"""
        for ext_id, cb in self.checkboxes.items():
            cb.setChecked(ext_id in extensions)
