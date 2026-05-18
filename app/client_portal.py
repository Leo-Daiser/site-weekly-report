from __future__ import annotations

import csv
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import typer
from rich.console import Console
from rich.table import Table

from app.admin_clients import AdminClientRow, build_admin_client_rows
from app.billing_store import load_subscriptions
from app.utils import resolve_project_path

console = Console()
cli = typer.Typer(help="Client portal magic-link and settings request tools.")

SESSION_COLUMNS = ("token_hash", "email", "expires_at", "used_at", "created_at", "kind")
REQUEST_COLUMNS = (
    "request_id",
    "client_email",
    "url",
    "brand_name",
    "brand_color",
    "logo_url",
    "report_recipient_email",
    "notes",
    "status",
    "created_at",
    "resolved_at",
    "admin_notes",
)


@dataclass
class ClientPortalToken:
    token_hash: str
    email: str
    expires_at: str
    used_at: str = ""
    created_at: str = ""
    kind: str = "magic"


@dataclass
class ClientSettingsRequest:
    request_id: str
    client_email: str
    url: str = ""
    brand_name: str = ""
    brand_color: str = ""
    logo_url: str = ""
    report_recipient_email: str = ""
    notes: str = ""
    status: str = "pending"
    created_at: str = ""
    resolved_at: str = ""
    admin_notes: str = ""


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_raw_token() -> str:
    return secrets.token_urlsafe(32)


def load_tokens(path: Path) -> list[ClientPortalToken]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            ClientPortalToken(
                token_hash=row.get("token_hash", ""),
                email=row.get("email", ""),
                expires_at=row.get("expires_at", ""),
                used_at=row.get("used_at", ""),
                created_at=row.get("created_at", ""),
                kind=row.get("kind") or "magic",
            )
            for row in reader
        ]


def save_tokens(path: Path, tokens: list[ClientPortalToken]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SESSION_COLUMNS)
        writer.writeheader()
        for token in tokens:
            writer.writerow(token.__dict__)


def create_magic_link(
    *,
    sessions_path: Path,
    email: str,
    base_url: str,
    ttl_minutes: int = 30,
) -> tuple[str, ClientPortalToken]:
    raw_token = new_raw_token()
    record = ClientPortalToken(
        token_hash=hash_token(raw_token),
        email=email.strip().lower(),
        expires_at=(utc_now() + timedelta(minutes=ttl_minutes)).isoformat(),
        created_at=utc_now_iso(),
        kind="magic",
    )
    tokens = load_tokens(sessions_path)
    tokens.append(record)
    save_tokens(sessions_path, tokens)
    base = base_url.rstrip("/") or "http://localhost:8000"
    return f"{base}/client/magic?{urlencode({'token': raw_token})}", record


def consume_magic_token(
    *,
    sessions_path: Path,
    raw_token: str,
    session_days: int = 7,
) -> tuple[str, str]:
    token_hash = hash_token(raw_token)
    tokens = load_tokens(sessions_path)
    for record in tokens:
        if record.kind != "magic" or record.token_hash != token_hash:
            continue
        if record.used_at:
            raise ValueError("Magic link already used")
        if parse_iso(record.expires_at) < utc_now():
            raise ValueError("Magic link expired")
        record.used_at = utc_now_iso()
        session_raw = new_raw_token()
        session = ClientPortalToken(
            token_hash=hash_token(session_raw),
            email=record.email,
            expires_at=(utc_now() + timedelta(days=session_days)).isoformat(),
            created_at=utc_now_iso(),
            kind="session",
        )
        tokens.append(session)
        save_tokens(sessions_path, tokens)
        return record.email, session_raw
    raise ValueError("Magic link not found")


def email_for_session(sessions_path: Path, raw_session: str | None) -> str | None:
    if not raw_session:
        return None
    token_hash = hash_token(raw_session)
    for record in load_tokens(sessions_path):
        if record.kind != "session" or record.token_hash != token_hash:
            continue
        if parse_iso(record.expires_at) < utc_now():
            return None
        return record.email
    return None


def revoke_session(sessions_path: Path, raw_session: str | None) -> None:
    if not raw_session:
        return
    token_hash = hash_token(raw_session)
    tokens = load_tokens(sessions_path)
    for record in tokens:
        if record.kind == "session" and record.token_hash == token_hash:
            record.used_at = utc_now_iso()
            record.expires_at = utc_now_iso()
    save_tokens(sessions_path, tokens)


def clients_for_email(
    *,
    email: str,
    clients_csv: Path,
    subscriptions_path: Path,
    client_status_path: Path,
    reports_dir: Path,
    client_packages_dir: Path,
    project_root: Path,
) -> list[AdminClientRow]:
    target = email.strip().lower()
    rows = build_admin_client_rows(
        clients_csv=clients_csv,
        subscriptions_path=subscriptions_path,
        client_status_path=client_status_path,
        reports_dir=reports_dir,
        client_packages_dir=client_packages_dir,
        project_root=project_root,
    )
    return [row for row in rows if row.client_email.strip().lower() == target]


def subscription_for_email(subscriptions_path: Path, email: str):
    target = email.strip().lower()
    return next((item for item in load_subscriptions(subscriptions_path) if item.customer_email.lower() == target), None)


def next_request_id(existing: list[ClientSettingsRequest]) -> str:
    max_num = 0
    for request in existing:
        if request.request_id.startswith("client_req_"):
            try:
                max_num = max(max_num, int(request.request_id.split("_")[-1]))
            except ValueError:
                continue
    return f"client_req_{max_num + 1:04d}"


def load_settings_requests(path: Path) -> list[ClientSettingsRequest]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            ClientSettingsRequest(
                request_id=row.get("request_id", ""),
                client_email=row.get("client_email", ""),
                url=row.get("url", ""),
                brand_name=row.get("brand_name", ""),
                brand_color=row.get("brand_color", ""),
                logo_url=row.get("logo_url", ""),
                report_recipient_email=row.get("report_recipient_email", ""),
                notes=row.get("notes", ""),
                status=row.get("status") or "pending",
                created_at=row.get("created_at", ""),
                resolved_at=row.get("resolved_at", ""),
                admin_notes=row.get("admin_notes", ""),
            )
            for row in reader
        ]


def save_settings_requests(path: Path, requests: list[ClientSettingsRequest]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUEST_COLUMNS)
        writer.writeheader()
        for request in requests:
            writer.writerow(request.__dict__)


def create_settings_request(path: Path, request: ClientSettingsRequest) -> ClientSettingsRequest:
    requests = load_settings_requests(path)
    if not request.request_id:
        request.request_id = next_request_id(requests)
    if not request.created_at:
        request.created_at = utc_now_iso()
    requests.append(request)
    save_settings_requests(path, requests)
    return request


def set_settings_request_status(
    path: Path,
    request_id: str,
    status: str,
    *,
    admin_notes: str = "",
) -> ClientSettingsRequest:
    requests = load_settings_requests(path)
    for index, request in enumerate(requests):
        if request.request_id == request_id:
            request.status = status
            request.resolved_at = utc_now_iso()
            if admin_notes:
                request.admin_notes = admin_notes
            requests[index] = request
            save_settings_requests(path, requests)
            return request
    raise ValueError(f"Settings request not found: {request_id}")


def approve_settings_request(path: Path, request_id: str, clients_csv: Path) -> ClientSettingsRequest:
    request = set_settings_request_status(path, request_id, "approved", admin_notes="Approved from admin")
    if not clients_csv.is_file():
        return request
    with clients_csv.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for column in ("brand_name", "brand_color", "brand_logo", "client_email"):
        if column not in fieldnames:
            fieldnames.append(column)
    for row in rows:
        same_email = (row.get("client_email") or "").strip().lower() == request.client_email.strip().lower()
        same_url = not request.url or (row.get("url") or "").strip().rstrip("/").lower() == request.url.strip().rstrip("/").lower()
        if same_email and same_url:
            if request.brand_name:
                row["brand_name"] = request.brand_name
            if request.brand_color:
                row["brand_color"] = request.brand_color
            if request.logo_url:
                row["brand_logo"] = request.logo_url
            if request.report_recipient_email:
                row["client_email"] = request.report_recipient_email
    with clients_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return request


def requests_for_email(path: Path, email: str) -> list[ClientSettingsRequest]:
    target = email.strip().lower()
    return [item for item in load_settings_requests(path) if item.client_email.strip().lower() == target]


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


@cli.command("create-login-link")
def create_login_link_cmd(
    email: str = typer.Option(..., "--email"),
    sessions_path: str = typer.Option("data/client_portal_sessions.csv", "--sessions-path"),
    base_url: str = typer.Option("http://localhost:8000", "--base-url"),
    ttl_minutes: int = typer.Option(30, "--ttl-minutes"),
) -> None:
    root = _project_root()
    link, _record = create_magic_link(
        sessions_path=resolve_project_path(sessions_path, root),
        email=email,
        base_url=base_url,
        ttl_minutes=ttl_minutes,
    )
    console.print(link)


@cli.command("list-requests")
def list_requests_cmd(
    requests_path: str = typer.Option("data/client_settings_requests.csv", "--requests-path"),
) -> None:
    root = _project_root()
    table = Table("ID", "Email", "URL", "Status", "Created")
    for request in load_settings_requests(resolve_project_path(requests_path, root)):
        table.add_row(request.request_id, request.client_email, request.url, request.status, request.created_at)
    console.print(table)


@cli.command("approve-request")
def approve_request_cmd(
    request_id: str = typer.Option(..., "--request-id"),
    requests_path: str = typer.Option("data/client_settings_requests.csv", "--requests-path"),
    clients_csv: str = typer.Option("data/clients.csv", "--clients-csv"),
) -> None:
    root = _project_root()
    request = approve_settings_request(
        resolve_project_path(requests_path, root),
        request_id,
        resolve_project_path(clients_csv, root),
    )
    console.print(f"[green]Approved[/green] {request.request_id}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
