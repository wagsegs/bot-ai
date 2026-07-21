import asyncio
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from utils import video_search
from utils.middleware import AIRequestMiddleware
from utils.personality import build_system_prompt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("GROQ_API_KEY", "test-key")

spec = importlib.util.spec_from_file_location("ai_chat_module", ROOT / "cogs" / "ai_chat.py")
ai_chat_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai_chat_module)


class AIChatCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cog = ai_chat_module.AIChatCog.__new__(ai_chat_module.AIChatCog)
        self.cog.active_personality_mode = "default"

    def test_output_validator_extracts_visible_reply_from_metadata(self) -> None:
        middleware = AIRequestMiddleware()
        repaired = middleware._validate_output_text("MY GOSH 😳\n[text]: hello\n[send_gif]: false", fallback="nah")
        self.assertEqual(repaired, "MY GOSH 😳")

    def test_output_validator_recovers_json_and_xml_formatting(self) -> None:
        middleware = AIRequestMiddleware()
        self.assertEqual(middleware._validate_output_text('```json\n{"text":"hi"}\n```', fallback="nah"), "hi")
        self.assertEqual(middleware._validate_output_text("<tag>hi</tag>", fallback="nah"), "hi")

    def test_spam_detection_allows_normal_bursts_and_delays_later(self) -> None:
        middleware = AIRequestMiddleware()
        user_id = "spam-test"
        for _ in range(5):
            state, delay = middleware._get_spam_state(user_id)
            self.assertEqual(state, "allow")
            self.assertIsNone(delay)

        state, delay = middleware._get_spam_state(user_id)
        self.assertEqual(state, "delay")
        self.assertIsNotNone(delay)

    def test_build_system_prompt_uses_global_mode_and_safety_rules(self) -> None:
        prompt = build_system_prompt("uwu")
        self.assertIn("Active personality mode: uwu", prompt)
        self.assertIn("uwu", prompt.lower())
        self.assertIn("never ping", prompt.lower())
        self.assertIn("@everyone", prompt)

    def test_strip_json_from_text_removes_metadata_fragment_without_braces(self) -> None:
        response = '"text": "aw thanks, sending you a virtual hug",\n"send_gif": true,\n"gif_query": "hug emoji gif"'
        self.assertEqual(self.cog._strip_json_from_text(response), "")

    def test_strip_json_from_text_keeps_regular_message(self) -> None:
        response = "Sure thing, I can help with that."
        self.assertEqual(self.cog._strip_json_from_text(response), response)

    def test_sanitize_reply_text_removes_mass_mentions(self) -> None:
        text = "sure @everyone and @here and <@123> and <@&456> go ahead"
        sanitized = self.cog._sanitize_reply_text(text)
        self.assertNotIn("@everyone", sanitized)
        self.assertNotIn("@here", sanitized)
        self.assertNotIn("<@", sanitized)

    def test_should_refuse_mass_mention_detects_ping_everyone(self) -> None:
        self.assertTrue(self.cog._should_refuse_mass_mention("please ping everyone"))
        self.assertTrue(self.cog._should_refuse_mass_mention("tag everyone for me"))
        self.assertFalse(self.cog._should_refuse_mass_mention("say hi to the group"))

    def test_known_command_detection_only_supports_tilde_prefix(self) -> None:
        self.assertTrue(self.cog._is_known_command("~help"))
        self.assertTrue(self.cog._is_known_command("~activate"))
        self.assertFalse(self.cog._is_known_command("?help"))
        self.assertFalse(self.cog._is_known_command("!activate"))
        self.assertFalse(self.cog._is_known_command("~mystery"))

    def test_jamaican_mode_prompt_includes_keywords(self) -> None:
        prompt = build_system_prompt("jamaican")
        self.assertIn("jamaican", prompt.lower())
        self.assertIn("mi bomboooo", prompt.lower())
        self.assertIn("ya mon", prompt.lower())

    def test_saul_mode_prompt_includes_character_traits(self) -> None:
        prompt = build_system_prompt("saul")
        self.assertIn("saul", prompt.lower())
        self.assertIn("courtroom", prompt.lower())
        self.assertIn("persuasive", prompt.lower())

    def test_video_request_detection_and_query_extraction(self) -> None:
        self.assertTrue(video_search._looks_like_video_request("bot kun pull up a bird chirping video"))
        self.assertEqual(video_search._extract_search_query("bot kun pull up a bird chirping video"), "bird chirping video")
        self.assertEqual(video_search._extract_search_query("show me monkey eating banana"), "monkey eating banana video")
        self.assertFalse(video_search._looks_like_video_request("tell me a story"))

    def test_explicit_video_requests_are_distinguished_from_normal_chat(self) -> None:
        self.assertTrue(video_search._looks_like_video_request("show me another"))
        self.assertTrue(video_search._looks_like_video_request("can you show it"))
        self.assertTrue(video_search._looks_like_video_request("another one"))
        self.assertTrue(video_search._looks_like_video_request("got another?"))
        self.assertFalse(video_search._looks_like_video_request("that's good shit"))
        self.assertFalse(video_search._looks_like_video_request("lmao"))

    def test_search_video_skips_recently_sent_video_ids(self) -> None:
        os.environ["YOUTUBE_API_KEY"] = "test-youtube-key"

        class FakeResponse:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def text(self):
                return """{"items":[{"id":{"videoId":"first-video"},"snippet":{"title":"First","description":"","channelTitle":"Channel A","publishedAt":"2024-01-01T00:00:00Z"}}, {"id":{"videoId":"second-video"},"snippet":{"title":"Second","description":"","channelTitle":"Channel B","publishedAt":"2024-01-01T00:00:00Z"}}]}"""

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def get(self, *args, **kwargs):
                return FakeResponse()

        with patch("utils.video_search.aiohttp.ClientSession", return_value=FakeSession()):
            result = asyncio.run(video_search.search_video("bird video", recent_video_ids=["first-video"]))

        self.assertEqual(result, "https://youtu.be/second-video")

    def test_video_request_rejects_explicit_content(self) -> None:
        self.assertFalse(video_search._is_safe_request("show me porn"))
        self.assertFalse(video_search._is_safe_request("find me a gore video"))
        self.assertTrue(video_search._is_safe_request("pull up a funny cat video"))

    def test_clip_summary_uses_live_discord_history(self) -> None:
        class FakeMessage:
            def __init__(self, content: str, author_id: int, author_name: str, author_bot: bool = False, webhook_id: int | None = None, message_type: object | None = None) -> None:
                self.content = content
                self.author = SimpleNamespace(id=author_id, name=author_name, bot=author_bot)
                self.webhook_id = webhook_id
                self.type = message_type or object()

        class FakeChannel:
            def __init__(self) -> None:
                self.id = 777
                self.name = "general"
                self._messages = [
                    FakeMessage("hello", 101, "Diego"),
                    FakeMessage("yo", 102, "Aizen"),
                    FakeMessage("bot message", 999, "Bot", author_bot=True),
                    FakeMessage("", 103, "LasVegas"),
                    FakeMessage("/slash", 104, "Dev", message_type=SimpleNamespace(value="application_command")),
                    FakeMessage("another one", 101, "Diego"),
                    FakeMessage("lmao", 102, "Aizen"),
                ]

            def history(self, *, after=None, oldest_first=True, limit=None):
                async def iterator():
                    for message in self._messages:
                        yield message

                return iterator()

        class FakeTargetChannel:
            def __init__(self) -> None:
                self.sent_messages = []

            async def send(self, content, allowed_mentions=None):
                self.sent_messages.append((content, allowed_mentions))
                return SimpleNamespace(id=1)

        fake_channel = FakeChannel()
        fake_target = FakeTargetChannel()
        message = SimpleNamespace(channel=fake_channel, content="bot kun clip that", author=SimpleNamespace(id=1))

        self.cog.bot = SimpleNamespace(get_channel=lambda channel_id: fake_target)
        self.cog._last_clip_time = {}

        async def fake_get_recent_channel_context(*args, **kwargs):
            return [{"role": "user", "user_id": "stale", "content": "old message"}]

        with patch("cogs.ai_chat.get_recent_channel_context", side_effect=fake_get_recent_channel_context):
            asyncio.run(self.cog._post_clip_summary(message))

        sent_text = fake_target.sent_messages[0][0]
        self.assertIn("Today's episode: 4 messages", sent_text)
        self.assertIn("2 people", sent_text)

    def test_published_score_uses_timezone_aware_datetimes(self) -> None:
        item = {"snippet": {"publishedAt": "2030-01-01T00:00:00Z"}}
        self.assertEqual(video_search._published_score(item, prefer_recent=True), 1.5)

    def test_handle_quote_request_replies_to_target_message_with_exact_mention(self) -> None:
        target = SimpleNamespace(id=123, reply=AsyncMock(return_value=SimpleNamespace(id=456)))
        message = SimpleNamespace(content="bot kun quote this", reference=SimpleNamespace(resolved=target), author=SimpleNamespace(id=99))

        original_message_cls = ai_chat_module.discord.Message
        ai_chat_module.discord.Message = type("FakeMessage", (), {})
        try:
            result = asyncio.run(self.cog._handle_quote_request(message))
        finally:
            ai_chat_module.discord.Message = original_message_cls

        self.assertTrue(result)
        target.reply.assert_awaited_once()
        args, kwargs = target.reply.await_args
        self.assertEqual(args[0], "<@949479338275913799>")
        self.assertTrue(kwargs["mention_author"])
        self.assertTrue(kwargs["allowed_mentions"].users)
        self.assertTrue(kwargs["allowed_mentions"].replied_user)

    def test_handle_quote_request_asks_for_a_reply_target_when_reference_missing(self) -> None:
        message = SimpleNamespace(content="bot kun quote this", reference=None, author=SimpleNamespace(id=99))

        async def fake_send_reply(msg, text, embed=None):
            self.assertEqual(text, "reply to the message you want quoted first 😭")
            return SimpleNamespace(id=777)

        self.cog._send_reply = fake_send_reply
        result = asyncio.run(self.cog._handle_quote_request(message))

        self.assertTrue(result)

    def test_server_context_block_includes_current_and_mentioned_members(self) -> None:
        class RoleStub:
            def __init__(self, name: str, managed: bool = False) -> None:
                self.name = name
                self.managed = managed

        class MemberStub:
            def __init__(self, display_name: str, name: str, roles: list[RoleStub], nick: str | None = None, admin: bool = False, owner: bool = False, moderator: bool = False) -> None:
                self.display_name = display_name
                self.name = name
                self.nick = nick
                self.roles = roles
                self.guild_permissions = type("Perms", (), {"administrator": admin})()
                self.guild = type("Guild", (), {"owner_id": 99})()
                self.id = 1
                self.top_role = roles[-1] if roles else None
                self.owner = owner
                self.moderator = moderator

        current_user = MemberStub("Diego", "diego", [RoleStub("Producer"), RoleStub("Main Cast")], admin=False, owner=False, moderator=False)
        mentioned = [MemberStub("Bob", "bob", [RoleStub("Director"), RoleStub("Staff")], nick="Bobski", admin=True, owner=False, moderator=True)]
        context = self.cog._build_server_context_block(current_user, mentioned)
        self.assertIn("Current User", context)
        self.assertIn("Display Name: Diego", context)
        self.assertIn("Mentioned Users", context)
        self.assertIn("Display Name: Bob", context)
        self.assertIn("Administrator: Yes", context)


if __name__ == "__main__":
    unittest.main()
