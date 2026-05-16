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
