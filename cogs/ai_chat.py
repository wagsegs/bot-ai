import asyncio
import logging
import random
import re
import sys
from datetime import datetime, timezone

import discord
from discord.ext import commands

from ai.action_planner import ActionPlanner
from ai.groq_provider import GroqProvider
from ai.prompt_builder import build_system_prompt
from config import BOT_NAME, require_config
from memory.conversation_memory import ConversationMemory
from memory.server_cache import ServerCache
from memory.user_memory import UserMemory
from moderation.blacklist import Blacklist
from moderation.nsfw import NSFWModerator
from moderation.spam import SpamFilter
from monitoring.dashboard import DashboardData
from monitoring.queue import RECOVERY_INSTRUCTION, RequestQueue
from router.conversation_manager import ConversationManager
from router.intent_detector import DetectedIntent, Intent, IntentDetector
from router.message_router import NaturalParticipation
from tools.clip import CLIP_SUMMARY_CHANNEL_ID, ClipGenerator
from tools.manager import MEME_TRIGGERS, ToolManager
from tools import youtube
from utils.availability import get_bot_availability, is_bot_available
from utils.database import init_db, prune_old_conversations
from utils.response_budget import can_respond, get_response_budget, record_request
from utils.supabase_memory import persistent_db_client

require_config()

logger = logging.getLogger("botkun")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

ADMIN_COMMANDS = {"~bot", "~dashboard", "~reload", "~blacklist", "~clip"}
PUBLIC_COMMANDS = {"~botkun", "~guide"}


class AIChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.ai_enabled = True
        self._start_time = datetime.utcnow()

        self.provider = GroqProvider()
        self.planner = ActionPlanner()
        self.queue = RequestQueue()
        self.tools = ToolManager()
        self.memory = ConversationMemory()
        self.user_memory = UserMemory()
        self.server_cache = ServerCache()
        self.conversations = ConversationManager()
        self.blacklist = Blacklist()
        self.spam = SpamFilter()
        self.nsfw = NSFWModerator()
        self.clip_gen = ClipGenerator()
        self.natural = NaturalParticipation(self.memory)

        self.bot_name_pattern = self._build_bot_name_pattern(BOT_NAME)
        self.intent_detector = IntentDetector(self.bot_name_pattern)

        init_db()
        logger.info("AIChatCog initialized")

    def _build_bot_name_pattern(self, bot_name: str) -> re.Pattern:
        tokens = re.findall(r"[A-Za-z0-9]+", bot_name)
        if not tokens:
            return re.compile(r"$^")
        separator = r"[\s\-]+"
        pattern = r"(?<![A-Za-z0-9])" + separator.join(re.escape(t) for t in tokens) + r"(?![A-Za-z0-9])"
        return re.compile(pattern, re.I)

    def _compute_reply_delay(self) -> float:
        queue_size = self.queue.get_stats().get("queue_size", 0)
        load = self.queue.rate_limiter.current_rate()
        if queue_size >= 3 or load >= 4:
            return random.uniform(8, 20)
        return random.uniform(3, 8)

    def _sanitize_reply_text(self, text: str) -> str:
        if not text:
            return ""
        cleaned = text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
        cleaned = re.sub(r"<@!?\d+>", "[mention removed]", cleaned)
        cleaned = re.sub(r"<@&\d+>", "[role mention removed]", cleaned)
        return cleaned.strip()

    def _should_refuse_mass_mention(self, text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        return any(t in lowered for t in ["ping everyone", "tag everyone", "mention all members", "mention everyone"])

    def _is_known_command(self, content: str) -> bool:
        if not content or not content.startswith("~"):
            return False
        return content.split()[0].lower() in ADMIN_COMMANDS | PUBLIC_COMMANDS

    async def _is_admin(self, user: discord.User | discord.Member) -> bool:
        if isinstance(user, discord.Member) and user.guild_permissions.administrator:
            return True
        if self.bot.owner_id and user.id == self.bot.owner_id:
            return True
        app = getattr(self.bot, "application", None)
        owner = getattr(app, "owner", None)
        return bool(owner and user.id == owner.id)

    async def _send_reply(
        self,
        message: discord.Message,
        text: str,
        embed: discord.Embed | None = None,
    ) -> discord.Message | None:
        if not text and embed is None:
            return None
        safe_text = self._sanitize_reply_text(text) if text else None
        if safe_text is not None and not safe_text:
            safe_text = "nah, not doing mass mentions."
        delay = self._compute_reply_delay()
        async with message.channel.typing():
            await asyncio.sleep(delay)
            try:
                return await message.reply(
                    content=safe_text,
                    embed=embed,
                    mention_author=True,
                    allowed_mentions=discord.AllowedMentions(replied_user=True),
                )
            except Exception:
                return await message.channel.send(
                    safe_text or "",
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(replied_user=True),
                )

    async def _get_ai_reply(
        self,
        prompt: str,
        user_id: str,
        channel_id: str,
        guild_id: str,
        server_context: str | None = None,
    ) -> dict:
        emoji_hint = self.user_memory.get_emoji_hint(user_id, guild_id)
        system_prompt = build_system_prompt(user_emoji_hint=emoji_hint)
        context = self.memory.build_ai_context(user_id, channel_id)
        user_hint = self.user_memory.get_context_hint(user_id, guild_id)
        messages = [{"role": "system", "content": system_prompt}]
        if user_hint:
            messages.append({"role": "system", "content": f"User context:\n{user_hint}"})
        for item in context:
            messages.append({"role": item["role"], "content": item["content"]})
        if server_context:
            messages.append({"role": "system", "content": server_context})
        messages.append({"role": "user", "content": prompt})

        async def provider_call() -> dict:
            return await self.provider.chat(messages)

        async def retry_call() -> dict:
            retry_messages = [
                {"role": "system", "content": RECOVERY_INSTRUCTION},
                *messages,
            ]
            return await self.provider.chat(retry_messages)

        spam_state = self.spam.record_attempt(user_id)
        result = await self.queue.enqueue(
            provider_call,
            user_id=user_id,
            fallback_message=random.choice(["nah my brain lagged for a sec 💀", "brain lag"]),
            retry_request_fn=retry_call,
            validate_fn=self.planner.validate_output_text,
            spam_block=spam_state == "ignore",
        )
        if result.get("dropped"):
            return {"reply": "", "gif_category": None, "youtube_query": None, "meme_topic": None, "actions": []}
        return result

    async def _execute_tool_actions(self, message: discord.Message, result: dict) -> dict:
        self.tools.reset_actions()
        channel_id = message.channel.id
        actions = result.get("actions", [])

        if result.get("youtube_query"):
            url = await self.tools.handle_youtube(
                result["youtube_query"], channel_id, explicit=True, query_override=result["youtube_query"]
            )
            if url:
                opener = self.tools.youtube_opener()
                existing = result.get("reply", "")
                result["reply"] = f"{existing}\n{opener}\n{url}".strip() if existing else f"{opener}\n{url}"
            elif "couldn't find" not in (result.get("reply") or "").lower():
                result["reply"] = (result.get("reply") or "") + "\nbro even YouTube couldn't find anything 😭"

        if result.get("meme_topic") is not None or "meme" in actions:
            url = await self.tools.handle_meme(result.get("meme_topic"))
            if url:
                result["meme_url"] = url

        if result.get("gif_category"):
            url = await self.tools.handle_gif(result["gif_category"])
            if url:
                result["gif_url"] = url

        executed = self.tools.executed_actions
        result["reply"] = self.planner.strip_youtube_claims_without_action(result.get("reply", ""), executed)
        return result

    async def _handle_response(self, message: discord.Message, prompt: str, *, natural: bool = False) -> None:
        user_id = str(message.author.id)
        channel_id = str(message.channel.id)
        guild_id = str(message.guild.id) if message.guild else ""

        if self.blacklist.is_blacklisted(user_id):
            return

        nsfw_action, nsfw_reply = self.nsfw.check(user_id, prompt)
        if nsfw_action == "ignore":
            return
        if nsfw_action == "reject" and nsfw_reply:
            await self._send_reply(message, nsfw_reply)
            return

        if self.tools.looks_like_meme_request(prompt):
            url = await self.tools.handle_meme(self.tools.extract_meme_topic(prompt))
            if url:
                await message.channel.send(url, allowed_mentions=discord.AllowedMentions.none())
                self.memory.save(user_id, channel_id, "assistant", f"[meme] {url}")
            else:
                await self._send_reply(message, "no meme today, the API was being dramatic 😭")
            self.natural.mark_bot_spoke(channel_id)
            return

        if self._should_refuse_mass_mention(prompt):
            await self._send_reply(message, "respectfully no, I'm not mass mentioning people.")
            return

        if youtube.looks_like_video_request(prompt):
            url = await self.tools.handle_youtube(prompt, message.channel.id, explicit=True)
            if url:
                await self._send_reply(message, f"{self.tools.youtube_opener()}\n{url}")
            else:
                await self._send_reply(message, "bro even YouTube couldn't find anything 😭")
            self.natural.mark_bot_spoke(channel_id)
            return

        mentioned = [m for m in message.mentions if isinstance(m, discord.Member)]
        member = message.author if isinstance(message.author, discord.Member) else None
        server_ctx = self.server_cache.build_context_block(
            message.guild.id if message.guild else 0, member, mentioned
        )

        result = await self._get_ai_reply(prompt, user_id, channel_id, guild_id, server_ctx)
        if not result.get("reply") and natural:
            return

        record_request()
        result = await self._execute_tool_actions(message, result)

        reply_text = (result.get("reply") or "")[:250].strip()
        if len(reply_text) >= 250:
            reply_text = reply_text[:-1] + "…"

        if not reply_text or self.planner.looks_like_leaked_format(reply_text):
            reply_text = random.choice(["nah my brain lagged for a sec 💀", "brain lag"])

        if reply_text == "[SKIP]":
            return

        self.memory.save(user_id, channel_id, "user", prompt)
        self.memory.save(user_id, channel_id, "assistant", reply_text)

        if reply_text:
            await self._send_reply(message, reply_text)

        if result.get("gif_url"):
            await message.channel.send(result["gif_url"], allowed_mentions=discord.AllowedMentions.none())
        elif result.get("meme_url"):
            await message.channel.send(result["meme_url"], allowed_mentions=discord.AllowedMentions.none())

        self.natural.mark_bot_spoke(channel_id)
        self.conversations.claim(channel_id, user_id)

    async def _handle_public_command(self, message: discord.Message, command: str) -> None:
        if command == "~botkun":
            # Always report actual status, don't block on availability
            status = get_bot_availability().get_status()
            if self.ai_enabled and status["is_online"]:
                await self._send_reply(message, f"{BOT_NAME} is online and lurking 👀")
            else:
                reason = "taking a break" if not status["is_online"] else "disabled"
                await self._send_reply(message, f"{BOT_NAME} is {reason} right now.")
        
        if command == "~guide":
            # Delete user's command message
            try:
                await message.delete()
            except Exception:
                pass
            
            # Create guide embed
            from pathlib import Path
            image_path = Path(__file__).parent.parent / "image.png"
            
            embed = discord.Embed(
                title="🤖 Bot-kun Guide",
                description="I'm just another member of the server.\n\nTalk to me naturally—mention me once, then keep chatting normally.\n\nI won't always reply, and that's intentional.",
                color=discord.Color.teal()
            )
            
            if image_path.exists():
                with open(image_path, "rb") as f:
                    embed.set_thumbnail(file=discord.File(f, "image.png"))
            
            embed.add_field(
                name="✨ What I Can Do",
                value="• Chat naturally\n• Pull up YouTube videos\n• Send GIFs & memes\n• Occasionally join conversations\n• Turn funny moments into **Bombo Times** episodes",
                inline=False
            )
            
            embed.add_field(
                name="💡 Tips",
                value="• You don't need commands for everything.\n• If I don't reply, I might be taking a break, busy talking to someone else, or slowing myself down.",
                inline=False
            )
            
            embed.add_field(
                name="📜 Public Commands",
                value="`~botkun`   Check if I'm online.\n`~guide`    Show this guide.",
                inline=False
            )
            
            embed.add_field(
                name="🎬 Bombo Times",
                value="Admins can use `~clip` to turn the latest conversation into a **Bombo Times** episode posted in **#bombo-times**.",
                inline=False
            )
            
            embed.set_footer(text="This guide disappears in 45 seconds.")
            
            guide_message = await message.channel.send(embed=embed)
            
            # Auto-delete after 45 seconds
            await asyncio.sleep(45)
            try:
                await guide_message.delete()
            except Exception:
                pass

    async def _handle_admin_command(self, message: discord.Message) -> None:
        content = message.content.strip()
        command = content.split()[0].lower()

        if not await self._is_admin(message.author):
            if self._is_known_command(content):
                await self._send_reply(message, "Nice try. Admin only.")
            return

        if command == "~bot":
            self.ai_enabled = not self.ai_enabled
            state = "online" if self.ai_enabled else "offline"
            await self._send_reply(message, f"Bot-kun is now {state}.")
            return

        if command == "~dashboard":
            import resource
            from pathlib import Path
            
            mem_mb = 0.0
            if sys.platform != "win32":
                mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            
            cache_breakdown = self.server_cache.get_cache_breakdown()
            
            data = DashboardData(
                start_time=self._start_time,
                provider_status=self.provider.status,
                ai_enabled=self.ai_enabled,
                queue_stats=self.queue.get_stats(),
                budget_status=get_response_budget().get_status(),
                availability_status=get_bot_availability().get_status(),
                conversation_count=self.conversations.count(),
                cache_size=self.server_cache.size(),
                memory_usage_mb=mem_mb,
                bot_latency_ms=self.bot.latency * 1000,
                last_error=self.queue.last_error,
                cache_breakdown=cache_breakdown,
            )
            
            fields = data.build_embed()
            
            # Create engineer-style dashboard embed
            embed = discord.Embed(
                title="╭──────────────────────────────╮\n        BOT-KUN DASHBOARD\n╰──────────────────────────────╯",
                color=discord.Color.dark_teal(),
                timestamp=datetime.now(timezone.utc)
            )
            
            # Add image thumbnail
            image_path = Path(__file__).parent.parent / "image.png"
            if image_path.exists():
                with open(image_path, "rb") as f:
                    embed.set_thumbnail(file=discord.File(f, "image.png"))
            
            # System section
            sys_vals = fields["system"]
            embed.add_field(
                name="System",
                value=f"**AI:** {sys_vals['ai_enabled']}\n**Provider:** {sys_vals['provider']}\n**Status:** {sys_vals['provider_status']}\n**Uptime:** {sys_vals['uptime']}",
                inline=False
            )
            
            # Performance section
            perf_vals = fields["performance"]
            embed.add_field(
                name="Performance",
                value=f"**API Latency:** {perf_vals['api_latency_ms']} ms\n**Avg Response:** {perf_vals['avg_response_ms']} ms\n**Queue:** {perf_vals['queue_size']}\n**Rate:** {perf_vals['current_rate']}\n**Req/Min:** {perf_vals['requests_per_min']}",
                inline=False
            )
            
            # Availability section
            avail_vals = fields["availability"]
            embed.add_field(
                name="Availability",
                value=f"**State:** {avail_vals['state']}\n**Time Left:** {avail_vals['remaining_minutes']} min\n**Budget:** {avail_vals['budget_state']} ({avail_vals['budget_usage']})",
                inline=False
            )
            
            # Memory section
            mem_vals = fields["memory"]
            embed.add_field(
                name="Memory",
                value=f"**Conversations:** {mem_vals['conversations']}\n**Cache:** {mem_vals['cache_size']}\n**RAM:** {mem_vals['memory_mb']}",
                inline=False
            )
            
            # Statistics section
            stats_vals = fields["statistics"]
            embed.add_field(
                name="Statistics",
                value=f"**Success:** {stats_vals['success']}\n**Failures:** {stats_vals['failures']}\n**Dropped:** {stats_vals['dropped']}\n**Last Error:** {stats_vals['last_error']}",
                inline=False
            )
            
            # Server Cache section
            cache_vals = fields["server_cache"]
            embed.add_field(
                name="Server Cache",
                value=f"**Members:** {cache_vals['members']}\n**Channels:** {cache_vals['channels']}\n**Roles:** {cache_vals['roles']}",
                inline=False
            )
            
            # Admin Commands section
            embed.add_field(
                name="Admin Commands",
                value="`~bot` Toggle Bot-kun\n`~reload` Reload bot and cache\n`~clip` Create Bombo Times episode\n`~blacklist` Manage blocked users",
                inline=False
            )
            
            # Footer with last updated time
            embed.set_footer(text=f"Last Updated\n{fields['last_updated']}")
            
            await self._send_reply(message, None, embed=embed)
            return

        if command == "~reload":
            self.server_cache.clear()
            self.conversations.clear()
            self.user_memory.clear()
            if message.guild:
                await self.server_cache.warm(message.guild)
            await self._send_reply(message, "Reloaded personality, cleared caches, restarted conversations.")
            return

        if command == "~blacklist":
            parts = content.split()
            if len(parts) < 2:
                users = self.blacklist.list_users()
                listing = ", ".join(f"<@{u}>" for u in users) if users else "Nobody blacklisted."
                await self._send_reply(message, listing)
                return
            if message.mentions:
                for user in message.mentions:
                    if parts[1].lower() in ("remove", "unblacklist", "-"):
                        self.blacklist.remove(user.id)
                        await self._send_reply(message, f"Removed <@{user.id}> from blacklist.")
                    else:
                        self.blacklist.add(user.id)
                        await self._send_reply(message, f"Blacklisted <@{user.id}>. No interaction.")
            return

        if command == "~clip":
            channel = message.channel
            messages = await self.clip_gen.fetch_channel_messages(channel, limit=30)
            episode_num = self.clip_gen.next_episode_number()
            summary, gif_query = await self.clip_gen.generate_ai_summary(
                self.clip_gen.build_conversation_prompt(messages),
                self.provider,
                episode_number=episode_num
            )
            target = self.bot.get_channel(CLIP_SUMMARY_CHANNEL_ID)
            gif_url = await self.tools.handle_gif(gif_query)
            if target:
                await target.send(summary, allowed_mentions=discord.AllowedMentions.none())
                if gif_url:
                    await target.send(gif_url, allowed_mentions=discord.AllowedMentions.none())
                await self._send_reply(message, f"Done.\n{target.jump_url if hasattr(target, 'jump_url') else ''}")
            else:
                await self._send_reply(message, "Couldn't find #bombo-times channel.")
            return

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild or not self.bot.is_ready():
            return
        if not message.content:
            return
        if message.content.startswith(("!", "?")):
            return

        user_id = str(message.author.id)
        channel_id = str(message.channel.id)

        if isinstance(message.author, discord.Member):
            self.user_memory.observe_message(
                user_id, str(message.guild.id), message.content,
                nickname=message.author.nick or message.author.display_name,
            )

        if self.blacklist.is_blacklisted(user_id):
            return

        bot_id = self.bot.user.id if self.bot.user else 0
        detected = self.intent_detector.detect(
            message,
            bot_user_id=bot_id,
            meme_triggers=MEME_TRIGGERS,
            video_check=youtube.looks_like_video_request,
        )

        if detected.intent == Intent.ADMIN_COMMAND:
            await self._handle_admin_command(message)
            return
        if detected.intent == Intent.PUBLIC_COMMAND:
            await self._handle_public_command(message, detected.command)
            return

        if not self.ai_enabled or not is_bot_available() or not can_respond():
            return

        directed = detected.intent in {
            Intent.BOT_MENTION, Intent.BOT_NAME, Intent.BOT_REPLY, Intent.ROAST,
        }

        if directed:
            self.conversations.claim(channel_id, user_id)
            await self._handle_response(message, detected.prompt)
            return

        if detected.intent == Intent.CONTINUATION:
            if self.conversations.should_respond(channel_id, user_id, directed_at_bot=False):
                await self._handle_response(message, detected.prompt)
                return

        await self.natural.maybe_participate(message, self._handle_response)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        prune_old_conversations(30)
        await persistent_db_client.start()
        for guild in self.bot.guilds:
            await self.server_cache.warm(guild)
        logger.info("Bot ready — server cache warmed for %d guilds", len(self.bot.guilds))

    # --- Backward-compatible helpers for tests ---
    def _strip_json_from_text(self, text: str) -> str:
        return self.planner.strip_json_from_text(text)

    def _build_server_context_block(self, current_user, mentioned_users=None) -> str:
        gid = current_user.guild.id if current_user and current_user.guild else 0
        return self.server_cache.build_context_block(gid, current_user, mentioned_users)
