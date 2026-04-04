#!/usr/bin/env python3
"""Debug: image scoring and quality filters — test against real wiki images.

For each character:
1. Gets all images from their wiki page
2. Applies name match + BAD_IMAGE_KEYWORDS filter (same as find_best_image)
3. Scores each remaining candidate via _score_image_url
4. Downloads top candidates
5. Runs bg removal + content_ratio + height_fill quality checks
6. Calls find_best_image to show what the pipeline would actually pick

Usage:
    cd vidforge
    python -m vidforge.debug.character_pipeline.images <wiki> <character_page> [max_inspect]

max_inspect limits how many top-scored candidates get downloaded and
bg-removed (the expensive part). All images are scored regardless.

Examples:
    python -m vidforge.debug.character_pipeline.images dragonball.fandom.com Goku
    python -m vidforge.debug.character_pipeline.images onepunchman.fandom.com Saitama 15
    python -m vidforge.debug.character_pipeline.images attackontitan.fandom.com Levi_Ackerman 5
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from vidforge.assets.bg_remove import content_ratio
from vidforge.assets.bg_remove import height_fill
from vidforge.assets.bg_remove import remove_background
from vidforge.assets.images import download_image
from vidforge.debug import ReportBuilder
from vidforge.debug import upload_file
from vidforge.sources.fandom import BAD_IMAGE_KEYWORDS
from vidforge.sources.fandom import _score_image_url
from vidforge.sources.fandom import find_best_image
from vidforge.sources.fandom import get_image_url
from vidforge.sources.fandom import get_page_images

# Thresholds from vidforge.assets.images.fetch_and_process_image
MAX_CONTENT_RATIO = 0.75
MIN_HEIGHT_FILL = 0.55


def _passes_filters(fname: str, name_parts: list[str]) -> bool:
    """Check if an image passes name match + bad keyword filters."""
    fname_lower = fname.lower().replace("_", " ").replace("-", " ")
    has_name = any(p in fname_lower for p in name_parts if len(p) > 2)
    return has_name and not any(kw in fname_lower for kw in BAD_IMAGE_KEYWORDS)


def main() -> None:
    args = sys.argv[1:]
    if len(args) < 2:
        print("Usage: debug_images.py <wiki> <character_page> [max_inspect]")
        print("Example: debug_images.py dragonball.fandom.com Goku")
        sys.exit(1)

    wiki = args[0]
    page = args[1]
    max_inspect = int(args[2]) if len(args) > 2 else 10
    name_parts = page.lower().replace("_", " ").split()

    report = ReportBuilder(
        f"Image Scoring Debug — {page}",
        f"Wiki: {wiki} | Testing image scoring, bg removal, and quality filters",
    )
    report.add_meta("wiki", wiki)
    report.add_meta("page", page)
    report.add_meta("max_content_ratio", str(MAX_CONTENT_RATIO))
    report.add_meta("min_height_fill", str(MIN_HEIGHT_FILL))

    # ── Get all images from the page ─────────────────────────────────────
    print(f"Fetching images for {page} from {wiki}...", flush=True)
    images = get_page_images(wiki, page)
    images_section = report.add_section(f"Page Images ({len(images)} found)")
    for fname in images[:30]:
        images_section.add_status(fname, ok=True)

    if not images:
        report.add_summary({"images_found": "0", "status": "no images on page"})
        url = report.upload()
        print(f"Report: {url}" if url else "Upload failed")
        return

    # ── Apply name + keyword filters, then score ─────────────────────────
    print(f"\nScoring all {len(images)} images (with name+keyword filters)...", flush=True)
    score_rows: list[list[str]] = [["Filename", "Score", "Filtered"]]

    passed_filter: list[tuple[float, str, str]] = []  # (score, fname, url)
    filtered_out: list[str] = []

    for fname in images:
        url = get_image_url(wiki, fname)
        if not url:
            continue

        if not _passes_filters(fname, name_parts):
            filtered_out.append(fname[:60])
            continue

        score = _score_image_url(url)
        passed_filter.append((score, fname, url))
        score_rows.append([fname[:50], f"{score:.1f}", "✅"])
        time.sleep(0.1)

    passed_filter.sort(key=lambda x: -x[0])

    score_section = report.add_section(
        f"Scored Images ({len(passed_filter)} passed filters, {len(filtered_out)} filtered out)"
    )
    score_section.add_table(score_rows[0], score_rows[1:])

    if filtered_out:
        filt_section = report.add_section(f"Filtered Out ({len(filtered_out)})")
        for f in filtered_out[:20]:
            filt_section.add_status(f, ok=False)

    if not passed_filter:
        report.add_summary(
            {
                "images_found": str(len(images)),
                "passed_filters": "0",
                "status": "no candidates passed name+keyword filters",
            }
        )
        url = report.upload()
        print(f"Report: {url}" if url else "Upload failed")
        return

    # ── Download and inspect top candidates ──────────────────────────────
    inspect_count = min(len(passed_filter), max_inspect)
    print(f"\nInspecting top {inspect_count} candidates (bg removal)...", flush=True)
    download_ok = 0
    download_fail = 0
    pass_quality = 0
    fail_quality = 0

    for score, fname, url in passed_filter[:max_inspect]:
        print(f"  [{score:.1f}] {fname[:40]}...", end=" ", flush=True)
        section = report.add_section(f"Score {score:.1f} — {fname[:60]}")
        section.add_stat("filename", fname)
        section.add_stat("score", f"{score:.1f}")
        section.add_stat("url", url[:80])

        img = download_image(url)
        if not img:
            section.add_status("Download failed", ok=False)
            download_fail += 1
            print("download failed", flush=True)
            continue

        section.add_stat("size", f"{img.width}x{img.height}")
        section.add_stat("aspect", f"{img.width / img.height:.2f}")
        download_ok += 1

        # Upload original
        orig_path = Path(f"/tmp/vf_debug_{fname.replace('/', '_')}.png")
        img.save(orig_path)
        orig_url = upload_file(orig_path)
        if orig_url:
            section.add_image(orig_url, "original")

        # Quality checks (before bg removal)
        cr = content_ratio(img)
        hf = height_fill(img)
        aspect = img.width / img.height
        effective_cr_max = MAX_CONTENT_RATIO if aspect >= 0.6 else 0.90

        section.add_stat("size", f"{img.width}x{img.height}")
        section.add_stat("aspect", f"{aspect:.2f}")
        section.add_stat("content_ratio", f"{cr:.3f} (max {effective_cr_max:.2f})")
        section.add_stat("height_fill", f"{hf:.3f} (min {MIN_HEIGHT_FILL})")

        cr_ok = cr <= effective_cr_max
        hf_ok = hf >= MIN_HEIGHT_FILL
        section.add_status(f"content_ratio: {cr:.3f} {'✅' if cr_ok else '❌ too wide'}", ok=cr_ok)
        section.add_status(f"height_fill: {hf:.3f} {'✅' if hf_ok else '❌ too short'}", ok=hf_ok)

        # Try bg removal
        print(f"dl={img.width}x{img.height}", end=" ", flush=True)
        processed = remove_background(img)
        if processed:
            proc_path = Path(f"/tmp/vf_debug_proc_{fname.replace('/', '_')}.png")
            processed.save(proc_path)
            proc_url = upload_file(proc_path)
            if proc_url:
                section.add_image(proc_url, "bg removed")
            section.add_status("Background removal OK", ok=True)

            # Re-check quality after bg removal
            cr2 = content_ratio(processed)
            hf2 = height_fill(processed)
            aspect2 = processed.width / processed.height if processed.height else 99.0
            effective_cr_max2 = MAX_CONTENT_RATIO if aspect2 >= 0.6 else 0.90
            section.add_stat("post_bg_content_ratio", f"{cr2:.3f}")
            section.add_stat("post_bg_height_fill", f"{hf2:.3f}")

            if cr2 <= effective_cr_max2 and hf2 >= MIN_HEIGHT_FILL:
                pass_quality += 1
                print("✅ pass", flush=True)
            else:
                fail_quality += 1
                reason = []
                if cr2 > MAX_CONTENT_RATIO:
                    reason.append(f"cr={cr2:.2f}")
                if hf2 < MIN_HEIGHT_FILL:
                    reason.append(f"hf={hf2:.2f}")
                section.add_status(f"Rejected after bg removal: {', '.join(reason)}", ok=False)
                print(f"❌ rejected ({', '.join(reason)})", flush=True)
        else:
            section.add_status("Background removal failed", ok=False)
            fail_quality += 1
            print("❌ bg removal failed", flush=True)

        time.sleep(0.5)

    # ── Show what find_best_image would pick ─────────────────────────────
    print("\nRunning find_best_image()...", flush=True)
    pipeline_url = find_best_image(wiki, page)
    pipeline_section = report.add_section("Pipeline Result (find_best_image)")
    if pipeline_url:
        pipeline_section.add_status(f"Would pick: {pipeline_url[:80]}", ok=True)

        # Check if any of our inspected images match
        matched = any(url == pipeline_url for _, _, url in passed_filter[:max_inspect])
        if not matched:
            pipeline_section.add_status(
                "⚠️ Pipeline pick was NOT in our inspected set — "
                "it may have been filtered by content checks in fetch_and_process_image",
                ok=False,
            )
    else:
        pipeline_section.add_status("find_best_image returned None", ok=False)

    report.add_summary(
        {
            "Images on page": str(len(images)),
            "Passed filters": str(len(passed_filter)),
            "Filtered out": str(len(filtered_out)),
            "Downloaded OK": str(download_ok),
            "Download failed": str(download_fail),
            "Passed quality": str(pass_quality),
            "Failed quality": str(fail_quality),
            "Pipeline pick": pipeline_url[:80] if pipeline_url else "None",
        }
    )

    print("\nUploading report...", flush=True)
    url = report.upload()
    if url:
        print(f"Report: {url}")
    else:
        local = report.save("/tmp/vidforge_debug_images.html")
        print(f"Local: {local}")


if __name__ == "__main__":
    main()
