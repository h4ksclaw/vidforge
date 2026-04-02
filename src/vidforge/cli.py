"""VidForge CLI — generate, upload, preview, dag commands."""

import shutil
from pathlib import Path

import typer
from rich.console import Console

from vidforge.pipeline import run_pipeline

app = typer.Typer(help="VidForge — modular video generation system")
console = Console()


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
    recipe: Path = typer.Argument(..., help="Path to recipe YAML file"),
    output: Path = typer.Option("dag.html", help="Output file"),
    format: str = typer.Option("html", help="Export format (html/svg/png/dot/mermaid)"),
) -> None:
    """Export the pipeline DAG visualization."""
    console.print(f"[bold]Exporting DAG to {output}[/bold]")
    run_pipeline(str(recipe), export_dag=str(output))
    console.print(f"[green]✅ DAG exported to {output}[/green]")
