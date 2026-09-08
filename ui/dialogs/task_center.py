"""全局定时任务中心"""
import threading
import uuid
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

from core.process import run_process
from ui.worker import OperationWorker, register_worker
from core.docker import DockerManager
from core.project import Project
from core.tasks import PRESET_SCHEDULES, TaskDefinition, TaskManager, now_iso
from ui.dialogs.build_progress import BuildProgressDialog
from ui.styles import FluentDialog, themed_color


class TaskRuntimeWorker(QThread):
    task_finished = pyqtSignal(str, bool, str, str)
    build_required = pyqtSignal(str)
    log_line = pyqtSignal(str)

    def __init__(self, projects, project_name, action, task_id="", build_if_needed=False,
                 task=None, original_project_name=None):
        super().__init__()
        register_worker(self)
        self.projects = projects
        self.project_name = project_name
        self.action = action
        self.task_id = task_id
        self.build_if_needed = build_if_needed
        self.task = task
        self.original_project_name = original_project_name
        self.cancel_event = threading.Event()
        self.run_id = uuid.uuid4().hex

    def _command(self, docker, args):
        if self.cancel_event.is_set():
            raise InterruptedError("操作已取消")
        command = docker.get_compose_command()
        if not command:
            raise RuntimeError("未检测到 Docker Compose")
        result = run_process(command + args, cwd=str(docker.project_path),
                             cancel=self.cancel_event, on_output=self.log_line.emit, timeout=3600)
        if result.returncode:
            raise RuntimeError(result.stdout[-2000:] or "Docker 命令执行失败")
        return result.stdout

    def _sync_existing(self, docker):
        if not docker.has_service("cron"):
            return
        running = self._command(docker, ["ps", "--status", "running", "--format", "{{.Service}}", "cron"])
        if "cron" in running.splitlines():
            self._command(docker, ["exec", "-T", "cron", "crontab", "/var/www/html/.phpbox/tasks/generated.cron"])

    def run(self):
        manager = TaskManager(self.projects)
        project = manager.get_project(self.project_name)
        docker = None
        try:
            if self.cancel_event.is_set():
                raise InterruptedError("操作已取消")
            if not project:
                raise ValueError("项目不存在")
            if self.task is not None:
                manager.save_task(self.task, self.original_project_name)
            elif self.action == "delete":
                manager.delete_task(self.task_id)
            elif self.action in {"enable", "disable"}:
                manager.set_task_enabled(self.task_id, self.action == "enable")
            if self.original_project_name and self.original_project_name != project.name:
                source = manager.get_project(self.original_project_name)
                self._sync_existing(DockerManager(source.path))
            docker = DockerManager(project.path)
            enabled = self.action in {"enable", "run_now"} or (self.task is not None and self.task.enabled)
            if not enabled:
                self._sync_existing(docker)
            else:
                changes = manager.ensure_project_runtime(project)
                args = ["up", "-d"]
                if self.build_if_needed or any(changes.values()):
                    args.append("--build")
                    self.build_required.emit(project.name)
                self._command(docker, args + ["cron"])
                self._command(docker, ["exec", "-T", "cron", "crontab", "/var/www/html/.phpbox/tasks/generated.cron"])
                if self.action == "run_now":
                    self._command(docker, ["exec", "-T", "cron", "setsid",
                                          "/var/www/html/.phpbox/tasks/run_task.sh", self.task_id, "--manual", self.run_id])
            self.task_finished.emit(self.action, True, "", project.name)
        except Exception as exc:
            if self.action == "run_now" and docker is not None and isinstance(exc, (InterruptedError, TimeoutError)):
                state = f"/var/www/html/.phpbox/tasks/state/{self.run_id}"
                try:
                    result = run_process(docker.get_compose_command() + ["exec", "-T", "cron", "sh", "-c",
                        'touch "$1.cancel"; if [ -f "$1.pid" ]; then /bin/kill -TERM -- "-$(cat "$1.pid")"; fi',
                        "sh", state], cwd=str(project.path), timeout=15)
                    if result.returncode:
                        raise RuntimeError(result.stdout)
                except Exception as cleanup_error:
                    exc = RuntimeError(f"{exc}；终止容器内任务失败：{cleanup_error}")
            self.task_finished.emit(self.action, False, str(exc), self.project_name)

    def stop(self):
        self.cancel_event.set()


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
        if getattr(self, "_refreshing", False):
            self._refresh_again = True
            return
        self._refreshing = True
        manager = self.task_manager
        def collect():
            manager.cleanup_old_logs()
            return manager, manager.get_task_rows()
        self.refresh_worker = OperationWorker(collect)
        self.refresh_worker.succeeded.connect(self._on_tasks_loaded)
        self.refresh_worker.failed.connect(self._on_tasks_failed)
        self.refresh_worker.start()

    def _on_tasks_failed(self, message):
        self._refreshing = False
        self._notify("刷新失败", message, "warning")

    def _on_tasks_loaded(self, result):
        self._refreshing = False
        manager, rows = result
        if getattr(self, "_refresh_again", False) or manager is not self.task_manager:
            self._refresh_again = False
            self.refresh_tasks()
            return
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
                "允许调度" if task.enabled else "已禁用调度",
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
        start_stop_btn.setToolTip("启用调度" if not task.enabled else "停止后续调度（不终止当前执行）")
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
        valid, message = self.task_manager.validate_task(task)
        if not valid:
            self._notify("保存失败", message, "error")
            return
        self._start_runtime_worker("save", task.project_name, task.name,
                                   task=task, original_project_name=original_project_name)

    def delete_task(self, task_id: str):
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        box = MessageBox("确认删除", f"确定删除任务“{task.name}”吗？正在执行的任务不会被终止。", self)
        if box.exec():
            self._start_runtime_worker("delete", task.project_name, task.name, task_id=task_id)

    def toggle_task(self, task_id: str, enabled: bool):
        task = self.task_manager.get_task(task_id)
        if task:
            self._start_runtime_worker("enable" if enabled else "disable", task.project_name, task.name, task_id=task_id)

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
        manager = self.task_manager
        self.log_worker = OperationWorker(lambda: (task.name, manager.read_recent_task_logs(project, task_id)))
        self.log_worker.succeeded.connect(self._on_task_logs_loaded)
        self.log_worker.failed.connect(self._on_tasks_failed)
        self.log_worker.start()

    def _on_task_logs_loaded(self, result):
        name, content = result
        TaskLogDialog(f"任务日志 - {name}", content, self).show()

    def _start_runtime_worker(self, action: str, project_name: str, task_name: str,
                              task_id: str = "", build_if_needed: bool = False, task=None, original_project_name=None):
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
            build_if_needed=build_if_needed, task=task, original_project_name=original_project_name
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
            messages = {"run_now": "执行结束", "enable": "调度已启用", "disable": "后续调度已停止，当前执行不受影响",
                        "delete": "任务已删除，当前执行不受影响", "save": "配置已保存并同步"}
            self._notify("操作完成", f"{task_name}：{messages[action]}")
        else:
            self._notify("操作未完成", f"{message}。请刷新核查；本地配置可能已保存。", "warning")

    def _cancel_runtime_worker(self):
        if self.runtime_worker and self.runtime_worker.isRunning():
            self.runtime_worker.stop()

    def closeEvent(self, event):
        if self.runtime_worker and self.runtime_worker.isRunning():
            self.runtime_worker.stop()
            event.ignore()
            return
        if self.build_progress_dialog:
            self.build_progress_dialog.close()
        super().closeEvent(event)
