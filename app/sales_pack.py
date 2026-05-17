from __future__ import annotations

from pathlib import Path
from typing import Literal

import typer
from rich.console import Console

from app.sales_assets import generate_sales_pack, load_sales_pack_config
from app.utils import resolve_project_path

console = Console()
cli = typer.Typer(help="Generate local sales and landing materials.")

DEFAULT_CONFIG = "data/sales_pack.example.json"
DEFAULT_OUTPUT_DIR = "sales_pack"

FormatChoice = Literal["md", "html", "both"]


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


@cli.command("version")
def version_cmd() -> None:
    """Show sales_pack module version label."""
    console.print("app.sales_pack (Weekly Site Report)")


@cli.command("generate")
def generate_cmd(
    config_path: str = typer.Option(DEFAULT_CONFIG, "--config"),
    output_dir: str = typer.Option(DEFAULT_OUTPUT_DIR, "--output-dir"),
    output_format: FormatChoice = typer.Option("md", "--format"),
) -> None:
    """Generate sales pack markdown (and optional HTML) assets."""
    root = _project_root()
    config_file = resolve_project_path(config_path, root)
    out_dir = resolve_project_path(output_dir, root)
    template_dir = root / "templates"

    fmt = output_format.lower()
    if fmt not in ("md", "html", "both"):
        console.print("[red]Error:[/red] --format must be md, html, or both")
        raise typer.Exit(code=1)

    try:
        config = load_sales_pack_config(config_file)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    pack_dir = generate_sales_pack(
        config,
        out_dir,
        template_dir=template_dir,
        output_format=fmt,
    )

    console.print(f"\n[green]Sales pack generated[/green]")
    console.print(f"Output: {pack_dir}")
    console.print(f"Product: {config.product_name}")
    console.print(f"Format: {fmt}\n")
    for path in sorted(pack_dir.glob("*.md")):
        console.print(f"  - {path.name}")
    if fmt in ("html", "both"):
        console.print("")
        for path in sorted(pack_dir.glob("*.html")):
            console.print(f"  - {path.name}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
