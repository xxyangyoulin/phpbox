"""Xdebug 配置对话框"""
from pathlib import Path
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout
from PyQt6.QtCore import Qt

from qfluentwidgets import (
    PushButton, PrimaryPushButton, LineEdit, SpinBox,
    BodyLabel, CaptionLabel, CheckBox, CardWidget,
    StrongBodyLabel, FluentIcon as FIF, InfoBar, InfoBarPosition, MessageBox
)

from core.docker import DockerManager
from ui.styles import FluentDialog


class XdebugDialog(FluentDialog):
    """Xdebug 配置对话框"""

    def __init__(self, project_path: Path, project_name: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.project_name = project_name
        self.docker = DockerManager(project_path)

        self.setWindowTitle(f"Xdebug 配置 - {project_name}")
        self.setMinimumSize(450, 300)
        self.setup_ui()
        self.load_current_config()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # 启用开关
        self.enable_cb = CheckBox("启用 Xdebug")
        self.enable_cb.stateChanged.connect(self.on_enable_changed)
        layout.addWidget(self.enable_cb)

        # 配置卡片
        self.config_card = CardWidget(self)
        config_layout = QVBoxLayout(self.config_card)
        config_layout.setSpacing(12)

        config_layout.addWidget(StrongBodyLabel("调试配置"))

        # IDE Key
        ide_layout = QHBoxLayout()
        ide_layout.addWidget(BodyLabel("IDE Key:"))
        self.ide_key_input = LineEdit()
        self.ide_key_input.setPlaceholderText("IDE Key (如: PHPSTORM)")
        self.ide_key_input.setClearButtonEnabled(True)
        ide_layout.addWidget(self.ide_key_input, 1)
        config_layout.addLayout(ide_layout)

        # 调试端口
        port_layout = QHBoxLayout()
        port_layout.addWidget(BodyLabel("调试端口:"))
        self.port_spin = SpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(9003)
        port_layout.addWidget(self.port_spin)
        port_layout.addStretch()
        config_layout.addLayout(port_layout)

        # 远程主机
        host_layout = QHBoxLayout()
        host_layout.addWidget(BodyLabel("远程主机:"))
        self.host_input = LineEdit()
        self.host_input.setPlaceholderText("留空则自动检测")
        self.host_input.setClearButtonEnabled(True)
        host_layout.addWidget(self.host_input, 1)
        config_layout.addLayout(host_layout)

        layout.addWidget(self.config_card)

        # 说明
        hint = CaptionLabel(
            "提示：启用后需要在 IDE 中配置 Xdebug 监听\n"
            "VS Code: 安装 PHP Debug 扩展\n"
            "PhpStorm: Settings > PHP > Debug > Xdebug"
        )
        layout.addWidget(hint)

        layout.addStretch()

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = PushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = PrimaryPushButton(FIF.SAVE, "保存并重启 PHP")
        save_btn.clicked.connect(self.save_config)
        save_btn.setDefault(True)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    def on_enable_changed(self, state):
        """启用状态改变"""
        enabled = state == Qt.CheckState.Checked.value
        self.config_card.setEnabled(enabled)

    def load_current_config(self):
        """加载当前配置"""
        php_ini = self.project_path / "php" / "php.ini"
        if not php_ini.exists():
            return

        content = php_ini.read_text()

        # 检查 xdebug 是否启用
        if "xdebug.mode=debug" in content or "zend_extension=xdebug" in content:
            self.enable_cb.setChecked(True)
        else:
            self.enable_cb.setChecked(False)
            self.config_card.setEnabled(False)

        # 解析配置
        import re
        ide_match = re.search(r'xdebug\.ide_key\s*=\s*(\S+)', content)
        if ide_match:
            self.ide_key_input.setText(ide_match.group(1))
        else:
            self.ide_key_input.setText("PHPSTORM")

        port_match = re.search(r'xdebug\.client_port\s*=\s*(\d+)', content)
        if port_match:
            self.port_spin.setValue(int(port_match.group(1)))

        host_match = re.search(r'xdebug\.client_host\s*=\s*(\S+)', content)
        if host_match:
            self.host_input.setText(host_match.group(1))

    def save_config(self):
        """保存配置"""
        php_ini = self.project_path / "php" / "php.ini"
        if not php_ini.exists():
            InfoBar.error(
                title="错误",
                content="找不到 php.ini 文件",
                parent=self
            )
            return

        content = php_ini.read_text()

        # 获取 Docker 网关地址
        docker_host = self.host_input.text().strip() or self.get_docker_gateway()

        # 移除旧的 xdebug 配置
        import re
        content = re.sub(r'\n?;?\s*zend_extension\s*=.*xdebug.*', '', content)
        content = re.sub(r'\n?;?\s*xdebug\.[a-z_]+\s*=.*', '', content)

        # 生成新配置
        if self.enable_cb.isChecked():
            xdebug_config = f"""

; Xdebug 配置
zend_extension=xdebug
xdebug.mode=debug
xdebug.ide_key={self.ide_key_input.text() or 'PHPSTORM'}
xdebug.client_host={docker_host}
xdebug.client_port={self.port_spin.value()}
xdebug.start_with_request=trigger
"""

            # 在文件末尾添加
            content = content.rstrip() + xdebug_config

        # 写入文件
        php_ini.write_text(content)

        # 重启 PHP 服务
        result = self.docker.restart_service("php")
        if result.success:
            status = "启用" if self.enable_cb.isChecked() else "禁用"
            InfoBar.success(
                title="成功",
                content=f"Xdebug 已{status}，PHP 服务已重启",
                orient=Qt.Orientation.Horizontal,
                parent=self.window()
            )
            self.accept()
        else:
            InfoBar.warning(
                title="警告",
                content=f"配置已保存但重启失败: {result.error}",
                parent=self.window()
            )

    def get_docker_gateway(self) -> str:
        """获取 Docker 网关地址"""
        import subprocess
        try:
            compose_cmd = self.docker.get_compose_command()
            if not compose_cmd:
                return "host.docker.internal"
            result = subprocess.run(
                compose_cmd + ["exec", "php", "ip", "route"],
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
                timeout=10
            )
            for line in result.stdout.splitlines():
                if "default via" in line:
                    return line.split()[2]
        except Exception:
            pass
        return "host.docker.internal"
