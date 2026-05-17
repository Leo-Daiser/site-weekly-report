import csv
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.email_sender import send_email_with_attachments
from app.models import EmailManifestEntry, SMTPConfig
from app.outbox import (
    build_client_email_lookup,
    create_outbox_for_batch,
    read_manifest,
    write_manifest,
)
from app.send_reports import send_prepared_emails


class TestOutbox(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.batch_dir = self.root / "reports" / "batch_test"
        self.batch_dir.mkdir(parents=True)
        self.clients_csv = self.root / "clients.csv"
        self.clients_csv.write_text(
            "client_name,client_email,brand_name,url,brand_color,brand_logo,footer_text,format,max_links,timeout\n"
            "Client A,alice@example.com,Brand A,https://example.com,,,,,,\n"
            "Client B,,Brand B,https://other.com,,,,,,\n",
            encoding="utf-8",
        )
        report_html = self.batch_dir / "example_com_2026.html"
        report_html.write_text("<html><body>report</body></html>", encoding="utf-8")
        report_other = self.batch_dir / "other_com_2026.html"
        report_other.write_text("<html><body>other</body></html>", encoding="utf-8")
        summary_path = self.batch_dir / "summary.csv"
        with summary_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "client_name",
                    "brand_name",
                    "url",
                    "normalized_domain",
                    "success",
                    "scan_ok",
                    "error",
                    "status_code",
                    "warnings_count",
                    "broken_links_count",
                    "changes_count",
                    "previous_check_found",
                    "html_path",
                    "pdf_path",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "client_name": "Client A",
                    "brand_name": "Brand A",
                    "url": "https://example.com",
                    "normalized_domain": "example.com",
                    "success": "true",
                    "scan_ok": "true",
                    "error": "",
                    "status_code": "200",
                    "warnings_count": "3",
                    "broken_links_count": "0",
                    "changes_count": "1",
                    "previous_check_found": "false",
                    "html_path": "example_com_2026.html",
                    "pdf_path": "",
                }
            )
            writer.writerow(
                {
                    "client_name": "Client B",
                    "brand_name": "Brand B",
                    "url": "https://other.com",
                    "normalized_domain": "other.com",
                    "success": "true",
                    "scan_ok": "true",
                    "error": "",
                    "status_code": "200",
                    "warnings_count": "1",
                    "broken_links_count": "0",
                    "changes_count": "0",
                    "previous_check_found": "false",
                    "html_path": "other_com_2026.html",
                    "pdf_path": "",
                }
            )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_creates_outbox_manifest_and_emails(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        result = create_outbox_for_batch(
            batch_dir=self.batch_dir,
            clients_csv=self.clients_csv,
            outbox_dir=self.root / "outbox",
            project_root=project_root,
        )
        self.assertTrue(result.manifest_path.is_file())
        self.assertTrue((result.outbox_dir / "emails" / "example_com.txt").is_file())
        self.assertTrue((result.outbox_dir / "emails" / "example_com.html").is_file())
        self.assertEqual(result.prepared_count, 1)
        self.assertEqual(result.skipped_count, 1)
        self.assertTrue(any("client_email" in w for w in result.warnings))

    def test_missing_email_skipped_without_crash(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        result = create_outbox_for_batch(
            batch_dir=self.batch_dir,
            clients_csv=self.clients_csv,
            outbox_dir=self.root / "outbox2",
            project_root=project_root,
        )
        entries = read_manifest(result.manifest_path)
        skipped = [e for e in entries if e.status == "skipped"]
        self.assertGreaterEqual(len(skipped), 1)


class TestEmailSender(unittest.TestCase):
    def test_builds_message_with_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.pdf"
            report.write_bytes(b"%PDF-1.4 test")
            captured: dict[str, EmailMessage] = {}

            def fake_send(message: EmailMessage) -> None:
                captured["msg"] = message

            smtp = SMTPConfig(
                host="smtp.test",
                port=587,
                from_email="reports@test.com",
                username="user",
                password="pass",
            )
            with patch("app.email_sender.smtplib.SMTP") as mock_smtp:
                instance = MagicMock()
                mock_smtp.return_value.__enter__.return_value = instance
                instance.send_message.side_effect = fake_send
                send_email_with_attachments(
                    to_email="client@example.com",
                    subject="Test",
                    text_body="Hello",
                    html_body="<p>Hello</p>",
                    attachments=[report],
                    smtp_config=smtp,
                )
            message = captured["msg"]
            self.assertEqual(message["To"], "client@example.com")
            filenames = [
                part.get_filename()
                for part in message.iter_attachments()
            ]
            self.assertIn("report.pdf", filenames)


class TestSendPreparedEmails(unittest.TestCase):
    def test_dry_run_flag_parsed(self) -> None:
        from app.send_reports import _parse_dry_run

        self.assertTrue(_parse_dry_run(True))
        self.assertFalse(_parse_dry_run(False))

    def test_send_prepared_calls_smtp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch_dir = root / "batch"
            batch_dir.mkdir()
            outbox_dir = root / "outbox" / "batch"
            emails = outbox_dir / "emails"
            emails.mkdir(parents=True)
            (emails / "a.txt").write_text("text", encoding="utf-8")
            (emails / "a.html").write_text("<p>x</p>", encoding="utf-8")
            report = batch_dir / "r.html"
            report.write_text("<html></html>", encoding="utf-8")
            entry = EmailManifestEntry(
                client_name="A",
                client_email="a@test.com",
                url="https://x.com",
                subject="Subj",
                text_path="emails/a.txt",
                html_path="emails/a.html",
                report_html_path="r.html",
                status="prepared",
            )
            write_manifest(outbox_dir / "manifest.csv", [entry])
            with patch("app.send_reports.send_email_with_attachments") as mocked:
                sent, failed = send_prepared_emails(
                    batch_dir=batch_dir,
                    outbox_dir=outbox_dir,
                    smtp_overrides={
                        "host": "smtp.test",
                        "from_email": "r@test.com",
                    },
                    limit=10,
                )
                mocked.assert_called_once()
            self.assertEqual(sent, 1)
            self.assertEqual(failed, 0)
            updated = read_manifest(outbox_dir / "manifest.csv")
            self.assertEqual(updated[0].status, "sent")

    def test_send_failure_updates_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch_dir = root / "batch"
            batch_dir.mkdir()
            outbox_dir = root / "outbox" / "batch"
            emails = outbox_dir / "emails"
            emails.mkdir(parents=True)
            (emails / "a.txt").write_text("text", encoding="utf-8")
            report = batch_dir / "r.html"
            report.write_text("<html></html>", encoding="utf-8")
            entry = EmailManifestEntry(
                client_name="A",
                client_email="a@test.com",
                url="https://x.com",
                subject="Subj",
                text_path="emails/a.txt",
                html_path="",
                report_html_path="r.html",
                status="prepared",
            )
            write_manifest(outbox_dir / "manifest.csv", [entry])
            with patch(
                "app.send_reports.send_email_with_attachments",
                side_effect=RuntimeError("smtp down"),
            ):
                sent, failed = send_prepared_emails(
                    batch_dir=batch_dir,
                    outbox_dir=outbox_dir,
                    smtp_overrides={
                        "host": "smtp.test",
                        "from_email": "r@test.com",
                    },
                )
            self.assertEqual(sent, 0)
            self.assertEqual(failed, 1)
            updated = read_manifest(outbox_dir / "manifest.csv")
            self.assertEqual(updated[0].status, "failed")
            self.assertIn("smtp down", updated[0].error)


class TestGitignore(unittest.TestCase):
    def test_gitignore_contains_outbox_rule(self) -> None:
        content = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(
            encoding="utf-8"
        )
        self.assertIn("outbox/*", content)
        self.assertIn("!outbox/.gitkeep", content)


class TestClientEmailLookup(unittest.TestCase):
    def test_lookup_by_client_and_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.csv"
            path.write_text(
                "client_name,client_email,brand_name,url\n"
                "X,x@example.com,B,https://site.com\n",
                encoding="utf-8",
            )
            lookup = build_client_email_lookup(path)
            self.assertEqual(lookup[("x", "https://site.com")], "x@example.com")


if __name__ == "__main__":
    unittest.main()
