"""AniList GraphQL source — fetch character images via AniList API.

Provides clean profile images as a fallback or alternative to Fandom wiki.
AniList images are typically high-quality renders suitable for bg removal.
"""

from __future__ import annotations

from typing import Any
from typing import cast

import httpx

_API_URL = "https://graphql.anilist.co"
_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "VidForge/0.1 (github.com/h4ksclaw/vidforge)",
}

# GraphQL query to search for a character by name and get their image
_CHARACTER_QUERY = """\
query ($search: String) {
  Character(search: $search) {
    name { full }
    image { large }
  }
}
"""

# GraphQL query to search multiple characters and get images
_CHARACTERS_QUERY = """\
query ($search: String, $page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    characters(search: $search, sort: FAVOURITES_DESC) {
      name { full }
      image { large }
      favourites
    }
  }
}
"""


def _graphql(query: str, variables: dict[str, object]) -> dict[str, Any] | None:
    """Execute a GraphQL query against AniList."""
    try:
        with httpx.Client(timeout=15, headers=_HEADERS) as client:
            resp = client.post(_API_URL, json={"query": query, "variables": variables})
            resp.raise_for_status()
            data = cast(dict[str, Any], resp.json())
            if "errors" in data:
                return None
            return data
    except (httpx.HTTPError, OSError):
        return None


def find_character_image(name: str, show: str = "") -> str | None:
    """Find a character image URL via AniList.

    Uses the exact character search which returns the best match.
    Returns the URL of the large character image, or None.
    """
    data = _graphql(_CHARACTER_QUERY, {"search": name})
    if not data:
        return None

    char = data.get("data", {}).get("Character")
    if not char:
        return None

    return cast(str | None, char.get("image", {}).get("large"))


def search_character_images(name: str, max_results: int = 5) -> list[str]:
    """Search for character images via AniList (returns multiple results).

    Useful when exact match fails — returns images sorted by popularity.
    """
    urls: list[str] = []
    for page in range(1, (max_results // 5) + 2):
        data = _graphql(_CHARACTERS_QUERY, {"search": name, "page": page, "perPage": 5})
        if not data:
            break

        chars = data.get("data", {}).get("Page", {}).get("characters") or []
        if not chars:
            break

        for char in chars:
            img = char.get("image", {}).get("large")
            if img:
                urls.append(img)

        if len(chars) < 5:
            break

        if len(urls) >= max_results:
            break

    return urls[:max_results]
