from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from app.convert_client import run_convert_client
from app.crm_store import add_lead, generate_next_lead_id
from app.models import LeadRecord, SignupRecord
from app.signup_store import create_signup, load_signups, update_signup, utc_now_iso
from app.utils import normalize_domain, resolve_project_path

console = Console()
cli = typer.Typer(help="Pending signup intake and approval workflow.")

DEFAULT_SIGNUPS = "data/pending_signups.csv"
DEFAULT_CRM = "data/leads_crm.csv"
DEFAULT_CLIENTS = "data/clients.csv"
DEFAULT_PRICING = "data/pricing.example.json"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def first_website(signup: SignupRecord) -> str:
    urls = [item.strip() for item in signup.website_urls.replace("\n", ",").split(",")]
    return next((url for url in urls if url), "")


def approve_signup(
    *,
    signup_id: str,
    signups_path: Path,
    crm_path: Path,
    clients_csv: Path,
    pricing_file: Path,
    packages_dir: Path,
    template_dir: Path,
    project_root: Path,
    weekly_job_file: Path | None = None,
) -> SignupRecord:
    signups = load_signups(signups_path)
    signup = next((item for item in signups if item.signup_id == signup_id), None)
    if signup is None:
        raise ValueError(f"Signup not found: {signup_id}")
    if signup.status not in ("pending", "needs_review"):
        raise ValueError(f"Signup is not pending: {signup.status}")

    url = first_website(signup)
    if not url:
        signup.status = "needs_review"
        signup.notes = "No website URL supplied"
        update_signup(signups_path, signup)
        return signup

    lead_id = generate_next_lead_id(crm_path)
    lead = LeadRecord(
        lead_id=lead_id,
        client_name=signup.agency_name,
        client_email=signup.report_recipient_email or signup.billing_email,
        url=url,
        normalized_domain=normalize_domain(url),
        source="self_serve_signup",
        status="interested",
        created_at=signup.created_at or utc_now_iso(),
        notes=f"Signup: {signup.signup_id}; plan={signup.plan_id}; sites={signup.website_urls}",
    )
    add_lead(crm_path, lead)
    run_convert_client(
        lead_id=lead_id,
        plan_id=signup.plan_id,
        crm_path=crm_path,
        clients_csv=clients_csv,
        pricing_file=pricing_file,
        packages_dir=packages_dir,
        template_dir=template_dir,
        project_root=project_root,
        brand_name=signup.brand_name or signup.agency_name,
        brand_color=signup.brand_color,
        report_format="both",
        add_to_weekly_job=weekly_job_file is not None,
        weekly_job_file=weekly_job_file,
        weekly_job_example=project_root / "data" / "weekly_jobs.example.json",
    )
    signup.status = "approved"
    signup.approved_at = utc_now_iso()
    update_signup(signups_path, signup)
    return signup


@cli.command("create")
def create_cmd(
    agency_name: str = typer.Option(..., "--agency-name"),
    billing_email: str = typer.Option(..., "--billing-email"),
    report_recipient_email: str = typer.Option(..., "--report-recipient-email"),
    plan: str = typer.Option(..., "--plan"),
    website_urls: str = typer.Option(..., "--website-urls"),
    brand_name: str = typer.Option("", "--brand-name"),
    brand_color: str = typer.Option("#2563eb", "--brand-color"),
    signups_path: str = typer.Option(DEFAULT_SIGNUPS, "--signups-path"),
) -> None:
    root = _project_root()
    signup = create_signup(
        resolve_project_path(signups_path, root),
        SignupRecord(
            signup_id="",
            agency_name=agency_name,
            billing_email=billing_email,
            report_recipient_email=report_recipient_email,
            plan_id=plan,
            website_urls=website_urls,
            brand_name=brand_name,
            brand_color=brand_color,
        ),
    )
    console.print(f"[green]Signup created[/green] {signup.signup_id}")


@cli.command("list")
def list_cmd(signups_path: str = typer.Option(DEFAULT_SIGNUPS, "--signups-path")) -> None:
    root = _project_root()
    table = Table(show_header=True)
    table.add_column("ID")
    table.add_column("Agency")
    table.add_column("Plan")
    table.add_column("Status")
    table.add_column("Websites")
    for signup in load_signups(resolve_project_path(signups_path, root)):
        table.add_row(signup.signup_id, signup.agency_name, signup.plan_id, signup.status, signup.website_urls)
    console.print(table)


@cli.command("approve")
def approve_cmd(
    signup_id: str = typer.Option(..., "--signup-id"),
    signups_path: str = typer.Option(DEFAULT_SIGNUPS, "--signups-path"),
    crm_path: str = typer.Option(DEFAULT_CRM, "--crm-path"),
    clients_csv: str = typer.Option(DEFAULT_CLIENTS, "--clients-csv"),
    pricing_file: str = typer.Option(DEFAULT_PRICING, "--pricing-file"),
    packages_dir: str = typer.Option("client_packages", "--packages-dir"),
    weekly_job_file: str | None = typer.Option(None, "--weekly-job-file"),
) -> None:
    root = _project_root()
    signup = approve_signup(
        signup_id=signup_id,
        signups_path=resolve_project_path(signups_path, root),
        crm_path=resolve_project_path(crm_path, root),
        clients_csv=resolve_project_path(clients_csv, root),
        pricing_file=resolve_project_path(pricing_file, root),
        packages_dir=resolve_project_path(packages_dir, root),
        template_dir=root / "templates",
        project_root=root,
        weekly_job_file=resolve_project_path(weekly_job_file, root) if weekly_job_file else None,
    )
    console.print(f"[green]Signup {signup.signup_id} status:[/green] {signup.status}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
