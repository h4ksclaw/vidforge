"""Tests for AniList image source."""

from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from vidforge.sources.anilist import find_character_image
from vidforge.sources.anilist import search_character_images


@pytest.fixture
def mock_response():
    return {
        "data": {
            "Character": {
                "name": {"full": "Gokuu Son"},
                "image": {"large": "https://s4.anilist.co/file/anilistcdn/character/large/246.png"},
            }
        }
    }


@pytest.fixture
def mock_search_response():
    return {
        "data": {
            "Page": {
                "characters": [
                    {
                        "name": {"full": "Vegeta"},
                        "image": {
                            "large": "https://s4.anilist.co/file/anilistcdn/character/large/247.png"
                        },
                        "favourites": 21351,
                    },
                    {
                        "name": {"full": "Vegeta (Xeno)"},
                        "image": {
                            "large": "https://s4.anilist.co/file/anilistcdn/character/large/248.png"
                        },
                        "favourites": 500,
                    },
                ]
            }
        }
    }


def test_find_character_image_success(mock_response):
    with patch("vidforge.sources.anilist.httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(post=MagicMock(return_value=mock_resp))
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        url = find_character_image("Goku")
        assert url == "https://s4.anilist.co/file/anilistcdn/character/large/246.png"


def test_find_character_image_no_results():
    with patch("vidforge.sources.anilist.httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"Character": None}}
        mock_resp.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(post=MagicMock(return_value=mock_resp))
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        assert find_character_image("NonexistentChar") is None


def test_find_character_image_api_error():
    with patch("vidforge.sources.anilist.httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"errors": [{"message": "Too many requests"}]}
        mock_resp.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(post=MagicMock(return_value=mock_resp))
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        assert find_character_image("Goku") is None


def test_find_character_image_network_error():
    with patch("vidforge.sources.anilist.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__ = MagicMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        assert find_character_image("Goku") is None


def test_search_character_images_success(mock_search_response):
    with patch("vidforge.sources.anilist.httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_search_response
        mock_resp.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(post=MagicMock(return_value=mock_resp))
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        urls = search_character_images("Vegeta")
        assert len(urls) == 2
        assert "anilistcdn" in urls[0]


def test_search_character_images_empty():
    with patch("vidforge.sources.anilist.httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"Page": {"characters": []}}}
        mock_resp.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(post=MagicMock(return_value=mock_resp))
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        assert search_character_images("Nobody") == []
