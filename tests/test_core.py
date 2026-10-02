"""Tests intentionally import no GTK and can run on Linux or Windows."""

import unittest
import configparser
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from mailflag.core.delivery import DeliveryClass, classify_delivery, uid_window
from mailflag.core.models import AccountProfile, MessageIdentity
from mailflag.core.monitor import (
    MonitorConfig, _mailbox_session, reconnect_delay, refresh_folder_status,
)
from mailflag.core.otp import MIN_CONFIDENCE, confidence, extract_code
from mailflag.core.accounts import configured_emails
from mailflag.core.actions import move_exact
from mailflag.core.state import read_store, write_store
from mailflag.providers.yahoo import YAHOO


class PortableCore(unittest.TestCase):
    def test_delivery_classification(self):
        self.assertEqual(classify_delivery(), DeliveryClass.LIVE)
        self.assertEqual(classify_delivery(startup=True), DeliveryClass.PENDING)
        self.assertEqual(classify_delivery(resumed=True), DeliveryClass.PENDING)
        self.assertEqual(classify_delivery(outage_seconds=91), DeliveryClass.PENDING)

    def test_uid_window(self):
        self.assertEqual(list(uid_window(40, 44)), [41, 42, 43])
        self.assertEqual(list(uid_window(43, 44)), [])

    def test_models_include_folder_and_uidvalidity(self):
        account = AccountProfile('a@example.test', 'yahoo')
        identity = MessageIdentity(account.email, 'INBOX', 7, 42, '<id@test>')
        self.assertEqual(account.folders, ('INBOX',))
        self.assertEqual(identity.uidvalidity, 7)

    def test_provider_profile_owns_yahoo_values(self):
        self.assertEqual(YAHOO.imap_host, 'imap.mail.yahoo.com')
        self.assertEqual(YAHOO.spam_folder, 'Bulk')

    def test_monitor_config_is_platform_neutral(self):
        config = MonitorConfig()
        self.assertEqual(config.idle_timeout, 10)
        self.assertEqual(config.socket_timeout, 15)
        self.assertEqual(config.watchdog_timeout, 20)

    def test_reconnect_backoff_is_fast_then_bounded(self):
        config = MonitorConfig()
        self.assertEqual(
            [reconnect_delay(config, index) for index in range(8)],
            [3, 5, 10, 20, 40, 60, 60, 60],
        )

    def test_folder_refresh_prefers_fresh_select_response_codes(self):
        box = Mock()
        box.client.response.side_effect = [
            ("UIDVALIDITY", [b"7"]),
            ("UIDNEXT", [b"346"]),
        ]
        box.folder.status.return_value = {"UIDVALIDITY": 7, "UIDNEXT": 345}
        self.assertEqual(
            refresh_folder_status(box, "INBOX"),
            {"UIDVALIDITY": 7, "UIDNEXT": 346},
        )
        box.folder.set.assert_called_once_with("INBOX", readonly=True)
        box.folder.status.assert_not_called()

    def test_folder_refresh_falls_back_to_status(self):
        box = Mock()
        box.client.response.side_effect = [(None, None), (None, None)]
        box.folder.status.return_value = {"UIDVALIDITY": 7, "UIDNEXT": 346}
        self.assertEqual(
            refresh_folder_status(box, "INBOX"),
            {"UIDVALIDITY": 7, "UIDNEXT": 346},
        )

    def test_logout_cleanup_does_not_hide_original_connection_error(self):
        box = Mock()
        box.logout.side_effect = OSError("logout EOF")
        with self.assertRaisesRegex(RuntimeError, "original failure"):
            with _mailbox_session(box):
                raise RuntimeError("original failure")

    def test_otp_true_and_false(self):
        self.assertEqual(extract_code('Your verification code is 482913', ''),
                         '482913')
        github = ('7776 [repo] Run failed: Android verification - branch '
                  'feature/v0.4.0 (c377668)')
        self.assertIsNone(extract_code(github, 'workflow build failed'))
        score, _ = confidence('workflow build verification code 482913',
                              'branch commit test failed')
        self.assertLess(score, MIN_CONFIDENCE)

    def test_account_config_backward_compatibility(self):
        config = configparser.ConfigParser()
        config.read_dict({
            'account': {'email': 'old@example.test'},
            'accounts': {'emails': 'old@example.test\nnew@example.test'},
        })
        self.assertEqual(configured_emails(config),
                         ['old@example.test', 'new@example.test'])

    def test_state_codec_and_legacy_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            store = {'version': 2, 'accounts': {'a@example.test': {
                'uidvalidity': 7, 'last_processed_uid': 42,
                'pending_uids': [42, 42],
                'message_refs': {'42': {'message_id': '<id@test>'}},
            }}}
            write_store(path, store)
            loaded = read_store(path)
            self.assertEqual(loaded['accounts']['a@example.test']['pending_uids'], [42])
            self.assertEqual(loaded['accounts']['a@example.test']['message_refs']['42']['message_id'], '<id@test>')
            path.write_text('{"uidvalidity":9,"last_processed_uid":10,"pending_uids":[]}', encoding='utf-8')
            self.assertIn('__legacy__', read_store(path)['accounts'])

    def test_core_has_no_desktop_or_linux_imports(self):
        core = Path(__file__).parents[1] / 'mailflag' / 'core'
        text = '\n'.join(path.read_text(encoding='utf-8')
                         for path in core.glob('*.py'))
        for forbidden in ('gi.repository', 'secret-tool', 'xdg-open',
                          'notify-send', 'AyatanaAppIndicator'):
            self.assertNotIn(forbidden, text)

    def test_exact_move_uses_validated_uid_and_destination(self):
        box = Mock()
        box.login.return_value = box
        box.__enter__ = Mock(return_value=box)
        box.__exit__ = Mock(return_value=False)
        box.folder.status.return_value = {'UIDVALIDITY': 7}
        box.fetch.return_value = [SimpleNamespace(uid='42')]
        destination = Mock(return_value='Trash')
        self.assertTrue(move_exact(lambda _host: box, 'imap.test', 'INBOX',
                                   'a@test', 'secret', 42, 7, destination))
        box.move.assert_called_once_with(['42'], 'Trash')
        self.assertFalse(move_exact(lambda _host: box, 'imap.test', 'INBOX',
                                    'a@test', 'secret', '42:*', 7, destination))


if __name__ == '__main__':
    unittest.main()
