import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiohttp
from dotenv import load_dotenv

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")


def _get_youtube_api_key() -> str:
    return os.getenv("YOUTUBE_API_KEY", YOUTUBE_API_KEY) or ""

VIDEO_TRIGGER_PHRASES = (
    "pull up",
    "show me",
    "find me",
    "send me",
    "send the link",
    "lemme see",
    "let me see",
    "play the video",
    "open the video",
    "video of",
    "clip of",
    "watch",
    "another video",
    "another one",
    "show another",
    "pull up another",
    "can you show it",
    "let me see it",
    "got another",
    "more videos",
)

FOLLOW_UP_PHRASES = {
    "another one",
    "another video",
    "another",
    "show another",
    "pull up another",
    "one more",
    "again",
    "it",
    "that",
    "him",
    "her",
    "those",
    "more",
    "again please",
    "again pls",
}

VIDEO_OPENERS = {
    "default": [
        "oh that one? gotchu",
        "hold up, here's the next hit",
        "say less, here's another",
        "watch this",
        "one sec, pulling it up",
    ],
    "jamaican": [
        "irie, lemme show yuh one more",
        "ya mon, next clip comin' through",
        "seen, dis one hot",
        "big up, check dis one",
    ],
    "saul": [
        "Your honor, I'd like to submit Exhibit A.",
        "Evidence has been located.",
        "I've got exactly what the prosecution ordered.",
        "Ladies and gentlemen, I present the next exhibit.",
    ],
    "uwu": [
        "omg yes, here's another one uwu",
        "hehe, i found a cute one for you",
        "one more for you, okay?",
    ],
    "chaotic": [
        "hold my drink, this one slaps",
        "buckle up, another one incoming",
        "next clip, chaos edition",
    ],
}

UNSAFE_TERMS = [
    "porn",
    "sex",
    "nude",
    "nudity",
    "explicit",
    "fetish",
    "gore",
    "graphic violence",
    "violence",
    "execution",
    "self-harm",
    "suicide",
    "kill",
    "murder",
    "crime",
    "drug",
    "drugs",
    "terror",
    "terrorism",
    "abuse",
    "hate",
    "harass",
    "harassment",
]

RECENT_TERMS = {"latest", "today", "new", "recent", "fresh", "upload"}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _looks_like_video_request(text: str) -> bool:
    if not text:
        return False
    lowered = _normalize_text(text)
    if any(phrase in lowered for phrase in VIDEO_TRIGGER_PHRASES):
        return True
    if re.search(r"\b(?:show|find|send|pull up|play|open|watch|let me see|lemme see)\b", lowered) and re.search(r"\b(?:video|clip|link)\b", lowered):
        return True
    if re.search(r"\b(?:another|more)\b", lowered) and re.search(r"\b(?:video|clip|one)\b", lowered):
        return True
    if lowered.endswith(" video") or " video " in lowered:
        return True
    return False


def _is_follow_up_request(text: str) -> bool:
    if not text:
        return False
    lowered = _normalize_text(text)
    return lowered in FOLLOW_UP_PHRASES or any(lowered.startswith(phrase + "") for phrase in FOLLOW_UP_PHRASES)


def _extract_search_query(text: str) -> str:
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
    if re.search(r"\b(?:video|clip|watch)\b", lowered):
        return lowered
    return f"{lowered} video".strip()


def _is_safe_request(text: str) -> bool:
    if not text:
        return True
    lowered = _normalize_text(text)
    for term in UNSAFE_TERMS:
        if term in lowered:
            return False
    return True


def _token_match_score(text: str, tokens: set[str]) -> int:
    lowered = _normalize_text(text)
    return sum(1 for token in tokens if token in lowered)


def _is_short_or_livestream(item: dict[str, Any]) -> bool:
    snippet = item.get("snippet", {})
    title = snippet.get("title", "").lower()
    description = snippet.get("description", "").lower()
    if "shorts" in title or "shorts" in description:
        return True
    if "live" in title or "live" in description or "stream" in title or "stream" in description:
        return True
    return False


def _is_official_channel(snippet: dict[str, Any]) -> bool:
    channel_title = snippet.get("channelTitle", "").lower()
    return any(keyword in channel_title for keyword in ("official", "vevo", "united", "nba", "fifa", "espn", "mlb", "nfl", "nhl", "pga", "mma", "f1", "uefa", "sony", "warner", "disney"))


def _published_score(item: dict[str, Any], prefer_recent: bool) -> float:
    snippet = item.get("snippet", {})
    published_at = snippet.get("publishedAt")
    if not published_at:
        return 0.0
    try:
        published_time = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if published_time.tzinfo is None:
            published_time = published_time.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age = now - published_time
        if age < timedelta(days=1):
            return 1.5 if prefer_recent else 0.5
        if age < timedelta(days=7):
            return 1.2 if prefer_recent else 0.3
        if age < timedelta(days=30):
            return 1.0
    except ValueError:
        return 0.0
    return 0.0


def _score_video_item(item: dict[str, Any], query_tokens: set[str], prefer_recent: bool) -> float:
    snippet = item.get("snippet", {})
    title = snippet.get("title", "")
    description = snippet.get("description", "")
    score = 0.0
    score += _token_match_score(title, query_tokens) * 4
    score += _token_match_score(description, query_tokens) * 1
    if _is_official_channel(snippet):
        score += 3.0
    if _is_short_or_livestream(item):
        score -= 2.5
    if prefer_recent:
        score += _published_score(item, prefer_recent=True)
    else:
        score += _published_score(item, prefer_recent=False)
    if title.lower().startswith(tuple(query_tokens)):
        score += 1.5
    if any(term in title.lower() for term in ("official", "full match", "highlights", "best", "goals", "highlights")):
        score += 0.8
    return score


async def search_video(query: str, previous_topic: str | None = None, recent_video_ids: Optional[list[str]] = None) -> Optional[str]:
    if not query and not previous_topic:
        print("=== YOUTUBE SEARCH === No videos returned: no query or previous topic was provided")
        return None
    api_key = _get_youtube_api_key()
    print("=== YOUTUBE SEARCH ===")
    print("API key loaded:", bool(api_key))
    if not api_key:
        print("=== YOUTUBE SEARCH === No videos returned: YouTube API key is not configured")
        return None
    if not _is_safe_request(query or previous_topic or ""):
        print("=== YOUTUBE SEARCH === No videos returned: request failed the safety filter")
        return None
    if _is_follow_up_request(query) and previous_topic:
        query = previous_topic
    search_query = _extract_search_query(query).strip() or (previous_topic or "").strip()
    print("Original request:", query)
    print("Extracted query:", search_query)
    if not search_query:
        print("=== YOUTUBE SEARCH === No videos returned: no searchable query could be extracted")
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
    print("=== YOUTUBE SEARCH ===")
    print("Request params:", params)
    print("API key sent:", bool(api_key))
    print("safeSearch:", params.get("safeSearch"))
    print("videoEmbeddable:", params.get("videoEmbeddable"))
    print("videoSyndicated:", params.get("videoSyndicated"))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://www.googleapis.com/youtube/v3/search", params=params, timeout=10) as response:
                response_text = await response.text()
                print("Status:", response.status)
                print("Response:", response_text[:1000])
                if response.status != 200:
                    print(f"=== YOUTUBE SEARCH === No videos returned: YouTube API responded with HTTP {response.status}")
                    return None
                payload = json.loads(response_text) if response_text else {}
                items = payload.get("items", []) or []
                print("Videos returned:", len(items))
                scored = []
                query_tokens = set(re.findall(r"[a-z0-9]+", search_query.lower()))
                recent_ids = {video_id for video_id in (recent_video_ids or []) if video_id}
                for item in items:
                    snippet = item.get("snippet", {})
                    title = snippet.get("title", "")
                    video_id = item.get("id", {}).get("videoId")
                    score = _score_video_item(item, query_tokens, prefer_recent)
                    print(title, score, video_id)
                    if not video_id:
                        continue
                    if video_id in recent_ids:
                        print("Skipping recently sent video:", video_id)
                        continue
                    scored.append((score, video_id))
                if not scored:
                    print("=== YOUTUBE SEARCH === No videos returned: every candidate was missing a video ID or was filtered out during ranking")
                    return None
                scored.sort(key=lambda pair: pair[0], reverse=True)
                best_video_id = scored[0][1]
                print("Chosen video:", best_video_id)
                return f"https://youtu.be/{best_video_id}"
    except Exception as exc:
        print(f"=== YOUTUBE SEARCH === No videos returned: error while calling YouTube API: {exc}")
        return None
