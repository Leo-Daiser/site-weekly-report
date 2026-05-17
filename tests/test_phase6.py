import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from click.exceptions import Exit as ClickExit

from app.batch import load_clients_csv
from app.models import BatchRunResult, BrandingConfig, EmailRunResult, WeeklyJobConfig
from app.weekly import execute_weekly_run, load_weekly_job


class TestWeeklyJobFile(unittest.TestCase):
    def test_example_job_loads(self) -> None:
        root = Path(__file__).resolve().parent.parent
        job = load_weekly_job(root / "data" / "weekly_jobs.example.json")
        self.assertEqual(job.job_name, "default_weekly_reports")
        self.assertEqual(job.clients_csv, "data/clients.example.csv")
        self.assertFalse(job.send_email)
        self.assertTrue(job.create_outbox)


class TestWeeklyDryRun(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.clients = self.root / "clients.csv"
        self.clients.write_text(
            "client_name,client_email,url\n"
            "A,a@example.com,https://example.com\n"
            "B,b@example.com,https://example.org\n",
            encoding="utf-8",
        )
        self.job_path = self.root / "job.json"
        self.job_path.write_text(
            json.dumps(
                {
                    "job_name": "test_job",
                    "clients_csv": "clients.csv",
                    "output_dir": "reports",
                    "outbox_dir": "outbox",
                    "db_path": "data/db.sqlite",
                    "branding_file": None,
                    "format": "html",
                    "max_links": 5,
                    "timeout": 5,
                    "create_outbox": True,
                    "send_email": False,
                    "continue_on_error": True,
                    "limit": None,
                }
            ),
            encoding="utf-8",
        )
        self.run_logs = self.root / "run_logs"
        self.reports = self.root / "reports"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_dry_run_does_not_create_batch(self) -> None:
        job = load_weekly_job(self.job_path)
        job.clients_csv = str(self.clients.relative_to(self.root))
        log, log_path = execute_weekly_run(
            job,
            mode="dry-run",
            project_root=self.root,
            run_logs_dir=self.run_logs,
        )
        self.assertTrue(log.success)
        self.assertTrue(log_path.is_file())
        self.assertIsNone(log.batch_dir)
        self.assertEqual(log.total, 2)
        self.assertFalse(any(self.reports.glob("batch_*")))

    def test_dry_run_writes_run_log(self) -> None:
        job = load_weekly_job(self.job_path)
        job.clients_csv = str(self.clients)
        execute_weekly_run(
            job,
            mode="dry-run",
            project_root=self.root,
            run_logs_dir=self.run_logs,
        )
        logs = list(self.run_logs.glob("weekly_run_*.json"))
        self.assertEqual(len(logs), 1)
        payload = json.loads(logs[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["mode"], "dry-run")
        self.assertTrue(payload["success"])


class TestWeeklyGenerate(unittest.TestCase):
    def test_generate_creates_batch_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clients = root / "clients.csv"
            clients.write_text(
                "client_name,url\nX,https://example.com\n",
                encoding="utf-8",
            )
            job = WeeklyJobConfig(
                job_name="gen",
                clients_csv=str(clients),
                output_dir="reports",
                branding_file=None,
            )
            batch_dir = root / "reports" / "batch_test"
            batch_dir.mkdir(parents=True)
            mock_batch = BatchRunResult(
                batch_dir=batch_dir,
                summary_csv=batch_dir / "summary.csv",
                summary_html=batch_dir / "summary.html",
                total=1,
                successful=1,
                failed=0,
            )
            mock_batch.summary_csv.write_text("x", encoding="utf-8")
            mock_batch.summary_html.write_text("<html></html>", encoding="utf-8")

            with patch(
                "app.weekly.run_batch_from_clients_csv",
                return_value=mock_batch,
            ) as mocked:
                log, _ = execute_weekly_run(
                    job,
                    mode="generate",
                    project_root=root,
                    run_logs_dir=root / "run_logs",
                )
                mocked.assert_called_once()

            self.assertTrue(log.success)
            self.assertIsNotNone(log.batch_dir)
            self.assertIsNotNone(log.summary_csv)
            self.assertIsNone(log.outbox_dir)


class TestWeeklyOutbox(unittest.TestCase):
    def test_outbox_mode_creates_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clients = root / "clients.csv"
            clients.write_text(
                "client_name,client_email,url\n"
                "X,x@example.com,https://example.com\n",
                encoding="utf-8",
            )
            job = WeeklyJobConfig(
                job_name="outbox",
                clients_csv=str(clients),
                output_dir="reports",
                outbox_dir="outbox",
                branding_file=None,
            )
            batch_dir = root / "reports" / "batch_x"
            batch_dir.mkdir(parents=True)
            outbox_dir = root / "outbox" / "batch_x"
            outbox_dir.mkdir(parents=True)

            mock_batch = BatchRunResult(
                batch_dir=batch_dir,
                summary_csv=batch_dir / "summary.csv",
                summary_html=batch_dir / "summary.html",
                total=1,
                successful=1,
                failed=0,
            )
            mock_batch.summary_csv.write_text("a", encoding="utf-8")
            mock_batch.summary_html.write_text("b", encoding="utf-8")
            mock_email = EmailRunResult(
                outbox_dir=outbox_dir,
                emails_prepared=1,
            )

            with patch("app.weekly.run_batch_from_clients_csv", return_value=mock_batch):
                with patch(
                    "app.weekly.prepare_and_optionally_send_reports",
                    return_value=mock_email,
                ) as prep:
                    log, _ = execute_weekly_run(
                        job,
                        mode="outbox",
                        project_root=root,
                        run_logs_dir=root / "run_logs",
                    )
                    prep.assert_called_once()
                    self.assertTrue(prep.call_args.kwargs["dry_run"])

            self.assertEqual(log.emails_prepared, 1)
            self.assertEqual(log.emails_sent, 0)
            self.assertIsNotNone(log.outbox_dir)


class TestWeeklySend(unittest.TestCase):
    def test_send_without_smtp_fails_before_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clients = root / "clients.csv"
            clients.write_text(
                "client_name,client_email,url\nX,x@example.com,https://example.com\n",
                encoding="utf-8",
            )
            job = WeeklyJobConfig(
                job_name="send",
                clients_csv=str(clients),
                branding_file=None,
            )

            with patch("app.weekly.run_batch_from_clients_csv") as batch_mock:
                with self.assertRaises(ClickExit):
                    execute_weekly_run(
                        job,
                        mode="send",
                        project_root=root,
                        run_logs_dir=root / "run_logs",
                        smtp_overrides={},
                    )
                batch_mock.assert_not_called()

            logs = list((root / "run_logs").glob("weekly_run_*.json"))
            self.assertEqual(len(logs), 1)
            payload = json.loads(logs[0].read_text(encoding="utf-8"))
            self.assertFalse(payload["success"])
            self.assertIn("SMTP", payload["error"] or "")


class TestWeeklyRunLogOnError(unittest.TestCase):
    def test_missing_csv_writes_failed_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = WeeklyJobConfig(
                job_name="bad",
                clients_csv="missing.csv",
                branding_file=None,
            )
            with self.assertRaises(ClickExit):
                execute_weekly_run(
                    job,
                    mode="generate",
                    project_root=root,
                    run_logs_dir=root / "run_logs",
                )
            logs = list((root / "run_logs").glob("weekly_run_*.json"))
            self.assertEqual(len(logs), 1)
            payload = json.loads(logs[0].read_text(encoding="utf-8"))
            self.assertFalse(payload["success"])
            self.assertIsNotNone(payload["error"])


class TestGitignoreRunLogs(unittest.TestCase):
    def test_gitignore_contains_run_logs_rule(self) -> None:
        content = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(
            encoding="utf-8"
        )
        self.assertIn("run_logs/*", content)
        self.assertIn("!run_logs/.gitkeep", content)


class TestCliCompatibility(unittest.TestCase):
    def test_main_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.main", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--url", result.stdout)

    def test_batch_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.batch", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--clients", result.stdout)

    def test_send_reports_dry_run_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.send_reports", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--dry-run", result.stdout)

    def test_weekly_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.weekly", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--job-file", result.stdout)
        self.assertIn("--mode", result.stdout)


class TestLoadClientsForWeekly(unittest.TestCase):
    def test_limit_applies_to_row_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.csv"
            path.write_text(
                "client_name,url\nA,https://a.com\nB,https://b.com\nC,https://c.com\n",
                encoding="utf-8",
            )
            rows = load_clients_csv(path)
            limited = rows[:2]
            self.assertEqual(len(limited), 2)


if __name__ == "__main__":
    unittest.main()
