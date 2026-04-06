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
from vidforge.sources.anilist import search_character_images as anilist_search
from vidforge.sources.fandom import BAD_IMAGE_KEYWORDS
from vidforge.sources.fandom import _score_image_url
from vidforge.sources.fandom import get_image_url
from vidforge.sources.fandom import get_page_images

HEADERS = {"User-Agent": "VidForge/0.1 (github.com/h4ksclaw/vidforge)"}


def _make_thumbnail(
    img: Image.Image, max_h: int = 200, bg: tuple[int, ...] = (80, 30, 140, 255)
) -> Image.Image | None:
    """Create a small thumbnail for debug report uploads with colored background."""
    if not img or img.height < 10:
        return None
    ratio = max_h / img.height
    new_w = int(img.width * ratio)
    thumb = img.resize((new_w, max_h), Image.LANCZOS)
    # Composite onto colored background
    canvas = Image.new("RGBA", thumb.size, bg)
    canvas.alpha_composite(thumb)
    return canvas


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


def _quality_score(img: Image.Image, source_score: float = 1.0) -> float:
    """Score a processed (bg-removed) image for full-body character suitability.

    Higher = better. Considers:
    - Height fill (0.7-0.95 is ideal — character fills most of the frame vertically)
    - Content ratio (0.3-0.75 is ideal — character has reasonable width without being a crop)
    - Aspect ratio (0.3-0.7 is ideal — portrait standing pose)
    - Source score bonus (fandom "render" > generic fandom > anilist > jikan)

    Returns 0.0 to 1.0.
    """
    if not img or img.height < 100:
        return 0.0

    hf = height_fill(img)
    cr = content_ratio(img)
    aspect = img.width / img.height if img.height else 99.0

    # Height fill: sweet spot is 0.7-0.95 (character fills most of the frame)
    if 0.7 <= hf <= 0.95:
        hf_score = 1.0
    elif 0.55 <= hf < 0.7:
        hf_score = 0.6  # cropped but usable
    elif 0.95 < hf <= 1.0:
        hf_score = 0.9  # very tight crop, still often full body
    else:
        hf_score = 0.0

    # Content ratio: sweet spot is 0.3-0.75
    # > 0.85 is almost certainly a face/torso crop
    if 0.3 <= cr <= 0.75:
        cr_score = 1.0
    elif 0.75 < cr <= 0.85:
        cr_score = 0.5  # questionable
    elif 0.15 <= cr < 0.3:
        cr_score = 0.5  # very slim character
    elif cr > 0.85:
        cr_score = 0.15  # almost certainly a crop
    else:
        cr_score = 0.1

    # Aspect ratio: sweet spot is 0.3-0.7 (portrait standing pose)
    if 0.3 <= aspect <= 0.7:
        ar_score = 1.0
    elif 0.7 < aspect <= 0.9:
        ar_score = 0.7  # wider but still portrait
    elif 0.2 <= aspect < 0.3:
        ar_score = 0.5  # very narrow
    elif 0.9 < aspect <= 1.2:
        ar_score = 0.3  # square-ish, often a crop
    else:
        ar_score = 0.1

    # Source score bonus: prefer images from sources that scored well on filename
    # fandom "render" (5.0) > fandom generic (1.0) > anilist (3.0) > jikan (2.0)
    # Normalize to 0-1 bonus range
    source_bonus = min(source_score / 5.0, 1.0) * 0.08  # max 0.08 bonus

    # Weighted combination — content metrics dominate
    return hf_score * 0.40 + cr_score * 0.35 + ar_score * 0.15 + source_bonus


def gather_candidates(
    name: str,
    wiki: str = "",
    wiki_page: str = "",
    show_name: str = "",
    max_fandom: int = 6,
    max_rembg: int = 3,  # only bg-remove top N candidates per source
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

    # 2. AniList — try multiple results for better coverage
    try:
        anilist_url = anilist_find(name, show=show_name)
        if anilist_url and not any(c["url"] == anilist_url for c in candidates):
            candidates.append({"url": anilist_url, "source": "anilist", "source_score": 3.0})
        # Also try broader search for more candidates
        for url in anilist_search(name, max_results=3)[1:]:  # skip first (already tried)
            if url and not any(c["url"] == url for c in candidates):
                candidates.append({"url": url, "source": "anilist", "source_score": 2.0})
    except (ImportError, OSError):
        pass

    # 3. Jikan / MAL — disabled (returns wrong-show results too often)
    # try:
    #     jikan_url = jikan_find(name, show=show_name)
    #     if jikan_url and not any(c["url"] == jikan_url for c in candidates):
    #         candidates.append({"url": jikan_url, "source": "jikan", "source_score": 2.0})

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
    show_name: str = "",
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
        show_name=show_name,
        skip_bg_removal=skip_bg_removal,
        min_height_fill=min_height_fill,
    )
    return result.item


def fetch_best_image_debug(
    item: Item,
    wiki: str = "",
    wiki_page: str = "",
    show_name: str = "",
    skip_bg_removal: bool = False,
    min_height_fill: float = 0.55,
    max_rembg: int = 3,
) -> FetchResult:
    """Fetch best image with full candidate evaluation details for debugging.

    max_rembg limits how many candidates get the expensive bg-removal step.
    All candidates are still downloaded and scored by cheap heuristics.
    Only the top max_rembg by source_score get full processing.
    """
    if not item.image_url:
        candidates = gather_candidates(
            item.name, wiki=wiki, wiki_page=wiki_page, show_name=show_name
        )
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

    # Sort by source_score descending — cheap heuristic pre-filter
    # Only run expensive bg-removal on top max_rembg candidates
    candidates_sorted = sorted(candidates, key=lambda c: -c["source_score"])
    rembg_count = 0

    for candidate in candidates_sorted:
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

        # Save raw thumbnail for debug reports
        raw_thumb = _make_thumbnail(img, max_h=200)
        if raw_thumb:
            raw_thumb_path = f"/tmp/vf_cand_{item.name.replace(' ', '_')}_{len(evaluated)}.png"
            raw_thumb.save(raw_thumb_path)
            cr_result.raw_url = raw_thumb_path

        # Background removal — only for top max_rembg candidates by source_score
        if not skip_bg_removal:
            if rembg_count >= max_rembg:
                cr_result.reject_reason = "skipped (max_rembg reached)"
                evaluated.append(cr_result)
                continue
            processed = remove_background(img)
            if not processed:
                cr_result.reject_reason = "bg removal failed"
                evaluated.append(cr_result)
                continue
            img = processed
            rembg_count += 1
            # Save processed thumbnail for debug reports
            proc_thumb = _make_thumbnail(img, max_h=200)
            if proc_thumb:
                proc_thumb_path = (
                    f"/tmp/vf_cand_{item.name.replace(' ', '_')}_{len(evaluated)}_proc.png"
                )
                proc_thumb.save(proc_thumb_path)
                cr_result.processed_url = proc_thumb_path

        # Quality metrics
        hf = height_fill(img)
        cr = content_ratio(img)
        cr_result.height_fill = round(hf, 3)
        cr_result.content_ratio = round(cr, 3)
        cr_result.quality_score = round(_quality_score(img, candidate["source_score"]), 3)

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
