"""VidForge pipeline — backward compatibility shim.

The actual pipeline logic has moved to generators. This module re-exports
run_pipeline for backward compatibility with existing code and CLI.

    vidforge.pipeline.run_pipeline  # still works
"""

from __future__ import annotations

from vidforge.generators.heights.pipeline import _run_pipeline

__all__ = ["run_pipeline"]

run_pipeline = _run_pipeline
