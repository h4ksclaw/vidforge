"""Content-hash based file caching."""

import hashlib
import shutil
from pathlib import Path

from vidforge.models import Item


def cache_dir() -> Path:
    """Return the global cache directory."""
    d = Path.home() / ".cache" / "vidgen"
    d.mkdir(parents=True, exist_ok=True)
    return d


def content_hash(data: bytes) -> str:
    """Return SHA-256 hex digest of data."""
    return hashlib.sha256(data).hexdigest()[:16]


def item_cache_key(item: Item) -> str:
    """Generate a filesystem-safe cache key for an item."""
    raw = f"{item.name}:{item.value}:{item.image_url or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def get_cached(key: str, subdir: str = "images") -> Path | None:
    """Return cached file path if it exists, else None."""
    d = cache_dir() / subdir
    if not d.exists():
        return None
    matches = list(d.glob(f"{key}.*"))
    if matches:
        return matches[0]
    return None


def put_cached(key: str, data: bytes, subdir: str = "images", suffix: str = ".png") -> Path:
    """Save data to cache, return the file path."""
    d = cache_dir() / subdir
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{key}{suffix}"
    path.write_bytes(data)
    return path


def clear_cache(subdir: str | None = None) -> int:
    """Clear cache. Returns number of files removed."""
    d = cache_dir() / subdir if subdir else cache_dir()
    if not d.exists():
        return 0
    count = sum(1 for _ in d.rglob("*") if _.is_file())
    shutil.rmtree(d, ignore_errors=True)
    return count
