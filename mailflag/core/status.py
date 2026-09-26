"""Thread-safe aggregate connection health for all configured accounts."""

import threading
import time


def stale_connected_accounts(snapshot, now, max_age):
    return [
        email
        for email, value in snapshot.items()
        if value["state"] == "connected"
        and value.get("last_connected_at") is not None
        and now - value["last_connected_at"] > max_age
    ]


class ConnectionStatus:
    def __init__(self, accounts, changed=None, clock=time.monotonic):
        self._lock = threading.RLock()
        self._clock = clock
        self._changed = changed
        now = clock()
        self._accounts = {
            email: {
                "state": "connecting",
                "detail": "Starting",
                "changed_at": now,
                "last_connected_at": None,
            }
            for email in accounts
        }

    def update(self, email, state, detail=""):
        if state not in {"connecting", "connected", "error"}:
            raise ValueError(f"Unknown connection state: {state}")
        with self._lock:
            old = self._accounts[email]
            now = self._clock()
            if old["state"] != state or old["detail"] != detail:
                old["changed_at"] = now
            old["state"] = state
            old["detail"] = detail
            if state == "connected":
                old["last_connected_at"] = now
        if self._changed:
            self._changed()

    def snapshot(self):
        with self._lock:
            return {email: dict(value) for email, value in self._accounts.items()}

    def aggregate(self):
        values = list(self.snapshot().values())
        connected = sum(item["state"] == "connected" for item in values)
        errors = sum(item["state"] == "error" for item in values)
        total = len(values)
        if connected == total and total:
            return "online"
        if connected:
            return "partial"
        if errors == total and total:
            return "offline"
        return "connecting"
