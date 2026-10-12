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
from mailflag.__main__ import should_open_settings
from mailflag.platform.base import AppPaths
from mailflag.core.state import read_store, write_store
from mailflag.settings_service import POPUP_DURATIONS, SettingsService, otp_timeout
from mailflag import remove_account as remove_module
from mailflag import shutdown as shutdown_module


class FakeCredentials:
    def __init__(self):
        self.values = {}
        self.delete_error = None
    def get(self, account): return self.values.get(account, "")
    def set(self, account, secret): self.values[account] = secret
    def delete(self, account):
        if self.delete_error:
            raise self.delete_error
        self.values.pop(account, None)


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
        write_store(self.platform.paths.state_file, {
            "accounts": {
                "a@yahoo.com": {"folders": {"INBOX": {
                    "uidvalidity": 1, "last_processed_uid": 4,
                    "pending_uids": [4], "message_refs": {},
                }}},
                "b@yahoo.com": {"folders": {"INBOX": {
                    "uidvalidity": 2, "last_processed_uid": 8,
                    "pending_uids": [8], "message_refs": {},
                }}},
            },
        })
        self.service.remove_account("a@yahoo.com")
        self.assertEqual(self.service.accounts(), ["b@yahoo.com"])
        self.assertNotIn("a@yahoo.com", self.platform.credentials.values)
        self.assertEqual(self.platform.credentials.get("b@yahoo.com"), "two")
        state = read_store(self.platform.paths.state_file)
        self.assertNotIn("a@yahoo.com", state["accounts"])
        self.assertEqual(
            state["accounts"]["b@yahoo.com"]["folders"]["INBOX"]["pending_uids"],
            [8],
        )

    def test_keyring_delete_failure_changes_nothing(self):
        self.service.add_yahoo_account("a@yahoo.com", "one")
        write_store(self.platform.paths.state_file, {
            "accounts": {"a@yahoo.com": {"folders": {"INBOX": {
                "uidvalidity": 1, "last_processed_uid": 4,
                "pending_uids": [4], "message_refs": {},
            }}}},
        })
        before_config = self.platform.paths.config_file.read_text()
        before_state = self.platform.paths.state_file.read_text()
        self.platform.credentials.delete_error = RuntimeError("keyring unavailable")
        with self.assertRaisesRegex(RuntimeError, "keyring unavailable"):
            self.service.remove_account("a@yahoo.com")
        self.assertEqual(self.platform.paths.config_file.read_text(), before_config)
        self.assertEqual(self.platform.paths.state_file.read_text(), before_state)
        self.assertEqual(self.platform.credentials.get("a@yahoo.com"), "one")

    def test_removed_account_can_be_added_again_as_new(self):
        self.service.add_yahoo_account("a@yahoo.com", "one")
        self.service.remove_account("a@yahoo.com")
        self.assertEqual(self.service.accounts(), [])
        self.service.add_yahoo_account("a@yahoo.com", "new-secret")
        self.assertEqual(self.service.accounts(), ["a@yahoo.com"])
        self.assertEqual(
            self.platform.credentials.get("a@yahoo.com"), "new-secret"
        )

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

    def test_desktop_startup_opens_settings_only_for_fresh_profile(self):
        self.assertTrue(should_open_settings(["--startup"], []))
        self.assertFalse(should_open_settings(["--startup"], ["a@yahoo.com"]))
        self.assertTrue(should_open_settings(["--settings"], None))
        self.assertFalse(should_open_settings(["--background"], None))


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


class ShutdownTests(unittest.TestCase):
    def test_process_scan_matches_only_mailflag_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = {
                101: ["/usr/bin/python3", "-m", "mailflag", "--background"],
                102: ["/usr/bin/python3", "-m", "mailflag", "--settings"],
                103: ["/usr/bin/python3", "-m", "other_app", "--background"],
                104: ["/usr/bin/python3", "worker-mailflag.py"],
                105: ["/usr/bin/python3", "-m", "mailflag", "--shutdown"],
            }
            for pid, argv in cases.items():
                process = root / str(pid)
                process.mkdir()
                (process / "cmdline").write_bytes(
                    b"\0".join(item.encode() for item in argv) + b"\0"
                )
                (process / "status").write_text("Name:\tpython3\nUid:\t1000 1000 1000 1000\n")
            found = shutdown_module.mailflag_processes(root)
            self.assertEqual([pid for pid, _uid, _argv in found], [101, 102])

    def test_graceful_shutdown_contacts_both_sockets_for_each_user(self):
        processes = [
            (101, 1000, ["python3", "-m", "mailflag", "--background"]),
            (102, 1000, ["python3", "-m", "mailflag", "--settings"]),
            (201, 1001, ["python3", "-m", "mailflag", "--background"]),
        ]
        homes = {1000: Path("/home/one"), 1001: Path("/home/two")}
        with patch.object(shutdown_module, "mailflag_processes", return_value=processes), \
             patch.object(shutdown_module, "_home_for_uid", side_effect=homes.get), \
             patch.object(shutdown_module, "send_command", return_value=True) as send:
            self.assertEqual(shutdown_module.graceful_shutdown(), 4)
        paths = {call.args[0] for call in send.call_args_list}
        self.assertEqual(paths, {
            Path("/home/one/.config/mailflag/control.sock"),
            Path("/home/one/.config/mailflag/settings-control.sock"),
            Path("/home/two/.config/mailflag/control.sock"),
            Path("/home/two/.config/mailflag/settings-control.sock"),
        })


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
