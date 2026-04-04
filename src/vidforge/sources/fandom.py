"""Fandom wiki API source — fetch character data from Fandom wikis."""

import re
import time
from typing import Any
from typing import cast
from urllib.parse import unquote

import httpx

from vidforge.models import Item

HEADERS = {"User-Agent": "VidForge/0.1 (github.com/h4ksclaw/vidforge)"}

# Keywords that indicate non-character pages
SKIP_WORDS = [
    "voice actor",
    "seiyū",
    "seiyuu",
    "voice",
    "actor",
    "actress",
    "episode",
    "chapter",
    "saga",
    "arc",
    "volume",
    "list of",
    "timeline",
    "universe",
    "world",
    "guide",
    "encyclopedia",
    "technique",
    "move",
    "transformation",
    "power",
    "ability",
    "race",
    "species",
    "class",
    "type",
    "category",
    "weapon",
    "vehicle",
    "ship",
    "robot",
    "mecha",
    "opening",
    "ending",
    "theme",
    "song",
    "soundtrack",
    "location",
    "planet",
    "place",
    "city",
    "island",
    "region",
    "movie",
    "film",
    "ova",
    "special",
    "trailer",
    "promo",
    "databook",
    "card game",
    "tcg",
    "nakahara",
    "yonaga",
    "ogiso",
    "tsuda",
    "kaji",
    "sawashiro",
    "park",
    "romi",
    "yūki",
    "aoi",
    "saito",
    "tanaka",
]

# Keywords that indicate bad image filenames (action scenes, not standing poses)
BAD_IMAGE_KEYWORDS = [
    "logo",
    "icon",
    "symbol",
    "flag",
    "map",
    "gif",
    "vs",
    "fight",
    "battle",
    "attack",
    "saga",
    "arc",
    "death",
    "kill",
    "manga panel",
    "chapter",
    "episode screenshot",
    "card",
    "stamp",
    "chibi",
    "sprite",
    "shreds",
    "beats",
    "cuts",
    "shoots",
    "tortures",
    "slashes",
    "punches",
    "kicks",
    "assaults",
    "stabs",
    "crushes",
    "destroys",
    "murders",
    "interrogates",
    "yells at",
    "threatens",
    "holds",
    "popularity poll",
    "overlay",
]


def parse_height(raw: str) -> int | None:
    """Extract height in cm from a raw infobox value."""
    if not raw:
        return None
    raw = re.sub(r"<ref[^>]*>.*?</ref>", "", raw, flags=re.DOTALL)
    raw = re.sub(r"\{\{[^}]*\}\}", "", raw)
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = raw.strip(' "\x27\n')
    if not raw or raw.lower() in ("unknown", "?", "none", "n/a", "-"):
        return None

    m = re.search(r"([\d.]+)\s*cm", raw, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        if 30 <= val <= 3000:
            return int(val)

    m = re.search(r"([\d.]+)\s*m\b(?!m|onster|ale|echa)", raw, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        if 0.5 <= val <= 30.0:
            return int(val * 100)

    m = re.search(r"(\d+)[\x27'](\d{1,2})[\x22\"]?", raw)
    if m:
        return int((int(m.group(1)) * 12 + int(m.group(2))) * 2.54)

    m = re.search(r"(\d+)\s*feet\s*(\d{1,2})\s*inches?", raw, re.IGNORECASE)
    if m:
        return int((int(m.group(1)) * 12 + int(m.group(2))) * 2.54)

    m = re.search(r"^([\d.]+)$", raw)
    if m:
        val = float(m.group(1))
        if 0.5 <= val <= 3.0:
            return int(val * 100)
        if 50 <= val <= 300:
            return int(val)

    return None


def _api(wiki: str, params: dict[str, Any]) -> dict[str, Any]:
    """Make a Fandom API request."""
    params["format"] = "json"
    url = f"https://{wiki}/api.php"
    with httpx.Client(timeout=15, headers=HEADERS) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return cast(dict[str, Any], resp.json())


def get_height(wiki: str, page: str) -> int | None:
    """Parse height from a character's wiki page."""
    try:
        data = _api(wiki, {"action": "parse", "page": page, "prop": "wikitext"})
        text = data["parse"]["wikitext"]["*"]
        match = re.search(r"\|\s*height\s*=\s*(.+?)(?:\||\n|\})", text, re.IGNORECASE)
        if match:
            return parse_height(match.group(1).strip())
    except (httpx.HTTPError, KeyError):
        pass
    return None


def get_page_images(wiki: str, page: str) -> list[str]:
    """Get image filenames from a wiki page."""
    try:
        data = _api(
            wiki,
            {
                "action": "parse",
                "page": page,
                "prop": "images",
                "imageslimit": 200,
            },
        )
        return cast(list[str], data.get("parse", {}).get("images", []))
    except (httpx.HTTPError, KeyError):
        return []


def get_image_url(wiki: str, filename: str) -> str | None:
    """Get full URL for a wiki image."""
    if not filename.startswith("File:"):
        filename = f"File:{filename}"
    try:
        data = _api(
            wiki,
            {
                "action": "query",
                "titles": filename,
                "prop": "imageinfo",
                "iiprop": "url|size",
            },
        )
        for page_data in data["query"]["pages"].values():
            if "imageinfo" in page_data:
                return cast(str, page_data["imageinfo"][0]["url"])
    except (httpx.HTTPError, KeyError):
        pass
    return None


def discover_characters(wiki: str, max_pages: int = 100) -> list[str]:
    """Find character pages that have height data using insource search."""

    pages: list[str] = []
    offset = 0

    while len(pages) < max_pages:
        try:
            data = _api(
                wiki,
                {
                    "action": "query",
                    "list": "search",
                    "srsearch": 'insource:"|height" insource:"cm"',
                    "srnamespace": 0,
                    "srlimit": 50,
                    "sroffset": offset,
                },
            )
        except (httpx.HTTPError, KeyError):
            break

        results = data.get("query", {}).get("search", [])
        if not results:
            break

        for r in results:
            title: str = r["title"]
            if len(title) > 40:
                continue
            if any(sw in title.lower() for sw in SKIP_WORDS):
                continue
            pages.append(title)

        if len(results) < 50:
            break
        offset += 50
        time.sleep(0.3)

    return list(dict.fromkeys(pages))[:max_pages]


def fetch_characters(
    wiki: str,
    character_pages: list[str] | None = None,
    max_chars: int = 15,
) -> list[Item]:
    """Fetch characters with heights from a Fandom wiki.

    Args:
        wiki: Fandom wiki domain (e.g. "dragonball.fandom.com")
        character_pages: Optional explicit list of wiki page names.
            If None, discovers characters via search.
        max_chars: Maximum characters to return.

    Returns:
        List of Items sorted by height (ascending).
    """
    if character_pages is None:
        candidates = discover_characters(wiki, max_pages=max_chars * 5)
    else:
        candidates = character_pages

    # Batch height fetching (10 at a time via API)
    chars: list[Item] = []
    for page in candidates:
        h = get_height(wiki, page)
        if h is not None:
            chars.append(Item(name=page, value=h))
        time.sleep(0.15)

    chars.sort(key=lambda c: c.value)
    return chars[:max_chars]


def find_best_image(wiki: str, character_name: str) -> str | None:
    """Find the best image URL for a character.

    Two-pass approach:
    1. Score all images by filename keywords (profile/render/infobox = high)
    2. If no high-score candidates, fall back to any image containing the character name
    3. Filter by BAD_IMAGE_KEYWORDS (action scenes, non-character images)

    Returns the URL of the highest-scoring image, or None.
    """

    images = get_page_images(wiki, character_name)
    name_parts = character_name.lower().replace("_", " ").split()

    candidates: list[tuple[float, str, str]] = []  # (score, fname, url)

    for fname in images:
        fname_lower = fname.lower().replace("_", " ").replace("-", " ")
        has_name = any(p in fname_lower for p in name_parts if len(p) > 2)
        if not has_name:
            continue
        if any(kw in fname_lower for kw in BAD_IMAGE_KEYWORDS):
            continue

        url = get_image_url(wiki, fname)
        if not url:
            continue

        score = _score_image_url(url)
        candidates.append((score, fname, url))
        time.sleep(0.1)

    if not candidates:
        return None

    candidates.sort(key=lambda x: -x[0])
    return candidates[0][2]


def _score_image_url(url: str) -> float:
    """Score an image URL for suitability based on filename patterns.

    Higher scores = more likely a clean standing render/profile.
    Falls back to 1.0 for any image that passes the name+keyword filters
    in find_best_image (so content-based quality checks can still evaluate it).
    """
    fname = unquote(url.lower()).replace("_", " ").replace("-", " ")

    # Strong signals — clean character images
    if any(kw in fname for kw in ["profile", "render", "databook"]):
        return 5.0
    if any(kw in fname for kw in ["infobox", "character image"]):
        return 4.0
    if any(kw in fname for kw in ["full body", "full_body", "standing"]):
        return 4.0

    # Medium signals
    if any(kw in fname for kw in ["anime", "design", "artwork", "costume"]):
        return 3.0
    if "manga" in fname:
        return 1.5

    # Fallback — image passed name+keyword filters, let content checks decide
    return 1.0
