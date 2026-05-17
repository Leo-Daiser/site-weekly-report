from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from app.models import PaymentStatus, SubscriptionRecord

SUBSCRIPTION_COLUMNS = [
    "customer_email",
    "plan_id",
    "payment_status",
    "stripe_customer_id",
    "stripe_subscription_id",
    "current_period_end",
    "updated_at",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_subscriptions(path: Path) -> list[SubscriptionRecord]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            SubscriptionRecord(
                customer_email=row.get("customer_email", ""),
                plan_id=row.get("plan_id", ""),
                payment_status=(row.get("payment_status") or "pending_payment"),
                stripe_customer_id=row.get("stripe_customer_id") or None,
                stripe_subscription_id=row.get("stripe_subscription_id") or None,
                current_period_end=row.get("current_period_end") or None,
                updated_at=row.get("updated_at", ""),
            )
            for row in reader
        ]


def save_subscriptions(path: Path, records: list[SubscriptionRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUBSCRIPTION_COLUMNS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.model_dump())


def upsert_subscription(path: Path, record: SubscriptionRecord) -> SubscriptionRecord:
    records = load_subscriptions(path)
    record.updated_at = record.updated_at or utc_now_iso()
    replaced = False
    for index, existing in enumerate(records):
        same_subscription = (
            record.stripe_subscription_id
            and existing.stripe_subscription_id == record.stripe_subscription_id
        )
        same_email = existing.customer_email.lower() == record.customer_email.lower()
        if same_subscription or same_email:
            records[index] = record
            replaced = True
            break
    if not replaced:
        records.append(record)
    save_subscriptions(path, records)
    return record


def set_subscription_status(
    path: Path,
    *,
    stripe_subscription_id: str | None,
    customer_email: str | None,
    status: PaymentStatus,
) -> SubscriptionRecord | None:
    records = load_subscriptions(path)
    updated: SubscriptionRecord | None = None
    for record in records:
        if stripe_subscription_id and record.stripe_subscription_id == stripe_subscription_id:
            record.payment_status = status
            record.updated_at = utc_now_iso()
            updated = record
            break
        if customer_email and record.customer_email.lower() == customer_email.lower():
            record.payment_status = status
            record.updated_at = utc_now_iso()
            updated = record
            break
    if updated:
        save_subscriptions(path, records)
    return updated
