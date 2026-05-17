import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.batch import (
    load_clients_csv,
    run_batch,
    write_summary_csv,
    write_summary_html,
)
from app.models import BrandingConfig, ReportRunResult
from app.models import PageFetchResult
from app.pipeline import compute_scan_ok, run_single_report


class TestLoadClientsCsv(unittest.TestCase):
    def test_reads_two_clients(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clients.csv"
            path.write_text(
                "client_name,brand_name,url,brand_color,brand_logo,footer_text,format,max_links,timeout\n"
                "Client A,Brand A,https://example.com,,,,,,\n"
                "Client B,Brand B,https://example.org,,,,pdf,5,8\n",
                encoding="utf-8",
            )
            rows = load_clients_csv(path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["client_name"], "Client A")
            self.assertEqual(rows[1]["format"], "pdf")


class TestBatchDefaults(unittest.TestCase):
    def test_empty_csv_format_uses_cli_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "clients.csv"
            csv_path.write_text(
                "client_name,brand_name,url,brand_color,brand_logo,footer_text,format,max_links,timeout\n"
                "Only Client,My Brand,https://example.com,,,,,,\n",
                encoding="utf-8",
            )
            out = root / "reports"
            db = root / "data" / "checks.sqlite"

            mock_result = ReportRunResult(
                url="https://example.com",
                normalized_domain="example.com",
                success=True,
                scan_ok=True,
                html_path=str(out / "batch_x" / "report.html"),
                status_code=200,
                client_name="Only Client",
                brand_name="My Brand",
            )

            with patch("app.batch.run_single_report", return_value=mock_result) as mocked:
                batch_dir, results = run_batch(
                    clients_path=csv_path,
                    output_dir=out,
                    db_path=db,
                    project_root=root,
                    default_format="both",
                    default_max_links=30,
                    default_timeout=10.0,
                    file_config=BrandingConfig(),
                )

            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(mocked.call_args.kwargs["output_format"], "both")
            self.assertTrue(results[0].success)
            self.assertTrue((batch_dir / "summary.csv").is_file())
            self.assertTrue((batch_dir / "summary.html").is_file())


class TestBatchContinueOnError(unittest.TestCase):
    def test_invalid_url_does_not_stop_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "clients.csv"
            csv_path.write_text(
                "client_name,brand_name,url,brand_color,brand_logo,footer_text,format,max_links,timeout\n"
                "Bad,,not-a-valid-url,,,,,,\n"
                "Good,Brand,https://example.com,,,,,,\n",
                encoding="utf-8",
            )

            ok_result = ReportRunResult(
                url="https://example.com",
                success=True,
                scan_ok=True,
                html_path="x.html",
                client_name="Good",
            )

            def side_effect(url: str, **kwargs: object) -> ReportRunResult:
                if "example.com" in url:
                    return ok_result
                return ReportRunResult(url=url, success=False, error="bad url")

            with patch("app.batch.run_single_report", side_effect=side_effect):
                _, results = run_batch(
                    clients_path=csv_path,
                    output_dir=root / "reports",
                    db_path=root / "db.sqlite",
                    project_root=root,
                    default_format="html",
                    default_max_links=5,
                    default_timeout=5.0,
                    file_config=BrandingConfig(),
                    continue_on_error=True,
                )

            self.assertEqual(len(results), 2)
            self.assertFalse(results[0].success)
            self.assertTrue(results[1].success)


class TestSummaryFiles(unittest.TestCase):
    def test_summary_csv_and_html_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            batch_dir = Path(tmp)
            results = [
                ReportRunResult(
                    url="https://example.com",
                    normalized_domain="example.com",
                    success=True,
                    scan_ok=True,
                    client_name="Client",
                    brand_name="Brand",
                    html_path=str(batch_dir / "a.html"),
                    warnings_count=2,
                ),
                ReportRunResult(
                    url="bad",
                    success=False,
                    error="failed",
                    client_name="Bad",
                ),
            ]
            csv_path = batch_dir / "summary.csv"
            html_path = batch_dir / "summary.html"
            write_summary_csv(csv_path, results, batch_dir)
            write_summary_html(html_path, results, batch_dir)

            with csv_path.open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1]["success"], "false")
            self.assertIn("scan_ok", rows[0])

            html = html_path.read_text(encoding="utf-8")
            self.assertIn("Client", html)
            self.assertIn("FAILED", html)
            self.assertIn("a.html", html)


class TestScanOk(unittest.TestCase):
    def test_scan_ok_false_when_page_error(self) -> None:
        page = PageFetchResult(source_url="https://x.com", error="timeout")
        self.assertFalse(compute_scan_ok(page))

    def test_scan_ok_false_when_status_500(self) -> None:
        page = PageFetchResult(source_url="https://x.com", status_code=500)
        self.assertFalse(compute_scan_ok(page))


class TestPipelineImport(unittest.TestCase):
    def test_run_single_report_returns_failed_result_for_bad_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_single_report(
                url="",
                max_links=5,
                timeout=5.0,
                output_dir=root / "out",
                db_path=root / "db.sqlite",
                branding=BrandingConfig(),
                output_format="html",
                project_root=root,
            )
            self.assertFalse(result.success)
            self.assertIsNotNone(result.error)


class TestMainStillImports(unittest.TestCase):
    def test_main_module_importable(self) -> None:
        from app import main

        self.assertTrue(callable(main.main))


if __name__ == "__main__":
    unittest.main()
