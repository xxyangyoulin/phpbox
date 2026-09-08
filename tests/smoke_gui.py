from unittest.mock import patch

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from ui.main_window import ProjectDashboardPage
from ui.dialogs.create_project import CreateProjectDialog

app = QApplication([])
with patch('ui.main_window.ProjectManager'), patch('ui.dialogs.create_project.ProjectManager'), patch('core.docker.DockerManager._detect_compose'):
    dashboard = ProjectDashboardPage()
    creator = CreateProjectDialog()
    dashboard.show()
    creator.show()
    QTimer.singleShot(200, dashboard.hide)
    QTimer.singleShot(200, creator.hide)
    QTimer.singleShot(250, app.quit)
    raise SystemExit(app.exec())
