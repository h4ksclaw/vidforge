"""Tests for vidforge.models — Pydantic data models."""

from vidforge.models import Effect
from vidforge.models import Item
from vidforge.models import Recipe
from vidforge.models import Scene
from vidforge.models import Target
from vidforge.models import Timeline


class TestItem:
    def test_basic(self) -> None:
        item = Item(name="Goku", value=175)
        assert item.name == "Goku"
        assert item.value == 175
        assert item.image_url is None
        assert item.metadata == {}

    def test_with_image(self) -> None:
        item = Item(name="Goku", value=175, image_url="https://example.com/goku.png")
        assert item.image_url == "https://example.com/goku.png"

    def test_with_metadata(self) -> None:
        item = Item(name="Goku", value=175, metadata={"show": "DBZ", "role": "protagonist"})
        assert item.metadata["show"] == "DBZ"

    def test_missing_required_fields(self) -> None:
        import pydantic
        import pytest

        with pytest.raises(pydantic.ValidationError):
            Item()  # type: ignore[call-arg]


class TestScene:
    def test_empty_scene(self) -> None:
        scene = Scene(template="intro")
        assert scene.template == "intro"
        assert scene.items == []
        assert scene.effects == []

    def test_scene_with_items(self) -> None:
        items = [Item(name="A", value=1), Item(name="B", value=2)]
        scene = Scene(template="comparison", items=items)
        assert len(scene.items) == 2


class TestTimeline:
    def test_empty(self) -> None:
        tl = Timeline()
        assert tl.scenes == []

    def test_with_scenes(self) -> None:
        tl = Timeline(
            scenes=[
                Scene(template="intro"),
                Scene(template="comparison"),
                Scene(template="outro"),
            ]
        )
        assert len(tl.scenes) == 3
        assert tl.scenes[0].template == "intro"


class TestTarget:
    def test_youtube_defaults(self) -> None:
        t = Target(name="youtube", width=1920, height=1080)
        assert t.max_duration == 180.0
        assert t.fps == 30
        assert t.text_scale == 1.0

    def test_tiktok_vertical(self) -> None:
        t = Target(name="tiktok", width=1080, height=1920, max_duration=180.0)
        assert t.width < t.height


class TestRecipe:
    def test_basic(self) -> None:
        r = Recipe(name="DBZ Heights", source="fandom", target="youtube")
        assert r.source == "fandom"
        assert r.target == "youtube"

    def test_with_config(self) -> None:
        r = Recipe(
            name="DBZ Heights",
            source="fandom",
            source_config={"wiki": "dragonball.fandom.com", "page": "Goku"},
            target="youtube",
            music_query="dragon ball z instrumental",
        )
        assert r.source_config["wiki"] == "dragonball.fandom.com"
        assert r.music_query == "dragon ball z instrumental"


class TestEffect:
    def test_basic(self) -> None:
        e = Effect(name="scroll", params={"direction": "up", "speed": 1.0})
        assert e.name == "scroll"
        assert e.params["speed"] == 1.0
