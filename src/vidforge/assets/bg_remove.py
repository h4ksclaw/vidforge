"""Background removal using rembg — two-pass approach."""

from typing import TYPE_CHECKING
from typing import Any

import numpy as np
from PIL import Image

if TYPE_CHECKING:
    pass


def _get_remove_fn() -> Any:
    """Lazy-load rembg.remove to avoid importing onnxruntime at module level."""
    from rembg import remove

    return remove


def remove_background(img: Image.Image) -> Image.Image | None:
    """Remove background from an image using rembg.

    Two-pass approach:
    1. Fast default pass (no alpha matting)
    2. If content fills < 50% of image height, retry with alpha matting

    Returns RGBA image or None if removal fails entirely.
    """
    remove = _get_remove_fn()

    raw_result = remove(img)
    if not isinstance(raw_result, Image.Image):
        return None
    result = raw_result
    if result.mode != "RGBA":
        result = result.convert("RGBA")

    alpha = np.array(result.split()[3])
    binary = (alpha > 64).astype(np.uint8)

    rows = np.where(binary.max(axis=1))[0]
    cols = np.where(binary.max(axis=0))[0]
    if len(rows) == 0 or len(cols) == 0:
        return None

    content_h = rows[-1] - rows[0]
    img_h = alpha.shape[0]
    h_fill = content_h / img_h if img_h else 0

    # If content fills less than 50% of height, try alpha matting pass
    if h_fill < 0.50:
        result2 = remove(
            img,
            alpha_matting=True,
            alpha_matting_foreground_threshold=220,
            alpha_matting_background_threshold=20,
            alpha_matting_erode_size=5,
        )
        if not isinstance(result2, Image.Image):
            return result
        if result2.mode != "RGBA":
            result2 = result2.convert("RGBA")
        alpha2 = np.array(result2.split()[3])
        binary2 = (alpha2 > 64).astype(np.uint8)
        rows2 = np.where(binary2.max(axis=1))[0]
        if len(rows2) > 0:
            content_h2 = rows2[-1] - rows2[0]
            h_fill2 = content_h2 / img_h
            if h_fill2 > h_fill:
                result = result2

    return result


def score_image(img: Image.Image) -> float:
    """Score image for suitability as a full-body character image.

    Returns a float 0-1 representing how much of the image height
    is filled with content (tall narrow = good, wide short = bad).
    """
    w, h = img.size
    if h < 100 or w < 50:
        return 0.0
    ratio = w / h
    if ratio > 1.2 or ratio < 0.15:
        return 0.0

    try:
        alpha_arr = np.array(img.split()[3])
        rows: set[int] = set()
        for y in range(0, h, 4):
            for x in range(0, w, 4):
                if alpha_arr[y, x] > 128:
                    rows.add(y)
        if not rows:
            return 0.0
        return float(max(rows) - min(rows)) / h
    except (IndexError, AttributeError):
        return 0.0


def content_ratio(img: Image.Image) -> float:
    """Calculate content-to-image width ratio.

    Values > 0.75 suggest a face crop rather than full body.
    """
    w, h = img.size
    if h < 100 or w < 50:
        return 1.0

    try:
        alpha = img.split()[3]
        binary = (np.array(alpha) > 128).astype(np.uint8)
        cols = np.where(binary.max(axis=0))[0]
        if len(cols) == 0:
            return 1.0
        return float(cols[-1] - cols[0]) / w
    except (IndexError, AttributeError):
        return 1.0


def height_fill(img: Image.Image) -> float:
    """Calculate how much of the image height is filled with content.

    Values < 0.55 suggest the image is cropped.
    """
    h = img.size[1]
    if h < 100:
        return 0.0

    try:
        alpha = img.split()[3]
        binary = (np.array(alpha) > 128).astype(np.uint8)
        rows = np.where(binary.max(axis=1))[0]
        if len(rows) == 0:
            return 0.0
        return float(rows[-1] - rows[0]) / h
    except (IndexError, AttributeError):
        return 0.0
