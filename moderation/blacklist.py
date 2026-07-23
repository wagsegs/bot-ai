"""Blacklist management."""

import json
from pathlib import Path

BLACKLIST_FILE = Path("blacklist.json")


class Blacklist:
    def __init__(self) -> None:
        self._users: set[str] = set()
        self._load()

    def _load(self) -> None:
        try:
            if BLACKLIST_FILE.exists():
                data = json.loads(BLACKLIST_FILE.read_text(encoding="utf-8"))
                self._users = set(str(u) for u in data.get("users", []))
        except Exception:
            self._users = set()

    def _save(self) -> None:
        BLACKLIST_FILE.write_text(
            json.dumps({"users": sorted(self._users)}, indent=2),
            encoding="utf-8",
        )

    def is_blacklisted(self, user_id: str | int) -> bool:
        return str(user_id) in self._users

    def add(self, user_id: str | int) -> None:
        self._users.add(str(user_id))
        self._save()

    def remove(self, user_id: str | int) -> None:
        self._users.discard(str(user_id))
        self._save()

    def list_users(self) -> list[str]:
        return sorted(self._users)

    def clear(self) -> None:
        self._users = set()
        self._save()
