import errno
import os
import socket

from PyQt6.QtCore import QObject, QSocketNotifier, pyqtSignal


class SingleInstance(QObject):
    requested = pyqtSignal(str)

    def __init__(self, request, parent=None):
        super().__init__(parent)
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        address = f"\0phpbox-gui-{os.getuid()}"
        try:
            self.socket.bind(address)
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                self.socket.close()
                raise
            try:
                self.socket.sendto(request.encode(), address)
            finally:
                self.socket.close()
            self.is_primary = False
            return
        self.is_primary = True
        self.socket.setblocking(False)
        self.notifier = QSocketNotifier(self.socket.fileno(), QSocketNotifier.Type.Read, self)
        self.notifier.activated.connect(self._receive)

    def _receive(self):
        self.requested.emit(self.socket.recv(64).decode('utf-8', errors='replace'))

    def close(self):
        if self.is_primary:
            self.notifier.setEnabled(False)
        self.socket.close()
