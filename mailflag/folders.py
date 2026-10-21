"""Interactive discovery and per-account monitored-folder configuration."""

import configparser
import os
import sys

from .core.accounts import configured_emails, configured_folders, set_configured_folders
from .platform import get_platform


EXCLUDED_SPECIAL_FLAGS = {
    r"\Noselect", r"\Trash", r"\Junk", r"\Sent", r"\Drafts", r"\All",
    r"\Archive",
}
EXCLUDED_YAHOO_NAMES = {"Bulk", "Trash", "Sent", "Draft"}


def selectable_folder_names(folder_infos, inbox="INBOX"):
    result = []
    for info in folder_infos:
        name = str(getattr(info, "name", "") or "").strip()
        flags = {str(flag).casefold() for flag in getattr(info, "flags", ())}
        if not name or any(flag.casefold() in flags for flag in EXCLUDED_SPECIAL_FLAGS):
            continue
        if name.casefold() in {value.casefold() for value in EXCLUDED_YAHOO_NAMES}:
            continue
        if name.casefold() == inbox.casefold():
            continue
        result.append(name)
    return sorted(set(result), key=str.casefold)


def _choose_account(accounts, requested=None):
    if requested:
        if requested not in accounts:
            raise SystemExit(f"Unknown MailFlag account: {requested}")
        return requested
    if len(accounts) == 1:
        return accounts[0]
    print("MailFlag accounts:")
    for index, account in enumerate(accounts, 1):
        print(f"  {index}. {account}")
    raw = input("Choose account number: ").strip()
    try:
        return accounts[int(raw) - 1]
    except (ValueError, IndexError):
        raise SystemExit("Invalid account selection.")


def configure_folders(requested_account=None):
    platform = get_platform()
    config = configparser.ConfigParser()
    if platform.paths.config_file.exists():
        config.read(platform.paths.config_file, encoding="utf-8")
    accounts = configured_emails(config)
    if not accounts:
        raise SystemExit("No accounts configured. Run mailflag --add-account first.")
    account = _choose_account(accounts, requested_account)
    # Imported here to avoid a module cycle: SettingsService reuses the
    # selectable-folder filter from this module.
    from .settings_service import SettingsService
    service = SettingsService(platform=platform)
    details = service.account_details(account)
    print(f"Discovering IMAP folders for {details.display_name}...")
    available = [
        folder for folder in service.discover_folders(account)
        if folder.casefold() != "inbox"
    ]

    current = configured_folders(config, account, "INBOX")
    current_folded = {folder.casefold() for folder in current}
    print("INBOX is always monitored.")
    if not available:
        print("No additional selectable folders were found.")
        return current
    for index, folder in enumerate(available, 1):
        marker = "x" if folder.casefold() in current_folded else " "
        print(f"  {index:>2}. [{marker}] {folder}")
    print("Enter folder numbers separated by commas; enter 0 for INBOX only.")
    raw = input("Monitored folders: ").strip()
    if not raw:
        print("No changes made.")
        return current
    selected = []
    if raw != "0":
        try:
            indexes = {int(value.strip()) for value in raw.split(",") if value.strip()}
            selected = [available[index - 1] for index in sorted(indexes)]
        except (ValueError, IndexError):
            raise SystemExit("Invalid folder selection.")
    result = set_configured_folders(config, account, selected, "INBOX")
    platform.paths.config_dir.mkdir(parents=True, exist_ok=True)
    with platform.paths.config_file.open("w", encoding="utf-8") as stream:
        config.write(stream)
    os.chmod(platform.paths.config_file, 0o600)
    print("Monitored folders saved:")
    for folder in result:
        print(f"  - {folder}")
    print("Restart MailFlag to apply the updated folder list.")
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    requested = argv[0] if argv else None
    configure_folders(requested)


if __name__ == "__main__":
    main()
