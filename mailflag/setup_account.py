#!/usr/bin/env python3

import configparser
import getpass
import os
from .platform import get_platform
from .core.accounts import configured_emails

PLATFORM = get_platform()
CONFIG_DIR = PLATFORM.paths.config_dir
CONFIG_FILE = PLATFORM.paths.config_file


def load_accounts(config):
    return configured_emails(config)


config = configparser.ConfigParser()
if CONFIG_FILE.exists():
    config.read(CONFIG_FILE, encoding="utf-8")

accounts = load_accounts(config)

print("MailFlag — add Yahoo account")
print()
if accounts:
    print("Already configured:")
    for i, account in enumerate(accounts, 1):
        print(f"  {i}. {account}")
    print()

email = input("Second Yahoo email: ").strip()
if not email:
    raise SystemExit("No email entered.")

if email in accounts:
    print("This account is already configured.")
    raise SystemExit(0)

password = getpass.getpass("Yahoo App Password for this account: ").strip()
if not password:
    raise SystemExit("No App Password entered.")

try:
    PLATFORM.credentials.set(email, password + "\n")
except Exception as exc:
    password = None
    raise SystemExit(f"Could not save the App Password securely: {exc}")

# Drop the Python copy as soon as practical.
password = None

accounts.append(email)

if not config.has_section("accounts"):
    config.add_section("accounts")

config.set("accounts", "emails", "\n".join(accounts))

# Keep the old [account] section for backward compatibility.
if not config.has_section("account"):
    config.add_section("account")
if not config.get("account", "email", fallback="").strip():
    config.set("account", "email", accounts[0])

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
with CONFIG_FILE.open("w", encoding="utf-8") as f:
    config.write(f)
os.chmod(CONFIG_FILE, 0o600)

print()
print("Second Yahoo account added locally.")
print("Configured MailFlag accounts:")
for i, account in enumerate(accounts, 1):
    print(f"  {i}. {account}")
