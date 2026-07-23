"""Conversation memory with local storage and summarization for Groq."""

import re
from typing import Optional

from utils.database import (
    get_recent_channel_context,
    get_recent_context,
    save_message,
    clear_all_conversations,
)

SUMMARIZE_THRESHOLD = 60
CONTEXT_LIMIT_FOR_AI = 8


class ConversationMemory:
    def save(self, user_id: str, channel_id: str, role: str, content: str) -> None:
        save_message(user_id, channel_id, role, content)

    def get_user_context(self, user_id: str, channel_id: str, limit: int = CONTEXT_LIMIT_FOR_AI) -> list[dict]:
        return get_recent_context(user_id, channel_id, limit=limit)

    def get_channel_messages(self, channel_id: str, limit: int = SUMMARIZE_THRESHOLD) -> list[dict]:
        return get_recent_channel_context(channel_id, limit=limit)

    def build_ai_context(self, user_id: str, channel_id: str) -> list[dict]:
        """Load local messages; summarize if over threshold before sending to Groq."""
        channel_msgs = self.get_channel_messages(channel_id, limit=SUMMARIZE_THRESHOLD)
        user_msgs = [m for m in channel_msgs if m.get("user_id") == user_id]

        if len(user_msgs) >= SUMMARIZE_THRESHOLD:
            summary = self._summarize(user_msgs[:-CONTEXT_LIMIT_FOR_AI])
            recent = user_msgs[-CONTEXT_LIMIT_FOR_AI:]
            context = [{"role": "system", "content": f"Earlier conversation summary: {summary}"}]
            for msg in recent:
                role = msg.get("role", "user")
                context.append({"role": role, "content": msg.get("content", "")})
            return context

        return self.get_user_context(user_id, channel_id)

    def _summarize(self, messages: list[dict]) -> str:
        if not messages:
            return "No prior context."
        topics: dict[str, int] = {}
        for msg in messages:
            for word in re.findall(r"[a-z]{4,}", (msg.get("content") or "").lower()):
                if word not in {"that", "this", "with", "have", "just", "like", "what", "when"}:
                    topics[word] = topics.get(word, 0) + 1
        top = sorted(topics, key=topics.get, reverse=True)[:3]
        topic_str = ", ".join(top) if top else "general chat"
        return f"~{len(messages)} messages about {topic_str}."

    def clear_all(self) -> None:
        clear_all_conversations()
