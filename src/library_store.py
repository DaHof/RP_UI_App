from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from data_model import CardProfile


class LibraryStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._profiles: Dict[str, CardProfile] = {}

    def load(self) -> None:
        if not self._path.exists():
            self._profiles = {}
            return
        data = json.loads(self._path.read_text())
        self._profiles = {
            item["id"]: CardProfile.from_dict(item)
            for item in data.get("profiles", [])
        }

    def save(self) -> None:
        payload = {
            "profiles": [profile.to_dict() for profile in self._profiles.values()],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    def list_profiles(self) -> List[CardProfile]:
        return sorted(
            self._profiles.values(),
            key=lambda profile: profile.timestamps.last_seen_at,
            reverse=True,
        )

    def get_by_uid(self, uid: str) -> Optional[CardProfile]:
        for profile in self._profiles.values():
            if profile.uid == uid:
                return profile
        return None

    def upsert(self, profile: CardProfile) -> None:
        self._profiles[profile.id] = profile
        self.save()

    def delete(self, profile_id: str) -> None:
        if profile_id in self._profiles:
            del self._profiles[profile_id]
            self.save()
