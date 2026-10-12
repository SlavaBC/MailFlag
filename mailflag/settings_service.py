"""Headless settings operations shared by the GTK UI and tests."""

import configparser
import os
from pathlib import Path

from imap_tools import MailBox

from .core.accounts import configured_emails, configured_folders, set_configured_folders
from .core.state import read_store, write_store
from .folders import selectable_folder_names
from .platform import get_platform
from .providers import YAHOO


POPUP_DURATIONS = (10, 20, 30, 45, 60)


class SettingsService:
    def __init__(self, platform=None, mailbox_factory=MailBox):
        self.platform = platform or get_platform()
        self.mailbox_factory = mailbox_factory

    @property
    def config_file(self):
        return self.platform.paths.config_file

    def read_config(self):
        config = configparser.ConfigParser(interpolation=None)
        if self.config_file.exists():
            config.read(self.config_file, encoding="utf-8")
        return config

    def write_config(self, config):
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_file.with_suffix(".ini.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            config.write(stream)
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.config_file)
        os.chmod(self.config_file, 0o600)

    def accounts(self):
        return configured_emails(self.read_config())

    def folders(self, account):
        return configured_folders(self.read_config(), account, YAHOO.inbox)

    def test_connection(self, account, password):
        with self.mailbox_factory(YAHOO.imap_host, timeout=15).login(
            account, password, initial_folder=None,
        ) as mailbox:
            mailbox.folder.status(YAHOO.inbox)
        return True

    def discover_folders(self, account, password=None):
        password = password or self.platform.credentials.get(account)
        if not password:
            raise RuntimeError("App Password is unavailable in the system keyring.")
        with self.mailbox_factory(YAHOO.imap_host, timeout=15).login(
            account, password, initial_folder=None,
        ) as mailbox:
            return [YAHOO.inbox] + selectable_folder_names(
                mailbox.folder.list(), YAHOO.inbox
            )

    def add_yahoo_account(self, account, password, folders=("INBOX",)):
        account = account.strip()
        if not account or not password:
            raise ValueError("Email and App Password are required.")
        self.test_connection(account, password)
        config = self.read_config()
        accounts = configured_emails(config)
        if account not in accounts:
            accounts.append(account)
        if not config.has_section("accounts"):
            config.add_section("accounts")
        config.set("accounts", "emails", "\n".join(accounts))
        if not config.has_section("account"):
            config.add_section("account")
        config.set("account", "email", accounts[0])
        set_configured_folders(config, account, folders, YAHOO.inbox)
        self.platform.credentials.set(account, password)
        try:
            self.write_config(config)
        except Exception:
            self.platform.credentials.delete(account)
            raise
        return account

    def update_folders(self, account, folders):
        config = self.read_config()
        if account not in configured_emails(config):
            raise KeyError(account)
        result = set_configured_folders(config, account, folders, YAHOO.inbox)
        self.write_config(config)
        return result

    def update_yahoo_credential(self, account, password):
        if account not in self.accounts():
            raise KeyError(account)
        self.test_connection(account, password)
        self.platform.credentials.set(account, password)

    def remove_account(self, account):
        original_config = self.read_config()
        if account not in configured_emails(original_config):
            raise KeyError(account)
        config = self.read_config()
        accounts = [item for item in configured_emails(config) if item != account]
        if config.has_section("accounts"):
            config.set("accounts", "emails", "\n".join(accounts))
        if config.has_section("account"):
            config.set("account", "email", accounts[0] if accounts else "")
        config.remove_section(f"account:{account}")
        original_state = read_store(self.platform.paths.state_file)
        state = read_store(self.platform.paths.state_file)
        state["accounts"].pop(account, None)
        credential = self.platform.credentials.get(account)
        credential_deleted = False
        config_written = False
        try:
            if credential:
                self.platform.credentials.delete(account)
                credential_deleted = True
            self.write_config(config)
            config_written = True
            write_store(self.platform.paths.state_file, state)
        except Exception as exc:
            rollback_errors = []
            if config_written:
                try:
                    self.write_config(original_config)
                except Exception as rollback_exc:
                    rollback_errors.append(f"config rollback: {rollback_exc}")
                try:
                    write_store(self.platform.paths.state_file, original_state)
                except Exception as rollback_exc:
                    rollback_errors.append(f"state rollback: {rollback_exc}")
            if credential_deleted:
                try:
                    self.platform.credentials.set(account, credential)
                except Exception as rollback_exc:
                    rollback_errors.append(f"credential rollback: {rollback_exc}")
            detail = f"Account removal failed: {exc}"
            if rollback_errors:
                detail += "; " + "; ".join(rollback_errors)
            raise RuntimeError(detail) from exc

    def notification_preferences(self):
        config = self.read_config()
        duration = config.getint("notifications", "popup_duration", fallback=30)
        if duration not in POPUP_DURATIONS:
            duration = 30
        return {
            "show_popup": config.getboolean("notifications", "show_popup", fallback=True),
            "play_sound": config.getboolean("notifications", "play_sound", fallback=True),
            "popup_duration": duration,
        }

    def save_notification_preferences(self, show_popup, play_sound, duration):
        duration = int(duration)
        if duration not in POPUP_DURATIONS:
            raise ValueError("Unsupported popup duration.")
        config = self.read_config()
        if not config.has_section("notifications"):
            config.add_section("notifications")
        config.set("notifications", "show_popup", str(bool(show_popup)).lower())
        config.set("notifications", "play_sound", str(bool(play_sound)).lower())
        config.set("notifications", "popup_duration", str(duration))
        self.write_config(config)


def otp_timeout(popup_duration):
    return min(30, int(popup_duration))


__all__ = ["SettingsService", "POPUP_DURATIONS", "otp_timeout"]
