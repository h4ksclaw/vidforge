"""Tests for vidforge.assets.music."""

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from vidforge.assets.music import _download_audio
from vidforge.assets.music import _safe_name
from vidforge.assets.music import _search_cc
from vidforge.assets.music import fetch_music
from vidforge.assets.music import get_audio_duration


class TestSafeName:
    def test_basic(self) -> None:
        assert _safe_name("Dragon Ball Z") == "Dragon_Ball_Z"

    def test_special_chars(self) -> None:
        result = _safe_name("Naruto: Shippuden!!")
        assert "Naruto" in result
        assert "Shippuden" in result

    def test_empty(self) -> None:
        assert _safe_name("") == ""


class TestSearchCc:
    def test_returns_filtered_results(self) -> None:
        """_search_cc should filter to valid video IDs and duration range."""
        mock_entries = [
            {"id": "abc123def45", "duration": 120, "title": "DBZ Instrumental"},
            {"id": "short", "duration": 30, "title": "Too Short"},  # < 60s, filtered
            {"id": "xyz789uvw01", "duration": 2400, "title": "Too Long"},  # > 30min, filtered
            {"id": "good1234vid", "duration": 180, "title": "Good Track"},
        ]

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"entries": mock_entries}

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            results = _search_cc("dragon ball z instrumental")

        assert len(results) == 2
        assert results[0] == ("abc123def45", 120, "DBZ Instrumental")
        assert results[1] == ("good1234vid", 180, "Good Track")

    def test_handles_empty_results(self) -> None:
        """_search_cc should return empty list on failure."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = Exception("network error")

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            results = _search_cc("test")

        assert results == []


class TestDownloadAudio:
    def test_download_success(self, tmp_path: Path) -> None:
        """_download_audio should find the raw file and convert to final path."""
        raw_file = tmp_path / "test_raw.mp3"
        raw_file.write_bytes(b"\x00\x01\x02")

        call_count = 0

        def mock_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            # First call is yt-dlp, second is ffmpeg
            if "ffmpeg" in cmd:
                # Simulate ffmpeg creating the output
                (tmp_path / "test.mp3").write_bytes(b"fake mp3 data")
            return MagicMock(returncode=0, stderr="")

        with patch("vidforge.assets.music.subprocess.run", side_effect=mock_run):
            result = _download_audio("abc12345678", "test", tmp_path)

        assert result == tmp_path / "test.mp3"
        assert call_count == 2

    def test_download_failure(self, tmp_path: Path) -> None:
        """_download_audio should return None when download fails."""
        with patch("vidforge.assets.music.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            # No file created

            result = _download_audio("abc12345678", "test", tmp_path)

        assert result is None


class TestFetchMusic:
    def test_returns_cached_file(self, tmp_path: Path) -> None:
        """fetch_music should return cached file if it exists."""
        cached = tmp_path / "music" / "test_query.mp3"
        cached.parent.mkdir(parents=True)
        cached.write_bytes(b"fake mp3")

        with patch("vidforge.assets.music.cache_dir", return_value=tmp_path):
            result = fetch_music("test query")

        assert result == cached

    def test_searches_multiple_queries(self, tmp_path: Path) -> None:
        """fetch_music should try multiple query variations."""
        with (
            patch("vidforge.assets.music.cache_dir", return_value=tmp_path / "noexist"),
            patch(
                "vidforge.assets.music._search_cc",
                return_value=[
                    ("abc12345678", 120, "Test Track"),
                ],
            ) as mock_search,
            patch(
                "vidforge.assets.music._download_audio", return_value=tmp_path / "test.mp3"
            ) as mock_dl,
        ):
            mock_dl.return_value.touch()
            result = fetch_music("test show")

        assert result == tmp_path / "test.mp3"
        # First query should be "{show} instrumental"
        assert mock_search.call_args[0][0] == "test show instrumental"

    def test_raises_when_no_results(self, tmp_path: Path) -> None:
        """fetch_music should raise FileNotFoundError when nothing found."""
        with (
            patch("vidforge.assets.music.cache_dir", return_value=tmp_path / "noexist"),
            patch("vidforge.assets.music._search_cc", return_value=[]),
            pytest.raises(FileNotFoundError, match="No music found"),
        ):
            fetch_music("nonexistent show that will not be found")


class TestGetAudioDuration:
    def test_returns_float(self) -> None:
        """get_audio_duration should parse ffprobe output."""
        with patch("vidforge.assets.music.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="32.5\n", stderr="")

            result = get_audio_duration(Path("test.mp3"))
            assert result == 32.5

    def test_raises_on_failure(self) -> None:
        """get_audio_duration should raise on ffprobe failure."""
        with patch("vidforge.assets.music.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="probe failed")

            with pytest.raises(RuntimeError, match="ffprobe failed"):
                get_audio_duration(Path("bad.mp3"))
