from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from app.config import DEFAULT_MAX_LINKS, DEFAULT_OUTPUT_DIR, DEFAULT_TIMEOUT
from app.link_checker import run_link_checks
from app.models import SiteReport
from app.report_builder import (
    build_recommendations,
    collect_all_warnings,
    render_report,
)
from app.scanner import check_robots_and_sitemap, fetch_page
from app.seo_checks import check_forms, run_seo_checks
from app.utils import domain_to_filename, normalize_url

console = Console()


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
) -> None:
    """Сканирует главную страницу и генерирует HTML-отчёт."""
    try:
        source_url = normalize_url(url)
    except ValueError as exc:
        console.print(f"[red]Ошибка:[/red] {exc}")
        raise typer.Exit(code=1) from exc

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

    project_root = Path(__file__).resolve().parent.parent
    template_dir = project_root / "templates"
    out_dir = Path(output_dir)
    if not out_dir.is_absolute():
        out_dir = project_root / out_dir

    filename = domain_to_filename(page.final_url or source_url)
    output_path = out_dir / filename
    render_report(report, template_dir, output_path)
    report.report_path = str(output_path)

    broken = links.broken_count if links else 0
    warning_count = len(report.all_warnings)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("URL", page.final_url or source_url)
    table.add_row(
        "HTTP status",
        str(page.status_code) if page.status_code is not None else "—",
    )
    table.add_row("Warnings", str(warning_count))
    table.add_row("Broken links", str(broken))
    table.add_row("Отчёт", str(output_path))
    console.print(table)
    console.print()


if __name__ == "__main__":
    typer.run(main)
