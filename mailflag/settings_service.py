"""Headless settings operations shared by the GTK UI and tests."""

import configparser
import imaplib
import os
import socket
import ssl
from pathlib import Path

from imap_tools import MailBox, MailBoxUnencrypted, MailboxLoginError

from .core.accounts import (
    AccountSettings, account_settings, configured_accounts, configured_emails,
    configured_folders, new_custom_account_id, set_configured_folders,
    set_custom_account,
)
from .core.state import read_store, write_store
from .folders import selectable_folder_names
from .platform import get_platform
from .providers import YAHOO


POPUP_DURATIONS = (10, 20, 30, 45, 60)


class SettingsService:
    def __init__(self, platform=None, mailbox_factory=MailBox,
                 unencrypted_mailbox_factory=MailBoxUnencrypted):
        self.platform = platform or get_platform()
        self.mailbox_factory = mailbox_factory
        self.unencrypted_mailbox_factory = unencrypted_mailbox_factory

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

    def account_details(self, account):
        if account not in self.accounts():
            raise KeyError(account)
        return account_settings(self.read_config(), account)

    def account_records(self):
        return configured_accounts(self.read_config())

    def folders(self, account):
        return configured_folders(self.read_config(), account, YAHOO.inbox)

    @staticmethod
    def _validate_endpoint(host, port):
        host = str(host or "").strip()
        if not host or any(character.isspace() for character in host):
            raise ValueError("Invalid IMAP host.")
        try:
            port = int(port)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid IMAP port.") from exc
        if not 1 <= port <= 65535:
            raise ValueError("Invalid IMAP port.")
        return host, port

    def _mailbox(self, settings):
        host, port = self._validate_endpoint(
            settings.imap_host, settings.imap_port
        )
        factory = (self.mailbox_factory if settings.imap_ssl
                   else self.unencrypted_mailbox_factory)
        return factory(host, port=port, timeout=15)

    @staticmethod
    def _check_required_features(mailbox, inbox="INBOX"):
        mailbox.folder.status(inbox)
        capabilities = getattr(mailbox.client, "capabilities", ())
        if isinstance(capabilities, (tuple, list, set, frozenset)):
            names = {
                (item.decode("ascii", "ignore") if isinstance(item, bytes)
                 else str(item)).upper()
                for item in capabilities
            }
            if names and "IDLE" not in names:
                raise RuntimeError(
                    "Server does not support required IMAP IDLE functionality."
                )

    @staticmethod
    def _friendly_connection_error(exc):
        text = str(exc).strip()
        folded = text.casefold()
        if isinstance(exc, ValueError):
            return exc
        if isinstance(exc, ssl.SSLError) or any(
            word in folded for word in ("certificate", "ssl", "tls")
        ):
            return RuntimeError(f"SSL/TLS error: {text or type(exc).__name__}")
        if isinstance(exc, (imaplib.IMAP4.error, MailboxLoginError)) or any(
            word in folded for word in (
                "authentication", "authenticate", "login failed",
                "invalid credentials", "authfailed",
            )
        ):
            return RuntimeError("Authentication failed. Check the username and password.")
        if isinstance(exc, (socket.gaierror, TimeoutError, ConnectionError, OSError)):
            return RuntimeError(
                f"IMAP host is unreachable: {text or type(exc).__name__}"
            )
        if "required imap" in folded:
            return exc
        return RuntimeError(f"IMAP connection failed: {text or type(exc).__name__}")

    def _test_settings(self, settings, password):
        if not settings.username or not password:
            raise ValueError("Username and password are required.")
        try:
            with self._mailbox(settings).login(
                settings.username, password, initial_folder=None,
            ) as mailbox:
                self._check_required_features(mailbox)
        except Exception as exc:
            friendly = self._friendly_connection_error(exc)
            if friendly is exc:
                raise
            raise friendly from exc
        return True

    def test_connection(self, account, password):
        if account in self.accounts():
            settings = self.account_details(account)
        else:
            settings = AccountSettings(
                account, "yahoo", account, account, YAHOO.imap_host,
                YAHOO.imap_port, YAHOO.imap_ssl,
            )
        return self._test_settings(settings, password)

    def custom_settings(self, display_name, username, host, port=993,
                        use_ssl=True, account_id=None):
        host, port = self._validate_endpoint(host, port)
        display_name = str(display_name or "").strip()
        username = str(username or "").strip()
        if not display_name:
            raise ValueError("Account name is required.")
        if not username:
            raise ValueError("Email / username is required.")
        return AccountSettings(
            account_id or new_custom_account_id(), "custom_imap",
            display_name, username, host, port, bool(use_ssl),
        )

    def test_custom_connection(self, display_name, username, host, port,
                               use_ssl, password):
        settings = self.custom_settings(
            display_name, username, host, port, use_ssl
        )
        self._test_settings(settings, password)
        return True

    def discover_folders(self, account, password=None):
        settings = (self.account_details(account) if account in self.accounts()
                    else AccountSettings(
                        account, "yahoo", account, account, YAHOO.imap_host,
                        YAHOO.imap_port, YAHOO.imap_ssl,
                    ))
        password = password or self.platform.credentials.get(account)
        if not password:
            raise RuntimeError("Password is unavailable in the system keyring.")
        try:
            with self._mailbox(settings).login(
                settings.username, password, initial_folder=None,
            ) as mailbox:
                self._check_required_features(mailbox)
                return ["INBOX"] + selectable_folder_names(
                    mailbox.folder.list(), "INBOX"
                )
        except Exception as exc:
            friendly = self._friendly_connection_error(exc)
            if friendly is exc:
                raise
            raise friendly from exc

    def discover_custom_folders(self, display_name, username, host, port,
                                use_ssl, password):
        settings = self.custom_settings(
            display_name, username, host, port, use_ssl
        )
        self._test_settings(settings, password)
        try:
            with self._mailbox(settings).login(
                settings.username, password, initial_folder=None,
            ) as mailbox:
                return ["INBOX"] + selectable_folder_names(
                    mailbox.folder.list(), "INBOX"
                )
        except Exception as exc:
            friendly = self._friendly_connection_error(exc)
            raise friendly from exc

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

    def add_custom_account(self, display_name, username, host, port, use_ssl,
                           password, folders=("INBOX",), account_id=None):
        settings = self.custom_settings(
            display_name, username, host, port, use_ssl, account_id
        )
        if not password:
            raise ValueError("Password / app password is required.")
        self._test_settings(settings, password)
        config = self.read_config()
        accounts = configured_emails(config)
        if settings.account_id in accounts:
            raise ValueError("This Custom IMAP account already exists.")
        accounts.append(settings.account_id)
        if not config.has_section("accounts"):
            config.add_section("accounts")
        config.set("accounts", "emails", "\n".join(accounts))
        if not config.has_section("account"):
            config.add_section("account")
        config.set("account", "email", accounts[0])
        set_custom_account(config, settings)
        set_configured_folders(config, settings.account_id, folders, "INBOX")
        self.platform.credentials.set(settings.account_id, password)
        try:
            self.write_config(config)
        except Exception:
            self.platform.credentials.delete(settings.account_id)
            raise
        return settings.account_id

    def update_folders(self, account, folders):
        config = self.read_config()
        if account not in configured_emails(config):
            raise KeyError(account)
        result = set_configured_folders(config, account, folders, YAHOO.inbox)
        self.write_config(config)
        return result

    def update_yahoo_credential(self, account, password):
        return self.update_account_credential(account, password)

    def update_account_credential(self, account, password):
        if account not in self.accounts():
            raise KeyError(account)
        self.test_connection(account, password)
        self.platform.credentials.set(account, password)

    def update_custom_account(self, account, display_name, username, host,
                              port, use_ssl, password):
        current = self.account_details(account)
        if current.provider_id != "custom_imap":
            raise ValueError("The selected account is not Custom IMAP.")
        settings = self.custom_settings(
            display_name, username, host, port, use_ssl, account
        )
        self._test_settings(settings, password)
        config = self.read_config()
        original = self.read_config()
        old_secret = self.platform.credentials.get(account)
        set_custom_account(config, settings)
        self.platform.credentials.set(account, password)
        try:
            self.write_config(config)
        except Exception:
            if old_secret:
                self.platform.credentials.set(account, old_secret)
            self.write_config(original)
            raise
        return account

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
