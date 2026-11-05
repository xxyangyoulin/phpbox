"""PHP 配置编辑对话框"""
import re
from pathlib import Path
from typing import Tuple
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QGridLayout
from PyQt6.QtCore import Qt, pyqtSignal

from qfluentwidgets import (
    PushButton, PrimaryPushButton, LineEdit, SpinBox,
    BodyLabel, CaptionLabel, ComboBox, EditableComboBox, CardWidget,
    StrongBodyLabel, FluentIcon as FIF, InfoBar, InfoBarPosition, MessageBox
)

from ui.worker import OperationWorker
from core.docker import DockerManager, DockerResult
from core.environment import EnvironmentManager, read_binding
from ui.styles import FluentDialog


# 常用时区列表
COMMON_TIMEZONES = [
    "Asia/Shanghai",
    "Asia/Hong_Kong",
    "Asia/Tokyo",
    "Asia/Seoul",
    "Asia/Singapore",
    "Asia/Taipei",
    "Asia/Dubai",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Moscow",
    "America/New_York",
    "America/Los_Angeles",
    "America/Chicago",
    "Australia/Sydney",
    "UTC",
]

# 可编辑的配置项（排除 xdebug_status 和 opcache_status）
EDITABLE_CONFIGS = [
    "memory_limit",
    "max_execution_time",
    "max_input_time",
    "upload_max_filesize",
    "post_max_size",
    "max_file_uploads",
    "display_errors",
    "error_reporting",
    "date.timezone",
]

# 配置项中文名
CONFIG_LABELS = {
    "memory_limit": "内存限制",
    "max_execution_time": "最大执行时间",
    "max_input_time": "最大输入时间",
    "upload_max_filesize": "上传文件大小",
    "post_max_size": "POST 大小",
    "max_file_uploads": "最大上传数量",
    "display_errors": "显示错误",
    "error_reporting": "错误报告",
    "date.timezone": "时区",
}


class PhpConfigDialog(FluentDialog):
    """PHP 配置编辑对话框"""

    config_applied = pyqtSignal()

    def __init__(self, project_path: Path, project_name: str, current_config: dict, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.project_name = project_name
        self.current_config = current_config
        self._notification_parent = parent.window() if parent else self
        self.docker = DockerManager(project_path)
        binding = read_binding(project_path)
        self.environment = EnvironmentManager().load(binding['environment_id']) if binding else None
        self.config_path = self.environment.path if self.environment else project_path

        self.setWindowTitle(f"编辑 PHP 配置 - {project_name}")
        self.setMinimumSize(500, 450)
        self.setup_ui()
        self.load_current_config()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        if self.environment:
            projects = EnvironmentManager().bindings(self.environment.id)
            scope = BodyLabel(f"PHP 环境：{self.environment.name}\n影响项目：" +
                              ('、'.join(path.name for path in projects) or '无'))
            scope.setWordWrap(True)
            layout.addWidget(scope)

        # 配置卡片
        config_card = CardWidget(self)
        config_layout = QVBoxLayout(config_card)
        config_layout.setSpacing(12)
        config_layout.setContentsMargins(20, 16, 20, 16)

        config_layout.addWidget(StrongBodyLabel("PHP 配置项"))

        # 配置网格
        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setColumnStretch(1, 1)

        self.inputs = {}

        # memory_limit - 文本输入（数字+单位）
        row = 0
        grid.addWidget(BodyLabel(f"{CONFIG_LABELS['memory_limit']}: "), row, 0)
        self.inputs["memory_limit"] = LineEdit()
        self.inputs["memory_limit"].setPlaceholderText("如: 256M, 1G")
        self.inputs["memory_limit"].setClearButtonEnabled(True)
        grid.addWidget(self.inputs["memory_limit"], row, 1)

        # max_execution_time - 数字输入
        row += 1
        grid.addWidget(BodyLabel(f"{CONFIG_LABELS['max_execution_time']}: "), row, 0)
        exec_layout = QHBoxLayout()
        self.inputs["max_execution_time"] = SpinBox()
        self.inputs["max_execution_time"].setRange(0, 86400)
        self.inputs["max_execution_time"].setValue(30)
        exec_layout.addWidget(self.inputs["max_execution_time"])
        exec_layout.addWidget(CaptionLabel("秒 (0=无限制)"))
        exec_layout.addStretch()
        grid.addLayout(exec_layout, row, 1)

        # max_input_time - 数字输入
        row += 1
        grid.addWidget(BodyLabel(f"{CONFIG_LABELS['max_input_time']}: "), row, 0)
        input_layout = QHBoxLayout()
        self.inputs["max_input_time"] = SpinBox()
        self.inputs["max_input_time"].setRange(-1, 86400)
        self.inputs["max_input_time"].setValue(60)
        input_layout.addWidget(self.inputs["max_input_time"])
        input_layout.addWidget(CaptionLabel("秒 (-1=无限制)"))
        input_layout.addStretch()
        grid.addLayout(input_layout, row, 1)

        # upload_max_filesize - 文本输入
        row += 1
        grid.addWidget(BodyLabel(f"{CONFIG_LABELS['upload_max_filesize']}: "), row, 0)
        self.inputs["upload_max_filesize"] = LineEdit()
        self.inputs["upload_max_filesize"].setPlaceholderText("如: 10M, 100M")
        self.inputs["upload_max_filesize"].setClearButtonEnabled(True)
        grid.addWidget(self.inputs["upload_max_filesize"], row, 1)

        # post_max_size - 文本输入
        row += 1
        grid.addWidget(BodyLabel(f"{CONFIG_LABELS['post_max_size']}: "), row, 0)
        self.inputs["post_max_size"] = LineEdit()
        self.inputs["post_max_size"].setPlaceholderText("如: 20M, 200M")
        self.inputs["post_max_size"].setClearButtonEnabled(True)
        grid.addWidget(self.inputs["post_max_size"], row, 1)

        # max_file_uploads - 数字输入
        row += 1
        grid.addWidget(BodyLabel(f"{CONFIG_LABELS['max_file_uploads']}: "), row, 0)
        uploads_layout = QHBoxLayout()
        self.inputs["max_file_uploads"] = SpinBox()
        self.inputs["max_file_uploads"].setRange(1, 1000)
        self.inputs["max_file_uploads"].setValue(20)
        uploads_layout.addWidget(self.inputs["max_file_uploads"])
        uploads_layout.addWidget(CaptionLabel("个"))
        uploads_layout.addStretch()
        grid.addLayout(uploads_layout, row, 1)

        # display_errors - 下拉选择
        row += 1
        grid.addWidget(BodyLabel(f"{CONFIG_LABELS['display_errors']}: "), row, 0)
        self.inputs["display_errors"] = ComboBox()
        self.inputs["display_errors"].addItems(["On", "Off"])
        grid.addWidget(self.inputs["display_errors"], row, 1)

        # error_reporting - 文本输入
        row += 1
        grid.addWidget(BodyLabel(f"{CONFIG_LABELS['error_reporting']}: "), row, 0)
        self.inputs["error_reporting"] = LineEdit()
        self.inputs["error_reporting"].setPlaceholderText("如: E_ALL, E_ALL & ~E_NOTICE")
        self.inputs["error_reporting"].setClearButtonEnabled(True)
        grid.addWidget(self.inputs["error_reporting"], row, 1)

        # date.timezone - 可编辑下拉
        row += 1
        grid.addWidget(BodyLabel(f"{CONFIG_LABELS['date.timezone']}: "), row, 0)
        self.inputs["date.timezone"] = EditableComboBox()
        self.inputs["date.timezone"].addItems(COMMON_TIMEZONES)
        grid.addWidget(self.inputs["date.timezone"], row, 1)

        config_layout.addLayout(grid)
        layout.addWidget(config_card)

        # 提示信息
        hint = CaptionLabel(
            "提示：修改配置后会自动重启 PHP 服务使配置生效。\n"
            "POST 大小应大于或等于上传文件大小。"
        )
        hint.setStyleSheet("color: #64748b;")
        layout.addWidget(hint)

        layout.addStretch()

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = PushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        self.save_btn = PrimaryPushButton(FIF.SAVE, "保存并应用" if self.environment else "保存并重启 PHP")
        self.save_btn.clicked.connect(self.save_config)
        self.save_btn.setDefault(True)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)

    def load_current_config(self):
        """加载当前配置"""
        # memory_limit
        val = self.current_config.get("memory_limit", "128M")
        self.inputs["memory_limit"].setText(val)

        # max_execution_time
        val = self.current_config.get("max_execution_time", "30")
        try:
            self.inputs["max_execution_time"].setValue(int(val))
        except ValueError:
            self.inputs["max_execution_time"].setValue(30)

        # max_input_time
        val = self.current_config.get("max_input_time", "60")
        try:
            self.inputs["max_input_time"].setValue(int(val))
        except ValueError:
            self.inputs["max_input_time"].setValue(60)

        # upload_max_filesize
        val = self.current_config.get("upload_max_filesize", "2M")
        self.inputs["upload_max_filesize"].setText(val)

        # post_max_size
        val = self.current_config.get("post_max_size", "8M")
        self.inputs["post_max_size"].setText(val)

        # max_file_uploads
        val = self.current_config.get("max_file_uploads", "20")
        try:
            self.inputs["max_file_uploads"].setValue(int(val))
        except ValueError:
            self.inputs["max_file_uploads"].setValue(20)

        # display_errors
        val = self.current_config.get("display_errors", "On")
        index = 0 if val.lower() == "on" else 1
        self.inputs["display_errors"].setCurrentIndex(index)

        # error_reporting
        val = self.current_config.get("error_reporting", "E_ALL")
        self.inputs["error_reporting"].setText(val)

        # date.timezone
        val = self.current_config.get("date.timezone", "UTC")
        combo = self.inputs["date.timezone"]
        index = combo.findText(val)
        if index >= 0:
            combo.setCurrentIndex(index)
        else:
            combo.setCurrentText(val)

    def validate_input(self) -> Tuple[bool, str]:
        """验证输入

        Returns:
            tuple: (是否有效, 错误消息)
        """
        # 验证大小格式（memory_limit, upload_max_filesize, post_max_size）
        size_pattern = re.compile(r'^\d+[KMGkmg]?$')

        for key in ["memory_limit", "upload_max_filesize", "post_max_size"]:
            value = self.inputs[key].text().strip()
            if not value:
                return False, f"{CONFIG_LABELS[key]} 不能为空"
            if key == "memory_limit" and value == "-1":
                continue
            if not size_pattern.fullmatch(value):
                return False, f"{CONFIG_LABELS[key]} 格式无效，应为数字或数字+单位(如 256M, 1G)"

        # 验证 post_max_size >= upload_max_filesize
        upload_size = self._parse_size(self.inputs["upload_max_filesize"].text().strip())
        post_size = self._parse_size(self.inputs["post_max_size"].text().strip())
        if post_size != 0 and post_size < upload_size:
            return False, "POST 大小应大于或等于上传文件大小"

        # 验证 error_reporting 格式（基本验证）
        error_rep = self.inputs["error_reporting"].text().strip()
        constants = {"E_ERROR", "E_WARNING", "E_PARSE", "E_NOTICE", "E_CORE_ERROR", "E_CORE_WARNING",
                     "E_COMPILE_ERROR", "E_COMPILE_WARNING", "E_USER_ERROR", "E_USER_WARNING", "E_USER_NOTICE",
                     "E_STRICT", "E_RECOVERABLE_ERROR", "E_DEPRECATED", "E_USER_DEPRECATED", "E_ALL"}
        import ast
        try:
            tree = ast.parse(error_rep, mode="eval")
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    if node.id not in constants:
                        raise ValueError()
                elif isinstance(node, ast.Constant):
                    if type(node.value) is not int or node.value < 0:
                        raise ValueError()
                elif not isinstance(node, (ast.Expression, ast.Load, ast.BinOp, ast.UnaryOp,
                                          ast.BitAnd, ast.BitOr, ast.BitXor, ast.Invert)):
                    raise ValueError()
        except (SyntaxError, ValueError):
            return False, "错误报告格式无效，应为 E_ 常量表达式或非负整数"

        return True, ""

    def _parse_size(self, size_str: str) -> int:
        """解析大小字符串为字节数"""
        size_str = size_str.strip().upper()
        if not size_str:
            return 0

        multipliers = {'K': 1024, 'M': 1024**2, 'G': 1024**3}

        match = re.match(r'^(\d+)([KMG])?$', size_str)
        if match:
            num = int(match.group(1))
            unit = match.group(2)
            if unit:
                return num * multipliers[unit]
            return num
        return 0

    def save_config(self):
        """保存配置"""
        # 验证输入
        valid, error_msg = self.validate_input()
        if not valid:
            InfoBar.error(
                title="验证失败",
                content=error_msg,
                orient=Qt.Orientation.Horizontal,
                parent=self
            )
            return

        php_ini = self.config_path / "php" / "php.ini"
        if not php_ini.exists():
            InfoBar.error(
                title="错误",
                content="找不到 php.ini 文件",
                parent=self
            )
            return

        content = php_ini.read_text()

        # 获取输入值
        new_values = {
            "memory_limit": self.inputs["memory_limit"].text().strip(),
            "max_execution_time": str(self.inputs["max_execution_time"].value()),
            "max_input_time": str(self.inputs["max_input_time"].value()),
            "upload_max_filesize": self.inputs["upload_max_filesize"].text().strip(),
            "post_max_size": self.inputs["post_max_size"].text().strip(),
            "max_file_uploads": str(self.inputs["max_file_uploads"].value()),
            "display_errors": self.inputs["display_errors"].currentText(),
            "error_reporting": self.inputs["error_reporting"].text().strip(),
            "date.timezone": self.inputs["date.timezone"].currentText().strip(),
        }

        # 更新配置项
        for key, value in new_values.items():
            # 匹配配置行（可能有注释前导分号）
            pattern = rf'^({key}\s*=\s*).*'
            replacement = rf'{key} = {value}'

            lines = content.split('\n')
            found = False
            for i, line in enumerate(lines):
                if re.match(pattern, line.strip()):
                    lines[i] = replacement
                    found = True
                    break

            # 如果没找到，在文件末尾添加
            if not found:
                lines.append(f"{key} = {value}")

            content = '\n'.join(lines)

        if self.environment:
            projects = EnvironmentManager().bindings(self.environment.id)
            if not MessageBox('应用 PHP 环境配置', f'将更新 PHP 环境「{self.environment.name}」，运行中的环境将重启。\n影响项目：' +
                              ('、'.join(path.name for path in projects) or '无') +
                              '\n正在执行的任务会阻止操作。', self).exec():
                return
            def operation():
                manager = EnvironmentManager()
                environment = manager.load(self.environment.id)
                manager.update(environment, environment.extensions, environment.proxy, content)
                return DockerResult(True)
        else:
            php_ini.write_text(content)
            def operation():
                result = self.docker.restart_service("php")
                if not result.success:
                    raise RuntimeError(result.error)
                return result

        self.save_btn.setEnabled(False)
        self.operation_worker = OperationWorker(operation)
        self.operation_worker.succeeded.connect(self._on_restarted)
        self.operation_worker.failed.connect(self._on_restart_failed)
        if hasattr(self._notification_parent, 'operations_page'):
            self._notification_parent.operations_page.track(
                self.operation_worker, self.project_name + ' · 应用 PHP 配置', str(self.config_path), dialog=self
            )
        self.operation_worker.start()
        self.accept()
        InfoBar.info(title="正在应用 PHP 配置", content="PHP 服务将在后台更新，完成后会通知你。",
                     parent=self._notification_parent)

    def _on_restart_failed(self, message):
        self.save_btn.setEnabled(True)
        if self.environment:
            InfoBar.error(title="环境配置应用失败", content=message, parent=self._notification_parent)
        else:
            InfoBar.warning(title="配置已保存，但重启失败", content=message, parent=self._notification_parent)

    def _on_restarted(self, result):
        self.save_btn.setEnabled(True)
        self.config_applied.emit()
        InfoBar.success(
            title="成功",
            content="PHP 环境配置已应用" if self.environment else "配置已更新，PHP 服务已重启",
            orient=Qt.Orientation.Horizontal,
            parent=self._notification_parent
        )
