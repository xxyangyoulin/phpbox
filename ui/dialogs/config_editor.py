"""配置文件编辑器对话框"""
from pathlib import Path
from typing import Optional, List
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QFrame, QMessageBox
from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QFont, QSyntaxHighlighter, QTextCharFormat, QColor,
    QTextCursor, QKeySequence, QShortcut
)

from qfluentwidgets import (
    PushButton, PrimaryPushButton, ComboBox, TextEdit, LineEdit,
    BodyLabel, CaptionLabel, ToolButton, FluentIcon as FIF,
    InfoBar, InfoBarPosition, MessageBox
)
from ui.styles import FluentDialog


class ConfigHighlighter(QSyntaxHighlighter):
    """配置文件语法高亮（包含搜索高亮）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._search_text = ""
        self.setup_formats()

    def setup_formats(self):
        from qfluentwidgets import isDarkTheme

        if isDarkTheme():
            comment_color = "#6a9955"
            section_color = "#569cd6"
            key_color = "#ce9178"
            search_bg = "#ffeb3b"
            search_fg = "#000000"
        else:
            comment_color = "#008000"
            section_color = "#0000ff"
            key_color = "#800080"
            search_bg = "#ffeb3b"
            search_fg = "#000000"

        # 注释
        self.comment_format = QTextCharFormat()
        self.comment_format.setForeground(QColor(comment_color))
        self.comment_format.setFontItalic(True)

        # 节
        self.section_format = QTextCharFormat()
        self.section_format.setForeground(QColor(section_color))
        self.section_format.setFontWeight(700)

        # 键
        self.key_format = QTextCharFormat()
        self.key_format.setForeground(QColor(key_color))

        # 搜索高亮
        self.search_format = QTextCharFormat()
        self.search_format.setBackground(QColor(search_bg))
        self.search_format.setForeground(QColor(search_fg))

    def set_search_text(self, text: str):
        self._search_text = text
        self.rehighlight()

    def highlightBlock(self, text):
        # 先应用语法高亮
        stripped = text.strip()

        # 注释
        if stripped.startswith(';') or stripped.startswith('#'):
            self.setFormat(0, len(text), self.comment_format)
        # 节
        elif stripped.startswith('[') and stripped.endswith(']'):
            self.setFormat(0, len(text), self.section_format)
        # 键 = 值
        elif '=' in text and not stripped.startswith(';'):
            idx = text.find('=')
            self.setFormat(0, idx, self.key_format)

        # 再应用搜索高亮（会覆盖语法高亮）
        if self._search_text:
            lower_text = text.lower()
            lower_search = self._search_text.lower()
            pos = 0
            while True:
                idx = lower_text.find(lower_search, pos)
                if idx == -1:
                    break
                self.setFormat(idx, len(self._search_text), self.search_format)
                pos = idx + len(self._search_text)


class UnsavedChangesDialog(FluentDialog):
    """未保存更改对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("未保存的更改")
        self.setMinimumWidth(400)
        self.setModal(True)
        self._setup_ui()

        # 覆盖父对话框的 ESC 快捷键（设置为子对话框作用域）
        if parent and hasattr(parent, 'escape_shortcut'):
            parent.escape_shortcut.setEnabled(False)
        self._parent = parent

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 20)

        # 消息
        message_label = BodyLabel("当前文件有未保存的更改，是否保存？")
        layout.addWidget(message_label)

        layout.addStretch()

        # 按钮区域
        btn_layout = QHBoxLayout()

        self.save_btn = PrimaryPushButton(FIF.SAVE, "保存")
        self.discard_btn = PushButton("不保存")
        self.cancel_btn = PushButton("取消")

        btn_layout.addStretch(1)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.discard_btn)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addStretch(1)

        layout.addLayout(btn_layout)

        # 连接信号
        self.save_btn.clicked.connect(self.accept_save)
        self.discard_btn.clicked.connect(self.accept_discard)
        self.cancel_btn.clicked.connect(self.reject)

        # 设置默认按钮和焦点
        self.save_btn.setFocus()

    def accept_save(self):
        self.done(1)  # 保存

    def accept_discard(self):
        self.done(2)  # 不保存

    def done(self, result):
        """对话框结束时恢复父对话框快捷键"""
        if self._parent and hasattr(self._parent, 'escape_shortcut'):
            self._parent.escape_shortcut.setEnabled(True)
        super().done(result)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)


class ConfigEditorDialog(FluentDialog):
    """配置文件编辑器对话框"""

    def __init__(self, project_path: Path, project_name: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.project_name = project_name
        self.current_file: Optional[Path] = None
        self.has_unsaved_changes = False
        self._original_content = ""  # 保存原始文件内容
        self._search_matches: List[QTextCursor] = []
        self._current_match_index = -1
        self._last_search_text = ""  # 记录上次搜索的文本
        self._last_editor_content = ""  # 用于检测内容是否真的变化

        self.setWindowTitle(f"配置编辑器 - {project_name}")
        self.setMinimumSize(900, 700)
        self.setup_ui()
        self.setup_shortcuts()
        self.load_config_list()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 顶部工具栏
        toolbar = QHBoxLayout()
        toolbar.addWidget(BodyLabel("配置文件:"))
        self.file_combo = ComboBox()
        self.file_combo.setMinimumWidth(250)
        self.file_combo.currentTextChanged.connect(self.on_file_selected)
        toolbar.addWidget(self.file_combo)

        external_btn = ToolButton(FIF.FOLDER)
        external_btn.setToolTip("外部编辑")
        external_btn.clicked.connect(self.open_external_editor)
        toolbar.addWidget(external_btn)

        # 搜索按钮
        search_btn = ToolButton(FIF.SEARCH)
        search_btn.setToolTip("搜索 (Ctrl+F)")
        search_btn.clicked.connect(self.show_search)
        toolbar.addWidget(search_btn)

        toolbar.addStretch()

        self.save_btn = PrimaryPushButton(FIF.SAVE, "保存")
        self.save_btn.clicked.connect(self.save_file)
        self.save_btn.setEnabled(False)
        toolbar.addWidget(self.save_btn)

        layout.addLayout(toolbar)

        # 文件路径标签
        self.file_path_label = CaptionLabel()
        layout.addWidget(self.file_path_label)

        # 搜索栏
        self.search_frame = QFrame()
        self.search_frame.setStyleSheet("QFrame { background-color: rgba(0,0,0,0.05); border-radius: 4px; padding: 4px; }")
        search_layout = QHBoxLayout(self.search_frame)
        search_layout.setContentsMargins(8, 4, 8, 4)
        search_layout.setSpacing(8)

        self.search_input = LineEdit()
        self.search_input.setPlaceholderText("搜索... (按回车搜索)")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumWidth(200)
        self.search_input.textChanged.connect(self.on_search_text_changed)
        self.search_input.returnPressed.connect(self.on_search_return_pressed)
        search_layout.addWidget(self.search_input)

        self.search_count_label = CaptionLabel("")
        self.search_count_label.setMinimumWidth(60)
        search_layout.addWidget(self.search_count_label)

        self.find_prev_btn = ToolButton(FIF.UP)
        self.find_prev_btn.setToolTip("上一个 (Shift+Enter)")
        self.find_prev_btn.clicked.connect(self.find_previous)
        search_layout.addWidget(self.find_prev_btn)

        self.find_next_btn = ToolButton(FIF.DOWN)
        self.find_next_btn.setToolTip("下一个 (Enter)")
        self.find_next_btn.clicked.connect(self.find_next)
        search_layout.addWidget(self.find_next_btn)

        close_search_btn = ToolButton(FIF.CLOSE)
        close_search_btn.setToolTip("关闭 (Esc)")
        close_search_btn.clicked.connect(self.hide_search)
        search_layout.addWidget(close_search_btn)

        self.search_frame.hide()
        layout.addWidget(self.search_frame)

        # 编辑器
        self.editor = TextEdit()
        self.editor.setFont(QFont("Consolas", 11))
        self._apply_editor_style()
        self.editor.textChanged.connect(self.on_text_changed)

        # 语法高亮（包含搜索高亮）
        self.highlighter = ConfigHighlighter(self.editor.document())

        layout.addWidget(self.editor, 1)

        # 状态栏
        status_layout = QHBoxLayout()
        self.status_label = CaptionLabel("就绪")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()

        self.line_label = CaptionLabel("行: 1, 列: 1")
        status_layout.addWidget(self.line_label)

        layout.addLayout(status_layout)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = PushButton("关闭")
        cancel_btn.clicked.connect(self.close)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        self.editor.cursorPositionChanged.connect(self.update_cursor_position)

    def setup_shortcuts(self):
        """设置快捷键"""
        self.search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.search_shortcut.activated.connect(self.show_search)

        self.escape_shortcut = QShortcut(QKeySequence("Escape"), self)
        self.escape_shortcut.activated.connect(self.on_escape_pressed)

        self.f3_shortcut = QShortcut(QKeySequence("F3"), self)
        self.f3_shortcut.activated.connect(self.find_next)

        self.shift_f3_shortcut = QShortcut(QKeySequence("Shift+F3"), self)
        self.shift_f3_shortcut.activated.connect(self.find_previous)

    def _apply_editor_style(self):
        """根据主题应用编辑器样式"""
        from qfluentwidgets import isDarkTheme
        if isDarkTheme():
            self.editor.setStyleSheet("""
                TextEdit {
                    background-color: #1e1e1e;
                    color: #d4d4d4;
                    border: 1px solid #3c3c3c;
                    border-radius: 4px;
                }
            """)
        else:
            self.editor.setStyleSheet("""
                TextEdit {
                    background-color: #fafafa;
                    border: 1px solid #ddd;
                    border-radius: 4px;
                }
            """)

    def show_search(self):
        """显示搜索栏"""
        self.search_frame.show()
        self.search_input.setFocus()
        self.search_input.selectAll()

    def hide_search(self):
        """隐藏搜索栏"""
        self.search_frame.hide()
        self.highlighter.set_search_text("")
        self._search_matches.clear()
        self._current_match_index = -1
        self._last_search_text = ""
        self.search_count_label.setText("")
        self.editor.setFocus()

    def on_escape_pressed(self):
        """ESC键处理"""
        if self.search_frame.isVisible():
            self.hide_search()
        else:
            self.close()

    def on_search_text_changed(self, text: str):
        """搜索文本变化 - 只清除高亮，不触发搜索"""
        if not text:
            self._search_matches.clear()
            self._current_match_index = -1
            self.highlighter.set_search_text("")
            self.search_count_label.setText("")

    def on_search_return_pressed(self):
        """按下回车键时执行搜索或跳转到下一个"""
        current_text = self.search_input.text()

        # 如果搜索文本没变且已有匹配结果，跳转到下一个
        if current_text == self._last_search_text and self._search_matches:
            self.find_next()
        else:
            # 文本变化了，执行新搜索
            self._do_search()

    def _do_search(self):
        """执行实际搜索"""
        text = self.search_input.text()
        self._last_search_text = text
        self._search_matches.clear()
        self._current_match_index = -1

        if not text:
            self.highlighter.set_search_text("")
            self.search_count_label.setText("")
            return

        # 先查找所有匹配位置（不触发高亮，避免卡顿）
        content = self.editor.toPlainText()
        lower_content = content.lower()
        lower_text = text.lower()
        pos = 0
        while True:
            idx = lower_content.find(lower_text, pos)
            if idx == -1:
                break
            cursor = QTextCursor(self.editor.document())
            cursor.setPosition(idx)
            cursor.setPosition(idx + len(text), QTextCursor.MoveMode.KeepAnchor)
            self._search_matches.append(cursor)
            pos = idx + len(text)

        # 最后再应用高亮
        self.highlighter.set_search_text(text)

        if self._search_matches:
            self._current_match_index = 0
            self._jump_to_match(0)
            self.search_count_label.setText(f"1/{len(self._search_matches)}")
        else:
            self.search_count_label.setText("0/0")

    def find_next(self):
        """查找下一个"""
        if not self._search_matches:
            return
        self._current_match_index = (self._current_match_index + 1) % len(self._search_matches)
        self._jump_to_match(self._current_match_index)
        self.search_count_label.setText(f"{self._current_match_index + 1}/{len(self._search_matches)}")

    def find_previous(self):
        """查找上一个"""
        if not self._search_matches:
            return
        self._current_match_index = (self._current_match_index - 1) % len(self._search_matches)
        self._jump_to_match(self._current_match_index)
        self.search_count_label.setText(f"{self._current_match_index + 1}/{len(self._search_matches)}")

    def _jump_to_match(self, index: int):
        """跳转到指定匹配"""
        if 0 <= index < len(self._search_matches):
            cursor = self._search_matches[index]
            self.editor.setTextCursor(cursor)
            self.editor.ensureCursorVisible()

    def load_config_list(self):
        """加载配置文件列表"""
        self.file_combo.clear()

        config_files = [
            ("PHP 配置 (php.ini)", "php/php.ini"),
            ("PHP-FPM 配置 (php-fpm.conf)", "php/php-fpm.conf"),
            ("PHP-FPM 池配置 (www.conf)", "php/www.conf"),
            ("Nginx 站点配置 (default.conf)", "nginx/default.conf"),
            ("Nginx 主配置 (nginx.conf)", "nginx/nginx.conf"),
            ("Docker Compose (docker-compose.yml)", "docker-compose.yml"),
            ("Dockerfile", "Dockerfile"),
        ]

        for name, rel_path in config_files:
            full_path = self.project_path / rel_path
            if full_path.exists():
                self.file_combo.addItem(name)
                self.file_combo.setItemData(self.file_combo.count() - 1, rel_path)

        if self.file_combo.count() > 0:
            self.file_combo.setCurrentIndex(0)
            # 手动加载第一个文件
            rel_path = self.file_combo.itemData(0)
            if rel_path:
                self.current_file = self.project_path / rel_path
                self.load_file()

    def _prompt_save_changes(self) -> bool:
        """提示保存更改，返回 True 表示继续操作，False 表示取消操作"""
        dialog = UnsavedChangesDialog(self)
        result = dialog.exec()

        if result == 1:  # 保存
            self.save_file()
            return True
        elif result == 2:  # 不保存
            return True
        else:  # 取消
            return False

    def on_file_selected(self, name: str):
        """选择文件"""
        if not name:
            return

        if self.has_unsaved_changes:
            if not self._prompt_save_changes():
                return  # 用户取消

        rel_path = self.file_combo.currentData()
        if rel_path:
            self.current_file = self.project_path / rel_path
            self.load_file()

    def load_file(self):
        """加载文件内容"""
        if not self.current_file or not self.current_file.exists():
            self.editor.clear()
            self._original_content = ""
            self._last_editor_content = ""
            self.save_btn.setEnabled(False)
            self.file_path_label.setText("文件不存在")
            return

        try:
            content = self.current_file.read_text(encoding='utf-8')
            self._original_content = content
            self._last_editor_content = content
            self.editor.setPlainText(content)
            self.has_unsaved_changes = False
            self.save_btn.setEnabled(False)
            self.file_path_label.setText(str(self.current_file))
            self.status_label.setText(f"已加载: {self.current_file.name}")
        except Exception as e:
            InfoBar.error(title="读取失败", content=f"无法读取文件: {e}", parent=self)
            self.editor.clear()
            self._original_content = ""
            self._last_editor_content = ""

    def on_text_changed(self):
        """文本变化"""
        current_content = self.editor.toPlainText()

        # 检测内容是否真的变化（光标移动等不会改变内容）
        if current_content != self._last_editor_content:
            # 内容真的变化了，清除搜索结果
            if self._search_matches:
                self._search_matches.clear()
                self._current_match_index = -1
                self._last_search_text = ""
                self.highlighter.set_search_text("")
                self.search_count_label.setText("")

        self._last_editor_content = current_content

        # 比较当前内容与原始内容
        self.has_unsaved_changes = (current_content != self._original_content)
        self.save_btn.setEnabled(self.has_unsaved_changes)

    def save_file(self):
        """保存文件"""
        if not self.current_file:
            return

        try:
            content = self.editor.toPlainText()
            self.current_file.write_text(content, encoding='utf-8')
            self._original_content = content  # 更新原始内容
            self._last_editor_content = content  # 更新内容快照
            self.has_unsaved_changes = False
            self.save_btn.setEnabled(False)
            self.status_label.setText(f"已保存: {self.current_file.name}")

            InfoBar.success(
                title="保存成功",
                content="配置文件已保存。如果修改了服务配置，请重启服务使之生效。",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )
        except Exception as e:
            InfoBar.error(title="保存失败", content=str(e), parent=self)

    def open_external_editor(self):
        """使用外部编辑器打开"""
        if not self.current_file:
            return

        if self.has_unsaved_changes:
            if not self._prompt_save_changes():
                return  # 用户取消

        try:
            import subprocess
            subprocess.Popen(["xdg-open", str(self.current_file)])
            self.status_label.setText("已在外部编辑器中打开")
        except Exception as e:
            InfoBar.error(title="错误", content=f"无法打开外部编辑器: {e}", parent=self)

    def update_cursor_position(self):
        """更新光标位置显示"""
        cursor = self.editor.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1
        self.line_label.setText(f"行: {line}, 列: {col}")

    def keyPressEvent(self, event):
        """键盘事件处理"""
        # Shift+Enter 在搜索框中查找上一个
        if self.search_frame.isVisible() and self.search_input.hasFocus():
            if event.key() == Qt.Key.Key_Return and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.find_previous()
                return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        """关闭事件"""
        if self.has_unsaved_changes:
            if not self._prompt_save_changes():
                event.ignore()
                return

        super().closeEvent(event)
