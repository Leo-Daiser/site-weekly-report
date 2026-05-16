from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PageFetchResult(BaseModel):
    source_url: str
    final_url: str | None = None
    status_code: int | None = None
    response_time_ms: float | None = None
    html: str | None = None
    error: str | None = None


class SeoCheckResult(BaseModel):
    title: str | None = None
    title_length: int = 0
    meta_description: str | None = None
    meta_description_length: int = 0
    h1_list: list[str] = Field(default_factory=list)
    h1_count: int = 0
    canonical_url: str | None = None
    html_lang: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ResourceCheckResult(BaseModel):
    resource_type: Literal["robots.txt", "sitemap.xml"]
    url: str
    exists: bool = False
    status_code: int | None = None
    error: str | None = None


class FormCheckResult(BaseModel):
    method: str | None = None
    action: str | None = None
    input_count: int = 0
    has_submit: bool = False
    warnings: list[str] = Field(default_factory=list)


class LinkItem(BaseModel):
    url: str
    status_code: int | None = None
    response_time_ms: float | None = None
    error: str | None = None
    is_broken: bool = False


class LinkCheckResult(BaseModel):
    internal_links: list[str] = Field(default_factory=list)
    external_links: list[str] = Field(default_factory=list)
    checked_links: list[LinkItem] = Field(default_factory=list)
    broken_count: int = 0
    warnings: list[str] = Field(default_factory=list)


DiffSeverity = Literal["positive", "neutral", "warning", "critical"]


class DiffChange(BaseModel):
    message: str
    severity: DiffSeverity


class ReportDiff(BaseModel):
    has_previous: bool = False
    previous_created_at: str | None = None
    changes: list[DiffChange] = Field(default_factory=list)
    first_check_message: str | None = None
    no_changes_message: str | None = None

    @property
    def change_count(self) -> int:
        return len(self.changes)


class StoredCheck(BaseModel):
    id: int
    created_at: str
    input_url: str
    final_url: str | None = None
    normalized_domain: str
    status_code: int | None = None
    response_time_ms: float | None = None
    title: str | None = None
    title_length: int | None = None
    description: str | None = None
    description_length: int | None = None
    h1_count: int | None = None
    canonical_url: str | None = None
    robots_exists: int = 0
    robots_status_code: int | None = None
    sitemap_exists: int = 0
    sitemap_status_code: int | None = None
    forms_count: int = 0
    broken_links_count: int = 0
    internal_links_count: int = 0
    external_links_count: int = 0
    warnings_count: int = 0
    raw_json: str | None = None


class BrandingConfig(BaseModel):
    brand_name: str = "WebReport Weekly"
    client_name: str | None = None
    brand_color: str = "#2563eb"
    logo_path: str | None = None
    footer_text: str | None = "Prepared by WebReport Weekly"
    show_powered_by: bool = True


ReportFormat = Literal["html", "pdf", "both"]


class SiteReport(BaseModel):
    scanned_at: datetime = Field(default_factory=datetime.now)
    source_url: str
    page: PageFetchResult
    seo: SeoCheckResult | None = None
    robots: ResourceCheckResult | None = None
    sitemap: ResourceCheckResult | None = None
    forms: list[FormCheckResult] = Field(default_factory=list)
    links: LinkCheckResult | None = None
    all_warnings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    report_path: str | None = None
    pdf_path: str | None = None
    diff: ReportDiff | None = None
