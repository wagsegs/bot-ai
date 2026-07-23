from collections import deque
from datetime import datetime, timedelta


class RateLimiter:
    """Proactive rate limiting: target 4 requests / 10s, hard limit 5 / 10s."""

    WINDOW_SECONDS = 10
    TARGET_REQUESTS = 4
    MAX_REQUESTS = 5

    def __init__(self) -> None:
        self._request_times: deque[datetime] = deque()

    def _prune(self) -> None:
        cutoff = datetime.utcnow() - timedelta(seconds=self.WINDOW_SECONDS)
        while self._request_times and self._request_times[0] < cutoff:
            self._request_times.popleft()

    def record(self) -> None:
        self._prune()
        self._request_times.append(datetime.utcnow())

    def current_rate(self) -> int:
        self._prune()
        return len(self._request_times)

    def can_accept(self) -> bool:
        return self.current_rate() < self.MAX_REQUESTS

    def should_throttle(self) -> bool:
        return self.current_rate() >= self.TARGET_REQUESTS

    def wait_seconds(self) -> float:
        """Seconds to wait before next request when at target."""
        self._prune()
        if not self._request_times:
            return 0.0
        if len(self._request_times) < self.TARGET_REQUESTS:
            return 0.0
        oldest = self._request_times[0]
        elapsed = (datetime.utcnow() - oldest).total_seconds()
        return max(0.0, self.WINDOW_SECONDS - elapsed + 0.1)
