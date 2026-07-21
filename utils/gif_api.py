import aiohttp
import json
import random
import re
from typing import Any

from config import KLIPY_KEY


def _simplify_query(query: str) -> str:
    simplified = re.sub(r"[^a-z0-9 ]", " ", query.lower()).strip()
    parts = [part for part in simplified.split() if len(part) > 2]
    if not parts:
        return simplified
    return parts[0]


async def _fetch_first_gif(query: str) -> str | None:
    if not KLIPY_KEY or not query:
        print("=== KLIPY REQUEST === Missing Klipy key or query")
        return None

    url = "https://api.klipy.com/v2/search"
    params = {
        "q": query,
        "limit": 1,
        "key": KLIPY_KEY,
    }

    print("=== KLIPY REQUEST ===")
    print("Request URL:", url)
    print("Query parameters:", {"q": query, "limit": 1, "key": "<REDACTED>"})

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as response:
                raw_text = await response.text()
                print("=== KLIPY RESPONSE ===")
                print("Status:", response.status)
                print("Raw body:", raw_text[:2000])

                if response.status != 200:
                    print("=== KLIPY RESPONSE === Non-200 status returned")
                    return None

                try:
                    data = json.loads(raw_text)
                except json.JSONDecodeError as exc:
                    print("=== KLIPY RESPONSE === Failed to parse JSON:", exc)
                    return None

                results = data.get("results") or []
                if isinstance(results, dict):
                    results = [results]

                print("=== KLIPY RESPONSE === Number of results:", len(results))
                if not results:
                    print("=== KLIPY RESPONSE === No results found")
                    return None

                first_item = results[0]
                if not isinstance(first_item, dict):
                    print("=== KLIPY RESPONSE === First result is not an object")
                    return None

                media_formats = first_item.get("media_formats")
                if not isinstance(media_formats, dict):
                    print("=== KLIPY RESPONSE === Missing media_formats in first result")
                    return None

                gif_url = None
                if isinstance(media_formats.get("gif"), dict):
                    gif_url = media_formats["gif"].get("url")
                if not gif_url and isinstance(media_formats.get("mediumgif"), dict):
                    gif_url = media_formats["mediumgif"].get("url")

                if not gif_url:
                    print("=== KLIPY RESPONSE === No gif or mediumgif URL in first result")
                    return None

                print("=== KLIPY RESPONSE === Chosen GIF URL:", gif_url)
                return gif_url
    except Exception as exc:
        print("=== KLIPY REQUEST === Exception while fetching GIF:", exc)
        return None


async def fetch_gif(query: str) -> str | None:
    result = await _fetch_first_gif(query)
    if result:
        return result

    fallback_query = _simplify_query(query)
    if fallback_query and fallback_query != query:
        print("=== KLIPY REQUEST === No results on first query, retrying with simpler query:", fallback_query)
        return await _fetch_first_gif(fallback_query)

    return None
