#!/usr/bin/env python3
"""Debug: character discovery — test discover_characters and height fetching.

Shows what pages the wiki search returns, which ones get filtered by skip words,
which ones have parseable heights, and which are missed.

Usage:
    cd vidforge
    python scripts/debug_discovery.py <wiki> [max_pages]

Examples:
    python scripts/debug_discovery.py dragonball.fandom.com
    python scripts/debug_discovery.py onepunchman.fandom.com 50
"""

from __future__ import annotations

import sys
import time
from typing import Any

from vidforge.debug import ReportBuilder
from vidforge.sources.fandom import SKIP_WORDS
from vidforge.sources.fandom import _api
from vidforge.sources.fandom import discover_characters
from vidforge.sources.fandom import get_height


def main() -> None:
    args = sys.argv[1:]
    if len(args) < 1:
        print("Usage: debug_discovery.py <wiki> [max_pages]")
        sys.exit(1)

    wiki = args[0]
    max_pages = int(args[1]) if len(args) > 1 else 50

    report = ReportBuilder(
        f"Character Discovery Debug — {wiki}",
        "Testing wiki search, skip word filtering, and height parsing",
    )
    report.add_meta("wiki", wiki)
    report.add_meta("max_pages", str(max_pages))

    # ── Raw discovery (bypass skip words to see everything) ──────────────
    print(f"Searching {wiki} for height data...", flush=True)

    raw_pages: list[dict[str, Any]] = []
    offset = 0

    while len(raw_pages) < max_pages:
        try:
            data = _api(
                wiki,
                {
                    "action": "query",
                    "list": "search",
                    "srsearch": 'insource:"|height" insource:"cm"',
                    "srnamespace": 0,
                    "srlimit": 50,
                    "sroffset": offset,
                },
            )
        except Exception as e:
            print(f"  API error: {e}", flush=True)
            break

        results = data.get("query", {}).get("search", [])
        if not results:
            break

        for r in results:
            title = r["title"]
            # Find which skip word (if any) filters it
            filtered_by = None
            if len(title) > 40:
                filtered_by = "length > 40"
            else:
                for sw in SKIP_WORDS:
                    if sw in title.lower():
                        filtered_by = f'"{sw}"'
                        break

            raw_pages.append(
                {
                    "title": title,
                    "filtered_by": filtered_by or "",
                    "filtered": filtered_by is not None,
                    "height": None,  # placeholder
                }
            )

        if len(results) < 50:
            break
        offset += 50
        time.sleep(0.3)

    print(f"  {len(raw_pages)} raw results", flush=True)

    # ── Check heights for non-filtered pages ─────────────────────────────
    print("Checking heights...", flush=True)
    for page_data in raw_pages:
        if page_data["filtered"]:
            continue
        title = page_data["title"]
        h = get_height(wiki, title)
        page_data["height"] = h
        time.sleep(0.15)

    # ── Build report ─────────────────────────────────────────────────────
    # Filtered out
    filtered = [p for p in raw_pages if p["filtered"]]
    passed_filter = [p for p in raw_pages if not p["filtered"]]
    with_height = [p for p in passed_filter if p["height"] is not None]
    no_height = [p for p in passed_filter if p["height"] is None]

    # Section: filtered out
    if filtered:
        filt_section = report.add_section(f"Filtered Out ({len(filtered)})")
        filt_rows = [["Title", "Filtered by"]]
        for p in filtered[:30]:
            filt_rows.append([p["title"], p["filtered_by"]])
        filt_section.add_table(filt_rows[0], filt_rows[1:])

    # Section: passed filter, has height
    if with_height:
        height_section = report.add_section(f"Characters with Height ({len(with_height)})")
        height_rows = [["Title", "Height (cm)", "Height (m)"]]
        for p in sorted(with_height, key=lambda x: x["height"] or 0):
            h = p["height"]
            h_m = f"{h / 100:.2f}" if h and h >= 100 else str(h)
            height_rows.append([p["title"], str(h), h_m])
        height_section.add_table(height_rows[0], height_rows[1:])

    # Section: passed filter, no height
    if no_height:
        no_h_section = report.add_section(f"Passed Filter, No Height ({len(no_height)})")
        for p in no_height[:20]:
            no_h_section.add_status(p["title"], ok=False)

    # Compare with discover_characters
    print("Running discover_characters (official)...", flush=True)
    discovered = discover_characters(wiki, max_pages=max_pages)
    disc_section = report.add_section(f"discover_characters() returned {len(discovered)}")
    for page in discovered:
        disc_section.add_status(page, ok=True)

    # Show what discover_characters missed that we found
    official_set = set(discovered)
    our_set = {p["title"] for p in with_height}
    missed = our_set - official_set
    extra = official_set - our_set

    if missed:
        miss_section = report.add_section(f"discover_characters MISSED ({len(missed)})")
        for title in missed:
            h = next(p["height"] for p in with_height if p["title"] == title)
            miss_section.add_status(f"{title} ({h}cm)", ok=False)

    if extra:
        extra_section = report.add_section(f"discover_characters EXTRA ({len(extra)})")
        for title in extra:
            extra_section.add_status(title, ok=True)

    report.add_summary(
        {
            "Raw search results": str(len(raw_pages)),
            "Filtered out": str(len(filtered)),
            "Passed filter": str(len(passed_filter)),
            "With parseable height": str(len(with_height)),
            "No height (missing field)": str(len(no_height)),
            "discover_characters() returned": str(len(discovered)),
            "Missed by discover": str(len(missed)),
        }
    )

    print("\nUploading report...", flush=True)
    url = report.upload()
    if url:
        print(f"Report: {url}")
    else:
        local = report.save("/tmp/vidforge_debug_discovery.html")
        print(f"Local: {local}")


if __name__ == "__main__":
    main()
