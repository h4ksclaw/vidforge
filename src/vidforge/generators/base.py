"""Base class for video generators.

Each generator produces a video from some input (recipe, CLI args, API call).
Subclasses implement the Hamilton DAG and expose a run() method.
"""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from pathlib import Path
from typing import Any


class BaseGenerator(ABC):
    """Base class for video generators.

    Subclasses must implement:
    - name: unique identifier
    - description: human-readable description
    - run(): execute the pipeline and return the output path
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique generator identifier (e.g., 'heights')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for UI/CLI."""
        ...

    @abstractmethod
    def run(
        self,
        *,
        recipe_path: str | Path | None = None,
        export_dag: str | Path | None = None,
        **kwargs: Any,
    ) -> Path:
        """Execute the generator pipeline.

        Args:
            recipe_path: Optional path to a recipe YAML file.
            export_dag: Optional path to export the DAG visualization.
            **kwargs: Generator-specific parameters.

        Returns:
            Path to the output video file.
        """
        ...
