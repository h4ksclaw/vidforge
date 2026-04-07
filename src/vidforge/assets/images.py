"""Image fetching, caching, and processing pipeline."""

import io
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
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
from vidforge.assets.pose_check import check_full_body
from vidforge.assets.scoring import color_palette_variance
from vidforge.assets.scoring import compute_all_features
from vidforge.assets.scoring import edge_density_score
from vidforge.assets.scoring import symmetry_score
from vidforge.assets.scoring import vertical_thirds_coverage
from vidforge.models import Item
from vidforge.sources.anilist import find_character_image as anilist_find
from vidforge.sources.anilist import search_character_images as anilist_search
from vidforge.sources.fandom import BAD_IMAGE_KEYWORDS
from vidforge.sources.fandom import _score_image_url
from vidforge.sources.fandom import get_image_url
from vidforge.sources.fandom import get_page_images

logger = logging.getLogger(__name__)

# Number of parallel rembg workers (capped at CPU count)
_REMBG_WORKERS = min(4, os.cpu_count() or 2)

HEADERS = {"User-Agent": "VidForge/0.1 (github.com/h4ksclaw/vidforge)"}


def _rembg_worker(img: Image.Image) -> Image.Image | None:
    """Run rembg in a thread worker. Accepts PIL Image, returns processed PIL Image or None.

    Thread-safe because rembg/onnxruntime inference is stateless.
    """
    try:
        return remove_background(img)
    except Exception:
        return None


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
    pose_full_body: bool = False
    pose_head: bool = False
    pose_feet: bool = False
    # Advanced scoring features
    color_variance: float = 0.0
    top_third: float = 0.0
    middle_third: float = 0.0
    bottom_third: float = 0.0
    all_thirds_present: bool = False
    symmetry: float = 0.0
    edge_smoothness: float = 0.0


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


# Scoring weights — tunable via Streamlit app
SCORING_WEIGHTS: dict[str, float] = {
    "height_fill": 0.25,
    "content_ratio": 0.30,
    "aspect_ratio": 0.10,
    "source_bonus": 0.04,
    "pose": 0.08,
    "color_variance": 0.08,
    "vertical_thirds": 0.08,
    "symmetry": 0.04,
    "edge_smoothness": 0.03,
}


def _quality_score(img: Image.Image, source_score: float = 1.0) -> float:
    """Score a processed (bg-removed) image for full-body character suitability.

    Higher = better. Uses multiple heuristic signals:
    - Height fill — character fills frame vertically (penalize crops)
    - Content ratio — reasonable width without being a tight crop
    - Aspect ratio — portrait standing pose preferred
    - Source bonus — fandom "render" filenames preferred
    - Pose detection — full-body standing pose confirmed
    - Color variance — distinct color regions = clean render
    - Vertical thirds — content in top/middle/bottom = full body
    - Symmetry — standing poses are roughly symmetric
    - Edge smoothness — clean renders have smooth edges

    Returns 0.0 to 1.0.
    """
    if not img or img.height < 100:
        return 0.0

    hf = height_fill(img)
    cr = content_ratio(img)
    aspect = img.width / img.height if img.height else 99.0
    w = SCORING_WEIGHTS

    # --- Height fill ---
    hf_score = 1.0 if hf >= 0.55 else 0.0

    # --- Content ratio ---
    if 0.25 <= cr <= 0.70:
        cr_score = 1.0
    elif 0.70 < cr <= 0.78:
        cr_score = 0.6
    elif 0.15 <= cr < 0.25:
        cr_score = 0.4
    elif 0.78 < cr <= 0.88:
        cr_score = 0.25
    elif cr > 0.88:
        cr_score = 0.05
    else:
        cr_score = 0.05

    # --- Aspect ratio ---
    if 0.3 <= aspect <= 0.7:
        ar_score = 1.0
    elif 0.7 < aspect <= 0.9:
        ar_score = 0.7
    elif 0.2 <= aspect < 0.3:
        ar_score = 0.5
    elif 0.9 < aspect <= 1.2:
        ar_score = 0.3
    else:
        ar_score = 0.1

    # --- Source bonus ---
    source_bonus = min(source_score / 5.0, 1.0) * w["source_bonus"]

    # --- Pose detection ---
    try:
        pose = check_full_body(img)
        if pose["full_body"]:
            pose_score = 1.0
        elif pose["has_head"] or pose["has_feet"]:
            pose_score = 0.3
        else:
            pose_score = -0.5  # penalty
    except Exception:
        pose_score = 0.0

    # --- Color variance ---
    cv = color_palette_variance(img)

    # --- Vertical thirds ---
    thirds = vertical_thirds_coverage(img)
    if thirds["all_present"]:
        thirds_score = 1.0
    else:
        # Partial credit for having 2 out of 3
        present = sum(1 for k in ("top", "middle", "bottom") if thirds[k] >= 0.30)
        thirds_score = present / 3.0

    # --- Symmetry ---
    sym = symmetry_score(img)

    # --- Edge smoothness ---
    edge = edge_density_score(img)

    # --- Weighted combination ---
    raw = (
        hf_score * w["height_fill"]
        + cr_score * w["content_ratio"]
        + ar_score * w["aspect_ratio"]
        + source_bonus
        + pose_score * w["pose"]
        + cv * w["color_variance"]
        + thirds_score * w["vertical_thirds"]
        + sym * w["symmetry"]
        + edge * w["edge_smoothness"]
    )
    return max(0.0, min(1.0, raw))


def gather_candidates(
    name: str,
    wiki: str = "",
    wiki_page: str = "",
    show_name: str = "",
    show_search_term: str = "",
    max_fandom: int = 8,
    max_rembg: int = 6,  # only bg-remove top N candidates per source
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

    # 2. AniList — show-scoped character search (no cross-show contamination)
    try:
        anilist_url = anilist_find(name, show=show_name, show_search_term=show_search_term)
        if anilist_url and not any(c["url"] == anilist_url for c in candidates):
            candidates.append({"url": anilist_url, "source": "anilist", "source_score": 3.0})
        # Also try broader search for more candidates
        for url in anilist_search(
            name, max_results=3, show=show_name, show_search_term=show_search_term
        )[:3]:
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
    max_results: int = 8,
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
    show_search_term: str = "",
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
        show_search_term=show_search_term,
        skip_bg_removal=skip_bg_removal,
        min_height_fill=min_height_fill,
    )
    return result.item


def fetch_best_image_debug(
    item: Item,
    wiki: str = "",
    wiki_page: str = "",
    show_name: str = "",
    show_search_term: str = "",
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
            item.name,
            wiki=wiki,
            wiki_page=wiki_page,
            show_name=show_name,
            show_search_term=show_search_term,
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

    # Phase 1: Download all candidates (fast, sequential)
    downloaded: list[tuple[dict, Image.Image | None, CandidateResult]] = []
    for ci, candidate in enumerate(candidates_sorted):
        url = candidate["url"]
        cr_result = CandidateResult(
            url=url,
            source=candidate["source"],
            source_score=candidate["source_score"],
            status="rejected",
        )
        img = download_image(url)
        if not img:
            cr_result.reject_reason = "download failed"
            evaluated.append(cr_result)
            downloaded.append((candidate, None, cr_result))
            continue
        cr_result.aspect_ratio = round(img.width / img.height, 3) if img.height else 99.0
        # Save raw thumbnail
        raw_thumb = _make_thumbnail(img, max_h=200)
        if raw_thumb:
            raw_thumb_path = f"/tmp/vf_cand_{item.name.replace(' ', '_')}_{ci}.png"
            raw_thumb.save(raw_thumb_path)
            cr_result.raw_url = raw_thumb_path
        downloaded.append((candidate, img, cr_result))

    # Phase 2: Background removal in parallel
    rembg_count = 0
    if not skip_bg_removal:
        # Pick top max_rembg candidates for rembg
        rembg_candidates = [
            (i, cand, img, cr)
            for i, (cand, img, cr) in enumerate(downloaded)
            if img is not None and rembg_count < max_rembg
        ][:max_rembg]

        if rembg_candidates:
            # Process in parallel using threads (shared memory, no serialization overhead)
            results_map: dict[int, Image.Image | None] = {}
            with ThreadPoolExecutor(max_workers=_REMBG_WORKERS) as pool:
                futures = {
                    pool.submit(_rembg_worker, img): idx
                    for idx, _data, img, _cr in rembg_candidates
                }
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        results_map[idx] = future.result()
                    except Exception as e:
                        logger.warning("rembg worker failed for candidate %d: %s", idx, e)
                        results_map[idx] = None

            # Apply results back
            for idx, _cand, _img, cr in rembg_candidates:
                processed = results_map.get(idx)
                if processed is None:
                    cr.reject_reason = "bg removal failed"
                else:
                    # Replace the image in downloaded list
                    downloaded[idx] = (downloaded[idx][0], processed, cr)
                    rembg_count += 1
                    # Save processed thumbnail
                    proc_thumb = _make_thumbnail(processed, max_h=200)
                    if proc_thumb:
                        proc_thumb_path = (
                            f"/tmp/vf_cand_{item.name.replace(' ', '_')}_{idx}_proc.png"
                        )
                        proc_thumb.save(proc_thumb_path)
                        cr.processed_url = proc_thumb_path
        # Mark skipped candidates (downloaded but not selected for rembg)
        rembg_indices = {idx for idx, _, _, _ in rembg_candidates}
        for i, (_cand, img, cr) in enumerate(downloaded):
            if img is not None and i not in rembg_indices and cr.reject_reason == "rejected":
                cr.reject_reason = "skipped (max_rembg reached)"

    # Phase 3: Score all candidates (fast, sequential)
    for _ci, (candidate, img, cr_result) in enumerate(downloaded):
        if img is None:
            continue  # already rejected (download failed or bg removal failed)

        # Quality metrics
        hf = height_fill(img)
        cr = content_ratio(img)
        cr_result.height_fill = round(hf, 3)
        cr_result.content_ratio = round(cr, 3)
        cr_result.quality_score = round(_quality_score(img, candidate["source_score"]), 3)

        # Pose detection (full-body check)
        try:
            pose = check_full_body(img)
            cr_result.pose_full_body = pose["full_body"]
            cr_result.pose_head = pose["has_head"]
            cr_result.pose_feet = pose["has_feet"]
        except Exception:
            pass

        # Advanced scoring features
        try:
            features = compute_all_features(img)
            cr_result.color_variance = features["color_variance"]
            cr_result.top_third = features["top_third"]
            cr_result.middle_third = features["middle_third"]
            cr_result.bottom_third = features["bottom_third"]
            cr_result.all_thirds_present = features["all_thirds_present"]
            cr_result.symmetry = features["symmetry"]
            cr_result.edge_smoothness = features["edge_smoothness"]
        except Exception:
            pass

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
