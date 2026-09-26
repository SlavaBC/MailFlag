"""Safe mail-opening preferences and Yahoo Webmail search helpers."""

import configparser
import os
import threading
from .platform import get_platform
from .providers import YAHOO

PLATFORM = get_platform()
CONFIG_FILE = PLATFORM.paths.config_file
SYSTEM_DEFAULT = "system_default"
YAHOO_WEBMAIL = "yahoo_webmail"
YAHOO_MAIL_URL = YAHOO.webmail_url
_lock = threading.RLock()


def get_open_mode():
    config = configparser.ConfigParser(interpolation=None)
    if CONFIG_FILE.exists():
        config.read(CONFIG_FILE, encoding="utf-8")
    value = config.get("opening", "mail_with", fallback=SYSTEM_DEFAULT).strip()
    return value if value in {SYSTEM_DEFAULT, YAHOO_WEBMAIL} else SYSTEM_DEFAULT


def set_open_mode(value):
    if value not in {SYSTEM_DEFAULT, YAHOO_WEBMAIL}:
        raise ValueError("Unknown mail-opening mode")
    with _lock:
        config = configparser.ConfigParser(interpolation=None)
        if CONFIG_FILE.exists():
            config.read(CONFIG_FILE, encoding="utf-8")
        if not config.has_section("opening"):
            config.add_section("opening")
        config.set("opening", "mail_with", value)
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = CONFIG_FILE.with_suffix(".opening.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            config.write(stream)
        os.chmod(temporary, 0o600)
        os.replace(temporary, CONFIG_FILE)
        os.chmod(CONFIG_FILE, 0o600)
    return value


def launch_system_default():
    if PLATFORM.open_default_mail_client():
        print("Opened the system-default mail client.")
        return True
    return launch_yahoo_webmail()


def launch_yahoo_webmail():
    if PLATFORM.open_url(YAHOO_MAIL_URL):
        print("Opened Yahoo Mail in the default browser.")
        return True
    print("Yahoo Webmail launch failed.")
    return False


def launch_selected_mode():
    if get_open_mode() == YAHOO_WEBMAIL:
        return launch_yahoo_webmail()
    return launch_system_default()
