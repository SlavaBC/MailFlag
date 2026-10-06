"""Headless tests for the public-beta settings model and lifecycle control."""

import configparser
import socket
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mailflag.ipc import ControlServer, send_command
from mailflag.platform.base import AppPaths
from mailflag.settings_service import POPUP_DURATIONS, SettingsService, otp_timeout
from mailflag import remove_account as remove_module


class FakeCredentials:
    def __init__(self): self.values = {}
    def get(self, account): return self.values.get(account, "")
    def set(self, account, secret): self.values[account] = secret
    def delete(self, account): self.values.pop(account, None)


class SettingsModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.platform = SimpleNamespace(
            paths=AppPaths(root, root, root / "cache", root),
            credentials=FakeCredentials(),
        )
        self.box = Mock()
        self.box.login.return_value = self.box
        self.box.__enter__ = Mock(return_value=self.box)
        self.box.__exit__ = Mock(return_value=False)
        self.box.folder.status.return_value = {"UIDVALIDITY": 1, "UIDNEXT": 2}
        self.factory = Mock(return_value=self.box)
        self.service = SettingsService(self.platform, self.factory)

    def test_fresh_install_has_no_accounts_and_defaults(self):
        self.assertEqual(self.service.accounts(), [])
        self.assertEqual(self.service.notification_preferences(), {
            "show_popup": True, "play_sound": True, "popup_duration": 30,
        })

    def test_add_yahoo_account_tests_connection_and_uses_keyring(self):
        self.service.add_yahoo_account("a@yahoo.com", "app-password")
        self.assertEqual(self.service.accounts(), ["a@yahoo.com"])
        self.assertEqual(self.platform.credentials.get("a@yahoo.com"), "app-password")
        text = self.platform.paths.config_file.read_text()
        self.assertNotIn("app-password", text)
        self.box.folder.status.assert_called_with("INBOX")

    def test_wrong_password_does_not_write_account_or_credential(self):
        self.box.folder.status.side_effect = OSError("authentication rejected")
        with self.assertRaises(OSError):
            self.service.add_yahoo_account("a@yahoo.com", "wrong")
        self.assertEqual(self.service.accounts(), [])
        self.assertEqual(self.platform.credentials.values, {})

    def test_two_accounts_keep_independent_folders(self):
        self.service.add_yahoo_account("a@yahoo.com", "one")
        self.service.add_yahoo_account("b@yahoo.com", "two")
        self.service.update_folders("a@yahoo.com", ["INBOX", "Amazon"])
        self.service.update_folders("b@yahoo.com", ["INBOX", "Bank"])
        self.assertEqual(self.service.folders("a@yahoo.com"), ["INBOX", "Amazon"])
        self.assertEqual(self.service.folders("b@yahoo.com"), ["INBOX", "Bank"])

    def test_remove_one_account_keeps_other_and_deletes_only_its_secret(self):
        self.service.add_yahoo_account("a@yahoo.com", "one")
        self.service.add_yahoo_account("b@yahoo.com", "two")
        self.service.remove_account("a@yahoo.com")
        self.assertEqual(self.service.accounts(), ["b@yahoo.com"])
        self.assertNotIn("a@yahoo.com", self.platform.credentials.values)
        self.assertEqual(self.platform.credentials.get("b@yahoo.com"), "two")

    def test_edit_account_retests_and_replaces_only_credential(self):
        self.service.add_yahoo_account("a@yahoo.com", "one")
        self.service.update_yahoo_credential("a@yahoo.com", "replacement")
        self.assertEqual(self.service.accounts(), ["a@yahoo.com"])
        self.assertEqual(self.platform.credentials.get("a@yahoo.com"), "replacement")

    def test_notification_durations_and_otp_cap(self):
        for duration in POPUP_DURATIONS:
            self.service.save_notification_preferences(False, False, duration)
            prefs = self.service.notification_preferences()
            self.assertEqual(prefs["popup_duration"], duration)
            self.assertEqual(otp_timeout(duration), min(30, duration))

    def test_invalid_duration_is_rejected(self):
        with self.assertRaises(ValueError):
            self.service.save_notification_preferences(True, True, 37)

    def test_config_is_written_private(self):
        self.service.add_yahoo_account("a@yahoo.com", "one")
        self.assertEqual(self.platform.paths.config_file.stat().st_mode & 0o777, 0o600)


class IpcTests(unittest.TestCase):
    def test_background_control_socket_receives_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "control.sock"
            commands = []
            server = ControlServer(path, commands.append)
            try:
                server.start()
            except PermissionError:
                server.close()
                self.skipTest("Unix sockets are blocked by this test sandbox")
            self.addCleanup(server.close)
            for _ in range(20):
                if send_command(path, "stop"): break
                time.sleep(0.01)
            for _ in range(20):
                if commands: break
                time.sleep(0.01)
            self.assertEqual(commands, ["stop"])

    def test_missing_background_socket_is_harmless(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(send_command(Path(directory) / "missing.sock", "stop"))


class RemoveAccountCliTests(unittest.TestCase):
    def test_cli_requires_confirmation_and_delegates_safe_removal(self):
        service = Mock()
        service.accounts.return_value = ["a@yahoo.com"]
        with patch.object(remove_module, "SettingsService", return_value=service):
            self.assertFalse(remove_module.remove_account(input_fn=lambda _p: "n"))
            service.remove_account.assert_not_called()
            self.assertTrue(remove_module.remove_account(input_fn=lambda _p: "y"))
            service.remove_account.assert_called_once_with("a@yahoo.com")


if __name__ == "__main__":
    unittest.main()
