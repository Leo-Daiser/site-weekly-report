from __future__ import annotations

from datetime import datetime
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
from app.diff import build_report_diff
from app.link_checker import run_link_checks
from app.models import SiteReport
from app.pdf_exporter import PdfExportError, export_html_to_pdf
from app.report_builder import (
    build_recommendations,
    collect_all_warnings,
    render_report,
)
from app.scanner import check_robots_and_sitemap, fetch_page
from app.seo_checks import check_forms, run_seo_checks
from app.storage import get_latest_check, save_check
from app.utils import normalize_domain, normalize_url, report_output_filenames

console = Console()

FormatChoice = Literal["html", "pdf", "both"]


def _resolve_path(path_str: str, project_root: Path) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = project_root / path
    return path


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
) -> None:
    """Сканирует главную страницу и генерирует HTML-отчёт."""
    try:
        source_url = normalize_url(url)
    except ValueError as exc:
        console.print(f"[red]Ошибка:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    output_format = report_format.lower()
    if output_format not in ("html", "pdf", "both"):
        console.print("[red]Ошибка:[/red] --format должен быть html, pdf или both")
        raise typer.Exit(code=1)

    project_root = Path(__file__).resolve().parent.parent

    try:
        if branding_file:
            branding_path = _resolve_path(branding_file, project_root)
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
    console.print(f"Сканирование: [cyan]{source_url}[/cyan]\n")

    page = fetch_page(source_url, timeout)

    base_for_resources = page.final_url or source_url
    robots, sitemap = check_robots_and_sitemap(base_for_resources, timeout)

    seo = None
    forms: list = []
    links = None

    if page.html:
        seo = run_seo_checks(page.html)
        forms = check_forms(page.html)
        check_url = page.final_url or source_url
        links = run_link_checks(page.html, check_url, max_links, timeout)

    report = SiteReport(
        source_url=source_url,
        page=page,
        seo=seo,
        robots=robots,
        sitemap=sitemap,
        forms=forms,
        links=links,
    )
    report.all_warnings = collect_all_warnings(report)
    report.recommendations = build_recommendations(report)

    normalized = normalize_domain(page.final_url or source_url)
    sqlite_path = _resolve_path(db_path, project_root)

    previous = get_latest_check(sqlite_path, normalized)
    report.diff = build_report_diff(previous, report)
    save_check(sqlite_path, report, normalized)

    template_dir = project_root / "templates"
    out_dir = _resolve_path(output_dir, project_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    report_url = page.final_url or source_url
    run_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    html_filename, pdf_filename = report_output_filenames(report_url, run_timestamp)
    html_path = out_dir / html_filename

    render_report(report, template_dir, html_path, branding)
    report.report_path = str(html_path)

    pdf_path: Path | None = None
    if output_format in ("pdf", "both"):
        pdf_path = out_dir / pdf_filename
        try:
            export_html_to_pdf(html_path, pdf_path)
            report.pdf_path = str(pdf_path)
        except PdfExportError as exc:
            for line in str(exc).splitlines():
                console.print(f"[red]{line}[/red]", soft_wrap=False)
            if output_format == "pdf":
                raise typer.Exit(code=1) from exc

    broken = links.broken_count if links else 0
    warning_count = len(report.all_warnings)
    diff = report.diff
    change_count = diff.change_count if diff else 0
    previous_label = "found" if diff and diff.has_previous else "not found"

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("URL", page.final_url or source_url)
    table.add_row(
        "HTTP status",
        str(page.status_code) if page.status_code is not None else "—",
    )
    table.add_row("Warnings", str(warning_count))
    table.add_row("Broken links", str(broken))
    table.add_row("Previous check", previous_label)
    table.add_row("Changes", str(change_count))
    table.add_row("Brand", branding.brand_name)
    if branding.client_name:
        table.add_row("Client", branding.client_name)
    if output_format in ("html", "both", "pdf"):
        table.add_row("HTML report", str(html_path))
    if pdf_path and report.pdf_path:
        table.add_row("PDF report", str(pdf_path))
    table.add_row("Database", str(sqlite_path))
    console.print(table)
    console.print()


if __name__ == "__main__":
    typer.run(main)
