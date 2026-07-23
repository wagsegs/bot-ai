"""Spam detection: 3 attempts → ignore 5 minutes."""

from collections import deque
from datetime import datetime, timedelta


class SpamFilter:
    IGNORE_DURATION = timedelta(minutes=5)
    MAX_ATTEMPTS = 3
    WINDOW_SECONDS = 12

    def __init__(self) -> None:
        self._history: dict[str, deque[datetime]] = {}
        self._ignored_until: dict[str, datetime] = {}

    def _prune(self, user_id: str) -> None:
        history = self._history.setdefault(user_id, deque(maxlen=20))
        cutoff = datetime.utcnow() - timedelta(seconds=self.WINDOW_SECONDS)
        while history and history[0] < cutoff:
            history.popleft()

    def is_ignored(self, user_id: str) -> bool:
        until = self._ignored_until.get(user_id)
        if until and datetime.utcnow() < until:
            return True
        if until:
            del self._ignored_until[user_id]
        return False

    def record_attempt(self, user_id: str) -> str:
        """Returns 'allow', 'warn', or 'ignore'."""
        if self.is_ignored(user_id):
            return "ignore"
        self._prune(user_id)
        history = self._history.setdefault(user_id, deque(maxlen=20))
        history.append(datetime.utcnow())
        count = len(history)
        if count >= self.MAX_ATTEMPTS + 2:
            self._ignored_until[user_id] = datetime.utcnow() + self.IGNORE_DURATION
            return "ignore"
        if count >= self.MAX_ATTEMPTS:
            return "warn"
        return "allow"
