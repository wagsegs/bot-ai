import asyncio
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from ai.action_planner import ActionPlanner
from ai.prompt_builder import build_system_prompt
from tools import youtube
from memory.server_cache import ServerCache
from utils.middleware import AIRequestMiddleware

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("GROQ_API_KEY", "test-key")

spec = importlib.util.spec_from_file_location("ai_chat_module", ROOT / "cogs" / "ai_chat.py")
ai_chat_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai_chat_module)


class AIChatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cog = ai_chat_module.AIChatCog.__new__(ai_chat_module.AIChatCog)
        self.cog.planner = ActionPlanner()
        self.cog.server_cache = ServerCache()

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

    def test_build_system_prompt_single_personality(self) -> None:
        prompt = build_system_prompt()
        self.assertIn("not an assistant", prompt.lower())
        self.assertIn("never ping", prompt.lower())
        self.assertIn("@everyone", prompt)
        self.assertNotIn("personality mode", prompt.lower())

    def test_build_system_prompt_includes_emoji_hint(self) -> None:
        prompt = build_system_prompt(user_emoji_hint="😭💀")
        self.assertIn("😭", prompt)

    def test_strip_json_from_text_removes_metadata_fragment(self) -> None:
        response = '"text": "aw thanks",\n"send_gif": true,\n"gif_query": "hug"'
        self.assertEqual(self.cog._strip_json_from_text(response), "")

    def test_strip_json_from_text_keeps_regular_message(self) -> None:
        response = "Sure thing, I can help with that."
        self.assertEqual(self.cog._strip_json_from_text(response), response)

    def test_sanitize_reply_text_removes_mass_mentions(self) -> None:
        cog = ai_chat_module.AIChatCog.__new__(ai_chat_module.AIChatCog)
        text = "sure @everyone and @here and <@123> and <@&456> go ahead"
        sanitized = cog._sanitize_reply_text(text)
        self.assertNotIn("@everyone", sanitized)
        self.assertNotIn("@here", sanitized)
        self.assertNotIn("<@", sanitized)

    def test_should_refuse_mass_mention(self) -> None:
        cog = ai_chat_module.AIChatCog.__new__(ai_chat_module.AIChatCog)
        self.assertTrue(cog._should_refuse_mass_mention("please ping everyone"))
        self.assertFalse(cog._should_refuse_mass_mention("say hi"))

    def test_known_command_detection(self) -> None:
        cog = ai_chat_module.AIChatCog.__new__(ai_chat_module.AIChatCog)
        self.assertTrue(cog._is_known_command("~botkun"))
        self.assertTrue(cog._is_known_command("~dashboard"))
        self.assertFalse(cog._is_known_command("~mode"))
        self.assertFalse(cog._is_known_command("~aihelp"))

    def test_video_request_detection(self) -> None:
        self.assertTrue(youtube.looks_like_video_request("play the video of birds"))
        self.assertTrue(youtube.looks_like_video_request("pull up interstellar trailer"))
        self.assertFalse(youtube.looks_like_video_request("tell me a story"))

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

        with patch("tools.youtube.aiohttp.ClientSession", return_value=FakeSession()):
            result = asyncio.run(youtube.search_video("bird video", recent_video_ids=["first-video"]))
        self.assertEqual(result, "https://youtu.be/second-video")

    def test_clip_generator_builds_episode_summary(self) -> None:
        from tools.clip import ClipGenerator
        gen = ClipGenerator()
        messages = [
            {"content": "hello drama", "user_id": "1", "role": "user"},
            {"content": "yo drama continues", "user_id": "2", "role": "user"},
        ]
        summary = gen.build_summary(messages, user_names={"1": "<@1>", "2": "<@2>"})
        self.assertIn("Episode #", summary)
        self.assertIn("2 messages", summary)

    def test_action_planner_never_leaks_json(self) -> None:
        planner = ActionPlanner()
        result = planner.parse_response('{"text": "yo whats up", "send_gif": false, "gif_query": ""}')
        self.assertEqual(result["reply"], "yo whats up")
        # validate_output_text should parse the JSON and return the text field
        leaked = planner.validate_output_text('{"text": "broken", "send_gif": true}')
        self.assertEqual(leaked, "broken")
        self.assertNotIn("{", leaked)

    def test_unwrap_quoted_string_removes_outer_quotes(self) -> None:
        planner = ActionPlanner()
        self.assertEqual(planner.unwrap_quoted_string('"hello"'), "hello")
        self.assertEqual(planner.unwrap_quoted_string("'hello'"), "hello")
        self.assertEqual(planner.unwrap_quoted_string('"heyyyy!! 🙌"'), "heyyyy!! 🙌")
        self.assertEqual(planner.unwrap_quoted_string('  "hello"  '), "hello")

    def test_unwrap_quoted_string_preserves_internal_quotes(self) -> None:
        planner = ActionPlanner()
        self.assertEqual(planner.unwrap_quoted_string('He said "hello" yesterday.'), 'He said "hello" yesterday.')
        self.assertEqual(planner.unwrap_quoted_string('"He said \\"hello\\""'), '"He said \\"hello\\""')  # escaped quotes inside

    def test_validate_output_text_unwraps_quoted_replies(self) -> None:
        planner = ActionPlanner()
        self.assertEqual(planner.validate_output_text('"hello"'), "hello")
        self.assertEqual(planner.validate_output_text('"heyyyy!! 🙌"'), "heyyyy!! 🙌")
        self.assertEqual(planner.validate_output_text('He said "hello" yesterday.'), 'He said "hello" yesterday.')

    def test_server_context_block(self) -> None:
        class RoleStub:
            def __init__(self, name: str, managed: bool = False) -> None:
                self.name = name
                self.managed = managed

        class MemberStub:
            def __init__(self, display_name: str, name: str, roles: list[RoleStub], admin: bool = False) -> None:
                self.display_name = display_name
                self.name = name
                self.nick = None
                self.roles = roles
                self.guild_permissions = type("Perms", (), {"administrator": admin})()
                self.guild = type("Guild", (), {"owner_id": 99, "id": 1})()
                self.id = 1
                self.top_role = roles[-1] if roles else None

        current = MemberStub("Diego", "diego", [RoleStub("Producer"), RoleStub("Main Cast")])
        mentioned = [MemberStub("Bob", "bob", [RoleStub("Director")], admin=True)]
        context = self.cog._build_server_context_block(current, mentioned)
        self.assertIn("Current User", context)
        self.assertIn("Display Name: Diego", context)
        self.assertIn("Mentioned Users", context)

    def test_conversation_manager_continuation_works(self) -> None:
        from router.conversation_manager import ConversationManager
        from datetime import datetime, timedelta, UTC
        
        manager = ConversationManager()
        channel_id = "channel-123"
        diego_id = "user-456"
        bob_id = "user-789"
        
        # Diego starts conversation with mention
        manager.claim(channel_id, diego_id)
        
        # Diego continues without mention - should respond
        self.assertTrue(manager.should_respond(channel_id, diego_id, directed_at_bot=False))
        
        # Bob interrupts - should NOT respond (not owner, not directed)
        self.assertFalse(manager.should_respond(channel_id, bob_id, directed_at_bot=False))
        
        # Diego continues again - should still respond
        self.assertTrue(manager.should_respond(channel_id, diego_id, directed_at_bot=False))
        
        # Bob mentions bot directly - should respond and claim
        self.assertTrue(manager.should_respond(channel_id, bob_id, directed_at_bot=True))
        self.assertEqual(manager.get_owner(channel_id), bob_id)
        
        # Now Diego interrupts - should NOT respond
        self.assertFalse(manager.should_respond(channel_id, diego_id, directed_at_bot=False))

    def test_conversation_manager_expires_after_timeout(self) -> None:
        from router.conversation_manager import ConversationManager
        from datetime import datetime, timedelta, UTC
        
        manager = ConversationManager()
        channel_id = "channel-123"
        user_id = "user-456"
        
        # Start conversation
        manager.claim(channel_id, user_id)
        self.assertEqual(manager.get_owner(channel_id), user_id)
        
        # Manually expire the conversation
        conv = manager._active[channel_id]
        conv.last_activity = datetime.now(UTC) - timedelta(minutes=15)
        
        # Should now return None (expired)
        self.assertIsNone(manager.get_owner(channel_id))
        
        # Should not respond to continuation after expiration
        self.assertFalse(manager.should_respond(channel_id, user_id, directed_at_bot=False))


if __name__ == "__main__":
    unittest.main()
