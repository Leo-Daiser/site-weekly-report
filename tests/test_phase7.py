import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.leads import (
    append_to_clients_csv_if_needed,
    build_lead_slug,
    copy_sample_reports,
    run_onboard,
    validate_client_email,
    write_client_json,
)
from app.models import BrandingConfig, LeadClientRecord, ReportRunResult


class TestBuildLeadSlug(unittest.TestCase):
    def test_slug_from_name_and_domain(self) -> None:
        slug = build_lead_slug("Demo Client", "example.com")
        self.assertEqual(slug, "demo-client-example-com")


class TestValidateEmail(unittest.TestCase):
    def test_invalid_email_warning(self) -> None:
        warnings: list[str] = []
        result = validate_client_email("not-an-email", warnings)
        self.assertIsNone(result)
        self.assertTrue(any("Невалидный" in w for w in warnings))


class TestClientsCsvAppend(unittest.TestCase):
    def test_creates_csv_with_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clients.csv"
            status = append_to_clients_csv_if_needed(
                path,
                client_name="A",
                client_email="a@test.com",
                brand_name="Brand",
                url="https://example.com",
                brand_color="#2563eb",
                brand_logo=None,
                footer_text=None,
                report_format="html",
                max_links=30,
                timeout=10.0,
            )
            self.assertEqual(status, "added")
            self.assertTrue(path.is_file())
            with path.open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["url"], "https://example.com")

    def test_no_duplicate_by_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clients.csv"
            kwargs = dict(
                client_name="A",
                client_email="a@test.com",
                brand_name="Brand",
                url="https://example.com",
                brand_color="#2563eb",
                brand_logo=None,
                footer_text=None,
                report_format="html",
                max_links=30,
                timeout=10.0,
            )
            self.assertEqual(append_to_clients_csv_if_needed(path, **kwargs), "added")
            self.assertEqual(
                append_to_clients_csv_if_needed(
                    path,
                    client_name="B",
                    client_email="b@test.com",
                    **{k: v for k, v in kwargs.items() if k not in ("client_name", "client_email")},
                ),
                "already exists",
            )
            with path.open(encoding="utf-8") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 1)


class TestOnboardDeliverables(unittest.TestCase):
    def _mock_report(self, html_path: Path) -> ReportRunResult:
        return ReportRunResult(
            url="https://example.com",
            normalized_domain="example.com",
            success=True,
            scan_ok=True,
            status_code=200,
            html_path=str(html_path),
            warnings_count=3,
            broken_links_count=1,
            changes_count=0,
            previous_check_found=False,
            brand_name="SEO Studio",
            client_name="Demo Client",
        )

    def test_run_onboard_creates_lead_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "reports"
            reports.mkdir()
            leads = root / "leads"
            html = reports / "example_com_test.html"
            html.write_text("<html><body>report</body></html>", encoding="utf-8")
            mock = self._mock_report(html)
            template_dir = Path(__file__).resolve().parent.parent / "templates"

            with patch("app.leads.run_single_report", return_value=mock):
                result = run_onboard(
                    client_name="Demo Client",
                    client_email="demo@example.com",
                    url="https://example.com",
                    branding=BrandingConfig(brand_name="SEO Studio", client_name="Demo Client"),
                    output_format="html",
                    max_links=10,
                    timeout=10.0,
                    output_dir=reports,
                    db_path=root / "db.sqlite",
                    leads_dir=leads,
                    project_root=root,
                    template_dir=template_dir,
                )

            self.assertTrue(result.lead_dir.is_dir())
            self.assertTrue((result.lead_dir / "client.json").is_file())
            self.assertTrue((result.lead_dir / "sample_report.html").is_file())
            self.assertTrue(result.email_preview_txt.is_file())
            self.assertTrue(result.email_preview_html.is_file())
            self.assertTrue(result.notes_path.is_file())

            payload = json.loads((result.lead_dir / "client.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["client_name"], "Demo Client")
            self.assertEqual(payload["normalized_domain"], "example.com")

            notes = result.notes_path.read_text(encoding="utf-8")
            self.assertIn("https://example.com", notes)
            self.assertIn("Suggested outreach", notes)

            email_txt = result.email_preview_txt.read_text(encoding="utf-8")
            self.assertIn("example.com", email_txt)

    def test_copy_sample_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src.html"
            src.write_text("<html></html>", encoding="utf-8")
            lead = root / "lead"
            lead.mkdir()
            result = ReportRunResult(url="https://x.com", html_path=str(src), success=True)
            html_dest, _ = copy_sample_reports(result, lead)
            self.assertIsNotNone(html_dest)
            self.assertTrue((lead / "sample_report.html").is_file())


class TestWriteClientJson(unittest.TestCase):
    def test_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lead = Path(tmp) / "lead"
            lead.mkdir()
            record = LeadClientRecord(
                client_name="X",
                url="https://example.com",
                normalized_domain="example.com",
                brand_name="Brand",
                created_at="2026-01-01T00:00:00+00:00",
            )
            path = write_client_json(lead, record)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["client_name"], "X")


class TestGitignoreLeads(unittest.TestCase):
    def test_gitignore_contains_leads_rule(self) -> None:
        content = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(
            encoding="utf-8"
        )
        self.assertIn("leads/*", content)
        self.assertIn("!leads/.gitkeep", content)


class TestCliCompatibility(unittest.TestCase):
    def test_onboard_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.onboard", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--client-name", result.stdout)

    def test_main_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.main", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)

    def test_weekly_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.weekly", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
