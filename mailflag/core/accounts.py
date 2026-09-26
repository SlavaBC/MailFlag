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

