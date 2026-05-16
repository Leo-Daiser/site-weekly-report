from __future__ import annotations

import sqlite3
from pathlib import Path

from app.models import SiteReport, StoredCheck

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS site_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    input_url TEXT NOT NULL,
    final_url TEXT,
    normalized_domain TEXT NOT NULL,
    status_code INTEGER,
    response_time_ms REAL,
    title TEXT,
    title_length INTEGER,
    description TEXT,
    description_length INTEGER,
    h1_count INTEGER,
    canonical_url TEXT,
    robots_exists INTEGER,
    robots_status_code INTEGER,
    sitemap_exists INTEGER,
    sitemap_status_code INTEGER,
    forms_count INTEGER,
    broken_links_count INTEGER,
    internal_links_count INTEGER,
    external_links_count INTEGER,
    warnings_count INTEGER,
    raw_json TEXT NOT NULL
);
"""

INSERT_SQL = """
INSERT INTO site_checks (
    created_at, input_url, final_url, normalized_domain,
    status_code, response_time_ms,
    title, title_length, description, description_length,
    h1_count, canonical_url,
    robots_exists, robots_status_code,
    sitemap_exists, sitemap_status_code,
    forms_count, broken_links_count,
    internal_links_count, external_links_count,
    warnings_count, raw_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(CREATE_TABLE_SQL)
        conn.commit()


def _row_to_stored_check(row: sqlite3.Row) -> StoredCheck:
    return StoredCheck(
        id=row["id"],
        created_at=row["created_at"],
        input_url=row["input_url"],
        final_url=row["final_url"],
        normalized_domain=row["normalized_domain"],
        status_code=row["status_code"],
        response_time_ms=row["response_time_ms"],
        title=row["title"],
        title_length=row["title_length"],
        description=row["description"],
        description_length=row["description_length"],
        h1_count=row["h1_count"],
        canonical_url=row["canonical_url"],
        robots_exists=row["robots_exists"] or 0,
        robots_status_code=row["robots_status_code"],
        sitemap_exists=row["sitemap_exists"] or 0,
        sitemap_status_code=row["sitemap_status_code"],
        forms_count=row["forms_count"] or 0,
        broken_links_count=row["broken_links_count"] or 0,
        internal_links_count=row["internal_links_count"] or 0,
        external_links_count=row["external_links_count"] or 0,
        warnings_count=row["warnings_count"] or 0,
        raw_json=row["raw_json"],
    )


def metrics_from_report(report: SiteReport, normalized_domain: str) -> dict:
    seo = report.seo
    links = report.links
    return {
        "created_at": report.scanned_at.isoformat(),
        "input_url": report.source_url,
        "final_url": report.page.final_url,
        "normalized_domain": normalized_domain,
        "status_code": report.page.status_code,
        "response_time_ms": report.page.response_time_ms,
        "title": seo.title if seo else None,
        "title_length": seo.title_length if seo else 0,
        "description": seo.meta_description if seo else None,
        "description_length": seo.meta_description_length if seo else 0,
        "h1_count": seo.h1_count if seo else 0,
        "canonical_url": seo.canonical_url if seo else None,
        "robots_exists": 1 if report.robots and report.robots.exists else 0,
        "robots_status_code": report.robots.status_code if report.robots else None,
        "sitemap_exists": 1 if report.sitemap and report.sitemap.exists else 0,
        "sitemap_status_code": report.sitemap.status_code if report.sitemap else None,
        "forms_count": len(report.forms),
        "broken_links_count": links.broken_count if links else 0,
        "internal_links_count": len(links.internal_links) if links else 0,
        "external_links_count": len(links.external_links) if links else 0,
        "warnings_count": len(report.all_warnings),
        "raw_json": report.model_dump_json(),
    }


def get_latest_check(db_path: Path, normalized_domain: str) -> StoredCheck | None:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT * FROM site_checks
            WHERE normalized_domain = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (normalized_domain,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_stored_check(row)


def save_check(db_path: Path, report: SiteReport, normalized_domain: str) -> int:
    init_db(db_path)
    m = metrics_from_report(report, normalized_domain)
    values = (
        m["created_at"],
        m["input_url"],
        m["final_url"],
        m["normalized_domain"],
        m["status_code"],
        m["response_time_ms"],
        m["title"],
        m["title_length"],
        m["description"],
        m["description_length"],
        m["h1_count"],
        m["canonical_url"],
        m["robots_exists"],
        m["robots_status_code"],
        m["sitemap_exists"],
        m["sitemap_status_code"],
        m["forms_count"],
        m["broken_links_count"],
        m["internal_links_count"],
        m["external_links_count"],
        m["warnings_count"],
        m["raw_json"],
    )
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(INSERT_SQL, values)
        conn.commit()
        return int(cursor.lastrowid)
