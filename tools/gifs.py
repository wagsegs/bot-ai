"""GIF search via Klipy."""

import json
import re

import aiohttp

from config import KLIPY_KEY


def _simplify_query(query: str) -> str:
    simplified = re.sub(r"[^a-z0-9 ]", " ", query.lower()).strip()
    parts = [part for part in simplified.split() if len(part) > 2]
    return parts[0] if parts else simplified


async def _fetch_first_gif(query: str) -> str | None:
    if not KLIPY_KEY or not query:
        return None
    url = "https://api.klipy.com/v2/search"
    params = {"q": query, "limit": 1, "key": KLIPY_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as response:
                if response.status != 200:
                    return None
                data = json.loads(await response.text())
                results = data.get("results") or []
                if isinstance(results, dict):
                    results = [results]
                if not results:
                    return None
                first_item = results[0]
                media_formats = first_item.get("media_formats") if isinstance(first_item, dict) else None
                if not isinstance(media_formats, dict):
                    return None
                gif_url = None
                if isinstance(media_formats.get("gif"), dict):
                    gif_url = media_formats["gif"].get("url")
                if not gif_url and isinstance(media_formats.get("mediumgif"), dict):
                    gif_url = media_formats["mediumgif"].get("url")
                return gif_url
    except Exception:
        return None


async def fetch_gif(query: str) -> str | None:
    result = await _fetch_first_gif(query)
    if result:
        return result
    fallback = _simplify_query(query)
    if fallback and fallback != query:
        return await _fetch_first_gif(fallback)
    return None
