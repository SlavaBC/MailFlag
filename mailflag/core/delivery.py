"""Rules deciding whether recovered mail is live or pending-only."""

from enum import Enum


class DeliveryClass(str, Enum):
    LIVE = "live"
    PENDING = "pending"


def classify_delivery(*, startup=False, resumed=False, outage_seconds=0.0,
                      short_reconnect_seconds=90.0):
    if startup or resumed or outage_seconds > short_reconnect_seconds:
        return DeliveryClass.PENDING
    return DeliveryClass.LIVE


def uid_window(last_processed_uid, uidnext):
    """Return the inclusive new-UID range without any IMAP/UI dependency."""
    first = int(last_processed_uid) + 1
    last = max(0, int(uidnext) - 1)
    return range(first, last + 1) if last >= first else range(0)

