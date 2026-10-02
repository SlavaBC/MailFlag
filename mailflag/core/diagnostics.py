"""Small thread-safe JSONL diagnostics log for MailFlag latency experiments."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time


MAX_LOG_BYTES = 2 * 1024 * 1024


class DiagnosticLog:
    def __init__(self, path, max_bytes=MAX_LOG_BYTES, clock=time.time):
        self.path = Path(path)
        self.max_bytes = int(max_bytes)
        self.clock = clock
        self._lock = threading.RLock()

    def write(self, event, account="", **fields):
        timestamp = self.clock()
        record = {
            "time": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
            "epoch": round(timestamp, 3),
            "event": str(event),
        }
        if account:
            record["account"] = str(account)
        for key, value in fields.items():
            if value is not None:
                record[str(key)] = value
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed(len(line.encode("utf-8")))
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line)
        return record

    def _rotate_if_needed(self, incoming_bytes):
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return
        if size + incoming_bytes <= self.max_bytes:
            return
        previous = self.path.with_suffix(self.path.suffix + ".1")
        try:
            previous.unlink()
        except FileNotFoundError:
            pass
        self.path.replace(previous)


def read_events(path, limit=100):
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    result = []
    for line in lines[-max(0, int(limit)):]:
        try:
            result.append(json.loads(line))
        except (TypeError, ValueError):
            continue
    return result


def latest_delivery_summary(events):
    parsed_index = next(
        (index for index in range(len(events) - 1, -1, -1)
         if events[index].get("event") == "message_parsed"),
        None,
    )
    if parsed_index is None:
        return "Latest delivery: no message has been recorded yet."
    parsed = events[parsed_index]
    account = parsed.get("account")
    uid = parsed.get("uid")
    status = next(
        (item for item in reversed(events[:parsed_index])
         if item.get("event") in {"status_ok", "folder_refresh"}
         and item.get("account") == account
         and item.get("uidnext_changed")),
        None,
    )
    ui = next(
        (item for item in events[parsed_index + 1:]
         if item.get("event") == "ui_dispatch"
         and item.get("account") == account and item.get("uid") == uid),
        None,
    )
    parts = [f"Latest delivery: account={account} uid={uid} kind={parsed.get('kind')}"]
    if parsed.get("header_age_seconds") is not None:
        parts.append(f"header-to-parse={parsed['header_age_seconds']}s")
    if status is not None:
        parts.append(f"imap-to-parse={round(parsed['epoch'] - status['epoch'], 3)}s")
    if ui is not None:
        parts.append(f"parse-to-ui={round(ui['epoch'] - parsed['epoch'], 3)}s")
    return " ".join(parts)


def format_report(path, limit=200):
    events = read_events(path, limit)
    lines = [
        f"MailFlag diagnostics: {Path(path)}",
        f"Events shown: {len(events)}",
        latest_delivery_summary(events),
    ]
    for item in events:
        details = " ".join(
            f"{key}={value}"
            for key, value in item.items()
            if key not in {"time", "epoch", "event", "account"}
        )
        account = f" [{item['account']}]" if item.get("account") else ""
        lines.append(
            f"{item.get('time', '?')} {item.get('event', '?')}{account}"
            + (f" {details}" if details else "")
        )
    return "\n".join(lines)
