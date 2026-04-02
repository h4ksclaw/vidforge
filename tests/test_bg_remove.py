"""Tests for vidforge.assets.bg_remove — background removal."""

from PIL import Image

from vidforge.assets.bg_remove import content_ratio, height_fill, score_image


def _make_test_image(width: int, height: int, content_height: int | None = None) -> Image.Image:
    """Create a test RGBA image with vertical content strip."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ch = content_height or height
    y_start = (height - ch) // 2
    for y in range(y_start, y_start + ch):
        for x in range(width):
            img.putpixel((x, y), (255, 0, 0, 255))
    return img


class TestScoreImage:
    def test_full_body(self) -> None:
        img = _make_test_image(200, 800)
        score = score_image(img)
        assert score > 0.8

    def test_face_crop(self) -> None:
        # Wide image — ratio > 1.2 → score = 0
        img = _make_test_image(400, 300)
        score = score_image(img)
        assert score == 0.0

    def test_tiny_image(self) -> None:
        img = _make_test_image(10, 10)
        assert score_image(img) == 0.0

    def test_empty_image(self) -> None:
        img = Image.new("RGBA", (200, 800), (0, 0, 0, 0))
        assert score_image(img) == 0.0


class TestContentRatio:
    def test_narrow_content(self) -> None:
        img = _make_test_image(100, 800, 780)
        cr = content_ratio(img)
        assert cr >= 0.9  # content spans most of width

    def test_full_width(self) -> None:
        img = _make_test_image(200, 800)
        assert content_ratio(img) >= 0.9

    def test_empty(self) -> None:
        img = Image.new("RGBA", (200, 800), (0, 0, 0, 0))
        assert content_ratio(img) == 1.0  # empty returns 1.0


class TestHeightFill:
    def test_full_height(self) -> None:
        img = _make_test_image(100, 800, 800)
        assert height_fill(img) >= 0.99

    def test_half_height(self) -> None:
        img = _make_test_image(100, 800, 400)
        hf = height_fill(img)
        assert 0.45 <= hf <= 0.55

    def test_empty(self) -> None:
        img = Image.new("RGBA", (200, 800), (0, 0, 0, 0))
        assert height_fill(img) == 0.0

    def test_tiny(self) -> None:
        img = _make_test_image(100, 50)
        assert height_fill(img) == 0.0
