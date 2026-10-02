import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from mailflag import app, opening, sound
from mailflag.core.actions import mark_exact_read
from mailflag.core.session import reconnect_is_live
from mailflag.core.status import ConnectionStatus, stale_connected_accounts


class Actions(unittest.TestCase):
    def box(self, validity=7, uids=('42',), flags=(r'\Seen',)):
        b = Mock()
        b.login.return_value = b
        b.__enter__ = Mock(return_value=b)
        b.__exit__ = Mock(return_value=False)
        b.folder.status.return_value = {'UIDVALIDITY': validity}
        b.fetch.return_value = [SimpleNamespace(uid=u, flags=flags) for u in uids]
        return b

    def run_action(self, b, uid='42'):
        return mark_exact_read(lambda host: b, 'imap.example.test', 'INBOX',
                               'a@example.test', '', uid, 7)

    def test_exact_seen(self):
        b = self.box()
        self.assertTrue(self.run_action(b))
        b.flag.assert_called_once_with(['42'], r'\Seen', True)
        for call in b.fetch.call_args_list:
            self.assertFalse(call.kwargs['mark_seen'])

    def test_reject_changed_missing_wrong_multiple(self):
        for b in (self.box(8), self.box(uids=()), self.box(uids=('43',)),
                  self.box(uids=('42','43'))):
            self.assertFalse(self.run_action(b))
            b.flag.assert_not_called()

    def test_reject_uid_sets_and_invalid_ids(self):
        for uid in ('1:*', '42,43', '0', '-1', '4294967296'):
            b = self.box()
            self.assertFalse(self.run_action(b, uid))
            b.login.assert_not_called()

    def test_validity_changes_before_store(self):
        b = self.box()
        b.folder.status.side_effect = [{'UIDVALIDITY':7}, {'UIDVALIDITY':8}]
        self.assertFalse(self.run_action(b))
        b.flag.assert_not_called()

    def test_failed_store_or_unconfirmed_seen(self):
        b = self.box()
        b.flag.side_effect = OSError('offline')
        self.assertFalse(self.run_action(b))
        self.assertFalse(self.run_action(self.box(flags=())))


class ConnectionHealth(unittest.TestCase):
    def test_aggregate_transitions(self):
        changes = []
        status = ConnectionStatus(('a', 'b'), lambda: changes.append(True))
        self.assertEqual(status.aggregate(), 'connecting')
        status.update('a', 'connected', 'Connected')
        self.assertEqual(status.aggregate(), 'partial')
        status.update('b', 'connected', 'Connected')
        self.assertEqual(status.aggregate(), 'online')
        status.update('a', 'error', 'EOF')
        self.assertEqual(status.aggregate(), 'partial')
        status.update('b', 'error', 'Timeout')
        self.assertEqual(status.aggregate(), 'offline')
        self.assertEqual(len(changes), 4)

    def test_snapshot_is_a_copy(self):
        status = ConnectionStatus(('a',))
        snapshot = status.snapshot()
        snapshot['a']['state'] = 'error'
        self.assertEqual(status.aggregate(), 'connecting')

    def test_stale_connected_account(self):
        snapshot = {
            'fresh': {'state': 'connected', 'last_connected_at': 100},
            'stale': {'state': 'connected', 'last_connected_at': 10},
            'failed': {'state': 'error', 'last_connected_at': 1},
        }
        self.assertEqual(
            stale_connected_accounts(snapshot, now=120, max_age=60),
            ['stale'],
        )

    def test_stale_socket_is_interrupted(self):
        mailbox = Mock()
        app.register_active_mailbox('a', mailbox)
        self.addCleanup(app.unregister_active_mailbox, 'a')
        self.assertTrue(app.interrupt_stale_mailbox('a'))
        mailbox.client.sock.shutdown.assert_called_once_with(app.socket.SHUT_RDWR)
        mailbox.client.sock.close.assert_called_once()

    def test_watchdog_marks_stalled_connection_and_closes_socket(self):
        clock = Mock(return_value=0.0)
        status = ConnectionStatus(('a',), clock=clock)
        status.update('a', 'connected', 'Connected')
        tray = object.__new__(app.TrayIndicator)
        tray.connection_status = status
        tray.unhealthy_since = None
        tray.outage_notified = False
        with patch.object(app.time, 'monotonic', return_value=21.0), \
                patch.object(app, 'interrupt_stale_mailbox', return_value=True) as interrupt, \
                patch.object(app, 'log_diagnostic'):
            self.assertTrue(tray._health_timer())
        interrupt.assert_called_once_with('a')
        snapshot = status.snapshot()['a']
        self.assertEqual(snapshot['state'], 'error')
        self.assertIn('reconnecting', snapshot['detail'])


class NotificationSound(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / 'config.ini'
        self.default = Path(self.tmp.name) / 'default.wav'
        self.default.write_bytes(b'RIFF-test')
        self.config.write_text('[accounts]\nemails = account@example.test\n')
        self.patches = [
            patch.object(sound, 'CONFIG_FILE', self.config),
            patch.object(sound, 'DEFAULT_SOUND', self.default),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_default_silent_and_custom_choice(self):
        self.assertEqual(sound.selected_sound_path(), self.default)
        sound.set_sound_choice('silent')
        self.assertIsNone(sound.selected_sound_path())
        self.assertIn('account@example.test', self.config.read_text())
        custom = Path(self.tmp.name) / 'custom %.ogg'
        custom.write_bytes(b'OggS-test')
        sound.set_sound_choice(custom)
        self.assertEqual(sound.selected_sound_path(), custom.resolve())

    def test_invalid_choice_is_rejected(self):
        invalid = Path(self.tmp.name) / 'sound.mp3'
        invalid.write_bytes(b'not-supported')
        with self.assertRaises(ValueError):
            sound.set_sound_choice(invalid)

    def test_silent_never_starts_player(self):
        sound.set_sound_choice('silent')
        with patch.object(sound.PLATFORM, 'play_audio') as start:
            self.assertFalse(sound.play_notification(force=True))
            start.assert_not_called()


class MailOpening(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / 'config.ini'
        self.config.write_text('[accounts]\nemails = account@example.test\n')
        patcher = patch.object(opening, 'CONFIG_FILE', self.config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_and_persisted_yahoo_mode(self):
        self.assertEqual(opening.get_open_mode(), opening.SYSTEM_DEFAULT)
        opening.set_open_mode(opening.YAHOO_WEBMAIL)
        self.assertEqual(opening.get_open_mode(), opening.YAHOO_WEBMAIL)
        self.assertIn('account@example.test', self.config.read_text())

    def test_yahoo_uses_stable_inbox_url(self):
        self.assertEqual(opening.YAHOO_MAIL_URL, 'https://mail.yahoo.com/')

    def test_both_launch_modes(self):
        with patch.object(opening.PLATFORM, 'open_default_mail_client',
                          return_value=True):
            self.assertTrue(opening.launch_system_default())
        opening.set_open_mode(opening.YAHOO_WEBMAIL)
        with patch.object(opening.PLATFORM, 'open_url', return_value=True) as start:
            self.assertTrue(opening.launch_selected_mode())
            start.assert_called_once_with('https://mail.yahoo.com/')


class StateAndUI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patches = [patch.object(app,'CONFIG_DIR',Path(self.tmp.name)),
                        patch.object(app,'STATE_FILE',Path(self.tmp.name)/'state.json'),
                        patch.object(app,'DIAGNOSTICS',Mock()),
                        patch.object(app,'refresh_indicator_async')]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_account_isolation_and_reset(self):
        app.save_mail_state('a', 7, 100, [42])
        app.save_mail_state('b', 9, 200, [42])
        app.remove_pending_uid('a',7,42)
        self.assertEqual(app.get_pending_uids('b'), [42])
        app.initialize_or_validate_state('a',8,301)
        self.assertEqual(app.load_mail_state('a')['last_processed_uid'],300)
        self.assertEqual(app.get_pending_uids('b'),[42])

    def test_message_id_metadata_is_preserved(self):
        app.save_mail_state('a', 7, 42, [42])
        reference = {'message_id':'<id@example.test>', 'sender':'A <a@x>',
                     'subject':'Hello', 'date':'2026-09-14T12:00:00'}
        self.assertTrue(app.save_message_reference('a', 7, 42, reference))
        app.save_mail_state('a', 7, 43)
        self.assertEqual(
            app.load_mail_state('a')['message_refs']['42']['message_id'],
            '<id@example.test>')

    def test_pending_open_clears_local_badge(self):
        app.save_mail_state('a', 7, 42, [42])
        review = app.PendingReview()
        review.active = True
        review._stop_and_return_to_indicator = Mock()
        item = {'email':'a', 'uidvalidity':7, 'uid':42, 'sender':'A <a@x>',
                'subject':'Hello', 'date':'2026-09-14T12:00:00'}
        review.items = app.deque([item])
        with patch.object(app.threading, 'Thread') as thread:
            review._regular_open(None, item)
            thread.assert_called_once()
        self.assertEqual(app.get_pending_uids('a'), [])
        review._stop_and_return_to_indicator.assert_called_once()

    def test_pending_open_clears_only_opened_account(self):
        app.save_mail_state('a', 7, 42, [41, 42])
        app.save_mail_state('b', 9, 53, [51, 52, 53])
        items = [
            {'email':'a', 'uidvalidity':7, 'uid':41},
            {'email':'a', 'uidvalidity':7, 'uid':42},
            {'email':'b', 'uidvalidity':9, 'uid':51},
            {'email':'b', 'uidvalidity':9, 'uid':52},
            {'email':'b', 'uidvalidity':9, 'uid':53},
        ]
        review = app.PendingReview()
        review.items = app.deque(items)
        review._stop_and_return_to_indicator = Mock()
        with patch.object(app.threading, 'Thread'):
            review._regular_open(None, items[0])
        self.assertEqual(app.get_pending_uids('a'), [])
        self.assertEqual(app.get_pending_uids('b'), [51, 52, 53])
        self.assertEqual(app.pending_count(), 3)

    def test_pending_open_preserves_mail_arriving_after_review_loaded(self):
        app.save_mail_state('a', 7, 43, [41, 42])
        items = [
            {'email':'a', 'uidvalidity':7, 'uid':41},
            {'email':'a', 'uidvalidity':7, 'uid':42},
        ]
        review = app.PendingReview()
        review.items = app.deque(items)
        review._stop_and_return_to_indicator = Mock()
        app.add_pending_uid('a', 7, 43)
        with patch.object(app.threading, 'Thread'):
            review._regular_open(None, items[0])
        self.assertEqual(app.get_pending_uids('a'), [43])

    def test_idle_safety_poll_is_fast(self):
        self.assertEqual(app.IDLE_TIMEOUT, 10)
        self.assertEqual(app.CONNECTION_STALE_SECONDS, 20)

    def test_pending_badge_text(self):
        self.assertEqual(app.pending_badge_text(1), '1')
        self.assertEqual(app.pending_badge_text(99), '99')
        self.assertEqual(app.pending_badge_text(100), '99+')

    def test_fresh_account_skips_old_mail(self):
        s = app.initialize_or_validate_state('new',4,100)
        self.assertEqual(s['last_processed_uid'],99)
        self.assertEqual(s['pending_uids'],[])

    def test_legacy_migration(self):
        app.STATE_FILE.write_text('{"uidvalidity":7,"last_processed_uid":99,"pending_uids":[42]}')
        app.migrate_legacy_state('a')
        self.assertEqual(app.get_pending_uids('a'),[42])

    def test_ignore_does_not_add_pending(self):
        popup = app.RegularMailPopup()
        popup.current_pending_context = ('a',7,42)
        popup.close_popup = Mock()
        with patch.object(app,'add_pending_uid') as add:
            popup.on_ignore(None)
            self.assertIsNone(popup.current_pending_context)
            add.assert_not_called()
            popup.close_popup.assert_called_once()

    def test_timeout_goes_pending(self):
        app.save_mail_state('a',7,42,[])
        popup = app.RegularMailPopup()
        popup.current_pending_context = ('a',7,42)
        popup.on_timeout()
        self.assertEqual(app.get_pending_uids('a'),[42])

    def test_busy_arrival_pending_only(self):
        app.save_mail_state('a',7,42,[])
        with patch.object(app,'notification_is_busy',return_value=True), patch.object(app,'play_notification'), patch.object(app.regular_popup,'show') as show:
            app.show_live_message_ui('regular',(), 'a',42,7)
            show.assert_not_called()
        self.assertEqual(app.get_pending_uids('a'),[42])

    def test_backlog_no_popup_and_checkpoint(self):
        app.save_mail_state('a',7,40,[])
        box = Mock()
        box.fetch.return_value = [SimpleNamespace(uid='41'),SimpleNamespace(uid='42')]
        with patch.object(app,'show_live_message_ui') as show:
            self.assertEqual(app.recover_backlog_messages(box,'a',7,43),2)
            show.assert_not_called()
        self.assertEqual(app.get_pending_uids('a'),[41,42])
        self.assertEqual(app.load_mail_state('a')['last_processed_uid'],42)

    def test_reconnect_boundaries(self):
        self.assertTrue(reconnect_is_live(15))
        self.assertTrue(reconnect_is_live(90))
        self.assertFalse(reconnect_is_live(90.01))
        self.assertFalse(reconnect_is_live(15, True))

    def test_suspend_clock(self):
        with patch.object(app.time,'clock_gettime',return_value=110.0), patch.object(app.time,'monotonic',return_value=100.0):
            self.assertGreater(app.suspend_gap_since((90.0,90.0)),5)

    def test_true_otp_phrases(self):
        examples = (
            ('Your verification code is 482913', '', '482913'),
            ('Security code', 'Enter this code: 7351', '7351'),
            ('Sign-in', 'Your one-time code is 87654321', '87654321'),
            ('Authentication code: 246810', '', '246810'),
            ('Код подтверждения: 593204', '', '593204'),
        )
        for subject, body, expected in examples:
            with self.subTest(subject=subject):
                self.assertEqual(app.extract_code(subject, body), expected)

    def test_github_workflow_is_not_otp(self):
        subject = ('7776 [example/project] Run failed: Android '
                   'verification - feature/export-format-and-detailed-scale-'
                   'v0.4.0 (c377668)')
        self.assertIsNone(app.extract_code(subject, 'Workflow build failed.'))

    def test_verification_alone_is_not_enough(self):
        self.assertIsNone(app.extract_code(
            'Android verification 482913', 'Build and test report'))

    def test_embedded_digits_are_not_otp(self):
        for token in ('c377668', 'build482913', '482913rc', 'ref_482913'):
            with self.subTest(token=token):
                self.assertIsNone(app.extract_code(
                    f'Your verification code is {token}', ''))

    def test_code_must_be_near_phrase(self):
        body = 'Verification code ' + ('unrelated text ' * 20) + '482913'
        self.assertIsNone(app.extract_code('', body))

    def test_ci_context_reduces_confidence(self):
        subject = 'Run failed: workflow build verification code 482913'
        score, code = app.otp_confidence(subject, 'branch commit test failed')
        self.assertEqual(code, '482913')
        self.assertLess(score, app.OTP_MIN_CONFIDENCE)
        self.assertIsNone(app.extract_code(subject, 'branch commit test failed'))


if __name__ == '__main__':
    unittest.main()
