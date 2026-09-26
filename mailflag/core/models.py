from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass(frozen=True)
class AccountProfile:
    email: str
    provider_id: str
    folders: Tuple[str, ...] = ("INBOX",)


@dataclass(frozen=True)
class MessageIdentity:
    account: str
    folder: str
    uidvalidity: int
    uid: int
    message_id: str = ""


@dataclass
class AccountState:
    uidvalidity: int
    last_processed_uid: int
    pending_uids: list[int] = field(default_factory=list)
    message_refs: Dict[str, dict] = field(default_factory=dict)

