import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.client_packages import (
    append_client_to_clients_csv,
    build_client_slug,
    create_client_package,
    update_weekly_job_config,
)
from app.convert_client import run_convert_client
from app.crm_store import add_lead, find_lead_by_id, load_leads, utc_now_iso
from app.models import LeadRecord
from app.pricing import get_plan, load_pricing_config


class TestBuildClientSlug(unittest.TestCase):
    def test_slug(self) -> None:
        self.assertEqual(
            build_client_slug("Demo Studio", "example.com"),
            "demo-studio-example-com",
        )


class TestAppendClientsCsv(unittest.TestCase):
    def test_creates_csv_with_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clients.csv"
            status = append_client_to_clients_csv(
                path,
                client_name="Demo",
                client_email="demo@example.com",
                brand_name="Demo",
                url="https://example.com",
                brand_color="#2563eb",
                footer_text="Prepared by Demo",
                report_format="both",
                max_links=30,
                timeout=10.0,
            )
            self.assertEqual(status, "added")
            with path.open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["url"], "https://example.com")

    def test_no_duplicate_url_and_email(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clients.csv"
            kwargs = dict(
                client_name="Demo",
                client_email="demo@example.com",
                brand_name="Demo",
                url="https://example.com",
                brand_color="#2563eb",
                footer_text="Prepared by Demo",
                report_format="both",
                max_links=30,
                timeout=10.0,
            )
            self.assertEqual(append_client_to_clients_csv(path, **kwargs), "added")
            self.assertEqual(append_client_to_clients_csv(path, **kwargs), "already exists")
            with path.open(encoding="utf-8") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 1)


class TestConvertClient(unittest.TestCase):
    def _seed_lead(self, crm_path: Path) -> LeadRecord:
        return add_lead(
            crm_path,
            LeadRecord(
                lead_id="lead_0001",
                client_name="Demo Studio",
                client_email="demo@example.com",
                url="https://example.com",
                normalized_domain="example.com",
                status="interested",
                created_at=utc_now_iso(),
            ),
        )

    def test_creates_client_package_and_updates_crm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crm_path = root / "leads_crm.csv"
            clients_path = root / "clients.csv"
            packages_dir = root / "client_packages"
            pricing_path = Path(__file__).resolve().parent.parent / "data" / "pricing.example.json"
            template_dir = Path(__file__).resolve().parent.parent / "templates"
            self._seed_lead(crm_path)

            result = run_convert_client(
                lead_id="lead_0001",
                plan_id="agency-lite",
                crm_path=crm_path,
                clients_csv=clients_path,
                pricing_file=pricing_path,
                packages_dir=packages_dir,
                template_dir=template_dir,
                project_root=root,
            )

            self.assertEqual(result.clients_csv_status, "added")
            slug_dir = packages_dir / "demo-studio-example-com"
            self.assertTrue(slug_dir.is_dir())
            self.assertTrue((slug_dir / "client_config.json").is_file())
            self.assertTrue((slug_dir / "onboarding_checklist.md").is_file())
            self.assertTrue((slug_dir / "welcome_message.md").is_file())

            config = json.loads((slug_dir / "client_config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["plan_name"], "Agency Lite")
            self.assertEqual(config["price_monthly"], 79)

            welcome = (slug_dir / "welcome_message.md").read_text(encoding="utf-8")
            self.assertIn("Agency Lite", welcome)
            self.assertIn("example.com", welcome)

            lead = find_lead_by_id(crm_path, "lead_0001")
            assert lead is not None
            self.assertEqual(lead.status, "converted")
            self.assertIn("plan=agency-lite", lead.notes)
            self.assertIsNone(lead.next_followup_at)

    def test_lead_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pricing_path = Path(__file__).resolve().parent.parent / "data" / "pricing.example.json"
            with self.assertRaises(ValueError) as ctx:
                run_convert_client(
                    lead_id="lead_9999",
                    plan_id="starter",
                    crm_path=root / "leads_crm.csv",
                    clients_csv=root / "clients.csv",
                    pricing_file=pricing_path,
                    packages_dir=root / "packages",
                    template_dir=Path(__file__).resolve().parent.parent / "templates",
                    project_root=root,
                )
            self.assertIn("not found", str(ctx.exception).lower())

    def test_unknown_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crm_path = root / "leads_crm.csv"
            pricing_path = Path(__file__).resolve().parent.parent / "data" / "pricing.example.json"
            self._seed_lead(crm_path)
            config, _ = load_pricing_config(pricing_path)
            with self.assertRaises(ValueError):
                get_plan(config, "unknown-plan-x")

    def test_missing_email(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crm_path = root / "leads_crm.csv"
            add_lead(
                crm_path,
                LeadRecord(
                    lead_id="lead_0001",
                    client_name="Demo",
                    url="https://example.com",
                    normalized_domain="example.com",
                    status="new",
                    created_at=utc_now_iso(),
                ),
            )
            pricing_path = Path(__file__).resolve().parent.parent / "data" / "pricing.example.json"
            with self.assertRaises(ValueError) as ctx:
                run_convert_client(
                    lead_id="lead_0001",
                    plan_id="starter",
                    crm_path=crm_path,
                    clients_csv=root / "clients.csv",
                    pricing_file=pricing_path,
                    packages_dir=root / "packages",
                    template_dir=Path(__file__).resolve().parent.parent / "templates",
                    project_root=root,
                )
            self.assertIn("client_email", str(ctx.exception).lower())


class TestWeeklyJobConfig(unittest.TestCase):
    def test_creates_local_weekly_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_path = root / "weekly_jobs.local.json"
            example = Path(__file__).resolve().parent.parent / "data" / "weekly_jobs.example.json"
            update_weekly_job_config(
                job_path,
                clients_csv="data/clients.local.csv",
                report_format="both",
                example_job_path=example,
            )
            data = json.loads(job_path.read_text(encoding="utf-8"))
            self.assertEqual(data["clients_csv"], "data/clients.local.csv")
            self.assertEqual(data["format"], "both")
            self.assertTrue(data["create_outbox"])
            self.assertFalse(data["send_email"])


class TestGitignorePhase11(unittest.TestCase):
    def test_gitignore_rules(self) -> None:
        content = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(
            encoding="utf-8"
        )
        self.assertIn("client_packages/*", content)
        self.assertIn("!client_packages/.gitkeep", content)
        self.assertIn("data/clients.csv", content)


class TestCliCompatibility(unittest.TestCase):
    def test_convert_client_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.convert_client", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--lead-id", result.stdout)

    def test_crm_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.crm", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)

    def test_proposal_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.proposal", "--help"],
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
