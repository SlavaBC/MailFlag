"""Portable reconnect policy; no UI or desktop dependencies."""
SHORT_RECONNECT_LIVE_SECONDS = 90
SUSPEND_GAP_SECONDS = 5.0


def reconnect_is_live(elapsed_seconds, was_suspended=False):
    return not was_suspended and 0 <= elapsed_seconds <= SHORT_RECONNECT_LIVE_SECONDS
