"""Configurable Linux notification sound without desktop-specific APIs."""

import configparser
import os
import threading
import time
from pathlib import Path
from .platform import get_platform

PLATFORM = get_platform()
CONFIG_FILE = PLATFORM.paths.config_file
DEFAULT_SOUND = Path(__file__).with_name("notification.wav")
SUPPORTED_SUFFIXES = {".wav", ".wave", ".ogg", ".oga", ".flac"}
_last = 0.0
_lock = threading.RLock()


def get_sound_choice():
    config = configparser.ConfigParser(interpolation=None)
    if CONFIG_FILE.exists():
        config.read(CONFIG_FILE, encoding="utf-8")
    value = config.get("notifications", "sound", fallback="default").strip()
    return value or "default"


def set_sound_choice(value):
    value = str(value).strip() or "default"
    if value not in {"default", "silent"}:
        path = Path(value).expanduser()
        if not path.is_file() or path.suffix.casefold() not in SUPPORTED_SUFFIXES:
            raise ValueError("Choose an existing WAV, OGG, or FLAC audio file.")
        value = str(path.resolve())

    with _lock:
        config = configparser.ConfigParser(interpolation=None)
        if CONFIG_FILE.exists():
            config.read(CONFIG_FILE, encoding="utf-8")
        if not config.has_section("notifications"):
            config.add_section("notifications")
        config.set("notifications", "sound", value)
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = CONFIG_FILE.with_suffix(".ini.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            config.write(stream)
        os.chmod(temporary, 0o600)
        os.replace(temporary, CONFIG_FILE)
        os.chmod(CONFIG_FILE, 0o600)
    return value


def selected_sound_path():
    choice = get_sound_choice()
    if choice == "silent":
        return None
    if choice == "default":
        return DEFAULT_SOUND
    path = Path(choice)
    return path if path.is_file() else DEFAULT_SOUND


def play_notification(force=False):
    global _last
    sound = selected_sound_path()
    if sound is None:
        return False
    now = time.monotonic()
    with _lock:
        if not force and now - _last < 0.5:
            return False
        _last = now

    return PLATFORM.play_audio(sound)
