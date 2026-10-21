"""Linux implementation preserving MailFlag's existing desktop behavior."""

import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

from .base import AppPaths, AutostartService, CredentialStore, PlatformServices


class SecretServiceCredentials(CredentialStore):
    def get(self, account):
        result = subprocess.run(
            ["secret-tool", "lookup", "service", "mailflag", "account", account],
            capture_output=True, text=True,
        )
        if result.returncode not in (0, 1) or (result.returncode and result.stderr.strip()):
            raise RuntimeError(result.stderr.strip() or "Secret Service lookup failed")
        return result.stdout.strip()

    def set(self, account, secret):
        subprocess.run(
            ["secret-tool", "store", "--label=MailFlag account password",
             "service", "mailflag", "account", account],
            input=secret, text=True, check=True,
        )

    def delete(self, account):
        result = subprocess.run(
            ["secret-tool", "clear", "service", "mailflag", "account", account],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Secret Service deletion failed")


class DesktopAutostart(AutostartService):
    def __init__(self, path): self.path = path
    def enable(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            "[Desktop Entry]\nType=Application\nName=MailFlag\n"
            "Exec=/usr/bin/mailflag --startup\nIcon=mailflag\n"
            "Terminal=false\nX-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
    def disable(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            "[Desktop Entry]\nType=Application\nName=MailFlag\nHidden=true\n",
            encoding="utf-8",
        )
    def is_enabled(self):
        if self.path.is_file():
            return "Hidden=true" not in self.path.read_text(encoding="utf-8")
        return Path("/etc/xdg/autostart/mailflag.desktop").is_file()


class LinuxPlatform(PlatformServices):
    def __init__(self):
        home = Path.home()
        config = home / ".config/mailflag"
        self.paths = AppPaths(config, config, home / ".cache/mailflag",
                              Path(__file__).resolve().parent.parent)
        self.credentials = SecretServiceCredentials()
        self.autostart = DesktopAutostart(home / ".config/autostart/mailflag.desktop")

    def power_clock_snapshot(self):
        mono = time.monotonic()
        total = (time.clock_gettime(time.CLOCK_BOOTTIME)
                 if hasattr(time, "CLOCK_BOOTTIME") else time.time())
        return total, mono

    def suspend_gap_since(self, snapshot):
        before_total, before_mono = snapshot
        total = (time.clock_gettime(time.CLOCK_BOOTTIME)
                 if hasattr(time, "CLOCK_BOOTTIME") else time.time())
        return max(0.0, (total - before_total) - (time.monotonic() - before_mono))

    def copy_text(self, text, primary=False):
        # Lazy GTK import keeps Core and headless tests GTK-free.
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, Gtk
        selection = Gdk.SELECTION_PRIMARY if primary else Gdk.SELECTION_CLIPBOARD
        clipboard = Gtk.Clipboard.get(selection)
        clipboard.set_text(text, -1)
        clipboard.store()

    def play_audio(self, path):
        for name in ("paplay", "pw-play", "aplay"):
            executable = shutil.which(name)
            if executable:
                try:
                    child = subprocess.Popen(
                        [executable, str(path)], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    threading.Thread(target=child.wait, daemon=True).start()
                    return True
                except OSError: pass
        return False

    def open_url(self, url):
        try:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        except OSError: return False

    def open_default_mail_client(self):
        try:
            result = subprocess.run(
                ["xdg-mime", "query", "default", "x-scheme-handler/mailto"],
                capture_output=True, text=True, timeout=5,
            )
            desktop_id = result.stdout.strip()
            for candidate in ([desktop_id, desktop_id[:-8]]
                              if desktop_id.endswith(".desktop") else [desktop_id]):
                if candidate and subprocess.run(
                    ["gtk-launch", candidate], stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=5,
                ).returncode == 0:
                    return True
        except Exception: pass
        return False

    def notify(self, title, body):
        try:
            subprocess.Popen(["notify-send", title, body], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        except OSError: return False
