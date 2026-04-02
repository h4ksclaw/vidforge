"""Tests for vidforge.assets.images — image fetching and processing."""

from unittest.mock import MagicMock, patch

import httpx
from PIL import Image

from vidforge.assets.images import download_image, fetch_and_process_image
from vidforge.models import Item


def _make_png_bytes(width: int = 100, height: int = 200) -> bytes:
    """Create minimal PNG bytes."""
    img = Image.new("RGBA", (width, height), (255, 0, 0, 255))
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestDownloadImage:
    @patch("vidforge.assets.images.httpx.Client")
    def test_success(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.content = _make_png_bytes()
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        result = download_image("https://example.com/img.png")
        assert result is not None
        assert result.size == (100, 200)

    @patch("vidforge.assets.images.httpx.Client")
    def test_http_error(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.HTTPError("404")

        assert download_image("https://example.com/missing.png") is None


class TestFetchAndProcessImage:
    def test_no_url(self) -> None:
        item = Item(name="Test", value=100)
        result = fetch_and_process_image(item)
        assert result.image_path is None

    def test_cached(self) -> None:
        item = Item(name="Cached", value=100, image_url="https://example.com/cached.png")
        # Put something in cache first
        from vidforge.assets.cache import item_cache_key, put_cached

        key = item_cache_key(item)
        put_cached(key, _make_png_bytes())

        result = fetch_and_process_image(item)
        assert result.image_path is not None

    @patch("vidforge.assets.images.remove_background")
    @patch("vidforge.assets.images.download_image")
    def test_download_fail(self, mock_dl: MagicMock, mock_rm: MagicMock) -> None:
        mock_dl.return_value = None
        item = Item(name="Fail", value=100, image_url="https://example.com/fail.png")

        result = fetch_and_process_image(item, skip_bg_removal=True)
        assert result.image_path is None

    @patch("vidforge.assets.images.remove_background")
    @patch("vidforge.assets.images.download_image")
    def test_bg_removal_fail(self, mock_dl: MagicMock, mock_rm: MagicMock) -> None:
        mock_dl.return_value = _make_png_bytes(200, 800)
        # download_image returns an Image, but let's mock properly
        from PIL import Image as PILImage

        mock_dl.return_value = PILImage.new("RGBA", (200, 800), (255, 0, 0, 255))
        mock_rm.return_value = None  # bg removal fails
        item = Item(name="BgFail", value=100, image_url="https://example.com/bgfail.png")

        result = fetch_and_process_image(item)
        assert result.image_path is None

    @patch("vidforge.assets.images.content_ratio")
    @patch("vidforge.assets.images.remove_background")
    @patch("vidforge.assets.images.download_image")
    def test_content_ratio_reject(
        self, mock_dl: MagicMock, mock_rm: MagicMock, mock_cr: MagicMock
    ) -> None:
        from PIL import Image as PILImage

        mock_dl.return_value = PILImage.new("RGBA", (200, 800), (255, 0, 0, 255))
        mock_rm.return_value = PILImage.new("RGBA", (200, 800), (255, 0, 0, 255))
        mock_cr.return_value = 0.9  # too wide, face crop
        item = Item(name="Wide", value=100, image_url="https://example.com/wide.png")

        result = fetch_and_process_image(item)
        assert result.image_path is None

    @patch("vidforge.assets.images.height_fill")
    @patch("vidforge.assets.images.content_ratio")
    @patch("vidforge.assets.images.remove_background")
    @patch("vidforge.assets.images.download_image")
    def test_height_fill_reject(
        self, mock_dl: MagicMock, mock_rm: MagicMock, mock_cr: MagicMock, mock_hf: MagicMock
    ) -> None:
        from PIL import Image as PILImage

        mock_dl.return_value = PILImage.new("RGBA", (200, 800), (255, 0, 0, 255))
        mock_rm.return_value = PILImage.new("RGBA", (200, 800), (255, 0, 0, 255))
        mock_cr.return_value = 0.5  # narrow enough
        mock_hf.return_value = 0.3  # too short, cropped
        item = Item(name="Short", value=100, image_url="https://example.com/short.png")

        result = fetch_and_process_image(item)
        assert result.image_path is None

    @patch("vidforge.assets.images.put_cached")
    @patch("vidforge.assets.images.height_fill")
    @patch("vidforge.assets.images.content_ratio")
    @patch("vidforge.assets.images.remove_background")
    @patch("vidforge.assets.images.download_image")
    def test_success(
        self,
        mock_dl: MagicMock,
        mock_rm: MagicMock,
        mock_cr: MagicMock,
        mock_hf: MagicMock,
        mock_put: MagicMock,
    ) -> None:
        from PIL import Image as PILImage

        mock_dl.return_value = PILImage.new("RGBA", (200, 800), (255, 0, 0, 255))
        mock_rm.return_value = PILImage.new("RGBA", (200, 800), (255, 0, 0, 255))
        mock_cr.return_value = 0.5  # narrow enough
        mock_hf.return_value = 0.8  # tall enough
        mock_put.return_value = "/fake/cache/path.png"
        item = Item(name="Good", value=100, image_url="https://example.com/good.png")

        result = fetch_and_process_image(item)
        assert result.image_path == "/fake/cache/path.png"
