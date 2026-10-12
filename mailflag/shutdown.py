"""Graceful, headless shutdown used by users and Debian package removal."""

import os
import pwd
from pathlib import Path

from .ipc import send_command


def mailflag_processes(proc_root=Path("/proc")):
    """Return running ``python -m mailflag`` processes, excluding this command."""
    found = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == os.getpid():
            continue
        try:
            arguments = (entry / "cmdline").read_bytes().split(b"\0")
            arguments = [item.decode("utf-8", "replace") for item in arguments if item]
            module = next(
                index for index in range(len(arguments) - 1)
                if arguments[index:index + 2] == ["-m", "mailflag"]
            )
            if "--shutdown" in arguments[module + 2:]:
                continue
            uid = (entry / "status").read_text().split("Uid:\t", 1)[1].split()[0]
            found.append((pid, int(uid), arguments))
        except (FileNotFoundError, PermissionError, StopIteration, IndexError, ValueError):
            continue
    return found


def _home_for_uid(uid):
    try:
        return Path(pwd.getpwuid(uid).pw_dir)
    except KeyError:
        return None


def graceful_shutdown(proc_root=Path("/proc")):
    """Ask every running user's background and Settings processes to exit."""
    homes = {
        home for _pid, uid, _arguments in mailflag_processes(proc_root)
        if (home := _home_for_uid(uid)) is not None
    }
    requested = 0
    for home in homes:
        config = home / ".config" / "mailflag"
        for socket_name in ("control.sock", "settings-control.sock"):
            if send_command(config / socket_name, "stop"):
                requested += 1
    return requested


__all__ = ["graceful_shutdown", "mailflag_processes"]
