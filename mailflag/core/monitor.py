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
    extra_folder_poll_seconds: int = 30


def reconnect_delay(config, consecutive_failures):
    """Return bounded reconnect backoff, starting with a fast recovery."""
    index = min(max(0, int(consecutive_failures)), len(config.reconnect_delays) - 1)
    return config.reconnect_delays[index]


class MonitorEvents(Protocol):
    def message_live(self, account, folder, message): ...
    def message_pending(self, account, folder, message): ...
    def connection_changed(self, account, state, detail=""): ...


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
def _mailbox_session(mailbox):
    """Log out without allowing a cleanup error to hide the real failure."""
    try:
        yield mailbox
    except BaseException:
        try:
            mailbox.logout()
        except Exception:
            pass
        raise
    else:
        mailbox.logout()


def run_account_monitor(account, password, provider, mailbox_factory, platform,
                        events, reconnect_event, config=MonitorConfig(),
                        suspend_gap_seconds=5.0, stop_event=None):
    """Run provider-neutral IMAP/IDLE and reconnect classification forever.

    UI/state effects are callbacks, so this loop can be reused by another UI
    and OS platform without importing GTK or Linux APIs.
    """
    if stop_event is not None and stop_event.is_set():
        return
    events.connection_changed(account, "connecting", "Connecting")
    first_connection = True
    reconnect_started_wall = None
    reconnect_was_suspend = False
    consecutive_failures = 0

    def monitored_folders():
        callback = getattr(events, "monitored_folders", None)
        folders = callback(account) if callback else (provider.inbox,)
        result = [provider.inbox]
        seen = {provider.inbox.casefold()}
        for folder in folders:
            folder = str(folder).strip()
            if folder and folder.casefold() not in seen:
                result.append(folder)
                seen.add(folder.casefold())
        return result

    def handle_folder(mailbox, folder, mode):
        try:
            status = refresh_folder_status(mailbox, folder)
            uidvalidity = int(status["UIDVALIDITY"])
            uidnext = int(status["UIDNEXT"])
            if mode == "pending":
                return events.recover_pending(
                    mailbox, account, folder, uidvalidity, uidnext
                )
            return events.process_live(
                mailbox, account, folder, uidvalidity, uidnext, password
            )
        except Exception as exc:
            callback = getattr(events, "folder_error", None)
            if callback:
                callback(account, folder, exc)
            return 0

    def handle_extra_folders(mailbox, mode):
        total = 0
        for folder in monitored_folders()[1:]:
            total += handle_folder(mailbox, folder, mode)
        # IDLE must always resume with the primary inbox selected.
        refresh_folder_status(mailbox, provider.inbox)
        return total

    while stop_event is None or not stop_event.is_set():
        operation_clock = platform.power_clock_snapshot()
        mailbox = None
        try:
            mailbox = mailbox_factory(
                provider.imap_host, timeout=config.socket_timeout
            ).login(account, password, initial_folder=None)
            with _mailbox_session(mailbox):
                events.register_mailbox(account, mailbox)
                if stop_event is not None and stop_event.is_set():
                    events.unregister_mailbox(account, mailbox)
                    return
                status = refresh_folder_status(mailbox, provider.inbox)
                uidvalidity = int(status["UIDVALIDITY"])
                uidnext = int(status["UIDNEXT"])
                events.connection_changed(account, "connected", "Connected")
                events.connected(account, mailbox, uidvalidity, uidnext)

                if first_connection:
                    events.recover_pending(
                        mailbox, account, provider.inbox, uidvalidity, uidnext
                    )
                    handle_extra_folders(mailbox, "pending")
                    first_connection = False
                elif reconnect_started_wall is not None:
                    outage = max(0.0, time.time() - reconnect_started_wall)
                    if reconnect_was_suspend or not reconnect_is_live(
                        outage, reconnect_was_suspend
                    ):
                        events.recover_pending(
                            mailbox, account, provider.inbox, uidvalidity, uidnext
                        )
                        handle_extra_folders(mailbox, "pending")
                    else:
                        events.process_live(
                            mailbox, account, provider.inbox,
                            uidvalidity, uidnext, password,
                        )
                        handle_extra_folders(mailbox, "live")
                    reconnect_started_wall = None
                    reconnect_was_suspend = False
                else:
                    events.recover_pending(
                        mailbox, account, provider.inbox, uidvalidity, uidnext
                    )
                    handle_extra_folders(mailbox, "pending")

                last_extra_poll = time.monotonic()

                while True:
                    if stop_event is not None and stop_event.is_set():
                        events.unregister_mailbox(account, mailbox)
                        return
                    idle_clock = platform.power_clock_snapshot()
                    responses = mailbox.idle.wait(timeout=config.idle_timeout)
                    if stop_event is not None and stop_event.is_set():
                        events.unregister_mailbox(account, mailbox)
                        return
                    gap = platform.suspend_gap_since(idle_clock)
                    status = refresh_folder_status(mailbox, provider.inbox)
                    new_validity = int(status["UIDVALIDITY"])
                    new_uidnext = int(status["UIDNEXT"])
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
                            mailbox, account, provider.inbox,
                            uidvalidity, new_uidnext,
                        )
                        handled += handle_extra_folders(mailbox, "pending")
                        last_extra_poll = time.monotonic()
                    else:
                        handled = events.process_live(
                            mailbox, account, provider.inbox,
                            uidvalidity, new_uidnext, password,
                        )
                        if (time.monotonic() - last_extra_poll
                                >= config.extra_folder_poll_seconds):
                            handled += handle_extra_folders(mailbox, "live")
                            last_extra_poll = time.monotonic()
                    if not responses and handled == 0:
                        events.heartbeat(account)
        except Exception as exc:
            events.unregister_mailbox(account, mailbox)
            if stop_event is not None and stop_event.is_set():
                return
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
            events.interrupted(account, exc, delay)
            retry_clock = platform.power_clock_snapshot()
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline:
                if stop_event is not None and stop_event.wait(0.1):
                    return
                if reconnect_event.is_set():
                    break
            reconnect_event.clear()
            if stop_event is not None and stop_event.is_set():
                return
            events.connection_changed(account, "connecting", "Reconnecting")
            try:
                if platform.suspend_gap_since(retry_clock) > suspend_gap_seconds:
                    reconnect_was_suspend = True
            except Exception:
                pass


__all__ = ["MonitorConfig", "MonitorEvents", "reconnect_delay", "refresh_folder_status",
           "run_account_monitor",
           "classify_delivery", "uid_window"]
