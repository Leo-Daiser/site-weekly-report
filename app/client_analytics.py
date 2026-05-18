from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from app.admin_clients import AdminClientRow
from app.utils import normalize_domain


@dataclass
class ClientReportSnapshot:
    url: str
    normalized_domain: str
    success: bool
    error: str = ""
    health_score: int | None = None
    health_label: str = ""
    warnings_count: int = 0
    broken_links_count: int = 0
    pages_checked_count: int = 0
    noindex_pages_count: int = 0
    broken_assets_count: int = 0
    top_actions: list[str] = field(default_factory=list)
    html_path: str = ""
    pdf_path: str = ""
    summary_path: str = ""
    created_at: str = ""


@dataclass
class ClientSiteAnalytics:
    row: AdminClientRow
    latest: ClientReportSnapshot | None = None
    previous: ClientReportSnapshot | None = None

    @property
    def score_delta(self) -> int | None:
        if not self.latest or not self.previous:
            return None
        if self.latest.health_score is None or self.previous.health_score is None:
            return None
        return self.latest.health_score - self.previous.health_score

    @property
    def warning_delta(self) -> int | None:
        if not self.latest or not self.previous:
            return None
        return self.latest.warnings_count - self.previous.warnings_count


@dataclass
class ClientDashboardAnalytics:
    sites: list[ClientSiteAnalytics]
    active_sites: int = 0
    average_health_score: int | None = None
    open_warnings: int = 0
    broken_links: int = 0
    latest_report_date: str = ""


def _parse_int(value: str | None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


def _is_success(value: str | None) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "ok", "success")


def _safe_domain(url: str) -> str:
    try:
        return normalize_domain(url)
    except Exception:
        return url.strip().rstrip("/").lower()


def _safe_rel(path_text: str, project_root: Path) -> str:
    if not path_text:
        return ""
    path = Path(path_text)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return ""


def _snapshot_from_row(row: dict[str, str], summary_path: Path, project_root: Path) -> ClientReportSnapshot:
    actions = [part.strip() for part in (row.get("top_actions") or "").split("|") if part.strip()]
    score = _parse_int(row.get("health_score"))
    return ClientReportSnapshot(
        url=row.get("url", ""),
        normalized_domain=row.get("normalized_domain") or _safe_domain(row.get("url", "")),
        success=_is_success(row.get("success")),
        error=row.get("error", ""),
        health_score=score,
        health_label=row.get("health_label", ""),
        warnings_count=_parse_int(row.get("warnings_count")) or 0,
        broken_links_count=_parse_int(row.get("broken_links_count")) or 0,
        pages_checked_count=_parse_int(row.get("pages_checked_count")) or 0,
        noindex_pages_count=_parse_int(row.get("noindex_pages_count")) or 0,
        broken_assets_count=_parse_int(row.get("broken_assets_count")) or 0,
        top_actions=actions[:3],
        html_path=_safe_rel(row.get("html_path", ""), project_root),
        pdf_path=_safe_rel(row.get("pdf_path", ""), project_root),
        summary_path=_safe_rel(str(summary_path), project_root),
        created_at=summary_path.parent.name,
    )


def load_report_snapshots(reports_dir: Path, project_root: Path) -> dict[str, list[ClientReportSnapshot]]:
    snapshots: dict[str, list[ClientReportSnapshot]] = {}
    summaries = sorted(
        reports_dir.rglob("summary.csv"),
        key=lambda path: (path.stat().st_mtime, path.parent.name, path.name),
        reverse=True,
    )
    for summary in summaries:
        try:
            with summary.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    domain = row.get("normalized_domain") or _safe_domain(row.get("url", ""))
                    if not domain:
                        continue
                    snapshots.setdefault(domain, []).append(_snapshot_from_row(row, summary, project_root))
        except OSError:
            continue
    return snapshots


def build_client_dashboard_analytics(
    rows: list[AdminClientRow],
    reports_dir: Path,
    project_root: Path,
) -> ClientDashboardAnalytics:
    snapshots_by_domain = load_report_snapshots(reports_dir, project_root)
    sites: list[ClientSiteAnalytics] = []
    scores: list[int] = []
    latest_dates: list[str] = []
    open_warnings = 0
    broken_links = 0

    for row in rows:
        domain = _safe_domain(row.url)
        snapshots = snapshots_by_domain.get(domain, [])
        latest = snapshots[0] if snapshots else None
        previous = snapshots[1] if len(snapshots) > 1 else None
        if latest:
            if latest.health_score is not None:
                scores.append(latest.health_score)
            open_warnings += latest.warnings_count
            broken_links += latest.broken_links_count
            if latest.created_at:
                latest_dates.append(latest.created_at)
        sites.append(ClientSiteAnalytics(row=row, latest=latest, previous=previous))

    active_sites = len([item for item in rows if item.operational_status == "active"])
    average = round(sum(scores) / len(scores)) if scores else None
    return ClientDashboardAnalytics(
        sites=sites,
        active_sites=active_sites,
        average_health_score=average,
        open_warnings=open_warnings,
        broken_links=broken_links,
        latest_report_date=max(latest_dates) if latest_dates else "",
    )
