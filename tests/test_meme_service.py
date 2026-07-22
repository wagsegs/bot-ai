import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from utils.meme_service import MemeService


class MemeServiceTests(unittest.TestCase):
    def test_topic_mapping_returns_expected_subreddits(self) -> None:
        service = MemeService()

        self.assertEqual(service.get_subreddits_for_topic("jojo"), ["ShitPostCrusaders"])
        self.assertEqual(service.get_subreddits_for_topic("programming"), ["ProgrammerHumor"])
        self.assertEqual(service.get_subreddits_for_topic("unknown"), ["AdviceAnimals", "dankmemes", "memes"])

    def test_fetch_meme_filters_unsuitable_items(self) -> None:
        service = MemeService()

        class FakeResponse:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def json(self):
                return {
                    "memes": [
                        {"url": "https://img/a.jpg", "nsfw": False, "spoiler": False, "ups": 120},
                        {"url": "https://img/b.jpg", "nsfw": True, "spoiler": False, "ups": 120},
                        {"url": "https://img/c.jpg", "nsfw": False, "spoiler": True, "ups": 120},
                        {"url": "https://img/d.jpg", "nsfw": False, "spoiler": False, "ups": 5},
                    ]
                }

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def get(self, *args, **kwargs):
                return FakeResponse()

        with patch("utils.meme_service.aiohttp.ClientSession", return_value=FakeSession()):
            meme = asyncio.run(service.fetch_meme("programming"))

        self.assertEqual(meme["url"], "https://img/a.jpg")
