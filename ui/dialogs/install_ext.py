"""安装扩展对话框"""
import os
import html
from typing import List
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from pathlib import Path
import subprocess

from qfluentwidgets import (
    PushButton, PrimaryPushButton, PillPushButton, LineEdit, TextEdit,
    BodyLabel, CaptionLabel, CheckBox, IndeterminateProgressRing,
    CardWidget, StrongBodyLabel, FluentIcon as FIF,
    InfoBar, InfoBarPosition, MessageBox
)

from core.docker import DockerManager
from core.settings import Settings
from ui.styles import FluentDialog


class InstallExtWorker(QThread):
    """安装扩展工作线程"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str, list)  # success, message, logs

    def __init__(self, project_path: Path, extensions: List[str], proxy: str = None):
        super().__init__()
        self.project_path = project_path
        self.extensions = extensions
        self.proxy = proxy
        self.logs = []
        self._running = True
        self.process = None

    def run(self):
        self.logs = []
        try:
            # 安装扩展
            cmd = ["docker", "compose", "exec", "-u", "root", "php",
                   "install-php-extensions"] + self.extensions

            # 设置环境变量（包含代理）
            env = os.environ.copy()
            if self.proxy:
                env["http_proxy"] = self.proxy
                env["https_proxy"] = self.proxy
                env["HTTP_PROXY"] = self.proxy
                env["HTTPS_PROXY"] = self.proxy
                self.logs.append(f"使用代理: {self.proxy}")
                self.logs.append("")

            self.process = subprocess.Popen(
                cmd,
                cwd=str(self.project_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env
            )

            for line in self.process.stdout:
                if not self._running:
                    break
                stripped = line.rstrip()
                self.logs.append(stripped)
                self.progress.emit(stripped)

            self.process.wait()
            
            if not self._running:
                self.finished.emit(False, "安装已取消", self.logs)
                return

            if self.process.returncode == 0:
                # 重启 PHP 服务
                self.logs.append("")
                self.logs.append("=== 重启 PHP 服务 ===")
                restart_cmd = ["docker", "compose", "restart", "php"]
                result = subprocess.run(
                    restart_cmd,
                    cwd=str(self.project_path),
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if result.stdout:
                    self.logs.append(result.stdout.strip())
                if result.returncode == 0:
                    self.finished.emit(True, "扩展安装完成，服务已重启", self.logs)
                else:
                    self.finished.emit(True, "扩展安装完成，但重启服务失败", self.logs)
            else:
                self.finished.emit(False, "扩展安装失败", self.logs)
        except Exception as e:
            if self._running:
                self.logs.append(f"错误: {str(e)}")
                self.finished.emit(False, str(e), self.logs)

    def stop(self):
        self._running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()


class InstallExtDialog(FluentDialog):
    """安装扩展对话框"""

    def __init__(self, project_path: Path, project_name: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.project_name = project_name
        self.docker = DockerManager(project_path)
        self.settings = Settings()
        self.worker = None

        self.setWindowTitle(f"安装扩展 - {project_name}")
        self.setMinimumSize(600, 500)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # 说明
        info = CaptionLabel(
            "输入要安装的 PHP 扩展名称，多个扩展用空格分隔。\n"
            "例如: redis gd mongodb"
        )
        layout.addWidget(info)

        # 扩展输入
        self.ext_input = LineEdit()
        self.ext_input.setPlaceholderText("例如: redis gd mongodb")
        self.ext_input.setClearButtonEnabled(True)
        layout.addWidget(self.ext_input)

        # 常用扩展快捷按钮
        quick_layout = QHBoxLayout()
        quick_layout.addWidget(BodyLabel("常用:"))
        for ext in ["redis", "gd", "mongodb", "swoole", "xdebug"]:
            btn = PillPushButton(ext)
            btn.clicked.connect(lambda checked, e=ext: self.add_extension(e))
            quick_layout.addWidget(btn)
        quick_layout.addStretch()
        layout.addLayout(quick_layout)

        # 选项
        options_layout = QHBoxLayout()

        self.start_container_cb = CheckBox("如果容器未运行，自动启动")
        self.start_container_cb.setChecked(True)
        options_layout.addWidget(self.start_container_cb)

        # 使用设置中的代理
        self.use_proxy_cb = CheckBox("使用全局设置中的代理")
        proxy = self.settings.get_proxy()
        if proxy:
            self.use_proxy_cb.setText(f"使用全局代理 ({proxy})")
            self.use_proxy_cb.setChecked(True)
        else:
            self.use_proxy_cb.setText("使用全局代理 (未配置)")
            self.use_proxy_cb.setEnabled(False)
        options_layout.addWidget(self.use_proxy_cb)

        layout.addLayout(options_layout)

        # 日志显示区域
        log_label = BodyLabel("安装日志:")
        layout.addWidget(log_label)

        self.log_text = TextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            TextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.log_text, 1)

        # 进度环
        self.progress = IndeterminateProgressRing()
        self.progress.setVisible(False)
        layout.addWidget(self.progress, alignment=Qt.AlignmentFlag.AlignCenter)

        # 状态标签
        self.status_label = BodyLabel()
        layout.addWidget(self.status_label)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.close_btn = PushButton("关闭")
        self.close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.close_btn)

        self.install_btn = PrimaryPushButton(FIF.DOWNLOAD, "安装")
        self.install_btn.clicked.connect(self.install_extensions)
        self.install_btn.setDefault(True)
        btn_layout.addWidget(self.install_btn)

        layout.addLayout(btn_layout)

    def add_extension(self, ext: str):
        """添加扩展到输入框"""
        current = self.ext_input.text().strip()
        if current:
            if ext not in current.split():
                self.ext_input.setText(f"{current} {ext}")
        else:
            self.ext_input.setText(ext)

    def append_log(self, line: str):
        """追加日志行"""
        # 简单的颜色处理
        color = "#d4d4d4"
        lower_line = line.lower()
        if "error" in lower_line or "fatal" in lower_line or "failed" in lower_line:
            color = "#f44747"
        elif "warn" in lower_line:
            color = "#dcdcaa"
        elif "success" in lower_line or "installed" in lower_line:
            color = "#22c55e"
        elif "info" in lower_line:
            color = "#3794ff"

        # 转义 HTML 特殊字符
        escaped = html.escape(line)
        self.log_text.append(f'<span style="color: {color}">{escaped}</span>')

        # 自动滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def install_extensions(self):
        """安装扩展"""
        text = self.ext_input.text().strip()
        if not text:
            InfoBar.warning(
                title="提示",
                content="请输入要安装的扩展名称",
                orient=Qt.Orientation.Horizontal,
                parent=self
            )
            return

        extensions = text.split()
        if not extensions:
            return

        # 检查容器是否运行
        if not self.docker._run_command(["ps", "--status", "running", "-q"]).output.strip():
            if self.start_container_cb.isChecked():
                self.status_label.setText("正在启动容器...")
                result = self.docker.up()
                if not result.success:
                    InfoBar.error(
                        title="启动失败",
                        content=f"启动容器失败: {result.error}",
                        orient=Qt.Orientation.Horizontal,
                        parent=self
                    )
                    return
            else:
                InfoBar.warning(
                    title="容器未运行",
                    content="容器未运行，请先启动项目",
                    orient=Qt.Orientation.Horizontal,
                    parent=self
                )
                return

        # 获取代理设置
        proxy = None
        if self.use_proxy_cb.isChecked():
            proxy = self.settings.get_proxy()

        # 清空日志
        self.log_text.clear()
        self.append_log(f"=== 开始安装扩展: {' '.join(extensions)} ===")
        if proxy:
            self.append_log(f"使用代理: {proxy}")
        self.append_log("")

        # 开始安装
        self.install_btn.setEnabled(False)
        self.ext_input.setEnabled(False)
        self.progress.setVisible(True)
        self.status_label.setText("正在安装扩展...")

        self.worker = InstallExtWorker(self.project_path, extensions, proxy)
        self.worker.progress.connect(self.append_log)
        self.worker.finished.connect(self.on_install_finished)
        self.worker.start()

    def on_install_finished(self, success: bool, msg: str, logs: List[str]):
        """安装完成"""
        self.progress.setVisible(False)
        self.install_btn.setEnabled(True)
        self.ext_input.setEnabled(True)

        # 添加最终日志
        self.append_log("")
        if success:
            self.append_log(f"=== {msg} ===")
            self.status_label.setStyleSheet("color: #22c55e; font-weight: bold;")
            self.status_label.setText(f"✓ {msg}")

            InfoBar.success(
                title="安装成功",
                content=msg,
                orient=Qt.Orientation.Horizontal,
                parent=self.window()
            )
            self.accept()
        else:
            self.append_log(f"=== 失败: {msg} ===")
            self.status_label.setStyleSheet("color: #ef4444; font-weight: bold;")
            self.status_label.setText(f"✗ {msg}")

            # 显示失败的详细对提示
            InfoBar.error(
                title="安装失败",
                content=f"扩展安装失败: {msg}。请查看日志获取详细信息。",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=-1, # 永不自动关闭，除非手动
                parent=self
            )

    def closeEvent(self, event):
        """关闭事件"""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
        super().closeEvent(event)
