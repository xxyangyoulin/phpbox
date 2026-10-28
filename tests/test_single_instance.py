import os
import time
import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication
from ui.single_instance import SingleInstance


APP = QApplication.instance() or QApplication([])


class SingleInstanceTests(unittest.TestCase):
    def test_duplicate_launches_forward_requests_and_release_address(self):
        with patch('ui.single_instance.os.getuid', return_value=f'test-{os.getpid()}'):
            first = SingleInstance('show')
            self.addCleanup(first.close)
            self.assertTrue(first.is_primary)
            received = []
            for request in ['show', 'new-project', 'hide']:
                second = SingleInstance(request)
                self.assertFalse(second.is_primary)
            first.requested.connect(received.append)
            deadline = time.monotonic() + 2
            while len(received) < 3 and time.monotonic() < deadline:
                APP.processEvents()
                time.sleep(0.01)
            self.assertEqual(received, ['show', 'new-project', 'hide'])
            first.close()
            replacement = SingleInstance('show')
            self.addCleanup(replacement.close)
            self.assertTrue(replacement.is_primary)
