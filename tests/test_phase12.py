import csv
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import PreflightCheckResult, PreflightReport
from app.preflight import write_markdown_report
from app.preflight_checks import (
    GITIGNORE_REQUIRED_PATTERNS,
    PreflightContext,
    check_clients_csv,
    check_gitignore,
    check_operator_config,
    check_playwright_pdf,
    check_project_structure,
    check_smtp_config,
    compute_ready,
    run_preflight_checks,
    summarize_report,
)


class TestPreflightModels(unittest.TestCase):
    def test_check_result_creation(self) -> None:
        item = PreflightCheckResult(
            name="Test",
            status="pass",
            message="OK",
        )
        self.assertEqual(item.status, "pass")

    def test_ready_false_on_fail(self) -> None:
        results = [
            PreflightCheckResult(name="A", status="pass", message="ok"),
            PreflightCheckResult(name="B", status="fail", message="bad"),
        ]
        self.assertFalse(compute_ready(results, strict=False))

    def test_ready_false_on_warning_when_strict(self) -> None:
        results = [
            PreflightCheckResult(name="A", status="warning", message="warn"),
        ]
        self.assertFalse(compute_ready(results, strict=True))
        self.assertTrue(compute_ready(results, strict=False))


class TestPreflightChecks(unittest.TestCase):
    def _ctx(self, tmp: str, **kwargs: object) -> PreflightContext:
        root = Path(__file__).resolve().parent.parent
        clients = root / "data/clients.example.csv"
        return PreflightContext(
            project_root=root,
            clients_csv=kwargs.get("clients_csv", clients),  # type: ignore[arg-type]
            weekly_job_file=root / "data/weekly_jobs.example.json",
            pricing_file=root / "data/pricing.example.json",
            crm_path=root / "data/leads_crm.csv",
            branding_file=root / "branding/default.json",
            check_smtp=bool(kwargs.get("check_smtp", False)),
            check_pdf=bool(kwargs.get("check_pdf", False)),
            run_smoke_tests=bool(kwargs.get("run_smoke_tests", True)),
            strict=bool(kwargs.get("strict", False)),
            is_example_clients=bool(kwargs.get("is_example_clients", True)),
        )

    def test_project_structure_passes(self) -> None:
        result = check_project_structure(self._ctx(""))
        self.assertEqual(result.status, "pass")

    def test_gitignore_patterns(self) -> None:
        result = check_gitignore(self._ctx(""))
        self.assertIn(result.status, ("pass", "fail"))
        content = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(
            encoding="utf-8"
        )
        for pattern in GITIGNORE_REQUIRED_PATTERNS:
            self.assertIn(pattern, content)

    def test_clients_csv_missing_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clients.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["client_name", "url"])
                writer.writeheader()
                writer.writerow({"client_name": "A", "url": "https://example.com"})
            ctx = self._ctx(tmp, clients_csv=path, is_example_clients=False)
            result = check_clients_csv(ctx)
            self.assertEqual(result.status, "fail")

    def test_weekly_and_pricing_via_full_run(self) -> None:
        report = run_preflight_checks(self._ctx(""))
        names = {item.name for item in report.results}
        self.assertIn("Weekly job", names)
        self.assertIn("Pricing", names)
        self.assertIn("Operator config", names)
        weekly = next(r for r in report.results if r.name == "Weekly job")
        pricing = next(r for r in report.results if r.name == "Pricing")
        self.assertIn(weekly.status, ("pass", "warning"))
        self.assertEqual(pricing.status, "pass")

    def test_operator_config_warns_without_env(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = check_operator_config(self._ctx(""))
        self.assertEqual(result.status, "warning")
        self.assertIn("ADMIN_PASSWORD", result.details or "")

    def test_smtp_skipped_by_default(self) -> None:
        result = check_smtp_config(self._ctx("", check_smtp=False))
        self.assertEqual(result.status, "skipped")

    def test_smtp_fail_when_enabled_and_empty(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = check_smtp_config(self._ctx("", check_smtp=True))
        self.assertEqual(result.status, "fail")

    def test_playwright_skipped_by_default(self) -> None:
        result = check_playwright_pdf(self._ctx("", check_pdf=False))
        self.assertEqual(result.status, "skipped")

    def test_markdown_report_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "preflight_reports"
            template_dir = Path(__file__).resolve().parent.parent / "templates"
            report = summarize_report(
                [
                    PreflightCheckResult(
                        name="Test", status="pass", message="OK"
                    )
                ],
                started_at="2026-01-01T00:00:00+00:00",
                finished_at="2026-01-01T00:00:01+00:00",
                strict=False,
            )
            path = write_markdown_report(
                report, output_dir=out, template_dir=template_dir
            )
            self.assertTrue(path.is_file())
            content = path.read_text(encoding="utf-8")
            self.assertIn("# Preflight report", content)
            self.assertIn("Test", content)


class TestCliCompatibility(unittest.TestCase):
    def test_preflight_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.preflight", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--check-pdf", result.stdout)

    def test_main_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.main", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)

    def test_convert_client_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.convert_client", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)


class TestGitignorePreflight(unittest.TestCase):
    def test_gitignore_contains_preflight_reports(self) -> None:
        content = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(
            encoding="utf-8"
        )
        self.assertIn("preflight_reports/*", content)
        self.assertIn("!preflight_reports/.gitkeep", content)


if __name__ == "__main__":
    unittest.main()
