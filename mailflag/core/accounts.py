"""Portable account configuration parsing."""

from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class AccountSettings:
    account_id: str
    provider_id: str
    display_name: str
    username: str
    imap_host: str
    imap_port: int = 993
    imap_ssl: bool = True


def new_custom_account_id():
    return f"custom-{uuid4().hex}"


def configured_emails(config):
    result = []
    old = config.get("account", "email", fallback="").strip()
    if old:
        result.append(old)
    for line in config.get("accounts", "emails", fallback="").splitlines():
        email = line.strip()
        if email and email not in result:
            result.append(email)
    return result


def account_settings(config, account_id):
    """Read one account while preserving the legacy Yahoo configuration."""
    section = f"account:{account_id}"
    provider = config.get(section, "provider", fallback="yahoo").strip()
    if provider == "custom_imap":
        return AccountSettings(
            account_id=account_id,
            provider_id=provider,
            display_name=config.get(section, "display_name", fallback="").strip()
                         or account_id,
            username=config.get(section, "username", fallback="").strip(),
            imap_host=config.get(section, "imap_host", fallback="").strip(),
            imap_port=config.getint(section, "imap_port", fallback=993),
            imap_ssl=config.getboolean(section, "imap_ssl", fallback=True),
        )
    return AccountSettings(
        account_id=account_id,
        provider_id="yahoo",
        display_name=config.get(section, "display_name", fallback="").strip()
                     or account_id,
        username=config.get(section, "username", fallback="").strip()
                 or account_id,
        imap_host="imap.mail.yahoo.com",
        imap_port=993,
        imap_ssl=True,
    )


def configured_accounts(config):
    return [account_settings(config, item) for item in configured_emails(config)]


def set_custom_account(config, settings):
    section = f"account:{settings.account_id}"
    if not config.has_section(section):
        config.add_section(section)
    config.set(section, "provider", "custom_imap")
    config.set(section, "display_name", settings.display_name)
    config.set(section, "username", settings.username)
    config.set(section, "imap_host", settings.imap_host)
    config.set(section, "imap_port", str(settings.imap_port))
    config.set(section, "imap_ssl", str(bool(settings.imap_ssl)).lower())


def normalize_monitored_folders(values, inbox="INBOX"):
    """Return a stable folder list with INBOX always enabled."""
    result = [inbox]
    seen = {inbox.casefold()}
    for value in values:
        folder = str(value).strip()
        if folder and folder.casefold() not in seen:
            seen.add(folder.casefold())
            result.append(folder)
    return result


def configured_folders(config, email, inbox="INBOX"):
    section = f"account:{email}"
    raw = config.get(section, "monitored_folders", fallback="")
    return normalize_monitored_folders(raw.splitlines(), inbox)


def set_configured_folders(config, email, folders, inbox="INBOX"):
    section = f"account:{email}"
    if not config.has_section(section):
        config.add_section(section)
    normalized = normalize_monitored_folders(folders, inbox)
    config.set(section, "monitored_folders", "\n".join(normalized))
    return normalized
