"""Image quality scoring features — lightweight heuristic analysis.

Pure numpy/Pillow implementations for detecting good standing character renders.
No ML dependencies — designed to be fast and deterministic.
"""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def color_palette_variance(img: Image.Image) -> float:
    """Measure color diversity in a bg-removed image.

    Good character renders have distinct color regions (hair, skin, clothes).
    Dark screenshots or muddy action scenes have clumped, low-variance colors.

    Returns 0-1 score where higher = more color diversity.
    """
    if not img or img.mode != "RGBA" or img.size[0] < 10 or img.size[1] < 10:
        return 0.0

    # Only look at non-transparent pixels
    arr = np.array(img.convert("RGBA"))
    alpha = arr[:, :, 3]
    mask = alpha > 64

    if mask.sum() < 100:
        return 0.0

    # Sample RGB channels for opaque pixels
    rgb = arr[:, :, :3].astype(np.float32)
    pixels = rgb[mask]

    # Compute per-channel variance and average
    channel_vars = np.var(pixels, axis=0)  # variance per R, G, B
    # Normalize: 255^2 = 65025 is max possible variance, typical good images ~5000-15000
    avg_var = float(np.mean(channel_vars))
    # Sigmoid-like mapping: 0 at 0, ~1 at 10000
    score = avg_var / (avg_var + 3000.0)
    return round(min(max(score, 0.0), 1.0), 4)


def vertical_thirds_coverage(img: Image.Image) -> dict[str, float]:
    """Check content presence in top, middle, and bottom thirds of the image.

    A full-body standing pose has content in all three zones.
    A torso crop only has top+middle. A headshot only has top.

    Returns dict with:
        - top: 0-1 fraction of top third with content
        - middle: 0-1 fraction of middle third with content
        - bottom: 0-1 fraction of bottom third with content
        - all_present: True if all thirds have >30% content
    """
    result = {"top": 0.0, "middle": 0.0, "bottom": 0.0, "all_present": False}

    if not img or img.mode != "RGBA" or img.size[1] < 30:
        return result

    alpha = np.array(img.split()[3])
    binary = (alpha > 64).astype(np.uint8)
    h, _w = binary.shape
    third = h // 3

    zones = {
        "top": binary[:third, :],
        "middle": binary[third : 2 * third, :],
        "bottom": binary[2 * third :, :],
    }

    for name, zone in zones.items():
        if zone.size > 0:
            result[name] = round(float(zone.sum()) / zone.size, 4)

    threshold = 0.30
    result["all_present"] = all(v >= threshold for k, v in result.items() if k != "all_present")
    return result


def symmetry_score(img: Image.Image) -> float:
    """Measure left-right symmetry of a bg-removed image.

    Standing character poses tend to be roughly symmetric.
    Action shots (punching, running, twisting) are asymmetric.

    Uses alpha channel overlap between original and horizontally flipped image.
    Returns 0-1 score where 1.0 = perfectly symmetric.
    """
    if not img or img.mode != "RGBA" or img.size[0] < 20 or img.size[1] < 20:
        return 0.0

    alpha = (np.array(img.split()[3]) > 64).astype(np.uint8)
    flipped = np.fliplr(alpha)

    # Intersection over union of alpha masks
    intersection = np.logical_and(alpha, flipped).sum()
    union = np.logical_or(alpha, flipped).sum()

    if union == 0:
        return 0.0

    iou = float(intersection) / float(union)
    return round(iou, 4)


def vertical_straightness(img: Image.Image) -> float:
    """Measure how straight/uniform the character silhouette is from top to bottom.

    A good standing character render has a roughly uniform width from head to feet.
    Action poses, S-curves, leaning, or twisting create non-uniform width.

    Method: divide image into horizontal strips, measure content width in each,
    compute coefficient of variation. Low CV = straight standing pose.

    Returns 0-1 score where higher = more straight/uniform.
    """
    if not img or img.mode != "RGBA" or img.size[1] < 30:
        return 0.0

    alpha = (np.array(img.split()[3]) > 64).astype(np.uint8)
    h, w = alpha.shape

    # Divide into vertical strips (skip top 5% and bottom 5% — head/feet edges are noisy)
    strip_count = min(20, h // 10)
    if strip_count < 5:
        return 0.5

    margin = int(h * 0.05)
    strip_height = (h - 2 * margin) // strip_count

    widths: list[float] = []
    for i in range(strip_count):
        y_start = margin + i * strip_height
        y_end = y_start + strip_height
        strip = alpha[y_start:y_end, :]
        # Measure content width: distance between leftmost and rightmost opaque pixel
        row_has_content = strip.any(axis=1)
        if not row_has_content.any():
            continue
        # Find left/right bounds across all rows in strip
        col_sums = strip.sum(axis=0)
        nonzero_cols = np.where(col_sums > 0)[0]
        if len(nonzero_cols) == 0:
            continue
        width = float(nonzero_cols[-1] - nonzero_cols[0]) / w
        widths.append(width)

    if len(widths) < 3:
        return 0.5

    # Coefficient of variation of widths
    mean_w = np.mean(widths)
    if mean_w == 0:
        return 0.0
    cv = float(np.std(widths) / mean_w)

    # Low CV = straight. Typical standing pose: CV 0.1-0.3
    # Action pose / S-curve: CV 0.4+
    # Map: CV 0.1 → 1.0, CV 0.5 → 0.0
    score = max(0.0, 1.0 - (cv - 0.10) / 0.40)
    return round(min(max(score, 0.0), 1.0), 4)


def foot_visibility_score(img: Image.Image) -> float:
    """Measure how clearly feet/ground contact is visible in the bottom of the image.

    A good standing character render shows feet at the bottom of the frame.
    Crops and action shots often cut off or obscure the feet.

    Method: check the bottom 15% of the image for content presence and width.
    Feet create a distinctive wide content area at the very bottom.

    Returns 0-1 score where higher = better foot visibility.
    """
    if not img or img.mode != "RGBA" or img.size[1] < 30:
        return 0.0

    alpha = (np.array(img.split()[3]) > 64).astype(np.uint8)
    h, _w = alpha.shape

    # Bottom 15% of image
    bottom_start = int(h * 0.85)
    bottom_zone = alpha[bottom_start:, :]

    # Content fill ratio in bottom zone
    fill = float(bottom_zone.sum()) / bottom_zone.size

    # Also check: is there content in the very last 5%?
    very_bottom = alpha[int(h * 0.95) :, :]
    very_bottom_fill = float(very_bottom.sum()) / very_bottom.size if very_bottom.size > 0 else 0.0

    # Scoring:
    # Good: fill > 0.20 (feet visible) and very_bottom > 0.10 (touching ground)
    # OK: fill > 0.10 (some content but maybe cropped)
    # Bad: fill < 0.05 (no feet at all)

    if fill >= 0.20 and very_bottom_fill >= 0.10:
        return 1.0  # clear feet
    elif fill >= 0.15:
        return 0.7  # probably feet
    elif fill >= 0.10:
        return 0.4  # some content, might be cropped
    elif fill >= 0.05:
        return 0.2  # minimal content
    else:
        return 0.0  # no feet


def edge_density_score(img: Image.Image) -> float:
    """Measure edge complexity in a bg-removed image.

    Clean renders have smooth, consistent edges.
    Screenshots have text overlays, speed lines, and compression artifacts.

    Uses simple gradient magnitude (no cv2 dependency).
    Returns 0-1 score where higher = smoother edges (less noise).
    """
    if not img or img.mode != "RGBA" or img.size[0] < 10 or img.size[1] < 10:
        return 0.0

    alpha = np.array(img.split()[3]).astype(np.float32)
    binary = (alpha > 64).astype(np.float32)

    if binary.sum() < 100:
        return 0.0

    # Compute gradient magnitude using simple differences
    grad_x = np.abs(np.diff(binary, axis=1))
    grad_y = np.abs(np.diff(binary, axis=0))

    # Edge pixels are those with gradient > 0
    edge_x = (grad_x > 0).astype(np.float32)
    edge_y = (grad_y > 0).astype(np.float32)

    # Total edge pixel count relative to content area
    content_area = binary.sum()
    if content_area == 0:
        return 0.0

    # Union of horizontal and vertical edge pixels
    # Pad to same shape
    edge_combined = np.zeros_like(binary)
    edge_combined[:, :-1] = np.maximum(edge_combined[:, :-1], edge_x)
    edge_combined[:-1, :] = np.maximum(edge_combined[:-1, :], edge_y)

    edge_ratio = edge_combined.sum() / content_area

    # Low edge ratio = smooth edges = good render
    # Typical clean renders: 0.05-0.15, screenshots with artifacts: 0.15-0.30+
    # Invert so higher = better (smoother)
    score = max(0.0, 1.0 - (edge_ratio - 0.03) / 0.20)
    return round(min(max(score, 0.0), 1.0), 4)


def compute_all_features(img: Image.Image) -> dict:
    """Compute all scoring features for an image.

    Returns dict with all feature values for scoring and display.
    """
    thirds = vertical_thirds_coverage(img)
    return {
        "color_variance": color_palette_variance(img),
        "top_third": thirds["top"],
        "middle_third": thirds["middle"],
        "bottom_third": thirds["bottom"],
        "all_thirds_present": thirds["all_present"],
        "symmetry": symmetry_score(img),
        "edge_smoothness": edge_density_score(img),
        "vertical_straightness": vertical_straightness(img),
        "foot_visibility": foot_visibility_score(img),
    }
