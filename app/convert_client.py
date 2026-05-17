from __future__ import annotations

from pathlib import Path
from typing import Literal

import typer
from rich.console import Console
from rich.table import Table

from app.client_packages import (
    append_client_to_clients_csv,
    create_client_package,
    update_weekly_job_config,
)
from app.crm_store import convert_lead_in_crm, find_lead_by_id, utc_now_iso
from app.models import ConvertClientResult
from app.pricing import get_plan, load_pricing_config
from app.utils import resolve_project_path

console = Console()

FormatChoice = Literal["html", "pdf", "both"]

DEFAULT_CRM_PATH = "data/leads_crm.csv"
DEFAULT_CLIENTS_CSV = "data/clients.csv"
DEFAULT_PRICING_FILE = "data/pricing.example.json"
DEFAULT_PACKAGES_DIR = "client_packages"
DEFAULT_WEEKLY_EXAMPLE = "data/weekly_jobs.example.json"


def _parse_bool_option(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def run_convert_client(
    *,
    lead_id: str,
    plan_id: str,
    crm_path: Path,
    clients_csv: Path,
    pricing_file: Path,
    packages_dir: Path,
    template_dir: Path,
    project_root: Path,
    brand_name: str | None = None,
    brand_color: str | None = None,
    report_format: str = "both",
    max_links: int = 30,
    timeout: float = 10.0,
    add_to_weekly_job: bool = False,
    weekly_job_file: Path | None = None,
    weekly_job_example: Path | None = None,
) -> ConvertClientResult:
    lead = find_lead_by_id(crm_path, lead_id)
    if lead is None:
        raise ValueError(f"Lead not found: {lead_id}")

    if not lead.client_name.strip():
        raise ValueError("Lead is missing client_name")
    if not lead.url.strip():
        raise ValueError("Lead is missing url")
    if not lead.client_email or not lead.client_email.strip():
        raise ValueError("Lead is missing client_email")

    config, _ = load_pricing_config(pricing_file)
    plan = get_plan(config, plan_id)

    resolved_brand = (brand_name or lead.client_name or "WebReport Weekly").strip()
    resolved_color = (brand_color or "#2563eb").strip()
    fmt = report_format.lower()
    if fmt not in ("html", "pdf", "both"):
        raise ValueError("--format must be html, pdf, or both")

    footer_text = f"Prepared by {resolved_brand}"
    clients_status = append_client_to_clients_csv(
        clients_csv,
        client_name=lead.client_name.strip(),
        client_email=lead.client_email.strip(),
        brand_name=resolved_brand,
        url=lead.url,
        brand_color=resolved_color,
        brand_logo=None,
        footer_text=footer_text,
        report_format=fmt,
        max_links=max_links,
        timeout=timeout,
    )

    converted_at = utc_now_iso()
    try:
        clients_csv_rel = clients_csv.relative_to(project_root).as_posix()
    except ValueError:
        clients_csv_rel = clients_csv.as_posix()

    package_dir, config_path, checklist_path, welcome_path = create_client_package(
        lead=lead,
        plan=plan,
        currency=config.currency,
        package_root=packages_dir,
        template_dir=template_dir,
        clients_csv_rel=clients_csv_rel,
        brand_name=resolved_brand,
        brand_color=resolved_color,
        report_format=fmt,
        max_links=max_links,
        timeout=timeout,
        converted_at=converted_at,
    )

    try:
        package_rel = package_dir.relative_to(project_root).as_posix()
    except ValueError:
        package_rel = package_dir.as_posix()

    updated_lead = convert_lead_in_crm(
        crm_path,
        lead.lead_id,
        plan_id=plan.plan_id,
        currency=config.currency,
        price_monthly=plan.price_monthly,
        setup_fee=plan.setup_fee,
        client_package_path=package_rel,
        converted_at=converted_at,
    )

    weekly_path: Path | None = None
    if add_to_weekly_job and weekly_job_file is not None:
        weekly_path = update_weekly_job_config(
            weekly_job_file,
            clients_csv=clients_csv_rel,
            report_format=fmt,
            example_job_path=weekly_job_example,
        )

    return ConvertClientResult(
        lead_id=lead.lead_id,
        clients_csv_status=clients_status,
        client_package_dir=package_dir,
        client_config_path=config_path,
        onboarding_checklist_path=checklist_path,
        welcome_message_path=welcome_path,
        clients_csv_path=clients_csv,
        weekly_job_path=weekly_path,
        crm_notes=updated_lead.notes,
    )


def main(
    lead_id: str = typer.Option(..., "--lead-id"),
    plan: str = typer.Option(..., "--plan"),
    crm_path: str = typer.Option(DEFAULT_CRM_PATH, "--crm-path"),
    clients_csv: str = typer.Option(DEFAULT_CLIENTS_CSV, "--clients-csv"),
    pricing_file: str = typer.Option(DEFAULT_PRICING_FILE, "--pricing-file"),
    client_packages_dir: str = typer.Option(
        DEFAULT_PACKAGES_DIR, "--client-packages-dir"
    ),
    weekly_job_file: str | None = typer.Option(
        None, "--weekly-job-file", help="Path to weekly job JSON"
    ),
    add_to_weekly_job: str = typer.Option(
        "false", "--add-to-weekly-job", help="Update weekly job config: true/false"
    ),
    brand_name: str | None = typer.Option(None, "--brand-name"),
    brand_color: str | None = typer.Option(None, "--brand-color"),
    report_format: FormatChoice = typer.Option("both", "--format"),
    max_links: int = typer.Option(30, "--max-links"),
    timeout: float = typer.Option(10.0, "--timeout"),
) -> None:
    """Convert CRM lead to active client (clients CSV + client package)."""
    root = _project_root()
    crm_file = resolve_project_path(crm_path, root)
    clients_file = resolve_project_path(clients_csv, root)
    pricing_path = resolve_project_path(pricing_file, root)
    packages_root = resolve_project_path(client_packages_dir, root)
    packages_root.mkdir(parents=True, exist_ok=True)
    template_dir = root / "templates"

    weekly_path: Path | None = None
    weekly_example = resolve_project_path(DEFAULT_WEEKLY_EXAMPLE, root)
    if weekly_job_file:
        weekly_path = resolve_project_path(weekly_job_file, root)

    add_weekly = _parse_bool_option(add_to_weekly_job)
    if add_weekly and weekly_path is None:
        console.print(
            "[red]Error:[/red] --weekly-job-file is required when --add-to-weekly-job is true"
        )
        raise typer.Exit(code=1)

    pricing_config, warnings = load_pricing_config(pricing_path)
    for message in warnings:
        console.print(f"[yellow]Warning:[/yellow] {message}")

    try:
        get_plan(pricing_config, plan)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    try:
        result = run_convert_client(
            lead_id=lead_id,
            plan_id=plan,
            crm_path=crm_file,
            clients_csv=clients_file,
            pricing_file=pricing_path,
            packages_dir=packages_root,
            template_dir=template_dir,
            project_root=root,
            brand_name=brand_name,
            brand_color=brand_color,
            report_format=report_format.lower(),
            max_links=max_links,
            timeout=timeout,
            add_to_weekly_job=add_weekly,
            weekly_job_file=weekly_path,
            weekly_job_example=weekly_example,
        )
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print("\n[bold]Lead converted to client[/bold]\n")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("Lead ID", result.lead_id)
    table.add_row(
        "clients.csv",
        "[green]added[/green]"
        if result.clients_csv_status == "added"
        else "[yellow]already exists[/yellow]",
    )
    table.add_row("Client package", str(result.client_package_dir))
    table.add_row("client_config.json", str(result.client_config_path))
    table.add_row("onboarding_checklist.md", str(result.onboarding_checklist_path))
    table.add_row("welcome_message.md", str(result.welcome_message_path))
    if result.weekly_job_path:
        table.add_row("Weekly job", str(result.weekly_job_path))
    console.print(table)
    console.print(
        "\n[dim]Email is not sent automatically. Use welcome_message.md manually.[/dim]\n"
    )


if __name__ == "__main__":
    typer.run(main)
