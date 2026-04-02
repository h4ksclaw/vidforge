"""Tests for vidforge.assets.cache — content-hash caching."""

from vidforge.assets.cache import clear_cache
from vidforge.assets.cache import content_hash
from vidforge.assets.cache import get_cached
from vidforge.assets.cache import item_cache_key
from vidforge.assets.cache import put_cached
from vidforge.models import Item


class TestContentHash:
    def test_deterministic(self) -> None:
        h1 = content_hash(b"hello")
        h2 = content_hash(b"hello")
        assert h1 == h2

    def test_different_inputs(self) -> None:
        h1 = content_hash(b"hello")
        h2 = content_hash(b"world")
        assert h1 != h2

    def test_length(self) -> None:
        h = content_hash(b"test")
        assert len(h) == 16


class TestItemCacheKey:
    def test_same_item_same_key(self) -> None:
        i1 = Item(name="Goku", value=175, image_url="https://example.com/goku.png")
        i2 = Item(name="Goku", value=175, image_url="https://example.com/goku.png")
        assert item_cache_key(i1) == item_cache_key(i2)

    def test_different_item_different_key(self) -> None:
        i1 = Item(name="Goku", value=175)
        i2 = Item(name="Vegeta", value=164)
        assert item_cache_key(i1) != item_cache_key(i2)

    def test_length(self) -> None:
        key = item_cache_key(Item(name="Test", value=100))
        assert len(key) == 16


class TestCacheGetPut:
    def test_put_and_get(self) -> None:
        key = "test-put-get"
        path = put_cached(key, b"\x89PNG\r\n\x1a\n", suffix=".png")
        assert path.exists()
        assert path.read_bytes() == b"\x89PNG\r\n\x1a\n"
        cached = get_cached(key)
        assert cached == path

    def test_get_miss(self) -> None:
        result = get_cached("nonexistent-key-xyz")
        assert result is None

    def test_subdir(self) -> None:
        key = "test-subdir"
        path = put_cached(key, b"data", subdir="custom")
        assert "custom" in str(path)
        cached = get_cached(key, subdir="custom")
        assert cached is not None
        cached_wrong = get_cached(key, subdir="other")
        assert cached_wrong is None


class TestClearCache:
    def test_clear_subdir(self) -> None:
        put_cached("clear-me-1", b"a")
        put_cached("clear-me-2", b"b")
        count = clear_cache()
        assert count >= 2
        assert get_cached("clear-me-1") is None
