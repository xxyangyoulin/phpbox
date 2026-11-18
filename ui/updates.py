import json

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest

from core.settings import Settings
from core.updates import RELEASE_API, RELEASES_URL, newer_release
from core.version import VERSION


class UpdateChecker(QObject):
    changed = pyqtSignal()
    available = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        self.reply = None
        self.status = '自动检查正式发布版本，也可以手动检查。'
        self.release_url = RELEASES_URL
        self.startup = QTimer(self)
        self.startup.setSingleShot(True)
        self.startup.timeout.connect(self.check)
        self.periodic = QTimer(self)
        self.periodic.timeout.connect(self.check)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self._abort)

    def start(self):
        self.startup.start(30_000)
        self.periodic.start(6 * 60 * 60 * 1000)

    def check(self):
        if self.reply is not None:
            return
        proxy_url = Settings().get_proxy()
        proxy = QNetworkProxy(QNetworkProxy.ProxyType.DefaultProxy)
        if proxy_url:
            address = QUrl(proxy_url)
            proxy = QNetworkProxy(QNetworkProxy.ProxyType.HttpProxy, address.host(), address.port(8080))
        self.manager.setProxy(proxy)
        request = QNetworkRequest(QUrl(RELEASE_API))
        request.setRawHeader(b'Accept', b'application/vnd.github+json')
        request.setRawHeader(b'User-Agent', ('PHPBox/' + VERSION).encode())
        self.status = '正在检查更新…'
        self.reply = self.manager.get(request)
        self.reply.finished.connect(self._finished)
        self.timeout.start(15_000)
        self.changed.emit()

    def _abort(self):
        if self.reply is not None:
            self.reply.abort()

    def _finished(self):
        reply = self.reply
        self.reply = None
        self.timeout.stop()
        release = None
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.status = '暂时无法检查更新，请稍后重试或直接访问 GitHub 发布页。'
            else:
                release = newer_release(json.loads(bytes(reply.readAll())))
                if release:
                    version, self.release_url = release
                    self.status = f'发现新版本 {version}，当前版本为 {VERSION}。'
                else:
                    self.status = f'当前版本 {VERSION} 已是最新正式版。'
        except (ValueError, UnicodeError):
            self.status = '无法读取更新信息，请稍后重试或直接访问 GitHub 发布页。'
        finally:
            reply.deleteLater()
        self.changed.emit()
        if release:
            self.available.emit(*release)
