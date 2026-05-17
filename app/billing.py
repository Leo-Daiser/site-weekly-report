from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from app.billing_store import load_subscriptions, set_subscription_status, upsert_subscription
from app.models import SubscriptionRecord
from app.utils import resolve_project_path

console = Console()
cli = typer.Typer(help="Stripe-compatible billing helpers for local development.")

DEFAULT_SUBSCRIPTIONS = "data/subscriptions.csv"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def verify_stripe_env() -> list[str]:
    missing: list[str] = []
    for name in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"):
        if not os.getenv(name):
            missing.append(name)
    return missing


def _event_object(event: dict[str, Any]) -> dict[str, Any]:
    return event.get("data", {}).get("object", {}) if isinstance(event.get("data"), dict) else {}


def _email_from_object(obj: dict[str, Any]) -> str:
    return (
        obj.get("customer_email")
        or obj.get("receipt_email")
        or obj.get("customer_details", {}).get("email")
        or ""
    )


def apply_stripe_event(event: dict[str, Any], subscriptions_path: Path) -> SubscriptionRecord | None:
    event_type = event.get("type")
    obj = _event_object(event)
    subscription_id = obj.get("subscription") or obj.get("id")
    customer_id = obj.get("customer")
    email = _email_from_object(obj)

    if event_type == "checkout.session.completed":
        metadata = obj.get("metadata") or {}
        record = SubscriptionRecord(
            customer_email=email,
            plan_id=metadata.get("plan_id") or obj.get("client_reference_id") or "unknown",
            payment_status="active",
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
        )
        return upsert_subscription(subscriptions_path, record)

    if event_type == "invoice.paid":
        updated = set_subscription_status(
            subscriptions_path,
            stripe_subscription_id=subscription_id,
            customer_email=email,
            status="active",
        )
        if updated:
            return updated
        return upsert_subscription(
            subscriptions_path,
            SubscriptionRecord(
                customer_email=email,
                plan_id=(obj.get("metadata") or {}).get("plan_id") or "unknown",
                payment_status="active",
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
            ),
        )

    if event_type == "invoice.payment_failed":
        return set_subscription_status(
            subscriptions_path,
            stripe_subscription_id=subscription_id,
            customer_email=email,
            status="payment_failed",
        )

    if event_type == "customer.subscription.deleted":
        return set_subscription_status(
            subscriptions_path,
            stripe_subscription_id=obj.get("id"),
            customer_email=email,
            status="cancelled",
        )

    return None


@cli.command("verify-config")
def verify_config_cmd() -> None:
    """Check required Stripe env vars without contacting Stripe."""
    missing = verify_stripe_env()
    if missing:
        console.print("[yellow]Stripe config incomplete[/yellow]")
        for name in missing:
            console.print(f"Missing: {name}")
        raise typer.Exit(code=1)
    console.print("[green]Stripe config OK[/green]")


@cli.command("list")
def list_cmd(
    subscriptions_path: str = typer.Option(DEFAULT_SUBSCRIPTIONS, "--subscriptions-path"),
) -> None:
    root = _project_root()
    records = load_subscriptions(resolve_project_path(subscriptions_path, root))
    table = Table(show_header=True)
    table.add_column("Email")
    table.add_column("Plan")
    table.add_column("Status")
    table.add_column("Subscription")
    for record in records:
        table.add_row(
            record.customer_email,
            record.plan_id,
            record.payment_status,
            record.stripe_subscription_id or "",
        )
    console.print(table)


@cli.command("sync-local")
def sync_local_cmd(
    event_file: str = typer.Option(..., "--event-file"),
    subscriptions_path: str = typer.Option(DEFAULT_SUBSCRIPTIONS, "--subscriptions-path"),
) -> None:
    """Apply a saved Stripe event JSON to local subscription storage."""
    root = _project_root()
    event_path = resolve_project_path(event_file, root)
    payload = json.loads(event_path.read_text(encoding="utf-8"))
    record = apply_stripe_event(payload, resolve_project_path(subscriptions_path, root))
    if record is None:
        console.print(f"[yellow]Ignored event:[/yellow] {payload.get('type')}")
        return
    console.print(f"[green]Updated subscription[/green] {record.customer_email}: {record.payment_status}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
