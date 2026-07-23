"""NSFW / explicit request moderation — 3 strikes: funny → sarcastic → ignore."""

from datetime import datetime, timedelta


class NSFWModerator:
    STRIKE_RESET = timedelta(hours=24)

    EXPLICIT_PATTERNS = (
        "send nudes", "nsfw", "porn", "explicit pic", "lewd",
        "strip for", "sexual", "hentai",
    )

    REJECTIONS = {
        1: [
            "nah I'm good 😭",
            "my eyes have standards",
            "that's a no from me chief",
        ],
        2: [
            "bro asked twice 💀",
            "you really thought I'd say yes?",
            "the audacity is impressive ngl",
        ],
    }

    def __init__(self) -> None:
        self._strikes: dict[str, tuple[int, datetime]] = {}

    def _get_strikes(self, user_id: str) -> int:
        entry = self._strikes.get(user_id)
        if not entry:
            return 0
        count, last = entry
        if datetime.utcnow() - last > self.STRIKE_RESET:
            del self._strikes[user_id]
            return 0
        return count

    def check(self, user_id: str, content: str) -> tuple[str, str | None]:
        """
        Returns (action, reply).
        action: 'allow' | 'reject' | 'ignore'
        """
        lowered = content.lower()
        if not any(p in lowered for p in self.EXPLICIT_PATTERNS):
            return "allow", None

        strikes = self._get_strikes(user_id) + 1
        self._strikes[user_id] = (strikes, datetime.utcnow())

        if strikes >= 3:
            return "ignore", None
        import random
        replies = self.REJECTIONS.get(strikes, self.REJECTIONS[2])
        return "reject", random.choice(replies)
