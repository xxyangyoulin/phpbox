"""全局定时任务中心"""
import os
import subprocess
from typing import List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QHeaderView, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget
)

from qfluentwidgets import (
    BodyLabel, CaptionLabel, CardWidget, CheckBox, ComboBox, FluentIcon as FIF,
    IconWidget, InfoBar, LineEdit, MessageBox, PrimaryPushButton, PushButton,
    StrongBodyLabel, TextEdit, ToolButton
)

from core.docker import DockerManager
from core.project import Project
from core.tasks import PRESET_SCHEDULES, TaskDefinition, TaskManager, now_iso
from core.settings import Settings
from ui.dialogs.build_progress import BuildProgressDialog
from ui.styles import FluentDialog, themed_color


class TaskRuntimeWorker(QThread):
    """后台执行 cron 运行时初始化/立即执行，避免阻塞 UI"""

    task_finished = pyqtSignal(str, bool, str, str)  # action, success, message, project_name
    build_required = pyqtSignal(str)
    log_line = pyqtSignal(str)

    def __init__(self, projects: List[Project], project_name: str,
                 action: str, task_id: str = "", build_if_needed: bool = False):
        super().__init__()
        self.projects = projects
        self.project_name = project_name
        self.action = action
        self.task_id = task_id
        self.build_if_needed = build_if_needed
        self.process = None

    def run(self):
        manager = TaskManager(self.projects)
        project = manager.get_project(self.project_name)
        if not project:
            self.task_finished.emit(self.action, False, "项目不存在", self.project_name)
            return

        changes = manager.ensure_project_runtime(project)
        docker = DockerManager(project.path)
        if not docker.has_service("cron"):
            self.task_finished.emit(self.action, False, "cron 服务未写入 docker-compose.yml", self.project_name)
            return

        proxy = Settings().get_proxy()
        build = self.build_if_needed or changes["dockerfile_changed"] or changes["compose_changed"]
        if build:
            self.build_required.emit(project.name)
            start_ok, start_message = self._stream_start_cron(docker, proxy)
            if not start_ok:
                self.task_finished.emit(self.action, False, start_message, self.project_name)
                return
        else:
            start_result = docker.start_service("cron", build=False, proxy=proxy)
            if not start_result.success:
                self.task_finished.emit(self.action, False, start_result.error, self.project_name)
                return

        self.log_line.emit("=== 应用 crontab 配置 ===")
        apply_result = docker.apply_project_cron_file("/var/www/html/.phpbox/tasks/generated.cron")
        if not apply_result.success:
            self.task_finished.emit(self.action, False, apply_result.error, self.project_name)
            return

        if self.action == "run_now":
            self.log_line.emit("=== 立即执行任务 ===")
            run_result = docker.run_task_now(self.task_id)
            if not run_result.success:
                self.task_finished.emit(self.action, False, run_result.error, self.project_name)
                return

        self.task_finished.emit(self.action, True, "", self.project_name)

    def _stream_start_cron(self, docker: DockerManager, proxy: Optional[str]) -> tuple:
        compose_cmd = docker.get_compose_command()
        if not compose_cmd:
            return False, "未检测到 docker compose 或 docker-compose"

        cmd = compose_cmd + ["up", "-d", "--build", "cron"]
        env = os.environ.copy()
        if proxy:
            env["HTTP_PROXY"] = proxy
            env["HTTPS_PROXY"] = proxy
            env["http_proxy"] = proxy
            env["https_proxy"] = proxy
            self.log_line.emit(f"使用代理: {proxy}")
        self.log_line.emit("=== 开始构建并启动 cron 服务 ===")

        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=str(docker.project_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env
            )

            for line in self.process.stdout:
                stripped = line.rstrip()
                if stripped:
                    self.log_line.emit(stripped)

            self.process.wait()
            if self.process.returncode == 0:
                self.log_line.emit("=== cron 服务构建完成 ===")
                return True, ""

            return False, "cron 服务构建失败，请查看日志"
        except Exception as exc:
            return False, str(exc)
        finally:
            self.process = None

    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()


class TaskEditorDialog(FluentDialog):
    """任务编辑对话框"""

    def __init__(self, projects: List[Project], task: Optional[TaskDefinition] = None, parent=None):
        super().__init__(parent)
        self.projects = projects
        self.task = task
        self.original_project_name = task.project_name if task else None
        self.setWindowTitle("编辑定时任务" if task else "新建定时任务")
        self.setMinimumSize(620, 540)
        self.setup_ui()
        self.load_task()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        project_row = QHBoxLayout()
        project_row.addWidget(BodyLabel("所属项目"))
        self.project_combo = ComboBox()
        for project in self.projects:
            self.project_combo.addItem(project.name)
        project_row.addWidget(self.project_combo, 1)
        layout.addLayout(project_row)

        name_row = QHBoxLayout()
        name_row.addWidget(BodyLabel("任务名称"))
        self.name_input = LineEdit()
        self.name_input.setPlaceholderText("例如：清理缓存")
        name_row.addWidget(self.name_input, 1)
        layout.addLayout(name_row)

        schedule_row = QHBoxLayout()
        schedule_row.addWidget(BodyLabel("执行周期"))
        self.schedule_combo = ComboBox()
        for label in PRESET_SCHEDULES:
            self.schedule_combo.addItem(label)
        self.schedule_combo.currentTextChanged.connect(self._update_schedule_mode)
        schedule_row.addWidget(self.schedule_combo, 1)
        layout.addLayout(schedule_row)

        self.custom_schedule_row = QHBoxLayout()
        self.custom_schedule_row.addWidget(BodyLabel("Cron 表达式"))
        self.custom_schedule_input = LineEdit()
        self.custom_schedule_input.setPlaceholderText("* * * * *")
        self.custom_schedule_row.addWidget(self.custom_schedule_input, 1)
        layout.addLayout(self.custom_schedule_row)

        user_row = QHBoxLayout()
        user_row.addWidget(BodyLabel("执行用户"))
        self.user_input = LineEdit()
        self.user_input.setPlaceholderText("user")
        user_row.addWidget(self.user_input, 1)
        layout.addLayout(user_row)

        layout.addWidget(BodyLabel("执行内容"))
        self.command_input = TextEdit()
        self.command_input.setPlaceholderText("例如：php artisan schedule:run")
        self.command_input.setMinimumHeight(180)
        layout.addWidget(self.command_input, 1)

        self.enabled_cb = CheckBox("启用该任务")
        self.enabled_cb.setChecked(True)
        layout.addWidget(self.enabled_cb)

        self.hint_label = CaptionLabel("预设周期会自动生成对应的 cron 表达式；选择“自定义”后可直接输入表达式。")
        self.hint_label.setStyleSheet(f"color: {themed_color('#64748b', '#94a3b8')};")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = PushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        self.save_btn = PrimaryPushButton(FIF.SAVE, "保存")
        self.save_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.save_btn)
        layout.addLayout(btn_row)

    def _update_schedule_mode(self, schedule_type: str):
        custom = schedule_type == "自定义"
        for index in range(self.custom_schedule_row.count()):
            widget = self.custom_schedule_row.itemAt(index).widget()
            if widget:
                widget.setVisible(custom)
        if custom:
            self.custom_schedule_input.show()
        else:
            self.custom_schedule_input.hide()

    def load_task(self):
        self.user_input.setText("user")
        if not self.task:
            self._update_schedule_mode(self.schedule_combo.currentText())
            return

        self.project_combo.setCurrentText(self.task.project_name)
        self.name_input.setText(self.task.name)
        self.schedule_combo.setCurrentText(self.task.schedule_type or "自定义")
        self.custom_schedule_input.setText(self.task.cron_expression)
        self.user_input.setText(self.task.user or "user")
        self.command_input.setPlainText(self.task.command)
        self.enabled_cb.setChecked(self.task.enabled)
        self._update_schedule_mode(self.schedule_combo.currentText())

    def get_task(self) -> TaskDefinition:
        task_id = self.task.id if self.task else ""
        created_at = self.task.created_at if self.task else now_iso()
        return TaskDefinition(
            id=task_id,
            name=self.name_input.text().strip(),
            project_name=self.project_combo.currentText().strip(),
            schedule_type=self.schedule_combo.currentText().strip(),
            schedule_value=self.schedule_combo.currentText().strip(),
            cron_expression=self.custom_schedule_input.text().strip(),
            user=self.user_input.text().strip() or "user",
            command=self.command_input.toPlainText().strip(),
            enabled=self.enabled_cb.isChecked(),
            created_at=created_at,
            updated_at=now_iso(),
        )


class TaskLogDialog(FluentDialog):
    """任务日志对话框"""

    def __init__(self, title: str, content: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(880, 560)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        self.log_text = TextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setPlainText(content or "暂无日志")
        self.log_text.setStyleSheet(f"""
            TextEdit {{
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: 'Consolas', 'Monaco', monospace;
                border: 1px solid {themed_color('#ddd', '#3c3c3c')};
                border-radius: 4px;
            }}
        """)
        layout.addWidget(self.log_text, 1)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = PushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)


class TaskCenterPage(QWidget):
    """全局任务中心页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.projects: List[Project] = []
        self.task_manager = TaskManager(self.projects)
        self.runtime_worker: Optional[TaskRuntimeWorker] = None
        self.build_progress_dialog: Optional[BuildProgressDialog] = None
        self._pending_task_name = ""
        self._pending_action = ""
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        header_card = CardWidget()
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(22, 18, 22, 18)
        header_layout.setSpacing(12)
        icon = IconWidget(FIF.DATE_TIME)
        icon.setFixedSize(22, 22)
        header_layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        header_text = QVBoxLayout()
        title = StrongBodyLabel("定时任务")
        subtitle = CaptionLabel("集中管理所有项目的 crontab 任务，支持启停、立即执行、日志和最近执行状态。")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {themed_color('#64748b', '#94a3b8')};")
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        header_layout.addLayout(header_text, 1)

        self.add_btn = PrimaryPushButton(FIF.ADD, "新建任务")
        self.add_btn.clicked.connect(self.add_task)
        header_layout.addWidget(self.add_btn)
        self.refresh_btn = PushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_tasks)
        header_layout.addWidget(self.refresh_btn)
        layout.addWidget(header_card)

        self.summary_label = CaptionLabel("")
        self.summary_label.setStyleSheet(f"color: {themed_color('#64748b', '#94a3b8')};")
        layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, 8, self)
        self.table.setHorizontalHeaderLabels([
            "任务名称", "所属项目", "执行周期", "执行用户", "状态", "上次执行时间", "最近结果", "操作"
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

    def _notify(self, title: str, content: str, level: str = "success"):
        bar_func = getattr(InfoBar, level, InfoBar.info)
        bar_func(
            title=title,
            content=content,
            orient=Qt.Orientation.Horizontal,
            parent=self.window()
        )

    def _set_busy(self, busy: bool, text: str = ""):
        self.table.setEnabled(not busy)
        self.add_btn.setEnabled(not busy)
        self.refresh_btn.setEnabled(not busy)
        if busy and text:
            self.summary_label.setText(text)

    def _ensure_docker_ready(self) -> bool:
        main_win = self.window()
        if hasattr(main_win, "ensure_docker_ready"):
            return main_win.ensure_docker_ready()
        return True

    def set_projects(self, projects: List[Project]):
        self.projects = projects
        self.task_manager = TaskManager(projects)
        self.refresh_tasks()

    def refresh_tasks(self):
        self.task_manager.cleanup_old_logs()
        rows = self.task_manager.get_task_rows()
        self.table.setRowCount(len(rows))
        enabled_count = 0

        for row_index, row in enumerate(rows):
            task = row["task"]
            state = row["state"]
            if task.enabled:
                enabled_count += 1
            values = [
                task.name,
                task.project_name,
                task.cron_expression if task.schedule_type == "自定义" else task.schedule_type,
                task.user,
                "已启用" if task.enabled else "已停止",
                self.task_manager.format_last_run(state),
                row["recent_result"],
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row_index, col_index, item)
            self.table.setCellWidget(row_index, 7, self._create_actions_widget(task))

        self.summary_label.setText(f"共 {len(rows)} 个任务，已启用 {enabled_count} 个")

    def _create_actions_widget(self, task: TaskDefinition) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        start_stop_btn = ToolButton(FIF.PLAY if not task.enabled else FIF.PAUSE)
        start_stop_btn.setToolTip("启动任务" if not task.enabled else "停止任务")
        start_stop_btn.clicked.connect(lambda: self.toggle_task(task.id, not task.enabled))
        layout.addWidget(start_stop_btn)

        run_btn = ToolButton(FIF.CARE_RIGHT_SOLID)
        run_btn.setToolTip("立即执行")
        run_btn.clicked.connect(lambda: self.run_task_now(task.id))
        layout.addWidget(run_btn)

        edit_btn = ToolButton(FIF.EDIT)
        edit_btn.setToolTip("编辑任务")
        edit_btn.clicked.connect(lambda: self.edit_task(task.id))
        layout.addWidget(edit_btn)

        log_btn = ToolButton(FIF.DOCUMENT)
        log_btn.setToolTip("查看日志")
        log_btn.clicked.connect(lambda: self.view_logs(task.id))
        layout.addWidget(log_btn)

        delete_btn = ToolButton(FIF.DELETE)
        delete_btn.setToolTip("删除任务")
        delete_btn.clicked.connect(lambda: self.delete_task(task.id))
        layout.addWidget(delete_btn)
        return widget

    def add_task(self):
        if not self.projects:
            self._notify("无法创建", "当前没有可用项目，请先创建项目", "warning")
            return
        dialog = TaskEditorDialog(self.projects, parent=self)
        if dialog.exec():
            self._save_task(dialog.get_task(), dialog.original_project_name)

    def edit_task(self, task_id: str):
        task = self.task_manager.get_task(task_id)
        if not task:
            self._notify("任务不存在", "无法找到该任务", "error")
            return
        dialog = TaskEditorDialog(self.projects, task=task, parent=self)
        if dialog.exec():
            self._save_task(dialog.get_task(), dialog.original_project_name)

    def _save_task(self, task: TaskDefinition, original_project_name: Optional[str]):
        try:
            self.task_manager.save_task(task, original_project_name=original_project_name)
        except ValueError as exc:
            self._notify("保存失败", str(exc), "error")
            return

        if task.enabled:
            if not self._ensure_docker_ready():
                self._notify("保存完成", f"任务 {task.name} 已保存，但 Docker 未就绪", "warning")
                self.refresh_tasks()
                return
            self._start_runtime_worker("save", task.project_name, task.name, build_if_needed=False)
        else:
            project = self.task_manager.get_project(task.project_name)
            docker = DockerManager(project.path)
            if docker.has_service("cron") and docker.is_service_running("cron"):
                result = docker.apply_project_cron_file("/var/www/html/.phpbox/tasks/generated.cron")
                if not result.success:
                    self._notify("保存完成", f"任务已保存，但停用未生效：{result.error}", "warning")
                    self.refresh_tasks()
                    return
            self._notify("保存完成", f"任务 {task.name} 已保存", "success")
            self.refresh_tasks()

    def delete_task(self, task_id: str):
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        box = MessageBox("确认删除", f"确定要删除任务“{task.name}”吗？", self)
        if not box.exec():
            return
        self.task_manager.delete_task(task_id)
        self.refresh_tasks()
        self._notify("删除完成", f"任务 {task.name} 已删除", "success")

    def toggle_task(self, task_id: str, enabled: bool):
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        self.task_manager.set_task_enabled(task_id, enabled)
        if enabled:
            if not self._ensure_docker_ready():
                self._notify("启动失败", "Docker 未就绪，任务已保存为启用状态", "warning")
                return
            self._start_runtime_worker("enable", task.project_name, task.name, build_if_needed=False)
        else:
            project = self.task_manager.get_project(task.project_name)
            if project and self._ensure_docker_ready():
                docker = DockerManager(project.path)
                if docker.has_service("cron") and docker.is_service_running("cron"):
                    docker.apply_project_cron_file("/var/www/html/.phpbox/tasks/generated.cron")
            self._notify("停止完成", f"任务 {task.name} 已停用", "success")
            self.refresh_tasks()

    def run_task_now(self, task_id: str):
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        if not self._ensure_docker_ready():
            self._notify("执行失败", "Docker 未就绪", "error")
            return
        self._start_runtime_worker("run_now", task.project_name, task.name, task_id=task_id, build_if_needed=False)

    def view_logs(self, task_id: str):
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        project = self.task_manager.get_project(task.project_name)
        if not project:
            return
        content = self.task_manager.read_recent_task_logs(project, task_id)
        TaskLogDialog(f"任务日志 - {task.name}", content, self).exec()

    def _start_runtime_worker(self, action: str, project_name: str, task_name: str,
                              task_id: str = "", build_if_needed: bool = False):
        if self.runtime_worker and self.runtime_worker.isRunning():
            self._notify("请稍候", "当前已有任务运行时操作正在执行", "warning")
            return

        self._pending_action = action
        self._pending_task_name = task_name
        self._set_busy(True, f"正在处理任务 {task_name}，首次启用时可能需要构建 cron 运行环境...")
        self.runtime_worker = TaskRuntimeWorker(
            self.projects,
            project_name,
            action=action,
            task_id=task_id,
            build_if_needed=build_if_needed
        )
        self.runtime_worker.build_required.connect(self._on_build_required)
        self.runtime_worker.log_line.connect(self._on_runtime_log_line)
        self.runtime_worker.task_finished.connect(self._on_runtime_worker_finished)
        self.runtime_worker.start()

    def _on_build_required(self, project_name: str):
        if self.build_progress_dialog:
            try:
                self.build_progress_dialog.close()
            except Exception:
                pass
        self.build_progress_dialog = BuildProgressDialog(project_name, self)
        self.build_progress_dialog.setWindowTitle("初始化定时任务运行环境")
        self.build_progress_dialog.title_label.setText(f"正在为「{project_name}」初始化定时任务环境")
        self.build_progress_dialog.status_label.setText("正在构建 cron 服务...")
        self.build_progress_dialog.set_progress(5, "准备安装 cron 环境...")
        self.build_progress_dialog.rejected.connect(self._cancel_runtime_worker)
        self.build_progress_dialog.show()

    def _on_runtime_log_line(self, line: str):
        if not self.build_progress_dialog:
            return
        self.build_progress_dialog.append_log(line)

    def _on_runtime_worker_finished(self, action: str, success: bool, message: str, project_name: str):
        self._set_busy(False)
        self.refresh_tasks()
        if self.build_progress_dialog:
            self.build_progress_dialog.append_log("")
            self.build_progress_dialog.append_log("=== 操作完成 ===" if success else f"=== 操作失败: {message} ===")
            self.build_progress_dialog.set_finished(success, message)

        task_name = self._pending_task_name or "任务"
        if success:
            if action == "run_now":
                self._notify("执行完成", f"任务 {task_name} 已执行", "success")
            elif action == "enable":
                self._notify("启动完成", f"任务 {task_name} 已启用", "success")
            else:
                self._notify("保存完成", f"任务 {task_name} 已保存并启用", "success")
            return

        if action == "run_now":
            self._notify("执行失败", message, "error")
        elif action == "enable":
            self._notify("启动失败", message, "error")
        else:
            self._notify("保存完成", f"任务已保存，但运行时初始化失败：{message}", "warning")

    def _cancel_runtime_worker(self):
        if self.runtime_worker and self.runtime_worker.isRunning():
            self.runtime_worker.stop()

    def closeEvent(self, event):
        if self.runtime_worker and self.runtime_worker.isRunning():
            self.runtime_worker.stop()
            self.runtime_worker.wait(3000)
        if self.build_progress_dialog:
            self.build_progress_dialog.close()
        super().closeEvent(event)
