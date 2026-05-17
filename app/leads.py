from __future__ import annotations

import csv
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.crm_store import register_onboarded_lead
from app.models import BrandingConfig, LeadClientRecord, OnboardResult, ReportRunResult
from app.outbox import render_email_bodies
from app.pipeline import SingleReportError, run_single_report
from app.utils import normalize_domain, normalize_url

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")

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

DEFAULT_OUTREACH_MESSAGE = (
    "Привет. Я подготовил короткий sample-report по сайту {{ url }}: проверил доступность, "
    "базовое SEO, формы, битые ссылки и изменения. Если полезно, могу делать такой отчёт "
    "еженедельно в white-label формате."
)


def validate_client_email(
    email: str | None,
    warnings: list[str],
) -> str | None:
    if email is None:
        return None
    text = email.strip()
    if not text:
        return None
    if not _EMAIL_RE.match(text):
        warnings.append(f"Невалидный client_email «{text}», email не будет сохранён")
        return None
    return text


def build_lead_slug(client_name: str, normalized_domain: str) -> str:
    name_part = _SLUG_RE.sub("-", client_name.lower().strip())
    name_part = name_part.strip("-") or "client"
    domain_part = normalized_domain.replace(".", "-").lower()
    domain_part = _SLUG_RE.sub("-", domain_part).strip("-") or "site"
    return f"{name_part}-{domain_part}"


def create_lead_folder(leads_dir: Path, slug: str) -> tuple[Path, bool]:
    """Создаёт папку лида. Возвращает (path, existed_before)."""
    lead_dir = leads_dir / slug
    existed = lead_dir.is_dir()
    lead_dir.mkdir(parents=True, exist_ok=True)
    return lead_dir, existed


def write_client_json(lead_dir: Path, record: LeadClientRecord) -> Path:
    path = lead_dir / "client.json"
    path.write_text(
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def copy_sample_reports(
    report_result: ReportRunResult,
    lead_dir: Path,
) -> tuple[Path | None, Path | None]:
    html_dest: Path | None = None
    pdf_dest: Path | None = None

    if report_result.html_path:
        src = Path(report_result.html_path)
        if src.is_file():
            html_dest = lead_dir / "sample_report.html"
            shutil.copy2(src, html_dest)

    if report_result.pdf_path:
        src = Path(report_result.pdf_path)
        if src.is_file():
            pdf_dest = lead_dir / "sample_report.pdf"
            shutil.copy2(src, pdf_dest)

    return html_dest, pdf_dest


def render_email_previews(
    template_dir: Path,
    lead_dir: Path,
    *,
    url: str,
    client_name: str,
    brand_name: str,
    report_result: ReportRunResult,
) -> tuple[Path, Path]:
    top_actions_list = [
        part.strip() for part in (report_result.top_actions or "").split("|") if part.strip()
    ]
    context: dict[str, object] = {
        "url": url,
        "status_code": report_result.status_code if report_result.status_code is not None else "—",
        "warnings_count": report_result.warnings_count,
        "broken_links_count": report_result.broken_links_count,
        "changes_count": report_result.changes_count,
        "brand_name": brand_name,
        "client_name": client_name,
        "health_score": report_result.health_score,
        "health_label": report_result.health_label or "",
        "top_actions": top_actions_list,
    }
    text_body, html_body = render_email_bodies(template_dir, context)
    txt_path = lead_dir / "email_preview.txt"
    html_path = lead_dir / "email_preview.html"
    txt_path.write_text(text_body, encoding="utf-8")
    html_path.write_text(html_body, encoding="utf-8")
    return txt_path, html_path


def render_lead_notes(
    template_dir: Path,
    lead_dir: Path,
    *,
    client_name: str,
    client_email: str | None,
    url: str,
    generated_at: str,
    report_result: ReportRunResult,
    outreach_message: str,
) -> Path:
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("lead_notes.md.j2")
    top_actions_list = [
        part.strip() for part in (report_result.top_actions or "").split("|") if part.strip()
    ]
    content = template.render(
        client_name=client_name,
        client_email=client_email or "—",
        url=url,
        generated_at=generated_at,
        status_code=report_result.status_code if report_result.status_code is not None else "—",
        warnings_count=report_result.warnings_count,
        broken_links_count=report_result.broken_links_count,
        changes_count=report_result.changes_count,
        previous_check_found="yes" if report_result.previous_check_found else "no",
        outreach_message=outreach_message,
        health_score=report_result.health_score,
        health_label=report_result.health_label or "—",
        top_actions=top_actions_list,
    )
    path = lead_dir / "notes.md"
    path.write_text(content, encoding="utf-8")
    return path


def _normalize_url_key(url: str) -> str:
    return normalize_url(url).rstrip("/").lower()


def append_to_clients_csv_if_needed(
    clients_csv: Path,
    *,
    client_name: str,
    client_email: str | None,
    brand_name: str,
    url: str,
    brand_color: str,
    brand_logo: str | None,
    footer_text: str | None,
    report_format: str,
    max_links: int,
    timeout: float,
) -> str:
    """Возвращает 'added' или 'already exists'."""
    url_key = _normalize_url_key(url)
    clients_csv.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    if clients_csv.is_file():
        with clients_csv.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                row_url = (row.get("url") or "").strip()
                if row_url and _normalize_url_key(row_url) == url_key:
                    return "already exists"
                rows.append({col: row.get(col, "") for col in CLIENTS_CSV_COLUMNS})

    new_row = {
        "client_name": client_name,
        "client_email": client_email or "",
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


def run_onboard(
    *,
    client_name: str,
    client_email: str | None,
    url: str,
    branding: BrandingConfig,
    output_format: str,
    max_links: int,
    timeout: float,
    output_dir: Path,
    db_path: Path,
    leads_dir: Path,
    project_root: Path,
    template_dir: Path,
    add_to_clients_csv: bool = False,
    clients_csv: Path | None = None,
    add_to_crm: bool = False,
    crm_csv: Path | None = None,
    brand_logo_cli: str | None = None,
    footer_text_cli: str | None = None,
    branding_warnings: list[str] | None = None,
) -> OnboardResult:
    warnings: list[str] = list(branding_warnings or [])

    name = client_name.strip()
    if not name:
        raise ValueError("client_name не может быть пустым")

    try:
        source_url = normalize_url(url)
    except ValueError as exc:
        raise ValueError(f"Некорректный url: {exc}") from exc

    email = validate_client_email(client_email, warnings)
    if client_email and client_email.strip() and email is None:
        pass
    elif not client_email or not client_email.strip():
        warnings.append("client_email не указан — email preview будет без адресата")

    normalized = normalize_domain(source_url)
    slug = build_lead_slug(name, normalized)
    lead_dir, lead_existed = create_lead_folder(leads_dir, slug)

    try:
        report_result = run_single_report(
            url=source_url,
            max_links=max_links,
            timeout=timeout,
            output_dir=output_dir,
            db_path=db_path,
            branding=branding,
            output_format=output_format.lower(),
            project_root=project_root,
        )
    except SingleReportError as exc:
        if not lead_existed:
            shutil.rmtree(lead_dir, ignore_errors=True)
        raise

    warnings.extend(report_result.branding_warnings)

    if not report_result.success:
        if not lead_existed:
            shutil.rmtree(lead_dir, ignore_errors=True)
        raise RuntimeError(report_result.error or "Не удалось сгенерировать отчёт")

    html_copy, pdf_copy = copy_sample_reports(report_result, lead_dir)
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    top_actions_list = [
        part.strip() for part in (report_result.top_actions or "").split("|") if part.strip()
    ]

    record = LeadClientRecord(
        client_name=name,
        client_email=email,
        url=source_url,
        normalized_domain=normalized,
        brand_name=branding.brand_name,
        brand_color=branding.brand_color,
        format=output_format.lower(),
        created_at=created_at,
        report_html_path="sample_report.html" if html_copy else "",
        report_pdf_path="sample_report.pdf" if pdf_copy else None,
        warnings_count=report_result.warnings_count,
        broken_links_count=report_result.broken_links_count,
        changes_count=report_result.changes_count,
        previous_check_found=report_result.previous_check_found,
        status_code=report_result.status_code,
        health_score=report_result.health_score,
        health_label=report_result.health_label,
        critical_issues=report_result.critical_issues,
        high_issues=report_result.high_issues,
        medium_issues=report_result.medium_issues,
        low_issues=report_result.low_issues,
        top_actions=top_actions_list,
    )
    client_json_path = write_client_json(lead_dir, record)

    email_txt, email_html = render_email_previews(
        template_dir,
        lead_dir,
        url=source_url,
        client_name=name,
        brand_name=branding.brand_name,
        report_result=report_result,
    )

    outreach_message = DEFAULT_OUTREACH_MESSAGE.replace("{{ url }}", source_url)
    notes_path = render_lead_notes(
        template_dir,
        lead_dir,
        client_name=name,
        client_email=email,
        url=source_url,
        generated_at=created_at,
        report_result=report_result,
        outreach_message=outreach_message,
    )

    csv_status: str | None = None
    if add_to_clients_csv and clients_csv is not None:
        csv_status = append_to_clients_csv_if_needed(
            clients_csv,
            client_name=name,
            client_email=email,
            brand_name=branding.brand_name,
            url=source_url,
            brand_color=branding.brand_color,
            brand_logo=branding.logo_path or brand_logo_cli,
            footer_text=branding.footer_text or footer_text_cli,
            report_format=output_format.lower(),
            max_links=max_links,
            timeout=timeout,
        )

    crm_status: str | None = None
    if add_to_crm and crm_csv is not None:
        sample_rel = ""
        if html_copy is not None:
            try:
                sample_rel = html_copy.relative_to(project_root).as_posix()
            except ValueError:
                sample_rel = html_copy.as_posix()
        crm_status = register_onboarded_lead(
            crm_csv,
            client_name=name,
            client_email=email,
            url=source_url,
            sample_report_path=sample_rel,
            health_score=report_result.health_score,
            health_label=report_result.health_label,
            source="onboard",
        )

    return OnboardResult(
        lead_dir=lead_dir,
        client_json_path=client_json_path,
        sample_report_html=html_copy,
        sample_report_pdf=pdf_copy,
        email_preview_txt=email_txt,
        email_preview_html=email_html,
        notes_path=notes_path,
        report_result=report_result,
        warnings=warnings,
        clients_csv_status=csv_status,
        crm_status=crm_status,
    )
