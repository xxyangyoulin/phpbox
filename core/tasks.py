"""全局定时任务管理"""
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.project import Project, get_project_code_path


PRESET_SCHEDULES: Dict[str, str] = {
    "每分钟": "* * * * *",
    "每5分钟": "*/5 * * * *",
    "每小时": "0 * * * *",
    "每天": "0 0 * * *",
    "每周": "0 0 * * 0",
    "每月": "0 0 1 * *",
    "自定义": "",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class TaskDefinition:
    id: str
    name: str
    project_name: str
    schedule_type: str
    schedule_value: str
    cron_expression: str
    user: str
    command: str
    enabled: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_dict(cls, data: dict) -> "TaskDefinition":
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:12]),
            name=str(data.get("name") or "").strip(),
            project_name=str(data.get("project_name") or "").strip(),
            schedule_type=str(data.get("schedule_type") or "自定义").strip(),
            schedule_value=str(data.get("schedule_value") or "").strip(),
            cron_expression=str(data.get("cron_expression") or "").strip(),
            user=str(data.get("user") or "user").strip(),
            command=str(data.get("command") or "").strip(),
            enabled=bool(data.get("enabled", True)),
            created_at=str(data.get("created_at") or now_iso()),
            updated_at=str(data.get("updated_at") or now_iso()),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "project_name": self.project_name,
            "schedule_type": self.schedule_type,
            "schedule_value": self.schedule_value,
            "cron_expression": self.cron_expression,
            "user": self.user,
            "command": self.command,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class TaskExecutionState:
    task_id: str
    last_run_at: str = ""
    last_finished_at: str = ""
    last_exit_code: Optional[int] = None
    last_status: str = ""
    last_log_file: str = ""

    @classmethod
    def from_dict(cls, task_id: str, data: dict) -> "TaskExecutionState":
        raw_exit_code = data.get("last_exit_code")
        exit_code = None
        if raw_exit_code not in (None, ""):
            try:
                exit_code = int(raw_exit_code)
            except (TypeError, ValueError):
                exit_code = None
        return cls(
            task_id=task_id,
            last_run_at=str(data.get("last_run_at") or ""),
            last_finished_at=str(data.get("last_finished_at") or ""),
            last_exit_code=exit_code,
            last_status=str(data.get("last_status") or ""),
            last_log_file=str(data.get("last_log_file") or ""),
        )

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "last_run_at": self.last_run_at,
            "last_finished_at": self.last_finished_at,
            "last_exit_code": self.last_exit_code,
            "last_status": self.last_status,
            "last_log_file": self.last_log_file,
        }


class TaskManager:
    """项目任务管理器"""

    def __init__(self, projects: List[Project]):
        self.projects = projects
        self._project_map = {project.name: project for project in projects}

    def get_project(self, project_name: str) -> Optional[Project]:
        return self._project_map.get(project_name)

    def get_project_task_root(self, project: Project) -> Path:
        code_path = get_project_code_path(project.path, project.name)
        return code_path / ".phpbox" / "tasks"

    def get_tasks_file(self, project: Project) -> Path:
        return self.get_project_task_root(project) / "tasks.json"

    def get_generated_cron_file(self, project: Project) -> Path:
        return self.get_project_task_root(project) / "generated.cron"

    def get_logs_dir(self, project: Project) -> Path:
        return self.get_project_task_root(project) / "logs"

    def get_state_dir(self, project: Project) -> Path:
        return self.get_project_task_root(project) / "state"

    def get_runner_script(self, project: Project) -> Path:
        return self.get_project_task_root(project) / "run_task.sh"

    def ensure_project_task_dirs(self, project: Project):
        root = self.get_project_task_root(project)
        (root / "logs").mkdir(parents=True, exist_ok=True)
        (root / "state").mkdir(parents=True, exist_ok=True)

    def load_project_tasks(self, project: Project) -> List[TaskDefinition]:
        tasks_file = self.get_tasks_file(project)
        if not tasks_file.exists():
            return []
        try:
            data = json.loads(tasks_file.read_text(encoding="utf-8"))
            if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                raise ValueError("任务配置必须是对象列表")
            tasks = [TaskDefinition.from_dict(item) for item in data]
            if any(not re.fullmatch(r"[a-zA-Z0-9_-]+", task.id) for task in tasks):
                raise ValueError("任务标识格式无效")
            return [task for task in tasks if task.project_name == project.name]
        except (OSError, ValueError) as exc:
            raise ValueError(f"无法读取 {tasks_file}: {exc}") from exc

    def save_project_tasks(self, project: Project, tasks: List[TaskDefinition]):
        self.ensure_project_task_dirs(project)
        payload = [task.to_dict() for task in tasks]
        target = self.get_tasks_file(project)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)

    def load_all_tasks(self) -> List[TaskDefinition]:
        tasks: List[TaskDefinition] = []
        for project in self.projects:
            tasks.extend(self.load_project_tasks(project))
        return tasks

    def get_task(self, task_id: str) -> Optional[TaskDefinition]:
        for task in self.load_all_tasks():
            if task.id == task_id:
                return task
        return None

    def get_task_state(self, project: Project, task_id: str) -> TaskExecutionState:
        state_file = self.get_state_dir(project) / f"{task_id}.json"
        if not state_file.exists():
            return TaskExecutionState(task_id=task_id)
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return TaskExecutionState.from_dict(task_id, data)
        except Exception:
            pass
        return TaskExecutionState(task_id=task_id)

    def get_task_log_files(self, project: Project, task_id: str) -> List[Path]:
        task_log_dir = self.get_logs_dir(project) / task_id
        if not task_log_dir.exists():
            return []
        return sorted(
            [item for item in task_log_dir.iterdir() if item.is_file() and item.suffix == ".log"],
            key=lambda item: item.stat().st_mtime,
            reverse=True
        )

    def read_recent_task_logs(self, project: Project, task_id: str, max_files: int = 20) -> str:
        chunks: List[str] = []
        for log_file in self.get_task_log_files(project, task_id)[:max_files]:
            try:
                with log_file.open("rb") as stream:
                    stream.seek(max(0, log_file.stat().st_size - 65536))
                    content = stream.read(65536).decode("utf-8", errors="replace")
                chunks.append(f"===== {log_file.name}（末尾最多 64 KiB）=====\n{content}")
            except Exception:
                continue
        return "\n\n".join(chunks).strip()

    def validate_task(self, task: TaskDefinition) -> Tuple[bool, str]:
        if not task.project_name:
            return False, "请选择所属项目"
        if task.project_name not in self._project_map:
            return False, f"项目 {task.project_name} 不存在"
        if task.id and not re.fullmatch(r"[a-zA-Z0-9_-]+", task.id):
            return False, "任务标识格式无效"
        if "\n" in task.name or "\r" in task.name:
            return False, "任务名称不能包含换行"
        if not task.name.strip():
            return False, "任务名称不能为空"
        if not task.user.strip():
            return False, "执行用户不能为空"
        if not re.match(r"^[a-z_][a-z0-9_-]*[$]?$", task.user, re.IGNORECASE):
            return False, "执行用户格式无效"
        if not task.command.strip():
            return False, "执行内容不能为空"
        cron_expression = self.resolve_cron_expression(task)
        if not self.is_valid_cron_expression(cron_expression):
            return False, "执行周期格式无效"
        return True, ""

    def resolve_cron_expression(self, task: TaskDefinition) -> str:
        if task.schedule_type == "自定义":
            return task.cron_expression.strip()
        return PRESET_SCHEDULES.get(task.schedule_type, task.cron_expression).strip()

    @staticmethod
    def is_valid_cron_expression(expression: str) -> bool:
        if "\n" in expression or "\r" in expression:
            return False
        parts = expression.split()
        if len(parts) != 5:
            return False
        names = [{}, {}, {}, dict(zip("jan feb mar apr may jun jul aug sep oct nov dec".split(), range(1, 13))),
                 dict(zip("sun mon tue wed thu fri sat".split(), range(7)))]
        for field, (low, high), aliases in zip(parts, [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)], names):
            for word, number in aliases.items():
                field = re.sub(word, str(number), field, flags=re.IGNORECASE)
            for item in field.split(","):
                match = re.fullmatch(r"(\*|[0-9]+(?:-[0-9]+)?)(?:/([0-9]+))?", item)
                if not match:
                    return False
                base, step = match.groups()
                if step is not None and not 1 <= int(step) <= high - low + 1:
                    return False
                if base != "*":
                    values = [int(value) for value in base.split("-")]
                    if not all(low <= value <= high for value in values):
                        return False
                    if len(values) == 2 and values[0] > values[1]:
                        return False
        return True

    @staticmethod
    def shell_quote(value: str) -> str:
        return "'" + value.replace("'", "'\"'\"'") + "'"

    def build_runner_script_content(self) -> str:
        return """#!/bin/sh
set -eu

TASK_ID="$1"
MODE="${2:-scheduled}"
RUN_ID="${3:-scheduled-$$}"
TASK_ROOT="/var/www/html/.phpbox/tasks"
TASK_FILE="$TASK_ROOT/tasks.json"
LOG_ROOT="$TASK_ROOT/logs"
STATE_ROOT="$TASK_ROOT/state"

mkdir -p "$LOG_ROOT" "$STATE_ROOT"
case "$TASK_ID:$RUN_ID" in *[!a-zA-Z0-9_:-]*) exit 1 ;; esac
exec 9>"$STATE_ROOT/$TASK_ID.lock"
flock -n 9 || { echo "任务已在执行，本次跳过"; exit 0; }
echo "$$" > "$STATE_ROOT/$RUN_ID.pid"
trap 'rm -f "$STATE_ROOT/$RUN_ID.pid" "$STATE_ROOT/$RUN_ID.cancel"' EXIT
if [ -f "$STATE_ROOT/$RUN_ID.cancel" ]; then exit 130; fi

clean_old_logs() {
    find "$LOG_ROOT" -type f -name '*.log' -mtime +3 -delete 2>/dev/null || true
}

read_task_meta() {
php -r '
$taskFile = $argv[1];
$taskId = $argv[2];
if (!is_file($taskFile)) {
    exit(1);
}
$data = json_decode(file_get_contents($taskFile), true);
if (!is_array($data)) {
    exit(1);
}
foreach ($data as $item) {
    if (($item["id"] ?? "") === $taskId) {
        $user = trim((string)($item["user"] ?? "user"));
        if ($user === "") {
            $user = "user";
        }
        if ($argv[3] !== "--manual" && empty($item["enabled"])) { exit(1); }
        $command = (string)($item["command"] ?? "");
        echo $user, PHP_EOL, $command, PHP_EOL;
        exit(0);
    }
}
exit(1);
' "$TASK_FILE" "$TASK_ID" "$MODE"
}

write_state() {
    status="$1"
    exit_code="$2"
    log_file="$3"
    started_at="$4"
    finished_at="$5"
    php -r '
$stateFile = $argv[1];
$payload = [
    "task_id" => $argv[2],
    "last_status" => $argv[3],
    "last_exit_code" => (int)$argv[4],
    "last_log_file" => $argv[5],
    "last_run_at" => $argv[6],
    "last_finished_at" => $argv[7],
];
$tmp = $stateFile . "." . getmypid() . ".tmp";
file_put_contents($tmp, json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE) . PHP_EOL);
rename($tmp, $stateFile);
' "$STATE_ROOT/$TASK_ID.json" "$TASK_ID" "$status" "$exit_code" "$log_file" "$started_at" "$finished_at"
}

clean_old_logs

TASK_META="$(read_task_meta || true)"
if [ -z "$TASK_META" ]; then
    exit 1
fi

TASK_USER="$(printf '%s\n' "$TASK_META" | sed -n '1p')"
TASK_COMMAND="$(printf '%s\n' "$TASK_META" | sed -n '2,$p')"
TIMESTAMP="$(date '+%Y%m%d-%H%M%S')"
TASK_LOG_DIR="$LOG_ROOT/$TASK_ID"
mkdir -p "$TASK_LOG_DIR"
chown --reference="$TASK_ROOT" "$TASK_LOG_DIR" "$LOG_ROOT" "$STATE_ROOT"
LOG_FILE="$(mktemp "$TASK_LOG_DIR/$TIMESTAMP-XXXXXX.log")"
STARTED_AT="$(date '+%Y-%m-%dT%H:%M:%S%z')"

set +e
su -s /bin/sh "$TASK_USER" --session-command "cd /var/www/html && $TASK_COMMAND" 9>&- >"$LOG_FILE" 2>&1
EXIT_CODE="$?"
set -e

FINISHED_AT="$(date '+%Y-%m-%dT%H:%M:%S%z')"
STATUS="success"
if [ "$EXIT_CODE" -ne 0 ]; then
    STATUS="failed"
fi

write_state "$STATUS" "$EXIT_CODE" "$LOG_FILE" "$STARTED_AT" "$FINISHED_AT"
clean_old_logs
exit "$EXIT_CODE"
"""

    def ensure_runner_script(self, project: Project):
        self.ensure_project_task_dirs(project)
        runner = self.get_runner_script(project)
        runner.write_text(self.build_runner_script_content(), encoding="utf-8")
        runner.chmod(0o755)

    @staticmethod
    def build_cron_service_block(project_name: str, code_dir_name: str) -> str:
        uid = os.getuid()
        gid = os.getgid()
        return f"""
  cron:
    container_name: phpdev-{project_name}-cron
    build:
      context: .
      dockerfile: Dockerfile
      args:
        USER_UID: {uid}
        USER_GID: {gid}
    restart: unless-stopped
    command: ["sh", "-lc", "mkdir -p /var/www/html/.phpbox/tasks/logs /var/www/html/.phpbox/tasks/state && touch /var/www/html/.phpbox/tasks/generated.cron && crontab /var/www/html/.phpbox/tasks/generated.cron || true && exec cron -f"]
    volumes:
      - ./{code_dir_name}:/var/www/html
      - ./php/php.ini:/usr/local/etc/php/php.ini
      - ./php/php-fpm.conf:/usr/local/etc/php/php-fpm.conf
      - ./php/www.conf:/usr/local/etc/php-fpm.d/www.conf
      - ./logs/php-fpm:/var/log/php-fpm
      - ~/.ssh:/home/user/.ssh:ro
      - ~/.gitconfig:/home/user/.gitconfig:ro
    depends_on:
      - php
    networks:
      - app
"""

    def ensure_project_runtime(self, project: Project) -> Dict[str, bool]:
        self.ensure_project_task_dirs(project)
        self.ensure_runner_script(project)
        self.write_generated_cron(project, self.load_project_tasks(project))
        dockerfile_changed = self._ensure_dockerfile_has_cron(project)
        compose_changed = self._ensure_compose_has_cron(project)
        return {
            "dockerfile_changed": dockerfile_changed,
            "compose_changed": compose_changed,
        }

    def _ensure_dockerfile_has_cron(self, project: Project):
        dockerfile = project.path / "Dockerfile"
        if not dockerfile.exists():
            return False
        content = dockerfile.read_text(encoding="utf-8")
        if re.search(r"\bcron\b", content):
            return False
        old = "RUN apt-get update && apt-get install -y unzip git openssh-client zsh curl wget sudo && rm -rf /var/lib/apt/lists/*"
        new = "RUN apt-get update && apt-get install -y unzip git openssh-client zsh curl wget sudo cron && rm -rf /var/lib/apt/lists/*"
        if old in content:
            content = content.replace(old, new, 1)
        else:
            content = re.sub(r"(apt-get install -y\s+)", r"\1cron ", content, count=1)
        dockerfile.write_text(content, encoding="utf-8")
        return True

    def _ensure_compose_has_cron(self, project: Project):
        compose_file = project.path / "docker-compose.yml"
        if not compose_file.exists():
            return False
        content = compose_file.read_text(encoding="utf-8")
        if re.search(r"^\s{2}cron:\s*$", content, re.MULTILINE):
            return False

        code_dir_name = get_project_code_path(project.path, project.name).name
        cron_block = self.build_cron_service_block(project.name, code_dir_name)
        marker = "\n  nginx:\n"
        if marker in content:
            content = content.replace(marker, cron_block + "\n  nginx:\n", 1)
        else:
            content = content.replace("\nnetworks:\n", cron_block + "\nnetworks:\n", 1)
        compose_file.write_text(content, encoding="utf-8")
        return True

    def generate_cron_content(self, project: Project, tasks: List[TaskDefinition]) -> str:
        lines = [
            "SHELL=/bin/sh",
            "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "",
        ]
        runner_path = "/var/www/html/.phpbox/tasks/run_task.sh"
        for task in tasks:
            if not task.enabled:
                continue
            cron_expression = self.resolve_cron_expression(task)
            if not self.is_valid_cron_expression(cron_expression):
                continue
            lines.append(f"# {task.name}")
            lines.append(f"{cron_expression} {runner_path} {self.shell_quote(task.id)}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def write_generated_cron(self, project: Project, tasks: List[TaskDefinition]):
        self.ensure_project_task_dirs(project)
        self.ensure_runner_script(project)
        content = self.generate_cron_content(project, tasks)
        target = self.get_generated_cron_file(project)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(target)

    def save_task(self, task: TaskDefinition, original_project_name: Optional[str] = None):
        valid, message = self.validate_task(task)
        if not valid:
            raise ValueError(message)

        target_project = self.get_project(task.project_name)
        if not target_project:
            raise ValueError(f"项目 {task.project_name} 不存在")

        if not task.id:
            task.id = uuid.uuid4().hex[:12]
        now = now_iso()
        if not task.created_at:
            task.created_at = now
        task.updated_at = now

        source_project_name = original_project_name or task.project_name
        source_project = self.get_project(source_project_name)

        affected = [target_project]
        if source_project and source_project != target_project:
            affected.append(source_project)
        snapshots = {}
        for project in affected:
            for file in [self.get_tasks_file(project), self.get_generated_cron_file(project)]:
                snapshots[file] = file.read_bytes() if file.exists() else None
        try:
            target_tasks = [item for item in self.load_project_tasks(target_project) if item.id != task.id]
            target_tasks.append(task)
            self.save_project_tasks(target_project, target_tasks)
            self.write_generated_cron(target_project, target_tasks)
            if source_project and source_project != target_project:
                source_tasks = [item for item in self.load_project_tasks(source_project) if item.id != task.id]
                self.save_project_tasks(source_project, source_tasks)
                self.write_generated_cron(source_project, source_tasks)
        except Exception:
            for file, content in snapshots.items():
                if content is None:
                    file.unlink(missing_ok=True)
                else:
                    file.write_bytes(content)
            raise

    def delete_task(self, task_id: str):
        for project in self.projects:
            tasks = self.load_project_tasks(project)
            if any(task.id == task_id for task in tasks):
                tasks = [task for task in tasks if task.id != task_id]
                self.save_project_tasks(project, tasks)
                self.write_generated_cron(project, tasks)

                return

    def set_task_enabled(self, task_id: str, enabled: bool):
        for project in self.projects:
            tasks = self.load_project_tasks(project)
            updated = False
            for task in tasks:
                if task.id == task_id:
                    task.enabled = enabled
                    task.updated_at = now_iso()
                    updated = True
                    break
            if updated:
                self.save_project_tasks(project, tasks)
                self.write_generated_cron(project, tasks)
                return

    def get_task_rows(self) -> List[dict]:
        rows: List[dict] = []
        for project in self.projects:
            for task in self.load_project_tasks(project):
                state = self.get_task_state(project, task.id)
                rows.append({
                    "task": task,
                    "project": project,
                    "state": state,
                    "recent_result": self.format_recent_result(state),
                })
        rows.sort(key=lambda row: (row["project"].name.lower(), row["task"].name.lower()))
        return rows

    @staticmethod
    def format_recent_result(state: TaskExecutionState) -> str:
        if not state.last_status:
            return "未执行"
        if state.last_status == "success":
            return "成功"
        if state.last_status == "failed":
            code = "" if state.last_exit_code is None else f" ({state.last_exit_code})"
            return f"失败{code}"
        return state.last_status

    @staticmethod
    def format_last_run(state: TaskExecutionState) -> str:
        return state.last_run_at or "--"

    def cleanup_old_logs(self):
        threshold = datetime.now() - timedelta(days=3)
        for project in self.projects:
            logs_dir = self.get_logs_dir(project)
            if not logs_dir.exists():
                continue
            for log_file in logs_dir.rglob("*.log"):
                try:
                    modified_at = datetime.fromtimestamp(log_file.stat().st_mtime)
                    if modified_at < threshold:
                        log_file.unlink(missing_ok=True)
                except Exception:
                    continue
