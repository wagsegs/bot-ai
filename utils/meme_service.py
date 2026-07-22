import os
import random
from typing import Optional

import aiohttp


class MemeService:
    """Fetch memes from Meme-API with lightweight filtering and duplicate prevention."""

    TOPIC_SUBREDDITS = {
        "jojo": ["ShitPostCrusaders"],
        "sbr": ["ShitPostCrusaders"],
        "jjba": ["ShitPostCrusaders"],
        "minecraft": ["MinecraftMemes"],
        "programming": ["ProgrammerHumor"],
        "python": ["ProgrammerHumor"],
        "coding": ["ProgrammerHumor"],
        "anime": ["animemes"],
        "football": ["footballmemes"],
        "discord": ["discordmemes"],
    }

    GENERAL_SUBREDDITS = ["AdviceAnimals", "dankmemes", "memes"]

    def __init__(self) -> None:
        self.base_url = os.getenv("MEME_API_URL", "https://meme-api.com")
        self._recent_urls: list[str] = []

    def _normalize_topic(self, topic: Optional[str]) -> Optional[str]:
        if not topic:
            return None
        return topic.strip().lower().replace(" ", "")

    def get_subreddits_for_topic(self, topic: Optional[str]) -> list[str]:
        normalized = self._normalize_topic(topic)
        if not normalized:
            return list(self.GENERAL_SUBREDDITS)
        if normalized in self.TOPIC_SUBREDDITS:
            return list(self.TOPIC_SUBREDDITS[normalized])
        if normalized.endswith("meme"):
            normalized = normalized[:-4]
        if normalized in self.TOPIC_SUBREDDITS:
            return list(self.TOPIC_SUBREDDITS[normalized])
        return list(self.GENERAL_SUBREDDITS)

    async def fetch_meme(self, topic: Optional[str] = None, *, count: int = 10) -> Optional[dict]:
        subreddits = self.get_subreddits_for_topic(topic)
        if not subreddits:
            return None

        for subreddit in subreddits:
            url = f"{self.base_url}/gimme/{subreddit}/{count}"
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=10) as response:
                        if response.status != 200:
                            continue
                        payload = await response.json()
            except Exception:
                continue

            items = payload.get("memes") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                continue
            candidates = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("nsfw") is True:
                    continue
                if item.get("spoiler") is True:
                    continue
                if not item.get("url"):
                    continue
                if item.get("ups", 0) is not None and int(item.get("ups", 0)) < 50:
                    continue
                if item.get("url") in self._recent_urls:
                    continue
                candidates.append(item)

            if not candidates:
                continue

            chosen = random.choice(candidates)
            self._recent_urls.append(chosen["url"])
            if len(self._recent_urls) > 100:
                self._recent_urls = self._recent_urls[-100:]
            return chosen

        return None

    async def fetch_meme_url(self, topic: Optional[str] = None) -> Optional[str]:
        meme = await self.fetch_meme(topic)
        return meme.get("url") if meme else None
