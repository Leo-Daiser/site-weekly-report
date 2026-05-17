import csv
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.crm_store import (
    add_lead,
    attach_sample_to_lead,
    find_duplicate,
    generate_next_lead_id,
    get_followups_due,
    load_leads,
    update_lead_status,
    utc_now_iso,
)
from app.leads import run_onboard
from app.models import BrandingConfig, LeadRecord, ReportRunResult


class TestGenerateLeadId(unittest.TestCase):
    def test_empty_csv_starts_at_lead_0001(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leads_crm.csv"
            self.assertEqual(generate_next_lead_id(path), "lead_0001")


class TestAddLead(unittest.TestCase):
    def test_creates_csv_with_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leads_crm.csv"
            lead = LeadRecord(
                lead_id="",
                client_name="Demo",
                url="https://example.com",
                normalized_domain="example.com",
                status="new",
            )
            saved = add_lead(path, lead)
            self.assertTrue(path.is_file())
            self.assertEqual(saved.lead_id, "lead_0001")
            with path.open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["client_name"], "Demo")

    def test_no_duplicate_same_domain_and_email(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leads_crm.csv"
            first = LeadRecord(
                lead_id="lead_0001",
                client_name="A",
                client_email="a@example.com",
                url="https://example.com",
                normalized_domain="example.com",
                status="new",
                created_at=utc_now_iso(),
            )
            add_lead(path, first)
            dup = find_duplicate(path, "https://example.com", "a@example.com")
            self.assertIsNotNone(dup)
            second = LeadRecord(
                lead_id="lead_0002",
                client_name="B",
                client_email="a@example.com",
                url="https://example.com/",
                normalized_domain="example.com",
                status="new",
            )
            with self.assertRaises(ValueError):
                add_lead(path, second)
            self.assertEqual(len(load_leads(path)), 1)


class TestUpdateLeadStatus(unittest.TestCase):
    def _seed(self, path: Path) -> None:
        add_lead(
            path,
            LeadRecord(
                lead_id="lead_0001",
                client_name="Demo",
                url="https://example.com",
                normalized_domain="example.com",
                status="new",
                created_at=utc_now_iso(),
            ),
        )

    def test_changes_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leads_crm.csv"
            self._seed(path)
            updated = update_lead_status(path, "lead_0001", "contacted")
            self.assertEqual(updated.status, "contacted")

    def test_contacted_sets_last_contacted_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leads_crm.csv"
            self._seed(path)
            updated = update_lead_status(path, "lead_0001", "contacted")
            self.assertTrue(updated.last_contacted_at)

    def test_contacted_sets_next_followup_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leads_crm.csv"
            self._seed(path)
            updated = update_lead_status(path, "lead_0001", "contacted")
            self.assertTrue(updated.next_followup_at)


class TestFollowupsDue(unittest.TestCase):
    def test_returns_due_leads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leads_crm.csv"
            add_lead(
                path,
                LeadRecord(
                    lead_id="lead_0001",
                    client_name="Due",
                    url="https://example.com",
                    normalized_domain="example.com",
                    status="contacted",
                    created_at=utc_now_iso(),
                    next_followup_at="2026-05-10T00:00:00+00:00",
                ),
            )
            add_lead(
                path,
                LeadRecord(
                    lead_id="lead_0002",
                    client_name="Future",
                    url="https://other.com",
                    normalized_domain="other.com",
                    status="contacted",
                    created_at=utc_now_iso(),
                    next_followup_at="2099-01-01T00:00:00+00:00",
                ),
            )
            due = get_followups_due(path, date(2026, 5, 17))
            self.assertEqual(len(due), 1)
            self.assertEqual(due[0].lead_id, "lead_0001")


class TestAttachSample(unittest.TestCase):
    def test_updates_sample_and_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leads_crm.csv"
            add_lead(
                path,
                LeadRecord(
                    lead_id="lead_0001",
                    client_name="Demo",
                    url="https://example.com",
                    normalized_domain="example.com",
                    status="new",
                    created_at=utc_now_iso(),
                ),
            )
            updated = attach_sample_to_lead(
                path,
                "lead_0001",
                sample_report_path="leads/demo/sample_report.html",
                health_score=72,
                health_label="Needs attention",
            )
            self.assertEqual(updated.sample_report_path, "leads/demo/sample_report.html")
            self.assertEqual(updated.health_score, 72)
            self.assertEqual(updated.health_label, "Needs attention")
            self.assertEqual(updated.status, "sample_created")


class TestExportOutreach(unittest.TestCase):
    def test_creates_markdown_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crm_path = root / "data" / "leads_crm.csv"
            crm_path.parent.mkdir(parents=True)
            add_lead(
                crm_path,
                LeadRecord(
                    lead_id="lead_0001",
                    client_name="Studio",
                    url="https://example.com",
                    normalized_domain="example.com",
                    status="new",
                    created_at=utc_now_iso(),
                    health_score=80,
                    health_label="Good",
                ),
            )
            exports = root / "crm_exports"
            exports.mkdir()
            with patch("app.crm._exports_dir", return_value=exports), patch(
                "app.crm._crm_path_option", return_value=crm_path
            ):
                from app.crm import export_outreach_cmd

                export_outreach_cmd(status="new", limit=10, crm_path=str(crm_path))
            files = list(exports.glob("outreach_*.md"))
            self.assertEqual(len(files), 1)
            content = files[0].read_text(encoding="utf-8")
            self.assertIn("Studio", content)
            self.assertIn("example.com", content)
            self.assertIn("Health Score", content)


class TestOnboardCrmIntegration(unittest.TestCase):
    def test_add_to_crm_registers_lead(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "reports"
            reports.mkdir()
            leads = root / "leads"
            crm_path = root / "data" / "leads_crm.csv"
            html = reports / "example_com_test.html"
            html.write_text("<html><body>report</body></html>", encoding="utf-8")
            mock = ReportRunResult(
                url="https://example.com",
                normalized_domain="example.com",
                success=True,
                scan_ok=True,
                status_code=200,
                html_path=str(html),
                warnings_count=1,
                broken_links_count=0,
                changes_count=0,
                health_score=85,
                health_label="Good",
            )
            template_dir = Path(__file__).resolve().parent.parent / "templates"
            with patch("app.leads.run_single_report", return_value=mock):
                result = run_onboard(
                    client_name="Demo Studio",
                    client_email="demo@example.com",
                    url="https://example.com",
                    branding=BrandingConfig(
                        brand_name="SEO Studio", client_name="Demo Studio"
                    ),
                    output_format="html",
                    max_links=10,
                    timeout=10.0,
                    output_dir=reports,
                    db_path=root / "db.sqlite",
                    leads_dir=leads,
                    project_root=root,
                    template_dir=template_dir,
                    add_to_crm=True,
                    crm_csv=crm_path,
                )
            self.assertTrue(result.crm_status and result.crm_status.startswith("lead_"))
            rows = load_leads(crm_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, "sample_created")
            self.assertEqual(rows[0].health_score, 85)
            self.assertIn("sample_report.html", rows[0].sample_report_path or "")


class TestGitignoreCrm(unittest.TestCase):
    def test_gitignore_crm_rules(self) -> None:
        content = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(
            encoding="utf-8"
        )
        self.assertIn("crm_exports/*", content)
        self.assertIn("!crm_exports/.gitkeep", content)
        self.assertIn("data/leads_crm.csv", content)


class TestCliCompatibility(unittest.TestCase):
    def test_crm_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.crm", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("add-lead", result.stdout)

    def test_main_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.main", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)

    def test_batch_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.batch", "--help"],
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

    def test_onboard_help_has_add_to_crm(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.onboard", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--add-to-crm", result.stdout)


if __name__ == "__main__":
    unittest.main()
