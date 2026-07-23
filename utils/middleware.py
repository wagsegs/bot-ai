"""Backward-compatible middleware wrapper for tests and legacy imports."""

import random
from collections import deque
from datetime import datetime, timedelta

from ai.action_planner import ActionPlanner


class AIRequestMiddleware:
    """Compat layer — delegates validation to ActionPlanner."""

    def __init__(self) -> None:
        self._planner = ActionPlanner()
        self._user_request_history: dict[str, deque[datetime]] = {}
        self._user_cooldowns: dict[str, datetime] = {}
        self._runtime_stats = {
            "successful_requests": 0,
            "failed_requests": 0,
            "retries": 0,
            "repaired_outputs": 0,
            "rate_limit_errors": 0,
            "average_response_ms": 0.0,
            "queue_size": 0,
        }

    def _validate_output_text(self, text: str | None, fallback: str | None = None) -> str:
        if not text or not isinstance(text, str):
            return fallback or "nah"
        raw = text.strip()
        if not raw:
            return fallback or "nah"
        
        # First, try to extract clean text before any metadata markers
        # If the text starts with normal content before [text]: or JSON, return that
        import re
        lines = raw.split("\n")
        clean_lines = []
        for line in lines:
            if "[text]:" in line or "[send_gif]:" in line or line.strip().startswith("{"):
                break
            if line.strip():
                clean_lines.append(line)
        
        if clean_lines:
            clean_text = "\n".join(clean_lines).strip()
            if clean_text and not self._planner.looks_like_leaked_format(clean_text):
                return clean_text
        
        # Handle XML tags (legacy test compatibility)
        if "<tag>" in raw and "</tag>" in raw:
            match = re.search(r"<tag>(.+)</tag>", raw)
            if match:
                extracted = match.group(1).strip()
                if extracted:
                    return extracted
        
        # Delegate to ActionPlanner for JSON handling
        return self._planner.validate_output_text(text, fallback)

    def _get_spam_state(self, user_id: str | None) -> tuple[str, float | None]:
        if not user_id:
            return "allow", None
        cooldown_until = self._user_cooldowns.get(user_id)
        if cooldown_until and datetime.utcnow() < cooldown_until:
            return "block", None
        history = self._user_request_history.setdefault(user_id, deque(maxlen=12))
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=12)
        while history and history[0] < cutoff:
            history.popleft()
        history.append(now)
        count = len(history)
        if count <= 5:
            return "allow", None
        if count <= 8:
            return "delay", random.uniform(0.6, 0.9)
        if count <= 12:
            return "delay", random.uniform(1.2, 1.8)
        self._user_cooldowns[user_id] = datetime.utcnow() + timedelta(seconds=8)
        return "block", None

    def get_stats(self) -> dict:
        return dict(self._runtime_stats)
