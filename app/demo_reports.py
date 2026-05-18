from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console

from app.branding import BrandingConfig
from app.models import (
    CrawledPageResult,
    DiffChange,
    FormCheckResult,
    LinkCheckResult,
    LinkItem,
    PageFetchResult,
    ReportDiff,
    ResourceCheckResult,
    SeoCheckResult,
    SiteReport,
    TechnicalCheckResult,
)
from app.report_builder import build_recommendations, collect_all_warnings, render_report
from app.sales_assets import generate_sales_pack, load_sales_pack_config
from app.scoring import enrich_report_with_health
from app.utils import resolve_project_path

console = Console()
cli = typer.Typer(help="Generate stable local demo reports for sales pages.")


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _base_report(name: str, url: str, status: int, response_ms: float) -> SiteReport:
    page = PageFetchResult(
        source_url=url,
        final_url=url,
        status_code=status,
        response_time_ms=response_ms,
        html="<html><head><title>Demo</title></head><body><h1>Demo</h1></body></html>",
    )
    return SiteReport(
        scanned_at=datetime(2026, 1, 1, 9, 0, 0),
        source_url=url,
        page=page,
        seo=SeoCheckResult(
            title=f"{name} - Website Services",
            title_length=len(f"{name} - Website Services"),
            meta_description="A clear service page with enough context for search snippets and client review.",
            meta_description_length=78,
            h1_list=[name],
            h1_count=1,
            canonical_url=url,
            html_lang="en",
        ),
        robots=ResourceCheckResult(resource_type="robots.txt", url=f"{url}/robots.txt", exists=True, status_code=200),
        sitemap=ResourceCheckResult(resource_type="sitemap.xml", url=f"{url}/sitemap.xml", exists=True, status_code=200),
        forms=[
            FormCheckResult(
                method="POST",
                action="/contact",
                input_count=4,
                has_submit=True,
            )
        ],
        links=LinkCheckResult(
            internal_links=[f"{url}/about", f"{url}/services", f"{url}/contact"],
            external_links=["https://www.linkedin.com/company/demo"],
        ),
        crawled_pages=[
            CrawledPageResult(url=url, final_url=url, status_code=status, response_time_ms=response_ms, title=f"{name} - Website Services", h1_count=1),
            CrawledPageResult(url=f"{url}/about", final_url=f"{url}/about", status_code=200, response_time_ms=response_ms + 40, title=f"About {name}", h1_count=1),
            CrawledPageResult(url=f"{url}/services", final_url=f"{url}/services", status_code=200, response_time_ms=response_ms + 55, title=f"{name} Services", h1_count=1),
        ],
        technical=TechnicalCheckResult(
            https_enabled=True,
            http_redirects_to_https=True,
            ssl_valid=True,
            ssl_expires_at="2026-12-31",
            ssl_days_remaining=240,
            robots_blocks_homepage=False,
        ),
        diff=ReportDiff(
            has_previous=True,
            previous_created_at="2025-12-25 09:00",
            changes=[],
            no_changes_message="No meaningful regressions were detected since the previous weekly report.",
        ),
    )


def build_demo_report(kind: str) -> SiteReport:
    if kind == "good":
        report = _base_report("Healthy Studio", "https://good-demo.example", 200, 320)
    elif kind == "medium":
        report = _base_report("Growing Studio", "https://medium-demo.example", 200, 1240)
        report.seo.meta_description = None
        report.seo.meta_description_length = 0
        report.seo.warnings.append("description отсутствует")
        report.links.broken_count = 1
        report.links.checked_links = [
            LinkItem(url="https://medium-demo.example/about", status_code=200, is_broken=False),
            LinkItem(url="https://medium-demo.example/old-offer", status_code=404, is_broken=True),
        ]
        report.technical.noindex_pages = ["https://medium-demo.example/about"]
        report.technical.warnings.append("Найдены страницы с noindex: 1")
        report.crawled_pages[1].noindex = True
        report.diff.changes = [
            DiffChange(message="One internal link became broken since the previous check.", severity="warning"),
            DiffChange(message="A noindex tag was detected on the About page.", severity="warning"),
        ]
    elif kind == "problem":
        report = _base_report("Problem Agency", "http://problem-demo.example", 500, 4200)
        report.page.status_code = 500
        report.page.error = None
        report.seo.title = None
        report.seo.title_length = 0
        report.seo.warnings.extend(["title отсутствует", "description отсутствует"])
        report.robots.exists = False
        report.robots.status_code = 404
        report.sitemap.exists = False
        report.sitemap.status_code = 404
        report.links.broken_count = 3
        report.links.checked_links = [
            LinkItem(url="http://problem-demo.example/missing", status_code=404, is_broken=True),
            LinkItem(url="http://problem-demo.example/old", status_code=410, is_broken=True),
            LinkItem(url="http://problem-demo.example/contact", status_code=500, is_broken=True),
        ]
        report.technical.https_enabled = False
        report.technical.http_redirects_to_https = False
        report.technical.ssl_valid = None
        report.technical.broken_assets = [
            LinkItem(url="http://problem-demo.example", is_broken=True, error="Broken page assets: 4")
        ]
        report.technical.warnings.extend(
            [
                "Сайт открыт не через HTTPS",
                "HTTP-версия не перенаправляет на HTTPS",
                "Найдены битые изображения/ассеты: 4",
            ]
        )
        report.crawled_pages[0].status_code = 500
        report.crawled_pages[0].broken_assets_count = 4
        report.crawled_pages[1].status_code = 404
        report.crawled_pages[1].error = "Page not found"
        report.diff.changes = [
            DiffChange(message="Homepage status changed from 200 to 500.", severity="critical"),
            DiffChange(message="Broken internal links increased from 0 to 3.", severity="warning"),
            DiffChange(message="robots.txt and sitemap.xml are no longer available.", severity="warning"),
        ]
    else:
        raise ValueError(f"Unknown demo kind: {kind}")

    report.all_warnings = collect_all_warnings(report)
    report.recommendations = build_recommendations(report)
    enrich_report_with_health(report)
    return report


def generate_demo_reports(output_dir: Path, template_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    branding = BrandingConfig(
        brand_name="WebReport Weekly",
        client_name="Demo Client",
        brand_color="#147a68",
        footer_text="Demo report generated by WebReport Weekly",
    )
    written: list[Path] = []
    for kind in ("good", "medium", "problem"):
        report = build_demo_report(kind)
        path = output_dir / f"{kind}_site_demo.html"
        render_report(report, template_dir, path, branding)
        written.append(path)
    return written


@cli.command("version")
def version_cmd() -> None:
    console.print("app.demo_reports (WebReport Weekly)")


@cli.command("generate")
def generate_cmd(
    output_dir: str = typer.Option("sales_pack/demo_reports", "--output-dir"),
    sales_config: str = typer.Option("data/sales_pack.example.json", "--sales-config"),
    sales_output_dir: str = typer.Option("sales_pack", "--sales-output-dir"),
    generate_landing: bool = typer.Option(
        True, "--generate-landing/--no-generate-landing"
    ),
) -> None:
    """Generate good/medium/problem demo reports and optionally a sales landing pack."""
    root = _project_root()
    template_dir = root / "templates"
    demo_dir = resolve_project_path(output_dir, root)
    written = generate_demo_reports(demo_dir, template_dir)
    console.print("\n[green]Demo reports generated[/green]")
    for path in written:
        console.print(f"  - {path}")

    if generate_landing:
        config = load_sales_pack_config(resolve_project_path(sales_config, root))
        pack_dir = generate_sales_pack(
            config,
            resolve_project_path(sales_output_dir, root),
            template_dir=template_dir,
            output_format="both",
        )
        console.print(f"Landing pack: {pack_dir}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
