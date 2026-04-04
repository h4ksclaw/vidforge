"""Image fetching, caching, and processing pipeline."""

import io

import httpx
from PIL import Image

from vidforge.assets.bg_remove import content_ratio
from vidforge.assets.bg_remove import height_fill
from vidforge.assets.bg_remove import remove_background
from vidforge.assets.cache import get_cached
from vidforge.assets.cache import item_cache_key
from vidforge.assets.cache import put_cached
from vidforge.models import Item

HEADERS = {"User-Agent": "VidForge/0.1 (github.com/h4ksclaw/vidforge)"}


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
