"""Provider-neutral IMAP monitor configuration and callback contract."""

from dataclasses import dataclass
from contextlib import contextmanager
import re
from typing import Protocol
import time

from .delivery import classify_delivery, uid_window
from .session import reconnect_is_live


@dataclass(frozen=True)
class MonitorConfig:
    idle_timeout: int = 10
    socket_timeout: int = 15
    watchdog_timeout: int = 20
    reconnect_delays: tuple[int, ...] = (3, 5, 10, 20, 40, 60)
    short_reconnect_seconds: int = 90


def reconnect_delay(config, consecutive_failures):
    """Return bounded reconnect backoff, starting with a fast recovery."""
    index = min(max(0, int(consecutive_failures)), len(config.reconnect_delays) - 1)
    return config.reconnect_delays[index]


class MonitorEvents(Protocol):
    def message_live(self, account, folder, message): ...
    def message_pending(self, account, folder, message): ...
    def connection_changed(self, account, state, detail=""): ...


def _diagnostic(events, account, event, **fields):
    callback = getattr(events, "diagnostic", None)
    if callback is not None:
        try:
            callback(account, event, **fields)
        except Exception:
            pass


def _imap_response_number(client, name):
    """Read a numeric response code produced by SELECT/EXAMINE, if available."""
    try:
        _kind, values = client.response(name)
    except Exception:
        return None
    for value in values or ():
        match = re.search(rb"\d+", value if isinstance(value, bytes)
                          else str(value).encode("ascii", "ignore"))
        if match:
            return int(match.group())
    return None


def refresh_folder_status(mailbox, folder):
    """Force a fresh EXAMINE and return authoritative mailbox identity/state.

    Yahoo can keep answering STATUS successfully while returning an old UIDNEXT
    on a long-lived connection.  EXAMINE refreshes the selected mailbox; its
    UID response codes are preferred, with STATUS only as a compatibility
    fallback for IMAP implementations that do not expose those codes.
    """
    # EXAMINE (readonly SELECT) refreshes state without ever expunging messages
    # that another client may have marked as deleted.
    mailbox.folder.set(folder, readonly=True)
    result = {
        name: _imap_response_number(mailbox.client, name)
        for name in ("UIDVALIDITY", "UIDNEXT")
    }
    missing = [name for name, value in result.items() if value is None]
    if missing:
        fallback = mailbox.folder.status(folder)
        for name in missing:
            result[name] = int(fallback[name])
    return result


@contextmanager
def _mailbox_session(mailbox, events, account):
    """Log out without allowing a cleanup error to hide the real failure."""
    try:
        yield mailbox
    except BaseException:
        try:
            mailbox.logout()
        except Exception as cleanup_error:
            _diagnostic(
                events, account, "logout_error",
                error=type(cleanup_error).__name__,
                detail=str(cleanup_error).strip()[:160],
                original_error_preserved=True,
            )
        raise
    else:
        mailbox.logout()


def run_account_monitor(account, password, provider, mailbox_factory, platform,
                        events, reconnect_event, config=MonitorConfig(),
                        suspend_gap_seconds=5.0):
    """Run provider-neutral IMAP/IDLE and reconnect classification forever.

    UI/state effects are callbacks, so this loop can be reused by another UI
    and OS platform without importing GTK or Linux APIs.
    """
    events.connection_changed(account, "connecting", "Connecting")
    first_connection = True
    reconnect_started_wall = None
    reconnect_was_suspend = False
    consecutive_failures = 0
    while True:
        operation_clock = platform.power_clock_snapshot()
        mailbox = None
        connect_started = time.monotonic()
        _diagnostic(events, account, "connect_start")
        try:
            mailbox = mailbox_factory(
                provider.imap_host, timeout=config.socket_timeout
            ).login(account, password, initial_folder=None)
            with _mailbox_session(mailbox, events, account):
                events.register_mailbox(account, mailbox)
                status = refresh_folder_status(mailbox, provider.inbox)
                uidvalidity = int(status["UIDVALIDITY"])
                uidnext = int(status["UIDNEXT"])
                last_seen_uidnext = uidnext
                _diagnostic(
                    events, account, "connect_ok",
                    seconds=round(time.monotonic() - connect_started, 3),
                    uidnext=uidnext,
                )
                events.connection_changed(account, "connected", "Connected")
                events.connected(account, mailbox, uidvalidity, uidnext)

                if first_connection:
                    events.recover_pending(mailbox, account, uidvalidity, uidnext)
                    first_connection = False
                elif reconnect_started_wall is not None:
                    outage = max(0.0, time.time() - reconnect_started_wall)
                    if reconnect_was_suspend or not reconnect_is_live(
                        outage, reconnect_was_suspend
                    ):
                        events.recover_pending(mailbox, account, uidvalidity, uidnext)
                    else:
                        events.process_live(mailbox, account, uidvalidity, uidnext, password)
                    reconnect_started_wall = None
                    reconnect_was_suspend = False
                else:
                    events.recover_pending(mailbox, account, uidvalidity, uidnext)

                while True:
                    idle_clock = platform.power_clock_snapshot()
                    idle_started = time.monotonic()
                    responses = mailbox.idle.wait(timeout=config.idle_timeout)
                    _diagnostic(
                        events, account, "idle_return",
                        seconds=round(time.monotonic() - idle_started, 3),
                        response_count=len(responses),
                    )
                    gap = platform.suspend_gap_since(idle_clock)
                    status_started = time.monotonic()
                    status = refresh_folder_status(mailbox, provider.inbox)
                    new_validity = int(status["UIDVALIDITY"])
                    new_uidnext = int(status["UIDNEXT"])
                    _diagnostic(
                        events, account, "folder_refresh",
                        seconds=round(time.monotonic() - status_started, 3),
                        uidnext=new_uidnext,
                        uidnext_changed=new_uidnext != last_seen_uidnext,
                        suspend_gap=round(gap, 3),
                    )
                    if new_validity != uidvalidity:
                        raise RuntimeError(f"{provider.inbox} UIDVALIDITY changed")
                    consecutive_failures = 0
                    events.connection_changed(
                        account,
                        "connected",
                        f"Checked {time.strftime('%H:%M:%S')}",
                    )
                    if gap > suspend_gap_seconds:
                        events.resumed(account, gap)
                        handled = events.recover_pending(
                            mailbox, account, uidvalidity, new_uidnext
                        )
                    else:
                        handled = events.process_live(
                            mailbox, account, uidvalidity, new_uidnext, password
                        )
                    if not responses and handled == 0:
                        events.heartbeat(account)
                    last_seen_uidnext = new_uidnext
        except Exception as exc:
            events.unregister_mailbox(account, mailbox)
            try:
                if platform.suspend_gap_since(operation_clock) > suspend_gap_seconds:
                    reconnect_was_suspend = True
            except Exception:
                pass
            if reconnect_started_wall is None:
                reconnect_started_wall = time.time()
            detail = type(exc).__name__
            if str(exc).strip():
                detail += f": {str(exc).strip()}"
            events.connection_changed(account, "error", detail[:90])
            delay = reconnect_delay(config, consecutive_failures)
            consecutive_failures += 1
            _diagnostic(
                events, account, "connection_error",
                error=type(exc).__name__,
                detail=str(exc).strip()[:160],
                reconnect_seconds=delay,
            )
            events.interrupted(account, exc, delay)
            retry_clock = platform.power_clock_snapshot()
            reconnect_event.wait(delay)
            reconnect_event.clear()
            events.connection_changed(account, "connecting", "Reconnecting")
            try:
                if platform.suspend_gap_since(retry_clock) > suspend_gap_seconds:
                    reconnect_was_suspend = True
            except Exception:
                pass


__all__ = ["MonitorConfig", "MonitorEvents", "reconnect_delay", "refresh_folder_status",
           "run_account_monitor",
           "classify_delivery", "uid_window"]
