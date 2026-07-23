"""Unified tool manager — routes all tool execution."""

import random
import re
from collections import deque
from typing import Optional

from tools import gifs, memes, youtube

MEME_TRIGGERS = (
    "send a meme", "send me a meme", "give me a meme",
    "show me a meme", "drop a meme", "show a meme", "meme please",
)

TOPIC_MAP = {
    "jojo": ["jojo", "jjba", "steel ball run"],
    "minecraft": ["minecraft"],
    "programming": ["programming", "coding", "python"],
    "anime": ["anime", "naruto", "one piece"],
    "football": ["football", "soccer"],
    "discord": ["discord"],
}


class ToolManager:
    def __init__(self) -> None:
        self._meme_service = memes.MemeService()
        self._recent_video_topics: dict[int, str] = {}
        self._recent_video_ids: dict[int, deque[str]] = {}
        self._executed_actions: list[str] = []

    def reset_actions(self) -> None:
        self._executed_actions = []

    @property
    def executed_actions(self) -> list[str]:
        return list(self._executed_actions)

    def looks_like_meme_request(self, prompt: str) -> bool:
        lowered = prompt.lower()
        return any(t in lowered for t in MEME_TRIGGERS)

    def extract_meme_topic(self, prompt: str) -> Optional[str]:
        lowered = prompt.lower()
        for topic, phrases in TOPIC_MAP.items():
            if any(p in lowered for p in phrases):
                return topic
        return None

    async def handle_meme(self, topic: Optional[str] = None) -> Optional[str]:
        url = await self._meme_service.fetch_meme_url(topic)
        if url:
            self._executed_actions.append("meme")
        return url

    async def handle_gif(self, query: str) -> Optional[str]:
        url = await gifs.fetch_gif(query)
        if url:
            self._executed_actions.append("gif")
        return url

    async def handle_youtube(
        self,
        prompt: str,
        channel_id: int,
        *,
        explicit: bool = False,
        query_override: Optional[str] = None,
    ) -> Optional[str]:
        previous = self._recent_video_topics.get(channel_id)
        is_follow_up = youtube.is_follow_up_request(prompt)
        if not explicit and not youtube.looks_like_video_request(prompt) and not query_override:
            return None
        raw = query_override or (previous if is_follow_up and previous else prompt)
        search_q = youtube.extract_search_query(raw)
        if not search_q:
            return None
        recent_ids = list(self._recent_video_ids.get(channel_id, deque(maxlen=10)))
        url = await youtube.search_video(raw, previous_topic=previous, recent_video_ids=recent_ids)
        if url:
            self._executed_actions.append("youtube")
            self._recent_video_topics[channel_id] = search_q
            ids = self._recent_video_ids.setdefault(channel_id, deque(maxlen=10))
            match = re.search(r"(?:youtu\.be/|youtube\.com/watch\?v=)([A-Za-z0-9_-]+)", url)
            vid = match.group(1) if match else url.rsplit("/", 1)[-1]
            ids.append(vid)
        return url

    def youtube_opener(self) -> str:
        return random.choice(youtube.VIDEO_OPENERS)

    async def maybe_natural_gif(self, mood_hint: str, *, probability: float = 0.25) -> Optional[str]:
        if random.random() > probability:
            return None
        return await self.handle_gif(mood_hint or "reaction")
