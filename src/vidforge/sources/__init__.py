"""Source registry."""

from vidforge.sources.base import Source

_REGISTRY: dict[str, type[Source]] = {}


def register(name: str, cls: type[Source]) -> None:
    _REGISTRY[name] = cls


def get(name: str) -> type[Source]:
    if name not in _REGISTRY:
        available = ", ".join(_REGISTRY) or "(none)"
        raise ValueError(f"Unknown source: {name!r}. Available: {available}")
    return _REGISTRY[name]


def list_sources() -> list[str]:
    return sorted(_REGISTRY.keys())
