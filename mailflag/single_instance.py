"""Per-user process lock preventing duplicate MailFlag workers."""

import fcntl


def acquire_instance_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None
    return lock
