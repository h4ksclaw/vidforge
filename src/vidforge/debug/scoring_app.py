"""Streamlit debug app for manual image classification and scoring exploration.

Run: uv run streamlit run src/vidforge/debug/scoring_app.py

Features:
- Browse candidates per character across all shows
- Classify images as good/bad/skip
- Explore metrics vs classifications
- Tune scoring weights with sliders
- Export classifications as JSON training data
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import streamlit as st
from PIL import Image

# Add project root to path
_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from vidforge.assets.bg_remove import remove_background  # noqa: E402
from vidforge.assets.images import SCORING_WEIGHTS  # noqa: E402
from vidforge.assets.images import CandidateResult  # noqa: E402
from vidforge.assets.images import content_ratio  # noqa: E402
from vidforge.assets.images import download_image  # noqa: E402
from vidforge.assets.images import gather_candidates  # noqa: E402
from vidforge.assets.images import height_fill  # noqa: E402
from vidforge.assets.pose_check import check_full_body  # noqa: E402
from vidforge.assets.scoring import compute_all_features  # noqa: E402

# Page config
st.set_page_config(page_title="VidForge Scoring Debug", layout="wide")

# Cache directory
CACHE_DIR = Path("/tmp/vf_streamlit_cache")
CACHE_DIR.mkdir(exist_ok=True)

# Labels file
LABELS_FILE = CACHE_DIR / "labels.json"


def _get_shows() -> list[dict[str, Any]]:
    """Import shows list from scaling.py."""
    from vidforge.generators.heights.debug.scaling import SHOWS

    return SHOWS


def _load_labels() -> dict[str, str]:
    """Load saved classifications."""
    if LABELS_FILE.exists():
        return json.loads(LABELS_FILE.read_text())
    return {}


def _save_labels(labels: dict[str, str]) -> None:
    """Save classifications to disk."""
    LABELS_FILE.write_text(json.dumps(labels, indent=2))


def _image_key(url: str) -> str:
    """Generate a filesystem-safe key from URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _download_and_process(url: str, key: str) -> tuple[Image.Image | None, Image.Image | None]:
    """Download and bg-remove an image, caching results."""
    raw_path = CACHE_DIR / f"{key}_raw.png"
    proc_path = CACHE_DIR / f"{key}_proc.png"

    # Load from cache if available
    if raw_path.exists():
        try:
            raw = Image.open(raw_path).copy()
            proc = Image.open(proc_path).copy() if proc_path.exists() else None
            return raw, proc
        except Exception:
            pass

    # Download
    img = download_image(url)
    if not img:
        return None, None

    img.save(raw_path)

    # Background removal
    proc = remove_background(img)
    if proc:
        proc.save(proc_path)

    return img, proc


def _candidate_to_dict(c: CandidateResult) -> dict[str, Any]:
    """Serialize CandidateResult for display."""
    return {
        "url": c.url,
        "source": c.source,
        "source_score": c.source_score,
        "status": c.status,
        "reject_reason": c.reject_reason,
        "quality_score": c.quality_score,
        "height_fill": c.height_fill,
        "content_ratio": c.content_ratio,
        "aspect_ratio": c.aspect_ratio,
        "pose_full_body": c.pose_full_body,
        "pose_head": c.pose_head,
        "pose_feet": c.pose_feet,
        "color_variance": c.color_variance,
        "top_third": c.top_third,
        "middle_third": c.middle_third,
        "bottom_third": c.bottom_third,
        "all_thirds_present": c.all_thirds_present,
        "symmetry": c.symmetry,
        "edge_smoothness": c.edge_smoothness,
    }


# ─── Main App ───────────────────────────────────────────────────────────────────


def main() -> None:
    shows = _get_shows()
    labels = _load_labels()

    # Sidebar: controls
    with st.sidebar:
        st.header("Controls")

        show_names = [s["name"] for s in shows]
        selected_show = st.selectbox("Show", show_names, index=0)
        show_config = next(s for s in shows if s["name"] == selected_show)

        st.divider()
        st.header("Scoring Weights")
        st.caption("Adjust weights and re-score on next load")

        weight_keys = list(SCORING_WEIGHTS.keys())
        new_weights = {}
        for key in weight_keys:
            new_weights[key] = st.slider(
                key.replace("_", " ").title(),
                min_value=0.0,
                max_value=0.50,
                value=SCORING_WEIGHTS[key],
                step=0.01,
                format="%.2f",
            )

        if st.button("Apply Weights", type="primary"):
            SCORING_WEIGHTS.update(new_weights)
            st.success("Weights updated! Reload images to see effect.")

        st.divider()
        st.header("Data")
        if st.button("Export Labels"):
            _save_labels(labels)
            st.success(f"Saved {len(labels)} labels to {LABELS_FILE}")
            st.code(f"cp {LABELS_FILE} ./training_labels.json")

        if st.button("Clear Cache"):
            shutil.rmtree(CACHE_DIR, ignore_errors=True)
            CACHE_DIR.mkdir(exist_ok=True)
            st.success("Cache cleared")
            st.rerun()

        total_labels = len(labels)
        good_count = sum(1 for v in labels.values() if v == "good")
        bad_count = sum(1 for v in labels.values() if v == "bad")
        st.metric("Total Labels", total_labels)
        col1, col2 = st.columns(2)
        col1.metric("Good", good_count, delta=None)
        col2.metric("Bad", bad_count, delta=None)

    # Main content
    st.title(f"🦞 {selected_show} — Image Scoring Debug")

    characters = show_config.get("characters", [])
    if not characters:
        st.warning("No characters defined for this show.")
        return

    # Character tabs
    char_tabs = st.tabs([f"{name} ({height}cm)" for name, height, _ in characters])

    for tab_idx, (name, height, wiki_page) in enumerate(characters):
        with char_tabs[tab_idx]:
            st.subheader(f"{name} — {height}cm")

            # Load candidates
            with st.spinner("Loading candidates..."):
                candidates_raw = gather_candidates(
                    name,
                    wiki=show_config["wiki"],
                    wiki_page=wiki_page,
                    show_name=show_config["name"],
                    show_search_term=show_config.get("anilist_search", ""),
                    max_fandom=8,
                    max_rembg=8,
                )

            if not candidates_raw:
                st.warning("No candidates found.")
                continue

            st.caption(f"{len(candidates_raw)} candidates from all sources")

            # Process each candidate
            cols_per_row = 4
            rows = [
                candidates_raw[i : i + cols_per_row]
                for i in range(0, len(candidates_raw), cols_per_row)
            ]

            for row in rows:
                row_cols = st.columns(len(row))
                for col_idx, candidate in enumerate(row):
                    with row_cols[col_idx]:
                        url = candidate["url"]
                        key = _image_key(url)

                        # Download + process
                        raw_img, proc_img = _download_and_process(url, key)

                        if raw_img is None:
                            st.error("Download failed")
                            continue

                        # Display images
                        display_col1, display_col2 = st.columns(2)
                        with display_col1:
                            st.image(raw_img, caption="Raw", use_container_width=True)
                        with display_col2:
                            if proc_img:
                                st.image(proc_img, caption="BG Removed", use_container_width=True)
                            else:
                                st.warning("BG removal failed")

                        # Classification
                        label_key = f"{selected_show}:{name}:{key}"
                        current_label = labels.get(label_key, "unlabeled")

                        col_a, col_b, col_c = st.columns(3)
                        if col_a.button(
                            "👍 Good",
                            key=f"good_{key}",
                            type="primary" if current_label == "good" else "secondary",
                        ):
                            labels[label_key] = "good"
                            _save_labels(labels)
                            st.rerun()
                        if col_b.button(
                            "👎 Bad",
                            key=f"bad_{key}",
                            type="primary" if current_label == "bad" else "secondary",
                        ):
                            labels[label_key] = "bad"
                            _save_labels(labels)
                            st.rerun()
                        if col_c.button(
                            "⏭ Skip",
                            key=f"skip_{key}",
                            type="primary" if current_label == "skip" else "secondary",
                        ):
                            labels[label_key] = "skip"
                            _save_labels(labels)
                            st.rerun()

                        # Show metrics if we have a processed image
                        if proc_img:
                            try:
                                hf = height_fill(proc_img)
                                cr = content_ratio(proc_img)
                                pose = check_full_body(proc_img)
                                features = compute_all_features(proc_img)

                                st.caption(
                                    f"Q={candidate.get('quality_score', '?'):.2f} "
                                    f"HF={hf:.2f} CR={cr:.2f} "
                                    f"CV={features['color_variance']:.2f} "
                                    f"Sym={features['symmetry']:.2f} "
                                    f"Edge={features['edge_smoothness']:.2f}"
                                )
                                st.caption(
                                    f"3rds: T={features['top_third']:.2f} "
                                    f"M={features['middle_third']:.2f} "
                                    f"B={features['bottom_third']:.2f} "
                                    f"{'✅' if features['all_thirds_present'] else '❌'} "
                                    f"Pose: {'✅' if pose['full_body'] else '❌'}"
                                )
                            except Exception as e:
                                st.caption(f"Metrics error: {e}")

                        st.caption(
                            f"Source: {candidate['source']} ({candidate['source_score']:.1f})"
                        )
                        if current_label != "unlabeled":
                            emoji = {"good": "👍", "bad": "👎", "skip": "⏭"}[current_label]
                            st.caption(f"Labeled: {emoji} {current_label}")


if __name__ == "__main__":
    main()
