import ast
import asyncio
import json
import logging
import os
import random
import re
from collections import deque
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from openai import AsyncOpenAI, AuthenticationError, RateLimitError, APIConnectionError, APIStatusError

from config import BOT_NAME, GROQ_API_KEY, RESPONSE_DELAY, require_config
from utils.conversation import ConversationSession
from utils.database import (
    init_db,
    save_message,
    get_recent_context,
    get_recent_channel_context,
    prune_old_conversations,
    clear_all_conversations,
)
from utils.personality import MOODS, build_system_prompt
from utils.supabase_memory import persistent_db_client
from utils.gif_api import fetch_gif
from utils.middleware import AIRequestMiddleware
from utils.video_search import (
    search_video,
    _looks_like_video_request,
    _extract_search_query,
    _is_follow_up_request,
    VIDEO_OPENERS,
)

require_config()

logger = logging.getLogger("mi_bombo")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

print("=== GROQ === Initializing client...")
client = AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)

CLIP_TRIGGERS = (
    "bot kun clip that",
    "clip this",
    "save this",
    "that deserves a clip",
    "clip that",
    "save that",
)

QUOTE_TRIGGERS = (
    "bot kun quote this",
    "quote him",
    "quote her",
    "quote that",
    "make this a quote",
    "quote this",
)

PARTICIPATION_MESSAGES = (
    "y'all been complaining about Monday for 15 minutes 😭",
    "bro this argument has had 7 plot twists",
    "this chat has officially derailed",
    "someone call the recap team, this thread is wild",
    "the vibes here are peak chaos rn",
)

SERIOUS_KEYWORDS = {
    "rip",
    "condolences",
    "sorry",
    "prayers",
    "trauma",
    "hospital",
    "death",
    "passed away",
    "rest in peace",
    "incident",
    "emergency",
    "help",
}

CLIP_SUMMARY_CHANNEL_ID = 1526652930604662955


class AIChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.sessions: dict[tuple[str, str], ConversationSession] = {}
        self.bot_name_pattern = self._build_bot_name_pattern(BOT_NAME)
        self.active_personality_mode = "default"
        self.active_mood = "locked in"
        self._mood_updated_at = datetime.utcnow()
        self.ai_enabled = True
        self._provider_status = "ready"
        self._start_time = datetime.utcnow()
        self.middleware = AIRequestMiddleware()
        self._participation_cooldowns: dict[int, datetime] = {}
        self._recent_video_topics: dict[int, str] = {}
        self._recent_video_ids: dict[int, deque[str]] = {}
        self._last_clip_time: dict[int, datetime] = {}
        self._identity_message_counts: dict[int, int] = {}
        init_db()
        print("=== COG INIT ===")
        print("AIChatCog initialized")

    def _is_bot_mention(self, message: discord.Message) -> bool:
        return any(
            mention.id == self.bot.user.id for mention in message.mentions
        )

    def _is_reply_to_bot(self, message: discord.Message) -> bool:
        if not message.reference or not message.reference.resolved:
            return False
        referenced = message.reference.resolved
        return isinstance(referenced, discord.Message) and referenced.author.id == self.bot.user.id

    def _build_bot_name_pattern(self, bot_name: str) -> re.Pattern:
        tokens = re.findall(r"[A-Za-z0-9]+", bot_name)
        if not tokens:
            return re.compile(r"$^")
        separator = r"[\s\-]+"
        pattern = r"(?<![A-Za-z0-9])" + separator.join(re.escape(token) for token in tokens) + r"(?![A-Za-z0-9])"
        return re.compile(pattern, re.I)

    def _is_bot_name_mentioned(self, message: discord.Message) -> bool:
        if not message.content:
            return False
        return bool(self.bot_name_pattern.search(message.content))

    def _strip_bot_name(self, text: str) -> str:
        return self.bot_name_pattern.sub("", text).strip()

    def _sanitize_reply_text(self, text: str) -> str:
        if not text:
            return ""
        cleaned = text
        cleaned = cleaned.replace("@everyone", "@\u200beveryone")
        cleaned = cleaned.replace("@here", "@\u200bhere")
        cleaned = re.sub(r"<@!?\d+>", "[mention removed]", cleaned)
        cleaned = re.sub(r"<@&\d+>", "[role mention removed]", cleaned)
        return cleaned.strip()

    def _collect_visible_roles(self, member: discord.Member | None) -> list[str]:
        if not member:
            return []
        roles: list[str] = []
        for role in getattr(member, "roles", []) or []:
            if role is None:
                continue
            if getattr(role, "name", None) in {"@everyone"}:
                continue
            if getattr(role, "managed", False):
                continue
            role_name = getattr(role, "name", None)
            if role_name:
                roles.append(role_name)
        return roles

    def _get_member_context(self, member: discord.Member | None) -> str:
        if not member:
            return "User context is unavailable."
        display_name = getattr(member, "display_name", getattr(member, "name", "Unknown"))
        nickname = getattr(member, "nick", "") or "None"
        highest_role = getattr(getattr(member, "top_role", None), "name", "None")
        roles = self._collect_visible_roles(member)
        important_roles = []
        if member.guild_permissions.administrator:
            important_roles.append("Administrator")
        if member.guild_permissions.manage_guild:
            important_roles.append("Guild Manager")
        if member.guild_permissions.manage_channels:
            important_roles.append("Moderator")
        if member.guild_permissions.manage_messages:
            important_roles.append("Moderator")
        if getattr(member, "voice", None) and getattr(member.voice, "channel", None):
            important_roles.append("In Voice Channel")
        joined = getattr(member, "joined_at", None)
        joined_text = joined.strftime("%Y-%m-%d") if joined else "Unknown"
        lines = [
            f"User: {display_name}",
            f"Nickname: {nickname}",
            f"Highest Role: {highest_role}",
        ]
        if important_roles:
            lines.append("Important Roles: " + ", ".join(dict.fromkeys(important_roles)))
        else:
            lines.append("Important Roles: None")
        lines.append(f"Owner/Admin/Moderator: {'Yes' if member.guild_permissions.administrator or member.guild_permissions.manage_guild or member.guild_permissions.manage_messages else 'No'}")
        if getattr(member, "voice", None) and getattr(member.voice, "channel", None):
            lines.append(f"Voice Channel: {member.voice.channel.name}")
        lines.append(f"Joined Server: {joined_text}")
        return "\n".join(lines)

    def _update_identity_memory(self, member: discord.Member) -> None:
        self._identity_message_counts[member.id] = self._identity_message_counts.get(member.id, 0) + 1
        identity = {
            "discord_user_id": str(member.id),
            "guild_id": str(member.guild.id) if member.guild else "",
            "username": getattr(member, "name", ""),
            "display_name": getattr(member, "display_name", ""),
            "nickname": getattr(member, "nick", "") or "",
            "highest_role": getattr(getattr(member, "top_role", None), "name", ""),
            "important_roles": json.dumps([
                role for role in [
                    "Owner" if member.guild and member.guild.owner_id == member.id else None,
                    "Administrator" if member.guild_permissions.administrator else None,
                    "Moderator" if member.guild_permissions.manage_messages or member.guild_permissions.manage_guild else None,
                ]
                if role
            ]),
            "join_date": getattr(member, "joined_at", None),
            "last_seen": datetime.utcnow(),
            "message_count": self._identity_message_counts[member.id],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        asyncio.create_task(persistent_db_client.enqueue_identity(identity))

    def _clip_triggered(self, content: str) -> bool:
        lowered = content.lower()
        return any(trigger in lowered for trigger in CLIP_TRIGGERS)

    def _quote_triggered(self, content: str) -> bool:
        lowered = content.lower()
        return any(trigger in lowered for trigger in QUOTE_TRIGGERS)

    def _is_serious_channel(self, content: str) -> bool:
        lowered = content.lower()
        return any(keyword in lowered for keyword in SERIOUS_KEYWORDS)

    def _can_participate(self, channel_id: int) -> bool:
        cooldown = self._participation_cooldowns.get(channel_id)
        if cooldown and datetime.utcnow() < cooldown:
            return False
        self._participation_cooldowns[channel_id] = datetime.utcnow() + timedelta(minutes=30)
        return True

    def _track_identity_activity(self, member: discord.Member) -> None:
        try:
            self._update_identity_memory(member)
        except Exception as exc:
            print("=== IDENTITY MEMORY === failed to update:", exc)

    async def _maybe_participate(self, message: discord.Message) -> bool:
        if random.random() > 0.015:
            return False
        if self._is_serious_channel(message.content or ""):
            return False
        recent = get_recent_channel_context(str(message.channel.id), limit=25)
        user_ids = [entry["user_id"] for entry in recent if entry.get("role") == "user"]
        if len(recent) < 12 or len(set(user_ids)) < 3:
            return False
        if not self._can_participate(message.channel.id):
            return False
        try:
            await message.channel.send(
                random.choice(PARTICIPATION_MESSAGES),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return True
        except Exception as exc:
            print("=== PARTICIPATION === failed to send message:", exc)
            return False

    def _refresh_mood(self) -> None:
        now = datetime.utcnow()
        if now - self._mood_updated_at >= timedelta(hours=4):
            self.active_mood = random.choice(list(MOODS.keys()))
            self._mood_updated_at = now

    def _build_clip_summary(self, recent_messages: list[dict]) -> str:
        if not recent_messages:
            return "This channel is quiet, but I still found something weird to say."

        user_messages = []
        for msg in recent_messages:
            role = msg.get("role")
            if role == "user":
                user_messages.append(msg)
                continue
            if msg.get("user_id") and msg.get("content") is not None:
                user_messages.append(msg)

        user_ids = [msg.get("user_id") for msg in user_messages if msg.get("user_id")]
        unique_users = len(set(user_ids))
        total_messages = len(user_messages)
        word_counts: dict[str, int] = {}
        for msg in user_messages:
            content = msg.get("content", "")
            if len(content) < 10:
                continue
            lower = content.lower()
            for word in re.findall(r"[a-z]{3,}", lower):
                if word in {"the", "and", "for", "you", "that", "this", "with", "have", "from", "just", "your", "dont", "does", "what", "when", "then", "like"}:
                    continue
                word_counts[word] = word_counts.get(word, 0) + 1
        common_words = [word for word, count in sorted(word_counts.items(), key=lambda x: (-x[1], x[0]))[:3] if count > 1]
        highlight = common_words[0] if common_words else "drama"
        top_actor = None
        author_counts: dict[str, int] = {}
        for msg in user_messages:
            author = msg.get("user_id")
            if author:
                author_counts[author] = author_counts.get(author, 0) + 1
        if author_counts:
            top_actor = max(author_counts, key=author_counts.get)
        episode_line = f"Today's episode: {total_messages} messages, {unique_users} people were in the scene."
        if top_actor:
            episode_line += ""
        extra_line = f"Most of it was about {highlight}."
        roast_line = "Nobody learned anything."
        return f"{episode_line}\n{extra_line}\n{roast_line}"

    async def _fetch_live_clip_messages(self, channel: discord.TextChannel) -> list[dict]:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        messages: list[discord.Message] = []
        async for message in channel.history(after=today, oldest_first=True, limit=None):
            if len(messages) >= 1000:
                break
            messages.append(message)

        filtered_messages: list[dict] = []
        for message in messages:
            content = getattr(message, "content", "") or ""
            author = getattr(message, "author", None)
            if not author:
                continue
            if getattr(author, "bot", False):
                continue
            if getattr(message, "webhook_id", None):
                continue
            if not content.strip():
                continue
            if getattr(message, "type", None) is not None and getattr(message.type, "value", None) == "application_command":
                continue
            filtered_messages.append({
                "content": content,
                "user_id": str(getattr(author, "id", "unknown")),
                "username": getattr(author, "name", "unknown"),
                "created_at": getattr(message, "created_at", None),
                "reference": getattr(message, "reference", None),
            })

        return filtered_messages

    async def _post_clip_summary(self, message: discord.Message) -> None:
        if self._is_serious_channel(message.content):
            return
        if message.channel.id in self._last_clip_time and datetime.utcnow() - self._last_clip_time[message.channel.id] < timedelta(minutes=20):
            return

        channel = message.channel
        live_messages = await self._fetch_live_clip_messages(channel)
        print("=== CLIP GENERATOR ===")
        print("Source: Discord History")
        print("Channel:", getattr(channel, "name", "unknown"))
        print("Messages fetched:", len(live_messages))
        print("Users:", len({item["user_id"] for item in live_messages}))
        print("Time range: today")
        if len(live_messages) < 10:
            print("=== CLIP WARNING ===")
            print(f"Only {len(live_messages)} messages found.")

        summary_text = self._build_clip_summary(live_messages)
        self._last_clip_time[message.channel.id] = datetime.utcnow()
        target_channel = self.bot.get_channel(CLIP_SUMMARY_CHANNEL_ID)
        if target_channel is None:
            return
        try:
            await target_channel.send(summary_text, allowed_mentions=discord.AllowedMentions.none())
        except Exception as exc:
            print("=== CLIP SUMMARY === failed to post summary:", exc)

    async def _handle_quote_request(self, message: discord.Message) -> bool:
        if not self._quote_triggered(message.content):
            return False
        if not message.reference or not message.reference.resolved:
            print("=== QUOTE ===")
            print("No reply target found")
            await self._send_reply(message, "reply to the message you want quoted first 😭")
            return True
        referenced = message.reference.resolved
        if not hasattr(referenced, "reply") or not callable(getattr(referenced, "reply")):
            print("=== QUOTE ===")
            print("Referenced message was not a Discord message")
            await self._send_reply(message, "reply to the message you want quoted first 😭")
            return True

        print("=== QUOTE ===")
        print("Target message:", referenced.id)
        print("Replying with mention:", "<@949479338275913799>")
        print("Mention author:", True)
        try:
            await referenced.reply(
                "<@949479338275913799>",
                mention_author=True,
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    replied_user=True,
                ),
            )
            return True
        except Exception as exc:
            print("=== QUOTE TRIGGER === failed to reply:", exc)
            return False

    def _build_server_context_block(self, current_user: discord.Member | None, mentioned_users: list[discord.Member] | None = None) -> str:
        context_lines: list[str] = ["=== Server Context ===", ""]
        if current_user is None:
            context_lines.append("Current User")
            context_lines.append("Display Name: Unknown")
            context_lines.append("Highest Role: Unknown")
            context_lines.append("Roles: None")
            context_lines.append("Administrator: No")
            context_lines.append("")
        else:
            context_lines.append("Current User")
            context_lines.append(f"Display Name: {getattr(current_user, 'display_name', getattr(current_user, 'name', 'Unknown'))}")
            highest_role = getattr(current_user, "top_role", None)
            highest_role_name = getattr(highest_role, "name", None) or "None"
            context_lines.append(f"Highest Role: {highest_role_name}")
            visible_roles = self._collect_visible_roles(current_user)
            context_lines.append("Roles:")
            if visible_roles:
                context_lines.extend(f"- {role}" for role in visible_roles[:8])
            else:
                context_lines.append("- None")
            admin = bool(getattr(getattr(current_user, "guild_permissions", None), "administrator", False))
            owner = bool(getattr(current_user, "id", None) and getattr(getattr(current_user, "guild", None), "owner_id", None) == getattr(current_user, "id", None))
            moderator = bool(getattr(current_user, "moderator", False))
            context_lines.append(f"Administrator: {'Yes' if admin else 'No'}")
            context_lines.append(f"Owner: {'Yes' if owner else 'No'}")
            context_lines.append(f"Moderator: {'Yes' if moderator else 'No'}")
            context_lines.append("")

        if mentioned_users:
            context_lines.append("Mentioned Users")
            for member in mentioned_users[:4]:
                display_name = getattr(member, "display_name", getattr(member, "name", "Unknown"))
                highest_role = getattr(member, "top_role", None)
                highest_role_name = getattr(highest_role, "name", None) or "None"
                visible_roles = self._collect_visible_roles(member)
                context_lines.append(f"Display Name: {display_name}")
                context_lines.append(f"Highest Role: {highest_role_name}")
                context_lines.append("Roles:")
                if visible_roles:
                    context_lines.extend(f"- {role}" for role in visible_roles[:8])
                else:
                    context_lines.append("- None")
                admin = bool(getattr(getattr(member, "guild_permissions", None), "administrator", False))
                context_lines.append(f"Administrator: {'Yes' if admin else 'No'}")
                context_lines.append("")
        return "\n".join(context_lines).strip()

    def _should_refuse_mass_mention(self, text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        return any(token in lowered for token in ["ping everyone", "tag everyone", "mention all members", "mention everyone", "ping all", "tag all"])

    def _is_known_command(self, content: str) -> bool:
        if not content or not content.startswith("~"):
            return False
        known_commands = {
            "~activate",
            "~deactivate",
            "~mode",
            "~resetmode",
            "~status",
            "~memoryclear",
            "~reload",
            "~help",
        }
        return content.split()[0].lower() in known_commands

    def _format_uptime(self, uptime: timedelta) -> str:
        total_seconds = int(uptime.total_seconds())
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)

        parts: list[str] = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds or not parts:
            parts.append(f"{seconds}s")
        return " ".join(parts)

    async def _send_reply(self, message: discord.Message, text: str, embed: discord.Embed | None = None) -> discord.Message | None:
        if not text and embed is None:
            return None

        safe_text = self._sanitize_reply_text(text) if text else None
        if safe_text is not None and not safe_text:
            safe_text = "nah, not doing mass mentions."

        print("=== DISCORD SEND === Typing indicator start")
        async with message.channel.typing():
            await asyncio.sleep(RESPONSE_DELAY)
            try:
                print("=== DISCORD SEND === Sending reply to original message")
                sent_message = await message.reply(
                    content=safe_text,
                    embed=embed,
                    mention_author=True,
                    allowed_mentions=discord.AllowedMentions(replied_user=True),
                )
                print("Sent reply successfully:", getattr(sent_message, "id", None))
                return sent_message
            except Exception as reply_exc:
                print("Discord reply exception, falling back to channel.send:", reply_exc)
                sent_message = await message.channel.send(
                    safe_text or "",
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(replied_user=True),
                )
                print("Sent fallback channel message successfully:", getattr(sent_message, "id", None))
                return sent_message

    def _normalize_bool(self, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"true", "yes", "1", "on"}
        return False

    def _try_parse_json(self, text: str) -> dict | None:
        if not text or not isinstance(text, str):
            return None
        candidate = text.strip()
        if not candidate:
            return None

        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

        try:
            decoder = json.JSONDecoder()
            parsed, _ = decoder.raw_decode(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    def _find_json_object(self, text: str) -> dict | None:
        if not text:
            return None

        for block in re.findall(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.S | re.I):
            parsed = self._try_parse_json(block)
            if parsed is not None:
                return parsed

        cursor = 0
        while True:
            start = text.find("{", cursor)
            if start == -1:
                break
            parsed = self._try_parse_json(text[start:])
            if parsed is not None:
                return parsed
            cursor = start + 1

        return None

    def _find_matching_brace(self, text: str, start_index: int) -> int | None:
        depth = 0
        in_string = False
        escape = False
        for index in range(start_index, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    return index
        return None

    def _strip_json_from_text(self, text: str) -> str:
        if not text:
            return ""

        cleaned = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", text, flags=re.S | re.I)

        metadata_fragment_pattern = re.compile(
            r'(?is)(?:^|[\r\n])\s*(?:"text"\s*:\s*".*?"\s*(?:,|\n)\s*"send_gif"\s*:\s*(?:true|false)\s*(?:,|\n)\s*"gif_query"\s*:\s*".*?"|'
            r'"text"\s*:\s*".*?"\s*(?:,|\n)\s*"gif_query"\s*:\s*".*?"\s*(?:,|\n)\s*"send_gif"\s*:\s*(?:true|false)|'
            r'"send_gif"\s*:\s*(?:true|false)\s*(?:,|\n)\s*"gif_query"\s*:\s*".*?"\s*(?:,|\n)\s*"text"\s*:\s*".*?")'
        )
        cleaned = metadata_fragment_pattern.sub("", cleaned)

        start = cleaned.find('{')
        while start != -1:
            end = self._find_matching_brace(cleaned, start)
            if end is None:
                break
            snippet = cleaned[start:end + 1]
            if '"text"' in snippet or '"send_gif"' in snippet or '"gif_query"' in snippet:
                cleaned = cleaned[:start] + cleaned[end + 1:]
                break
            start = cleaned.find('{', start + 1)

        return cleaned.strip()

    async def _request_groq_once(self, messages: list[dict]) -> dict:
        print("=== GROQ ===")
        print("Using model: llama-3.3-70b-versatile")
        print("Sending request...")
        try:
            response = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.9,
            )
            print("Received response")
            usage = getattr(response, "usage", None)
            if usage is not None:
                print("Tokens used:", usage)
                total_tokens = getattr(usage, "total_tokens", None)
                self.middleware._record_token_usage(total_tokens)
            response_text = ""
            if response.choices and len(response.choices) > 0:
                response_text = getattr(response.choices[0].message, "content", "")
            print("Response text:", repr(response_text))
            self._provider_status = "ready"
            extracted = self._find_json_object(response_text)
            if isinstance(extracted, dict):
                print("Parsed JSON response")
                text_value = extracted.get("text", "")
                if not isinstance(text_value, str):
                    text_value = str(text_value) if text_value is not None else ""
                text_value = text_value.strip()
                text_value = text_value or self._strip_json_from_text(response_text)

                send_gif = self._normalize_bool(extracted.get("send_gif", False))
                gif_query = str(extracted.get("gif_query", "")).strip() if send_gif else ""
                return {
                    "reply": text_value,
                    "gif_category": gif_query if send_gif and gif_query else None,
                }

            cleaned_text = self._strip_json_from_text(response_text)
            if cleaned_text:
                return {"reply": cleaned_text, "gif_category": None}

            print("GROQ response did not parse as JSON or contained only malformed JSON metadata")
            print("Raw response text:", repr(response_text))
            return {"reply": "", "gif_category": None}
        except AuthenticationError as auth_exc:
            self._provider_status = "auth_error"
            print("Provider error:", auth_exc)
            return {"reply": "", "gif_category": None}
        except RateLimitError as rate_exc:
            self._provider_status = "rate_limited"
            print("Provider error:", rate_exc)
            return {"reply": "", "gif_category": None}
        except APIConnectionError as conn_exc:
            self._provider_status = "network_error"
            print("Provider error:", conn_exc)
            return {"reply": "", "gif_category": None}
        except APIStatusError as api_exc:
            self._provider_status = "provider_error"
            print("Provider error:", api_exc)
            return {"reply": "", "gif_category": None}
        except Exception as exc:
            self._provider_status = "provider_error"
            print("Provider error:", exc)
            return {"reply": "", "gif_category": None}

    async def _get_ai_reply(self, prompt: str, context: list[dict], *, user_id: str | None = None, server_context: str | None = None) -> dict:
        self._refresh_mood()
        system_prompt = build_system_prompt(self.active_personality_mode, self.active_mood)
        messages = [{"role": "system", "content": system_prompt}]
        for item in context:
            messages.append({"role": item["role"], "content": item["content"]})
        if server_context:
            messages.append({"role": "system", "content": server_context})
        messages.append({"role": "user", "content": prompt})

        async def provider_call() -> dict:
            return await self._request_groq_once(messages)

        async def retry_provider_call() -> dict:
            retry_messages = [
                {"role": "system", "content": self.middleware._recovery_instruction},
                {"role": "system", "content": system_prompt},
            ]
            retry_messages.extend(messages[1:])
            return await self._request_groq_once(retry_messages)

        fallback_message = random.choice(["nah my brain lagged for a sec 💀", "brain lag", "thinking machine exploded"])
        result = await self.middleware.request(
            provider_call,
            user_id=user_id,
            fallback_message=fallback_message,
            retry_request_fn=retry_provider_call,
        )
        return result

    async def _handle_response(self, message: discord.Message, prompt: str) -> None:
        print("=== MESSAGE HANDLER ===")
        print("Handling AI response for user:", message.author.id, "channel:", message.channel.id)
        if self._should_refuse_mass_mention(prompt):
            await self._send_reply(message, "respectfully no, I’m not mass mentioning people.")
            return

        if self._quote_triggered(prompt):
            if await self._handle_quote_request(message):
                return

        if self._clip_triggered(prompt):
            await self._post_clip_summary(message)
            return

        explicit_video_request = _looks_like_video_request(prompt)
        is_follow_up = _is_follow_up_request(prompt)
        if explicit_video_request and (not is_follow_up or self._recent_video_topics.get(message.channel.id)):
            previous_topic = self._recent_video_topics.get(message.channel.id)
            raw_query = previous_topic if is_follow_up and previous_topic else prompt
            query = _extract_search_query(raw_query)
            if not query:
                await self._send_reply(message, "bro even YouTube couldn't find anything 😭")
                return
            recent_video_ids = list(self._recent_video_ids.get(message.channel.id, deque(maxlen=10)))
            video_url = await search_video(raw_query, previous_topic=previous_topic, recent_video_ids=recent_video_ids)
            if video_url:
                opener_list = VIDEO_OPENERS.get(self.active_personality_mode, VIDEO_OPENERS.get("default", []))
                opener_text = random.choice(opener_list) if opener_list else "gotchu"
                await self._send_reply(message, f"{opener_text}\n{video_url}")
                self._recent_video_topics[message.channel.id] = query
                recent_ids = self._recent_video_ids.setdefault(message.channel.id, deque(maxlen=10))
                video_id_match = re.search(r"(?:youtu\.be/|youtube\.com/watch\?v=)([A-Za-z0-9_-]+)", video_url)
                video_id = video_id_match.group(1) if video_id_match else video_url.rsplit("/", 1)[-1]
                recent_ids.append(video_id)
                return
            await self._send_reply(message, "bro even YouTube couldn't find anything 😭")
            return

        context = get_recent_context(str(message.author.id), str(message.channel.id), limit=8)
        print("=== DATABASE === Conversation loaded:", len(context), "messages")
        mentioned_users: list[discord.Member] = []
        if message.mentions:
            mentioned_users = [mention for mention in message.mentions if isinstance(mention, discord.Member)]
        server_context = self._build_server_context_block(message.author if isinstance(message.author, discord.Member) else None, mentioned_users)
        result = await self._get_ai_reply(prompt, context, user_id=str(message.author.id), server_context=server_context)
        reply_text = result["reply"][:250].strip()
        if len(reply_text) >= 250:
            reply_text = reply_text[:-1] + "…"

        save_message(str(message.author.id), str(message.channel.id), "user", prompt)
        save_message(str(message.author.id), str(message.channel.id), "assistant", reply_text)
        print("=== DATABASE === Conversation saved")

        if reply_text:
            print("=== DISCORD SEND === Attempting to send text reply...")
            await self._send_reply(message, reply_text)

        if result.get("gif_category"):
            gif_url = await fetch_gif(result["gif_category"])
            if gif_url:
                print("=== DISCORD SEND === Final GIF URL to send:", gif_url)
                try:
                    sent_gif_message = await message.channel.send(gif_url, allowed_mentions=discord.AllowedMentions.none())
                    print("Sent GIF URL successfully:", getattr(sent_gif_message, "id", None))
                except Exception as exc:
                    print("Discord exception while sending GIF URL:", exc)
                    raise

        print("=== FINAL === Finished handling message")

    async def _handle_admin_command(self, message: discord.Message) -> None:
        if not message.content:
            return
        content = message.content.strip()
        if not content.startswith("~"):
            return

        command = content.split()[0].lower()
        is_admin = message.author.guild_permissions.administrator

        if command == "~help":
            embed = discord.Embed(
                title="━━━━━━━━━━━━━━━━━━\n🤖 MI BOMBO AI",
                description="A polished Discord-side AI companion with personality controls and admin tools.",
                color=discord.Color.from_rgb(0x7B, 0x61, 0xFF),
            )
            embed.add_field(name="📚 General Commands", value="`~help` Shows this menu\n`~mode` Shows the current personality", inline=False)
            embed.add_field(name="🛠 Administrator Commands", value="`~activate` Enable AI globally\n`~deactivate` Disable AI globally\n`~mode <personality>` Change the active personality\n`~resetmode` Reset to Default\n`~status` Show AI status\n`~memoryclear` Clear conversation memory\n`~reload` Reload personality prompt", inline=False)
            embed.add_field(name="🎭 Available Personalities", value="⭐ Default\n💖 UWU\n😈 Gremlin\n🕵 Detective\n👑 Villain\n📜 NPC\n😴 Sleepy\n💀 Chaotic\n🥊 Tsundere\n🏴 Pirate\n🎮 Gamer\n🏢 Corporate\n🎭 Anime\n🐱 Cat\n📖 Oracle\n🇯🇲 Jamaican\n⚖️ Saul", inline=False)
            embed.add_field(name="Current Mode", value=f"**{self.active_personality_mode.title()}**", inline=False)
            embed.set_footer(text="Only administrators may change personalities.")
            await self._send_reply(message, None, embed=embed)
            return

        if not is_admin:
            if self._is_known_command(content):
                await self._send_reply(message, "🎬 Nice try. The Director didn't clear you for that command.")
            else:
                await self._send_reply(message, "🤨 Never heard of that command.\nTry ~help instead.")
            return

        if content == "~activate":
            self.ai_enabled = True
            await self._send_reply(message, "AI is back online, boss.")
            return

        if content == "~deactivate":
            self.ai_enabled = False
            await self._send_reply(message, "AI is offline for now.")
            return

        if content == "~mode":
            await self._send_reply(message, f"Current mode: {self.active_personality_mode}")
            return

        if content == "~resetmode":
            self.active_personality_mode = "default"
            await self._send_reply(message, "Mode reset to default.")
            return

        if content.startswith("~mode "):
            mode = content.split(maxsplit=1)[1].strip().lower()
            valid_modes = {"default", "uwu", "gremlin", "detective", "villain", "npc", "sleepy", "chaotic", "tsundere", "pirate", "gamer", "corporate", "anime", "cat", "oracle", "jamaican", "saul"}
            if mode in valid_modes:
                self.active_personality_mode = mode
                await self._send_reply(message, f"Mode changed to {mode}.")
            else:
                await self._send_reply(message, "That mode doesn't exist, sadly.")
            return

        if content == "~status":
            uptime = datetime.utcnow() - self._start_time
            provider_status = self._provider_status
            if provider_status == "ready":
                provider_value = "Ready"
            elif provider_status == "rate_limited":
                provider_value = "Rate Limited"
            elif provider_status in {"auth_error", "network_error", "provider_error"}:
                provider_value = "Offline"
            else:
                provider_value = provider_status.replace("_", " ").title()

            stats = self.middleware.get_stats()
            embed = discord.Embed(
                title="🤖 MI BOMBO AI Status",
                description="Live status and bot telemetry.",
                color=discord.Color.teal(),
            )
            embed.add_field(name="🤖 AI", value="Enabled" if self.ai_enabled else "Disabled", inline=True)
            embed.add_field(name="🎭 Current Personality", value=self.active_personality_mode.title(), inline=True)
            embed.add_field(name="🧠 AI Model", value="llama-3.3-70b-versatile", inline=True)
            embed.add_field(name="🌐 Provider", value=provider_value, inline=True)
            embed.add_field(name="📡 Ping", value=f"{round(self.bot.latency * 1000)} ms", inline=True)
            embed.add_field(name="⏱ Uptime", value=self._format_uptime(uptime), inline=True)
            embed.add_field(name="📈 Success", value=str(stats.get("successful_requests", 0)), inline=True)
            embed.add_field(name="⚠️ Failures", value=str(stats.get("failed_requests", 0)), inline=True)
            embed.add_field(name="🔁 Retries", value=str(stats.get("retries", 0)), inline=True)
            embed.add_field(name="🛠 Repaired", value=str(stats.get("repaired_outputs", 0)), inline=True)
            embed.add_field(name="🚦 Rate Limits", value=str(stats.get("rate_limit_errors", 0)), inline=True)
            embed.add_field(name="⏳ Avg Reply", value=f"{stats.get('average_response_ms', 0)} ms", inline=True)
            embed.add_field(name="🏁 Queue", value=str(stats.get("queue_size", 0)), inline=True)
            embed.add_field(name="💬 Conversations", value=str(len(self.sessions)), inline=True)
            embed.add_field(name="🏠 Guild", value=message.guild.name if message.guild else "Direct Message", inline=True)
            embed.add_field(name="📅 Started", value=self._start_time.strftime("%Y-%m-%d %H:%M UTC"), inline=True)
            embed.set_footer(text="MI BOMBO AI")
            await self._send_reply(message, None, embed=embed)
            return

        if content == "~memoryclear":
            clear_all_conversations()
            await self._send_reply(message, "Memory cleared.")
            return

        if content == "~reload":
            await self._send_reply(message, "Personality prompt reloaded.")
            return

        await self._send_reply(message, "🤨 Never heard of that command.\nTry ~help instead.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        print("=== MESSAGE RECEIVED ===")
        print("Author:", message.author, message.author.id)
        print("Channel:", message.channel, getattr(message.channel, "id", None))
        print("Guild:", message.guild, getattr(message.guild, "id", None))
        print("Content:", repr(message.content))
        print("Mentions:", [mention.id for mention in message.mentions])
        print("Reply target:", getattr(message.reference, "message_id", None), "resolved:", bool(getattr(message.reference, "resolved", None)))

        mention_detected = False
        reply_to_bot = False
        name_detected = False
        if self.bot.user:
            mention_detected = self._is_bot_mention(message)
            reply_to_bot = self._is_reply_to_bot(message)
            name_detected = self._is_bot_name_mentioned(message)

        is_dot_ai = bool(message.content and message.content.startswith(".ai "))
        is_roast = bool(message.content and "roast me" in message.content.lower())
        is_admin_command = bool(message.content and message.content.startswith("~"))
        is_bang_command = bool(message.content and message.content.startswith("!"))
        is_question_command = bool(message.content and message.content.startswith("?"))

        print("=== FILTERS ===")
        print("Mention detected:", mention_detected)
        print("Name detected:", name_detected)
        print("Reply to bot:", reply_to_bot)
        print("Is .ai command:", is_dot_ai)
        print("Roast trigger:", is_roast)
        print("Should respond:", mention_detected or name_detected or reply_to_bot or is_dot_ai or is_roast)

        if message.author.bot:
            print("Ignored because author is bot")
            return

        if not message.guild:
            print("Ignored because message is not in a guild")
            return

        if not self.bot.is_ready():
            print("Ignored because bot is not ready")
            return

        if not message.content:
            print("Ignored because message content is empty; message_content intent may be missing")
            return

        if isinstance(message.author, discord.Member):
            self._track_identity_activity(message.author)

        if is_bang_command or is_question_command:
            print("Ignored because message uses a legacy command prefix")
            return

        if is_admin_command:
            await self._handle_admin_command(message)
            return

        if not self.ai_enabled:
            print("Ignored because AI is disabled globally")
            return

        if mention_detected or name_detected:
            prompt = message.content
            if mention_detected:
                prompt = re.sub(r"<@!?\d+>", "", prompt).strip()
            if name_detected:
                prompt = self._strip_bot_name(prompt)
            prompt = prompt.strip()
            if not prompt:
                prompt = "Say hello in a fun and friendly way."
            await self._handle_response(message, prompt)
            return

        if reply_to_bot:
            prompt = message.content.strip()
            if not prompt:
                prompt = "Continue the conversation naturally."
            await self._handle_response(message, prompt)
            return

        if is_dot_ai:
            prompt = message.content[4:].strip()
            if prompt:
                await self._handle_response(message, prompt)
            return

        if is_roast:
            await self._handle_response(message, "Roast me playfully and harmlessly.")
            return

        participated = await self._maybe_participate(message)
        if participated:
            return

        print("Ignored because no trigger matched")

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        print("=== COG READY ===")
        prune_old_conversations(30)
        await persistent_db_client.start()
        stats = await persistent_db_client.get_stats()
        print("=== DATABASE === Pruned old conversations")
        print("🧠 Persistent Memory")
        print(f"Status: {stats['status'].title()}")
        print(f"Users: {stats['users']}")
        print(f"Relationships: {stats['relationships']}")
        print(f"Quotes: {stats['quotes']}")
        print(f"Topics: {stats['topics']}")
        print(f"Queue: {stats['queue']}")
        print(f"Pool: {stats['pool']}")
