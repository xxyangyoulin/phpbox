import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PyQt6.QtCore import QObject, QSettings, pyqtSignal
from PyQt6.QtNetwork import QNetworkReply, QNetworkProxy
from PyQt6.QtWidgets import QApplication

from core.updates import REPOSITORY_URL, RELEASE_API, newer_release
from ui.dialogs.settings import SettingsDialog
from ui.main_window import MainWindow
from ui.updates import UpdateChecker


APP = QApplication.instance() or QApplication([])


class FakeReply(QObject):
    finished = pyqtSignal()

    def __init__(self, payload=None, error=QNetworkReply.NetworkError.NoError):
        super().__init__()
        self.payload = json.dumps(payload).encode()
        self.network_error = error

    def error(self):
        return self.network_error

    def readAll(self):
        return self.payload

    def abort(self):
        self.network_error = QNetworkReply.NetworkError.OperationCanceledError
        self.finished.emit()


class UpdateTests(unittest.TestCase):
    def test_only_new_stable_versions_and_trusted_links(self):
        for tag, newer in [('v2.1.1', False), ('2.0.9', False), ('v2.1.10', True), ('v3.0.0', True)]:
            result = newer_release({'tag_name': tag, 'html_url': 'https://untrusted.example'}, '2.1.1')
            self.assertEqual(bool(result), newer)
            if newer:
                self.assertEqual(result[1], REPOSITORY_URL + '/releases/tag/' + tag)
        for kind in ('draft', 'prerelease'):
            self.assertIsNone(newer_release({'tag_name': 'v9.0.0', kind: True}))
        for data in ([], {}, {'tag_name': 'latest'}, {'tag_name': 'v9.0.0/../../other'}):
            with self.assertRaises(ValueError):
                newer_release(data)

    def test_check_is_async_deduplicates_and_uses_software_proxy(self):
        reply = FakeReply({'tag_name': 'v99.0.0'})
        with patch('ui.updates.QNetworkAccessManager') as factory, \
             patch('ui.updates.Settings') as settings:
            settings.return_value.get_proxy.return_value = 'http://127.0.0.1:7890'
            factory.return_value.get.return_value = reply
            checker = UpdateChecker()
            self.addCleanup(checker.deleteLater)
            available = Mock()
            checker.available.connect(available)
            checker.check()
            checker.check()
            factory.return_value.get.assert_called_once()
            self.assertEqual(factory.return_value.get.call_args.args[0].url().toString(), RELEASE_API)
            proxy = factory.return_value.setProxy.call_args.args[0]
            self.assertEqual(proxy.type(), QNetworkProxy.ProxyType.HttpProxy)
            self.assertEqual((proxy.hostName(), proxy.port()), ('127.0.0.1', 7890))
            available.assert_not_called()
            reply.finished.emit()
            available.assert_called_once_with('99.0.0', REPOSITORY_URL + '/releases/tag/v99.0.0')
            self.assertIsNone(checker.reply)
            self.assertFalse(checker.timeout.isActive())
            self.assertIn('99.0.0', checker.status)

    def test_failure_timeout_and_invalid_json_allow_retry_without_notification(self):
        for outcome in ('network', 'timeout', 'invalid'):
            with self.subTest(outcome=outcome), patch('ui.updates.QNetworkAccessManager') as factory, \
                 patch('ui.updates.Settings') as settings:
                settings.return_value.get_proxy.return_value = None
                reply = FakeReply({})
                if outcome == 'network':
                    reply.network_error = QNetworkReply.NetworkError.HostNotFoundError
                if outcome == 'invalid':
                    reply.payload = b'<html>offline</html>'
                factory.return_value.get.return_value = reply
                checker = UpdateChecker()
                self.addCleanup(checker.deleteLater)
                available = Mock()
                checker.available.connect(available)
                checker.check()
                if outcome == 'timeout':
                    checker._abort()
                else:
                    reply.finished.emit()
                available.assert_not_called()
                self.assertIsNone(checker.reply)
                self.assertIn('重试', checker.status)
                next_reply = FakeReply({'tag_name': 'v1.0.0'})
                factory.return_value.get.return_value = next_reply
                checker.check()
                next_reply.finished.emit()
                self.assertIn('最新正式版', checker.status)

    def test_system_notification_once_per_version_even_when_hidden(self):
        with tempfile.TemporaryDirectory() as directory, patch('ui.main_window.Settings') as factory, \
             patch('ui.main_window.QSystemTrayIcon.isSystemTrayAvailable', return_value=True), \
             patch('ui.main_window.QSystemTrayIcon.supportsMessages', return_value=True):
            config = QSettings(str(Path(directory) / 'settings.ini'), QSettings.Format.IniFormat)
            factory.return_value.settings = config
            window = Mock()
            window.isVisible.return_value = False
            for version in ('9.0.0', '9.0.0', '9.0.1'):
                MainWindow._notify_update(window, version, REPOSITORY_URL)
            self.assertEqual(window.tray_icon.showMessage.call_count, 2)
            self.assertEqual(config.value('updates/notified_version'), '9.0.1')
            window._notify.assert_not_called()

    def test_settings_about_links_and_check_state(self):
        checker = UpdateChecker()
        self.addCleanup(checker.deleteLater)
        dialog = SettingsDialog(update_checker=checker)
        card = dialog.about_card
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        APP.processEvents()
        self.assertTrue(card.check_button.isEnabled())
        dialog.resize(560, 400)
        APP.processEvents()
        self.assertLessEqual(dialog.height(), 400)
        self.assertGreater(dialog.scroll.verticalScrollBar().maximum(), 0)
        self.assertTrue(dialog.save_btn.isVisible())
        checker.reply = FakeReply()
        checker.status = '正在检查更新…'
        checker.changed.emit()
        self.assertFalse(card.check_button.isEnabled())
        self.assertEqual(card.status.text(), checker.status)
        with patch('ui.dialogs.about.QDesktopServices.openUrl', return_value=True) as open_url:
            card.release_button.click()
            self.assertEqual(open_url.call_args.args[0].toString(), checker.release_url)
        checker.reply.deleteLater()
        checker.reply = None
        dialog.hide()
