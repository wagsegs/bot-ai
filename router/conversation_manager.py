"""Track conversation ownership: channel → active user."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ChannelConversation:
    user_id: str
    started_at: datetime = field(default_factory=datetime.utcnow)


class ConversationManager:
    def __init__(self) -> None:
        self._active: dict[str, ChannelConversation] = {}

    def claim(self, channel_id: str, user_id: str) -> None:
        self._active[channel_id] = ChannelConversation(user_id=user_id)

    def get_owner(self, channel_id: str) -> str | None:
        conv = self._active.get(channel_id)
        return conv.user_id if conv else None

    def should_respond(
        self,
        channel_id: str,
        author_id: str,
        *,
        directed_at_bot: bool,
    ) -> bool:
        """Continue replying to owner unless interruption is clearly directed at bot."""
        owner = self.get_owner(channel_id)
        if owner is None:
            return directed_at_bot
        if directed_at_bot:
            self.claim(channel_id, author_id)
            return True
        if author_id == owner:
            return True
        return False

    def clear(self) -> None:
        self._active.clear()

    def count(self) -> int:
        return len(self._active)
