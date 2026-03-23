"""重建镜像对话框"""
import html
import os
import subprocess
from pathlib import Path
from typing import List

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout

from qfluentwidgets import (
    BodyLabel, CaptionLabel, CheckBox, FluentIcon as FIF, InfoBar,
    IndeterminateProgressRing, PrimaryPushButton, PushButton, TextEdit
)

from core.docker import DockerManager
from core.proxy import convert_proxy_for_docker
from core.settings import Settings
from ui.styles import FluentDialog, themed_color


class RebuildImageWorker(QThread):
    """重建镜像工作线程"""

    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str, list)

    def __init__(self, project_path: Path, proxy: str = None):
        super().__init__()
        self.project_path = project_path
        self.proxy = proxy
        self.logs: List[str] = []
        self._running = True
        self.process = None

    def run(self):
        self.logs = []
        try:
            docker = DockerManager(self.project_path)
            compose_cmd = docker.get_compose_command()
            if not compose_cmd:
                self.finished.emit(False, "未检测到 docker compose 或 docker-compose", self.logs)
                return

            env = os.environ.copy()
            if self.proxy:
                env["http_proxy"] = self.proxy
                env["https_proxy"] = self.proxy
                env["HTTP_PROXY"] = self.proxy
                env["HTTPS_PROXY"] = self.proxy
                self._emit_log(f"使用代理: {self.proxy}")
                self._emit_log("")

            if not self._stream_command(
                compose_cmd + ["build", "--no-cache"],
                env,
                "=== 开始重建镜像 ==="
            ):
                return

            if not self._stream_command(
                compose_cmd + ["up", "-d", "--force-recreate"],
                env,
                "=== 正在重建并启动容器 ==="
            ):
                return

            self.finished.emit(True, "镜像重建完成，容器已重新创建", self.logs)
        except Exception as e:
            if self._running:
                self._emit_log(f"错误: {str(e)}")
                self.finished.emit(False, str(e), self.logs)

    def _stream_command(self, cmd: List[str], env: dict, title: str) -> bool:
        self._emit_log(title)
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
            self._emit_log(line.rstrip())

        self.process.wait()
        return_code = self.process.returncode
        self.process = None

        if not self._running:
            self.finished.emit(False, "重建已取消", self.logs)
            return False

        if return_code != 0:
            self.finished.emit(False, "重建失败", self.logs)
            return False

        self._emit_log("")
        return True

    def _emit_log(self, line: str):
        self.logs.append(line)
        self.progress.emit(line)

    def stop(self):
        self._running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()


class RebuildImageDialog(FluentDialog):
    """重建镜像对话框"""

    rebuild_finished = pyqtSignal()

    def __init__(self, project_path: Path, project_name: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.project_name = project_name
        self.settings = Settings()
        self.worker = None

        self.setWindowTitle(f"重建镜像 - {project_name}")
        self.setMinimumSize(640, 520)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        info = CaptionLabel(
            "将执行无缓存重建，并重新创建当前项目容器。\n"
            "适用于更新 Dockerfile、清理旧代理环境变量或刷新基础环境。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        options_layout = QHBoxLayout()
        self.use_proxy_cb = CheckBox("使用全局设置中的代理")
        proxy = self.settings.get_proxy()
        if proxy:
            self.use_proxy_cb.setText(f"使用全局代理 ({proxy})")
            self.use_proxy_cb.setChecked(True)
        else:
            self.use_proxy_cb.setText("使用全局代理 (未配置)")
            self.use_proxy_cb.setEnabled(False)
        options_layout.addWidget(self.use_proxy_cb)
        options_layout.addStretch(1)
        layout.addLayout(options_layout)

        layout.addWidget(BodyLabel("重建日志:"))
        self.log_text = TextEdit()
        self.log_text.setReadOnly(True)
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

        self.progress = IndeterminateProgressRing()
        self.progress.setVisible(False)
        layout.addWidget(self.progress, alignment=Qt.AlignmentFlag.AlignCenter)

        self.status_label = BodyLabel()
        layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.close_btn = PushButton("关闭")
        self.close_btn.clicked.connect(self._on_close)
        btn_layout.addWidget(self.close_btn)

        self.rebuild_btn = PrimaryPushButton(FIF.SYNC, "重建镜像")
        self.rebuild_btn.clicked.connect(self.rebuild_image)
        btn_layout.addWidget(self.rebuild_btn)
        layout.addLayout(btn_layout)

    def append_log(self, line: str):
        color = "#d4d4d4"
        lower = line.lower()
        if "error" in lower or "failed" in lower or "fatal" in lower:
            color = "#f44747"
        elif "warn" in lower:
            color = "#dcdcaa"
        elif "done" in lower or "success" in lower or "started" in lower:
            color = "#22c55e"
        elif line.startswith("==="):
            color = "#3794ff"

        self.log_text.append(f'<span style="color: {color}">{html.escape(line)}</span>')
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def rebuild_image(self):
        self.log_text.clear()
        self.status_label.setStyleSheet("")
        self.status_label.setText("正在重建镜像...")
        self.rebuild_btn.setEnabled(False)
        self.progress.setVisible(True)

        proxy = None
        if self.use_proxy_cb.isChecked():
            raw_proxy = self.settings.get_proxy()
            if raw_proxy:
                proxy = convert_proxy_for_docker(raw_proxy)

        self.worker = RebuildImageWorker(self.project_path, proxy)
        self.worker.progress.connect(self.append_log)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_finished(self, success: bool, message: str, logs: List[str]):
        self.progress.setVisible(False)
        self.rebuild_btn.setEnabled(True)
        self.append_log("")
        if success:
            self.append_log(f"=== {message} ===")
            self.status_label.setStyleSheet("color: #22c55e; font-weight: bold;")
            self.status_label.setText(f"✓ {message}")
            self.rebuild_finished.emit()
            InfoBar.success(
                title="重建成功",
                content=message,
                orient=Qt.Orientation.Horizontal,
                parent=self.window()
            )
        else:
            self.append_log(f"=== 失败: {message} ===")
            self.status_label.setStyleSheet("color: #ef4444; font-weight: bold;")
            self.status_label.setText(f"✗ {message}")
            InfoBar.error(
                title="重建失败",
                content=f"{message}。请查看日志获取详细信息。",
                orient=Qt.Orientation.Horizontal,
                parent=self
            )

    def _on_close(self):
        if self.worker and self.worker.isRunning():
            self.status_label.setText("正在取消重建...")
            self.worker.stop()
            self.worker.wait()
        self.reject()
