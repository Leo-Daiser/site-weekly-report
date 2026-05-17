from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.diff import build_report_diff
from app.link_checker import run_link_checks
from app.models import BrandingConfig, PageFetchResult, ReportRunResult, SiteReport
from app.pdf_exporter import PdfExportError, export_html_to_pdf
from app.report_builder import (
    build_recommendations,
    collect_all_warnings,
    render_report,
)
from app.scanner import check_robots_and_sitemap, fetch_page
from app.seo_checks import check_forms, run_seo_checks
from app.storage import get_latest_check, save_check
from app.utils import normalize_domain, normalize_url, report_output_filenames


class SingleReportError(Exception):
    """Ошибка одиночного прогона (например, PDF-only при сбое экспорта)."""

    def __init__(self, message: str, result: ReportRunResult | None = None) -> None:
        super().__init__(message)
        self.result = result


def compute_scan_ok(page: PageFetchResult) -> bool:
    if page.error:
        return False
    if page.status_code is None:
        return False
    if page.status_code >= 500:
        return False
    return True


def run_single_report(
    url: str,
    max_links: int,
    timeout: float,
    output_dir: Path,
    db_path: Path,
    branding: BrandingConfig,
    output_format: str,
    project_root: Path,
    run_timestamp: str | None = None,
) -> ReportRunResult:
    """Сканирует сайт, сохраняет историю и генерирует отчёт(ы)."""
    result = ReportRunResult(
        url=url,
        brand_name=branding.brand_name,
        client_name=branding.client_name,
    )

    try:
        source_url = normalize_url(url)
    except ValueError as exc:
        result.error = str(exc)
        return result

    result.url = source_url

    try:
        page = fetch_page(source_url, timeout)
        result.scan_ok = compute_scan_ok(page)
        result.status_code = page.status_code

        base_for_resources = page.final_url or source_url
        robots, sitemap = check_robots_and_sitemap(base_for_resources, timeout)

        seo = None
        forms: list = []
        links = None

        if page.html:
            seo = run_seo_checks(page.html)
            forms = check_forms(page.html)
            check_url = page.final_url or source_url
            links = run_link_checks(page.html, check_url, max_links, timeout)

        report = SiteReport(
            source_url=source_url,
            page=page,
            seo=seo,
            robots=robots,
            sitemap=sitemap,
            forms=forms,
            links=links,
        )
        report.all_warnings = collect_all_warnings(report)
        report.recommendations = build_recommendations(report)

        normalized = normalize_domain(page.final_url or source_url)
        result.normalized_domain = normalized

        previous = get_latest_check(db_path, normalized)
        report.diff = build_report_diff(previous, report)
        save_check(db_path, report, normalized)

        result.warnings_count = len(report.all_warnings)
        result.broken_links_count = links.broken_count if links else 0
        result.changes_count = report.diff.change_count if report.diff else 0
        result.previous_check_found = bool(report.diff and report.diff.has_previous)

        output_dir.mkdir(parents=True, exist_ok=True)
        template_dir = project_root / "templates"
        report_url = page.final_url or source_url
        ts = run_timestamp or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        html_filename, pdf_filename = report_output_filenames(report_url, ts)
        html_path = output_dir / html_filename

        _, render_warnings = render_report(report, template_dir, html_path, branding)
        result.branding_warnings.extend(render_warnings)
        report.report_path = str(html_path)
        result.html_path = str(html_path)

        fmt = output_format.lower()
        if fmt in ("pdf", "both"):
            pdf_path = output_dir / pdf_filename
            try:
                export_html_to_pdf(html_path, pdf_path)
                report.pdf_path = str(pdf_path)
                result.pdf_path = str(pdf_path)
            except PdfExportError as exc:
                if fmt == "pdf":
                    result.error = str(exc)
                    result.success = False
                    raise SingleReportError(str(exc), result) from exc
                result.branding_warnings.append(str(exc))

        result.success = True
        return result

    except SingleReportError:
        raise
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.success = False
        return result
