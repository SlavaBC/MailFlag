"""Portable JSON state codec with per-account, per-folder checkpoints."""

import json
import os
from pathlib import Path


STATE_VERSION = 3
DEFAULT_FOLDER = "INBOX"


def normalize_reference(reference):
    return {
        "message_id": str(reference.get("message_id", ""))[:998],
        "sender": str(reference.get("sender", ""))[:1000],
        "subject": str(reference.get("subject", ""))[:1000],
        "date": str(reference.get("date", ""))[:80],
    }


def normalize_folder(value):
    references = {}
    for uid, reference in value.get("message_refs", {}).items():
        try:
            references[str(int(uid))] = normalize_reference(reference)
        except Exception:
            pass
    return {
        "uidvalidity": int(value["uidvalidity"]),
        "last_processed_uid": int(value["last_processed_uid"]),
        "pending_uids": sorted(set(int(x) for x in value.get("pending_uids", []))),
        "message_refs": references,
    }


def normalize_account(value):
    # v2 stored one INBOX state directly under the account. Migrate it without
    # replaying mail or discarding pending items.
    source_folders = value.get("folders")
    if not isinstance(source_folders, dict):
        source_folders = {DEFAULT_FOLDER: value}
    folders = {}
    for folder, folder_state in source_folders.items():
        try:
            folders[str(folder)] = normalize_folder(folder_state)
        except Exception:
            pass
    recent = []
    for message_id in value.get("recent_message_ids", []):
        message_id = str(message_id).strip()[:998]
        if message_id and message_id not in recent:
            recent.append(message_id)
    return {"folders": folders, "recent_message_ids": recent[-500:]}


def read_store(path: Path):
    if not path.exists():
        return {"version": STATE_VERSION, "accounts": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("accounts"), dict):
            accounts = {}
            for email, value in data["accounts"].items():
                try:
                    accounts[email] = normalize_account(value)
                except Exception:
                    pass
            return {"version": STATE_VERSION, "accounts": accounts}
        if isinstance(data, dict) and {"uidvalidity", "last_processed_uid"} <= data.keys():
            return {
                "version": STATE_VERSION,
                "accounts": {"__legacy__": normalize_account(data)},
            }
    except Exception as exc:
        print("WARNING: state file could not be read:", type(exc).__name__, exc)
    return {"version": STATE_VERSION, "accounts": {}}


def write_store(path: Path, store):
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {
        "version": STATE_VERSION,
        "accounts": {
            email: normalize_account(value)
            for email, value in store.get("accounts", {}).items()
        },
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)
