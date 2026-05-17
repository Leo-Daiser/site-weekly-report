from __future__ import annotations

import csv
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.leads import build_lead_slug
from app.models import ClientPackageConfig, ConvertClientResult, LeadRecord, PricingPlan
from app.utils import normalize_url

CLIENTS_CSV_COLUMNS = (
    "client_name",
    "client_email",
    "brand_name",
    "url",
    "brand_color",
    "brand_logo",
    "footer_text",
    "format",
    "max_links",
    "timeout",
)

DEFAULT_WEEKLY_JOB_TEMPLATE: dict[str, object] = {
    "job_name": "local_weekly_reports",
    "clients_csv": "data/clients.csv",
    "output_dir": "reports",
    "outbox_dir": "outbox",
    "db_path": "data/checks.sqlite",
    "branding_file": "branding/default.json",
    "format": "html",
    "max_links": 30,
    "timeout": 10,
    "create_outbox": True,
    "send_email": False,
    "continue_on_error": True,
    "limit": None,
}


def build_client_slug(client_name: str, normalized_domain: str) -> str:
    return build_lead_slug(client_name, normalized_domain)


def _normalize_url_key(url: str) -> str:
    return normalize_url(url).rstrip("/").lower()


def _client_identity_key(url: str, client_email: str | None) -> tuple[str, str]:
    return (_normalize_url_key(url), (client_email or "").strip().lower())


def append_client_to_clients_csv(
    clients_csv: Path,
    *,
    client_name: str,
    client_email: str,
    brand_name: str,
    url: str,
    brand_color: str,
    brand_logo: str | None = None,
    footer_text: str | None = None,
    report_format: str,
    max_links: int,
    timeout: float,
) -> str:
    """Returns 'added' or 'already exists'."""
    identity = _client_identity_key(url, client_email)
    clients_csv.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    if clients_csv.is_file():
        with clients_csv.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                row_url = (row.get("url") or "").strip()
                row_email = (row.get("client_email") or "").strip()
                if row_url and _client_identity_key(row_url, row_email) == identity:
                    return "already exists"
                rows.append({col: row.get(col, "") for col in CLIENTS_CSV_COLUMNS})

    new_row = {
        "client_name": client_name,
        "client_email": client_email,
        "brand_name": brand_name,
        "url": normalize_url(url),
        "brand_color": brand_color,
        "brand_logo": brand_logo or "",
        "footer_text": footer_text or "",
        "format": report_format,
        "max_links": str(max_links),
        "timeout": str(int(timeout) if timeout == int(timeout) else timeout),
    }
    rows.append(new_row)

    with clients_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CLIENTS_CSV_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in CLIENTS_CSV_COLUMNS})

    return "added"


def write_client_config(package_dir: Path, config: ClientPackageConfig) -> Path:
    path = package_dir / "client_config.json"
    path.write_text(
        json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _template_env(template_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def render_onboarding_checklist(
    template_dir: Path,
    package_dir: Path,
    *,
    context: dict[str, object],
) -> Path:
    env = _template_env(template_dir)
    content = env.get_template("client_onboarding_checklist.md.j2").render(**context)
    path = package_dir / "onboarding_checklist.md"
    path.write_text(content, encoding="utf-8")
    return path


def render_welcome_message(
    template_dir: Path,
    package_dir: Path,
    *,
    context: dict[str, object],
) -> Path:
    env = _template_env(template_dir)
    content = env.get_template("welcome_message.md.j2").render(**context)
    path = package_dir / "welcome_message.md"
    path.write_text(content, encoding="utf-8")
    return path


def create_client_package(
    *,
    lead: LeadRecord,
    plan: PricingPlan,
    currency: str,
    package_root: Path,
    template_dir: Path,
    clients_csv_rel: str,
    brand_name: str,
    brand_color: str,
    report_format: str,
    max_links: int,
    timeout: float,
    converted_at: str,
) -> tuple[Path, Path, Path, Path]:
    slug = build_client_slug(lead.client_name, lead.normalized_domain)
    package_dir = package_root / slug
    package_dir.mkdir(parents=True, exist_ok=True)

    config = ClientPackageConfig(
        lead_id=lead.lead_id,
        client_name=lead.client_name,
        client_email=lead.client_email or "",
        url=lead.url,
        normalized_domain=lead.normalized_domain,
        plan_id=plan.plan_id,
        plan_name=plan.name,
        price_monthly=plan.price_monthly,
        setup_fee=plan.setup_fee,
        currency=currency,
        brand_name=brand_name,
        brand_color=brand_color,
        format=report_format,
        max_links=max_links,
        timeout=timeout,
        converted_at=converted_at,
        clients_csv=clients_csv_rel,
    )

    template_context: dict[str, object] = {
        "client_name": lead.client_name,
        "url": lead.url,
        "plan_name": plan.name,
        "currency": currency,
        "price_monthly": plan.price_monthly,
        "setup_fee": plan.setup_fee,
        "brand_name": brand_name,
        "format": report_format,
    }

    config_path = write_client_config(package_dir, config)
    checklist_path = render_onboarding_checklist(
        template_dir, package_dir, context=template_context
    )
    welcome_path = render_welcome_message(template_dir, package_dir, context=template_context)
    return package_dir, config_path, checklist_path, welcome_path


def update_weekly_job_config(
    job_path: Path,
    *,
    clients_csv: str,
    report_format: str,
    example_job_path: Path | None = None,
) -> Path:
    if job_path.is_file():
        data = json.loads(job_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Invalid weekly job JSON: {job_path}")
    elif example_job_path is not None and example_job_path.is_file():
        data = json.loads(example_job_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Invalid weekly job example: {example_job_path}")
    else:
        data = dict(DEFAULT_WEEKLY_JOB_TEMPLATE)

    data["clients_csv"] = clients_csv
    data["format"] = report_format
    data["create_outbox"] = True
    data["send_email"] = False

    job_path.parent.mkdir(parents=True, exist_ok=True)
    job_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return job_path
