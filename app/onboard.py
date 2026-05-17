from __future__ import annotations

from pathlib import Path
from typing import Literal

import typer
from rich.console import Console
from rich.table import Table

from app.branding import load_branding_config, resolve_branding
from app.config import DEFAULT_DB_PATH, DEFAULT_MAX_LINKS, DEFAULT_OUTPUT_DIR, DEFAULT_TIMEOUT
from app.leads import run_onboard
from app.pipeline import SingleReportError
from app.utils import resolve_project_path

console = Console()

FormatChoice = Literal["html", "pdf", "both"]
DEFAULT_LEADS_DIR = "leads"
DEFAULT_CLIENTS_CSV = "data/clients.csv"


def _parse_bool_option(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _print_warnings(warnings: list[str]) -> None:
    for message in warnings:
        console.print(f"[yellow]Warning:[/yellow] {message}")


def main(
    client_name: str = typer.Option(..., "--client-name", help="Имя лида / клиента"),
    client_email: str | None = typer.Option(
        None, "--client-email", help="Email лида (опционально)"
    ),
    url: str = typer.Option(..., "--url", help="URL сайта"),
    brand_name: str | None = typer.Option(None, "--brand-name", help="Название бренда"),
    brand_color: str | None = typer.Option(None, "--brand-color", help="Цвет бренда (#RRGGBB)"),
    brand_logo: str | None = typer.Option(None, "--brand-logo", help="Путь к логотипу"),
    footer_text: str | None = typer.Option(None, "--footer-text", help="Текст в подвале"),
    report_format: FormatChoice = typer.Option(
        "html", "--format", help="Формат отчёта: html, pdf, both"
    ),
    max_links: int = typer.Option(
        DEFAULT_MAX_LINKS, "--max-links", help="Макс. внутренних ссылок"
    ),
    timeout: float = typer.Option(DEFAULT_TIMEOUT, "--timeout", help="Таймаут HTTP (сек)"),
    db_path: str = typer.Option(
        DEFAULT_DB_PATH, "--db-path", help="SQLite-база истории проверок"
    ),
    output_dir: str = typer.Option(
        DEFAULT_OUTPUT_DIR, "--output-dir", help="Папка для отчёта в reports/"
    ),
    leads_dir: str = typer.Option(
        DEFAULT_LEADS_DIR, "--leads-dir", help="Папка для lead deliverables"
    ),
    branding_file: str | None = typer.Option(
        None, "--branding-file", help="JSON с настройками брендинга"
    ),
    add_to_clients_csv: str = typer.Option(
        "false",
        "--add-to-clients-csv",
        help="Добавить лида в clients CSV: true / false",
    ),
    clients_csv: str = typer.Option(
        DEFAULT_CLIENTS_CSV, "--clients-csv", help="Путь к clients CSV"
    ),
) -> None:
    """Онбординг лида: sample-report и deliverable-папка без автоматической отправки email."""
    output_format = report_format.lower()
    if output_format not in ("html", "pdf", "both"):
        console.print("[red]Ошибка:[/red] --format должен быть html, pdf или both")
        raise typer.Exit(code=1)

    project_root = Path(__file__).resolve().parent.parent
    template_dir = project_root / "templates"

    try:
        if branding_file:
            file_config = load_branding_config(
                str(resolve_project_path(branding_file, project_root))
            )
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

    console.print("\n[bold]Weekly Site Report — Onboard[/bold]")
    console.print(f"Lead: [cyan]{client_name}[/cyan] — {url}\n")

    try:
        result = run_onboard(
            client_name=client_name,
            client_email=client_email,
            url=url,
            branding=branding,
            output_format=output_format,
            max_links=max_links,
            timeout=timeout,
            output_dir=resolve_project_path(output_dir, project_root),
            db_path=resolve_project_path(db_path, project_root),
            leads_dir=resolve_project_path(leads_dir, project_root),
            project_root=project_root,
            template_dir=template_dir,
            add_to_clients_csv=_parse_bool_option(add_to_clients_csv),
            clients_csv=resolve_project_path(clients_csv, project_root),
            brand_logo_cli=brand_logo,
            footer_text_cli=footer_text,
            branding_warnings=branding_warnings,
        )
    except SingleReportError as exc:
        console.print(f"[red]Ошибка PDF:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except (ValueError, RuntimeError) as exc:
        console.print(f"[red]Ошибка:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    _print_warnings(result.warnings)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("Lead folder", str(result.lead_dir))
    table.add_row("client.json", str(result.client_json_path))
    if result.sample_report_html:
        table.add_row("Sample HTML", str(result.sample_report_html))
    if result.sample_report_pdf:
        table.add_row("Sample PDF", str(result.sample_report_pdf))
    table.add_row("Email preview (txt)", str(result.email_preview_txt))
    table.add_row("Email preview (html)", str(result.email_preview_html))
    table.add_row("Notes", str(result.notes_path))
    table.add_row("Warnings", str(result.report_result.warnings_count))
    table.add_row("Broken links", str(result.report_result.broken_links_count))
    if result.clients_csv_status:
        label = (
            "[green]added[/green]"
            if result.clients_csv_status == "added"
            else "[yellow]already exists[/yellow]"
        )
        table.add_row("clients.csv", label)
    console.print(table)
    console.print(
        "\n[dim]Email не отправлялся. Проверьте sample_report и email_preview вручную.[/dim]\n"
    )


if __name__ == "__main__":
    typer.run(main)
