"""YouTube trailer/video search."""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiohttp
from dotenv import load_dotenv

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

VIDEO_TRIGGER_PHRASES = (
    "play the video",
    "open the video",
    "video of",
    "clip of",
    "youtube video",
    "youtube",
    "music video",
    "song",
    "music",
    "watch this",
    "watch the",
    "trailer",
    "pull up",
)

# Action verbs that indicate video search intent
ACTION_VERBS = (
    "pull up",
    "show",
    "show me",
    "play",
    "put on",
    "find",
    "search",
    "open",
    "watch",
    "look for",
)

# Video content indicators
VIDEO_TARGETS = (
    "trailer",
    "movie",
    "song",
    "music",
    "video",
    "clip",
    "episode",
    "soundtrack",
    "live performance",
    "official video",
    "music video",
    "official audio",
)

# False positive patterns - these should NOT trigger video search
FALSE_POSITIVE_PATTERNS = (
    "show me your",
    "show me my",
    "show me his",
    "show me her",
    "show me their",
    "play with me",
    "play with",
    "watch this conversation",
    "watch the conversation",
    "find my",
    "find your",
    "find his",
    "find her",
    "find their",
    "open the server",
    "open server",
    "show me your code",
    "show me your opinion",
    "show me your memory",
    "show me your thoughts",
)

FOLLOW_UP_PHRASES = {
    "another one", "another video", "another", "show another",
    "pull up another", "one more", "again", "it", "that", "him", "her", "more",
}

VIDEO_OPENERS = [
    "oh that one? gotchu",
    "hold up, here's the next hit",
    "say less, here's another",
    "watch this",
    "one sec, pulling it up",
]

UNSAFE_TERMS = [
    "porn", "sex", "nude", "nudity", "explicit", "fetish", "gore",
    "graphic violence", "violence", "execution", "self-harm", "suicide",
    "kill", "murder", "crime", "drug", "drugs", "terror", "terrorism",
    "abuse", "hate", "harass", "harassment",
]

RECENT_TERMS = {"latest", "today", "new", "recent", "fresh", "upload"}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def looks_like_video_request(text: str) -> bool:
    if not text:
        return False
    lowered = _normalize_text(text)
    
    # First, check for false positive patterns
    for pattern in FALSE_POSITIVE_PATTERNS:
        if pattern in lowered:
            return False
    
    # Check for action verb + video target combination (most natural)
    has_action_verb = any(verb in lowered for verb in ACTION_VERBS)
    has_video_target = any(target in lowered for target in VIDEO_TARGETS)
    
    if has_action_verb and has_video_target:
        return True
    
    # Check for legacy trigger phrases
    if any(phrase in lowered for phrase in VIDEO_TRIGGER_PHRASES):
        return True
    
    # More lenient: if there's an action verb with content that looks like a title
    if has_action_verb:
        # Check if there's meaningful content after the action verb
        words = lowered.split()
        # If there are enough words to be a title (at least 2-3 words after removing action verb)
        if len(words) >= 3:
            # Remove common action verbs from the start
            for verb in ACTION_VERBS:
                if lowered.startswith(verb):
                    remaining = lowered[len(verb):].strip()
                    # If remaining text has substance, it's likely a video request
                    if len(remaining.split()) >= 2:
                        return True
    
    # Check for explicit video keywords with action verbs
    if any(kw in lowered for kw in ("video", "youtube", "song", "music", "trailer")):
        if any(verb in lowered for verb in ACTION_VERBS):
            return True
    
    return False


def is_follow_up_request(text: str) -> bool:
    if not text:
        return False
    lowered = _normalize_text(text)
    return lowered in FOLLOW_UP_PHRASES or any(lowered.startswith(phrase) for phrase in FOLLOW_UP_PHRASES)


def extract_search_query(text: str) -> str:
    if not text:
        return ""
    lowered = _normalize_text(text)
    lowered = re.sub(r"^(?:bot\s+kun|kun|hey kun|yo kun)\b\s*", "", lowered)
    lowered = re.sub(r"^(?:hey|yo|please|pls|can you|could you|would you)\s+", "", lowered)
    for phrase in VIDEO_TRIGGER_PHRASES:
        if phrase in lowered:
            lowered = lowered.split(phrase, 1)[1]
            break
    lowered = _normalize_text(lowered)
    lowered = re.sub(r"^(?:a|an|the)\s+", "", lowered)
    if not lowered:
        return ""
    if re.search(r"\b(?:video|clip|watch|trailer)\b", lowered):
        return lowered
    return f"{lowered} video".strip()


def is_safe_request(text: str) -> bool:
    if not text:
        return True
    lowered = _normalize_text(text)
    return not any(term in lowered for term in UNSAFE_TERMS)


def _token_match_score(text: str, tokens: set[str]) -> int:
    return sum(1 for token in tokens if token in _normalize_text(text))


def _is_short_or_livestream(item: dict[str, Any]) -> bool:
    snippet = item.get("snippet", {})
    title = snippet.get("title", "").lower()
    description = snippet.get("description", "").lower()
    return "shorts" in title or "shorts" in description or "live" in title or "stream" in title


def _is_official_channel(snippet: dict[str, Any]) -> bool:
    channel_title = snippet.get("channelTitle", "").lower()
    keywords = ("official", "vevo", "united", "nba", "fifa", "espn", "sony", "warner", "disney")
    return any(kw in channel_title for kw in keywords)


def _published_score(item: dict[str, Any], prefer_recent: bool) -> float:
    snippet = item.get("snippet", {})
    published_at = snippet.get("publishedAt")
    if not published_at:
        return 0.0
    try:
        published_time = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if published_time.tzinfo is None:
            published_time = published_time.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - published_time
        if age < timedelta(days=1):
            return 1.5 if prefer_recent else 0.5
        if age < timedelta(days=7):
            return 1.2 if prefer_recent else 0.3
    except ValueError:
        return 0.0
    return 0.0


def _score_video_item(item: dict[str, Any], query_tokens: set[str], prefer_recent: bool) -> float:
    snippet = item.get("snippet", {})
    title = snippet.get("title", "")
    description = snippet.get("description", "")
    score = _token_match_score(title, query_tokens) * 4 + _token_match_score(description, query_tokens)
    if _is_official_channel(snippet):
        score += 3.0
    if _is_short_or_livestream(item):
        score -= 2.5
    score += _published_score(item, prefer_recent)
    return score


async def search_video(
    query: str,
    previous_topic: str | None = None,
    recent_video_ids: Optional[list[str]] = None,
) -> Optional[str]:
    api_key = os.getenv("YOUTUBE_API_KEY", YOUTUBE_API_KEY) or ""
    if not query and not previous_topic:
        return None
    if not api_key:
        return None
    if not is_safe_request(query or previous_topic or ""):
        return None
    if is_follow_up_request(query) and previous_topic:
        query = previous_topic
    search_query = extract_search_query(query).strip() or (previous_topic or "").strip()
    if not search_query:
        return None
    prefer_recent = any(term in _normalize_text(query) for term in RECENT_TERMS)
    params = {
        "part": "snippet",
        "q": search_query,
        "type": "video",
        "maxResults": 5,
        "videoEmbeddable": "true",
        "videoSyndicated": "true",
        "safeSearch": "strict",
        "key": api_key,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://www.googleapis.com/youtube/v3/search", params=params, timeout=10
            ) as response:
                if response.status != 200:
                    return None
                payload = json.loads(await response.text() or "{}")
                items = payload.get("items", []) or []
                query_tokens = set(re.findall(r"[a-z0-9]+", search_query.lower()))
                recent_ids = {vid for vid in (recent_video_ids or []) if vid}
                scored = []
                for item in items:
                    video_id = item.get("id", {}).get("videoId")
                    if not video_id or video_id in recent_ids:
                        continue
                    scored.append((_score_video_item(item, query_tokens, prefer_recent), video_id))
                if not scored:
                    return None
                scored.sort(key=lambda pair: pair[0], reverse=True)
                return f"https://youtu.be/{scored[0][1]}"
    except Exception:
        return None


# Backward-compatible aliases for tests
_looks_like_video_request = looks_like_video_request
_is_follow_up_request = is_follow_up_request
_extract_search_query = extract_search_query
_is_safe_request = is_safe_request
_published_score = _published_score
