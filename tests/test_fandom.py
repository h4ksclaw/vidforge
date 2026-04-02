"""Tests for vidforge.sources.fandom — Fandom wiki API source."""

from unittest.mock import MagicMock
from unittest.mock import patch

import httpx

from vidforge.sources.fandom import parse_height


class TestParseHeight:
    def test_cm(self) -> None:
        assert parse_height("175 cm") == 175
        assert parse_height("175cm") == 175
        assert parse_height("1.75 m") == 175

    def test_meters(self) -> None:
        assert parse_height("1.80 m") == 180
        assert parse_height("2.5m") == 250

    def test_feet_inches(self) -> None:
        result = parse_height("5'9\"")
        assert result is not None
        assert 170 <= result <= 180

    def test_feet_inches_text(self) -> None:
        result = parse_height("5 feet 9 inches")
        assert result is not None
        assert 170 <= result <= 180

    def test_bare_number_cm(self) -> None:
        assert parse_height("175") == 175

    def test_bare_number_meters(self) -> None:
        assert parse_height("1.75") == 175

    def test_unknown(self) -> None:
        assert parse_height("unknown") is None
        assert parse_height("?") is None
        assert parse_height("none") is None
        assert parse_height("n/a") is None

    def test_none(self) -> None:
        assert parse_height("") is None
        assert parse_height(None) is None  # type: ignore[arg-type]

    def test_with_html(self) -> None:
        assert parse_height("<ref>source</ref>175 cm") == 175

    def test_out_of_range(self) -> None:
        assert parse_height("10 cm") is None
        assert parse_height("5000 cm") is None

    def test_wiki_format(self) -> None:
        # {{height|175}} gets stripped by template removal regex
        assert parse_height("{{height|175}}") is None

    def test_giant(self) -> None:
        assert parse_height("500 cm") == 500


class TestGetHeight:
    @patch("vidforge.sources.fandom._api")
    def test_valid_height(self, mock_api: MagicMock) -> None:
        mock_api.return_value = {"parse": {"wikitext": {"*": "| height = 175 cm\n"}}}
        from vidforge.sources.fandom import get_height

        assert get_height("test.fandom.com", "Goku") == 175

    @patch("vidforge.sources.fandom._api")
    def test_no_height_field(self, mock_api: MagicMock) -> None:
        mock_api.return_value = {"parse": {"wikitext": {"*": "| name = Goku\n"}}}
        from vidforge.sources.fandom import get_height

        assert get_height("test.fandom.com", "Goku") is None

    @patch("vidforge.sources.fandom._api")
    def test_api_error(self, mock_api: MagicMock) -> None:
        mock_api.side_effect = httpx.HTTPError("timeout")
        from vidforge.sources.fandom import get_height

        assert get_height("test.fandom.com", "Goku") is None


class TestFetchCharacters:
    @patch("vidforge.sources.fandom.get_height")
    def test_explicit_pages(self, mock_height: MagicMock) -> None:
        mock_height.side_effect = [175, 164, None, 200]
        from vidforge.sources.fandom import fetch_characters

        result = fetch_characters(
            "test.fandom.com",
            character_pages=["Goku", "Vegeta", "Unknown", "Buu"],
            max_chars=10,
        )
        assert len(result) == 3
        assert result[0].name == "Vegeta"  # sorted by height
        assert result[0].value == 164
        assert result[2].name == "Buu"
        assert result[2].value == 200

    @patch("vidforge.sources.fandom.get_height")
    def test_max_chars_limit(self, mock_height: MagicMock) -> None:
        mock_height.side_effect = [100, 150, 200, 250]
        from vidforge.sources.fandom import fetch_characters

        result = fetch_characters(
            "test.fandom.com",
            character_pages=["A", "B", "C", "D"],
            max_chars=2,
        )
        assert len(result) == 2

    @patch("vidforge.sources.fandom.get_height")
    def test_empty(self, mock_height: MagicMock) -> None:
        mock_height.return_value = None
        from vidforge.sources.fandom import fetch_characters

        result = fetch_characters("test.fandom.com", character_pages=["X"])
        assert result == []


class TestGetPageImages:
    @patch("vidforge.sources.fandom._api")
    def test_returns_images(self, mock_api: MagicMock) -> None:
        mock_api.return_value = {"parse": {"images": ["File:Goku.png", "File:Goku_profile.jpg"]}}
        from vidforge.sources.fandom import get_page_images

        result = get_page_images("test.fandom.com", "Goku")
        assert result == ["File:Goku.png", "File:Goku_profile.jpg"]

    @patch("vidforge.sources.fandom._api")
    def test_api_error(self, mock_api: MagicMock) -> None:
        mock_api.side_effect = httpx.HTTPError("timeout")
        from vidforge.sources.fandom import get_page_images

        result = get_page_images("test.fandom.com", "Goku")
        assert result == []


class TestGetImageUrl:
    @patch("vidforge.sources.fandom._api")
    def test_returns_url(self, mock_api: MagicMock) -> None:
        mock_api.return_value = {
            "query": {"pages": {"123": {"imageinfo": [{"url": "https://example.com/img.png"}]}}}
        }
        from vidforge.sources.fandom import get_image_url

        assert get_image_url("test.fandom.com", "Goku.png") == "https://example.com/img.png"

    @patch("vidforge.sources.fandom._api")
    def test_no_imageinfo(self, mock_api: MagicMock) -> None:
        mock_api.return_value = {"query": {"pages": {"-1": {}}}}
        from vidforge.sources.fandom import get_image_url

        assert get_image_url("test.fandom.com", "Missing.png") is None


class TestFindBestImage:
    @patch("vidforge.sources.fandom.get_image_url")
    @patch("vidforge.sources.fandom.get_page_images")
    def test_picks_best_score(self, mock_images: MagicMock, mock_url: MagicMock) -> None:
        mock_images.return_value = ["File:Goku_infobox.png", "File:Goku_chibi.png"]
        mock_url.side_effect = ["https://a.com/infobox.png", "https://a.com/chibi.png"]
        from vidforge.sources.fandom import find_best_image

        result = find_best_image("test.fandom.com", "Goku")
        assert result is not None
        assert "infobox" in result

    @patch("vidforge.sources.fandom.get_page_images")
    def test_no_matching_images(self, mock_images: MagicMock) -> None:
        mock_images.return_value = ["File:Logo.png"]
        from vidforge.sources.fandom import find_best_image

        assert find_best_image("test.fandom.com", "Goku") is None


class TestDiscoverCharacters:
    @patch("vidforge.sources.fandom._api")
    def test_finds_characters(self, mock_api: MagicMock) -> None:
        mock_api.return_value = {
            "query": {
                "search": [
                    {"title": "Goku"},
                    {"title": "Vegeta"},
                    {"title": "Episode 1"},
                ]
            }
        }
        from vidforge.sources.fandom import discover_characters

        result = discover_characters("test.fandom.com", max_pages=10)
        assert "Goku" in result
        assert "Vegeta" in result
        assert "Episode 1" not in result  # filtered by skip words

    @patch("vidforge.sources.fandom._api")
    def test_empty_results(self, mock_api: MagicMock) -> None:
        mock_api.return_value = {"query": {"search": []}}
        from vidforge.sources.fandom import discover_characters

        result = discover_characters("test.fandom.com")
        assert result == []

    @patch("vidforge.sources.fandom._api")
    def test_filters_skip_words(self, mock_api: MagicMock) -> None:
        mock_api.return_value = {
            "query": {
                "search": [
                    {"title": "Voice Actor List"},
                    {"title": "Opening Theme"},
                    {"title": "Krillin"},
                ]
            }
        }
        from vidforge.sources.fandom import discover_characters

        result = discover_characters("test.fandom.com")
        assert result == ["Krillin"]
