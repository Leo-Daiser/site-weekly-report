from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from app.models import ClientOperationalStatus, ClientStatusRecord

CLIENT_STATUS_COLUMNS = ["client_email", "url", "status", "reason", "updated_at"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _key(email: str, url: str) -> tuple[str, str]:
    return (email.strip().lower(), url.strip().rstrip("/").lower())


def load_client_statuses(path: Path) -> list[ClientStatusRecord]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            ClientStatusRecord(
                client_email=row.get("client_email", ""),
                url=row.get("url", ""),
                status=row.get("status", "active") or "active",
                reason=row.get("reason", ""),
                updated_at=row.get("updated_at", ""),
            )
            for row in reader
        ]


def save_client_statuses(path: Path, records: list[ClientStatusRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CLIENT_STATUS_COLUMNS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.model_dump())


def set_client_status(
    path: Path,
    *,
    client_email: str,
    url: str,
    status: ClientOperationalStatus,
    reason: str = "",
) -> ClientStatusRecord:
    records = load_client_statuses(path)
    target_key = _key(client_email, url)
    updated = ClientStatusRecord(
        client_email=client_email,
        url=url,
        status=status,
        reason=reason,
        updated_at=utc_now_iso(),
    )
    for index, record in enumerate(records):
        if _key(record.client_email, record.url) == target_key:
            records[index] = updated
            save_client_statuses(path, records)
            return updated
    records.append(updated)
    save_client_statuses(path, records)
    return updated


def active_client_keys(path: Path) -> set[tuple[str, str]]:
    return {
        _key(record.client_email, record.url)
        for record in load_client_statuses(path)
        if record.status == "active"
    }


def paused_client_keys(path: Path) -> set[tuple[str, str]]:
    return {
        _key(record.client_email, record.url)
        for record in load_client_statuses(path)
        if record.status in ("paused", "needs_review")
    }
