"""安装扩展对话框"""
import os
import threading
import uuid
import html
from typing import List, Optional
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from pathlib import Path

from qfluentwidgets import (
    PushButton, PrimaryPushButton, PillPushButton, LineEdit, TextEdit,
    BodyLabel, CaptionLabel, CheckBox, IndeterminateProgressRing,
    CardWidget, StrongBodyLabel, FluentIcon as FIF,
    InfoBar, InfoBarPosition, MessageBox
)

from core.process import run_process
from ui.worker import register_worker
from core.docker import DockerManager
from core.settings import Settings
from core.proxy import convert_proxy_for_docker
from ui.styles import FluentDialog, themed_color


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
        self.run_id = uuid.uuid4().hex
        self.cancel_event = threading.Event()
        register_worker(self, f"{project_path.name} · 安装扩展")

    def run(self):
        self.logs = []
        try:
            docker = DockerManager(self.project_path)
            compose_cmd = docker.get_compose_command()
            if not compose_cmd:
                self.finished.emit(False, "未检测到 docker compose 或 docker-compose", self.logs)
                return
            # 显式将代理环境变量注入容器内的安装进程
            exec_args = ["exec", "-T"]
            if self.proxy:
                exec_args.extend([
                    "-e", f"http_proxy={self.proxy}",
                    "-e", f"https_proxy={self.proxy}",
                    "-e", f"HTTP_PROXY={self.proxy}",
                    "-e", f"HTTPS_PROXY={self.proxy}",
                ])

            # 安装扩展
            pid_file = f"/tmp/phpbox-install-{self.run_id}"
            cmd = compose_cmd + exec_args + ["-u", "root", "php", "setsid", "sh", "-c",
                'file="$1"; shift; echo $$ > "$file.pid"; [ ! -f "$file.cancel" ] || exit 130; exec "$@"',
                "sh", pid_file, "install-php-extensions"] + self.extensions

            # 设置环境变量（包含代理）
            env = os.environ.copy()
            if self.proxy:
                env["http_proxy"] = self.proxy
                env["https_proxy"] = self.proxy
                env["HTTP_PROXY"] = self.proxy
                env["HTTPS_PROXY"] = self.proxy
                self.logs.append(f"使用代理: {self.proxy}")
                self.logs.append("")

            result = run_process(cmd, cwd=str(self.project_path), env=env,
                                 cancel=self.cancel_event, on_output=self.progress.emit, timeout=3600)
            if result.returncode == 0:
                # 重启 PHP 服务
                self.logs.append("")
                self.logs.append("=== 重启 PHP 服务 ===")
                restart_cmd = compose_cmd + ["restart", "php"]
                result = run_process(restart_cmd, cwd=str(self.project_path), cancel=self.cancel_event, timeout=60)
                if result.stdout:
                    self.logs.append(result.stdout.strip())
                if result.returncode == 0:
                    self.finished.emit(True, "扩展安装完成，服务已重启", self.logs)
                else:
                    self.finished.emit(True, "扩展安装完成，但重启服务失败", self.logs)
            else:
                self.finished.emit(False, "扩展安装失败", self.logs)
        except Exception as e:
            if isinstance(e, (InterruptedError, TimeoutError)):
                try:
                    result = run_process(compose_cmd + ["exec", "-T", "-u", "root", "php", "sh", "-c",
                        'touch "$1.cancel"; if [ -f "$1.pid" ]; then /bin/kill -TERM -- "-$(cat "$1.pid")"; fi',
                        "sh", f"/tmp/phpbox-install-{self.run_id}"], cwd=str(self.project_path), timeout=15)
                    if result.returncode:
                        raise RuntimeError(result.stdout)
                except Exception as cleanup_error:
                    e = RuntimeError(f"{e}；容器内安装进程终止失败：{cleanup_error}")
            self.finished.emit(False, str(e), self.logs)

    def stop(self):
        self.cancel_event.set()


class InstallExtDialog(FluentDialog):
    """安装扩展对话框"""

    def __init__(self, project_path: Path, project_name: str, parent=None, initial_extensions: Optional[List[str]] = None):
        super().__init__(parent)
        self.project_path = project_path
        self.project_name = project_name
        self.docker = DockerManager(project_path)
        self.settings = Settings()
        self.worker = None
        self.initial_extensions = initial_extensions or []

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
        if self.initial_extensions:
            self.ext_input.setText(" ".join(self.initial_extensions))
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
        self.log_text.document().setMaximumBlockCount(2000)
        self.log_text.setStyleSheet(f"""
            TextEdit {{
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
                border: 1px solid {themed_color('#ddd', '#3c3c3c')};
                border-radius: 4px;
            }}
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
        background_btn = PushButton("转到后台")
        background_btn.clicked.connect(self.hide)
        btn_layout.addWidget(background_btn)
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
            if proxy:
                proxy = convert_proxy_for_docker(proxy)

        # 清空日志
        self.log_text.clear()
        self.append_log(f"=== 开始安装扩展: {' '.join(extensions)} ===")
        if proxy:
            self.append_log(f"使用代理: {proxy}")
        self.append_log("")

        # 开始安装
        self.install_btn.setEnabled(False)
        self.close_btn.setText("取消操作")
        self.ext_input.setEnabled(False)
        self.progress.setVisible(True)
        self.status_label.setText("正在安装扩展...")

        self._pending_extensions = extensions
        self.worker = InstallExtWorker(self.project_path, extensions, proxy)
        self.worker.progress.connect(self.append_log)
        self.worker.finished.connect(self.on_install_finished)
        self.worker.start()

    def on_install_finished(self, success: bool, msg: str, logs: List[str]):
        """安装完成"""
        self.progress.setVisible(False)
        self.install_btn.setEnabled(True)
        self.close_btn.setText("关闭")
        self.ext_input.setEnabled(True)

        # 添加最终日志
        self.append_log("")
        if success:
            self.append_log(f"=== {msg} ===")
            self.status_label.setStyleSheet("color: #22c55e; font-weight: bold;")
            self.status_label.setText(f"✓ {msg}")

            self._persist_extensions_to_dockerfile()

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

    def _persist_extensions_to_dockerfile(self):
        """将新安装的扩展追加到 Dockerfile，使重建时保留"""
        dockerfile = self.project_path / "Dockerfile"
        if not dockerfile.exists() or not self._pending_extensions:
            return
        try:
            content = dockerfile.read_text()
            import re
            # 查找最后一行 RUN install-php-extensions ... 并追加新扩展
            pattern = r'(RUN install-php-extensions .+)'
            matches = list(re.finditer(pattern, content))
            if matches:
                last_match = matches[-1]
                existing_exts = last_match.group(1).split()[2:]  # skip "RUN install-php-extensions"
                new_exts = [e for e in self._pending_extensions if e not in existing_exts]
                if new_exts:
                    new_line = last_match.group(1) + " " + " ".join(new_exts)
                    content = content[:last_match.start()] + new_line + content[last_match.end():]
                    dockerfile.write_text(content)
            else:
                # 没有已有的 install-php-extensions 行，在末尾追加
                ext_line = f"\nRUN install-php-extensions {' '.join(self._pending_extensions)}\n"
                content += ext_line
                dockerfile.write_text(content)
        except Exception as e:
            print(f"持久化扩展到 Dockerfile 失败: {e}")

    def closeEvent(self, event):
        self.hide()
        event.ignore()
