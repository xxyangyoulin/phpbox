"""扩展选择器组件"""
from typing import List
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal

from qfluentwidgets import (
    PushButton, BodyLabel, CaptionLabel, CheckBox,
    CardWidget, StrongBodyLabel, ScrollArea, SearchLineEdit,
    TransparentToolButton, FluentIcon as FIF, isDarkTheme
)
from core.config import EXTENSIONS


# 快捷预设定义：名称 -> 扩展 ID 列表
PRESETS = {
    "基础套装": ["pdo_mysql", "redis", "gd", "mbstring", "curl", "zip",
                 "bcmath", "iconv", "igbinary"],
    "Laravel": ["pdo_mysql", "redis", "gd", "mbstring", "curl", "zip",
                "bcmath", "iconv", "igbinary", "tokenizer", "ctype",
                "fileinfo", "phar", "dom", "xml", "simplexml", "xmlwriter",
                "xmlreader"],
    "ThinkPHP": ["pdo_mysql", "redis", "gd", "mbstring", "curl", "zip",
                 "bcmath", "iconv", "tokenizer", "ctype", "fileinfo",
                 "simplexml", "dom"],
    "全栈": None,  # None 表示全选
}


class CollapsibleCategory(QWidget):
    """可折叠的扩展分类卡片"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._collapsed = False
        self._setup_ui(title)

    def _setup_ui(self, title: str):
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        self._card = CardWidget(self)
        card_layout = QVBoxLayout(self._card)
        card_layout.setSpacing(0)
        card_layout.setContentsMargins(16, 8, 16, 12)

        # 标题行（点击可折叠）
        header = QWidget()
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 4, 0, 4)
        header_layout.setSpacing(8)

        self._title_label = StrongBodyLabel(title)
        self._toggle_btn = TransparentToolButton(FIF.CHEVRON_DOWN_MED, self)
        self._toggle_btn.setFixedSize(20, 20)
        self._toggle_btn.clicked.connect(self.toggle)

        self._count_label = CaptionLabel("0/0")
        self._count_label.setStyleSheet("color: #64748b;")

        header_layout.addWidget(self._title_label)
        header_layout.addWidget(self._count_label)
        header_layout.addStretch()
        header_layout.addWidget(self._toggle_btn)

        header.mousePressEvent = lambda e: self.toggle()
        card_layout.addWidget(header)

        # 分隔线
        self._separator = QFrame()
        self._separator.setFrameShape(QFrame.Shape.HLine)
        self._separator.setStyleSheet("color: #e2e8f0;")
        card_layout.addWidget(self._separator)

        # 扩展内容区
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setSpacing(4)
        self._content_layout.setContentsMargins(0, 8, 0, 0)
        card_layout.addWidget(self._content)

        self._outer.addWidget(self._card)

    def add_checkbox(self, cb: QWidget):
        self._content_layout.addWidget(cb)

    def toggle(self):
        self._collapsed = not self._collapsed
        self._content.setVisible(not self._collapsed)
        self._separator.setVisible(not self._collapsed)
        icon = FIF.CHEVRON_RIGHT if self._collapsed else FIF.CHEVRON_DOWN_MED
        self._toggle_btn.setIcon(icon)

    def update_count(self, checked: int, total: int):
        self._count_label.setText(f"{checked}/{total}")


class ExtensionSelector(QWidget):
    """扩展选择器组件"""

    selection_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.checkboxes = {}        # {ext_id: CheckBox}
        self.category_widgets = {}  # {category_name: CollapsibleCategory}
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ── 快捷预设行 ──────────────────────────────────────────
        preset_card = CardWidget()
        preset_inner = QVBoxLayout(preset_card)
        preset_inner.setContentsMargins(16, 10, 16, 10)
        preset_inner.setSpacing(8)
        preset_inner.addWidget(BodyLabel("快捷预设"))

        preset_btn_row = QHBoxLayout()
        preset_btn_row.setSpacing(8)
        for preset_name in PRESETS:
            btn = PushButton(preset_name)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda checked, n=preset_name: self._apply_preset(n))
            preset_btn_row.addWidget(btn)
        preset_btn_row.addStretch()
        preset_inner.addLayout(preset_btn_row)
        layout.addWidget(preset_card)

        # ── 操作栏 ──────────────────────────────────────────────
        op_layout = QHBoxLayout()
        op_layout.setSpacing(8)

        self.count_label = CaptionLabel("已选: 0 个扩展")
        self.search_input = SearchLineEdit()
        self.search_input.setPlaceholderText("搜索扩展名称或 ID...")
        self.search_input.textChanged.connect(self.filter_extensions)

        deselect_btn = PushButton("清空")
        deselect_btn.clicked.connect(self.deselect_all)
        restore_btn = PushButton("恢复默认")
        restore_btn.clicked.connect(self.select_default)

        op_layout.addWidget(self.count_label)
        op_layout.addStretch()
        op_layout.addWidget(deselect_btn)
        op_layout.addWidget(restore_btn)
        layout.addLayout(op_layout)
        layout.addWidget(self.search_input)

        # ── 扩展列表（可滚动）──────────────────────────────────
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self._container_layout = QVBoxLayout(container)
        self._container_layout.setSpacing(8)
        self._container_layout.setContentsMargins(0, 0, 4, 0)

        for category, exts in EXTENSIONS.items():
            cat_widget = CollapsibleCategory(category)
            for ext in exts:
                cb = CheckBox(f"{ext['name']}  ({ext['id']})")
                cb.setChecked(ext['default'])
                cb.stateChanged.connect(lambda state, c=category: self._on_cb_changed(c))
                cat_widget.add_checkbox(cb)
                self.checkboxes[ext['id']] = cb
            self._container_layout.addWidget(cat_widget)
            self.category_widgets[category] = cat_widget

        self._container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

        self.update_count()

    def _on_cb_changed(self, category: str):
        self._update_category_count(category)
        self.update_count()
        self.selection_changed.emit(self.get_selected_extensions())

    def _update_category_count(self, category: str):
        cat_widget = self.category_widgets.get(category)
        if not cat_widget:
            return
        exts = EXTENSIONS.get(category, [])
        total = len(exts)
        checked = sum(1 for e in exts if self.checkboxes[e['id']].isChecked())
        cat_widget.update_count(checked, total)

    def _update_all_category_counts(self):
        for category in EXTENSIONS:
            self._update_category_count(category)

    def _apply_preset(self, name: str):
        ids = PRESETS.get(name)
        if ids is None:
            # 全选
            self.select_all()
        else:
            id_set = set(ids)
            for ext_id, cb in self.checkboxes.items():
                cb.setChecked(ext_id in id_set)
        self._update_all_category_counts()
        self.update_count()
        self.selection_changed.emit(self.get_selected_extensions())

    def filter_extensions(self, text: str):
        text = text.lower().strip()
        for category, cat_widget in self.category_widgets.items():
            exts = EXTENSIONS.get(category, [])
            visible = 0
            for ext in exts:
                cb = self.checkboxes[ext['id']]
                match = not text or text in ext['name'].lower() or text in ext['id'].lower()
                cb.setVisible(match)
                if match:
                    visible += 1
            cat_widget.setVisible(visible > 0)

    def update_count(self):
        count = sum(1 for cb in self.checkboxes.values() if cb.isChecked())
        self.count_label.setText(f"已选: {count} 个扩展")

    def get_selected_extensions(self) -> List[str]:
        return [ext_id for ext_id, cb in self.checkboxes.items() if cb.isChecked()]

    def select_all(self):
        for cb in self.checkboxes.values():
            cb.setChecked(True)

    def deselect_all(self):
        for cb in self.checkboxes.values():
            cb.setChecked(False)

    def select_default(self):
        for category, exts in EXTENSIONS.items():
            for ext in exts:
                if ext['id'] in self.checkboxes:
                    self.checkboxes[ext['id']].setChecked(ext['default'])
        self._update_all_category_counts()

    def set_selected(self, extensions: List[str]):
        id_set = set(extensions)
        for ext_id, cb in self.checkboxes.items():
            cb.setChecked(ext_id in id_set)
        self._update_all_category_counts()
        self.update_count()
