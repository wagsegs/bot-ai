"""Clip episode summary generation for #bombo-times."""

import random
import re
from datetime import datetime, timezone
from typing import Optional

CLIP_SUMMARY_CHANNEL_ID = 1526652930604662955


class ClipGenerator:
    _episode_counter = 0

    def __init__(self) -> None:
        self._last_clip_time: dict[int, datetime] = {}

    @classmethod
    def next_episode_number(cls) -> int:
        cls._episode_counter += 1
        return cls._episode_counter

    def build_conversation_prompt(self, messages: list[dict]) -> str:
        """Build a prompt with actual conversation messages for AI summarization."""
        if not messages:
            return "No messages to summarize."

        lines = ["Summarize ONLY the following messages.", "Do not invent events.", "Retell what actually happened.", "Write it like a funny recap for a newspaper.", "", "Messages:"]
        
        for i, msg in enumerate(messages, 1):
            username = msg.get("username", "Unknown")
            content = msg.get("content", "")
            if content:
                lines.append(f"[{i}]")
                lines.append(f"{username}:")
                lines.append(content)
                lines.append("")
        
        return "\n".join(lines)

    async def generate_ai_summary(self, prompt: str, provider, episode_number: int) -> str:
        """Generate a funny recap using the AI provider."""
        system_prompt = """Generate a newspaper-style recap for Bombo Times, a recurring series based on real Discord conversations.

Your job is to turn the actual last ~30 messages into an entertaining episode, almost like recapping a sitcom.

Rules:
- Read ONLY the provided messages
- Never invent events, conversations, or jokes that didn't happen
- Focus on the funniest or most memorable 2-3 moments
- Write naturally, like someone watching the chaos unfold
- Keep the tone witty, observational, and playful
- Do NOT sound like ChatGPT or a news reporter
- Keep it around 80-150 words
- Never summarize every message one by one
- Never mention message counts, participant counts, or metadata
- Never use Discord mentions. Use plain display names only
- The GIF is handled separately by the bot, so do NOT mention GIFs or memes in the text

Forbidden phrases:
- "The conversation took a turn..."
- "Meanwhile..."
- "As the conversation progressed..."
- "People discussed..."
- "Most of the conversation..."
- "The chat was mainly about..."
- "Nobody learned anything."
- "Moral of the story..."

Episode Header:
Always begin with:
🎬 BOMBO TIMES
S0EXX
"Episode Title"

Where:
- Season is always 0
- Episode number is supplied by the application
- Create a short, memorable title (3-8 words) based on the funniest moment
- The title should feel like the name of a TV episode

Writing Style:
Write like someone who's been watching the Discord server unfold from the sidelines.
Don't explain what happened. Retell it.
Don't describe every message. Instead, build one small story around the funniest moments.
Assume the reader was there and is reliving the moment.
The humor should come from what actually happened—not from random jokes or AI filler.

Ending:
Finish with ONE short signature line such as:
- Director's Note: ...
- Roll credits.
- Fade to black.
- Until the next episode...
- Cue the ending theme.

Reference something that actually happened in the conversation whenever possible."""
        
        # Add episode number to the prompt
        episode_header = f"Episode Number: S0E{episode_number:02d}\n\n"
        user_prompt = episode_header + prompt
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        try:
            result = await provider.chat(messages)
            reply = result.get("reply", "")
            # Remove any Discord mentions that might have slipped through
            reply = re.sub(r"<@!?\d+>", "", reply)
            reply = re.sub(r"<@&\d+>", "", reply)
            return reply.strip()
        except Exception:
            return "The episode was too chaotic to summarize. Even the AI gave up."

    def build_summary(self, messages: list[dict], *, user_names: dict[str, str] | None = None, provider=None) -> str:
        """Legacy method — use generate_ai_summary instead."""
        if provider:
            prompt = self.build_conversation_prompt(messages)
            return self.generate_ai_summary(prompt, provider)
        
        # Fallback to old metadata-based summary if no provider
        if not messages:
            return "Episode recap: the channel was quiet. Suspiciously quiet."

        user_messages = [
            msg for msg in messages
            if msg.get("content") and (msg.get("role") == "user" or msg.get("user_id"))
        ]
        user_ids = [msg.get("user_id") for msg in user_messages if msg.get("user_id")]
        unique_users = len(set(user_ids))
        total = len(user_messages)

        word_counts: dict[str, int] = {}
        for msg in user_messages:
            content = msg.get("content", "")
            if len(content) < 10:
                continue
            for word in re.findall(r"[a-z]{3,}", content.lower()):
                if word in {"the", "and", "for", "you", "that", "this", "with", "have", "from", "just", "like"}:
                    continue
                word_counts[word] = word_counts.get(word, 0) + 1
        highlight = max(word_counts, key=word_counts.get) if word_counts else "chaos"

        author_counts: dict[str, int] = {}
        for msg in user_messages:
            uid = msg.get("user_id")
            if uid:
                author_counts[uid] = author_counts.get(uid, 0) + 1

        mentions = []
        if author_counts and user_names:
            top_users = sorted(author_counts, key=author_counts.get, reverse=True)[:3]
            for uid in top_users:
                name = user_names.get(uid, f"<@{uid}>")
                mentions.append(name)

        episode = self.next_episode_number()
        mention_line = " ".join(mentions) if mentions else ""
        lines = [
            f"**Episode #{episode}**",
            f"{total} messages, {unique_users} people were involved.",
            f"Most of it was about **{highlight}**.",
            random.choice([
                "Nobody learned anything.",
                "Peak server moment tbh.",
                "Certified bombo times material.",
                "The plot twists were unnecessary.",
            ]),
        ]
        if mention_line:
            lines.insert(1, mention_line)
        return "\n".join(lines)

    async def fetch_channel_messages(self, channel, *, limit: int = 30) -> list[dict]:
        messages: list[dict] = []
        async for message in channel.history(limit=limit, oldest_first=False):
            author = getattr(message, "author", None)
            if not author or getattr(author, "bot", False):
                continue
            content = getattr(message, "content", "") or ""
            if not content.strip():
                continue
            messages.append({
                "content": content,
                "user_id": str(getattr(author, "id", "unknown")),
                "username": getattr(author, "display_name", getattr(author, "name", "unknown")),
                "role": "user",
            })
        return list(reversed(messages))
