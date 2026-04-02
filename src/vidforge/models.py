"""Pydantic models for the video generation pipeline."""

from pydantic import BaseModel, Field


class Item(BaseModel):
    """A single data item (character, fact, ranking entry, etc.)."""

    name: str
    value: float = Field(description="Numeric value for sorting/comparison (height, rank, score)")
    image_url: str | None = None
    image_path: str | None = None
    metadata: dict = Field(default_factory=dict)


class Effect(BaseModel):
    """A reusable video effect (scroll, zoom, fade, etc.)."""

    name: str
    params: dict = Field(default_factory=dict)


class Scene(BaseModel):
    """A single scene in the timeline."""

    template: str
    items: list[Item] = Field(default_factory=list)
    effects: list[Effect] = Field(default_factory=list)
    duration: float | None = None
    music_path: str | None = None
    metadata: dict = Field(default_factory=dict)


class Timeline(BaseModel):
    """Ordered sequence of scenes."""

    scenes: list[Scene] = Field(default_factory=list)


class Target(BaseModel):
    """Platform output configuration."""

    name: str
    width: int
    height: int
    max_duration: float = 180.0
    fps: int = 30
    safe_margin_top: int = 60
    safe_margin_bottom: int = 120
    safe_margin_sides: int = 80
    text_scale: float = 1.0
    metadata: dict = Field(default_factory=dict)


class Recipe(BaseModel):
    """Video generation recipe."""

    name: str
    source: str
    source_config: dict = Field(default_factory=dict)
    target: str
    template: str = "comparison"
    intro_template: str = "default"
    outro_template: str = "default"
    music_query: str | None = None
    metadata: dict = Field(default_factory=dict)
