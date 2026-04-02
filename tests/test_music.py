"""Tests for vidforge.assets.music."""

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from vidforge.assets.music import fetch_music
from vidforge.assets.music import get_audio_duration


class TestFetchMusic:
    def test_fetch_music_calls_yt_dlp_with_query(self, tmp_path: Path) -> None:
        """fetch_music should call yt-dlp with the right search query."""
        with (
            patch("vidforge.assets.music.subprocess.run") as mock_run,
            patch("vidforge.assets.music._music_cache") as mock_cache,
        ):
            # Simulate yt-dlp creating a file
            audio_file = tmp_path / "music" / "test_music.opus"
            audio_file.parent.mkdir(parents=True)
            audio_file.write_bytes(b"\x00\x01\x02")
            mock_cache.return_value = tmp_path / "music"

            mock_run.return_value = MagicMock(returncode=0, stderr="")

            result = fetch_music("dragon ball z instrumental")

            assert result == audio_file
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "ytsearch1:dragon ball z instrumental" in call_args

    def test_fetch_music_raises_on_failure(self) -> None:
        """fetch_music should raise RuntimeError if yt-dlp fails."""
        with patch("vidforge.assets.music.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="download failed")

            with pytest.raises(RuntimeError, match="yt-dlp failed"):
                fetch_music("nonexistent query")

    def test_fetch_music_raises_if_no_file(self, tmp_path: Path) -> None:
        """fetch_music should raise FileNotFoundError if no file was downloaded."""
        with (
            patch("vidforge.assets.music.subprocess.run") as mock_run,
            patch("vidforge.assets.music._music_cache") as mock_cache,
        ):
            mock_cache.return_value = tmp_path / "empty"
            (tmp_path / "empty").mkdir(parents=True)
            mock_run.return_value = MagicMock(returncode=0, stderr="")

            with pytest.raises(FileNotFoundError, match="No music file found"):
                fetch_music("test query")


class TestGetAudioDuration:
    def test_get_duration_returns_float(self) -> None:
        """get_audio_duration should return a float."""
        with patch("vidforge.assets.music.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="32.5\n", stderr="")

            result = get_audio_duration(Path("test.opus"))
            assert result == 32.5

    def test_get_duration_raises_on_failure(self) -> None:
        """get_audio_duration should raise RuntimeError if ffprobe fails."""
        with patch("vidforge.assets.music.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="probe failed")

            with pytest.raises(RuntimeError, match="ffprobe failed"):
                get_audio_duration(Path("bad.opus"))
