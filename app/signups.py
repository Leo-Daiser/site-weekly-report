from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from app.convert_client import run_convert_client
from app.crm_store import add_lead, generate_next_lead_id
from app.billing_store import load_subscriptions
from app.models import LeadRecord, SignupRecord, SubscriptionRecord
from app.pricing import get_plan, load_pricing_config
from app.signup_store import create_signup, load_signups, update_signup, utc_now_iso
from app.utils import normalize_domain, normalize_url, resolve_project_path

console = Console()
cli = typer.Typer(help="Pending signup intake and approval workflow.")

DEFAULT_SIGNUPS = "data/pending_signups.csv"
DEFAULT_CRM = "data/leads_crm.csv"
DEFAULT_CLIENTS = "data/clients.csv"
DEFAULT_PRICING = "data/pricing.example.json"
DEFAULT_SUBSCRIPTIONS = "data/subscriptions.csv"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def first_website(signup: SignupRecord) -> str:
    urls = [item.strip() for item in signup.website_urls.replace("\n", ",").split(",")]
    return next((url for url in urls if url), "")


def signup_website_urls(signup: SignupRecord) -> list[str]:
    raw_urls = [
        item.strip()
        for item in signup.website_urls.replace("\n", ",").split(",")
        if item.strip()
    ]
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_url in raw_urls:
        url = normalize_url(raw_url)
        key = url.rstrip("/").lower()
        if key not in seen:
            normalized.append(url)
            seen.add(key)
    return normalized


def validate_signup_for_plan(signup: SignupRecord, pricing_file: Path) -> list[str]:
    try:
        config, _warnings = load_pricing_config(pricing_file)
        plan = get_plan(config, signup.plan_id)
        urls = signup_website_urls(signup)
    except (OSError, ValueError) as exc:
        return [str(exc)]

    errors: list[str] = []
    if not urls:
        errors.append("At least one website URL is required")
    if len(urls) > plan.sites_included:
        errors.append(
            f"Plan {plan.name} includes {plan.sites_included} site(s), got {len(urls)}"
        )
    return errors


def subscription_for_signup(
    signup: SignupRecord,
    subscriptions_path: Path,
) -> SubscriptionRecord | None:
    billing_email = signup.billing_email.strip().lower()
    recipient_email = signup.report_recipient_email.strip().lower()
    for record in load_subscriptions(subscriptions_path):
        record_email = record.customer_email.strip().lower()
        if record_email and record_email in {billing_email, recipient_email}:
            return record
    return None


def apply_payment_record_to_signup(
    signup: SignupRecord,
    subscription: SubscriptionRecord | None,
) -> bool:
    original = signup.model_dump()
    if subscription is None:
        signup.payment_status = "pending_payment"
        signup.payment_notes = "No matching subscription found"
        if signup.status == "pending":
            signup.status = "pending_payment"
        return signup.model_dump() != original

    signup.payment_status = subscription.payment_status
    if subscription.plan_id and subscription.plan_id != signup.plan_id:
        signup.payment_notes = (
            f"Plan mismatch: signup={signup.plan_id}, subscription={subscription.plan_id}"
        )
        signup.status = "needs_review"
    else:
        signup.payment_notes = f"Matched subscription for {subscription.customer_email}"
        if subscription.payment_status == "active" and signup.status == "pending_payment":
            signup.status = "pending"
        if subscription.payment_status in ("payment_failed", "cancelled"):
            signup.status = "needs_review"
    return signup.model_dump() != original


def reconcile_signup_payments(
    *,
    signups_path: Path,
    subscriptions_path: Path,
) -> tuple[int, int]:
    signups = load_signups(signups_path)
    updated = 0
    for signup in signups:
        if signup.status in ("approved", "rejected"):
            continue
        subscription = subscription_for_signup(signup, subscriptions_path)
        if apply_payment_record_to_signup(signup, subscription):
            updated += 1
    if updated:
        from app.signup_store import save_signups

        save_signups(signups_path, signups)
    return len(signups), updated


def validate_signup_payment(
    signup: SignupRecord,
    *,
    subscriptions_path: Path | None,
    require_payment: bool,
) -> list[str]:
    errors: list[str] = []
    subscription = subscription_for_signup(signup, subscriptions_path) if subscriptions_path else None
    if subscription:
        apply_payment_record_to_signup(signup, subscription)
        if subscription.plan_id and subscription.plan_id != signup.plan_id:
            errors.append(
                f"Plan mismatch: signup={signup.plan_id}, subscription={subscription.plan_id}"
            )
    elif require_payment:
        signup.payment_status = "pending_payment"
        signup.payment_notes = "No matching subscription found"
        errors.append("Payment is not active: no matching subscription found")

    if signup.payment_status in ("payment_failed", "cancelled"):
        errors.append(f"Payment is not active: {signup.payment_status}")
    if require_payment and signup.payment_status != "active":
        errors.append(f"Payment is not active: {signup.payment_status}")
    return errors


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
    subscriptions_path: Path | None = None,
    require_payment: bool = False,
) -> SignupRecord:
    signups = load_signups(signups_path)
    signup = next((item for item in signups if item.signup_id == signup_id), None)
    if signup is None:
        raise ValueError(f"Signup not found: {signup_id}")
    if signup.status not in ("pending", "pending_payment", "needs_review"):
        raise ValueError(f"Signup is not pending: {signup.status}")

    validation_errors = validate_signup_for_plan(signup, pricing_file)
    validation_errors.extend(
        validate_signup_payment(
            signup,
            subscriptions_path=subscriptions_path,
            require_payment=require_payment,
        )
    )
    if validation_errors:
        signup.status = "needs_review"
        signup.notes = "; ".join(dict.fromkeys(validation_errors))
        update_signup(signups_path, signup)
        return signup
    url = signup_website_urls(signup)[0]

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


def set_signup_status(
    *,
    signup_id: str,
    signups_path: Path,
    status: str,
    notes: str = "",
) -> SignupRecord:
    signup = next((item for item in load_signups(signups_path) if item.signup_id == signup_id), None)
    if signup is None:
        raise ValueError(f"Signup not found: {signup_id}")
    signup.status = status  # type: ignore[assignment]
    if notes:
        signup.notes = notes
    return update_signup(signups_path, signup)


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
            status="pending_payment",
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
    table.add_column("Payment")
    table.add_column("Websites")
    for signup in load_signups(resolve_project_path(signups_path, root)):
        table.add_row(
            signup.signup_id,
            signup.agency_name,
            signup.plan_id,
            signup.status,
            signup.payment_status,
            signup.website_urls,
        )


@cli.command("reconcile-payments")
def reconcile_payments_cmd(
    signups_path: str = typer.Option(DEFAULT_SIGNUPS, "--signups-path"),
    subscriptions_path: str = typer.Option(DEFAULT_SUBSCRIPTIONS, "--subscriptions-path"),
) -> None:
    root = _project_root()
    total, updated = reconcile_signup_payments(
        signups_path=resolve_project_path(signups_path, root),
        subscriptions_path=resolve_project_path(subscriptions_path, root),
    )
    console.print(f"[green]Reconciled[/green] {updated}/{total} signup(s)")
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
    subscriptions_path: str = typer.Option(DEFAULT_SUBSCRIPTIONS, "--subscriptions-path"),
    require_payment: bool = typer.Option(False, "--require-payment/--manual-mode"),
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
        subscriptions_path=resolve_project_path(subscriptions_path, root),
        require_payment=require_payment,
    )
    console.print(f"[green]Signup {signup.signup_id} status:[/green] {signup.status}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
