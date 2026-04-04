"""Music fetching and processing via yt-dlp with Creative Commons filter.

Uses yt-dlp's flat extraction with YouTube CC search filter to find
royalty-free instrumental tracks, then downloads the best match.
Falls back through multiple query variations.
"""

import contextlib
import logging
import re
import subprocess
from pathlib import Path

import yt_dlp

from vidforge.assets.cache import cache_dir

logger = logging.getLogger(__name__)


def _safe_name(s: str) -> str:
    """Convert string to filesystem-safe name."""
    return re.sub(r"[^a-zA-Z0-9]", "_", s).strip("_")


def _search_cc(query: str, max_results: int = 5) -> list[tuple[str, int, str]]:
    """Search YouTube with Creative Commons filter.

    Returns list of (video_id, duration_seconds, title), filtered to 60s-30min.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "extractor_args": {"youtube": {"search_filter": "EgIwAQ=="}},
    }

    results: list[tuple[str, int, str]] = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            data = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
        except Exception:
            return results

    if not data or "entries" not in data:
        return results

    for entry in data["entries"]:
        vid = entry.get("id") or ""
        duration = entry.get("duration") or 0
        title = entry.get("title") or ""

        if len(vid) != 11:
            continue
        # Filter: 60s to 30min
        if duration < 60 or duration > 1800:
            continue

        results.append((vid, int(duration), title))

    return results


def _download_audio(
    video_id: str,
    safe_name: str,
    output_dir: Path,
) -> Path | None:
    """Download audio from a YouTube video ID."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    raw_pattern = str(output_dir / f"{safe_name}_raw.%(ext)s")
    final_path = output_dir / f"{safe_name}.mp3"

    subprocess.run(
        [
            "yt-dlp",
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "--force-overwrite",
            "-o",
            raw_pattern,
            url,
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )

    # Find the downloaded file (yt-dlp replaces %(ext)s)
    candidates = [
        output_dir / f"{safe_name}_raw.mp3",
        output_dir / f"{safe_name}_raw.m4a",
    ]
    candidates.extend(output_dir.glob(f"{safe_name}_raw.*"))
    downloaded = next((c for c in candidates if c.exists()), None)

    if downloaded is None:
        logger.warning("Download failed for video %s", video_id)
        return None

    # Normalize to final path
    if downloaded != final_path:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(downloaded),
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                str(final_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        with contextlib.suppress(OSError):
            downloaded.unlink()

    if final_path.exists():
        logger.info(
            "Downloaded music: %s (%.1fMB)", final_path.name, final_path.stat().st_size / 1048576
        )
        return final_path

    return None


def fetch_music(query: str, max_duration: float = 300.0) -> Path:
    """Search YouTube for Creative Commons music matching query.

    Tries multiple query variations and falls back through results.
    Returns path to downloaded MP3 file.

    Args:
        query: Search query string (e.g. show name).
        max_duration: Maximum allowed duration in seconds (default 5 min).
    """
    output_dir = cache_dir() / "music"
    output_dir.mkdir(parents=True, exist_ok=True)
    safe = _safe_name(query)
    final_path = output_dir / f"{safe}.mp3"

    # Return cached if available
    if final_path.exists():
        logger.info("Music cached: %s", final_path.name)
        return final_path

    # Build query variations
    queries = [
        f"{query} instrumental",
        f"{query} soundtrack instrumental",
        f"{query} bgm",
        f"{query} ost",
    ]

    for q in queries:
        logger.info("Searching: %s", q)
        results = _search_cc(q, max_results=3)

        for vid_id, duration, title in results:
            if duration > max_duration:
                continue
            logger.info("Trying: %s (%ds)", title[:50], duration)
            path = _download_audio(vid_id, safe, output_dir)
            if path:
                return path

    raise FileNotFoundError(f"No music found for query: {query}")


def get_audio_duration(path: Path) -> float:
    """Get duration of an audio file using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[-300:]}")
    return float(result.stdout.strip())
