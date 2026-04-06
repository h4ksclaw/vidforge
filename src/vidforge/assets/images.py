"""Image fetching, caching, and processing pipeline."""

import io
from dataclasses import dataclass
from dataclasses import field
from typing import Any

import httpx
from PIL import Image

from vidforge.assets.bg_remove import content_ratio
from vidforge.assets.bg_remove import height_fill
from vidforge.assets.bg_remove import remove_background
from vidforge.assets.cache import get_cached
from vidforge.assets.cache import item_cache_key
from vidforge.assets.cache import put_cached
from vidforge.models import Item
from vidforge.sources.anilist import find_character_image as anilist_find
from vidforge.sources.fandom import BAD_IMAGE_KEYWORDS
from vidforge.sources.fandom import _score_image_url
from vidforge.sources.fandom import get_image_url
from vidforge.sources.fandom import get_page_images
from vidforge.sources.jikan import find_character_image as jikan_find

HEADERS = {"User-Agent": "VidForge/0.1 (github.com/h4ksclaw/vidforge)"}


@dataclass
class CandidateResult:
    """Result of evaluating a single image candidate."""

    url: str
    source: str
    source_score: float
    status: str  # "winner", "accepted", "rejected"
    reject_reason: str = ""
    quality_score: float = 0.0
    height_fill: float = 0.0
    content_ratio: float = 0.0
    aspect_ratio: float = 0.0
    raw_url: str = ""  # uploaded thumbnail of original
    processed_url: str = ""  # uploaded thumbnail of bg-removed


@dataclass
class FetchResult:
    """Result of fetch_best_image with full candidate evaluation details."""

    item: Item
    candidates: list[CandidateResult] = field(default_factory=list)


def download_image(url: str) -> Image.Image | None:
    """Download an image from a URL and convert to RGBA."""
    try:
        with httpx.Client(timeout=15, headers=HEADERS) as client:
            resp = client.get(url)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content))
            return img.convert("RGBA") if img.mode != "RGBA" else img
    except (httpx.HTTPError, OSError):
        return None


def _quality_score(img: Image.Image) -> float:
    """Score a processed (bg-removed) image for full-body character suitability.

    Higher = better. Considers:
    - Height fill (0.55-0.95 is ideal, penalize too short or too tight)
    - Content ratio (0.3-0.7 is ideal, penalize too wide or too narrow)
    - Aspect ratio (0.3-0.8 is ideal for standing poses)

    Returns 0.0 to 1.0.
    """
    if not img or img.height < 100:
        return 0.0

    hf = height_fill(img)
    cr = content_ratio(img)
    aspect = img.width / img.height if img.height else 99.0

    # Height fill: sweet spot is 0.6-0.9
    if 0.6 <= hf <= 0.9:
        hf_score = 1.0
    elif 0.55 <= hf <= 0.95:
        hf_score = 0.8
    elif 0.4 <= hf <= 1.0:
        hf_score = 0.4
    else:
        hf_score = 0.0

    # Content ratio: sweet spot is 0.3-0.7 (character takes up reasonable width)
    if 0.3 <= cr <= 0.7:
        cr_score = 1.0
    elif 0.2 <= cr <= 0.8:
        cr_score = 0.7
    else:
        cr_score = 0.2

    # Aspect ratio: sweet spot is 0.3-0.8 (portrait-ish)
    if 0.3 <= aspect <= 0.8:
        ar_score = 1.0
    elif 0.2 <= aspect <= 1.0:
        ar_score = 0.6
    else:
        ar_score = 0.1

    # Weighted combination
    return hf_score * 0.45 + cr_score * 0.35 + ar_score * 0.2


def gather_candidates(
    name: str,
    wiki: str = "",
    wiki_page: str = "",
    max_fandom: int = 3,
) -> list[dict[str, Any]]:
    """Gather candidate image URLs from all available sources.

    Returns list of {"url": str, "source": str, "source_score": float}
    with best candidates first.
    """
    candidates: list[dict[str, Any]] = []

    # 1. Fandom wiki — get top N scored images
    if wiki:
        page = wiki_page or name
        fandom_urls = _fandom_top_images(wiki, page, max_fandom)
        for score, url in fandom_urls:
            candidates.append({"url": url, "source": "fandom", "source_score": score})

    # 2. AniList — single best match
    try:
        anilist_url = anilist_find(name)
        if anilist_url and not any(c["url"] == anilist_url for c in candidates):
            candidates.append({"url": anilist_url, "source": "anilist", "source_score": 3.0})
    except (ImportError, OSError):
        pass

    # 3. Jikan / MAL — single best match
    try:
        jikan_url = jikan_find(name)
        if jikan_url and not any(c["url"] == jikan_url for c in candidates):
            candidates.append({"url": jikan_url, "source": "jikan", "source_score": 2.0})
    except (ImportError, OSError):
        pass

    return candidates


def _fandom_top_images(
    wiki: str,
    character_name: str,
    max_results: int = 3,
) -> list[tuple[float, str]]:
    """Get top N scored image URLs from a Fandom wiki page.

    Returns list of (score, url) sorted by score descending.
    """
    images = get_page_images(wiki, character_name)
    name_parts = character_name.lower().replace("_", " ").split()

    scored: list[tuple[float, str]] = []
    for fname in images:
        fname_lower = fname.lower().replace("_", " ").replace("-", " ")
        has_name = any(p in fname_lower for p in name_parts if len(p) > 2)
        if not has_name:
            continue
        if any(kw in fname_lower for kw in BAD_IMAGE_KEYWORDS):
            continue

        url = get_image_url(wiki, fname)
        if url:
            score = _score_image_url(url)
            scored.append((score, url))

    scored.sort(key=lambda x: -x[0])
    return scored[:max_results]


def fetch_best_image(
    item: Item,
    wiki: str = "",
    wiki_page: str = "",
    skip_bg_removal: bool = False,
    min_height_fill: float = 0.55,
) -> Item:
    """Fetch the best image for an item from all available sources.

    Gathers candidates from Fandom (top 3), AniList, and Jikan.
    Downloads and processes each, picks the one with the best quality score.

    Checks cache first. Returns item with image_path set if successful.
    """
    result = fetch_best_image_debug(
        item,
        wiki=wiki,
        wiki_page=wiki_page,
        skip_bg_removal=skip_bg_removal,
        min_height_fill=min_height_fill,
    )
    return result.item


def fetch_best_image_debug(
    item: Item,
    wiki: str = "",
    wiki_page: str = "",
    skip_bg_removal: bool = False,
    min_height_fill: float = 0.55,
) -> FetchResult:
    """Fetch best image with full candidate evaluation details for debugging.

    Returns FetchResult with per-candidate status, scores, and reject reasons.
    """
    if not item.image_url:
        candidates = gather_candidates(item.name, wiki=wiki, wiki_page=wiki_page)
    else:
        candidates = [{"url": item.image_url, "source": "direct", "source_score": 1.0}]

    fetch_result = FetchResult(item=item)

    if not candidates:
        return fetch_result

    # Check cache
    key = item_cache_key(item)
    cached = get_cached(key)
    if cached:
        return fetch_result  # cached, no candidate details

    best_item: Item | None = None
    best_score = -1.0
    evaluated: list[CandidateResult] = []

    for candidate in candidates:
        url = candidate["url"]
        cr_result = CandidateResult(
            url=url,
            source=candidate["source"],
            source_score=candidate["source_score"],
            status="rejected",
        )

        # Download
        img = download_image(url)
        if not img:
            cr_result.reject_reason = "download failed"
            evaluated.append(cr_result)
            continue

        cr_result.aspect_ratio = round(img.width / img.height, 3) if img.height else 99.0

        # Background removal
        if not skip_bg_removal:
            processed = remove_background(img)
            if not processed:
                cr_result.reject_reason = "bg removal failed"
                evaluated.append(cr_result)
                continue
            img = processed

        # Quality metrics
        hf = height_fill(img)
        cr = content_ratio(img)
        cr_result.height_fill = round(hf, 3)
        cr_result.content_ratio = round(cr, 3)
        cr_result.quality_score = round(_quality_score(img), 3)

        # Quality filter: height fill
        if hf < min_height_fill:
            cr_result.reject_reason = f"height_fill={hf:.2f} < {min_height_fill}"
            evaluated.append(cr_result)
            continue

        cr_result.status = "accepted"

        if cr_result.quality_score > best_score:
            best_score = cr_result.quality_score
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            path = put_cached(key, buf.getvalue())
            best_item = item.model_copy(update={"image_path": str(path)})

        evaluated.append(cr_result)

    # Mark the winner
    if best_item and evaluated:
        for cr in evaluated:
            if cr.status == "accepted" and cr.quality_score == best_score:
                cr.status = "winner"
                break

    fetch_result.item = best_item or item
    fetch_result.candidates = evaluated
    return fetch_result


def fetch_and_process_image(
    item: Item,
    skip_bg_removal: bool = False,
    min_score: float = 0.5,
    max_content_ratio: float = 0.75,
    min_height_fill: float = 0.55,
) -> Item:
    """Fetch image for an item, apply bg removal and quality filters.

    Checks cache first. If no cached version, downloads from item.image_url,
    removes background, and saves to cache.

    Returns the item with image_path set if successful, unchanged otherwise.
    """
    if not item.image_url:
        return item

    # Check cache
    key = item_cache_key(item)
    cached = get_cached(key)
    if cached:
        return item.model_copy(update={"image_path": str(cached)})

    # Download
    img = download_image(item.image_url)
    if not img:
        return item

    # Background removal
    if not skip_bg_removal:
        processed = remove_background(img)
        if processed:
            img = processed
        else:
            return item  # bg removal failed completely

    # Quality filters
    aspect = img.width / img.height if img.height else 99.0
    cr = content_ratio(img)
    hf = height_fill(img)

    # For tall narrow images (aspect < 0.6), content_ratio is expected to be
    # high because the character naturally fills most of the width.
    # Only apply content_ratio threshold to wider images.
    effective_cr_max = max_content_ratio
    if aspect < 0.6:
        effective_cr_max = 0.90  # allow tighter crops for tall images

    if cr > effective_cr_max:
        return item  # face crop or overly wide content

    if hf < min_height_fill:
        return item  # cropped image

    # Save to cache
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    path = put_cached(key, buf.getvalue())
    return item.model_copy(update={"image_path": str(path)})
