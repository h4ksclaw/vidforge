"""Generator registry — discover and load video generators.

Each generator lives in src/vidforge/generators/<name>/ and provides:
- A pipeline module with Hamilton DAG functions
- Optional debug scripts in a debug/ subpackage
- Self-registration via generators/<name>/__init__.py
"""

from __future__ import annotations

from contextlib import suppress
from importlib import import_module
from pathlib import Path

from vidforge.generators.base import BaseGenerator

_REGISTRY: dict[str, type[BaseGenerator]] = {}


def register(name: str, cls: type[BaseGenerator]) -> None:
    """Register a generator by name."""
    _REGISTRY[name] = cls


def get(name: str) -> type[BaseGenerator]:
    """Get a registered generator class by name."""
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise ValueError(f"Unknown generator: {name!r}. Available: {available}")
    return _REGISTRY[name]


def list_generators() -> list[str]:
    """List all registered generator names."""
    return sorted(_REGISTRY.keys())


def discover_all() -> dict[str, type[BaseGenerator]]:
    """Auto-discover all generators by scanning the generators package.

    Each subpackage with an __init__.py that calls register() is loaded.
    """
    generators_dir = Path(__file__).parent
    for child in sorted(generators_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        init_file = child / "__init__.py"
        if init_file.exists():
            module_name = f"vidforge.generators.{child.name}"
            with suppress(Exception):
                import_module(module_name)
    return _REGISTRY.copy()
