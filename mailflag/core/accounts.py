"""Portable account configuration parsing."""


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
