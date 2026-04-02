"""VidForge CLI."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(
    name="vidforge",
    help="Modular video generation system.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def generate(
    recipe: Path = typer.Argument(..., help="Path to recipe YAML file"),
    target: str = typer.Option("youtube", help="Platform target"),
    output: Optional[Path] = typer.Option(None, help="Output file path"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show DAG without running"),
    export_dag: Optional[Path] = typer.Option(None, "--export-dag", help="Export DAG to file"),
) -> None:
    """Generate a video from a recipe."""
    console.print(f"[bold]Generating video from:[/] {recipe}")
    console.print(f"[dim]Target: {target}[/]")

    if dry_run:
        console.print("[yellow]Dry run — showing DAG only[/]")
        # TODO: Hamilton DAG visualization
        return

    if export_dag:
        console.print(f"[dim]Exporting DAG to {export_dag}[/]")
        # TODO: Hamilton DAG export
        return

    # TODO: Load recipe, build Hamilton DAG, run pipeline
    console.print("[green]Done![/]")


@app.command()
def upload(
    video: Path = typer.Argument(..., help="Path to video file"),
    platform: str = typer.Option("youtube", help="Target platform"),
    title: Optional[str] = typer.Option(None, help="Video title"),
) -> None:
    """Upload a video to a platform."""
    console.print(f"[bold]Uploading to {platform}:[/] {video}")
    # TODO: Platform upload logic


@app.command()
def preview(
    recipe: Path = typer.Argument(..., help="Path to recipe YAML file"),
    step: str = typer.Option("validate", help="Run pipeline up to this step"),
) -> None:
    """Generate an HTML preview of pipeline intermediate results."""
    console.print(f"[bold]Previewing pipeline up to:[/] {step}")
    # TODO: Run pipeline to step, generate HTML preview


@app.command()
def dag(
    recipe: Path = typer.Argument(..., help="Path to recipe YAML file"),
    output: Path = typer.Option("dag.html", help="Output file"),
    format: str = typer.Option("html", help="Export format (html/svg/png/dot/mermaid)"),
) -> None:
    """Export the pipeline DAG visualization."""
    console.print(f"[bold]Exporting DAG:[/] {output} ({format})")
    # TODO: Hamilton DAG export


if __name__ == "__main__":
    app()
