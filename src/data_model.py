from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from typing import Any, Dict, List, Optional


@dataclasses.dataclass
class TagDump:
    present: bool = False
    complete: bool = False
    coverage: Optional[Dict[str, Any]] = None
    raw_bytes: Optional[str] = None
    auth_info: Optional[Dict[str, Any]] = None


@dataclasses.dataclass
class TagNdef:
    present: bool = False
    records: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    raw_bytes: Optional[str] = None


@dataclasses.dataclass
class TagCapabilities:
    can_read: bool = True
    can_write_ndef: bool = False
    can_dump_memory: bool = False
    can_write_raw: bool = False
    can_emulate_ndef: bool = False
    can_emulate_raw: bool = False
    auto_clone_choice: Optional[str] = None
    auto_clone_reason: Optional[str] = None


@dataclasses.dataclass
class TagTimestamps:
    created_at: str
    last_seen_at: str
    last_emulated_at: Optional[str] = None
    last_cloned_at: Optional[str] = None


@dataclasses.dataclass
class CardProfile:
    id: str
    friendly_name: str
    category: Optional[str]
    notes: Optional[str]
    uid: str
    uid_short: str
    tag_type: str
    tech_details: Dict[str, Any]
    ndef: TagNdef
    dump: TagDump
    capabilities: TagCapabilities
    timestamps: TagTimestamps

    @staticmethod
    def new_from_scan(uid: str, tag_type: str, tech_details: Optional[Dict[str, Any]] = None) -> "CardProfile":
        uid_upper = uid.upper()
        now = dt.datetime.utcnow().isoformat()
        uid_short = uid_upper[-8:] if len(uid_upper) > 8 else uid_upper
        return CardProfile(
            id=str(uuid.uuid4()),
            friendly_name=f"{tag_type} {uid_short}",
            category=None,
            notes=None,
            uid=uid_upper,
            uid_short=uid_short,
            tag_type=tag_type,
            tech_details=tech_details or {},
            ndef=TagNdef(),
            dump=TagDump(),
            capabilities=TagCapabilities(),
            timestamps=TagTimestamps(created_at=now, last_seen_at=now),
        )

    def touch_seen(self) -> None:
        self.timestamps.last_seen_at = dt.datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "CardProfile":
        return CardProfile(
            id=data["id"],
            friendly_name=data["friendly_name"],
            category=data.get("category"),
            notes=data.get("notes"),
            uid=data["uid"],
            uid_short=data["uid_short"],
            tag_type=data["tag_type"],
            tech_details=data.get("tech_details", {}),
            ndef=TagNdef(**data.get("ndef", {})),
            dump=TagDump(**data.get("dump", {})),
            capabilities=TagCapabilities(**data.get("capabilities", {})),
            timestamps=TagTimestamps(**data["timestamps"]),
        )
