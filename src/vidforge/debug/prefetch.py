"""Pre-fetch all candidate images for all shows.

Downloads images, runs bg removal, computes all metrics, saves to JSON.
Run this ONCE, then the Streamlit app loads instantly from cache.

Usage:
    cd vidforge && uv run python3 src/vidforge/debug/prefetch.py
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from PIL import Image  # noqa: E402

from vidforge.assets.bg_remove import remove_background  # noqa: E402
from vidforge.assets.images import _quality_score  # noqa: E402
from vidforge.assets.images import content_ratio  # noqa: E402
from vidforge.assets.images import download_image  # noqa: E402
from vidforge.assets.images import gather_candidates  # noqa: E402
from vidforge.assets.images import height_fill  # noqa: E402
from vidforge.assets.pose_check import check_full_body  # noqa: E402
from vidforge.assets.scoring import compute_all_features  # noqa: E402

CACHE_DIR = Path("/tmp/vf_streamlit_cache")
CACHE_DIR.mkdir(exist_ok=True)
DATA_FILE = CACHE_DIR / "prefetched.json"


def _image_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _download_and_process(url: str, key: str) -> bool:
    """Download + bg-remove a single image, save to cache. Returns True on success."""
    raw_path = CACHE_DIR / f"{key}_raw.png"
    proc_path = CACHE_DIR / f"{key}_proc.png"

    if proc_path.exists():
        return True

    img = download_image(url)
    if not img:
        return False

    img.save(raw_path)

    proc = remove_background(img)
    if proc:
        proc.save(proc_path)
        return True

    return False


def _process_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    """Download, process, and compute metrics for one candidate."""
    try:
        url = candidate["url"]
        key = _image_key(url)

        if not _download_and_process(url, key):
            return None

        proc_path = CACHE_DIR / f"{key}_proc.png"
        if not proc_path.exists():
            return None

        img = Image.open(proc_path).convert("RGBA")

        hf = height_fill(img)
        cr = content_ratio(img)
        pose = check_full_body(img)
        features = compute_all_features(img)
        q_score = _quality_score(img, candidate["source_score"])

        return {
            "key": key,
            "url": url,
            "source": candidate["source"],
            "source_score": candidate["source_score"],
            "hf": round(float(hf), 4),
            "cr": round(float(cr), 4),
            "q_score": round(float(q_score), 4),
            "pose": {k: bool(v) for k, v in pose.items()},
            "features": {k: float(v) for k, v in features.items()},
        }
    except Exception as e:
        logging.getLogger(__name__).warning("Failed to process candidate: %s", e)
        return None


def _get_shows() -> dict[str, Any]:
    """Lazy import to avoid circular dependency."""
    from vidforge.generators.heights.debug.scaling import SHOWS

    return SHOWS


def main() -> None:
    all_data: dict[str, dict[str, Any]] = {}

    # Load existing data to skip already-done shows
    if DATA_FILE.exists():
        all_data = json.loads(DATA_FILE.read_text())
        print(f"Loaded existing data for {len(all_data)} shows")

    for show in _get_shows():
        show_name = show["name"]

        # Skip if already prefetched
        if show_name in all_data:
            print(f"[SKIP] {show_name} (already done)")
            continue

        print(f"\n{'=' * 60}")
        print(f"[FETCH] {show_name}")
        print(f"{'=' * 60}")

        show_data: dict[str, Any] = {}

        for name, height, wiki_page in show["characters"]:
            print(f"  {name} ({height}cm)...", end=" ", flush=True)
            t0 = time.time()

            # Gather candidates
            candidates_raw = gather_candidates(
                name,
                wiki=show["wiki"],
                wiki_page=wiki_page,
                show_name=show["name"],
                show_search_term=show.get("anilist_search", ""),
                max_fandom=8,
                max_rembg=8,
            )

            if not candidates_raw:
                print("no candidates")
                continue

            # Process all candidates sequentially (safe on low RAM)
            processed = []
            for c in candidates_raw:
                result = _process_candidate(c)
                if result:
                    processed.append(result)

            if not processed:
                print("all failed")
                continue

            # Sort by quality score to find algo pick
            processed.sort(key=lambda c: c["q_score"], reverse=True)
            algo_pick_idx = 0
            # Re-sort back to original order for display
            processed.sort(
                key=lambda c: candidates_raw.index(
                    next(cr for cr in candidates_raw if cr["url"] == c["url"])
                )
            )

            show_data[name] = {
                "candidates": processed,
                "algo_pick_idx": algo_pick_idx,
            }

            elapsed = time.time() - t0
            print(f"✓ {len(processed)}/{len(candidates_raw)} candidates ({elapsed:.0f}s)")

        all_data[show_name] = show_data

        # Save after each show (so progress isn't lost)
        DATA_FILE.write_text(json.dumps(all_data, indent=2))
        print(f"  Saved ({len(all_data)} shows total)")

    print(f"\n{'=' * 60}")
    print(f"Done! Pre-fetched {len(all_data)} shows.")
    print(f"Data: {DATA_FILE}")
    print("Run: uv run streamlit run src/vidforge/debug/scoring_app.py")


if __name__ == "__main__":
    main()
