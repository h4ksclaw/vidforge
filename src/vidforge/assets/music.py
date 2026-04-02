"""Music fetching and processing via yt-dlp."""

import logging
import subprocess
from pathlib import Path

from vidforge.assets.cache import cache_dir

logger = logging.getLogger(__name__)


def _music_cache() -> Path:
    """Return the music cache directory."""
    d = cache_dir() / "music"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch_music(query: str, max_duration: float = 300.0) -> Path:
    """Search YouTube for music matching query and download best audio.

    Args:
        query: Search query string.
        max_duration: Maximum allowed duration in seconds (default 5 min).

    Returns:
        Path to the downloaded audio file (webm or opus).
    """
    cache = _music_cache()

    cmd = [
        "yt-dlp",
        "--yes-playlist",
        "-x",
        "--audio-format",
        "opus",
        "--audio-quality",
        "5",
        "--max-filesize",
        "50M",
        "--format",
        "bestaudio/best",
        "--match-filter",
        f"duration < {max_duration}",
        "--restrict-filenames",
        "--no-playlist",
        "-o",
        str(cache / "%(title).100s.%(ext)s"),
        f"ytsearch1:{query}",
    ]

    logger.info("Searching for music: %s", query)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr[-500:]}")

    # Find the downloaded file
    files = list(cache.glob("*"))
    if not files:
        raise FileNotFoundError(f"No music file found for query: {query}")

    # Get the most recently modified file
    audio_path = max(files, key=lambda p: p.stat().st_mtime)
    logger.info("Downloaded music: %s", audio_path.name)
    return audio_path


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
