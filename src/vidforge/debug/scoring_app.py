"""Streamlit debug app — pick the best image per character.

Pre-fetched data, instant loading. Pick winner per character with radio buttons.
Saves automatically on each pick.

Run: uv run streamlit run src/vidforge/debug/scoring_app.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import streamlit as st

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


st.set_page_config(page_title="VidForge Image Picker", layout="wide")

CACHE_DIR = Path("/tmp/vf_streamlit_cache")
DATA_FILE = CACHE_DIR / "prefetched.json"
PICKS_FILE = CACHE_DIR / "picks.json"


def _get_shows() -> list[dict[str, Any]]:
    from vidforge.generators.heights.debug.scaling import SHOWS

    return SHOWS


def _load_picks() -> dict[str, Any]:
    if PICKS_FILE.exists():
        try:
            return json.loads(PICKS_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_picks(picks: dict[str, Any]) -> None:
    PICKS_FILE.write_text(json.dumps(picks, indent=2))


def main() -> None:
    # Load pre-fetched data
    if not DATA_FILE.exists():
        st.error("No pre-fetched data. Run: uv run python3 src/vidforge/debug/prefetch.py")
        st.stop()

    data = json.loads(DATA_FILE.read_text())
    shows = _get_shows()

    # Initialize picks in session state so they persist across reruns
    if "picks" not in st.session_state:
        st.session_state.picks = _load_picks()

    st.title("🦞 VidForge — Pick the Best Image")

    # Sidebar
    with st.sidebar:
        show_names = [s["name"] for s in shows if s["name"] in data]
        if not show_names:
            st.warning("No pre-fetched shows.")
            st.stop()

        selected_show = st.selectbox("Show", show_names)

        total_picks = len(st.session_state.picks)
        shows_done = sum(
            1 for sn in show_names if any(k.startswith(sn + ":") for k in st.session_state.picks)
        )
        total_chars = sum(len(data.get(sn, {})) for sn in show_names)
        st.metric("Picks", f"{total_picks}/{total_chars}")
        st.metric("Shows Done", f"{shows_done}/{len(show_names)}")

        st.divider()
        if st.button("💾 Save to Disk"):
            _save_picks(st.session_state.picks)
            st.success(f"Saved {total_picks} picks to disk")

        if st.button("Export JSON"):
            _save_picks(st.session_state.picks)
            st.code(str(PICKS_FILE))

        if st.button("Clear Cache"):
            shutil.rmtree(CACHE_DIR, ignore_errors=True)
            CACHE_DIR.mkdir(exist_ok=True)
            st.success("Cleared. Re-run prefetch.py")

    show_config = next(s for s in shows if s["name"] == selected_show)
    show_data = data.get(selected_show, {})
    characters = show_config.get("characters", [])

    for _tab_idx, (name, height, _wiki_page) in enumerate(characters):
        pick_key = f"{selected_show}:{name}"
        char_data = show_data.get(name)
        if not char_data or not char_data.get("candidates"):
            continue

        candidates = char_data["candidates"]
        algo_pick_idx = char_data.get("algo_pick_idx", 0)

        # Get current pick (from session state or algo default)
        current_pick = st.session_state.picks.get(pick_key, {}).get("winner_idx", algo_pick_idx)
        if current_pick >= len(candidates):
            current_pick = algo_pick_idx

        with st.expander(f"**{name}** ({height}cm) — {len(candidates)} candidates", expanded=True):
            # Radio buttons to pick winner
            options = [
                f"#{i + 1} {c['source']} (Q={c.get('q_score', 0):.2f})"
                for i, c in enumerate(candidates)
            ]
            selected = st.radio(
                "Pick the best:",
                range(len(candidates)),
                index=current_pick,
                format_func=lambda i, opts=options: opts[i],
                key=f"radio_{pick_key}",
                horizontal=True,
            )

            # Auto-save pick on change
            if selected != current_pick:
                st.session_state.picks[pick_key] = {
                    "winner_idx": selected,
                    "winner_url": candidates[selected]["url"],
                }
                _save_picks(st.session_state.picks)
                st.rerun()

            # Show candidate images in a grid
            cols = st.columns(min(len(candidates), 4))
            for i, c in enumerate(candidates):
                with cols[i % len(cols)]:
                    is_picked = i == selected
                    is_algo = i == algo_pick_idx

                    if is_picked:
                        st.markdown("### ✅ YOUR PICK")
                    elif is_algo:
                        st.markdown("#### 🤖 Algo pick")

                    proc_path = CACHE_DIR / f"{c['key']}_proc.png"
                    raw_path = CACHE_DIR / f"{c['key']}_raw.png"

                    if proc_path.exists():
                        st.image(str(proc_path), width=200)
                    elif raw_path.exists():
                        st.image(str(raw_path), width=200)
                    else:
                        st.warning("Missing")

                    f = c.get("features", {})
                    st.caption(
                        f"Q={c.get('q_score', 0):.2f} "
                        f"HF={c.get('hf', 0):.2f} "
                        f"CR={c.get('cr', 0):.2f} "
                        f"CV={f.get('color_variance', 0):.2f} "
                        f"Sym={f.get('symmetry', 0):.2f} "
                        f"Edge={f.get('edge_smoothness', 0):.2f}"
                    )
                    pose_ok = "✅" if c.get("pose", {}).get("full_body") else "❌"
                    thirds_ok = "✅" if f.get("all_thirds_present") else "❌"
                    st.caption(f"Pose={pose_ok} 3rds={thirds_ok}")


if __name__ == "__main__":
    main()
