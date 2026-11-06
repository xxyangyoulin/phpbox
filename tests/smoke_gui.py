from unittest.mock import patch

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow, ProjectDashboardPage
from ui.dialogs.create_project import CreateProjectDialog
from ui.environments import EnvironmentsPage, EnvironmentEditor

app = QApplication([])
with patch('ui.main_window.ProjectManager'), patch('ui.dialogs.create_project.ProjectManager'), patch('core.docker.DockerManager._detect_compose'), \
     patch.object(MainWindow, 'load_projects'), patch.object(MainWindow, 'setup_tray'):
    window = MainWindow()
    dashboard = ProjectDashboardPage()
    creator = CreateProjectDialog()
    environments = EnvironmentsPage()
    editor = EnvironmentEditor()
    dashboard.show()
    creator.show()
    environments.show()
    editor.show()
    window.show()
    QTimer.singleShot(200, dashboard.hide)
    QTimer.singleShot(200, creator.hide)
    QTimer.singleShot(200, environments.hide)
    QTimer.singleShot(200, editor.hide)
    QTimer.singleShot(200, window.hide)
    QTimer.singleShot(250, app.quit)
    raise SystemExit(app.exec())
