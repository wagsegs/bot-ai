"""Track conversation ownership: channel → active user."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC

logger = logging.getLogger("botkun.conversation")


@dataclass
class ChannelConversation:
    user_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_activity: datetime = field(default_factory=lambda: datetime.now(UTC))
    continuation_used: bool = False


class ConversationManager:
    CONVERSATION_TIMEOUT_MINUTES = 10

    def __init__(self) -> None:
        self._active: dict[str, ChannelConversation] = {}

    def _is_expired(self, conv: ChannelConversation) -> bool:
        """Check if conversation has expired due to inactivity."""
        timeout = timedelta(minutes=self.CONVERSATION_TIMEOUT_MINUTES)
        return datetime.now(UTC) - conv.last_activity > timeout

    def claim(self, channel_id: str, user_id: str, *, explicit_mention: bool = False) -> None:
        """Claim or update conversation ownership with current timestamp."""
        existing = self._active.get(channel_id)
        if existing:
            existing.user_id = user_id
            existing.last_activity = datetime.now(UTC)
            if explicit_mention:
                existing.continuation_used = False
                logger.info("[conversation] Restarted via explicit mention: channel=%s user=%s", channel_id, user_id)
            else:
                logger.info("[conversation] Continued: channel=%s user=%s", channel_id, user_id)
        else:
            self._active[channel_id] = ChannelConversation(user_id=user_id)
            logger.info("[conversation] Started: channel=%s user=%s", channel_id, user_id)

    def interrupt_if_needed(self, channel_id: str, author_id: str) -> None:
        """Interrupt active conversation if a third party posts in the channel."""
        owner = self.get_owner(channel_id)
        if owner is None:
            return
        if author_id != owner:
            logger.info("[conversation] Interrupted by user=%s (was owner=%s)", author_id, owner)
            del self._active[channel_id]

    def get_owner(self, channel_id: str) -> str | None:
        conv = self._active.get(channel_id)
        if conv and self._is_expired(conv):
            del self._active[channel_id]
            return None
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
            logger.info("[conversation] Resumed via explicit mention: user=%s", author_id)
            self.claim(channel_id, author_id, explicit_mention=True)
            return True
        if author_id == owner:
            conv = self._active.get(channel_id)
            if conv and conv.continuation_used:
                logger.info("[conversation] Ignoring continuation (already used): channel=%s user=%s", channel_id, author_id)
                return False
            # Update activity timestamp when owner continues conversation
            self.claim(channel_id, author_id)
            if conv:
                conv.continuation_used = True
                logger.info("[conversation] Automatic continuation used: channel=%s user=%s", channel_id, author_id)
            return True
        return False

    def clear(self) -> None:
        self._active.clear()

    def count(self) -> int:
        # Clean up expired conversations before counting
        expired = [cid for cid, conv in self._active.items() if self._is_expired(conv)]
        for cid in expired:
            del self._active[cid]
        return len(self._active)
