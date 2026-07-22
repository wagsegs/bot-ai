import os
import random
from typing import Optional

import aiohttp


class RedditService:
    """Fetch a live meme image from Reddit using OAuth."""

    def __init__(self) -> None:
        self.client_id = os.getenv("REDDIT_CLIENT_ID", "")
        self.client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
        self.user_agent = os.getenv("REDDIT_USER_AGENT", "mi-bombo-bot/1.0")
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0

    async def _get_access_token(self) -> Optional[str]:
        if self._token and self._token_expiry > self._now():
            return self._token
        if not self.client_id or not self.client_secret:
            return None

        auth = aiohttp.BasicAuth(self.client_id, self.client_secret)
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": self.user_agent},
                auth=auth,
            ) as response:
                if response.status != 200:
                    return None
                payload = await response.json()
                token = payload.get("access_token")
                expires_in = int(payload.get("expires_in", 3600))
                if token:
                    self._token = token
                    self._token_expiry = self._now() + expires_in - 60
                    return token
        return None

    async def fetch_random_meme(self, subreddit: str) -> Optional[str]:
        token = await self._get_access_token()
        if not token:
            return None

        url = f"https://oauth.reddit.com/r/{subreddit}/hot?limit=25"
        headers = {"User-Agent": self.user_agent, "Authorization": f"bearer {token}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    return None
                payload = await response.json()

        children = payload.get("data", {}).get("children", [])
        candidates = []
        for child in children:
            data = child.get("data", {})
            if not data:
                continue
            if data.get("over_18"):
                continue
            if data.get("is_self") or data.get("is_video"):
                continue
            if data.get("gallery_data"):
                continue
            if not data.get("url"):
                continue
            if data.get("removed_by_category") or data.get("hidden"):
                continue
            if not data.get("url", "").startswith(("http://", "https://")):
                continue
            if not data.get("url", "").lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                continue
            candidates.append(data)

        if not candidates:
            return None

        candidate = random.choice(candidates)
        return candidate.get("url")

    def _now(self) -> float:
        import time

        return time.time()
