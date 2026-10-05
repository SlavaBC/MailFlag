"""RFC From-header formatting for user-visible sender metadata."""

from email.header import decode_header
from email.utils import getaddresses
import re


SPACE_RE = re.compile(r"\s+")


def _decode_header(value):
    pieces = []
    for payload, charset in decode_header(str(value or "")):
        if isinstance(payload, bytes):
            try:
                pieces.append(payload.decode(charset or "utf-8", "replace"))
            except LookupError:
                pieces.append(payload.decode("utf-8", "replace"))
        else:
            pieces.append(payload)
    return SPACE_RE.sub(" ", "".join(pieces)).strip()


def format_sender(raw_header="", fallback_email="", max_name_chars=160):
    """Return ``Display Name <email>`` while always preserving the address."""
    decoded = _decode_header(raw_header)
    addresses = getaddresses([decoded]) if decoded else ()
    name, email = addresses[0] if addresses else ("", "")
    name = _decode_header(name).strip(' "')
    email = SPACE_RE.sub("", email or fallback_email or "").strip()
    if max_name_chars and len(name) > max_name_chars:
        name = name[:max_name_chars - 1].rstrip() + "…"
    if name and email:
        return f"{name} <{email}>"
    return email or name or "(unknown sender)"


def format_message_sender(message, max_name_chars=160):
    """Format sender from an imap-tools message without trusting display name."""
    fallback = str(getattr(message, "from_", "") or "")
    raw = ""
    try:
        raw = message.obj["From"] or ""
    except (AttributeError, KeyError, TypeError):
        values = getattr(message, "from_values", None)
        if values is not None:
            raw = getattr(values, "full", "") or ""
    return format_sender(raw, fallback, max_name_chars)


__all__ = ["format_sender", "format_message_sender"]
