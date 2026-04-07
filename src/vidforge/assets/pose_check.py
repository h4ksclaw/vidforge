"""Lightweight full-body detection for anime character images.

Uses pure image analysis (no ML models) to estimate whether a bg-removed
character image shows a full-body standing pose vs a crop.

Two independent checks, each returning a 0-1 score:
1. Head detection: scans top portion of IMAGE for a head-like blob
2. Foot detection: scans bottom portion of IMAGE for foot-like structures

Key insight: we check relative to the full image, not the content bbox.
A full-body character should have content near both the top AND bottom edges.
A crop only has content in the middle (or top if head+torso crop).
"""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def check_full_body(img: Image.Image) -> dict:
    """Estimate if a bg-removed anime image shows a full-body standing pose.

    Returns dict with:
        - full_body: bool — True if both head and feet likely present
        - has_head: bool — content found near top of image
        - has_feet: bool — content found near bottom of image
        - head_score: float — 0-1 confidence of head detection
        - feet_score: float — 0-1 confidence of feet detection
        - vertical_span: float — fraction of image height covered by content
    """
    result = {
        "full_body": False,
        "has_head": False,
        "has_feet": False,
        "head_score": 0.0,
        "feet_score": 0.0,
        "vertical_span": 0.0,
    }

    if not img or img.height < 100:
        return result

    if img.mode != "RGBA":
        return result

    alpha = np.array(img.split()[3])
    binary = (alpha > 64).astype(np.uint8)
    h, _w = binary.shape

    # ─── Vertical content analysis ─────────────────────────────────────
    # For each row, count how many pixels have content
    row_content = np.array([np.sum(binary[y] > 0) for y in range(h)])
    max_row_content = max(row_content) if max(row_content) > 0 else 1

    # Normalize to 0-1 per row
    row_fill = row_content / max_row_content

    # Find first and last rows with significant content (>5% of max)
    threshold = 0.05
    filled_rows = np.where(row_fill > threshold)[0]
    if len(filled_rows) == 0:
        return result

    first_row = filled_rows[0]
    last_row = filled_rows[-1]
    vertical_span = (last_row - first_row) / h
    result["vertical_span"] = round(vertical_span, 3)

    # ─── Head detection ────────────────────────────────────────────────
    # Head should be in the top 15% of the image
    head_zone = h * 0.15
    head_rows = np.where(row_fill[: int(head_zone)] > threshold)[0]

    if len(head_rows) > 0:
        # How much of the head zone has content?
        head_coverage = len(head_rows) / head_zone
        # How filled are those rows? (a head should have decent fill)
        head_fill_avg = np.mean(row_fill[head_rows])
        # Combined score
        result["head_score"] = round(min(head_coverage * head_fill_avg * 2, 1.0), 3)
        result["has_head"] = result["head_score"] >= 0.1

    # ─── Feet detection ────────────────────────────────────────────────
    # Feet should be in the bottom 10% of the image
    feet_zone_start = int(h * 0.90)
    feet_rows = np.where(row_fill[feet_zone_start:] > threshold)[0]

    if len(feet_rows) > 0:
        # How much of the feet zone has content?
        feet_zone_size = h - feet_zone_start
        feet_coverage = len(feet_rows) / feet_zone_size
        # How filled are those rows?
        feet_fill_avg = np.mean(row_fill[feet_rows + feet_zone_start])
        # Combined score
        result["feet_score"] = round(min(feet_coverage * feet_fill_avg * 2, 1.0), 3)
        result["has_feet"] = result["feet_score"] >= 0.1

    # ─── Combined ─────────────────────────────────────────────────────
    result["full_body"] = result["has_head"] and result["has_feet"]

    return result
