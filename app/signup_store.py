from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from app.models import SignupRecord

SIGNUP_COLUMNS = [
    "signup_id",
    "agency_name",
    "billing_email",
    "report_recipient_email",
    "plan_id",
    "website_urls",
    "brand_name",
    "brand_color",
    "logo_url",
    "status",
    "stripe_checkout_session_id",
    "payment_status",
    "payment_notes",
    "created_at",
    "approved_at",
    "notes",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def next_signup_id(existing: list[SignupRecord]) -> str:
    max_num = 0
    for signup in existing:
        try:
            max_num = max(max_num, int(signup.signup_id.split("_")[-1]))
        except ValueError:
            continue
    return f"signup_{max_num + 1:04d}"


def load_signups(path: Path) -> list[SignupRecord]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            SignupRecord(
                signup_id=row.get("signup_id", ""),
                agency_name=row.get("agency_name", ""),
                billing_email=row.get("billing_email", ""),
                report_recipient_email=row.get("report_recipient_email", ""),
                plan_id=row.get("plan_id", ""),
                website_urls=row.get("website_urls", ""),
                brand_name=row.get("brand_name", ""),
                brand_color=row.get("brand_color", "#2563eb") or "#2563eb",
                logo_url=row.get("logo_url") or None,
                status=row.get("status", "pending") or "pending",
                stripe_checkout_session_id=row.get("stripe_checkout_session_id") or None,
                payment_status=row.get("payment_status", "pending_payment") or "pending_payment",
                payment_notes=row.get("payment_notes", ""),
                created_at=row.get("created_at", ""),
                approved_at=row.get("approved_at") or None,
                notes=row.get("notes", ""),
            )
            for row in reader
        ]


def save_signups(path: Path, signups: list[SignupRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SIGNUP_COLUMNS)
        writer.writeheader()
        for signup in signups:
            writer.writerow(signup.model_dump())


def create_signup(path: Path, signup: SignupRecord) -> SignupRecord:
    signups = load_signups(path)
    if not signup.signup_id:
        signup.signup_id = next_signup_id(signups)
    if not signup.created_at:
        signup.created_at = utc_now_iso()
    signups.append(signup)
    save_signups(path, signups)
    return signup


def find_signup(path: Path, signup_id: str) -> SignupRecord | None:
    for signup in load_signups(path):
        if signup.signup_id == signup_id:
            return signup
    return None


def update_signup(path: Path, updated: SignupRecord) -> SignupRecord:
    signups = load_signups(path)
    for index, signup in enumerate(signups):
        if signup.signup_id == updated.signup_id:
            signups[index] = updated
            save_signups(path, signups)
            return updated
    raise ValueError(f"Signup not found: {updated.signup_id}")
