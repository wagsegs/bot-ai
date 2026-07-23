"""Detect message intents and triggers."""

import re
from dataclasses import dataclass
from enum import Enum, auto


class Intent(Enum):
    ADMIN_COMMAND = auto()
    PUBLIC_COMMAND = auto()
    BOT_MENTION = auto()
    BOT_REPLY = auto()
    BOT_NAME = auto()
    CONTINUATION = auto()
    MEME = auto()
    VIDEO = auto()
    ROAST = auto()
    NATURAL = auto()
    IGNORE = auto()


@dataclass
class DetectedIntent:
    intent: Intent
    prompt: str = ""
    command: str = ""


class IntentDetector:
    def __init__(self, bot_name_pattern: re.Pattern) -> None:
        self.bot_name_pattern = bot_name_pattern

    def is_bot_mention(self, message, bot_user_id: int) -> bool:
        return any(m.id == bot_user_id for m in message.mentions)

    def is_reply_to_bot(self, message, bot_user_id: int) -> bool:
        if not message.reference or not message.reference.resolved:
            return False
        ref = message.reference.resolved
        return hasattr(ref, "author") and ref.author.id == bot_user_id

    def is_bot_name_mentioned(self, content: str) -> bool:
        return bool(content and self.bot_name_pattern.search(content))

    def strip_bot_name(self, text: str) -> str:
        return self.bot_name_pattern.sub("", text).strip()

    def detect(
        self,
        message,
        *,
        bot_user_id: int,
        meme_triggers: tuple[str, ...],
        video_check,
    ) -> DetectedIntent:
        content = (message.content or "").strip()
        if not content:
            return DetectedIntent(Intent.IGNORE)

        if content.startswith("~"):
            cmd = content.split()[0].lower()
            public = {"~botkun"}
            if cmd in public:
                return DetectedIntent(Intent.PUBLIC_COMMAND, command=cmd)
            return DetectedIntent(Intent.ADMIN_COMMAND, command=cmd, prompt=content)

        mention = self.is_bot_mention(message, bot_user_id)
        reply = self.is_reply_to_bot(message, bot_user_id)
        name = self.is_bot_name_mentioned(content)

        if mention or name:
            prompt = content
            if mention:
                prompt = re.sub(r"<@!?\d+>", "", prompt).strip()
            if name:
                prompt = self.strip_bot_name(prompt)
            if not prompt:
                prompt = "Say hello naturally."
            return DetectedIntent(Intent.BOT_MENTION if mention else Intent.BOT_NAME, prompt=prompt)

        if reply:
            prompt = content or "Continue the conversation naturally."
            return DetectedIntent(Intent.BOT_REPLY, prompt=prompt)

        if "roast me" in content.lower():
            return DetectedIntent(Intent.ROAST, prompt="Roast me playfully and harmlessly.")

        lowered = content.lower()
        if any(t in lowered for t in meme_triggers):
            return DetectedIntent(Intent.MEME, prompt=content)

        if video_check(content):
            return DetectedIntent(Intent.VIDEO, prompt=content)

        return DetectedIntent(Intent.CONTINUATION, prompt=content)
