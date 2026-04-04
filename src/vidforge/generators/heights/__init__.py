"""Heights comparison generator — anime character height ranking videos.

Produces scrolling videos comparing character heights from wiki data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vidforge.generators import register
from vidforge.generators.base import BaseGenerator
from vidforge.generators.heights.pipeline import _run_pipeline

__all__ = ["HeightsGenerator"]


class HeightsGenerator(BaseGenerator):
    """Generate anime character height comparison videos."""

    @property
    def name(self) -> str:
        return "heights"

    @property
    def description(self) -> str:
        return "Anime character height comparison — scrolling strip video with ranked characters"

    def run(
        self,
        *,
        recipe_path: str | Path | None = None,
        export_dag: str | Path | None = None,
        skip_bg_removal: bool = False,
        **kwargs: Any,
    ) -> Path:
        """Run the heights pipeline.

        Accepts a recipe YAML file, CLI args, or programmatic inputs.
        All are normalized to a recipe path internally.

        Returns:
            Path to the output video file.
        """
        if recipe_path is None:
            raise ValueError("recipe_path is required for heights generator")

        return _run_pipeline(
            recipe_path=str(recipe_path),
            skip_bg_removal=skip_bg_removal,
            export_dag=str(export_dag) if export_dag else None,
        )


register("heights", HeightsGenerator)
