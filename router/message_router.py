"""Natural participation — every ~50 messages, context-aware."""

import asyncio
import random
from datetime import datetime, timedelta, timezone

from memory.conversation_memory import ConversationMemory
from utils.availability import is_bot_available
from utils.response_budget import can_respond, get_spontaneous_probability_multiplier

SERIOUS_KEYWORDS = {
    "rip", "condolences", "sorry", "prayers", "trauma", "hospital",
    "death", "passed away", "rest in peace", "incident", "emergency",
}

PARTICIPATION_INTERVAL = 50


class NaturalParticipation:
    def __init__(self, memory: ConversationMemory) -> None:
        self.memory = memory
        self._channel_counts: dict[str, int] = {}
        self._last_bot_spoke: dict[str, datetime] = {}
        self._last_participation: datetime | None = None
        self._enabled = True

    def mark_bot_spoke(self, channel_id: str) -> None:
        self._last_bot_spoke[channel_id] = datetime.utcnow()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def _is_serious(self, content: str) -> bool:
        lowered = content.lower()
        return any(kw in lowered for kw in SERIOUS_KEYWORDS)

    async def maybe_participate(self, message, ai_callback) -> bool:
        """Check every ~50 messages if bot should join naturally."""
        if not self._enabled:
            return False
        if self._is_serious(message.content or ""):
            return False
        if not is_bot_available() or not can_respond():
            return False

        channel_id = str(message.channel.id)
        self._channel_counts[channel_id] = self._channel_counts.get(channel_id, 0) + 1
        if self._channel_counts[channel_id] % PARTICIPATION_INTERVAL != 0:
            return False

        if channel_id in self._last_bot_spoke:
            if datetime.utcnow() - self._last_bot_spoke[channel_id] < timedelta(minutes=5):
                return False

        if self._last_participation:
            if datetime.utcnow() - self._last_participation < timedelta(minutes=3):
                return False

        recent = self.memory.get_channel_messages(channel_id, limit=24)
        user_ids = {m.get("user_id") for m in recent if m.get("user_id")}
        if len(recent) < 8 or len(user_ids) < 2:
            return False

        probability = 0.18 * get_spontaneous_probability_multiplier()
        if random.random() > probability:
            return False

        self._last_participation = datetime.utcnow()
        delay = random.randint(15, 60)

        async def delayed():
            await asyncio.sleep(delay)
            summary = self._summarize_channel(recent)
            prompt = (
                f"The channel has been chatting without you. Recent vibe: {summary}. "
                "Reply naturally in 1-2 short sentences. Sometimes stay silent — if nothing fits, respond with exactly [SKIP]."
            )
            await ai_callback(message, prompt, natural=True)

        asyncio.create_task(delayed())
        return True

    def _summarize_channel(self, messages: list[dict]) -> str:
        texts = [m.get("content", "")[:80] for m in messages[-8:] if m.get("content")]
        return " | ".join(texts) if texts else "general banter"
