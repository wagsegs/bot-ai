"""Per-user memory: favorite emojis, nickname, speech style."""

import json
import re
from pathlib import Path
from typing import Optional

USER_MEMORY_FILE = Path("user_memory.json")

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)


class UserMemory:
    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            if USER_MEMORY_FILE.exists():
                self._data = json.loads(USER_MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            self._data = {}

    def _save(self) -> None:
        try:
            USER_MEMORY_FILE.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _key(self, user_id: str, guild_id: str) -> str:
        return f"{guild_id}:{user_id}"

    def observe_message(self, user_id: str, guild_id: str, content: str, *, nickname: str = "") -> None:
        key = self._key(user_id, guild_id)
        entry = self._data.setdefault(key, {
            "favorite_emojis": {},
            "nickname": nickname,
            "speech_samples": [],
        })
        if nickname:
            entry["nickname"] = nickname
        emojis = EMOJI_PATTERN.findall(content)
        for emoji in emojis:
            entry["favorite_emojis"][emoji] = entry["favorite_emojis"].get(emoji, 0) + 1
        if content.strip() and len(content) < 200:
            samples: list = entry["speech_samples"]
            samples.append(content.strip())
            entry["speech_samples"] = samples[-5:]
        self._save()

    def get_emoji_hint(self, user_id: str, guild_id: str) -> str:
        key = self._key(user_id, guild_id)
        entry = self._data.get(key, {})
        emojis: dict = entry.get("favorite_emojis", {})
        if not emojis:
            return ""
        top = sorted(emojis, key=emojis.get, reverse=True)[:3]
        return " ".join(top)

    def get_context_hint(self, user_id: str, guild_id: str) -> Optional[str]:
        key = self._key(user_id, guild_id)
        entry = self._data.get(key)
        if not entry:
            return None
        parts = []
        if entry.get("nickname"):
            parts.append(f"Nickname: {entry['nickname']}")
        emoji_hint = self.get_emoji_hint(user_id, guild_id)
        if emoji_hint:
            parts.append(f"Often uses: {emoji_hint}")
        samples = entry.get("speech_samples", [])
        if samples:
            parts.append(f"Talks like: {samples[-1][:80]}")
        return "\n".join(parts) if parts else None

    def clear(self) -> None:
        self._data = {}
        self._save()
