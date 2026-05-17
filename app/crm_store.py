from __future__ import annotations

import csv
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.models import LeadRecord
from app.utils import normalize_domain, normalize_url

CRM_CSV_COLUMNS = (
    "lead_id",
    "client_name",
    "client_email",
    "url",
    "normalized_domain",
    "source",
    "status",
    "created_at",
    "last_contacted_at",
    "next_followup_at",
    "sample_report_path",
    "health_score",
    "health_label",
    "notes",
    "tags",
    "proposal_path",
)

VALID_LEAD_STATUSES: frozenset[str] = frozenset(
    {
        "new",
        "sample_created",
        "contacted",
        "followup_needed",
        "replied",
        "interested",
        "not_interested",
        "converted",
        "lost",
    }
)

_LEAD_ID_RE = re.compile(r"^lead_(\d+)$", re.IGNORECASE)
FOLLOWUP_DAYS_AFTER_CONTACT = 3


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _parse_optional_int(value: str | None) -> int | None:
    text = _empty_to_none(value)
    if text is None:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _lead_from_row(row: dict[str, str]) -> LeadRecord:
    status = (_empty_to_none(row.get("status")) or "new").lower()
    if status not in VALID_LEAD_STATUSES:
        status = "new"
    return LeadRecord(
        lead_id=row.get("lead_id", "") or "",
        client_name=row.get("client_name", "") or "",
        client_email=_empty_to_none(row.get("client_email")),
        url=row.get("url", "") or "",
        normalized_domain=row.get("normalized_domain", "") or "",
        source=row.get("source", "") or "",
        status=status,  # type: ignore[arg-type]
        created_at=row.get("created_at", "") or "",
        last_contacted_at=_empty_to_none(row.get("last_contacted_at")),
        next_followup_at=_empty_to_none(row.get("next_followup_at")),
        sample_report_path=_empty_to_none(row.get("sample_report_path")),
        health_score=_parse_optional_int(row.get("health_score")),
        health_label=_empty_to_none(row.get("health_label")),
        notes=row.get("notes", "") or "",
        tags=row.get("tags", "") or "",
        proposal_path=_empty_to_none(row.get("proposal_path")),
    )


def _lead_to_row(lead: LeadRecord) -> dict[str, str]:
    return {
        "lead_id": lead.lead_id,
        "client_name": lead.client_name,
        "client_email": lead.client_email or "",
        "url": lead.url,
        "normalized_domain": lead.normalized_domain,
        "source": lead.source,
        "status": lead.status,
        "created_at": lead.created_at,
        "last_contacted_at": lead.last_contacted_at or "",
        "next_followup_at": lead.next_followup_at or "",
        "sample_report_path": lead.sample_report_path or "",
        "health_score": str(lead.health_score) if lead.health_score is not None else "",
        "health_label": lead.health_label or "",
        "notes": lead.notes,
        "tags": lead.tags,
        "proposal_path": lead.proposal_path or "",
    }


def ensure_crm_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(CRM_CSV_COLUMNS))
            writer.writeheader()


def _normalize_row(row: dict[str, str | None]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for col in CRM_CSV_COLUMNS:
        value = row.get(col)
        normalized[col] = (value or "").strip() if value is not None else ""
    return normalized


def load_leads(path: Path) -> list[LeadRecord]:
    ensure_crm_file(path)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return []
        fieldnames = list(reader.fieldnames)
        needs_migration = "proposal_path" not in fieldnames
        leads = [_lead_from_row(_normalize_row(row)) for row in reader]
    if needs_migration:
        save_leads(path, leads)
    return leads


def save_leads(path: Path, leads: list[LeadRecord]) -> None:
    ensure_crm_file(path)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CRM_CSV_COLUMNS))
        writer.writeheader()
        for lead in leads:
            writer.writerow(_lead_to_row(lead))


def generate_next_lead_id(path: Path) -> str:
    leads = load_leads(path)
    max_num = 0
    for lead in leads:
        match = _LEAD_ID_RE.match(lead.lead_id.strip())
        if match:
            max_num = max(max_num, int(match.group(1)))
    return f"lead_{max_num + 1:04d}"


def _emails_match(a: str | None, b: str | None) -> bool:
    left = (a or "").strip().lower()
    right = (b or "").strip().lower()
    if not left or not right:
        return True
    return left == right


def find_duplicate(
    path: Path,
    url: str,
    client_email: str | None,
) -> LeadRecord | None:
    domain = normalize_domain(url)
    email = _empty_to_none(client_email)
    for lead in load_leads(path):
        if lead.normalized_domain != domain:
            continue
        if _emails_match(lead.client_email, email):
            return lead
    return None


def add_lead(path: Path, lead: LeadRecord) -> LeadRecord:
    duplicate = find_duplicate(path, lead.url, lead.client_email)
    if duplicate is not None:
        raise ValueError(
            f"Duplicate lead: {duplicate.lead_id} ({duplicate.normalized_domain})"
        )
    leads = load_leads(path)
    if not lead.lead_id:
        lead.lead_id = generate_next_lead_id(path)
    if not lead.created_at:
        lead.created_at = utc_now_iso()
    if not lead.normalized_domain:
        lead.normalized_domain = normalize_domain(lead.url)
    leads.append(lead)
    save_leads(path, leads)
    return lead


def find_lead_by_id(path: Path, lead_id: str) -> LeadRecord | None:
    needle = lead_id.strip().lower()
    for lead in load_leads(path):
        if lead.lead_id.lower() == needle:
            return lead
    return None


def _parse_date(value: str | None) -> date | None:
    text = _empty_to_none(value)
    if text is None:
        return None
    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def update_lead_status(path: Path, lead_id: str, status: str) -> LeadRecord:
    normalized_status = status.strip().lower()
    if normalized_status not in VALID_LEAD_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    leads = load_leads(path)
    updated: LeadRecord | None = None
    now = utc_now_iso()

    for index, lead in enumerate(leads):
        if lead.lead_id != lead_id:
            continue
        lead.status = normalized_status  # type: ignore[assignment]
        if normalized_status == "contacted":
            lead.last_contacted_at = now
            followup = datetime.now(timezone.utc) + timedelta(days=FOLLOWUP_DAYS_AFTER_CONTACT)
            lead.next_followup_at = followup.replace(microsecond=0).isoformat()
        elif normalized_status in (
            "replied",
            "interested",
            "converted",
            "lost",
            "not_interested",
        ):
            lead.next_followup_at = None
        updated = lead
        leads[index] = lead
        break

    if updated is None:
        raise ValueError(f"Lead not found: {lead_id}")

    save_leads(path, leads)
    return updated


def attach_sample_to_lead(
    path: Path,
    lead_id: str,
    *,
    sample_report_path: str,
    health_score: int | None,
    health_label: str | None,
) -> LeadRecord:
    leads = load_leads(path)
    updated: LeadRecord | None = None

    for index, lead in enumerate(leads):
        if lead.lead_id != lead_id:
            continue
        lead.sample_report_path = sample_report_path
        lead.health_score = health_score
        lead.health_label = health_label
        if lead.status == "new":
            lead.status = "sample_created"
        updated = lead
        leads[index] = lead
        break

    if updated is None:
        raise ValueError(f"Lead not found: {lead_id}")

    save_leads(path, leads)
    return updated


def attach_proposal_to_lead(
    path: Path,
    lead_id: str,
    *,
    proposal_path: str,
) -> LeadRecord:
    leads = load_leads(path)
    updated: LeadRecord | None = None

    for index, lead in enumerate(leads):
        if lead.lead_id != lead_id:
            continue
        lead.proposal_path = proposal_path
        updated = lead
        leads[index] = lead
        break

    if updated is None:
        raise ValueError(f"Lead not found: {lead_id}")

    save_leads(path, leads)
    return updated


def get_followups_due(path: Path, today: date) -> list[LeadRecord]:
    due: list[LeadRecord] = []
    for lead in load_leads(path):
        followup = _parse_date(lead.next_followup_at)
        if followup is not None and followup <= today:
            due.append(lead)
    due.sort(key=lambda item: item.next_followup_at or "")
    return due


def convert_lead_in_crm(
    path: Path,
    lead_id: str,
    *,
    plan_id: str,
    currency: str,
    price_monthly: int | float,
    setup_fee: int | float,
    client_package_path: str,
    converted_at: str | None = None,
) -> LeadRecord:
    """Mark lead as converted and append conversion notes."""
    now = converted_at or utc_now_iso()
    note_line = (
        f"Converted at {now}; plan={plan_id}; "
        f"price={currency} {price_monthly}/month; setup={setup_fee}; "
        f"client_package={client_package_path}"
    )

    leads = load_leads(path)
    updated: LeadRecord | None = None

    for index, lead in enumerate(leads):
        if lead.lead_id != lead_id:
            continue
        lead.status = "converted"
        lead.next_followup_at = None
        if lead.notes.strip():
            lead.notes = f"{lead.notes.strip()}\n{note_line}"
        else:
            lead.notes = note_line
        updated = lead
        leads[index] = lead
        break

    if updated is None:
        raise ValueError(f"Lead not found: {lead_id}")

    save_leads(path, leads)
    return updated


def register_onboarded_lead(
    path: Path,
    *,
    client_name: str,
    client_email: str | None,
    url: str,
    sample_report_path: str,
    health_score: int | None,
    health_label: str | None,
    source: str = "onboard",
    notes: str = "",
) -> str:
    """Returns lead_id or 'duplicate'."""
    try:
        normalized_url = normalize_url(url)
    except ValueError as exc:
        raise ValueError(f"Invalid url: {exc}") from exc

    duplicate = find_duplicate(path, normalized_url, client_email)
    if duplicate is not None:
        return "duplicate"

    lead = LeadRecord(
        lead_id=generate_next_lead_id(path),
        client_name=client_name.strip(),
        client_email=_empty_to_none(client_email),
        url=normalized_url,
        normalized_domain=normalize_domain(normalized_url),
        source=source,
        status="sample_created",
        created_at=utc_now_iso(),
        sample_report_path=sample_report_path,
        health_score=health_score,
        health_label=health_label,
        notes=notes,
    )
    add_lead(path, lead)
    return lead.lead_id
