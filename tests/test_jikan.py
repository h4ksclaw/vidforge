"""Tests for Jikan (MAL) image source."""

from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from vidforge.sources.jikan import find_character_image
from vidforge.sources.jikan import search_character_images


@pytest.fixture
def mock_response():
    return {
        "data": [
            {
                "mal_id": 913,
                "name": "Vegeta",
                "images": {
                    "jpg": {"image_url": "https://myanimelist.net/images/characters/14/86185.jpg"},
                    "webp": {
                        "image_url": "https://myanimelist.net/images/characters/14/86185.webp",
                        "small_image_url": "https://myanimelist.net/images/characters/14/86185t.webp",
                    },
                },
            }
        ]
    }


@pytest.fixture
def mock_search_response():
    return {
        "data": [
            {
                "name": "Vegeta",
                "images": {
                    "webp": {
                        "image_url": "https://myanimelist.net/images/characters/14/86185.webp"
                    },
                    "jpg": {"image_url": "https://myanimelist.net/images/characters/14/86185.jpg"},
                },
            },
            {
                "name": "Vegeta (Xeno)",
                "images": {
                    "webp": {
                        "image_url": "https://myanimelist.net/images/characters/7/401876.webp"
                    },
                    "jpg": {"image_url": "https://myanimelist.net/images/characters/7/401876.jpg"},
                },
            },
        ]
    }


def test_find_character_image_webp(mock_response):
    with patch("vidforge.sources.jikan.httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(get=MagicMock(return_value=mock_resp))
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        url = find_character_image("Vegeta")
        assert url == "https://myanimelist.net/images/characters/14/86185.webp"


def test_find_character_image_jpg_fallback():
    """When webp is missing, fall back to jpg."""
    response_no_webp = {
        "data": [
            {
                "name": "Test",
                "images": {
                    "jpg": {"image_url": "https://myanimelist.net/images/test.jpg"},
                    "webp": {},
                },
            }
        ]
    }
    with patch("vidforge.sources.jikan.httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = response_no_webp
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(get=MagicMock(return_value=mock_resp))
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        url = find_character_image("Test")
        assert url == "https://myanimelist.net/images/test.jpg"


def test_find_character_image_no_results():
    with patch("vidforge.sources.jikan.httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(get=MagicMock(return_value=mock_resp))
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        assert find_character_image("Nobody") is None


def test_find_character_image_network_error():
    with patch("vidforge.sources.jikan.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__ = MagicMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        assert find_character_image("Goku") is None


def test_find_character_image_rate_limit_retry():
    """Test that 429 triggers a retry with sleep."""
    with (
        patch("vidforge.sources.jikan.httpx.Client") as mock_client_cls,
        patch("vidforge.sources.jikan.time.sleep") as mock_sleep,
    ):
        rate_resp = MagicMock()
        rate_resp.status_code = 429
        rate_resp.raise_for_status = MagicMock()

        ok_resp = MagicMock()
        ok_resp.json.return_value = {
            "data": [
                {
                    "name": "Goku",
                    "images": {
                        "webp": {"image_url": "https://myanimelist.net/images/goku.webp"},
                        "jpg": {"image_url": "https://myanimelist.net/images/goku.jpg"},
                    },
                }
            ]
        }
        ok_resp.status_code = 200
        ok_resp.raise_for_status = MagicMock()

        mock_get = MagicMock(side_effect=[rate_resp, ok_resp])
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(get=mock_get))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        url = find_character_image("Goku")
        assert url == "https://myanimelist.net/images/goku.webp"
        mock_sleep.assert_called_once_with(2)


def test_search_character_images_success(mock_search_response):
    with patch("vidforge.sources.jikan.httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_search_response
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(get=MagicMock(return_value=mock_resp))
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        urls = search_character_images("Vegeta")
        assert len(urls) == 2
        assert all("myanimelist" in u for u in urls)


def test_search_character_images_empty():
    with patch("vidforge.sources.jikan.httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(get=MagicMock(return_value=mock_resp))
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        assert search_character_images("Nobody") == []
