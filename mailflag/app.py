#!/usr/bin/env python3

import configparser
import cairo
from collections import deque
import json
import html
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")

from gi.repository import AyatanaAppIndicator3, Gdk, GdkPixbuf, GLib, Gtk, Pango
from imap_tools import MailBox
from .core.actions import mark_exact_read, move_exact, named_folder, special_folder
from .core.monitor import MonitorConfig, run_account_monitor
from .core.accounts import configured_emails, configured_folders
from .core.state import normalize_account, read_store, write_store
from .core.otp import (
    MIN_CONFIDENCE as OTP_MIN_CONFIDENCE,
    confidence as otp_confidence,
    extract_code,
)
from .core.preview import extract_human_text, extract_preview
from .opening import (
    SYSTEM_DEFAULT,
    YAHOO_WEBMAIL,
    get_open_mode,
    launch_selected_mode,
    set_open_mode,
)
from .sound import (
    get_sound_choice,
    play_notification,
    selected_sound_path,
    set_sound_choice,
)
from .core.session import reconnect_is_live
from .core.sender import format_message_sender
from .ipc import ControlServer
from .settings_service import SettingsService, otp_timeout
from .core.status import ConnectionStatus, stale_connected_accounts
from .platform import get_platform
from .providers import YAHOO
from .version import __version__


PLATFORM = get_platform()
MONITOR_CONFIG = MonitorConfig()
IMAP_HOST = YAHOO.imap_host
IMAP_FOLDER = YAHOO.inbox
# IDLE normally wakes immediately on Yahoo's EXISTS response.  The timeout is
# only a safety poll for a delayed/missed server notification.
IDLE_TIMEOUT = MONITOR_CONFIG.idle_timeout
IMAP_SOCKET_TIMEOUT = MONITOR_CONFIG.socket_timeout
CONNECTION_STALE_SECONDS = MONITOR_CONFIG.watchdog_timeout
POPUP_TIMEOUT_SECONDS = 30

# A short IMAP reconnect inside the same running MailFlag process is
# treated as a live interruption. Mail recovered during this window may
# still get an immediate popup. Longer interruptions become pending-only.
SHORT_RECONNECT_LIVE_SECONDS = 90

# Linux-wide suspend detection: CLOCK_BOOTTIME includes suspend time,
# CLOCK_MONOTONIC does not. A gap above this threshold means the machine
# very likely slept. No Cinnamon/GNOME/KDE-specific API is required.
SUSPEND_GAP_SECONDS = 5.0

CONFIG_DIR = PLATFORM.paths.config_dir
CONFIG_FILE = PLATFORM.paths.config_file
STATE_FILE = PLATFORM.paths.state_file
INDICATOR_ICON = Path(__file__).with_name("mailflag-pending-icon.png")
APPLICATION_ICON = Path(__file__).with_name("mailflag-app-icon.png")
STATUS_ICONS = {
    state: Path(__file__).with_name(f"mailflag-{state}.svg")
    for state in ("online", "connecting", "partial", "offline")
}


RECONNECT_EVENT = threading.Event()
CONNECTION_STATUS = None
tray_indicator = None
ACTIVE_MAILBOXES = {}
ACTIVE_MAILBOXES_LOCK = threading.RLock()
ACCOUNT_STOP_EVENTS = {}
ACCOUNT_WORKERS = {}


def register_active_mailbox(email, mailbox):
    with ACTIVE_MAILBOXES_LOCK:
        ACTIVE_MAILBOXES[email] = mailbox


def unregister_active_mailbox(email, mailbox=None):
    with ACTIVE_MAILBOXES_LOCK:
        if mailbox is None or ACTIVE_MAILBOXES.get(email) is mailbox:
            ACTIVE_MAILBOXES.pop(email, None)


def interrupt_stale_mailbox(email):
    with ACTIVE_MAILBOXES_LOCK:
        mailbox = ACTIVE_MAILBOXES.get(email)
    if mailbox is None:
        return False
    try:
        mailbox.client.sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        mailbox.client.sock.close()
    except OSError:
        pass
    return True

ACTION_STYLES = {
    "open": "mailflag-open",
    "delete": "mailflag-delete",
    "spam": "mailflag-spam",
    "ignore": "mailflag-ignore",
    "read": "mailflag-read",
}


def install_ui_styles():
    css = b"""
    button.mailflag-action {
        background-image: none;
        color: white;
        font-size: 120%;
        font-weight: 600;
        min-height: 34px;
        padding: 8px 14px;
        border-radius: 9px;
        text-shadow: none;
    }
    button.mailflag-open { background-color: #258744; }
    button.mailflag-open:hover { background-color: #31a455; }
    button.mailflag-delete { background-color: #c73535; }
    button.mailflag-delete:hover { background-color: #df4747; }
    button.mailflag-spam { background-color: #2875c7; }
    button.mailflag-spam:hover { background-color: #398bdf; }
    button.mailflag-ignore { background-color: #6f747a; }
    button.mailflag-ignore:hover { background-color: #858b92; }
    button.mailflag-read { background-color: #7a3db7; }
    button.mailflag-read:hover { background-color: #9252d0; }
    window.mailflag-transparent-window {
        background-image: none;
        background-color: rgba(0, 0, 0, 0);
        box-shadow: none;
    }
    box.mailflag-popup-card {
        background-image: linear-gradient(to bottom, #ffffff, #f4effa);
        border: 1px solid #8261ae;
        border-radius: 24px;
        padding: 20px 22px 22px 22px;
        box-shadow:
            0 8px 14px rgba(28, 14, 48, 0.48),
            inset 0 2px rgba(255, 255, 255, 1.0),
            inset 0 -2px rgba(91, 54, 135, 0.08);
    }
    drawingarea.mailflag-badge { background-color: transparent; }
    """
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(
            screen,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )


def scale_popup_label(label):
    attributes = Pango.AttrList()
    attributes.insert(Pango.attr_scale_new(1.2))
    label.set_attributes(attributes)
    return label


def clear_transparent_background(_widget, cr):
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_rgba(0, 0, 0, 0)
    cr.paint()
    cr.set_operator(cairo.OPERATOR_OVER)
    return False


def make_window_transparent(window):
    window.set_app_paintable(True)
    window.get_style_context().add_class("mailflag-transparent-window")
    screen = window.get_screen()
    visual = screen.get_rgba_visual() if screen is not None else None
    if visual is not None and screen.is_composited():
        window.set_visual(visual)
    window.connect("draw", clear_transparent_background)


def style_popup_card(box):
    box.get_style_context().add_class("mailflag-popup-card")
    box.set_margin_start(24)
    box.set_margin_end(24)
    box.set_margin_top(20)
    box.set_margin_bottom(28)
    return box


def style_action_button(button, action):
    context = button.get_style_context()
    context.add_class("mailflag-action")
    context.add_class(ACTION_STYLES[action])
    return button

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def load_accounts():
    """
    Load one or more Yahoo accounts from config.ini.

    Backward compatible with the original [account] email=... format.
    New multi-account format:
        [accounts]
        emails =
            first@yahoo.com
            second@yahoo.com
    """
    config = configparser.ConfigParser()

    if CONFIG_FILE.exists():
        config.read(CONFIG_FILE, encoding="utf-8")

    accounts = configured_emails(config)

    if accounts:
        return accounts

    raise RuntimeError("No accounts configured. Run mailflag --add-account first.")


def load_password(email):
    password = PLATFORM.credentials.get(email)

    if not password:
        raise RuntimeError(
            "Yahoo App Password was not found in the keyring for this email."
        )

    return password


def html_to_text(value):
    if not value:
        return ""

    value = html.unescape(value)
    value = TAG_RE.sub(" ", value)
    return SPACE_RE.sub(" ", value).strip()


def make_preview(body, limit=260):
    """Make a short single-line preview for an ordinary-mail popup."""
    return extract_preview(plain_body=body, limit=limit)


def _folder_name_and_flags(folder_info):
    """Return (name, flags) for imap-tools FolderInfo across versions."""
    name = getattr(folder_info, "name", None)
    flags = getattr(folder_info, "flags", ())

    if name is None and isinstance(folder_info, dict):
        name = folder_info.get("name")
        flags = folder_info.get("flags", ())

    if isinstance(flags, str):
        flags = tuple(flags.split())

    return name, tuple(flags or ())


def find_trash_folder(mailbox):
    """
    Prefer the server-advertised IMAP special-use \\Trash folder.
    Fall back to conservative, well-known trash names only if needed.
    """
    folders = list(mailbox.folder.list())

    for folder_info in folders:
        name, flags = _folder_name_and_flags(folder_info)
        if any(flag.casefold() == r"\trash" for flag in flags):
            return name

    fallback_names = {
        "trash",
        "deleted",
        "deleted items",
        "deleted messages",
    }

    for folder_info in folders:
        name, _flags = _folder_name_and_flags(folder_info)
        if name and name.casefold() in fallback_names:
            return name

    raise RuntimeError("IMAP Trash folder was not found; message was NOT moved.")


def find_special_folder(mailbox, special_flag, fallback_names):
    """Find an IMAP special-use folder by flag, then by conservative names."""
    folders = list(mailbox.folder.list())
    wanted = special_flag.casefold()

    for folder_info in folders:
        name, flags = _folder_name_and_flags(folder_info)
        if any(flag.casefold() == wanted for flag in flags):
            return name

    fallback_names = {name.casefold() for name in fallback_names}

    for folder_info in folders:
        name, _flags = _folder_name_and_flags(folder_info)
        if name and name.casefold() in fallback_names:
            return name

    raise RuntimeError(
        f"IMAP folder {special_flag} was not found; message was NOT moved."
    )


def move_exact_message(
    email,
    password,
    uid,
    expected_uidvalidity,
    special_flag,
    fallback_names,
    action_name,
):
    """
    Move one exact INBOX UID to a special folder using a separate IMAP
    connection, with UIDVALIDITY and exact-UID safety checks.
    """
    uid = str(uid)

    try:
        with MailBox(IMAP_HOST).login(
            email,
            password,
            initial_folder=IMAP_FOLDER,
        ) as mailbox:
            status = mailbox.folder.status(IMAP_FOLDER)
            current_uidvalidity = int(status["UIDVALIDITY"])

            if current_uidvalidity != int(expected_uidvalidity):
                print(
                    f"{action_name} ABORTED: UIDVALIDITY changed for UID {uid}. "
                    "Message was NOT moved."
                )
                return False

            found = list(
                mailbox.fetch(
                    uid_list=[uid],
                    mark_seen=False,
                    headers_only=True,
                )
            )

            if len(found) != 1 or str(found[0].uid) != uid:
                print(
                    f"{action_name} ABORTED: UID {uid} is no longer in INBOX. "
                    "Message was NOT moved."
                )
                return False

            destination = find_special_folder(
                mailbox,
                special_flag,
                fallback_names,
            )
            mailbox.move([uid], destination)

            print(f"{action_name}: UID {uid} -> {destination}")
            return True

    except Exception as exc:
        print(
            f"{action_name} ERROR for UID {uid}: "
            f"{type(exc).__name__}: {exc}"
        )
        print("Message was NOT intentionally moved by MailFlag.")
        return False


def move_exact_message_to_named_folder(
    email,
    password,
    uid,
    expected_uidvalidity,
    destination,
    action_name,
):
    """
    Move one exact INBOX UID to a known IMAP folder, preserving the same
    UIDVALIDITY/exact-UID safety checks used elsewhere.
    """
    uid = str(uid)

    try:
        with MailBox(IMAP_HOST).login(
            email,
            password,
            initial_folder=IMAP_FOLDER,
        ) as mailbox:
            status = mailbox.folder.status(IMAP_FOLDER)
            current_uidvalidity = int(status["UIDVALIDITY"])

            if current_uidvalidity != int(expected_uidvalidity):
                print(
                    f"{action_name} ABORTED: UIDVALIDITY changed for UID {uid}. "
                    "Message was NOT moved."
                )
                return False

            found = list(
                mailbox.fetch(
                    uid_list=[uid],
                    mark_seen=False,
                    headers_only=True,
                )
            )

            if len(found) != 1 or str(found[0].uid) != uid:
                print(
                    f"{action_name} ABORTED: UID {uid} is no longer in INBOX. "
                    "Message was NOT moved."
                )
                return False

            # Verify the Yahoo system folder exists using raw IMAP LIST.
            typ, data = mailbox.client.list('""', destination)
            if typ != "OK" or not data:
                print(
                    f"{action_name} ABORTED: destination {destination!r} "
                    "was not confirmed by Yahoo IMAP."
                )
                return False

            mailbox.move([uid], destination)
            print(f"{action_name}: UID {uid} -> {destination}")
            return True

    except Exception as exc:
        print(
            f"{action_name} ERROR for UID {uid}: "
            f"{type(exc).__name__}: {exc}"
        )
        print("Message was NOT intentionally moved by MailFlag.")
        return False


def move_regular_to_trash(email, password, uid, uidvalidity,
                          source_folder=IMAP_FOLDER):
    return move_exact(
        MailBox, IMAP_HOST, source_folder, email, password, uid, uidvalidity,
        special_folder(r"\Trash", {"Trash", "Deleted", "Deleted Items", "Deleted Messages"}),
    )


def move_regular_to_spam(email, password, uid, uidvalidity,
                         source_folder=IMAP_FOLDER):
    # Yahoo exposes its web "Spam" folder over IMAP as "Bulk"
    # with the special-use flag \\Junk.  On this account imap-tools'
    # high-level folder.list() does not surface that system folder,
    # so use the verified Yahoo IMAP folder name directly.
    return move_exact(
        MailBox, IMAP_HOST, source_folder, email, password, uid, uidvalidity,
        named_folder(YAHOO.spam_folder),
    )


def open_default_mail_app():
    return launch_selected_mode()


def _message_reference(msg, sender="", subject=""):
    message_id = ""
    try:
        message_id = str(msg.obj.get("Message-ID", "") or "").strip()
    except Exception:
        pass
    sent_at = ""
    try:
        if msg.date:
            sent_at = msg.date.isoformat()
    except Exception:
        pass
    return {
        "message_id": message_id[:998],
        "sender": str(sender or "")[:1000],
        "subject": str(subject or "")[:1000],
        "date": sent_at,
    }


def move_message_to_trash(email, password, uid, expected_uidvalidity,
                          source_folder=IMAP_FOLDER):
    return move_regular_to_trash(
        email, password, uid, expected_uidvalidity, source_folder
    )


def suspend_clock_snapshot():
    return PLATFORM.power_clock_snapshot()


def suspend_gap_since(snapshot):
    return PLATFORM.suspend_gap_since(snapshot)


STATE_LOCK = threading.RLock()


def _normalize_account_state(value):
    return normalize_account(value)


def _read_store_unlocked():
    """
    v3 state format:
      {
        "version": 3,
        "accounts": {
          "a@yahoo.com": {"folders": {"INBOX": {...}, "Amazon": {...}}},
          "b@yahoo.com": {"folders": {"INBOX": {...}}}
        }
      }

    Legacy v0.6 single-account state is preserved under __legacy__ until
    main() knows which configured account should inherit it.
    """
    return read_store(STATE_FILE)


def _write_store_unlocked(store):
    write_store(STATE_FILE, store)


def migrate_legacy_state(primary_email):
    with STATE_LOCK:
        store = _read_store_unlocked()
        legacy = store["accounts"].pop("__legacy__", None)

        if legacy is not None and primary_email not in store["accounts"]:
            store["accounts"][primary_email] = legacy
            _write_store_unlocked(store)
            print(
                f"Existing MailFlag checkpoint migrated to {primary_email}."
            )
        elif legacy is not None:
            _write_store_unlocked(store)


def _account_state(store, email, create=False):
    account = store["accounts"].get(email)
    if account is None and create:
        account = {"folders": {}, "recent_message_ids": []}
        store["accounts"][email] = account
    return account


def load_mail_state(email, folder=IMAP_FOLDER):
    with STATE_LOCK:
        store = _read_store_unlocked()
        account = _account_state(store, email)
        value = account.get("folders", {}).get(folder) if account else None
        if value is None:
            return None
        return {
            "uidvalidity": value["uidvalidity"],
            "last_processed_uid": value["last_processed_uid"],
            "pending_uids": list(value["pending_uids"]),
            "message_refs": dict(value.get("message_refs", {})),
        }


def save_mail_state(email, uidvalidity, last_processed_uid,
                    pending_uids=None, folder=IMAP_FOLDER):
    with STATE_LOCK:
        store = _read_store_unlocked()
        account = _account_state(store, email, create=True)
        old = account["folders"].get(folder)
        if pending_uids is None:
            if old and int(old["uidvalidity"]) == int(uidvalidity):
                pending_uids = old.get("pending_uids", [])
            else:
                pending_uids = []
        account["folders"][folder] = {
            "uidvalidity": int(uidvalidity),
            "last_processed_uid": int(last_processed_uid),
            "pending_uids": list(pending_uids),
            "message_refs": (
                dict(old.get("message_refs", {}))
                if old and int(old["uidvalidity"]) == int(uidvalidity)
                else {}
            ),
        }
        _write_store_unlocked(store)


def initialize_or_validate_state(email, uidvalidity, current_uidnext,
                                 folder=IMAP_FOLDER):
    current_last_uid = max(0, int(current_uidnext) - 1)
    with STATE_LOCK:
        store = _read_store_unlocked()
        account = _account_state(store, email, create=True)
        state = account["folders"].get(folder)
        if state is None:
            state = {
                "uidvalidity": int(uidvalidity),
                "last_processed_uid": current_last_uid,
                "pending_uids": [],
                "message_refs": {},
            }
            account["folders"][folder] = state
            _write_store_unlocked(store)
            print(
                f"[{email}/{folder}] Mail state initialized at UID "
                f"{current_last_uid}. Existing older mail will not be replayed."
            )
            return dict(state)
        if int(state["uidvalidity"]) != int(uidvalidity):
            print()
            print(
                f"[{email}/{folder}] WARNING: UIDVALIDITY changed. "
                "Old checkpoint/pending UIDs were reset safely."
            )
            state = {
                "uidvalidity": int(uidvalidity),
                "last_processed_uid": current_last_uid,
                "pending_uids": [],
                "message_refs": {},
            }
            account["folders"][folder] = state
            _write_store_unlocked(store)
        return {
            "uidvalidity": state["uidvalidity"],
            "last_processed_uid": state["last_processed_uid"],
            "pending_uids": list(state.get("pending_uids", [])),
            "message_refs": dict(state.get("message_refs", {})),
        }


def save_message_reference(email, uidvalidity, uid, reference,
                           folder=IMAP_FOLDER):
    """Persist RFC metadata inside the exact source folder state."""
    with STATE_LOCK:
        store = _read_store_unlocked()
        account = _account_state(store, email)
        state = account.get("folders", {}).get(folder) if account else None
        if not state or int(state["uidvalidity"]) != int(uidvalidity):
            return False
        refs = dict(state.get("message_refs", {}))
        refs[str(int(uid))] = dict(reference)
        state["message_refs"] = refs
        _write_store_unlocked(store)
    return True


def claim_message_id(email, message_id):
    """Deduplicate notifications across folders without affecting actions."""
    message_id = str(message_id or "").strip()[:998]
    if not message_id:
        return True
    with STATE_LOCK:
        store = _read_store_unlocked()
        account = _account_state(store, email, create=True)
        recent = list(account.get("recent_message_ids", []))
        if message_id in recent:
            return False
        recent.append(message_id)
        account["recent_message_ids"] = recent[-500:]
        _write_store_unlocked(store)
    return True


def get_pending_items():
    """Return [(email, folder, uid), ...] for every monitored folder."""
    with STATE_LOCK:
        store = _read_store_unlocked()
        result = []
        for email, account in store["accounts"].items():
            if email == "__legacy__":
                continue
            for folder, state in account.get("folders", {}).items():
                for uid in state.get("pending_uids", []):
                    result.append((email, folder, int(uid)))
        return result


def get_pending_uids(email, folder=IMAP_FOLDER):
    state = load_mail_state(email, folder)
    return list(state.get("pending_uids", [])) if state else []


def pending_count():
    return len(get_pending_items())


def pending_badge_text(count):
    count = max(0, int(count))
    return "99+" if count > 99 else str(count)


def refresh_indicator_async():
    try:
        GLib.idle_add(pending_indicator.refresh)
    except NameError:
        pass
    if tray_indicator is not None:
        GLib.idle_add(tray_indicator.refresh)


def add_pending_uid(email, uidvalidity, uid, folder=IMAP_FOLDER):
    uid = int(uid)
    with STATE_LOCK:
        store = _read_store_unlocked()
        account = _account_state(store, email)
        state = account.get("folders", {}).get(folder) if account else None
        if not state:
            return False
        if int(state["uidvalidity"]) != int(uidvalidity):
            print(f"[{email}/{folder}] Pending UID {uid} ignored: UIDVALIDITY changed.")
            return False
        pending = set(state.get("pending_uids", []))
        if uid in pending:
            return False
        pending.add(uid)
        state["pending_uids"] = sorted(pending)
        _write_store_unlocked(store)
    print(f"[{email}/{folder}] Pending UID {uid}. Total pending: {pending_count()}")
    refresh_indicator_async()
    return True


def remove_pending_uid(email, uidvalidity, uid, folder=IMAP_FOLDER):
    uid = int(uid)
    with STATE_LOCK:
        store = _read_store_unlocked()
        account = _account_state(store, email)
        state = account.get("folders", {}).get(folder) if account else None
        if not state or int(state["uidvalidity"]) != int(uidvalidity):
            return False
        pending = set(state.get("pending_uids", []))
        if uid not in pending:
            return False
        pending.remove(uid)
        state["pending_uids"] = sorted(pending)
        _write_store_unlocked(store)
    print(f"[{email}/{folder}] Pending handled: UID {uid}. Total: {pending_count()}")
    refresh_indicator_async()
    return True


def clear_pending_snapshot(email, uidvalidity, snapshot_uids,
                           folder=IMAP_FOLDER):
    snapshot = {int(uid) for uid in snapshot_uids}
    if not snapshot:
        return 0
    with STATE_LOCK:
        store = _read_store_unlocked()
        account = _account_state(store, email)
        state = account.get("folders", {}).get(folder) if account else None
        if not state or int(state["uidvalidity"]) != int(uidvalidity):
            return 0
        pending = set(state.get("pending_uids", []))
        removed = pending & snapshot
        if not removed:
            return 0
        state["pending_uids"] = sorted(pending - removed)
        _write_store_unlocked(store)
    print(
        f"[{email}/{folder}] Opened mail; cleared {len(removed)} reminder(s). "
        f"Total pending: {pending_count()}"
    )
    refresh_indicator_async()
    return len(removed)


def _save_checkpoint_and_pending(email, uidvalidity, last_uid, pending_uids,
                                 folder=IMAP_FOLDER):
    with STATE_LOCK:
        store = _read_store_unlocked()
        account = _account_state(store, email, create=True)
        old = account["folders"].get(folder, {})
        account["folders"][folder] = {
            "uidvalidity": int(uidvalidity),
            "last_processed_uid": int(last_uid),
            "pending_uids": sorted(set(int(x) for x in pending_uids)),
            "message_refs": dict(old.get("message_refs", {})),
        }
        _write_store_unlocked(store)


def recover_backlog_messages(mailbox, email, uidvalidity, current_uidnext,
                             folder=IMAP_FOLDER):
    """Recover one folder as pending without replaying a popup storm."""
    state = initialize_or_validate_state(email, uidvalidity, current_uidnext, folder)
    last_processed = int(state["last_processed_uid"])
    target_last_uid = max(0, int(current_uidnext) - 1)
    if target_last_uid <= last_processed:
        refresh_indicator_async()
        return 0
    first_uid = last_processed + 1
    pending = set(state.get("pending_uids", []))
    total_found = 0
    batch_start = first_uid
    print(
        f"[{email}/{folder}] Backlog UID {first_uid} through {target_last_uid}; "
        "no popups will be replayed."
    )
    while batch_start <= target_last_uid:
        batch_end = min(batch_start + 99, target_last_uid)
        messages = list(mailbox.fetch(
            uid_list=[str(uid) for uid in range(batch_start, batch_end + 1)],
            mark_seen=False, headers_only=True,
        ))
        for msg in messages:
            reference = _message_reference(
                msg,
                format_message_sender(msg),
                getattr(msg, "subject", "") or "(no subject)",
            )
            save_message_reference(email, uidvalidity, msg.uid, reference, folder)
            if claim_message_id(email, reference["message_id"]):
                pending.add(int(msg.uid))
                total_found += 1
        _save_checkpoint_and_pending(
            email, uidvalidity, batch_end, pending, folder
        )
        batch_start = batch_end + 1
    if total_found:
        print(f"[{email}/{folder}] Recovered {total_found} pending message(s).")
    refresh_indicator_async()
    return total_found

def notification_is_busy():
    try:
        return (
            popup.window is not None
            or regular_popup.window is not None
            or pending_review.active
        )
    except NameError:
        return False


def show_live_message_ui(
    kind,
    payload,
    email,
    uid,
    uidvalidity,
    folder=IMAP_FOLDER,
):
    """
    One immediate popup globally, even with multiple accounts.
    A simultaneous second arrival becomes pending instead of stacking.
    """
    preferences = SettingsService().notification_preferences()
    if preferences["play_sound"]:
        play_notification()
    if not preferences["show_popup"]:
        add_pending_uid(email, uidvalidity, uid, folder)
        return False
    busy = notification_is_busy()
    if busy:
        print(
            f"[{email}] Live UID {uid} arrived while MailFlag UI was busy; "
            "adding it to the persistent indicator."
        )
        add_pending_uid(email, uidvalidity, uid, folder)
        return False

    if kind == "otp":
        popup.show(*payload)
    else:
        regular_popup.show(*payload)

    return False


def process_live_message(
    msg,
    email,
    uidvalidity,
    password,
    folder=IMAP_FOLDER,
):
    subject = msg.subject or "(no subject)"
    sender = format_message_sender(msg)
    sender_email = msg.from_ or "(unknown sender)"

    body = extract_human_text(msg.text, msg.html)

    code = extract_code(subject, body)
    uid = int(msg.uid)
    reference = _message_reference(msg, sender, subject)
    save_message_reference(email, uidvalidity, uid, reference, folder)
    if not claim_message_id(email, reference["message_id"]):
        print(f"[{email}/{folder}] Duplicate Message-ID suppressed: UID {uid}")
        return False

    print()
    print("-" * 60)
    print(f"[{email}/{folder}] LIVE NEW MAIL")
    print("From:", sender)
    print("Subject:", subject)
    print("UID:", uid)

    if code:
        print("MAILFLAG CODE:", code)
        payload = (
            code,
            sender_email,
            subject,
            uid,
            uidvalidity,
            email,
            password,
            folder,
        )
        GLib.idle_add(
            show_live_message_ui,
            "otp",
            payload,
            email,
            uid,
            uidvalidity,
            folder,
        )
    else:
        print("MailFlag: ordinary mail")
        payload = (
            sender,
            subject,
            extract_preview(msg.text, msg.html),
            uid,
            uidvalidity,
            email,
            password,
            folder,
            reference["message_id"],
            reference["date"],
        )
        GLib.idle_add(
            show_live_message_ui,
            "regular",
            payload,
            email,
            uid,
            uidvalidity,
            folder,
        )

    print("-" * 60)
    return True


def process_live_new_messages(
    mailbox,
    email,
    uidvalidity,
    current_uidnext,
    password,
    folder=IMAP_FOLDER,
):
    state = initialize_or_validate_state(
        email,
        uidvalidity,
        current_uidnext,
        folder,
    )

    last_processed = int(state["last_processed_uid"])
    target_last_uid = max(0, int(current_uidnext) - 1)

    if target_last_uid <= last_processed:
        return 0

    first_uid = last_processed + 1
    total = 0
    batch_size = 100
    batch_start = first_uid

    while batch_start <= target_last_uid:
        batch_end = min(batch_start + batch_size - 1, target_last_uid)

        messages = list(
            mailbox.fetch(
                uid_list=[
                    str(uid)
                    for uid in range(batch_start, batch_end + 1)
                ],
                mark_seen=False,
            )
        )
        messages.sort(key=lambda msg: int(msg.uid))

        for msg in messages:
            if process_live_message(
                msg,
                email,
                uidvalidity,
                password,
                folder,
            ):
                total += 1

        save_mail_state(
            email,
            uidvalidity,
            batch_end,
            folder=folder,
        )
        batch_start = batch_end + 1

    return total


class MailFlagPopup:
    def __init__(self):
        self.window = None
        self.timeout_id = None
        self.current_pending_context = None

    def show(self, code, sender, subject, uid, uidvalidity, email, password,
             folder=IMAP_FOLDER):
        self.current_pending_context = (email, folder, int(uidvalidity), int(uid))

        if self.timeout_id is not None:
            try:
                GLib.source_remove(self.timeout_id)
            except Exception:
                pass
            self.timeout_id = None

        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None

        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window = window
        make_window_transparent(window)

        window.set_title("MailFlag")
        window.set_decorated(False)
        window.set_resizable(False)
        window.set_keep_above(True)
        window.set_skip_taskbar_hint(True)
        window.set_skip_pager_hint(True)
        # The popup must accept pointer interaction so the code can be clicked.
        window.set_accept_focus(True)
        window.set_default_size(540, 250)


        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
        )
        style_popup_card(outer)
        outer.set_border_width(0)
        window.add(outer)

        hint = scale_popup_label(Gtk.Label(label="Verification code"))
        hint.set_xalign(0.5)
        outer.pack_start(hint, False, False, 0)

        code_event = Gtk.EventBox()
        code_event.set_visible_window(False)
        code_event.set_tooltip_text("Click to copy")
        code_event.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        code_event.connect(
            "button-press-event",
            self.copy_code,
            code,
            uid,
            uidvalidity,
            email,
            password,
            folder,
        )

        code_label = Gtk.Label(label=code)
        code_label.modify_font(Pango.FontDescription("Sans Bold 38"))
        code_label.set_selectable(False)
        code_event.add(code_label)

        outer.pack_start(code_event, True, True, 0)

        sender_label = Gtk.Label()
        sender_label.set_markup(
            "<b>From:</b> " + GLib.markup_escape_text(sender or "(unknown)")
        )
        sender_label.set_xalign(0.0)
        scale_popup_label(sender_label)
        sender_label.set_ellipsize(Pango.EllipsizeMode.END)
        outer.pack_start(sender_label, False, False, 0)

        subject_label = Gtk.Label()
        subject_label.set_markup(
            "<b>Subject:</b> " + GLib.markup_escape_text(subject or "(no subject)")
        )
        subject_label.set_xalign(0.0)
        scale_popup_label(subject_label)
        subject_label.set_ellipsize(Pango.EllipsizeMode.END)
        outer.pack_start(subject_label, False, False, 0)

        window.connect("destroy", self.on_destroy)
        window.show_all()

        # Position near the upper-right corner of the current primary monitor.
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() if display else None

        if monitor is None and display is not None:
            monitor = display.get_monitor(0)

        if monitor is not None:
            area = monitor.get_workarea()
            width, height = window.get_size()
            x = area.x + area.width - width - 24
            y = area.y + 24
            window.move(x, y)

        duration = SettingsService().notification_preferences()["popup_duration"]
        self.timeout_id = GLib.timeout_add_seconds(
            otp_timeout(duration),
            self.on_timeout,
        )

        print(f"Popup shown for code {code}")
        print(
            f"Popup will close after {POPUP_TIMEOUT_SECONDS} seconds "
            "unless the code is clicked."
        )
        return False

    def copy_code(
        self, _widget, _event, code, uid, uidvalidity, email, password, folder
    ):
        PLATFORM.copy_text(code)
        PLATFORM.copy_text(code, primary=True)

        print(f"Code copied to clipboard: {code}")
        self.current_pending_context = None

        # A successful click means the user has taken the code.
        # Cancel the safety timeout and close immediately.
        if self.timeout_id is not None:
            try:
                GLib.source_remove(self.timeout_id)
            except Exception:
                pass
            self.timeout_id = None

        self.close_popup()

        threading.Thread(
            target=move_message_to_trash,
            args=(email, password, uid, uidvalidity, folder),
            daemon=True,
        ).start()

        return True

    def on_timeout(self):
        self.timeout_id = None
        print("OTP popup timed out.")

        if self.current_pending_context is not None:
            email, folder, uidvalidity, uid = self.current_pending_context
            self.current_pending_context = None
            add_pending_uid(email, uidvalidity, uid, folder)

        self.close_popup()
        return False

    def close_popup(self):
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass

        self.window = None
        return False

    def on_destroy(self, _window):
        self.window = None


def compact_label(label):
    scale_popup_label(label)
    label.set_line_wrap(True)
    label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    label.set_width_chars(42)
    label.set_max_width_chars(42)
    label.set_lines(3)
    label.set_ellipsize(Pango.EllipsizeMode.END)


class RegularMailPopup:
    def __init__(self):
        self.window = None
        self.timeout_id = None
        self.current_pending_context = None

    def show(
        self,
        sender,
        subject,
        preview,
        uid,
        uidvalidity,
        email,
        password,
        folder=IMAP_FOLDER,
        message_id="",
        sent_at="",
    ):
        self.current_pending_context = (email, folder, int(uidvalidity), int(uid))
        self.close_popup()

        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window = window
        make_window_transparent(window)

        window.set_title("MailFlag — New mail")
        window.set_decorated(False)
        window.set_resizable(False)
        window.set_keep_above(True)
        window.set_skip_taskbar_hint(True)
        window.set_skip_pager_hint(True)
        window.set_accept_focus(True)
        window.set_default_size(520, 340)

        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
        )
        style_popup_card(outer)
        outer.set_border_width(0)
        window.add(outer)

        title = Gtk.Label()
        title.set_markup("<b>⚑  New mail</b>")
        title.modify_font(Pango.FontDescription("Sans Bold 19"))
        title.set_xalign(0.0)
        outer.pack_start(title, False, False, 0)

        # Clickable message card: opens the system-default mail app.
        card = Gtk.EventBox()
        card.set_visible_window(False)
        card.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        card.set_tooltip_text("Open mail using the selected MailFlag setting")
        card.connect(
            "button-press-event", self.on_open,
            sender, subject, sent_at, email,
        )

        card_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
        )
        card.add(card_box)

        sender_label = Gtk.Label()
        sender_label.set_markup(
            "<b>From:</b> " + GLib.markup_escape_text(sender or "(unknown)")
        )
        sender_label.set_xalign(0.0)
        compact_label(sender_label)
        sender_label.set_ellipsize(Pango.EllipsizeMode.END)
        card_box.pack_start(sender_label, False, False, 0)

        subject_label = Gtk.Label()
        subject_label.set_markup(
            "<b>Subject:</b> " + GLib.markup_escape_text(subject or "(no subject)")
        )
        subject_label.set_xalign(0.0)
        compact_label(subject_label)
        subject_label.set_ellipsize(Pango.EllipsizeMode.END)
        card_box.pack_start(subject_label, False, False, 0)

        preview_label = Gtk.Label(label=preview or "(no text preview)")
        preview_label.set_xalign(0.0)
        compact_label(preview_label)
        preview_label.set_line_wrap(True)
        preview_label.set_lines(3)
        preview_label.set_ellipsize(Pango.EllipsizeMode.END)
        card_box.pack_start(preview_label, True, True, 0)

        outer.pack_start(card, True, True, 0)

        actions = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
        )

        open_button = Gtk.Button(label="Open")
        style_action_button(open_button, "open")
        open_button.connect(
            "clicked", self.on_open_button,
            sender, subject, sent_at, email,
        )
        actions.pack_start(open_button, True, True, 0)

        delete_button = Gtk.Button(label="Delete")
        style_action_button(delete_button, "delete")
        delete_button.connect(
            "clicked",
            self.on_delete,
            email,
            password,
            uid,
            uidvalidity,
            folder,
        )
        actions.pack_start(delete_button, True, True, 0)

        spam_button = Gtk.Button(label="Spam")
        style_action_button(spam_button, "spam")
        spam_button.connect(
            "clicked",
            self.on_spam,
            email,
            password,
            uid,
            uidvalidity,
            folder,
        )
        actions.pack_start(spam_button, True, True, 0)

        outer.pack_start(actions, False, False, 0)

        secondary = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        ignore = Gtk.Button(label="Ignore")
        style_action_button(ignore, "ignore")
        ignore.connect("clicked", self.on_ignore)
        secondary.pack_start(ignore, True, True, 0)
        read = Gtk.Button(label="Mark as Read")
        style_action_button(read, "read")
        read.connect("clicked", self.on_mark_read, email, password, uid,
                     uidvalidity, folder)
        secondary.pack_start(read, True, True, 0)
        outer.pack_start(secondary, False, False, 0)

        window.connect("destroy", self.on_destroy)
        window.show_all()
        self.position_window(window)

        duration = SettingsService().notification_preferences()["popup_duration"]
        self.timeout_id = GLib.timeout_add_seconds(
            duration,
            self.on_timeout,
        )

        print(f"Regular-mail popup shown for UID {uid}.")
        return False

    def position_window(self, window):
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() if display else None

        if monitor is None and display is not None:
            monitor = display.get_monitor(0)

        if monitor is not None:
            area = monitor.get_workarea()
            width, _height = window.get_size()
            x = area.x + area.width - width - 24
            y = area.y + 24
            window.move(x, y)

    def cancel_timeout(self):
        if self.timeout_id is not None:
            try:
                GLib.source_remove(self.timeout_id)
            except Exception:
                pass
            self.timeout_id = None

    def on_open(self, _widget, _event, sender, subject, sent_at, email):
        self.current_pending_context = None
        self.cancel_timeout()
        self.close_popup()
        threading.Thread(
            target=open_default_mail_app,
            daemon=True,
        ).start()
        return True

    def on_open_button(self, _button, sender, subject, sent_at, email):
        self.current_pending_context = None
        self.cancel_timeout()
        self.close_popup()
        threading.Thread(
            target=open_default_mail_app,
            daemon=True,
        ).start()

    def on_delete(self, _button, email, password, uid, uidvalidity, folder):
        self.current_pending_context = None
        self.cancel_timeout()
        self.close_popup()
        threading.Thread(
            target=move_regular_to_trash,
            args=(email, password, uid, uidvalidity, folder),
            daemon=True,
        ).start()

    def on_spam(self, _button, email, password, uid, uidvalidity, folder):
        self.current_pending_context = None
        self.cancel_timeout()
        self.close_popup()
        threading.Thread(
            target=move_regular_to_spam,
            args=(email, password, uid, uidvalidity, folder),
            daemon=True,
        ).start()

    def on_ignore(self, _button):
        self.current_pending_context = None
        self.close_popup()

    def on_mark_read(self, _button, email, password, uid, uidvalidity, folder):
        self.current_pending_context = None
        self.close_popup()
        def run():
            if not mark_exact_read(MailBox, IMAP_HOST, folder,
                                   email, password, uid, uidvalidity):
                add_pending_uid(email, uidvalidity, uid, folder)
        threading.Thread(target=run, daemon=True).start()

    def on_timeout(self):
        self.timeout_id = None
        print(
            "Regular-mail popup timed out; "
            "message moved to MailFlag pending state."
        )

        if self.current_pending_context is not None:
            email, folder, uidvalidity, uid = self.current_pending_context
            self.current_pending_context = None
            add_pending_uid(email, uidvalidity, uid, folder)

        self.close_popup()
        return False

    def close_popup(self):
        self.cancel_timeout()

        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass

        self.window = None
        return False

    def on_destroy(self, _window):
        self.window = None


popup = MailFlagPopup()
regular_popup = RegularMailPopup()


class TrayIndicator:
    """Always-visible system indicator for connection and pending status."""

    TITLES = {
        "online": "Connected",
        "connecting": "Connecting",
        "partial": "Partially connected",
        "offline": "Connection lost",
    }

    def __init__(self, connection_status):
        self.connection_status = connection_status
        self.unhealthy_since = None
        self.outage_notified = False
        self.indicator = AyatanaAppIndicator3.Indicator.new(
            "mailflag",
            str(STATUS_ICONS["connecting"]),
            AyatanaAppIndicator3.IndicatorCategory.COMMUNICATIONS,
        )
        self.indicator.set_status(
            AyatanaAppIndicator3.IndicatorStatus.ACTIVE
        )
        self.refresh()
        GLib.timeout_add_seconds(5, self._health_timer)

    def _disabled_item(self, text):
        item = Gtk.MenuItem(label=text)
        item.set_sensitive(False)
        return item

    def _open_pending(self, _item):
        if pending_count() > 0:
            pending_review.open()

    def _retry(self, _item):
        for email, value in self.connection_status.snapshot().items():
            if value["state"] != "connected":
                self.connection_status.update(email, "connecting", "Retrying now")
        RECONNECT_EVENT.set()

    def _quit(self, _item):
        Gtk.main_quit()

    def _open_settings(self, _item):
        installed = Path("/usr/bin/mailflag")
        command = [str(installed), "--settings"] if installed.exists() else [
            sys.executable, "-m", "mailflag", "--settings"
        ]
        try:
            subprocess.Popen(
                command, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True,
            )
        except OSError as exc:
            print(f"Settings launch failed: {exc}")

    def _set_sound(self, item, choice):
        if not item.get_active():
            return
        set_sound_choice(choice)
        self.refresh()

    def _set_open_mode(self, item, mode):
        if not item.get_active():
            return
        set_open_mode(mode)
        self.refresh()

    def _choose_sound(self, _item):
        dialog = Gtk.FileChooserDialog(
            title="Choose MailFlag notification sound",
            parent=None,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            "Cancel", Gtk.ResponseType.CANCEL,
            "Choose", Gtk.ResponseType.OK,
        )
        audio = Gtk.FileFilter()
        audio.set_name("Audio files (WAV, OGG, FLAC)")
        for pattern in ("*.wav", "*.WAV", "*.ogg", "*.OGG", "*.oga", "*.flac", "*.FLAC"):
            audio.add_pattern(pattern)
        dialog.add_filter(audio)
        current = selected_sound_path()
        if current is not None and current.exists():
            dialog.set_filename(str(current))
        response = dialog.run()
        filename = dialog.get_filename()
        dialog.destroy()
        if response == Gtk.ResponseType.OK and filename:
            try:
                set_sound_choice(filename)
                play_notification(force=True)
            except ValueError as exc:
                print(f"Sound selection error: {exc}")
        self.refresh()

    def _test_sound(self, _item):
        play_notification(force=True)

    def refresh(self):
        aggregate = self.connection_status.aggregate()
        snapshot = self.connection_status.snapshot()
        connected = sum(v["state"] == "connected" for v in snapshot.values())
        total = len(snapshot)
        count = pending_count()

        status_title = (
            "No accounts configured" if total == 0 else self.TITLES[aggregate]
        )
        icon_state = "offline" if total == 0 else aggregate

        self.indicator.set_icon_full(
            str(STATUS_ICONS[icon_state]),
            f"MailFlag: {status_title}",
        )
        self.indicator.set_label(str(count) if count else "", "99+")
        self.indicator.set_title(
            f"MailFlag — {status_title} — {count} pending"
        )

        menu = Gtk.Menu()
        menu.append(self._disabled_item(f"MailFlag {__version__}"))
        menu.append(self._disabled_item(
            f"MailFlag: {status_title} ({connected}/{total})"
        ))
        menu.append(Gtk.SeparatorMenuItem())
        symbols = {"connected": "✓", "connecting": "↻", "error": "!"}
        for email, value in snapshot.items():
            detail = value["detail"] or value["state"].capitalize()
            menu.append(self._disabled_item(
                f"{symbols[value['state']]} {email}: {detail}"
            ))
        menu.append(Gtk.SeparatorMenuItem())
        pending = Gtk.MenuItem(label=f"Pending mail: {count}")
        pending.set_sensitive(count > 0)
        pending.connect("activate", self._open_pending)
        menu.append(pending)
        retry = Gtk.MenuItem(label="Retry disconnected accounts now")
        retry.set_sensitive(connected < total)
        retry.connect("activate", self._retry)
        menu.append(retry)
        menu.append(Gtk.SeparatorMenuItem())

        choice = get_sound_choice()
        if choice == "default":
            sound_name = "Default"
        elif choice == "silent":
            sound_name = "Silent"
        else:
            sound_name = Path(choice).name
        sound_item = Gtk.MenuItem(label=f"Notification sound: {sound_name}")
        sound_menu = Gtk.Menu()
        default = Gtk.RadioMenuItem.new_with_label(None, "Default")
        silent = Gtk.RadioMenuItem.new_with_label_from_widget(default, "Silent")
        default.set_active(choice == "default")
        silent.set_active(choice == "silent")
        default.connect("activate", self._set_sound, "default")
        silent.connect("activate", self._set_sound, "silent")
        sound_menu.append(default)
        sound_menu.append(silent)
        choose = Gtk.MenuItem(label="Choose sound…")
        choose.connect("activate", self._choose_sound)
        sound_menu.append(choose)
        test = Gtk.MenuItem(label="Test sound")
        test.set_sensitive(choice != "silent")
        test.connect("activate", self._test_sound)
        sound_menu.append(test)
        sound_item.set_submenu(sound_menu)
        menu.append(sound_item)

        open_mode = get_open_mode()
        open_item = Gtk.MenuItem(label=(
            "Open mail with: Yahoo Webmail"
            if open_mode == YAHOO_WEBMAIL
            else "Open mail with: System default"
        ))
        open_menu = Gtk.Menu()
        system = Gtk.RadioMenuItem.new_with_label(None, "System default")
        yahoo = Gtk.RadioMenuItem.new_with_label_from_widget(
            system, "Yahoo Webmail"
        )
        system.set_active(open_mode == SYSTEM_DEFAULT)
        yahoo.set_active(open_mode == YAHOO_WEBMAIL)
        system.connect("activate", self._set_open_mode, SYSTEM_DEFAULT)
        yahoo.connect("activate", self._set_open_mode, YAHOO_WEBMAIL)
        open_menu.append(system)
        open_menu.append(yahoo)
        open_item.set_submenu(open_menu)
        menu.append(open_item)
        menu.append(Gtk.SeparatorMenuItem())
        settings_item = Gtk.MenuItem(label="Settings…")
        settings_item.connect("activate", self._open_settings)
        menu.append(settings_item)
        quit_item = Gtk.MenuItem(label="Quit MailFlag")
        quit_item.connect("activate", self._quit)
        menu.append(quit_item)
        menu.show_all()
        self.indicator.set_menu(menu)
        return False

    def _health_timer(self):
        now = time.monotonic()
        snapshot = self.connection_status.snapshot()
        for email in stale_connected_accounts(
            snapshot, now, CONNECTION_STALE_SECONDS
        ):
            self.connection_status.update(
                email,
                "error",
                "Heartbeat overdue; reconnecting",
            )
            interrupt_stale_mailbox(email)
        aggregate = self.connection_status.aggregate()
        if aggregate == "online":
            self.unhealthy_since = None
            self.outage_notified = False
        else:
            if self.unhealthy_since is None:
                self.unhealthy_since = now
            if now - self.unhealthy_since >= 60 and not self.outage_notified:
                self.outage_notified = True
                PLATFORM.notify(
                    "MailFlag connection problem",
                    "Mail monitoring is incomplete. Open the tray icon for details.",
                )
        return True


class PendingIndicator:
    """Persistent bottom-right MailFlag widget.  This is NOT a tray icon."""

    def __init__(self):
        self.window = None
        self.badge_area = None
        self.count = 0

    def _draw_badge(self, _widget, cr):
        count_text = pending_badge_text(self.count)

        width = _widget.get_allocated_width()
        height = _widget.get_allocated_height()
        radius = min(width, height) / 2 - 2

        cr.set_source_rgba(0.92, 0.10, 0.10, 1.0)
        cr.arc(width / 2, height / 2, radius, 0, 6.283185307)
        cr.fill()

        cr.set_source_rgba(1, 1, 1, 1)
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(13 if self.count > 99 else 17)

        ext = cr.text_extents(count_text)
        x = (width - ext.width) / 2 - ext.x_bearing
        y = (height - ext.height) / 2 - ext.y_bearing

        cr.move_to(x, y)
        cr.show_text(count_text)
        return False

    def _make_window(self):
        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window = window
        make_window_transparent(window)

        window.set_title("MailFlag pending mail")
        window.set_decorated(False)
        window.set_resizable(False)
        window.set_keep_above(True)
        window.set_skip_taskbar_hint(True)
        window.set_skip_pager_hint(True)
        window.set_accept_focus(True)
        window.set_default_size(112, 112)
        window.stick()

        event = Gtk.EventBox()
        event.set_visible_window(False)
        event.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        event.set_tooltip_text("Open new mail")
        event.connect("button-press-event", self._clicked)
        window.add(event)

        fixed = Gtk.Fixed()
        event.add(fixed)

        if INDICATOR_ICON.exists():
            try:
                source = GdkPixbuf.Pixbuf.new_from_file(str(INDICATOR_ICON))
                scaled = source.scale_simple(
                    104,
                    104,
                    GdkPixbuf.InterpType.BILINEAR,
                )

                image = Gtk.Image.new_from_pixbuf(scaled)
                fixed.put(image, 4, 4)
            except Exception as exc:
                print(
                    "Indicator icon load failed:",
                    type(exc).__name__,
                    exc,
                )
        else:
            fallback = Gtk.Label(label="✉ ⚑")
            fallback.set_size_request(112, 112)
            fixed.put(fallback, 0, 0)

        self.badge_area = Gtk.DrawingArea()
        self.badge_area.set_size_request(36, 36)
        self.badge_area.get_style_context().add_class("mailflag-badge")
        self.badge_area.connect("draw", self._draw_badge)
        fixed.put(self.badge_area, 2, 2)

        window.connect("destroy", self._destroyed)

    def _position(self):
        if self.window is None:
            return

        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() if display else None

        if monitor is None and display is not None:
            monitor = display.get_monitor(0)

        if monitor is None:
            return

        area = monitor.get_workarea()
        width, height = self.window.get_size()

        x = area.x + area.width - width - 18
        y = area.y + area.height - height - 78
        self.window.move(x, y)

    def refresh(self):
        self.count = pending_count()

        if self.count <= 0:
            self.hide()
            return False

        if self.window is None:
            self._make_window()

        if self.badge_area is not None:
            self.badge_area.queue_draw()

        self.window.show_all()
        self._position()

        print(
            f"MailFlag indicator visible: {self.count} pending message(s)."
        )
        return False

    def hide(self):
        if self.window is not None:
            try:
                self.window.hide()
            except Exception:
                pass
        return False

    def _clicked(self, _widget, _event):
        if self.count <= 0:
            return True

        self.hide()
        pending_review.open()
        return True

    def _destroyed(self, _window):
        self.window = None
        self.badge_area = None


class PendingReview:
    """
    Sequential pending-mail review across ALL configured accounts.
    Opened only by clicking the persistent indicator.
    """

    def __init__(self):
        self.active = False
        self.loading = False
        self.items = deque()
        self.window = None
        self.timeout_id = None

    def open(self):
        if self.active or self.loading:
            return False

        pending = get_pending_items()
        if not pending:
            pending_indicator.refresh()
            return False

        if not APP_ACCOUNTS:
            print("Pending review unavailable: no account credentials loaded.")
            pending_indicator.refresh()
            return False

        self.loading = True

        threading.Thread(
            target=self._load_messages,
            args=(pending,),
            daemon=True,
        ).start()

        return False

    def _load_messages(self, pending):
        items = []

        by_account = {}
        for email, folder, uid in pending:
            by_account.setdefault((email, folder), []).append(int(uid))

        try:
            for (email, folder), uids in by_account.items():
                password = APP_ACCOUNTS.get(email)
                if not password:
                    continue

                with MailBox(IMAP_HOST).login(
                    email,
                    password,
                    initial_folder=folder,
                ) as mailbox:
                    status = mailbox.folder.status(folder)
                    uidvalidity = int(status["UIDVALIDITY"])

                    state = load_mail_state(email, folder)
                    if (
                        not state
                        or int(state["uidvalidity"]) != uidvalidity
                    ):
                        print(
                            f"[{email}] Pending review skipped because "
                            "UIDVALIDITY changed."
                        )
                        continue

                    messages = list(
                        mailbox.fetch(
                            uid_list=[str(uid) for uid in uids],
                            mark_seen=False,
                        )
                    )
                    messages.sort(key=lambda msg: int(msg.uid))

                    found = {int(msg.uid) for msg in messages}
                    for uid in uids:
                        if uid not in found:
                            remove_pending_uid(
                                email,
                                uidvalidity,
                                uid,
                                folder,
                            )

                    for msg in messages:
                        subject = msg.subject or "(no subject)"
                        sender = format_message_sender(msg)
                        sender_email = msg.from_ or "(unknown sender)"
                        reference = _message_reference(msg, sender, subject)
                        save_message_reference(
                            email, uidvalidity, msg.uid, reference, folder
                        )

                        body = extract_human_text(msg.text, msg.html)

                        code = extract_code(subject, body)
                        items.append(
                            {
                                "email": email,
                                "folder": folder,
                                "password": password,
                                "uidvalidity": uidvalidity,
                                "uid": int(msg.uid),
                                "sender": sender_email if code else sender,
                                "subject": subject,
                                "preview": extract_preview(msg.text, msg.html),
                                "code": code,
                                "message_id": reference["message_id"],
                                "date": reference["date"],
                            }
                        )

            GLib.idle_add(self._start_loaded, items)

        except Exception as exc:
            print(
                "Pending review load error:",
                type(exc).__name__,
                exc,
            )
            GLib.idle_add(self._load_failed)

    def _load_failed(self):
        self.loading = False
        self.active = False
        pending_indicator.refresh()
        return False

    def _start_loaded(self, items):
        self.loading = False

        items = [item for item in items if item["email"] in APP_ACCOUNTS]

        if not items:
            self.active = False
            pending_indicator.refresh()
            return False

        self.items = deque(items)
        self.active = True
        self._show_next()
        return False

    def remove_account(self, email):
        self.items = deque(
            item for item in self.items if item["email"] != email
        )
        if self.active:
            self._show_next()
        return False

    def _cancel_timeout(self):
        if self.timeout_id is not None:
            try:
                GLib.source_remove(self.timeout_id)
            except Exception:
                pass
            self.timeout_id = None

    def _destroy_window(self):
        self._cancel_timeout()

        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass

        self.window = None

    def _stop_and_return_to_indicator(self):
        self._destroy_window()
        self.items.clear()
        self.active = False
        pending_indicator.refresh()
        return False

    def _show_next(self):
        self._destroy_window()

        if not self.items:
            self.active = False
            pending_indicator.refresh()
            return False

        item = self.items[0]

        if item["code"]:
            self._show_otp(item)
        else:
            self._show_regular(item)

        self.timeout_id = GLib.timeout_add_seconds(
            POPUP_TIMEOUT_SECONDS,
            self._review_timeout,
        )
        return False

    def _add_account_label(self, outer, item):
        if len(APP_ACCOUNTS) <= 1:
            return

        label = Gtk.Label()
        label.set_markup(
            "<small><b>Account:</b> " +
            GLib.markup_escape_text(item["email"]) +
            "</small>"
        )
        label.set_xalign(0.0)
        compact_label(label)
        outer.pack_start(label, False, False, 0)

    def _show_otp(self, item):
        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window = window
        make_window_transparent(window)

        window.set_title("MailFlag — Pending verification code")
        window.set_decorated(False)
        window.set_resizable(False)
        window.set_keep_above(True)
        window.set_skip_taskbar_hint(True)
        window.set_skip_pager_hint(True)
        window.set_accept_focus(True)
        window.set_default_size(540, 270)

        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=11,
        )
        style_popup_card(outer)
        outer.set_border_width(0)
        window.add(outer)

        position = Gtk.Label()
        position.set_markup(
            f"<small>Pending mail · {pending_count()} remaining</small>"
        )
        scale_popup_label(position)
        outer.pack_start(position, False, False, 0)

        self._add_account_label(outer, item)

        code_event = Gtk.EventBox()
        code_event.set_visible_window(False)
        code_event.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        code_event.set_tooltip_text("Click to copy and remove this OTP mail")
        code_event.connect(
            "button-press-event",
            self._otp_clicked,
            item,
        )

        code_label = Gtk.Label(label=item["code"])
        code_label.modify_font(Pango.FontDescription("Sans Bold 38"))
        code_event.add(code_label)
        outer.pack_start(code_event, True, True, 0)

        sender = Gtk.Label()
        sender.set_markup(
            "<b>From:</b> " +
            GLib.markup_escape_text(item["sender"])
        )
        sender.set_xalign(0.0)
        scale_popup_label(sender)
        outer.pack_start(sender, False, False, 0)

        subject = Gtk.Label()
        subject.set_markup(
            "<b>Subject:</b> " +
            GLib.markup_escape_text(item["subject"])
        )
        subject.set_xalign(0.0)
        scale_popup_label(subject)
        outer.pack_start(subject, False, False, 0)

        window.show_all()
        self._position_review_window()

    def _show_regular(self, item):
        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window = window
        make_window_transparent(window)

        window.set_title("MailFlag — Pending mail")
        window.set_decorated(False)
        window.set_resizable(False)
        window.set_keep_above(True)
        window.set_skip_taskbar_hint(True)
        window.set_skip_pager_hint(True)
        window.set_accept_focus(True)
        window.set_default_size(520, 360)

        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=11,
        )
        style_popup_card(outer)
        outer.set_border_width(0)
        window.add(outer)

        position = Gtk.Label()
        position.set_markup(
            f"<small>Pending mail · {pending_count()} remaining</small>"
        )
        position.set_xalign(0.0)
        scale_popup_label(position)
        outer.pack_start(position, False, False, 0)

        self._add_account_label(outer, item)

        sender = Gtk.Label()
        sender.set_markup(
            "<b>From:</b> " +
            GLib.markup_escape_text(item["sender"])
        )
        sender.set_xalign(0.0)
        compact_label(sender)
        outer.pack_start(sender, False, False, 0)

        subject = Gtk.Label()
        subject.set_markup(
            "<b>Subject:</b> " +
            GLib.markup_escape_text(item["subject"])
        )
        subject.set_xalign(0.0)
        compact_label(subject)
        subject.set_ellipsize(Pango.EllipsizeMode.END)
        outer.pack_start(subject, False, False, 0)

        preview = Gtk.Label(label=item["preview"] or "(no text preview)")
        preview.set_xalign(0.0)
        compact_label(preview)
        preview.set_line_wrap(True)
        preview.set_lines(3)
        preview.set_ellipsize(Pango.EllipsizeMode.END)
        outer.pack_start(preview, True, True, 0)

        actions = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
        )

        open_button = Gtk.Button(label="Open")
        style_action_button(open_button, "open")
        open_button.connect("clicked", self._regular_open, item)
        actions.pack_start(open_button, True, True, 0)

        delete_button = Gtk.Button(label="Delete")
        style_action_button(delete_button, "delete")
        delete_button.connect("clicked", self._regular_delete, item)
        actions.pack_start(delete_button, True, True, 0)

        spam_button = Gtk.Button(label="Spam")
        style_action_button(spam_button, "spam")
        spam_button.connect("clicked", self._regular_spam, item)
        actions.pack_start(spam_button, True, True, 0)

        outer.pack_start(actions, False, False, 0)

        secondary = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        ignore = Gtk.Button(label="Ignore")
        style_action_button(ignore, "ignore")
        ignore.connect("clicked", lambda _button: self._finish_current(item))
        secondary.pack_start(ignore, True, True, 0)
        read = Gtk.Button(label="Mark as Read")
        style_action_button(read, "read")
        read.connect("clicked", self._regular_read, item)
        secondary.pack_start(read, True, True, 0)
        outer.pack_start(secondary, False, False, 0)

        window.show_all()
        self._position_review_window()

    def _position_review_window(self):
        if self.window is None:
            return

        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() if display else None

        if monitor is None and display is not None:
            monitor = display.get_monitor(0)

        if monitor is not None:
            area = monitor.get_workarea()
            width, _height = self.window.get_size()
            self.window.move(
                area.x + area.width - width - 24,
                area.y + 24,
            )

    def _finish_current(self, item):
        remove_pending_uid(
            item["email"],
            item["uidvalidity"],
            item["uid"],
            item["folder"],
        )

        if self.items and (
            self.items[0]["email"],
            self.items[0]["folder"],
            self.items[0]["uid"],
        ) == (
            item["email"],
            item["folder"],
            item["uid"],
        ):
            self.items.popleft()
        else:
            self.items = deque(
                x
                for x in self.items
                if not (
                    x["email"] == item["email"]
                    and x["folder"] == item["folder"]
                    and x["uid"] == item["uid"]
                )
            )

        self._show_next()

    def _otp_clicked(self, _widget, _event, item):
        PLATFORM.copy_text(item["code"])
        PLATFORM.copy_text(item["code"], primary=True)

        print(
            f"[{item['email']}] Pending OTP copied: UID {item['uid']}"
        )

        threading.Thread(
            target=move_message_to_trash,
            args=(
                item["email"],
                item["password"],
                item["uid"],
                item["uidvalidity"],
                item["folder"],
            ),
            daemon=True,
        ).start()

        self._finish_current(item)
        return True

    def _regular_read(self, _button, item):
        self._cancel_timeout()
        self._destroy_window()
        def completed(ok):
            if ok:
                self._finish_current(item)
            else:
                self._stop_and_return_to_indicator()
            return False
        def run():
            ok = mark_exact_read(MailBox, IMAP_HOST, item["folder"],
                                 item["email"], item["password"],
                                 item["uid"], item["uidvalidity"])
            GLib.idle_add(completed, ok)
        threading.Thread(target=run, daemon=True).start()

    def _regular_open(self, _button, item):
        self._cancel_timeout()
        snapshots = {}
        for queued in self.items:
            if queued["email"] == item["email"]:
                key = (queued["folder"], int(queued["uidvalidity"]))
                snapshots.setdefault(key, set()).add(queued["uid"])
        snapshots.setdefault(
            (item["folder"], int(item["uidvalidity"])), set()
        ).add(item["uid"])
        for (folder, uidvalidity), uids in snapshots.items():
            clear_pending_snapshot(
                item["email"], uidvalidity, uids, folder
            )
        threading.Thread(
            target=open_default_mail_app,
            daemon=True,
        ).start()
        # Open means the user will review this account's mailbox. Other
        # accounts and mail that arrived after this review opened stay pending.
        self._stop_and_return_to_indicator()

    def _regular_delete(self, _button, item):
        threading.Thread(
            target=move_regular_to_trash,
            args=(
                item["email"],
                item["password"],
                item["uid"],
                item["uidvalidity"],
                item["folder"],
            ),
            daemon=True,
        ).start()
        self._finish_current(item)

    def _regular_spam(self, _button, item):
        threading.Thread(
            target=move_regular_to_spam,
            args=(
                item["email"],
                item["password"],
                item["uid"],
                item["uidvalidity"],
                item["folder"],
            ),
            daemon=True,
        ).start()
        self._finish_current(item)

    def _review_timeout(self):
        self.timeout_id = None
        print(
            "Pending review timed out. Remaining mail stays behind "
            "the MailFlag indicator."
        )
        self._stop_and_return_to_indicator()
        return False



pending_indicator = PendingIndicator()
pending_review = PendingReview()



APP_ACCOUNTS = {}
APP_MONITORED_FOLDERS = {}


def refresh_tray_async():
    if tray_indicator is not None:
        GLib.idle_add(tray_indicator.refresh)


def set_connection_state(email, state, detail=""):
    if CONNECTION_STATUS is not None:
        CONNECTION_STATUS.update(email, state, detail)


class _GtkMonitorEvents:
    """Thin adapter from portable monitor events to Linux GTK/state services."""

    def connection_changed(self, account, state, detail=""):
        set_connection_state(account, state, detail)

    def register_mailbox(self, account, mailbox):
        register_active_mailbox(account, mailbox)

    def unregister_mailbox(self, account, mailbox):
        unregister_active_mailbox(account, mailbox)

    def connected(self, account, mailbox, uidvalidity, uidnext):
        print(f"[{account}] Connected. Next new UID: {uidnext}")
        print(f"[{account}] {IMAP_FOLDER} UIDVALIDITY: {uidvalidity}")
        try:
            print(f"[{account}] Trash folder detected: {find_trash_folder(mailbox)}")
        except Exception as exc:
            print(f"[{account}] WARNING: {exc}")

    def monitored_folders(self, account):
        return APP_MONITORED_FOLDERS.get(account, [IMAP_FOLDER])

    def folder_error(self, account, folder, exc):
        print(
            f"[{account}/{folder}] Folder unavailable: "
            f"{type(exc).__name__}: {exc}. Other folders remain active."
        )

    def recover_pending(self, mailbox, account, folder, uidvalidity, uidnext):
        return recover_backlog_messages(
            mailbox, account, uidvalidity, uidnext, folder
        )

    def process_live(self, mailbox, account, folder, uidvalidity, uidnext,
                     password):
        return process_live_new_messages(
            mailbox, account, uidvalidity, uidnext, password, folder
        )

    def resumed(self, account, gap):
        print(f"[{account}] Resume detected (suspend gap ~{gap:.1f}s).")

    def heartbeat(self, account):
        print(f"[{account}] IDLE heartbeat: OK")

    def interrupted(self, account, exc, retry_seconds):
        print(
            f"[{account}] IMAP connection interrupted: "
            f"{type(exc).__name__}: {exc}"
        )
        print(f"[{account}] Reconnecting in {retry_seconds} seconds...")


def imap_worker(email, password, stop_event=None):
    print(f"[{email}] worker started.")
    run_account_monitor(
        email, password, YAHOO, MailBox, PLATFORM, _GtkMonitorEvents(),
        RECONNECT_EVENT, MONITOR_CONFIG, SUSPEND_GAP_SECONDS,
        stop_event=stop_event,
    )


def start_account_worker(email, password):
    stop_event = threading.Event()
    worker = threading.Thread(
        target=imap_worker,
        args=(email, password, stop_event),
        daemon=True,
        name=f"mailflag-{email}",
    )
    ACCOUNT_STOP_EVENTS[email] = stop_event
    ACCOUNT_WORKERS[email] = worker
    worker.start()
    return worker


def remove_runtime_account(email):
    snapshot = CONNECTION_STATUS.snapshot() if CONNECTION_STATUS else {}
    if email not in snapshot:
        raise KeyError(f"Unknown MailFlag account: {email}")

    password = APP_ACCOUNTS.get(email)
    stop_event = ACCOUNT_STOP_EVENTS.get(email)
    worker = ACCOUNT_WORKERS.get(email)
    if stop_event is not None:
        stop_event.set()
    interrupt_stale_mailbox(email)
    if worker is not None:
        worker.join(timeout=MONITOR_CONFIG.socket_timeout + 5)
        if worker.is_alive():
            raise RuntimeError("The account connection did not stop safely")

    try:
        from .settings_service import SettingsService
        SettingsService().remove_account(email)
    except Exception:
        if password:
            start_account_worker(email, password)
        raise

    APP_ACCOUNTS.pop(email, None)
    APP_MONITORED_FOLDERS.pop(email, None)
    ACCOUNT_STOP_EVENTS.pop(email, None)
    ACCOUNT_WORKERS.pop(email, None)
    unregister_active_mailbox(email)
    if CONNECTION_STATUS is not None:
        CONNECTION_STATUS.remove(email)
    GLib.idle_add(pending_review.remove_account, email)
    GLib.idle_add(pending_indicator.refresh)
    if tray_indicator is not None:
        GLib.idle_add(tray_indicator.refresh)
    print(f"[{email}] Account removed locally. Server mail was not changed.")
    return "OK"


def handle_control_command(command):
    if command == "stop":
        GLib.idle_add(Gtk.main_quit)
        return "OK"
    prefix = "remove-account "
    if command.startswith(prefix):
        email = command[len(prefix):].strip()
        if not email:
            raise ValueError("Account email is missing")
        return remove_runtime_account(email)
    raise ValueError(f"Unknown control command: {command}")


def main():
    global APP_ACCOUNTS, APP_MONITORED_FOLDERS, CONNECTION_STATUS, tray_indicator

    try:
        accounts = load_accounts()
    except Exception as exc:
        print("Startup error:", type(exc).__name__, exc)
        return

    if not accounts:
        print("No Yahoo accounts configured.")
        return

    config = configparser.ConfigParser()
    if CONFIG_FILE.exists():
        config.read(CONFIG_FILE, encoding="utf-8")
    APP_MONITORED_FOLDERS = {
        email: configured_folders(config, email, IMAP_FOLDER)
        for email in accounts
    }

    migrate_legacy_state(accounts[0])

    credentials = {}
    credential_errors = {}

    for email in accounts:
        try:
            credentials[email] = load_password(email)
        except Exception as exc:
            credential_errors[email] = f"Keyring: {type(exc).__name__}"
            print(
                f"[{email}] Account disabled for this run: "
                f"{type(exc).__name__}: {exc}"
            )

    install_ui_styles()
    if APPLICATION_ICON.exists():
        try:
            Gtk.Window.set_default_icon_from_file(str(APPLICATION_ICON))
        except GLib.Error as exc:
            print(f"Application icon error: {exc}")

    APP_ACCOUNTS = credentials
    CONNECTION_STATUS = ConnectionStatus(accounts, refresh_tray_async)
    tray_indicator = TrayIndicator(CONNECTION_STATUS)
    for email, detail in credential_errors.items():
        CONNECTION_STATUS.update(email, "error", detail)

    print()
    print(f"MailFlag v{__version__}")
    print(f"Accounts configured: {len(accounts)}")
    for email in accounts:
        suffix = "" if email in credentials else " (keyring unavailable)"
        print(" -", email + suffix)
    for email in accounts:
        print(f"[{email}] Monitored folders: " + ", ".join(
            APP_MONITORED_FOLDERS[email]
        ))
    print("Persistent bottom-right indicator: ENABLED")
    print("Portable startup/reconnect/resume classification: ENABLED")
    print("Desktop-specific APIs: NOT USED")
    print("System tray connection indicator: ENABLED")
    print()

    for email, password in credentials.items():
        start_account_worker(email, password)

    GLib.idle_add(pending_indicator.refresh)
    GLib.idle_add(tray_indicator.refresh)

    control = ControlServer(CONFIG_DIR / "control.sock", handle_control_command)
    control.start()
    try:
        Gtk.main()
    except KeyboardInterrupt:
        print()
        print("MailFlag stopped.")
    finally:
        control.close()


if __name__ == "__main__":
    main()
