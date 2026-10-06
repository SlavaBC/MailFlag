"""Interactive safe local account removal."""

from .settings_service import SettingsService


def remove_account(requested=None, input_fn=input):
    service = SettingsService()
    accounts = service.accounts()
    if not accounts:
        raise SystemExit("No MailFlag accounts are configured.")
    if requested:
        if requested not in accounts:
            raise SystemExit(f"Unknown MailFlag account: {requested}")
        account = requested
    elif len(accounts) == 1:
        account = accounts[0]
    else:
        for index, value in enumerate(accounts, 1):
            print(f"  {index}. {value}")
        try:
            account = accounts[int(input_fn("Choose account number: ").strip()) - 1]
        except (ValueError, IndexError):
            raise SystemExit("Invalid account selection.")
    answer = input_fn(
        f"Remove {account} from MailFlag, including its local pending state "
        "and keyring credential? [y/N]: "
    ).strip().casefold()
    if answer not in {"y", "yes"}:
        print("Account removal cancelled.")
        return False
    service.remove_account(account)
    print(f"Removed {account} from MailFlag. Server mail was not changed.")
    return True
