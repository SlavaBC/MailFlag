"""Portable JSON state codec for accounts, UIDs, pending and Message-ID."""

import json
import os
from pathlib import Path


def normalize_account(value):
    references = {}
    for uid, reference in value.get("message_refs", {}).items():
        try:
            references[str(int(uid))] = {
                "message_id": str(reference.get("message_id", ""))[:998],
                "sender": str(reference.get("sender", ""))[:1000],
                "subject": str(reference.get("subject", ""))[:1000],
                "date": str(reference.get("date", ""))[:80],
            }
        except Exception:
            pass
    return {
        "uidvalidity": int(value["uidvalidity"]),
        "last_processed_uid": int(value["last_processed_uid"]),
        "pending_uids": sorted(set(int(x) for x in value.get("pending_uids", []))),
        "message_refs": references,
    }


def read_store(path: Path):
    if not path.exists():
        return {"version": 2, "accounts": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("accounts"), dict):
            accounts = {}
            for email, value in data["accounts"].items():
                try: accounts[email] = normalize_account(value)
                except Exception: pass
            return {"version": 2, "accounts": accounts}
        if isinstance(data, dict) and {"uidvalidity", "last_processed_uid"} <= data.keys():
            return {"version": 2, "accounts": {"__legacy__": normalize_account(data)}}
    except Exception as exc:
        print("WARNING: state file could not be read:", type(exc).__name__, exc)
    return {"version": 2, "accounts": {}}


def write_store(path: Path, store):
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {"version": 2, "accounts": {
        email: normalize_account(value)
        for email, value in store.get("accounts", {}).items()
    }}
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)

