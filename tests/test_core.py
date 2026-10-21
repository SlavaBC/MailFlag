"""Tests intentionally import no GTK and can run on Linux or Windows."""

import unittest
import configparser
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mailflag.core.delivery import DeliveryClass, classify_delivery, uid_window
from mailflag.core.models import AccountProfile, MessageIdentity
from mailflag.core.monitor import (
    MonitorConfig, _mailbox_session, reconnect_delay, refresh_folder_status,
    run_account_monitor,
)
from mailflag.core.otp import MIN_CONFIDENCE, confidence, extract_code
from mailflag.core.accounts import (
    configured_emails, configured_folders, set_configured_folders,
)
from mailflag.core.actions import move_exact
from mailflag.core.state import read_store, write_store
from mailflag.providers.yahoo import YAHOO
from mailflag.providers.custom import custom_imap_profile
from mailflag.folders import selectable_folder_names
from mailflag.single_instance import acquire_instance_lock


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

    def test_custom_provider_owns_endpoint_and_transport(self):
        provider = custom_imap_profile('imap.example.test', 143, False, 'Work')
        self.assertEqual(provider.provider_id, 'custom_imap')
        self.assertEqual(provider.imap_host, 'imap.example.test')
        self.assertEqual(provider.imap_port, 143)
        self.assertFalse(provider.imap_ssl)
        self.assertIsNone(provider.spam_folder)

    def test_monitor_uses_separate_account_identity_and_login_username(self):
        box = Mock()
        box.login.return_value = box
        box.idle.wait.side_effect = SystemExit()
        factory = Mock(return_value=box)
        platform = Mock()
        platform.power_clock_snapshot.return_value = 0
        platform.suspend_gap_since.return_value = 0
        events = Mock()
        events.monitored_folders.return_value = ['INBOX']
        events.recover_pending.return_value = 0
        with patch('mailflag.core.monitor.refresh_folder_status',
                   return_value={'UIDVALIDITY': 1, 'UIDNEXT': 2}):
            with self.assertRaises(SystemExit):
                run_account_monitor(
                    'custom-stable-id', 'secret',
                    custom_imap_profile('imap.example.test'), factory,
                    platform, events, Mock(), MonitorConfig(),
                    username='actual-login@example.test',
                )
        box.login.assert_called_once_with(
            'actual-login@example.test', 'secret', initial_folder=None
        )

    def test_custom_monitor_reconnects_after_transient_failure(self):
        box = Mock()
        box.login.return_value = box
        box.idle.wait.side_effect = SystemExit()
        factory = Mock(side_effect=[OSError('temporary network loss'), box])
        platform = Mock()
        platform.power_clock_snapshot.return_value = 0
        platform.suspend_gap_since.return_value = 0
        events = Mock()
        events.monitored_folders.return_value = ['INBOX']
        events.recover_pending.return_value = 0
        reconnect = threading.Event()
        with patch('mailflag.core.monitor.refresh_folder_status',
                   return_value={'UIDVALIDITY': 1, 'UIDNEXT': 2}):
            with self.assertRaises(SystemExit):
                run_account_monitor(
                    'custom-id', 'secret',
                    custom_imap_profile('imap.example.test'), factory,
                    platform, events, reconnect,
                    MonitorConfig(reconnect_delays=(0,)), username='login',
                )
        self.assertEqual(factory.call_count, 2)
        events.interrupted.assert_called_once()
        box.login.assert_called_once_with('login', 'secret', initial_folder=None)

    def test_monitor_config_is_platform_neutral(self):
        config = MonitorConfig()
        self.assertEqual(config.idle_timeout, 10)
        self.assertEqual(config.socket_timeout, 15)
        self.assertEqual(config.watchdog_timeout, 20)
        self.assertEqual(config.extra_folder_poll_seconds, 30)

    def test_reconnect_backoff_is_fast_then_bounded(self):
        config = MonitorConfig()
        self.assertEqual(
            [reconnect_delay(config, index) for index in range(8)],
            [3, 5, 10, 20, 40, 60, 60, 60],
        )

    def test_monitor_does_not_connect_when_account_is_stopped(self):
        stop = threading.Event()
        stop.set()
        factory = Mock()
        events = Mock()
        run_account_monitor(
            'a@test', 'secret', YAHOO, factory, Mock(), events,
            threading.Event(), MonitorConfig(), stop_event=stop,
        )
        factory.assert_not_called()
        events.connection_changed.assert_not_called()

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

    def test_monitor_uses_one_connection_for_inbox_and_extra_folder(self):
        box = Mock()
        box.login.return_value = box
        box.idle.wait.return_value = []
        factory = Mock(return_value=box)
        platform = Mock()
        platform.power_clock_snapshot.return_value = 0
        platform.suspend_gap_since.return_value = 0
        events = Mock()
        events.monitored_folders.return_value = ['INBOX', 'Amazon']
        events.recover_pending.return_value = 0

        def process_live(_box, _account, folder, *_args):
            if folder == 'Amazon':
                raise SystemExit()
            return 0
        events.process_live.side_effect = process_live
        states = [
            {'UIDVALIDITY': 1, 'UIDNEXT': 10},  # initial INBOX
            {'UIDVALIDITY': 2, 'UIDNEXT': 20},  # startup Amazon
            {'UIDVALIDITY': 1, 'UIDNEXT': 10},  # restore INBOX
            {'UIDVALIDITY': 1, 'UIDNEXT': 11},  # live INBOX
            {'UIDVALIDITY': 2, 'UIDNEXT': 21},  # live Amazon
        ]
        config = MonitorConfig(extra_folder_poll_seconds=0)
        with patch('mailflag.core.monitor.refresh_folder_status',
                   side_effect=states):
            with self.assertRaises(SystemExit):
                run_account_monitor(
                    'a@test', 'secret', YAHOO, factory, platform, events,
                    Mock(), config,
                )
        factory.assert_called_once()
        recovered_folders = [call.args[2]
                             for call in events.recover_pending.call_args_list]
        self.assertEqual(recovered_folders, ['INBOX', 'Amazon'])
        live_folders = [call.args[2]
                        for call in events.process_live.call_args_list]
        self.assertEqual(live_folders, ['INBOX', 'Amazon'])

    def test_missing_extra_folder_does_not_stop_inbox(self):
        box = Mock()
        box.login.return_value = box
        box.idle.wait.side_effect = SystemExit()
        factory = Mock(return_value=box)
        platform = Mock()
        platform.power_clock_snapshot.return_value = 0
        platform.suspend_gap_since.return_value = 0
        events = Mock()
        events.monitored_folders.return_value = ['INBOX', 'Missing']
        events.recover_pending.return_value = 0
        states = [
            {'UIDVALIDITY': 1, 'UIDNEXT': 10},
            RuntimeError('folder not found'),
            {'UIDVALIDITY': 1, 'UIDNEXT': 10},
        ]
        with patch('mailflag.core.monitor.refresh_folder_status',
                   side_effect=states):
            with self.assertRaises(SystemExit):
                run_account_monitor(
                    'a@test', 'secret', YAHOO, factory, platform, events,
                    Mock(), MonitorConfig(),
                )
        events.folder_error.assert_called_once()
        self.assertEqual(events.folder_error.call_args.args[1], 'Missing')

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

    def test_monitored_folders_are_per_account_and_inbox_is_default(self):
        config = configparser.ConfigParser()
        self.assertEqual(configured_folders(config, 'a@test'), ['INBOX'])
        set_configured_folders(config, 'a@test', ['Amazon', 'Bank'])
        set_configured_folders(config, 'b@test', ['Orders'])
        self.assertEqual(
            configured_folders(config, 'a@test'),
            ['INBOX', 'Amazon', 'Bank'],
        )
        self.assertEqual(
            configured_folders(config, 'b@test'),
            ['INBOX', 'Orders'],
        )

    def test_monitored_folder_normalization_deduplicates_inbox(self):
        config = configparser.ConfigParser()
        set_configured_folders(config, 'a@test', ['inbox', 'Amazon', 'amazon'])
        self.assertEqual(configured_folders(config, 'a@test'), ['INBOX', 'Amazon'])

    def test_folder_discovery_excludes_action_and_noselect_folders(self):
        folders = [
            SimpleNamespace(name='INBOX', flags=()),
            SimpleNamespace(name='Amazon', flags=()),
            SimpleNamespace(name='Bulk', flags=(r'\Junk',)),
            SimpleNamespace(name='Trash', flags=(r'\Trash',)),
            SimpleNamespace(name='Parent', flags=(r'\Noselect',)),
            SimpleNamespace(name='Orders/2026', flags=()),
        ]
        self.assertEqual(
            selectable_folder_names(folders),
            ['Amazon', 'Orders/2026'],
        )

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
            inbox = loaded['accounts']['a@example.test']['folders']['INBOX']
            self.assertEqual(inbox['pending_uids'], [42])
            self.assertEqual(inbox['message_refs']['42']['message_id'], '<id@test>')
            self.assertEqual(loaded['version'], 3)
            path.write_text('{"uidvalidity":9,"last_processed_uid":10,"pending_uids":[]}', encoding='utf-8')
            self.assertIn('__legacy__', read_store(path)['accounts'])

    def test_state_keeps_independent_folder_checkpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            write_store(path, {'accounts': {'a@example.test': {'folders': {
                'INBOX': {'uidvalidity': 7, 'last_processed_uid': 10,
                          'pending_uids': [10], 'message_refs': {}},
                'Amazon': {'uidvalidity': 8, 'last_processed_uid': 20,
                           'pending_uids': [19], 'message_refs': {}},
            }}}})
            folders = read_store(path)['accounts']['a@example.test']['folders']
            self.assertEqual(folders['INBOX']['last_processed_uid'], 10)
            self.assertEqual(folders['Amazon']['last_processed_uid'], 20)
            self.assertEqual(folders['Amazon']['pending_uids'], [19])

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

    def test_single_instance_lock_blocks_second_process_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'instance.lock'
            first = acquire_instance_lock(path)
            self.assertIsNotNone(first)
            self.assertIsNone(acquire_instance_lock(path))
            first.close()
            second = acquire_instance_lock(path)
            self.assertIsNotNone(second)
            second.close()


if __name__ == '__main__':
    unittest.main()
