"""Provider-neutral IMAP monitor configuration and callback contract."""

from dataclasses import dataclass
from typing import Protocol
import time

from .delivery import classify_delivery, uid_window
from .session import reconnect_is_live


@dataclass(frozen=True)
class MonitorConfig:
    idle_timeout: int = 15
    socket_timeout: int = 30
    short_reconnect_seconds: int = 90


class MonitorEvents(Protocol):
    def message_live(self, account, folder, message): ...
    def message_pending(self, account, folder, message): ...
    def connection_changed(self, account, state, detail=""): ...


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
    while True:
        operation_clock = platform.power_clock_snapshot()
        mailbox = None
        try:
            with mailbox_factory(provider.imap_host, timeout=config.socket_timeout).login(
                account, password, initial_folder=provider.inbox,
            ) as mailbox:
                events.register_mailbox(account, mailbox)
                status = mailbox.folder.status(provider.inbox)
                uidvalidity = int(status["UIDVALIDITY"])
                uidnext = int(status["UIDNEXT"])
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
                    responses = mailbox.idle.wait(timeout=config.idle_timeout)
                    gap = platform.suspend_gap_since(idle_clock)
                    status = mailbox.folder.status(provider.inbox)
                    new_validity = int(status["UIDVALIDITY"])
                    new_uidnext = int(status["UIDNEXT"])
                    if new_validity != uidvalidity:
                        raise RuntimeError(f"{provider.inbox} UIDVALIDITY changed")
                    events.connection_changed(account, "connected", "Connected")
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
            events.interrupted(account, exc, 15)
            retry_clock = platform.power_clock_snapshot()
            reconnect_event.wait(15)
            reconnect_event.clear()
            events.connection_changed(account, "connecting", "Reconnecting")
            try:
                if platform.suspend_gap_since(retry_clock) > suspend_gap_seconds:
                    reconnect_was_suspend = True
            except Exception:
                pass


__all__ = ["MonitorConfig", "MonitorEvents", "run_account_monitor",
           "classify_delivery", "uid_window"]
