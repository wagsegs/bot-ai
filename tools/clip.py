"""Clip episode summary generation for #bombo-times."""

import json
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

CLIP_SUMMARY_CHANNEL_ID = 1526652930604662955
EPISODE_FILE = Path(__file__).parent.parent / "data" / "bombo_episode.json"


class ClipGenerator:
    _recent_gif_queries: list[str] = []

    def __init__(self) -> None:
        self._last_clip_time: dict[int, datetime] = {}
        # Ensure data directory exists
        EPISODE_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _load_episode_number(self) -> int:
        """Load the persistent episode number from file."""
        if EPISODE_FILE.exists():
            try:
                with open(EPISODE_FILE, "r") as f:
                    data = json.load(f)
                    return data.get("episode_number", 0)
            except (json.JSONDecodeError, IOError):
                pass
        return 0

    def _save_episode_number(self, episode_number: int) -> None:
        """Save the episode number to file."""
        try:
            with open(EPISODE_FILE, "w") as f:
                json.dump({"episode_number": episode_number}, f)
        except IOError:
            pass

    def next_episode_number(self) -> int:
        """Get the next episode number, persisting across restarts."""
        current = self._load_episode_number()
        next_num = current + 1
        self._save_episode_number(next_num)
        return next_num

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

    async def generate_ai_summary(self, prompt: str, provider, episode_number: int) -> tuple[str, str]:
        """Generate a funny recap and GIF query using the AI provider.
        
        Returns:
            tuple: (summary_text, gif_query)
        """
        # Random narration styles
        narration_styles = [
            "It all started when...",
            "Today's server drama featured...",
            "Nobody expected this conversation to end the way it did...",
            "In today's episode...",
            "The server collectively lost brain cells when...",
            "What began as a normal chat quickly turned into...",
            "The timeline of events is as follows...",
            "Witnesses reported the following sequence...",
        ]

        # Random ending styles
        ending_styles = [
            "Director's Note: Roll credits.",
            "Director's Note: Nobody learned anything today.",
            "Director's Note: See you next episode.",
            "Director's Note: Another day, another Discord moment.",
            "Director's Note: The plot thickens.",
            "Director's Note: Some lessons were learned. Probably.",
            "Director's Note: The server survived... somehow.",
            "Director's Note: Fade to black.",
            "Director's Note: Cue the ending theme.",
        ]

        selected_narration = random.choice(narration_styles)
        selected_ending = random.choice(ending_styles)

        system_prompt = f"""Generate a newspaper-style recap for Bombo Times, a recurring comedy series based on real Discord conversations.

Your job is to turn the actual last ~30 messages into an entertaining episode, almost like recapping a sitcom.

Rules:
- Read ONLY the provided messages
- Never invent events, conversations, or jokes that didn't happen
- Focus on the funniest or most memorable 2-3 moments
- Write naturally, like someone watching the chaos unfold
- Keep the tone witty, observational, and playful
- Do NOT sound like ChatGPT or a news reporter
- Keep it around 60-90 words (short and punchy)
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
S01EXXX
"Episode Title"

Where:
- Season is always 1
- Episode number is supplied by the application (use exactly that format)
- Create a SHORT clickbait-style title (2-6 words) based on the funniest moment
- Good examples: "The Meme Disaster", "The Flashbang Incident", "Bro Started Tweaking", "Average Discord Moment", "The DM Allegations", "Nobody Saw This Coming", "The Identity Crisis Arc", "Certified Discord Chaos", "The Awkward Hello", "The Great Debate"
- Avoid generic titles like "Diego's Confusion" or "Chase Gets Weird"

Writing Style:
Start your summary with: {selected_narration}
Write like someone who's been watching the Discord server unfold from the sidelines.
Don't explain what happened. Retell it.
Don't describe every message. Instead, build one small story around the funniest moments.
Assume the reader was there and is reliving the moment.
The humor should come from what actually happened—not from random jokes or AI filler.

Ending:
Finish with exactly this line:
{selected_ending}

Reference something that actually happened in the conversation whenever possible.

GIF Query:
Generate ONE highly specific GIF search query (3-6 words) that matches the funniest moment.
DO NOT use generic terms like: funny, meme, cat, reaction, lol, hilarious.
Instead use specific reactions like: confused cat, awkward wave, flashbang reaction, brain loading, side eye, guy staring in disbelief, popcorn reaction, nervous laugh, caught lying, dramatic exit, keyboard smashing, screaming internally, villain laugh, anime betrayal, bro what face.
The GIF should feel unique to this specific moment.

Response Format:
Return ONLY valid JSON with two keys:
- "summary": the Bombo Times episode text (including header and ending)
- "gif_query": a specific 3-6 word search term for a GIF"""
        
        # Add episode number to the prompt
        episode_header = f"Episode Number: S01E{episode_number:03d}\n\n"
        user_prompt = episode_header + prompt
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        try:
            result = await provider.chat(messages)
            reply = result.get("reply", "")
            
            # Try to parse as JSON
            try:
                parsed = json.loads(reply)
                summary = parsed.get("summary", reply)
                gif_query = parsed.get("gif_query", "funny")
            except (json.JSONDecodeError, TypeError):
                # Fallback: use entire reply as summary, default gif query
                summary = reply
                gif_query = "funny"
            
            # Remove any Discord mentions from summary
            summary = re.sub(r"<@!?\d+>", "", summary)
            summary = re.sub(r"<@&\d+>", "", summary)
            
            # Track recent GIF queries to avoid repetition
            if gif_query in self._recent_gif_queries:
                # If we've used this query recently, try to vary it slightly
                variations = ["reaction", "moment", "face", "expression"]
                if not any(v in gif_query.lower() for v in variations):
                    gif_query = f"{gif_query} reaction"
            
            self._recent_gif_queries.append(gif_query)
            if len(self._recent_gif_queries) > 10:
                self._recent_gif_queries.pop(0)
            
            return summary.strip(), gif_query.strip()
        except Exception:
            return "The episode was too chaotic to summarize. Even the AI gave up.", "confused"

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
