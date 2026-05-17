from __future__ import annotations

from pathlib import Path
from typing import Literal

import typer
from rich.console import Console
from rich.table import Table

from app.branding import load_branding_config, resolve_branding
from app.config import (
    DEFAULT_DB_PATH,
    DEFAULT_MAX_LINKS,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_TIMEOUT,
)
from app.pdf_exporter import PdfExportError
from app.pipeline import SingleReportError, run_single_report
from app.utils import resolve_project_path

console = Console()

FormatChoice = Literal["html", "pdf", "both"]


def _print_warnings(warnings: list[str]) -> None:
    for message in warnings:
        console.print(f"[yellow]Warning:[/yellow] {message}")


def main(
    url: str = typer.Option(..., "--url", help="URL сайта для сканирования"),
    max_links: int = typer.Option(
        DEFAULT_MAX_LINKS, "--max-links", help="Макс. внутренних ссылок для проверки"
    ),
    timeout: float = typer.Option(
        DEFAULT_TIMEOUT, "--timeout", help="Таймаут запросов в секундах"
    ),
    output_dir: str = typer.Option(
        DEFAULT_OUTPUT_DIR, "--output-dir", help="Папка для HTML-отчёта"
    ),
    db_path: str = typer.Option(
        DEFAULT_DB_PATH, "--db-path", help="Путь к SQLite-базе истории проверок"
    ),
    brand_name: str | None = typer.Option(None, "--brand-name", help="Название бренда"),
    client_name: str | None = typer.Option(None, "--client-name", help="Имя клиента"),
    brand_color: str | None = typer.Option(None, "--brand-color", help="Цвет бренда (#RRGGBB)"),
    brand_logo: str | None = typer.Option(None, "--brand-logo", help="Путь к логотипу"),
    footer_text: str | None = typer.Option(None, "--footer-text", help="Текст в подвале"),
    branding_file: str | None = typer.Option(
        None, "--branding-file", help="JSON-файл с настройками брендинга"
    ),
    report_format: FormatChoice = typer.Option(
        "html", "--format", help="Формат отчёта: html, pdf, both"
    ),
    max_pages: int = typer.Option(
        10, "--max-pages", help="Сколько страниц проверить в multi-page crawl"
    ),
    screenshot: bool = typer.Option(
        False, "--screenshot/--no-screenshot", help="Сделать screenshot главной страницы"
    ),
) -> None:
    """Сканирует главную страницу и генерирует HTML-отчёт."""
    output_format = report_format.lower()
    if output_format not in ("html", "pdf", "both"):
        console.print("[red]Ошибка:[/red] --format должен быть html, pdf или both")
        raise typer.Exit(code=1)

    project_root = Path(__file__).resolve().parent.parent

    try:
        if branding_file:
            branding_path = resolve_project_path(branding_file, project_root)
            file_config = load_branding_config(str(branding_path))
        else:
            file_config = load_branding_config(None)
    except FileNotFoundError as exc:
        console.print(f"[red]Ошибка:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    cli_overrides: dict[str, object] = {
        "brand_name": brand_name,
        "client_name": client_name,
        "brand_color": brand_color,
        "logo_path": brand_logo,
        "footer_text": footer_text,
    }
    branding, branding_warnings = resolve_branding(file_config, cli_overrides, project_root)
    _print_warnings(branding_warnings)

    console.print("\n[bold]Weekly Site Report[/bold]")
    console.print(f"Сканирование: [cyan]{url}[/cyan]\n")

    out_dir = resolve_project_path(output_dir, project_root)
    sqlite_path = resolve_project_path(db_path, project_root)

    try:
        result = run_single_report(
            url=url,
            max_links=max_links,
            timeout=timeout,
            output_dir=out_dir,
            db_path=sqlite_path,
            branding=branding,
            output_format=output_format,
            project_root=project_root,
            max_pages=max_pages,
            screenshot=screenshot,
        )
    except SingleReportError as exc:
        for line in str(exc).splitlines():
            console.print(f"[red]{line}[/red]", soft_wrap=False)
        raise typer.Exit(code=1) from exc

    _print_warnings(result.branding_warnings)

    if not result.success:
        console.print(f"[red]Ошибка:[/red] {result.error}")
        raise typer.Exit(code=1)

    previous_label = "found" if result.previous_check_found else "not found"

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("URL", result.url)
    table.add_row(
        "HTTP status",
        str(result.status_code) if result.status_code is not None else "—",
    )
    table.add_row("Warnings", str(result.warnings_count))
    table.add_row("Broken links", str(result.broken_links_count))
    table.add_row("Pages checked", str(result.pages_checked_count))
    table.add_row("Broken assets", str(result.broken_assets_count))
    table.add_row("Previous check", previous_label)
    table.add_row("Changes", str(result.changes_count))
    table.add_row("Brand", branding.brand_name)
    if branding.client_name:
        table.add_row("Client", branding.client_name)
    if output_format in ("html", "both", "pdf") and result.html_path:
        table.add_row("HTML report", result.html_path)
    if result.pdf_path:
        table.add_row("PDF report", result.pdf_path)
    table.add_row("Database", str(sqlite_path))
    console.print(table)
    console.print()


if __name__ == "__main__":
    typer.run(main)
