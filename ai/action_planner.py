import ast
import json
import logging
import re
from typing import Any

logger = logging.getLogger("botkun.action_planner")

GENERIC_FALLBACKS = [
    "nah my brain lagged for a sec 💀",
    "brain lag",
    "hold up",
]


class ActionPlanner:
    """Parser first, regex fallback second, generic fallback third. Never leak JSON."""

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
            pass
        try:
            parsed = ast.literal_eval(candidate)
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, SyntaxError):
            return None
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
        # Regex fallback: extract "text" field
        text_match = re.search(r'"text"\s*:\s*"([^"]*(?:\\.[^"]*)*)"', text)
        if text_match:
            extracted = text_match.group(1).replace('\\"', '"').replace("\\n", "\n")
            logger.info("Extracted text via regex fallback")
            return {"text": extracted, "send_gif": False, "gif_query": ""}
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
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index
        return None

    def strip_json_from_text(self, text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", text, flags=re.S | re.I)
        metadata_pattern = re.compile(
            r'(?is)(?:^|[\r\n])\s*(?:"text"\s*:\s*".*?"\s*(?:,|\n)\s*"send_gif"\s*:\s*(?:true|false)\s*(?:,|\n)\s*"gif_query"\s*:\s*".*?"|'
            r'"text"\s*:\s*".*?"\s*(?:,|\n)\s*"gif_query"\s*:\s*".*?"\s*(?:,|\n)\s*"send_gif"\s*:\s*(?:true|false))'
        )
        cleaned = metadata_pattern.sub("", cleaned)
        start = cleaned.find("{")
        while start != -1:
            end = self._find_matching_brace(cleaned, start)
            if end is None:
                break
            snippet = cleaned[start : end + 1]
            if '"text"' in snippet or '"send_gif"' in snippet or '"gif_query"' in snippet:
                cleaned = cleaned[:start] + cleaned[end + 1 :]
                break
            start = cleaned.find("{", start + 1)
        return cleaned.strip()

    def looks_like_leaked_format(self, text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        if lowered in {"null", "undefined", "none"}:
            return True
        if re.fullmatch(r"[\[\]\{\}\s]+", lowered):
            return True
        if "```" in lowered:
            return True
        if re.search(r"</?[a-zA-Z][^>]*>", lowered):
            return True
        if re.search(r"\b(?:assistant|system|user)\s*:", lowered):
            return True
        if re.search(r"(?<![a-z])(?:text|send_gif|gif_query|search_youtube|send_meme)\s*:", lowered):
            return True
        if re.search(r"\[(?:text|send_gif|gif_query)\]:", lowered):
            return True
        # Detect raw JSON objects with our known keys
        if re.search(r'\{\s*"(?:text|send_gif|gif_query|search_youtube|send_meme)"\s*:', lowered):
            return True
        return False

    def _normalize_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"true", "yes", "1", "on"}
        return False

    def parse_response(self, raw_text: str) -> dict:
        """Returns dict with reply, gif_category, youtube_query, meme_topic, actions."""
        actions: list[str] = []
        extracted = self._find_json_object(raw_text)
        if isinstance(extracted, dict):
            text_value = extracted.get("text", "")
            if not isinstance(text_value, str):
                text_value = str(text_value) if text_value is not None else ""
            text_value = text_value.strip() or self.strip_json_from_text(raw_text)

            send_gif = self._normalize_bool(extracted.get("send_gif", False))
            gif_query = str(extracted.get("gif_query", "")).strip() if send_gif else ""

            search_youtube = self._normalize_bool(extracted.get("search_youtube", False))
            youtube_query = str(extracted.get("youtube_query", "")).strip() if search_youtube else ""

            send_meme = self._normalize_bool(extracted.get("send_meme", False))
            meme_topic = str(extracted.get("meme_topic", "")).strip() if send_meme else ""

            if send_gif and gif_query:
                actions.append("gif")
            if search_youtube and youtube_query:
                actions.append("youtube")
            if send_meme:
                actions.append("meme")

            return {
                "reply": text_value,
                "gif_category": gif_query if send_gif and gif_query else None,
                "youtube_query": youtube_query if search_youtube else None,
                "meme_topic": meme_topic if send_meme else None,
                "actions": actions,
            }

        cleaned = self.strip_json_from_text(raw_text)
        if cleaned and not self.looks_like_leaked_format(cleaned):
            return {"reply": cleaned, "gif_category": None, "youtube_query": None, "meme_topic": None, "actions": []}

        return {"reply": "", "gif_category": None, "youtube_query": None, "meme_topic": None, "actions": []}

    def validate_output_text(self, text: str | None, fallback: str | None = None) -> str:
        fallback_message = fallback or GENERIC_FALLBACKS[0]
        if not text or not isinstance(text, str):
            return fallback_message
        raw = text.strip()
        if not raw:
            return fallback_message
        
        # First try to parse as JSON response
        parsed = self.parse_response(raw)
        if parsed.get("reply") and not self.looks_like_leaked_format(parsed["reply"]):
            return parsed["reply"]
        
        # If parsing failed or result still looks leaked, check original text
        if self.looks_like_leaked_format(raw):
            return fallback_message
        return raw

    def strip_youtube_claims_without_action(self, reply: str, actions: list[str]) -> str:
        """Remove hallucinated 'I searched YouTube' claims if youtube wasn't executed."""
        if "youtube" in actions:
            return reply
        patterns = [
            r"(?i)\b(i (?:searched|looked up|found).*youtube.*)",
            r"(?i)\b(pulled (?:it|that) up (?:on|from) youtube.*)",
        ]
        cleaned = reply
        for pattern in patterns:
            cleaned = re.sub(pattern, "", cleaned).strip()
        return cleaned or reply
