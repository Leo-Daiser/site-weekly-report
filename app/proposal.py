from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import typer
from jinja2 import Environment, FileSystemLoader, select_autoescape
from rich.console import Console

from app.crm_store import attach_proposal_to_lead, find_lead_by_id, utc_now_iso
from app.leads import build_lead_slug
from app.models import LeadRecord, PricingPlan, ProposalRecord
from app.pricing import get_plan, list_plans, load_pricing_config
from app.utils import resolve_project_path

console = Console()
cli = typer.Typer(help="Commercial proposal generator for CRM leads.")

DEFAULT_CRM_PATH = "data/leads_crm.csv"
DEFAULT_PRICING_FILE = "data/pricing.example.json"
DEFAULT_OUTPUT_DIR = "proposals"

FormatChoice = Literal["md", "html", "both"]


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _template_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_project_root() / "templates")),
        autoescape=select_autoescape(["html", "xml"]),
    )


def build_proposal_dir_name(lead: LeadRecord) -> str:
    slug = build_lead_slug(lead.client_name, lead.normalized_domain)
    return f"{lead.lead_id}_{slug}"


def build_findings_text(
    *,
    health_score: int | None,
    health_label: str | None,
    sample_report_path: str | None,
) -> str:
    parts: list[str] = []
    if health_score is not None and health_score < 60:
        parts.append(
            "The site needs attention: several technical and SEO signals should be fixed."
        )
    elif health_score is not None and health_score >= 75:
        parts.append(
            "The site looks stable today, but regular weekly monitoring helps catch regressions early."
        )
    else:
        parts.append(
            "A weekly check helps track availability, SEO basics, broken links, and changes over time."
        )

    if health_label:
        parts.append(f"Current status label: {health_label}.")

    if sample_report_path:
        parts.append("A sample report for this site is already prepared and can be shared.")
    else:
        parts.append("A sample report can be prepared before the first paid cycle.")

    return " ".join(parts)


def _format_plan_line(plan: PricingPlan, currency: str) -> str:
    line = f"{plan.plan_id}: {currency} {plan.price_monthly}/mo"
    if plan.setup_fee:
        line += f" + {currency} {plan.setup_fee} setup"
    return line


def generate_proposal(
    *,
    lead: LeadRecord,
    plan: PricingPlan,
    currency: str,
    output_dir: Path,
    project_root: Path,
    output_format: str = "both",
    created_at: str | None = None,
) -> ProposalRecord:
    created = created_at or utc_now_iso()
    dir_name = build_proposal_dir_name(lead)
    proposal_dir = output_dir / dir_name
    proposal_dir.mkdir(parents=True, exist_ok=True)

    findings_text = build_findings_text(
        health_score=lead.health_score,
        health_label=lead.health_label,
        sample_report_path=lead.sample_report_path,
    )

    context: dict[str, object] = {
        "client_name": lead.client_name,
        "url": lead.url,
        "created_at": created,
        "health_score": lead.health_score,
        "health_label": lead.health_label,
        "sample_report_path": lead.sample_report_path,
        "plan": plan,
        "currency": currency,
        "findings_text": findings_text,
    }

    env = _template_env()
    fmt = output_format.lower()
    md_path: Path | None = None
    html_path: Path | None = None
    reply_path: Path | None = None

    if fmt in ("md", "both"):
        md_path = proposal_dir / "proposal.md"
        md_path.write_text(
            env.get_template("proposal.md.j2").render(**context),
            encoding="utf-8",
        )

    if fmt in ("html", "both"):
        html_path = proposal_dir / "proposal.html"
        html_path.write_text(
            env.get_template("proposal.html.j2").render(**context),
            encoding="utf-8",
        )

    reply_path = proposal_dir / "proposal_reply.md"
    reply_path.write_text(
        env.get_template("proposal_reply.md.j2").render(**context),
        encoding="utf-8",
    )

    def rel(path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            return path.relative_to(project_root).as_posix()
        except ValueError:
            return path.as_posix()

    record = ProposalRecord(
        lead_id=lead.lead_id,
        client_name=lead.client_name,
        client_email=lead.client_email,
        url=lead.url,
        normalized_domain=lead.normalized_domain,
        health_score=lead.health_score,
        health_label=lead.health_label,
        sample_report_path=lead.sample_report_path,
        plan_id=plan.plan_id,
        plan_name=plan.name,
        price_monthly=plan.price_monthly,
        setup_fee=plan.setup_fee,
        currency=currency,
        created_at=created,
        proposal_md_path=rel(md_path),
        proposal_html_path=rel(html_path),
        proposal_reply_path=rel(reply_path),
    )

    json_path = proposal_dir / "proposal.json"
    json_path.write_text(
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return record


@cli.command("list-plans")
def list_plans_cmd(
    pricing_file: str = typer.Option(
        DEFAULT_PRICING_FILE, "--pricing-file", help="Path to pricing JSON"
    ),
) -> None:
    """Показать доступные тарифы."""
    root = _project_root()
    path = resolve_project_path(pricing_file, root)
    config, warnings = load_pricing_config(path)
    for message in warnings:
        console.print(f"[yellow]Warning:[/yellow] {message}")

    console.print("\n[bold]Pricing plans[/bold]\n")
    for plan in list_plans(config):
        console.print(_format_plan_line(plan, config.currency))


@cli.command("create")
def create_cmd(
    lead_id: str = typer.Option(..., "--lead-id"),
    plan: str = typer.Option(..., "--plan"),
    crm_path: str = typer.Option(DEFAULT_CRM_PATH, "--crm-path"),
    pricing_file: str = typer.Option(DEFAULT_PRICING_FILE, "--pricing-file"),
    output_dir: str = typer.Option(DEFAULT_OUTPUT_DIR, "--output-dir"),
    output_format: FormatChoice = typer.Option("both", "--format"),
) -> None:
    """Создать коммерческое предложение для лида из CRM."""
    root = _project_root()
    crm_file = resolve_project_path(crm_path, root)
    pricing_path = resolve_project_path(pricing_file, root)
    proposals_dir = resolve_project_path(output_dir, root)
    proposals_dir.mkdir(parents=True, exist_ok=True)

    lead = find_lead_by_id(crm_file, lead_id)
    if lead is None:
        console.print(f"[red]Lead not found:[/red] {lead_id}")
        raise typer.Exit(code=1)

    config, warnings = load_pricing_config(pricing_path)
    for message in warnings:
        console.print(f"[yellow]Warning:[/yellow] {message}")

    try:
        selected_plan = get_plan(config, plan)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    fmt = output_format.lower()
    if fmt not in ("md", "html", "both"):
        console.print("[red]Error:[/red] --format must be md, html, or both")
        raise typer.Exit(code=1)

    record = generate_proposal(
        lead=lead,
        plan=selected_plan,
        currency=config.currency,
        output_dir=proposals_dir,
        project_root=root,
        output_format=fmt,
    )

    proposal_dir_rel = f"{output_dir.rstrip('/')}/{build_proposal_dir_name(lead)}"
    attach_proposal_to_lead(crm_file, lead.lead_id, proposal_path=proposal_dir_rel)

    console.print(f"\n[green]Proposal created[/green] for {lead.client_name} ({lead.lead_id})")
    console.print(f"Plan: {record.plan_name} ({config.currency} {record.price_monthly}/mo)")
    if record.proposal_md_path:
        console.print(f"Markdown: {record.proposal_md_path}")
    if record.proposal_html_path:
        console.print(f"HTML: {record.proposal_html_path}")
    if record.proposal_reply_path:
        console.print(f"Reply text: {record.proposal_reply_path}")
    console.print(f"CRM proposal_path: {proposal_dir_rel}")
    console.print("\n[dim]Email is not sent automatically.[/dim]\n")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
