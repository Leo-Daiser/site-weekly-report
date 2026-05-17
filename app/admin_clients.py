from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.batch import _empty_to_none, _optional_float, _optional_int
from app.billing_store import load_subscriptions
from app.branding import BrandingConfig
from app.client_status_store import load_client_statuses
from app.leads import build_lead_slug
from app.models import ReportRunResult
from app.pipeline import SingleReportError, run_single_report
from app.utils import normalize_domain, normalize_url, report_base_filename


@dataclass
class AdminClientRow:
    client_name: str
    client_email: str
    brand_name: str
    url: str
    brand_color: str
    brand_logo: str
    footer_text: str
    report_format: str
    max_links: int
    timeout: float
    payment_status: str = "unknown"
    plan_id: str = ""
    operational_status: str = "active"
    latest_report_path: str = ""
    latest_summary: str = "—"
    client_package_path: str = ""


def _client_key(email: str, url: str) -> tuple[str, str]:
    return (email.strip().lower(), url.strip().rstrip("/").lower())


def load_clients_for_admin(clients_csv: Path) -> list[AdminClientRow]:
    if not clients_csv.is_file():
        return []
    rows: list[AdminClientRow] = []
    with clients_csv.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(
                AdminClientRow(
                    client_name=row.get("client_name", ""),
                    client_email=row.get("client_email", ""),
                    brand_name=row.get("brand_name", "") or row.get("client_name", ""),
                    url=row.get("url", ""),
                    brand_color=row.get("brand_color", "#2563eb") or "#2563eb",
                    brand_logo=row.get("brand_logo", ""),
                    footer_text=row.get("footer_text", ""),
                    report_format=row.get("format", "html") or "html",
                    max_links=_optional_int(row.get("max_links")) or 30,
                    timeout=_optional_float(row.get("timeout")) or 10.0,
                )
            )
    return rows


def latest_report_for_url(reports_dir: Path, url: str) -> Path | None:
    try:
        normalized_url = normalize_url(url)
    except ValueError:
        normalized_url = url
    domain = normalize_domain(normalized_url)
    prefix = domain.replace(".", "_").replace(":", "_")
    candidates = [path for path in reports_dir.rglob(f"{prefix}_*.html") if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name))


def latest_summary_for_url(reports_dir: Path, url: str) -> str:
    domain = normalize_domain(url)
    summaries = sorted(reports_dir.rglob("summary.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
    for summary in summaries:
        with summary.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if row.get("normalized_domain") == domain or normalize_domain(row.get("url", "")) == domain:
                    if row.get("success") != "true":
                        return row.get("error") or "Report failed"
                    score = row.get("health_score") or "—"
                    warnings = row.get("warnings_count") or "0"
                    broken = row.get("broken_links_count") or "0"
                    error = row.get("error") or ""
                    parts = [f"score={score}", f"warnings={warnings}", f"broken={broken}"]
                    if error:
                        parts.append(f"error={error}")
                    return ", ".join(parts)
    return "—"


def client_package_for(client_packages_dir: Path, client_name: str, url: str) -> Path | None:
    slug = build_lead_slug(client_name, normalize_domain(url))
    path = client_packages_dir / slug
    return path if path.is_dir() else None


def latest_run_for_client(run_logs_dir: Path, client_email: str, url: str) -> dict[str, object] | None:
    target_email = client_email.strip().lower()
    target_url = url.strip().rstrip("/").lower()
    candidates = sorted(run_logs_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        email = str(payload.get("client_email") or "").strip().lower()
        payload_url = str(payload.get("url") or "").strip().rstrip("/").lower()
        if email == target_email and payload_url == target_url:
            payload["_file"] = path.name
            return payload
    return None


def build_admin_client_rows(
    *,
    clients_csv: Path,
    subscriptions_path: Path,
    client_status_path: Path,
    reports_dir: Path,
    client_packages_dir: Path,
    project_root: Path,
) -> list[AdminClientRow]:
    rows = load_clients_for_admin(clients_csv)
    subscriptions = {
        item.customer_email.lower(): item for item in load_subscriptions(subscriptions_path)
    }
    statuses = {
        _client_key(item.client_email, item.url): item
        for item in load_client_statuses(client_status_path)
    }
    for row in rows:
        subscription = subscriptions.get(row.client_email.lower())
        if subscription:
            row.payment_status = subscription.payment_status
            row.plan_id = subscription.plan_id
        status = statuses.get(_client_key(row.client_email, row.url))
        if status:
            row.operational_status = status.status
        latest_report = latest_report_for_url(reports_dir, row.url)
        if latest_report:
            row.latest_report_path = _rel(latest_report, project_root)
        row.latest_summary = latest_summary_for_url(reports_dir, row.url)
        package = client_package_for(client_packages_dir, row.client_name, row.url)
        if package:
            row.client_package_path = _rel(package, project_root)
    return rows


def find_admin_client(clients_csv: Path, client_email: str, url: str) -> AdminClientRow:
    target = _client_key(client_email, url)
    for row in load_clients_for_admin(clients_csv):
        if _client_key(row.client_email, row.url) == target:
            return row
    raise ValueError(f"Client not found: {client_email} {url}")


def run_admin_single_client_report(
    *,
    clients_csv: Path,
    client_email: str,
    url: str,
    output_root: Path,
    db_path: Path,
    project_root: Path,
    run_logs_dir: Path,
) -> ReportRunResult:
    client = find_admin_client(clients_csv, client_email, url)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = output_root / f"admin_run_{stamp}"
    branding = BrandingConfig(
        brand_name=client.brand_name or client.client_name,
        client_name=client.client_name,
        brand_color=client.brand_color,
        logo_path=client.brand_logo or None,
        footer_text=client.footer_text or f"Prepared by {client.brand_name or client.client_name}",
    )
    try:
        result = run_single_report(
            url=client.url,
            max_links=client.max_links,
            timeout=client.timeout,
            output_dir=output_dir,
            db_path=db_path,
            branding=branding,
            output_format=client.report_format,
            project_root=project_root,
            max_pages=10,
            screenshot=False,
        )
    except SingleReportError as exc:
        result = exc.result or ReportRunResult(url=client.url, success=False, error=str(exc))

    log = {
        "run_type": "admin_single_site",
        "client_email": client.client_email,
        "url": client.url,
        "success": result.success,
        "scan_ok": result.scan_ok,
        "error": result.error,
        "html_path": result.html_path,
        "pdf_path": result.pdf_path,
        "health_score": result.health_score,
        "warnings_count": result.warnings_count,
        "broken_links_count": result.broken_links_count,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    run_logs_dir.mkdir(parents=True, exist_ok=True)
    (run_logs_dir / f"admin_run_{stamp}.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
