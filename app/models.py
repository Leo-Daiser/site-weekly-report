from __future__ import annotations

from datetime import datetime
from pathlib import Path
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

IssueSeverity = Literal["info", "low", "medium", "high", "critical"]
IssueCategory = Literal[
    "availability",
    "seo",
    "technical",
    "forms",
    "links",
    "performance",
    "changes",
]


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


class SMTPConfig(BaseModel):
    host: str
    port: int = 587
    username: str | None = None
    password: str | None = None
    from_email: str
    from_name: str | None = None
    use_tls: bool = True


class EmailManifestEntry(BaseModel):
    client_name: str = ""
    client_email: str = ""
    brand_name: str = ""
    url: str = ""
    subject: str = ""
    text_path: str = ""
    html_path: str = ""
    report_html_path: str = ""
    report_pdf_path: str = ""
    status: str = "prepared"
    error: str = ""


class OutboxResult(BaseModel):
    outbox_dir: Path
    manifest_path: Path
    prepared_count: int = 0
    skipped_count: int = 0
    sent_count: int = 0
    failed_count: int = 0
    warnings: list[str] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


class BatchRunResult(BaseModel):
    batch_dir: Path
    summary_csv: Path
    summary_html: Path
    total: int
    successful: int
    failed: int
    results: list[ReportRunResult] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


class EmailRunResult(BaseModel):
    outbox_dir: Path
    emails_prepared: int = 0
    emails_sent: int = 0
    emails_failed: int = 0
    skipped_count: int = 0
    warnings: list[str] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


WeeklyMode = Literal["dry-run", "generate", "outbox", "send"]


class WeeklyJobConfig(BaseModel):
    job_name: str
    clients_csv: str
    output_dir: str = "reports"
    outbox_dir: str = "outbox"
    db_path: str = "data/checks.sqlite"
    branding_file: str | None = "branding/default.json"
    format: ReportFormat = "html"
    max_links: int = 30
    timeout: float = 10
    create_outbox: bool = True
    send_email: bool = False
    continue_on_error: bool = True
    limit: int | None = None


class WeeklyRunLog(BaseModel):
    run_id: str
    job_name: str
    mode: WeeklyMode
    started_at: str
    finished_at: str | None = None
    success: bool = False
    clients_csv: str | None = None
    batch_dir: str | None = None
    outbox_dir: str | None = None
    summary_csv: str | None = None
    summary_html: str | None = None
    total: int = 0
    successful: int = 0
    failed: int = 0
    emails_prepared: int = 0
    emails_sent: int = 0
    emails_failed: int = 0
    error: str | None = None


class ReportIssue(BaseModel):
    code: str
    title: str
    description: str
    severity: IssueSeverity
    category: IssueCategory
    recommendation: str
    weight: int = 0


class PrioritizedAction(BaseModel):
    title: str
    reason: str
    severity: IssueSeverity
    category: IssueCategory
    estimated_impact: str


class HealthScore(BaseModel):
    score: int
    label: str
    issues_total: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    top_actions: list[PrioritizedAction] = Field(default_factory=list)


class LeadClientRecord(BaseModel):
    client_name: str
    client_email: str | None = None
    url: str
    normalized_domain: str
    brand_name: str
    brand_color: str = "#2563eb"
    format: str = "html"
    created_at: str
    report_html_path: str = "sample_report.html"
    report_pdf_path: str | None = None
    warnings_count: int = 0
    broken_links_count: int = 0
    changes_count: int = 0
    previous_check_found: bool = False
    status_code: int | None = None
    health_score: int | None = None
    health_label: str | None = None
    critical_issues: int = 0
    high_issues: int = 0
    medium_issues: int = 0
    low_issues: int = 0
    top_actions: list[str] = Field(default_factory=list)


class OnboardResult(BaseModel):
    lead_dir: Path
    client_json_path: Path
    sample_report_html: Path | None = None
    sample_report_pdf: Path | None = None
    email_preview_txt: Path
    email_preview_html: Path
    notes_path: Path
    report_result: ReportRunResult
    warnings: list[str] = Field(default_factory=list)
    clients_csv_status: str | None = None

    model_config = {"arbitrary_types_allowed": True}


class ReportRunResult(BaseModel):
    url: str
    normalized_domain: str | None = None
    success: bool = False
    scan_ok: bool = False
    error: str | None = None
    html_path: str | None = None
    pdf_path: str | None = None
    status_code: int | None = None
    warnings_count: int = 0
    broken_links_count: int = 0
    changes_count: int = 0
    previous_check_found: bool = False
    brand_name: str | None = None
    client_name: str | None = None
    branding_warnings: list[str] = Field(default_factory=list)
    health_score: int | None = None
    health_label: str | None = None
    critical_issues: int = 0
    high_issues: int = 0
    medium_issues: int = 0
    low_issues: int = 0
    top_actions: str = ""


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
    issues: list[ReportIssue] = Field(default_factory=list)
    health_score: HealthScore | None = None
