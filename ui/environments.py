import json
import threading

from PyQt6.QtCore import QThread, Qt, QSize, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QInputDialog, QSplitter, QListWidgetItem
from qfluentwidgets import (BodyLabel, CaptionLabel, ComboBox, InfoBar, LineEdit,
                            FluentIcon as FIF, FlowLayout, ScrollArea, StrongBodyLabel, setCustomStyleSheet,
                            ListWidget, MessageBox, MessageBoxBase, PrimaryPushButton, PushButton, TextEdit, TitleLabel)

from core.config import PHP_VERSIONS
from core.environment import EnvironmentManager, read_binding
from core.runtime import ProjectRuntime
from ui.dialogs.build_progress import BuildProgressDialog
from ui.styles import FluentDialog, SurfaceCard, StatusBadge
from ui.widgets.extension_selector import ExtensionSelector
from ui.worker import OperationWorker, register_worker


class EnvironmentWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str, list)

    def __init__(self, path, operation, title, dialog):
        super().__init__()
        self.project_path = path
        self.operation = operation
        self.cancel_event = threading.Event()
        self.result = None
        register_worker(self, title, dialog)

    def run(self):
        try:
            manager = EnvironmentManager(self.cancel_event, self.progress.emit)
            self.result = self.operation(manager)
            self.finished.emit(True, '操作完成', [])
        except Exception as exc:
            self.finished.emit(False, str(exc), [])

    def stop(self):
        self.cancel_event.set()


def run_environment_operation(parent, path, title, operation, completed):
    dialog = BuildProgressDialog(title, parent)
    dialog.setWindowTitle(title)
    dialog.title_label.setText(title)
    dialog.status_label.setText('正在执行，可转到后台继续使用应用')
    worker = EnvironmentWorker(path, operation, title, dialog)
    worker.progress.connect(dialog.append_log)
    def finished(success, message, logs):
        dialog.set_finished(success, message)
        dialog.title_label.setText(title + (' · 已完成' if success else ' · 未完成'))
        dialog.status_label.setText(message)
    worker.finished.connect(finished)
    worker.finished.connect(lambda success, message, logs: completed(worker.result) if success else None)
    dialog.rejected.connect(worker.stop)
    dialog.show()
    worker.start()
    return worker


class EnvironmentEditor(FluentDialog):
    saved = pyqtSignal(object)

    def __init__(self, parent=None, environment=None):
        super().__init__(parent)
        self.environment = environment
        self.setWindowTitle('编辑 PHP 环境' if environment else '新建 PHP 环境')
        self.resize(720, 720)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(TitleLabel('编辑 PHP 环境' if environment else '新建 PHP 环境'))
        self.name = LineEdit()
        self.name.setPlaceholderText('环境名称，例如 PHP 8.4 开发环境')
        layout.addWidget(self.name)
        row = QHBoxLayout()
        row.addWidget(BodyLabel('PHP 版本'))
        self.version = ComboBox()
        self.version.addItems(PHP_VERSIONS)
        row.addWidget(self.version)
        self.proxy = LineEdit()
        self.proxy.setPlaceholderText('构建代理（可选），例如 http://127.0.0.1:7890')
        if environment is None:
            from core.settings import Settings
            self.proxy.setText(Settings().get_proxy() or '')
        row.addWidget(self.proxy, 1)
        layout.addLayout(row)
        hint = CaptionLabel('使用 PHP 开发默认配置，内置与普通项目相同的终端插件及 proxy / noproxy / ckproxy 命令。\n'
                            '同一环境的项目共享配置和扩展。代理在运行时默认关闭，可在终端用 proxy 手动开启。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.extensions = ExtensionSelector()
        layout.addWidget(self.extensions, 1)
        self.config = TextEdit()
        self.config.setPlaceholderText('已加载 PHP 开发默认配置；在此填写覆盖项，Xdebug 等扩展配置也在这里设置')
        self.config.setMaximumHeight(170)
        self.config.setVisible(environment is not None)
        layout.addWidget(self.config)
        if environment:
            self.name.setText(environment.name)
            self.name.setEnabled(False)
            self.version.setCurrentText(environment.php_version)
            self.version.setEnabled(False)
            self.proxy.setText(environment.proxy)
            self.extensions.set_selected(environment.extensions)
            self.config.setPlainText((environment.path / 'php/php.ini').read_text())
            affected = EnvironmentManager().bindings(environment.id)
            label = BodyLabel('影响项目：' + ('、'.join(p.name for p in affected) or '无'))
            label.setWordWrap(True)
            layout.addWidget(label)
        row = QHBoxLayout()
        cancel = PushButton('取消')
        cancel.clicked.connect(self.reject)
        self.save = PrimaryPushButton('保存并应用' if environment else '创建并构建')
        self.save.clicked.connect(self.submit)
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(self.save)
        layout.addLayout(row)

    def submit(self):
        name, version = self.name.text().strip(), self.version.currentText()
        proxy, extensions = self.proxy.text().strip(), self.extensions.get_selected_extensions()
        config = self.config.toPlainText()
        if not name:
            InfoBar.error('名称不能为空', '请填写环境名称', parent=self)
            return
        environment = self.environment
        if environment:
            affected = EnvironmentManager().bindings(environment.id)
            if not MessageBox('应用共享配置', '将重启此环境，扩展或代理变化时会重建。影响项目：' +
                              ('、'.join(p.name for p in affected) or '无') + '。正在执行的任务会阻止操作。', self).exec():
                return
        def operation(manager):
            if environment:
                manager.update(environment, extensions, proxy, config)
                return environment
            result = manager.create(name, version, extensions, proxy)
            self.environment = result
            manager.build(result)
            manager.start(result)
            return result
        from core.environment import ENVIRONMENTS_DIR
        self.worker = run_environment_operation(self.parentWidget(), environment.path if environment else ENVIRONMENTS_DIR,
                                                self.windowTitle(), operation, self.saved.emit)
        self.accept()


class EnvironmentsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('php_environments')
        self.rows = []
        self.loading = False
        self.selected_id = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(TitleLabel('PHP 环境'))
        subtitle = CaptionLabel('在项目之间共享 PHP、配置与扩展。不同配置可创建独立环境。')
        subtitle.setWordWrap(True)
        subtitle.setTextColor(QColor('#606060'), QColor('#cecece'))
        layout.addWidget(subtitle)
        row = QHBoxLayout()
        create = PrimaryPushButton(FIF.ADD, '新建环境')
        create.clicked.connect(self.create)
        row.addWidget(create)
        self.refresh_button = PushButton(FIF.SYNC, '刷新')
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.refresh_button)
        row.addStretch()
        self.summary = CaptionLabel('尚无环境')
        row.addWidget(self.summary)
        layout.addLayout(row)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(12)
        list_card = SurfaceCard()
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(8, 12, 8, 8)
        self.list = ListWidget()
        self.list.setMinimumWidth(190)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        setCustomStyleSheet(self.list, 'QListWidget { background: transparent; border: none; }',
                            'QListWidget { background: transparent; border: none; }')
        self.list.currentRowChanged.connect(self.show_details)
        list_layout.addWidget(self.list)
        self.splitter.addWidget(list_card)

        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet('ScrollArea { background: transparent; border: none; }')
        detail_card = SurfaceCard()
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(20, 20, 20, 20)
        detail_layout.setSpacing(16)
        self.environment_title = StrongBodyLabel('选择一个 PHP 环境')
        self.environment_title.setWordWrap(True)
        detail_layout.addWidget(self.environment_title)
        badges = QHBoxLayout()
        self.version_badge = StatusBadge('PHP', tone='accent')
        self.state_badge = StatusBadge('未选择')
        badges.addWidget(self.version_badge)
        badges.addWidget(self.state_badge)
        badges.addStretch()
        detail_layout.addLayout(badges)
        self.detail_fields = {}
        for key, title in [('projects', '使用此环境的项目'), ('runtime', '运行配置'),
                           ('extensions', '扩展'), ('path', '环境目录')]:
            field_title = CaptionLabel(title)
            field_title.setTextColor(QColor('#606060'), QColor('#cecece'))
            detail_layout.addWidget(field_title)
            value = BodyLabel('—')
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            detail_layout.addWidget(value)
            self.detail_fields[key] = value

        actions = QWidget()
        row = FlowLayout(actions)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.actions = []
        for label, action in [('配置与扩展', 'edit'), ('启动', 'start'), ('停止', 'stop'),
                              ('重建', 'build'), ('重命名', 'rename'), ('删除', 'delete')]:
            button = PrimaryPushButton(label) if action == 'edit' else PushButton(label)
            button.clicked.connect(lambda checked=False, a=action: self.operate(a))
            self.actions.append(button)
            row.addWidget(button)
        detail_layout.addWidget(actions)
        self.diagnostics_button = PushButton(FIF.CODE, '查看运行信息')
        self.diagnostics_button.setCheckable(True)
        detail_layout.addWidget(self.diagnostics_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.details = TextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(180)
        self.details.setVisible(False)
        self.diagnostics_button.toggled.connect(self.details.setVisible)
        detail_layout.addWidget(self.details)
        detail_layout.addStretch()
        scroll.setWidget(detail_card)
        detail_card.setAutoFillBackground(False)
        self.splitter.addWidget(scroll)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        layout.addWidget(self.splitter, 1)
        self.show_details()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        orientation = Qt.Orientation.Vertical if self.width() < 780 else Qt.Orientation.Horizontal
        if self.splitter.orientation() != orientation:
            self.splitter.setOrientation(orientation)
            self.splitter.setSizes([180, 380] if orientation == Qt.Orientation.Vertical else [260, 520])

    def create(self):
        dialog = EnvironmentEditor(self)
        dialog.saved.connect(lambda env: self.refresh(env.id))
        dialog.show()
        self.editor = dialog

    def refresh(self, selected_id=None):
        if self.loading:
            return
        if isinstance(selected_id, str):
            self.selected_id = selected_id
        self.loading = True
        self.refresh_button.setEnabled(False)
        def fetch():
            manager = EnvironmentManager()
            rows = []
            for env in manager.list():
                running = manager.running(env)
                try:
                    info = manager.info(env) if running else {}
                except Exception as exc:
                    info = {'error': str(exc)}
                info['busy'] = manager.busy(env)
                rows.append((env, running, info, manager.bindings(env.id)))
            return rows
        self.worker = OperationWorker(fetch)
        self.worker.succeeded.connect(self.loaded)
        self.worker.failed.connect(self.failed)
        self.worker.start()

    def failed(self, message):
        self.loading = False
        self.refresh_button.setEnabled(True)
        self.summary.setText('刷新失败')
        self.details.setPlainText(message)
        self.diagnostics_button.setChecked(True)

    def loaded(self, rows):
        self.loading = False
        self.rows = rows
        self.refresh_button.setEnabled(True)
        self.summary.setText(f'{len(rows)} 个环境 · {sum(bool(row[1]) for row in rows)} 个运行中')
        self.list.blockSignals(True)
        self.list.clear()
        selected = 0
        for index, (env, running, info, projects) in enumerate(rows):
            version = info.get('version', env.php_version + '（配置版本）')
            status = '操作中' if info.get('busy') else '运行中' if running else '已停止 / 未构建'
            item = QListWidgetItem(FIF.CODE.icon(color=QColor('#808080')), f'{env.name}\nPHP {env.php_version} · {status}')
            item.setSizeHint(QSize(180, 68))
            item.setToolTip(f'{env.name} · PHP {version} · {len(projects)} 个项目')
            self.list.addItem(item)
            if env.id == self.selected_id:
                selected = index
        self.list.setCurrentRow(selected if rows else -1)
        self.list.blockSignals(False)
        self.show_details()

    def show_details(self, *args):
        index = self.list.currentRow()
        valid = 0 <= index < len(self.rows)
        for button in self.actions:
            button.setEnabled(valid)
        self.diagnostics_button.setEnabled(valid)
        self.version_badge.setVisible(valid)
        self.state_badge.setVisible(valid)
        if not valid:
            self.environment_title.setText('创建你的第一个 PHP 环境')
            self.detail_fields['projects'].setText('新建环境后，在项目的更多菜单中选择「切换 PHP 环境」。')
            for key in ('runtime', 'extensions', 'path'):
                self.detail_fields[key].setText('—')
            self.details.clear()
            self.diagnostics_button.setChecked(False)
            return
        env, running, info, projects = self.rows[index]
        self.selected_id = env.id
        self.environment_title.setText(env.name)
        self.version_badge.setText('PHP ' + info.get('version', env.php_version))
        self.state_badge.setText('操作中' if info.get('busy') else '运行中' if running else '已停止 / 未构建')
        self.state_badge.setTone('warning' if info.get('busy') else 'success' if running else 'neutral')
        self.detail_fields['projects'].setText('、'.join(p.name for p in projects) or '暂无绑定项目')
        self.detail_fields['runtime'].setText(
            info.get('error') or
            (f"内存限制 {info.get('memory_limit', '—')}  ·  时区 {info.get('timezone', '—')}" if running
             else '启动环境后可查看实际配置')
        )
        self.detail_fields['extensions'].setText(', '.join(info.get('extensions', env.extensions)) or '无')
        self.detail_fields['path'].setText(str(env.path))
        self.details.setPlainText(json.dumps(info, ensure_ascii=False, indent=2) if info else '环境尚未运行。')

    def operate(self, action):
        index = self.list.currentRow()
        if not 0 <= index < len(self.rows):
            return
        env, running, info, projects = self.rows[index]
        if action == 'edit':
            self.editor = EnvironmentEditor(self, env)
            self.editor.saved.connect(lambda value: self.refresh(value.id))
            self.editor.show()
            return
        if action == 'rename':
            name, ok = QInputDialog.getText(self, '重命名环境', '环境名称', text=env.name)
            if not ok:
                return
            operation = lambda manager: manager.rename(env, name)
        else:
            if action in ('stop', 'build', 'delete'):
                if not MessageBox('确认环境操作', f'将{"停止" if action == "stop" else "重建" if action == "build" else "删除"}「{env.name}」。\n影响项目：' +
                                  ('、'.join(p.name for p in projects) or '无') + '\n活动任务会阻止停止或重建；绑定中的环境不能删除。', self).exec():
                    return
            operation = lambda manager: getattr(manager, action)(env)
        self.worker = run_environment_operation(self, env.path, env.name + ' · ' + action, operation, lambda result: self.refresh())


class SwitchEnvironmentDialog(FluentDialog):
    changed = pyqtSignal()

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.setWindowTitle('切换 PHP 环境 · ' + project.name)
        self.resize(760, 630)
        layout = QVBoxLayout(self)
        layout.addWidget(BodyLabel('当前环境：' + (project.environment_name or '项目独立 PHP') + ' · PHP ' + project.php_version))
        row = QHBoxLayout()
        self.target = ComboBox()
        row.addWidget(self.target, 1)
        new = PushButton('新建环境')
        new.clicked.connect(self.create)
        row.addWidget(new)
        layout.addLayout(row)
        self.details = TextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 1)
        note = CaptionLabel('切换后新网站请求、命令和任务使用目标环境；已打开终端请重新打开。原环境仍保留。\n'
                            '共享环境可读取其他项目目录，仅适合同一用户的可信本地项目。不会修改 composer.lock、vendor 或应用 .env。')
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.check_button = PushButton('检查环境（必要时启动环境）')
        self.check_button.clicked.connect(self.check)
        row.addWidget(self.check_button)
        self.recover_button = PushButton('恢复原环境')
        self.recover_button.clicked.connect(self.recover)
        self.recover_button.setVisible((project.path / '.phpbox/switch.json').exists())
        row.addWidget(self.recover_button)
        self.apply = PrimaryPushButton('切换（未运行时先启动）')
        self.apply.clicked.connect(self.switch)
        row.addWidget(self.apply)
        layout.addLayout(row)
        self.target.currentIndexChanged.connect(self.preview)
        self.reload()

    def reload(self, environment=None):
        self.environments = EnvironmentManager().list()
        self.target.clear()
        for env in self.environments:
            self.target.addItem(env.name + ' · PHP ' + env.php_version, userData=env.id)
        if environment:
            self.target.setCurrentIndex(next(i for i, e in enumerate(self.environments) if e.id == environment.id))
        self.preview()

    def create(self):
        self.editor = EnvironmentEditor(self)
        self.editor.saved.connect(self.reload)
        self.editor.show()

    def selected(self):
        index = self.target.currentIndex()
        return self.environments[index] if 0 <= index < len(self.environments) else None

    def preview(self, *args):
        env = self.selected()
        self.apply.setEnabled(False)
        self.check_button.setEnabled(bool(env))
        if not env:
            self.details.setPlainText('请先创建 PHP 环境。')
            return
        try:
            if EnvironmentManager().busy(env):
                raise RuntimeError('目标环境正在构建或执行其他操作，请完成后重新选择')
            preview = ProjectRuntime(self.project.path).preview(env)
            lines = ['目标：' + env.name + ' · PHP ' + env.php_version,
                     '目标扩展声明：' + ', '.join(env.extensions), '代码路径：' + preview['code_path']]
            if not self.project.environment_id:
                lines += ['首次迁移会重新创建此项目的 Nginx，保留数据库容器和数据卷。',
                          '原扩展声明：' + ', '.join(preview['extensions']),
                          '原 PHP 配置不自动复制：' + ', '.join(preview['config_files']),
                          '应用数据库地址需自行调整：' + ('；'.join(preview['databases']) or '无数据库服务')]
            lines.append('点击检查可查看实际 PHP 版本、扩展、主要配置和目录权限。切换不检查 Composer 平台要求。')
            self.details.setPlainText('\n\n'.join(lines))
            self.apply.setEnabled(env.id != self.project.environment_id and not (self.project.path / '.phpbox/switch.json').exists())
        except Exception as exc:
            self.details.setPlainText(str(exc))
            self.check_button.setEnabled(False)

    def check(self):
        env = self.selected()
        if not env:
            return
        def operation(manager):
            runtime = ProjectRuntime(self.project.path, manager.cancel, manager.on_output)
            target = runtime.check(env)
            binding = read_binding(self.project.path)
            if binding:
                source = manager.load(binding['environment_id'])
                if manager.running(source):
                    target['current_environment'] = manager.info(source)
            else:
                from core.docker import DockerManager
                source = DockerManager(self.project.path, cancel=manager.cancel)
                target['current_environment'] = source.get_php_info() if source.is_service_running('php') else '独立 PHP 已停止，实际扩展与配置未知'
            return target
        self.worker = run_environment_operation(self, self.project.path, '检查 PHP 环境', operation,
            lambda result: self.details.append('\n检查结果：\n' + json.dumps(result, ensure_ascii=False, indent=2)))

    def switch(self):
        env = self.selected()
        if not env:
            return
        confirmation = MessageBoxBase(self)
        confirmation.viewLayout.addWidget(BodyLabel('确认切换 PHP 环境'))
        details = TextEdit()
        details.setReadOnly(True)
        details.setPlainText(self.details.toPlainText())
        confirmation.viewLayout.addWidget(details, 1)
        confirmation.viewLayout.addWidget(CaptionLabel('提交时会重新检查环境运行状态。'))
        confirmation.widget.setFixedSize(self.width() - 48, self.height() - 48)
        confirmation.yesButton.setText('确认切换')
        confirmation.cancelButton.setText('取消')
        if not confirmation.exec():
            return
        self.worker = run_environment_operation(self, self.project.path, '切换 PHP 环境',
            lambda manager: ProjectRuntime(self.project.path, manager.cancel, manager.on_output).switch(env), self.done_switch)
        self.apply.setEnabled(False)
        self.worker.finished.connect(lambda success, message, logs: self.preview() if not success else None)

    def recover(self):
        self.worker = run_environment_operation(self, self.project.path, '恢复项目环境',
            lambda manager: ProjectRuntime(self.project.path, manager.cancel, manager.on_output).recover(), self.done_switch)

    def done_switch(self, result):
        self.changed.emit()
        self.accept()
