"""VidForge CLI — generate, upload, preview, dag commands."""

import shutil
from collections.abc import Callable
from pathlib import Path

import typer
from rich.console import Console

from vidforge.generators.heights.pipeline import _export_dag
from vidforge.pipeline import run_pipeline

app = typer.Typer(help="VidForge — modular video generation system")
console = Console()

_DAG_EXPORTERS: dict[str, Callable[[str | Path], Path]] = {
    "heights": _export_dag,
}


@app.command()
def generate(
    recipe: Path = typer.Argument(..., help="Path to recipe YAML file"),
    target: str = typer.Option("youtube", help="Platform target"),
    output: Path | None = typer.Option(None, help="Output file path"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show DAG without running"),
    export_dag: Path | None = typer.Option(None, "--export-dag", help="Export DAG to file"),
) -> None:
    """Generate a video from a recipe."""
    console.print(f"[bold]Generating video from {recipe}[/bold]")

    dag_path = str(export_dag) if export_dag else None
    video_path = run_pipeline(str(recipe), export_dag=dag_path)

    if output and video_path:
        shutil.copy2(video_path, output)
        video_path = output

    console.print(f"[green]✅ Output: {video_path}[/green]")


@app.command()
def upload(
    video: Path = typer.Argument(..., help="Path to video file"),
    platform: str = typer.Option("youtube", help="Target platform"),
    title: str | None = typer.Option(None, help="Video title"),
) -> None:
    """Upload a video to a platform."""
    console.print(f"[yellow]Upload to {platform} not yet implemented[/yellow]")


@app.command()
def preview(
    recipe: Path = typer.Argument(..., help="Path to recipe YAML file"),
    step: str = typer.Option("validate", help="Run pipeline up to this step"),
) -> None:
    """Preview pipeline output without rendering."""
    console.print("[yellow]Preview not yet implemented[/yellow]")


@app.command()
def dag(
    recipe: Path | None = typer.Argument(
        None, help="Path to recipe YAML (optional, DAG-only mode if omitted)"
    ),
    output: Path = typer.Option("dag.svg", help="Output file"),
    format: str = typer.Option("svg", help="Export format (svg)"),
    generator: str = typer.Option("heights", help="Generator name (heights)"),
) -> None:
    """Export the pipeline DAG visualization.

    Works standalone (no recipe needed) — just generates the SVG from function metadata.
    Pass a recipe to also run the full pipeline.
    """
    exporter = _DAG_EXPORTERS.get(generator)
    if exporter is None:
        console.print(f"[red]Unknown generator: {generator}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Exporting DAG for '{generator}' to {output}[/bold]")
    exporter(output)
    console.print(f"[green]✅ DAG exported to {output}[/green]")
