"""Clip episode summary generation for #bombo-times."""

import random
import re
from datetime import datetime, timezone
from typing import Optional

CLIP_SUMMARY_CHANNEL_ID = 1526652930604662955


class ClipGenerator:
    _episode_counter = 0

    def __init__(self) -> None:
        self._last_clip_time: dict[int, datetime] = {}

    @classmethod
    def next_episode_number(cls) -> int:
        cls._episode_counter += 1
        return cls._episode_counter

    def build_summary(self, messages: list[dict], *, user_names: dict[str, str] | None = None) -> str:
        if not messages:
            return "Episode recap: the channel was quiet. Suspiciously quiet."

        user_messages = [
            msg for msg in messages
            if msg.get("content") and (msg.get("role") == "user" or msg.get("user_id"))
        ]
        user_ids = [msg.get("user_id") for msg in user_messages if msg.get("user_id")]
        unique_users = len(set(user_ids))
        total = len(user_messages)

        word_counts: dict[str, int] = {}
        for msg in user_messages:
            content = msg.get("content", "")
            if len(content) < 10:
                continue
            for word in re.findall(r"[a-z]{3,}", content.lower()):
                if word in {"the", "and", "for", "you", "that", "this", "with", "have", "from", "just", "like"}:
                    continue
                word_counts[word] = word_counts.get(word, 0) + 1
        highlight = max(word_counts, key=word_counts.get) if word_counts else "chaos"

        author_counts: dict[str, int] = {}
        for msg in user_messages:
            uid = msg.get("user_id")
            if uid:
                author_counts[uid] = author_counts.get(uid, 0) + 1

        mentions = []
        if author_counts and user_names:
            top_users = sorted(author_counts, key=author_counts.get, reverse=True)[:3]
            for uid in top_users:
                name = user_names.get(uid, f"<@{uid}>")
                mentions.append(name)

        episode = self.next_episode_number()
        mention_line = " ".join(mentions) if mentions else ""
        lines = [
            f"**Episode #{episode}**",
            f"{total} messages, {unique_users} people were involved.",
            f"Most of it was about **{highlight}**.",
            random.choice([
                "Nobody learned anything.",
                "Peak server moment tbh.",
                "Certified bombo times material.",
                "The plot twists were unnecessary.",
            ]),
        ]
        if mention_line:
            lines.insert(1, mention_line)
        return "\n".join(lines)

    async def fetch_channel_messages(self, channel, *, limit: int = 30) -> list[dict]:
        messages: list[dict] = []
        async for message in channel.history(limit=limit, oldest_first=False):
            author = getattr(message, "author", None)
            if not author or getattr(author, "bot", False):
                continue
            content = getattr(message, "content", "") or ""
            if not content.strip():
                continue
            messages.append({
                "content": content,
                "user_id": str(getattr(author, "id", "unknown")),
                "username": getattr(author, "display_name", getattr(author, "name", "unknown")),
                "role": "user",
            })
        return list(reversed(messages))
