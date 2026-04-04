#!/usr/bin/env python3
"""Debug: scaling visualizer — test height extraction + image scaling for multiple shows.

For each show:
1. Fetches characters with real heights from the wiki
2. Downloads and processes images (bg removal)
3. Renders a scaled comparison strip showing how the pipeline scales them
4. Marks actual pixel heights, raw cm, and scale factor

This is a live test — real APIs, real images, real processing.
The output is a visual HTML paste showing the scaling for each show.

Usage:
    cd vidforge
    python scripts/debug_scaling.py

Takes no arguments — tests all configured shows.
Use --limit N to test only the first N shows.
"""

from __future__ import annotations

import argparse
import gc
import time
from pathlib import Path

import numpy as np
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

from vidforge.assets.bg_remove import content_ratio
from vidforge.assets.bg_remove import height_fill
from vidforge.assets.bg_remove import remove_background
from vidforge.assets.images import download_image
from vidforge.assets.images import fetch_and_process_image
from vidforge.debug import ReportBuilder
from vidforge.debug import upload_file
from vidforge.models import Item
from vidforge.sources.fandom import find_best_image

# Pipeline scaling constants (from vidforge.pipeline.render_strip)
MARGIN_BOTTOM = 130
MARGIN_TOP = 80
STRIP_HEIGHT = 800  # target strip height for the debug render
AVAILABLE_H = STRIP_HEIGHT - MARGIN_BOTTOM - MARGIN_TOP
SCALE_FACTOR = 0.82  # 82% of available height used by tallest character

# Shows to test — (wiki, character_pages with known heights)
# Using small subsets (5-8 chars) so the debug run is fast
SHOWS: list[dict] = [
    {
        "name": "Dragon Ball Z",
        "wiki": "dragonball.fandom.com",
        "characters": [
            ("Krillin", 153, "Krillin"),
            ("Frieza", 158, "Frieza"),
            ("Vegeta", 164, "Vegeta"),
            ("Goku", 175, "Goku"),
            ("Gohan", 176, "Gohan"),
            ("Piccolo", 226, "Piccolo"),
            ("Cell", 210, "Cell"),
        ],
    },
    {
        "name": "Naruto",
        "wiki": "naruto.fandom.com",
        "characters": [
            ("Hinata", 163, "Hinata_Hyūga"),
            ("Sakura", 161, "Sakura_Haruno"),
            ("Naruto", 180, "Naruto_Uzumaki"),
            ("Sasuke", 168, "Sasuke_Uchiha"),
            ("Kakashi", 181, "Kakashi_Hatake"),
            ("Itachi", 178, "Itachi_Uchiha"),
        ],
    },
    {
        "name": "One Piece",
        "wiki": "onepiece.fandom.com",
        "characters": [
            ("Nami", 170, "Nami"),
            ("Luffy", 174, "Monkey_D._Luffy"),
            ("Zoro", 181, "Roronoa_Zoro"),
            ("Sanji", 177, "Sanji"),
            ("Jinbe", 301, "Jinbe"),
        ],
    },
    {
        "name": "Attack on Titan",
        "wiki": "attackontitan.fandom.com",
        "characters": [
            ("Levi", 160, "Levi_Ackerman"),
            ("Armin", 163, "Armin_Arlert"),
            ("Mikasa", 170, "Mikasa_Ackerman"),
            ("Eren", 170, "Eren_Yeager"),
            ("Erwin", 188, "Erwin_Smith"),
            ("Reiner", 185, "Reiner_Braun"),
        ],
    },
    {
        "name": "Jujutsu Kaisen",
        "wiki": "jujutsu-kaisen.fandom.com",
        "characters": [
            ("Nobara", 160, "Nobara_Kugisaki"),
            ("Maki", 170, "Maki_Zenin"),
            ("Yuji", 173, "Yuji_Itadori"),
            ("Megumi", 175, "Megumi_Fushiguro"),
            ("Gojo", 190, "Satoru_Gojo"),
        ],
    },
    {
        "name": "My Hero Academia",
        "wiki": "myheroacademia.fandom.com",
        "characters": [
            ("Tsuyu", 150, "Tsuyu_Asui"),
            ("Ochaco", 156, "Ochaco_Uraraka"),
            ("Midoriya", 166, "Izuku_Midoriya"),
            ("Bakugo", 172, "Katsuki_Bakugo"),
            ("Todoroki", 176, "Shoto_Todoroki"),
            ("All Might", 220, "All_Might"),
        ],
    },
    {
        "name": "Demon Slayer",
        "wiki": "kimetsu-no-yaiba.fandom.com",
        "characters": [
            ("Nezuko", 153, "Nezuko_Kamado"),
            ("Zenitsu", 164, "Zenitsu_Agatsuma"),
            ("Tanjiro", 165, "Tanjiro_Kamado"),
            ("Giyu", 176, "Giyu_Tomioka"),
            ("Rengoku", 177, "Kyojuro_Rengoku"),
        ],
    },
    {
        "name": "Death Note",
        "wiki": "deathnote.fandom.com",
        "characters": [
            ("Near", 155, "Near"),
            ("Mello", 171, "Mello"),
            ("L", 179, "L_(character)"),
            ("Light", 179, "Light_Yagami"),
            ("Soichiro", 182, "Soichiro_Yagami"),
            ("Teru Mikami", 187, "Teru_Mikami"),
        ],
    },
    {
        "name": "Bleach",
        "wiki": "bleach.fandom.com",
        "characters": [
            ("Rukia", 144, "Rukia_Kuchiki"),
            ("Orihime", 157, "Orihime_Inoue"),
            ("Ichigo", 181, "Ichigo_Kurosaki"),
            ("Byakuya", 180, "Byakuya_Kuchiki"),
            ("Kenpachi", 202, "Kenpachi_Zaraki"),
        ],
    },
    {
        "name": "One Punch Man",
        "wiki": "onepunchman.fandom.com",
        "characters": [
            ("Saitama", 175, "Saitama"),
            ("Genos", 178, "Genos"),
            ("Bang", 165, "Bang"),
            ("Fubuki", 166, "Fubuki"),
            ("Garou", 179, "Garou"),
        ],
    },
]

BAD_IMAGE_KEYWORDS = [
    "logo",
    "icon",
    "symbol",
    "flag",
    "map",
    "gif",
    "vs",
    "fight",
    "battle",
    "attack",
    "saga",
    "arc",
    "death",
    "kill",
    "manga panel",
    "chapter",
    "episode screenshot",
    "card",
    "stamp",
    "chibi",
    "sprite",
]


def diagnose_failure(wiki: str, wiki_page: str, name: str, img_url: str) -> str:
    """Run each pipeline step individually to find exactly where it fails.

    Mirrors the logic in vidforge.assets.images.fetch_and_process_image.
    Returns a human-readable failure reason.
    """
    # Step 1: Download
    img = download_image(img_url)
    if img is None:
        return "download failed"

    # Step 2: BG removal
    processed = remove_background(img)
    if processed is None:
        return "rembg failed"

    # Step 3: Quality checks (same thresholds as fetch_and_process_image)
    cr = content_ratio(processed)
    hf = height_fill(processed)

    reasons = []
    if cr > 0.75:
        reasons.append(f"content_ratio={cr:.3f} > 0.75")
    if hf < 0.55:
        reasons.append(f"height_fill={hf:.3f} < 0.55")

    if reasons:
        return ", ".join(reasons)

    return "unknown (passed all checks but no path returned)"


def _get_content_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Get bounding box of non-transparent content in an RGBA image.

    Returns (top, left, bottom, right) or None if no content.
    Uses the same logic as bg_remove.height_fill / content_ratio.
    """

    alpha = np.array(img.split()[3])
    binary = (alpha > 128).astype(np.uint8)
    rows = np.where(binary.max(axis=1))[0]
    cols = np.where(binary.max(axis=0))[0]
    if len(rows) == 0 or len(cols) == 0:
        return None
    return (int(rows[0]), int(cols[0]), int(rows[-1]), int(cols[-1]))


def render_scaling_strip(
    chars: list[dict],
    show_name: str,
) -> tuple[Path, dict]:
    """Render a visual strip showing scaled characters with content detection boxes.

    For each character with an image:
    - Draws the image scaled to the height target
    - Overlays a RED bounding box showing the detected content region
    - Shows where the pipeline thinks the character's head and feet are
    - Marks the height bar target vs actual content height

    Returns (strip_path, scale_info).
    chars: list of {"name", "height_cm", "img_path", "processed_url"}
    """
    if not chars:
        strip = Image.new("RGBA", (400, STRIP_HEIGHT), (10, 10, 20, 255))
        p = Path(f"/tmp/vf_scaling_{show_name.replace(' ', '_')}.png")
        strip.save(p)
        return p, {}

    chars_sorted = sorted(chars, key=lambda c: c["height_cm"])
    max_h = max(c["height_cm"] for c in chars_sorted)
    ground_y = STRIP_HEIGHT - MARGIN_BOTTOM
    scale = AVAILABLE_H * SCALE_FACTOR / max_h

    # Fonts
    try:
        font_name = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        font_ht = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        font_rank = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
        font_debug = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
    except OSError:
        font_name = font_ht = font_rank = font_debug = ImageFont.load_default()

    # Calculate widths
    gap = 60
    pad = 200
    char_widths: list[int] = []
    for c in chars_sorted:
        bar_h = int(c["height_cm"] * scale)
        img_path = c.get("img_path")
        if img_path and Path(img_path).exists():
            img = Image.open(img_path)
            ratio = img.width / img.height
            char_w = max(int(bar_h * ratio) + 30, 140)
        else:
            char_w = 100
        char_widths.append(char_w)

    total_w = sum(char_widths) + (len(chars_sorted) - 1) * gap + pad * 2

    # Build strip
    strip = Image.new("RGBA", (total_w, STRIP_HEIGHT), (10, 10, 20, 255))
    sd = ImageDraw.Draw(strip)

    # Ground line
    sd.line([(pad - 50, ground_y), (total_w - pad + 50, ground_y)], fill=(60, 55, 75, 220), width=2)

    # Height grid lines
    step = 50
    for h_cm in range(100, int(max_h * 1.15) + step, step):
        y = ground_y - int(h_cm * scale)
        if y < MARGIN_TOP - 10:
            break
        is_major = (h_cm % 100) == 0
        alpha = 60 if is_major else 30
        sd.line([(pad - 50, y), (total_w - pad + 50, y)], fill=(55, 50, 70, alpha), width=1)
        if is_major:
            lbl = f"{h_cm / 100:.1f}m" if h_cm >= 500 else f"{h_cm}cm"
            bbox = sd.textbbox((0, 0), lbl, font=font_ht)
            tw = bbox[2] - bbox[0]
            sd.text((pad - 60 - tw, y - 8), lbl, fill=(80, 75, 95, 160), font=font_ht)

    # Draw characters
    RED = (255, 50, 50)
    GREEN = (50, 255, 100)
    YELLOW = (255, 255, 50)
    accent = (255, 165, 0)
    x = pad
    scale_details: list[dict] = []

    for i, c in enumerate(chars_sorted):
        bar_h = int(c["height_cm"] * scale)
        img_path = c.get("img_path")
        x_center = x + char_widths[i] // 2

        # Height bar indicator (dashed line from ground to target height)
        sd.line([(x_center, ground_y - bar_h), (x_center, ground_y)], fill=(*accent, 60), width=1)

        # Target height marker at top (orange)
        sd.line(
            [(x_center - 8, ground_y - bar_h), (x_center + 8, ground_y - bar_h)],
            fill=(*accent, 200),
            width=2,
        )

        detail = {
            "name": c["name"],
            "height_cm": c["height_cm"],
            "bar_h": bar_h,
            "has_image": False,
            "content_bbox": None,
            "content_h_px": 0,
            "content_fill": 0.0,
            "content_ratio": 0.0,
            "scale_used": 0.0,
        }

        if img_path and Path(img_path).exists():
            img = Image.open(img_path)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            detail["has_image"] = True

            # Get content bounding box (same detection as pipeline quality checks)
            content = _get_content_bbox(img)

            img_ratio = img.width / img.height
            new_h = bar_h
            new_w = int(bar_h * img_ratio)
            if new_w > char_widths[i] - 30:
                new_w = char_widths[i] - 30
                new_h = int(new_w / img_ratio)

            if new_h > 5 and new_w > 5:
                img_r = img.resize((new_w, new_h), Image.LANCZOS)
                x_off = x_center - new_w // 2
                y_off = ground_y - bar_h + (bar_h - new_h)
                strip.paste(img_r, (x_off, y_off), img_r)

                # Draw RED bounding box for content detection
                if content:
                    top, left, bottom, right = content
                    orig_h = img.height
                    orig_w = img.width

                    # Scale content bbox to the resized image coordinates
                    scale_x = new_w / orig_w
                    scale_y = new_h / orig_h
                    box_left = int(x_off + left * scale_x)
                    box_top = int(y_off + top * scale_y)
                    box_right = int(x_off + right * scale_x)
                    box_bottom = int(y_off + bottom * scale_y)
                    box_h = box_bottom - box_top

                    # Red rectangle
                    sd.rectangle(
                        [box_left, box_top, box_right, box_bottom],
                        outline=RED,
                        width=2,
                    )

                    # Content height line (green) from content top to content bottom
                    sd.line(
                        [(box_right + 4, box_top), (box_right + 4, box_bottom)], fill=GREEN, width=2
                    )

                    # Bar height line (orange) from ground to target
                    bar_top_y = ground_y - bar_h
                    sd.line(
                        [(box_right + 10, bar_top_y), (box_right + 10, ground_y)],
                        fill=(*accent, 180),
                        width=1,
                    )

                    # Content metrics
                    content_fill = (bottom - top) / orig_h if orig_h else 0
                    content_w_ratio = (right - left) / orig_w if orig_w else 0
                    detail["content_bbox"] = [top, left, bottom, right]
                    detail["content_h_px"] = box_h
                    detail["content_fill"] = round(content_fill, 3)
                    detail["content_ratio"] = round(content_w_ratio, 3)
                    detail["scale_used"] = round(new_h / c["height_cm"], 4)

                    # Debug labels next to the box
                    label_x = box_right + 14
                    sd.text(
                        (label_x, box_top - 2),
                        f"head {box_top - y_off}px",
                        fill=GREEN,
                        font=font_debug,
                    )
                    sd.text(
                        (label_x, box_bottom - 2),
                        f"feet {box_bottom - y_off}px",
                        fill=GREEN,
                        font=font_debug,
                    )
                    sd.text(
                        (label_x, (box_top + box_bottom) // 2 - 6),
                        f"content {box_h}px",
                        fill=GREEN,
                        font=font_debug,
                    )

                    # Show the gap: where bar_h expects the top vs where content actually starts
                    gap_top = box_top - bar_top_y
                    if abs(gap_top) > 5:
                        sd.text(
                            (label_x, bar_top_y - 2),
                            f"gap {gap_top}px",
                            fill=YELLOW,
                            font=font_debug,
                        )

        # Name
        bbox = sd.textbbox((0, 0), c["name"], font=font_name)
        tw = bbox[2] - bbox[0]
        sd.text(
            (x_center - tw // 2, ground_y + 10),
            c["name"],
            fill=(240, 240, 240, 255),
            font=font_name,
        )

        # Height label
        h_val = c["height_cm"]
        h_label = f"{h_val / 100:.1f}m" if h_val >= 500 else f"{h_val}cm"
        bbox2 = sd.textbbox((0, 0), h_label, font=font_ht)
        tw2 = bbox2[2] - bbox2[0]
        sd.text(
            (x_center - tw2 // 2, ground_y + 34), h_label, fill=(150, 150, 160, 255), font=font_ht
        )

        # Pixel height label
        px_label = f"{bar_h}px"
        bbox3 = sd.textbbox((0, 0), px_label, font=font_rank)
        tw3 = bbox3[2] - bbox3[0]
        sd.text((x_center - tw3 // 2, ground_y + 52), px_label, fill=(*accent, 200), font=font_rank)

        # Rank
        rank_text = f"#{i + 1}"
        bbox4 = sd.textbbox((0, 0), rank_text, font=font_rank)
        rw = bbox4[2] - bbox4[0]
        pill_x = x_center - rw // 2 - 8
        pill_y = ground_y + 70
        sd.rounded_rectangle(
            [pill_x, pill_y, pill_x + rw + 16, pill_y + 22], radius=6, fill=(*accent, 50)
        )
        sd.text((x_center - rw // 2, pill_y + 3), rank_text, fill=(*accent, 230), font=font_rank)

        scale_details.append(detail)
        x += char_widths[i] + gap

    out_path = Path(f"/tmp/vf_scaling_{show_name.replace(' ', '_').replace(':', '').lower()}.png")
    strip.save(out_path)

    scale_info = {
        "show": show_name,
        "max_height_cm": max_h,
        "scale_factor": f"{scale:.4f}",
        "available_h": AVAILABLE_H,
        "strip_height": STRIP_HEIGHT,
        "ground_y": ground_y,
        "chars": scale_details,
    }

    return out_path, scale_info


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug scaling across shows")
    parser.add_argument("--limit", type=int, default=None, help="Test only first N shows")
    args = parser.parse_args()

    shows = SHOWS[: args.limit] if args.limit else SHOWS
    report = ReportBuilder(
        f"Scaling Debug — {len(shows)} Shows",
        "Live test: height extraction + image scaling for visual verification",
    )
    report.add_meta("shows", str(len(shows)))
    report.add_meta("strip_height", f"{STRIP_HEIGHT}px")
    report.add_meta("available_height", f"{AVAILABLE_H}px")
    report.add_meta("scale_factor", f"{SCALE_FACTOR} ({SCALE_FACTOR * 100:.0f}%)")

    total_chars = 0
    total_with_img = 0
    total_without_img = 0

    for si, show in enumerate(shows):
        print(f"\n[{si + 1}/{len(SHOWS)}] {show['name']} ({show['wiki']})", flush=True)
        section = report.add_section(f"{show['name']} — {show['wiki']}")

        chars_data: list[dict] = []
        for name, height, wiki_page in show["characters"]:
            print(f"  {name} ({height}cm)...", end=" ", flush=True)

            # Use the ACTUAL pipeline: find_best_image → fetch_and_process_image
            # This runs rembg + quality filters — same code path as the real pipeline
            img_url = find_best_image(show["wiki"], wiki_page)
            img_path = None
            fail_reason = None

            if not img_url:
                fail_reason = "no image found (scoring returned None)"
            else:
                item = Item(name=name, value=height, image_url=img_url)
                processed = fetch_and_process_image(item)
                if processed.image_path:
                    img_path = processed.image_path
                else:
                    # Diagnose why it failed — download raw and check each step
                    fail_reason = diagnose_failure(show["wiki"], wiki_page, name, img_url)

            has_img = img_path is not None
            if has_img:
                total_with_img += 1
                print("✓", flush=True)
            else:
                total_without_img += 1
                print(f"— {fail_reason}", flush=True)

            chars_data.append(
                {
                    "name": name,
                    "height_cm": height,
                    "img_path": img_path,
                    "fail_reason": fail_reason,
                }
            )
            total_chars += 1
            time.sleep(0.3)

        # Render scaling strip
        print("  Rendering strip...", end=" ", flush=True)
        strip_path, scale_info = render_scaling_strip(chars_data, show["name"])

        # Upload strip
        strip_url = upload_file(strip_path)
        if strip_url:
            section.add_full_image(
                strip_url, f"{show['name']} — scaled short to tall (red = content detection)"
            )
        print("done", flush=True)

        # Add scale info table — shows every character with pass/fail and why
        scale_rows = [
            ["Name", "Height", "Bar(px)", "Fill%", "CR%", "Status"],
        ]
        for c in scale_info["chars"]:
            h_val = c["height_cm"]
            h_label = f"{h_val / 100:.1f}m" if h_val >= 500 else f"{h_val}cm"
            fill = c.get("content_fill", 0)
            cr = c.get("content_ratio", 0)

            if c["has_image"]:
                fill_flag = "" if fill >= 0.55 else " ⚠️"
                cr_flag = "" if cr <= 0.75 else " ⚠️"
                status = f"✅ fill={fill:.0%}{fill_flag} cr={cr:.0%}{cr_flag}"
            else:
                status = f"❌ {c.get('fail_reason', 'unknown')[:40]}"

            scale_rows.append(
                [
                    c["name"],
                    h_label,
                    str(c["bar_h"]) if c["has_image"] else "—",
                    f"{fill:.0%}" if c["has_image"] else "—",
                    f"{cr:.0%}" if c["has_image"] else "—",
                    status,
                ]
            )

        section.add_table(scale_rows[0], scale_rows[1:])
        section.add_stat("max_height", f"{scale_info['max_height_cm']}cm")
        section.add_stat("scale", scale_info["scale_factor"])
        section.add_stat("ground_y", f"{scale_info['ground_y']}px")

        time.sleep(0.5)
        gc.collect()

    report.add_summary(
        {
            "Shows tested": str(len(SHOWS)),
            "Total characters": str(total_chars),
            "With images": str(total_with_img),
            "Without images": str(total_without_img),
        }
    )

    print(f"\n{'=' * 50}", flush=True)
    print("Uploading report...", flush=True)
    url = report.upload()
    if url:
        print(f"Report: {url}")
    else:
        local = report.save("/tmp/vidforge_debug_scaling.html")
        print(f"Local: {local}")


if __name__ == "__main__":
    main()
