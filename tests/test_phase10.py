import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.crm_store import CRM_CSV_COLUMNS, add_lead, attach_proposal_to_lead, load_leads, utc_now_iso
from app.models import LeadRecord
from app.pricing import get_plan, list_plans, load_pricing_config
from app.proposal import build_proposal_dir_name, generate_proposal


class TestPricing(unittest.TestCase):
    def test_load_pricing_example(self) -> None:
        path = Path(__file__).resolve().parent.parent / "data" / "pricing.example.json"
        config, warnings = load_pricing_config(path)
        self.assertFalse(warnings)
        self.assertEqual(config.currency, "USD")
        self.assertIn("starter", config.plans)

    def test_get_plan_agency_lite(self) -> None:
        path = Path(__file__).resolve().parent.parent / "data" / "pricing.example.json"
        config, _ = load_pricing_config(path)
        plan = get_plan(config, "agency-lite")
        self.assertEqual(plan.name, "Agency Lite")
        self.assertEqual(plan.price_monthly, 79)

    def test_unknown_plan_error(self) -> None:
        path = Path(__file__).resolve().parent.parent / "data" / "pricing.example.json"
        config, _ = load_pricing_config(path)
        with self.assertRaises(ValueError) as ctx:
            get_plan(config, "unknown-plan")
        self.assertIn("agency", str(ctx.exception).lower())
        self.assertIn("starter", str(ctx.exception).lower())

    def test_default_when_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, warnings = load_pricing_config(Path(tmp) / "missing.json")
            self.assertTrue(warnings)
            self.assertTrue(list_plans(config))


class TestProposalCreate(unittest.TestCase):
    def _seed_lead(
        self,
        path: Path,
        *,
        health_score: int | None = 72,
        sample_report_path: str | None = "leads/demo/sample_report.html",
    ) -> LeadRecord:
        lead = LeadRecord(
            lead_id="lead_0001",
            client_name="Demo Studio",
            client_email="demo@example.com",
            url="https://example.com",
            normalized_domain="example.com",
            status="sample_created",
            created_at=utc_now_iso(),
            health_score=health_score,
            health_label="Needs attention" if health_score is not None else None,
            sample_report_path=sample_report_path,
        )
        return add_lead(path, lead)

    def test_creates_proposal_folder_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crm_path = root / "leads_crm.csv"
            proposals_dir = root / "proposals"
            pricing_path = Path(__file__).resolve().parent.parent / "data" / "pricing.example.json"
            lead = self._seed_lead(crm_path)
            config, _ = load_pricing_config(pricing_path)
            plan = get_plan(config, "agency-lite")

            record = generate_proposal(
                lead=lead,
                plan=plan,
                currency=config.currency,
                output_dir=proposals_dir,
                project_root=root,
                output_format="both",
            )

            dir_name = build_proposal_dir_name(lead)
            proposal_dir = proposals_dir / dir_name
            self.assertTrue(proposal_dir.is_dir())
            self.assertTrue((proposal_dir / "proposal.json").is_file())
            self.assertTrue((proposal_dir / "proposal.md").is_file())
            self.assertTrue((proposal_dir / "proposal.html").is_file())
            self.assertTrue((proposal_dir / "proposal_reply.md").is_file())

            payload = json.loads((proposal_dir / "proposal.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["plan_name"], "Agency Lite")
            self.assertEqual(payload["price_monthly"], 79)
            self.assertEqual(payload["health_score"], 72)
            self.assertEqual(record.plan_id, "agency-lite")

            md = (proposal_dir / "proposal.md").read_text(encoding="utf-8")
            self.assertIn("Agency Lite", md)
            self.assertIn("79", md)
            self.assertIn("72", md)

    def test_md_only_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crm_path = root / "leads_crm.csv"
            proposals_dir = root / "proposals"
            pricing_path = Path(__file__).resolve().parent.parent / "data" / "pricing.example.json"
            lead = self._seed_lead(crm_path)
            config, _ = load_pricing_config(pricing_path)
            plan = get_plan(config, "starter")

            generate_proposal(
                lead=lead,
                plan=plan,
                currency=config.currency,
                output_dir=proposals_dir,
                project_root=root,
                output_format="md",
            )

            proposal_dir = proposals_dir / build_proposal_dir_name(lead)
            self.assertTrue((proposal_dir / "proposal.md").is_file())
            self.assertFalse((proposal_dir / "proposal.html").is_file())
            self.assertTrue((proposal_dir / "proposal_reply.md").is_file())

    def test_without_health_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crm_path = root / "leads_crm.csv"
            proposals_dir = root / "proposals"
            pricing_path = Path(__file__).resolve().parent.parent / "data" / "pricing.example.json"
            lead = self._seed_lead(crm_path, health_score=None, sample_report_path=None)
            config, _ = load_pricing_config(pricing_path)
            plan = get_plan(config, "starter")

            generate_proposal(
                lead=lead,
                plan=plan,
                currency=config.currency,
                output_dir=proposals_dir,
                project_root=root,
                output_format="both",
            )

            md = (proposals_dir / build_proposal_dir_name(lead) / "proposal.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("n/a", md)
            self.assertIn("not attached", md)

    def test_crm_proposal_path_updated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crm_path = root / "leads_crm.csv"
            lead = self._seed_lead(crm_path)
            attach_proposal_to_lead(
                crm_path,
                lead.lead_id,
                proposal_path="proposals/lead_0001_demo-studio-example-com",
            )
            rows = load_leads(crm_path)
            self.assertEqual(rows[0].proposal_path, "proposals/lead_0001_demo-studio-example-com")


class TestCrmMigration(unittest.TestCase):
    def test_old_csv_gets_proposal_path_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leads_crm.csv"
            old_columns = [c for c in CRM_CSV_COLUMNS if c != "proposal_path"]
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=old_columns)
                writer.writeheader()
                writer.writerow(
                    {
                        "lead_id": "lead_0001",
                        "client_name": "Demo",
                        "client_email": "",
                        "url": "https://example.com",
                        "normalized_domain": "example.com",
                        "source": "",
                        "status": "new",
                        "created_at": utc_now_iso(),
                        "last_contacted_at": "",
                        "next_followup_at": "",
                        "sample_report_path": "",
                        "health_score": "",
                        "health_label": "",
                        "notes": "",
                        "tags": "",
                    }
                )

            load_leads(path)
            with path.open(encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                self.assertIn("proposal_path", reader.fieldnames or [])


class TestGitignoreProposals(unittest.TestCase):
    def test_gitignore_contains_proposals(self) -> None:
        content = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(
            encoding="utf-8"
        )
        self.assertIn("proposals/*", content)
        self.assertIn("!proposals/.gitkeep", content)


class TestCliCompatibility(unittest.TestCase):
    def test_proposal_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.proposal", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("list-plans", result.stdout)

    def test_crm_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.crm", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)

    def test_onboard_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.onboard", "--help"],
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
