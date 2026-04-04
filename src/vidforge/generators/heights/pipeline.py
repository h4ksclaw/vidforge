"""Hamilton DAG pipeline for anime height comparison videos.

This module contains all the Hamilton DAG functions for the heights generator.
The DAG is: load_recipe → load_characters → build_items → (fetch_images →
process_images → sorted_items → render_strip) + (fetch_music_pipeline) →
render_video.
"""

from __future__ import annotations

import importlib
import os
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from hamilton import driver
from hamilton.execution.executors import MultiThreadingExecutor
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFilter
from PIL import ImageFont

from vidforge.assets.images import fetch_and_process_image
from vidforge.assets.music import fetch_music
from vidforge.models import Item
from vidforge.models import Recipe
from vidforge.models import Target
from vidforge.sources.fandom import find_best_image

# ─── Configuration ───────────────────────────────────────────────────────────


def load_recipe(recipe_path: str) -> Recipe:
    """Load a recipe YAML file."""
    p = Path(recipe_path)
    with p.open() as f:
        data = yaml.safe_load(f)
    return Recipe(**data)


def load_characters(load_recipe: Recipe) -> list[dict[str, Any]]:
    """Load character list from recipe's source_config.characters_file."""
    cfg = load_recipe.source_config
    chars_file = cfg.get("characters_file")
    if not chars_file:
        return []
    p = Path(chars_file)
    if not p.exists():
        p = Path("config/characters") / chars_file
    with p.open() as f:
        data = yaml.safe_load(f)
    return data.get("characters", [])


def build_items(load_characters: list[dict[str, Any]]) -> list[Item]:
    """Convert raw character dicts to Item models."""
    return [
        Item(name=c["name"], value=c["height"])
        for c in load_characters
        if "name" in c and "height" in c
    ]


def build_target(load_recipe: Recipe) -> Target:
    """Build Target from recipe target name."""
    targets = {
        "youtube": Target(name="youtube", width=1920, height=1080),
        "tiktok": Target(name="tiktok", width=1080, height=1920),
        "reels": Target(name="reels", width=1080, height=1920),
    }
    return targets.get(load_recipe.target, targets["youtube"])


# ─── Music fetching (parallel with image chain) ─────────────────────────────


def fetch_music_pipeline(load_recipe: Recipe) -> Path | None:
    """Fetch background music from YouTube based on recipe music_query.

    Runs in parallel with the image fetching chain — only depends on load_recipe.
    """
    if not load_recipe.music_query:
        return None
    return fetch_music(load_recipe.music_query)


# ─── Image fetching ──────────────────────────────────────────────────────────


def fetch_images(
    build_items: list[Item],
    load_recipe: Recipe,
) -> list[Item]:
    """Find best images for each character via Fandom API."""
    wiki = load_recipe.source_config.get("wiki", "")
    if not wiki:
        return build_items

    characters = load_characters(load_recipe)
    char_pages = {c["name"]: c.get("wiki_page", c["name"]) for c in characters}

    result = []
    for item in build_items:
        page = char_pages.get(item.name, item.name)
        url = find_best_image(wiki, page)
        if url:
            result.append(item.model_copy(update={"image_url": url}))
        else:
            result.append(item)
    return result


def process_images(
    fetch_images: list[Item],
    skip_bg_removal: bool = False,
) -> list[Item]:
    """Download images, remove backgrounds, apply quality filters."""
    result = []
    for item in fetch_images:
        processed = fetch_and_process_image(item, skip_bg_removal=skip_bg_removal)
        result.append(processed)
    return [i for i in result if i.image_path]


# ─── Sorting ─────────────────────────────────────────────────────────────────


def sorted_items(process_images: list[Item]) -> list[Item]:
    """Sort items by value (height) ascending."""
    return sorted(process_images, key=lambda i: i.value)


# ─── Strip rendering ────────────────────────────────────────────────────────


def render_strip(
    sorted_items: list[Item],
    build_target: Target,
    load_recipe: Recipe,
) -> tuple[Path, float]:
    """Build the wide character strip image. Returns (strip_path, duration)."""
    chars = [{"name": i.name, "height": i.value, "img_path": i.image_path} for i in sorted_items]

    if len(chars) < 2:
        raise ValueError("Need at least 2 characters")

    width = build_target.width
    height = build_target.height
    max_h = max(c["height"] for c in chars)
    margin_bottom = 130
    margin_top = 80
    available_h = height - margin_bottom - margin_top
    ground_y = height - margin_bottom
    scale = available_h * 0.82 / max_h
    accent_color = (255, 165, 0)

    # Fonts
    try:
        font_name = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        font_ht = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        font_rank = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        font_grid = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except OSError:
        font_name = font_ht = font_rank = font_grid = ImageFont.load_default()

    # Calculate char widths
    char_widths: list[int] = []
    for char in chars:
        bar_h = int(char["height"] * scale)
        img_path = char.get("img_path")
        if img_path and Path(img_path).exists():
            img = Image.open(img_path)
            ratio = img.width / img.height
            char_w = max(int(bar_h * ratio) + 40, 200)
        else:
            char_w = 200
        char_widths.append(char_w)

    gap = 80
    pad = 500
    total_w = sum(char_widths) + (len(chars) - 1) * gap + pad * 2

    # Build strip
    strip = Image.new("RGBA", (total_w, height), (0, 0, 0, 0))
    sd = ImageDraw.Draw(strip)

    # Ground line
    sd.line(
        [(pad - 100, ground_y), (total_w - pad + 100, ground_y)],
        fill=(60, 55, 75, 220),
        width=3,
    )

    # Grid lines
    step = 50
    for h_cm in range(100, int(max_h * 1.1) + step, step):
        y = ground_y - int(h_cm * scale)
        if y < margin_top - 20:
            break
        is_major = (h_cm % (step * 2)) == 0
        alpha = 50 if is_major else 25
        sd.line(
            [(pad - 100, y), (total_w - pad + 100, y)],
            fill=(55, 50, 70, alpha),
            width=1,
        )
        if is_major:
            lbl = f"{h_cm / 100:.1f}m" if h_cm >= 500 else f"{h_cm}cm"
            bbox = sd.textbbox((0, 0), lbl, font=font_grid)
            tw = bbox[2] - bbox[0]
            sd.text(
                (pad - 110 - tw, y - 10),
                lbl,
                fill=(80, 75, 95, 140),
                font=font_grid,
            )

    # Draw characters
    x = pad
    for i, char in enumerate(chars):
        x_center = x + char_widths[i] // 2
        bar_h = int(char["height"] * scale)
        img_path = char.get("img_path")

        if img_path and Path(img_path).exists():
            img = Image.open(img_path)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            img_ratio = img.width / img.height
            new_h = bar_h
            new_w = int(bar_h * img_ratio)
            if new_w > char_widths[i] - 40:
                new_w = char_widths[i] - 40
                new_h = int(new_w / img_ratio)
            if new_h > 5 and new_w > 5:
                img_r = img.resize((new_w, new_h), Image.LANCZOS)
                x_off = x_center - new_w // 2
                y_off = ground_y - bar_h + (bar_h - new_h)
                shadow = img_r.filter(ImageFilter.GaussianBlur(5))
                shadow.putalpha(50)
                strip.paste(shadow, (x_off + 4, y_off + 4), shadow)
                strip.paste(img_r, (x_off, y_off), img_r)

        # Name
        bbox = sd.textbbox((0, 0), char["name"], font=font_name)
        tw = bbox[2] - bbox[0]
        sd.text(
            (x_center - tw // 2, ground_y + 14),
            char["name"],
            fill=(240, 240, 240, 255),
            font=font_name,
        )

        # Height label
        h_val = char["height"]
        hlabel = f"{h_val / 100:.1f}m" if h_val >= 500 else f"{h_val}cm"
        bbox2 = sd.textbbox((0, 0), hlabel, font=font_ht)
        tw2 = bbox2[2] - bbox2[0]
        sd.text(
            (x_center - tw2 // 2, ground_y + 50),
            hlabel,
            fill=(150, 150, 160, 255),
            font=font_ht,
        )

        # Rank badge
        rank_text = f"#{i + 1}"
        bbox3 = sd.textbbox((0, 0), rank_text, font=font_rank)
        rw = bbox3[2] - bbox3[0]
        pill_x = x_center - rw // 2 - 10
        pill_y = ground_y + 84
        sd.rounded_rectangle(
            [pill_x, pill_y, pill_x + rw + 20, pill_y + 30],
            radius=8,
            fill=(*accent_color, 50),
        )
        sd.text(
            (x_center - rw // 2, pill_y + 4),
            rank_text,
            fill=(*accent_color, 230),
            font=font_rank,
        )

        x += char_widths[i] + gap

    # Background gradient
    bg_top, bg_bot = (8, 8, 18), (15, 12, 25)
    bg_arr = np.zeros((height, total_w, 3), dtype=np.uint8)
    for y in range(height):
        t = y / height
        bg_arr[y, :] = [
            int(bg_top[0] + (bg_bot[0] - bg_top[0]) * t),
            int(bg_top[1] + (bg_bot[1] - bg_top[1]) * t),
            int(bg_top[2] + (bg_bot[2] - bg_top[2]) * t),
        ]
    bg = Image.fromarray(bg_arr).convert("RGBA")

    # Ground fill
    gf = Image.new("RGBA", (total_w, margin_bottom), (0, 0, 0, 0))
    ImageDraw.Draw(gf).rectangle([0, 0, total_w, margin_bottom], fill=(25, 22, 35, 200))
    bg.paste(gf, (0, ground_y))

    # Composite and save
    full = Image.alpha_composite(bg, strip).convert("RGB")
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    strip_path = out_dir / "strip.png"
    full.save(strip_path)

    scroll_total = total_w - width
    scroll_speed = 60
    duration = scroll_total / scroll_speed + 2

    return strip_path, duration


# ─── Video rendering ────────────────────────────────────────────────────────


def render_video(
    render_strip: tuple[Path, float],
    build_target: Target,
    fetch_music_pipeline: Path | None = None,
) -> Path:
    """Render scrolling video from strip using ffmpeg crop filter."""
    strip_path, duration = render_strip
    width = build_target.width
    height = build_target.height
    fps = build_target.fps

    strip_img = Image.open(strip_path)
    strip_w = strip_img.width
    scroll_total = strip_w - width
    total_frames = int(duration * fps)
    px_per_frame = 60.0 / fps
    pause_frames = fps

    crop_expr = (
        f"x='if(lt(n,{pause_frames}),0,"
        f"if(gt(n,{total_frames - pause_frames}),{scroll_total},"
        f"min((n-{pause_frames})*{px_per_frame},{scroll_total})))'"
    )

    video_path = Path("output") / "scroll.mp4"

    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(strip_path),
    ]

    # Add music input if available
    if fetch_music_pipeline and fetch_music_pipeline.exists():
        cmd.extend(["-i", str(fetch_music_pipeline)])

    cmd.extend(
        [
            "-vf",
            f"crop={width}:{height}:{crop_expr}",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-t",
            str(duration),
        ]
    )

    # Add audio encoding if music is present
    if fetch_music_pipeline and fetch_music_pipeline.exists():
        cmd.extend(
            [
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
            ]
        )

    cmd.append(str(video_path))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {result.stderr[-500:]}")

    return video_path


# ─── Pipeline runner ─────────────────────────────────────────────────────────


def run_pipeline(
    recipe_path: str,
    skip_bg_removal: bool = False,
    export_dag: str | None = None,
) -> Path:
    """Run the Hamilton DAG pipeline with parallel execution."""
    this_module = importlib.import_module("vidforge.generators.heights.pipeline")

    # Use threading executor for I/O-bound parallelism (image fetching + music)
    max_workers = int(os.environ.get("VIDFORGE_WORKERS", 4))

    dr = (
        driver.Builder()
        .with_config({"skip_bg_removal": skip_bg_removal})
        .with_modules(this_module)
        .enable_dynamic_execution()
        .with_local_executor(MultiThreadingExecutor(max_tasks=max_workers))
        .build()
    )

    if export_dag:
        if not export_dag.endswith(".svg"):
            export_dag += ".svg"
        Path(export_dag).parent.mkdir(parents=True, exist_ok=True)
        dr.display_all_functions(
            output_file_path=export_dag,
            render_kwargs={"format": "svg"},
        )

    result = dr.execute(
        ["render_video"],
        inputs={"recipe_path": recipe_path},
    )
    return result["render_video"]
