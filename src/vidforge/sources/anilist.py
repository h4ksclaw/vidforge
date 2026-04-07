"""AniList GraphQL source — fetch character images via AniList API.

Provides clean profile images as a fallback or alternative to Fandom wiki.
AniList images are typically high-quality renders suitable for bg removal.

Key feature: show-scoped character search — all queries are filtered to
a specific anime, eliminating wrong-show results (e.g. "Kaworu" from a
different anime).
"""

from __future__ import annotations

import logging
import time
from typing import Any
from typing import cast

import httpx

logger = logging.getLogger(__name__)

_API_URL = "https://graphql.anilist.co"
_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "VidForge/0.1 (github.com/h4ksclaw/vidforge)",
}

# Simple in-memory cache: show_name -> media_id
_show_id_cache: dict[str, int] = {}

# GraphQL: look up a show by name, return its media ID
_MEDIA_SEARCH_QUERY = """\
query ($search: String, $type: MediaType) {
  Media(search: $search, type: $type, sort: SEARCH_MATCH) {
    id
    title { english romaji }
  }
}
"""

# GraphQL: get all characters for a show by media ID
_MEDIA_CHARACTERS_QUERY = """\
query ($id: Int, $page: Int, $perPage: Int) {
  Media(id: $id) {
    title { english }
    characters(page: $page, perPage: $perPage, sort: FAVOURITES_DESC) {
      edges {
        node {
          name { full }
          image { large }
          favourites
        }
      }
      pageInfo { hasNextPage total }
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
                logger.debug("AniList error: %s", data["errors"])
                return None
            return data
    except (httpx.HTTPError, OSError):
        return None


def _resolve_show_id(show_name: str, search_term: str = "") -> int | None:
    """Look up an AniList media ID for a show name.

    Args:
        show_name: The show name (used as cache key).
        search_term: Optional alternate search string if the show name
                     doesn't match well on AniList (e.g. "Neon Genesis Evangelion"
                     instead of "Evangelion").

    Returns:
        AniList media ID, or None if not found.
    """
    # Check cache first
    if show_name in _show_id_cache:
        return _show_id_cache[show_name]

    term = search_term or show_name
    data = _graphql(_MEDIA_SEARCH_QUERY, {"search": term, "type": "ANIME"})
    if not data:
        return None

    media = data.get("data", {}).get("Media")
    if not media:
        return None

    media_id = cast(int, media["id"])
    title = media.get("title", {})
    logger.info(
        "AniList: resolved '%s' -> media id=%d (%s)",
        show_name,
        media_id,
        title.get("english") or title.get("romaji"),
    )
    _show_id_cache[show_name] = media_id
    return media_id


def _fetch_show_characters(media_id: int, max_chars: int = 50) -> list[dict[str, Any]]:
    """Fetch all characters for a show from AniList.

    Returns list of dicts with keys: name, image_url, favourites.
    """
    chars: list[dict[str, Any]] = []
    page = 1
    per_page = 25

    while len(chars) < max_chars:
        data = _graphql(
            _MEDIA_CHARACTERS_QUERY,
            {"id": media_id, "page": page, "perPage": per_page},
        )
        if not data:
            break

        edges = data.get("data", {}).get("Media", {}).get("characters", {}).get("edges") or []
        if not edges:
            break

        for edge in edges:
            node = edge.get("node", {})
            name = node.get("name", {}).get("full", "")
            img = node.get("image", {}).get("large", "")
            if name and img:
                chars.append(
                    {
                        "name": name,
                        "image_url": img,
                        "favourites": node.get("favourites", 0),
                    }
                )

        page_info = (
            data.get("data", {}).get("Media", {}).get("characters", {}).get("pageInfo") or {}
        )
        if not page_info.get("hasNextPage"):
            break
        page += 1
        time.sleep(0.3)  # be gentle

    return chars[:max_chars]


def _name_matches(query: str, target: str) -> bool:
    """Check if a character name query matches a full name.

    Handles: "Kaworu" matching "Kaworu Nagisa", "Asuka" matching
    "Asuka Langley Souryuu", etc. Case-insensitive substring match.
    """
    q = query.lower().strip()
    t = target.lower().strip()
    if q in t:
        return True
    # Also check reversed (for names like "Nagisa Kaworu")
    parts = q.split()
    if len(parts) > 1:
        return q in t
    return False


def find_character_image(
    name: str,
    show: str = "",
    show_search_term: str = "",
) -> str | None:
    """Find a character image URL via AniList, scoped to a specific show.

    Args:
        name: Character name to search for.
        show: Show name for scoping (e.g. "Evangelion").
        show_search_term: Alternate search term for AniList if the show name
                          doesn't match well (e.g. "Neon Genesis Evangelion").

    Returns:
        URL of the character's image, or None if not found.
    """
    if not show:
        return None

    media_id = _resolve_show_id(show, show_search_term)
    if not media_id:
        return None

    chars = _fetch_show_characters(media_id)
    if not chars:
        return None

    # Find best match by name (most favourites wins if multiple matches)
    matches = [c for c in chars if _name_matches(name, c["name"])]
    if not matches:
        logger.debug("AniList: no match for '%s' in show '%s'", name, show)
        return None

    matches.sort(key=lambda c: c["favourites"], reverse=True)
    best = matches[0]
    logger.info("AniList: '%s' -> '%s' (%d favs)", name, best["name"], best["favourites"])
    return cast(str, best["image_url"])


def search_character_images(
    name: str,
    max_results: int = 5,
    show: str = "",
    show_search_term: str = "",
) -> list[str]:
    """Search for character images via AniList, scoped to a specific show.

    Returns image URLs for matching characters sorted by popularity (favourites).
    Only returns images from the specified show — no cross-show contamination.

    Args:
        name: Character name to search for.
        max_results: Maximum number of image URLs to return.
        show: Show name for scoping.
        show_search_term: Alternate search term for AniList.

    Returns:
        List of image URLs.
    """
    if not show:
        return []

    media_id = _resolve_show_id(show, show_search_term)
    if not media_id:
        return []

    chars = _fetch_show_characters(media_id)
    if not chars:
        return []

    matches = [c for c in chars if _name_matches(name, c["name"])]
    matches.sort(key=lambda c: c["favourites"], reverse=True)

    urls = [c["image_url"] for c in matches[:max_results]]
    logger.info(
        "AniList search '%s' in '%s': %d matches, returning %d",
        name,
        show,
        len(matches),
        len(urls),
    )
    return urls
