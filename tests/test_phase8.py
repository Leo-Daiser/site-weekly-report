import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.actions import build_prioritized_actions
from app.batch import SUMMARY_CSV_COLUMNS, write_summary_csv
from app.models import (
    LinkCheckResult,
    PageFetchResult,
    ReportRunResult,
    SeoCheckResult,
    SiteReport,
    StoredCheck,
)
from app.report_builder import render_report
from app.scoring import (
    LABEL_EXCELLENT,
    LABEL_NEEDS_ATTENTION,
    build_report_issues,
    calculate_health_score,
    enrich_report_with_health,
)


def _minimal_report(
    *,
    page: PageFetchResult | None = None,
    seo: SeoCheckResult | None = None,
    links: LinkCheckResult | None = None,
) -> SiteReport:
    return SiteReport(
        source_url="https://example.com",
        page=page
        or PageFetchResult(
            source_url="https://example.com", status_code=200, html="<html></html>"
        ),
        seo=seo
        or SeoCheckResult(
            title="Good title for SEO check here",
            title_length=30,
            meta_description="A" * 60,
            meta_description_length=60,
            h1_count=1,
            canonical_url="https://example.com/",
        ),
        links=links or LinkCheckResult(broken_count=0),
    )


class TestHealthScore(unittest.TestCase):
    def test_score_100_without_issues(self) -> None:
        health = calculate_health_score([])
        self.assertEqual(health.score, 100)
        self.assertEqual(health.label, LABEL_EXCELLENT)

    def test_critical_penalty_25(self) -> None:
        issues = build_report_issues(
            SiteReport(
                source_url="https://x.com",
                page=PageFetchResult(source_url="https://x.com", error="timeout"),
            )
        )
        health = calculate_health_score(issues)
        self.assertLessEqual(health.score, 75)
        self.assertGreaterEqual(health.critical_count, 1)

    def test_score_not_below_zero(self) -> None:
        issues = build_report_issues(
            SiteReport(
                source_url="https://x.com",
                page=PageFetchResult(source_url="https://x.com", error="e", status_code=500),
                seo=SeoCheckResult(),
                links=LinkCheckResult(broken_count=10),
            )
        )
        health = calculate_health_score(issues)
        self.assertGreaterEqual(health.score, 0)

    def test_label_excellent(self) -> None:
        self.assertEqual(calculate_health_score([]).label, LABEL_EXCELLENT)

    def test_label_needs_attention(self) -> None:
        from app.scoring import _issue

        issues = [
            _issue("a", "A", "d", "medium", "seo", "r"),
            _issue("b", "B", "d", "medium", "seo", "r"),
            _issue("c", "C", "d", "medium", "seo", "r"),
            _issue("d", "D", "d", "medium", "seo", "r"),
            _issue("e", "E", "d", "medium", "seo", "r"),
        ]
        health = calculate_health_score(issues)
        self.assertEqual(health.score, 65)
        self.assertEqual(health.label, LABEL_NEEDS_ATTENTION)


class TestReportIssues(unittest.TestCase):
    def test_page_error_critical(self) -> None:
        report = SiteReport(
            source_url="https://x.com",
            page=PageFetchResult(source_url="https://x.com", error="connection refused"),
        )
        issues = build_report_issues(report)
        self.assertTrue(any(i.code == "page_error" and i.severity == "critical" for i in issues))

    def test_missing_title_high(self) -> None:
        report = _minimal_report(
            seo=SeoCheckResult(title=None, title_length=0, h1_count=1)
        )
        issues = build_report_issues(report)
        self.assertTrue(any(i.code == "title_missing" and i.severity == "high" for i in issues))

    def test_missing_description_high(self) -> None:
        report = _minimal_report(
            seo=SeoCheckResult(
                title="Enough length title for page",
                title_length=28,
                meta_description=None,
                meta_description_length=0,
                h1_count=1,
                canonical_url="https://example.com/",
            )
        )
        issues = build_report_issues(report)
        self.assertTrue(any(i.code == "description_missing" for i in issues))

    def test_broken_links_medium(self) -> None:
        report = _minimal_report(links=LinkCheckResult(broken_count=2))
        issues = build_report_issues(report)
        self.assertTrue(any(i.code == "broken_links_medium" for i in issues))

    def test_broken_links_high(self) -> None:
        report = _minimal_report(links=LinkCheckResult(broken_count=5))
        issues = build_report_issues(report)
        self.assertTrue(any(i.code == "broken_links_high" for i in issues))


class TestPrioritizedActions(unittest.TestCase):
    def test_max_three_actions(self) -> None:
        from app.scoring import _issue

        issues = [
            _issue(f"i{n}", f"T{n}", "d", "low", "seo", "r") for n in range(10)
        ]
        actions = build_prioritized_actions(issues, limit=3)
        self.assertLessEqual(len(actions), 3)

    def test_sorted_by_severity(self) -> None:
        from app.scoring import _issue

        issues = [
            _issue("low1", "Low", "d", "low", "seo", "r"),
            _issue("crit", "Critical", "d", "critical", "availability", "r"),
            _issue("high1", "High", "d", "high", "seo", "r"),
        ]
        actions = build_prioritized_actions(issues)
        self.assertEqual(actions[0].severity, "critical")

    def test_no_issues_default_message(self) -> None:
        actions = build_prioritized_actions([])
        self.assertEqual(len(actions), 1)
        self.assertIn("No urgent", actions[0].title)


class TestBatchSummaryHealth(unittest.TestCase):
    def test_summary_csv_has_health_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            batch_dir = Path(tmp)
            result = ReportRunResult(
                url="https://example.com",
                success=True,
                health_score=72,
                health_label="Needs attention",
                critical_issues=0,
                high_issues=2,
                medium_issues=3,
                low_issues=1,
                top_actions="Fix links | Add description",
            )
            csv_path = batch_dir / "summary.csv"
            write_summary_csv(csv_path, [result], batch_dir)
            with csv_path.open(encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["health_score"], "72")
            self.assertIn("health_score", SUMMARY_CSV_COLUMNS)


class TestHtmlReportHealth(unittest.TestCase):
    def test_html_contains_health_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = _minimal_report()
            enrich_report_with_health(report)
            out = Path(tmp) / "report.html"
            template_dir = Path(__file__).resolve().parent.parent / "templates"
            from app.models import BrandingConfig

            render_report(report, template_dir, out, BrandingConfig())
            html = out.read_text(encoding="utf-8")
            self.assertIn("Site Health Score", html)
            self.assertIn("Executive summary", html)
            self.assertIn("Top 3 actions", html)


class TestOnboardClientJson(unittest.TestCase):
    def test_client_json_has_health_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "reports"
            reports.mkdir()
            html = reports / "r.html"
            html.write_text("<html></html>", encoding="utf-8")
            mock = ReportRunResult(
                url="https://example.com",
                success=True,
                health_score=80,
                health_label="Good",
                critical_issues=0,
                high_issues=1,
                medium_issues=2,
                low_issues=0,
                top_actions="Fix title",
                html_path=str(html),
            )
            from app.models import BrandingConfig
            from app.leads import run_onboard

            with patch("app.leads.run_single_report", return_value=mock):
                result = run_onboard(
                    client_name="Demo",
                    client_email="d@example.com",
                    url="https://example.com",
                    branding=BrandingConfig(),
                    output_format="html",
                    max_links=5,
                    timeout=10.0,
                    output_dir=reports,
                    db_path=root / "db.sqlite",
                    leads_dir=root / "leads",
                    project_root=root,
                    template_dir=Path(__file__).resolve().parent.parent / "templates",
                )
            import json

            data = json.loads(result.client_json_path.read_text(encoding="utf-8"))
            self.assertEqual(data["health_score"], 80)
            self.assertEqual(data["health_label"], "Good")


if __name__ == "__main__":
    unittest.main()
