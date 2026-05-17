from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import typer
from jinja2 import Environment, FileSystemLoader, select_autoescape
from rich.console import Console
from rich.table import Table

from app.crm_store import (
    add_lead,
    attach_sample_to_lead,
    find_duplicate,
    generate_next_lead_id,
    get_followups_due,
    load_leads,
    update_lead_status,
    utc_now_iso,
)
from app.models import LeadRecord
from app.utils import normalize_domain, normalize_url, resolve_project_path

console = Console()
cli = typer.Typer(help="Lead CRM and outreach tracker (local CSV).")
DEFAULT_CRM_PATH = "data/leads_crm.csv"
DEFAULT_EXPORTS_DIR = "crm_exports"


def _parse_bool_option(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _crm_path_option(value: str) -> Path:
    root = Path(__file__).resolve().parent.parent
    return resolve_project_path(value, root)


def _exports_dir() -> Path:
    root = Path(__file__).resolve().parent.parent
    path = root / DEFAULT_EXPORTS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _render_template(name: str, **context: object) -> str:
    root = Path(__file__).resolve().parent.parent
    env = Environment(
        loader=FileSystemLoader(str(root / "templates")),
        autoescape=select_autoescape(["html", "xml"]),
    )
    return env.get_template(name).render(**context).strip()


def _filter_leads(
    leads: list[LeadRecord],
    *,
    status: str | None = None,
    source: str | None = None,
    tag: str | None = None,
) -> list[LeadRecord]:
    result = leads
    if status:
        needle = status.strip().lower()
        result = [lead for lead in result if lead.status == needle]
    if source:
        needle = source.strip().lower()
        result = [lead for lead in result if lead.source.lower() == needle]
    if tag:
        needle = tag.strip().lower()
        result = [
            lead
            for lead in result
            if needle in [t.strip().lower() for t in lead.tags.split(",") if t.strip()]
        ]
    return result


def _print_leads_table(leads: list[LeadRecord]) -> None:
    table = Table(show_header=True)
    table.add_column("Lead ID")
    table.add_column("Client")
    table.add_column("URL")
    table.add_column("Status")
    table.add_column("Score")
    table.add_column("Follow-up")
    for lead in leads:
        table.add_row(
            lead.lead_id,
            lead.client_name,
            lead.url,
            lead.status,
            str(lead.health_score) if lead.health_score is not None else "-",
            (lead.next_followup_at or "-")[:10],
        )
    console.print(table)


@cli.command("add-lead")
def add_lead_cmd(
    client_name: str = typer.Option(..., "--client-name"),
    url: str = typer.Option(..., "--url"),
    client_email: str | None = typer.Option(None, "--client-email"),
    source: str = typer.Option("", "--source"),
    tags: str = typer.Option("", "--tags"),
    notes: str = typer.Option("", "--notes"),
    crm_path: str = typer.Option(DEFAULT_CRM_PATH, "--crm-path"),
) -> None:
    """Добавить лида в CRM."""
    path = _crm_path_option(crm_path)
    try:
        normalized_url = normalize_url(url)
    except ValueError as exc:
        console.print(f"[red]Ошибка:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    duplicate = find_duplicate(path, normalized_url, client_email)
    if duplicate is not None:
        console.print(
            f"[yellow]Duplicate:[/yellow] {duplicate.lead_id} "
            f"({duplicate.normalized_domain})"
        )
        raise typer.Exit(code=1)

    lead = LeadRecord(
        lead_id=generate_next_lead_id(path),
        client_name=client_name.strip(),
        client_email=client_email.strip() if client_email else None,
        url=normalized_url,
        normalized_domain=normalize_domain(normalized_url),
        source=source.strip(),
        status="new",
        created_at=utc_now_iso(),
        tags=tags.strip(),
        notes=notes.strip(),
    )
    add_lead(path, lead)
    console.print(f"[green]Lead added:[/green] {lead.lead_id}")


@cli.command("list")
def list_cmd(
    status: str | None = typer.Option(None, "--status"),
    source: str | None = typer.Option(None, "--source"),
    tag: str | None = typer.Option(None, "--tag"),
    limit: int = typer.Option(20, "--limit"),
    crm_path: str = typer.Option(DEFAULT_CRM_PATH, "--crm-path"),
) -> None:
    """Список лидов."""
    path = _crm_path_option(crm_path)
    leads = _filter_leads(load_leads(path), status=status, source=source, tag=tag)
    if limit > 0:
        leads = leads[:limit]
    if not leads:
        console.print("[dim]No leads found.[/dim]")
        return
    _print_leads_table(leads)


@cli.command("mark-status")
def mark_status_cmd(
    lead_id: str = typer.Option(..., "--lead-id"),
    status: str = typer.Option(..., "--status"),
    crm_path: str = typer.Option(DEFAULT_CRM_PATH, "--crm-path"),
) -> None:
    """Обновить статус лида."""
    path = _crm_path_option(crm_path)
    try:
        updated = update_lead_status(path, lead_id, status)
    except ValueError as exc:
        console.print(f"[red]Ошибка:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Updated:[/green] {updated.lead_id} -> {updated.status}")
    if updated.next_followup_at:
        console.print(f"Next follow-up: {updated.next_followup_at[:10]}")


@cli.command("attach-sample")
def attach_sample_cmd(
    lead_id: str = typer.Option(..., "--lead-id"),
    sample_report_path: str = typer.Option(..., "--sample-report-path"),
    health_score: int | None = typer.Option(None, "--health-score"),
    health_label: str | None = typer.Option(None, "--health-label"),
    crm_path: str = typer.Option(DEFAULT_CRM_PATH, "--crm-path"),
) -> None:
    """Прикрепить sample-report к лиду."""
    path = _crm_path_option(crm_path)
    try:
        updated = attach_sample_to_lead(
            path,
            lead_id,
            sample_report_path=sample_report_path,
            health_score=health_score,
            health_label=health_label,
        )
    except ValueError as exc:
        console.print(f"[red]Ошибка:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Attached sample to[/green] {updated.lead_id}")


@cli.command("followups")
def followups_cmd(
    today: bool = typer.Option(False, "--today", help="Use today's date"),
    on_date: str | None = typer.Option(None, "--date", help="YYYY-MM-DD"),
    export: str = typer.Option("false", "--export", help="Export markdown: true/false"),
    crm_path: str = typer.Option(DEFAULT_CRM_PATH, "--crm-path"),
) -> None:
    """Лиды с наступившим follow-up."""
    path = _crm_path_option(crm_path)
    if on_date:
        ref = date.fromisoformat(on_date)
    elif today:
        ref = date.today()
    else:
        ref = date.today()

    due = get_followups_due(path, ref)
    if not due:
        console.print(f"[dim]No follow-ups due on or before {ref.isoformat()}.[/dim]")
    else:
        console.print(f"\n[bold]Follow-ups due ≤ {ref.isoformat()}[/bold]\n")
        _print_leads_table(due)

    if _parse_bool_option(export):
        lines = [
            f"# Follow-ups {ref.isoformat()}",
            "",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
        ]
        for lead in due:
            msg = _render_template(
                "followup_message.md.j2",
                url=lead.url,
                client_name=lead.client_name,
            )
            lines.extend(
                [
                    f"## {lead.client_name} ({lead.lead_id})",
                    "",
                    f"- URL: {lead.url}",
                    f"- Status: {lead.status}",
                    f"- Sample: {lead.sample_report_path or '—'}",
                    "",
                    "### Suggested follow-up",
                    "",
                    msg,
                    "",
                    "---",
                    "",
                ]
            )
        out = _exports_dir() / f"followups_{ref.isoformat()}.md"
        out.write_text("\n".join(lines), encoding="utf-8")
        console.print(f"\nExported: {out}")


@cli.command("export-outreach")
def export_outreach_cmd(
    status: str = typer.Option("new", "--status"),
    limit: int = typer.Option(10, "--limit"),
    crm_path: str = typer.Option(DEFAULT_CRM_PATH, "--crm-path"),
) -> None:
    """Экспорт outreach-сообщений в markdown."""
    path = _crm_path_option(crm_path)
    leads = _filter_leads(load_leads(path), status=status)
    if limit > 0:
        leads = leads[:limit]

    today = date.today().isoformat()
    lines = [
        f"# Outreach {today}",
        "",
        f"Status filter: {status}",
        f"Count: {len(leads)}",
        "",
    ]
    for lead in leads:
        msg = _render_template(
            "outreach_message.md.j2",
            url=lead.url,
            health_score=lead.health_score,
            health_label=lead.health_label,
        )
        lines.extend(
            [
                f"## {lead.client_name} ({lead.lead_id})",
                "",
                f"- URL: {lead.url}",
                f"- Email: {lead.client_email or '—'}",
                f"- Sample report: {lead.sample_report_path or '—'}",
                "",
                "### Suggested outreach message",
                "",
                msg,
                "",
                "---",
                "",
            ]
        )
    out = _exports_dir() / f"outreach_{today}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    console.print(f"[green]Exported:[/green] {out} ({len(leads)} leads)")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
