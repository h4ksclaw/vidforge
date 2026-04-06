"""Jikan (MyAnimeList) source — fetch character images via Jikan v4 API.

Jikan is an unofficial MyAnimeList REST API. Character images from MAL
are typically profile pictures — clean, centered renders ideal for bg removal.
Rate limited to 3 requests/second.
"""

from __future__ import annotations

import time
from typing import Any
from typing import cast

import httpx

_HEADERS = {"User-Agent": "VidForge/0.1 (github.com/h4ksclaw/vidforge)"}
_BASE_URL = "https://api.jikan.moe/v4"
_RATE_LIMIT = 1.0 / 3.0  # 3 req/s max


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Make a rate-limited Jikan API request."""
    url = f"{_BASE_URL}{path}"
    try:
        with httpx.Client(timeout=15, headers=_HEADERS) as client:
            resp = client.get(url, params=params)
            if resp.status_code == 429:
                time.sleep(2)
                resp = client.get(url, params=params)
            resp.raise_for_status()
            return cast(dict[str, Any], resp.json())
    except (httpx.HTTPError, OSError):
        return None


def find_character_image(name: str, show: str = "") -> str | None:
    """Find a character image URL via Jikan.

    Searches MAL characters by name, optionally with show context for accuracy.
    Returns the first result's large JPG/WebP image URL. Prefers WebP for quality.
    """
    q = f"{name} {show}".strip() if show else name
    data = _get("/characters", params={"q": q, "limit": 1})
    if not data:
        return None

    chars = data.get("data", [])
    if not chars:
        return None

    images = chars[0].get("images", {})
    webp = images.get("webp", {}).get("image_url")
    if webp:
        return cast(str | None, webp)

    jpg = images.get("jpg", {}).get("image_url")
    return cast(str | None, jpg)


def search_character_images(name: str, max_results: int = 5, show: str = "") -> list[str]:
    """Search for character images via Jikan (returns multiple results).

    Returns image URLs sorted by relevance (MAL's default ordering).
    """
    q = f"{name} {show}".strip() if show else name
    data = _get("/characters", params={"q": q, "limit": max_results})
    if not data:
        return []

    urls: list[str] = []
    for char in data.get("data", []):
        images = char.get("images", {})
        url = images.get("webp", {}).get("image_url") or images.get("jpg", {}).get("image_url")
        if url:
            urls.append(url)

    return urls
