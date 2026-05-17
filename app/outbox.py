from __future__ import annotations

import csv
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models import EmailManifestEntry, OutboxResult

MANIFEST_COLUMNS = (
    "client_name",
    "client_email",
    "brand_name",
    "url",
    "subject",
    "text_path",
    "html_path",
    "report_html_path",
    "report_pdf_path",
    "status",
    "error",
)


def _empty(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text if text else None


def _parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def _parse_int(value: str | None) -> int | None:
    text = _empty(value)
    if text is None:
        return None
    return int(float(text))


def build_client_email_lookup(clients_csv: Path | None) -> dict[tuple[str, str], str]:
    if clients_csv is None or not clients_csv.is_file():
        return {}

    lookup: dict[tuple[str, str], str] = {}
    with clients_csv.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            client_name = _empty(row.get("client_name")) or ""
            url = _empty(row.get("url")) or ""
            email = _empty(row.get("client_email"))
            if email:
                lookup[(client_name.lower(), url.lower())] = email
                lookup[("", url.lower())] = email
    return lookup


def _resolve_report_path(batch_dir: Path, relative: str | None) -> Path | None:
    if not relative or relative == "-":
        return None
    path = batch_dir / relative
    return path if path.is_file() else None


def _email_slug(normalized_domain: str, client_name: str, index: int) -> str:
    base = normalized_domain or "unknown"
    safe = base.replace(".", "_").replace(":", "_")
    if not safe:
        safe = f"client_{index}"
    return safe


def render_email_bodies(
    template_dir: Path,
    context: dict[str, object],
) -> tuple[str, str]:
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    text = env.get_template("email_report.txt.j2").render(**context)
    html = env.get_template("email_report.html.j2").render(**context)
    return text, html


def read_manifest(manifest_path: Path) -> list[EmailManifestEntry]:
    if not manifest_path.is_file():
        return []
    entries: list[EmailManifestEntry] = []
    with manifest_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            entries.append(EmailManifestEntry.model_validate(row))
    return entries


def write_manifest(manifest_path: Path, entries: list[EmailManifestEntry]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry.model_dump())


def create_outbox_for_batch(
    batch_dir: Path,
    clients_csv: Path | None = None,
    outbox_dir: Path = Path("outbox"),
    project_root: Path | None = None,
) -> OutboxResult:
    batch_dir = batch_dir.resolve()
    summary_path = batch_dir / "summary.csv"
    if not summary_path.is_file():
        raise FileNotFoundError(f"summary.csv not found in {batch_dir}")

    root = project_root or Path(__file__).resolve().parent.parent
    template_dir = root / "templates"
    target_outbox = (outbox_dir / batch_dir.name).resolve()
    emails_dir = target_outbox / "emails"
    emails_dir.mkdir(parents=True, exist_ok=True)

    email_lookup = build_client_email_lookup(clients_csv)
    warnings: list[str] = []
    entries: list[EmailManifestEntry] = []
    prepared = 0
    skipped = 0

    with summary_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            client_name = row.get("client_name", "")
            url = row.get("url", "")
            brand_name = row.get("brand_name", "") or "WebReport Weekly"
            normalized = row.get("normalized_domain", "") or f"row_{index}"
            success = _parse_bool(row.get("success"))

            lookup_key = (client_name.lower(), url.lower())
            client_email = email_lookup.get(lookup_key) or email_lookup.get(("", url.lower()), "")

            report_html = _resolve_report_path(batch_dir, _empty(row.get("html_path")))
            report_pdf = _resolve_report_path(batch_dir, _empty(row.get("pdf_path")))

            if not success:
                entries.append(
                    EmailManifestEntry(
                        client_name=client_name,
                        client_email=client_email,
                        brand_name=brand_name,
                        url=url,
                        status="skipped",
                        error=row.get("error") or "Report was not generated",
                    )
                )
                skipped += 1
                continue

            if not report_html and not report_pdf:
                entries.append(
                    EmailManifestEntry(
                        client_name=client_name,
                        client_email=client_email,
                        brand_name=brand_name,
                        url=url,
                        status="skipped",
                        error="No report files found",
                    )
                )
                skipped += 1
                continue

            if not client_email:
                msg = f"No client_email for {client_name} ({url})"
                warnings.append(msg)
                entries.append(
                    EmailManifestEntry(
                        client_name=client_name,
                        brand_name=brand_name,
                        url=url,
                        status="skipped",
                        error="client_email is missing",
                    )
                )
                skipped += 1
                continue

            status_code = _parse_int(row.get("status_code"))
            health_score_raw = _empty(row.get("health_score"))
            health_score_val = _parse_int(health_score_raw)
            top_actions_raw = _empty(row.get("top_actions")) or ""
            top_actions_list = [
                part.strip() for part in top_actions_raw.split("|") if part.strip()
            ]
            context: dict[str, object] = {
                "url": url,
                "status_code": status_code if status_code is not None else "—",
                "warnings_count": _parse_int(row.get("warnings_count")) or 0,
                "broken_links_count": _parse_int(row.get("broken_links_count")) or 0,
                "changes_count": _parse_int(row.get("changes_count")) or 0,
                "brand_name": brand_name,
                "client_name": client_name,
                "health_score": health_score_val,
                "health_label": _empty(row.get("health_label")) or "",
                "top_actions": top_actions_list,
            }
            text_body, html_body = render_email_bodies(template_dir, context)

            slug = _email_slug(normalized, client_name, index)
            text_rel = f"emails/{slug}.txt"
            html_rel = f"emails/{slug}.html"
            (target_outbox / text_rel).write_text(text_body, encoding="utf-8")
            (target_outbox / html_rel).write_text(html_body, encoding="utf-8")

            subject = f"Еженедельный отчёт по сайту — {url}"
            entries.append(
                EmailManifestEntry(
                    client_name=client_name,
                    client_email=client_email,
                    brand_name=brand_name,
                    url=url,
                    subject=subject,
                    text_path=text_rel,
                    html_path=html_rel,
                    report_html_path=row.get("html_path", "") or "",
                    report_pdf_path=row.get("pdf_path", "") or "",
                    status="prepared",
                )
            )
            prepared += 1

    manifest_path = target_outbox / "manifest.csv"
    write_manifest(manifest_path, entries)

    return OutboxResult(
        outbox_dir=target_outbox,
        manifest_path=manifest_path,
        prepared_count=prepared,
        skipped_count=skipped,
        warnings=warnings,
    )


def pick_attachments(batch_dir: Path, entry: EmailManifestEntry) -> list[Path]:
    pdf_path = _resolve_report_path(batch_dir, _empty(entry.report_pdf_path))
    html_path = _resolve_report_path(batch_dir, _empty(entry.report_html_path))
    if pdf_path:
        return [pdf_path]
    if html_path:
        return [html_path]
    return []
