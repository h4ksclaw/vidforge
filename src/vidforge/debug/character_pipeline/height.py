#!/usr/bin/env python3
"""Debug: height extraction — test parse_height against real wiki data and edge cases.

Fetches actual wikitext from character pages, extracts the raw height field,
and shows what parse_height returns vs what we'd expect.

Usage:
    cd vidforge
    python scripts/debug_heights.py [wiki] [character_page ...]

Examples:
    python scripts/debug_heights.py dragonball.fandom.com Goku Vegeta Frieza
    python scripts/debug_heights.py onepunchman.fandom.com Saitama Genos
    python scripts/debug_heights.py bleach.fandom.com Ichigo_Kurosaki
"""

from __future__ import annotations

import re
import sys
import time

from vidforge.debug import ReportBuilder
from vidforge.sources.fandom import _api, parse_height


def get_raw_height_field(wiki: str, page: str) -> str | None:
    """Extract the raw | height = ... field from a wiki page's wikitext."""
    try:
        data = _api(wiki, {"action": "parse", "page": page, "prop": "wikitext"})
        text = data["parse"]["wikitext"]["*"]
        match = re.search(r"\|\s*height\s*=\s*(.+?)(?:\||\n|\})", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    except Exception:
        pass
    return None


# Known edge cases to always test
EDGE_CASES: list[tuple[str, str | None, int | None]] = [
    ("175 cm", "standard cm", 175),
    ("175cm", "no space", 175),
    ("1.75 m", "meters decimal", 175),
    ("1.75m", "meters no space", 175),
    ("5'9\"", "feet inches", 175),
    ("5 feet 9 inches", "feet inches text", 175),
    ("6'0", "feet only", 182),
    ("175", "bare cm", 175),
    ("1.75", "bare meters", 175),
    ("unknown", "unknown", None),
    ("?", "question mark", None),
    ("", "empty", None),
    ("188 centimeters", "centimeters full word", None),  # known gap
    ("Approx. 175 cm", "with prefix", 175),
    ("<ref>source</ref>175 cm", "with ref tag", 175),
    ("{{height|175}}", "template (stripped)", None),
    ("500 cm", "giant", 500),
    ("15 cm", "too small", None),
    ("5000 cm", "too big", None),
]


def main() -> None:
    args = sys.argv[1:]
    if len(args) < 1:
        print("Usage: debug_heights.py <wiki> [page1 page2 ...]")
        print("Example: debug_heights.py dragonball.fandom.com Goku Vegeta")
        sys.exit(1)

    wiki = args[0]
    pages = args[1:]

    report = ReportBuilder(
        f"Height Extraction Debug — {wiki}",
        "parse_height tested against real wiki wikitext and edge cases",
    )
    report.add_meta("wiki", wiki)
    report.add_meta("pages", ", ".join(pages) if pages else "none (edge cases only)")

    # ── Edge cases ───────────────────────────────────────────────────────
    edge_section = report.add_section("Edge Cases")
    edge_rows: list[list[str]] = [["Input", "Expected", "Got", "Status"]]
    edge_ok = 0
    edge_fail = 0

    for raw, _label, expected in EDGE_CASES:
        got = parse_height(raw)
        match = got == expected
        status = "✅" if match else "❌"
        if match:
            edge_ok += 1
        else:
            edge_fail += 1
        edge_rows.append(
            [
                f"{raw!r}",
                str(expected) if expected is not None else "None",
                str(got) if got is not None else "None",
                status,
            ]
        )
    edge_section.add_table(edge_rows[0], edge_rows[1:])

    # ── Real wiki pages ──────────────────────────────────────────────────
    if not pages:
        print("No pages specified, testing edge cases only.")
        print("Usage: debug_heights.py <wiki> [page1 page2 ...]")
        report.add_summary(
            {
                "Edge cases passed": str(edge_ok),
                "Edge cases failed": str(edge_fail),
            }
        )
        url = report.upload()
        if url:
            print(f"Report: {url}")
        return

    wiki_section = report.add_section("Real Wiki Data")
    wiki_rows: list[list[str]] = [["Page", "Raw field", "Parsed (cm)", "Status"]]
    wiki_ok = 0
    wiki_fail = 0

    for page in pages:
        print(f"  {page}...", end=" ", flush=True)
        raw_field = get_raw_height_field(wiki, page)
        parsed = parse_height(raw_field) if raw_field else None

        if parsed is not None:
            status = "✅"
            wiki_ok += 1
        else:
            status = "❌ no parse"
            wiki_fail += 1

        # Show raw field as code in a sub-section for inspection
        page_section = report.add_section(page)
        if raw_field:
            page_section.add_code(raw_field, "Raw wikitext height field")
        else:
            page_section.add_status("No | height = field found on page", ok=False)

        page_section.add_stat("raw_field", (raw_field or "none")[:80])
        page_section.add_stat("parsed", f"{parsed}cm" if parsed else "None")
        page_section.add_status(
            f"Parsed: {parsed}cm" if parsed else "Failed to parse", ok=parsed is not None
        )

        wiki_rows.append(
            [
                page,
                (raw_field or "none")[:50],
                str(parsed) if parsed else "None",
                status,
            ]
        )
        print(f"{'✅ ' + str(parsed) + 'cm' if parsed else '❌'}", flush=True)
        time.sleep(0.3)

    wiki_section.add_table(wiki_rows[0], wiki_rows[1:])

    report.add_summary(
        {
            "Edge cases": f"{edge_ok}/{edge_ok + edge_fail}",
            "Wiki pages": f"{wiki_ok}/{wiki_ok + wiki_fail}",
            "Total passed": str(edge_ok + wiki_ok),
            "Total failed": str(edge_fail + wiki_fail),
        }
    )

    print("\nUploading report...", flush=True)
    url = report.upload()
    if url:
        print(f"Report: {url}")
    else:
        local = report.save("/tmp/vidforge_debug_heights.html")
        print(f"Local: {local}")


if __name__ == "__main__":
    main()
