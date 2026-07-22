import random
import re
from datetime import datetime, timedelta
from typing import Callable, Optional


class TopicDetector:
    """Detect a dominant topic from recent chat messages."""

    TOPIC_KEYWORDS = {
        "jojo": ["jojo", "steel ball run", "jonny", "funny valentine", "araki"],
        "minecraft": ["minecraft", "creeper", "nether", "enderman"],
        "programming": ["python", "programming", "code", "debug", "bug", "javascript", "typescript"],
        "discord": ["discord", "server", "bot", "channel"],
        "football": ["football", "soccer", "goal", "fifa", "premier league"],
        "anime": ["anime", "naruto", "one piece", "dbz", "attack on titan"],
        "cats": ["cat", "cats", "kitten"],
    }

    def detect_topic(self, messages: list[dict]) -> Optional[str]:
        scores: dict[str, int] = {topic: 0 for topic in self.TOPIC_KEYWORDS}
        for msg in messages:
            content = str(msg.get("content", "") or "").lower()
            for topic, keywords in self.TOPIC_KEYWORDS.items():
                matches = sum(1 for keyword in keywords if keyword in content)
                if matches:
                    scores[topic] += matches
        if not any(scores.values()):
            return None
        best_topic, best_score = max(scores.items(), key=lambda item: (item[1], item[0]))
        return best_topic if best_score > 0 else None


class ConversationAnalyzer:
    """Build a lightweight summary of the recent conversation."""

    def analyze(self, messages: list[dict]) -> dict:
        recent_text = " ".join(str(msg.get("content", "") or "") for msg in messages[-12:])
        topic = TopicDetector().detect_topic(messages)
        return {
            "topic": topic,
            "message_count": len(messages),
            "recent_text": recent_text,
        }


class ProbabilityEngine:
    """Decide whether an action should occur with a probability."""

    def should_act(self, probability: float, *, rng: Optional[Callable[[], float]] = None) -> bool:
        rng = rng or random.random
        return rng() <= probability


class CooldownManager:
    """Prevent spam by enforcing simple cooldowns per channel and action."""

    def __init__(self, default_seconds: int = 45) -> None:
        self.default_seconds = default_seconds
        self._cooldowns: dict[tuple[str, str], datetime] = {}

    def allow(self, channel_key: str, action: str, *, seconds: Optional[int] = None) -> bool:
        key = (channel_key, action)
        now = datetime.utcnow()
        until = self._cooldowns.get(key)
        if until and now < until:
            return False
        self._cooldowns[key] = now + timedelta(seconds=seconds or self.default_seconds)
        return True


class ConversationRevival:
    """Decide when a dead chat is worth reviving."""

    def should_revive(self, *, last_user_message_age: timedelta, rng: Optional[Callable[[], float]] = None) -> bool:
        rng = rng or random.random
        if last_user_message_age < timedelta(minutes=2):
            return False
        probability = 0.2 if last_user_message_age >= timedelta(minutes=3) else 0.1
        return rng() <= probability


class ReplyGenerator:
    """Generate short, in-character replies for spontaneous participation."""

    REPLIES = {
        "jojo": [
            "bro got plot armor premium 💀",
            "nah that fight was so unfair 😭",
            "johnny really woke up and chose violence",
        ],
        "minecraft": [
            "the creeper always ruins the vibe",
            "that base was one block away from disaster",
        ],
        "programming": [
            "the bug was there the whole time 😭",
            "this codebase has a personal grudge",
        ],
        "discord": [
            "the server drama is somehow always 10x worse",
            "this channel is a full-time event",
        ],
        "football": [
            "that ref was asleep",
            "that goal was absolutely cooked",
        ],
        "anime": [
            "the plot twist hit like a truck",
            "araki really said hold my beer",
        ],
        "cats": [
            "the cat knew exactly what it was doing",
            "tiny menace with a full schedule",
        ],
    }

    def build_reply(self, topic: Optional[str]) -> str:
        if not topic:
            return random.choice([
                "the vibes are doing a lot right now",
                "this chat has officially derailed",
                "someone call the recap team",
            ])
        options = self.REPLIES.get(topic, [])
        if not options:
            return random.choice([
                "the vibes are doing a lot right now",
                "lowkey this is chaos",
            ])
        return random.choice(options)
