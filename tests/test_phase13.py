import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.sales_assets import generate_sales_pack, load_sales_pack_config


class TestSalesPackConfig(unittest.TestCase):
    def test_load_example_config(self) -> None:
        path = Path(__file__).resolve().parent.parent / "data" / "sales_pack.example.json"
        config = load_sales_pack_config(path)
        self.assertEqual(config.product_name, "WebReport Weekly")
        self.assertEqual(len(config.plans), 3)
        self.assertEqual(config.plans[0].checkout_url, "")
        self.assertEqual(config.contact_email, "hello@webreportweekly.example")
        self.assertEqual(config.signup_url, "/signup")
        self.assertTrue(config.main_benefits)


class TestGenerateSalesPack(unittest.TestCase):
    def test_generates_all_markdown_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = Path(__file__).resolve().parent.parent / "data" / "sales_pack.example.json"
            template_dir = Path(__file__).resolve().parent.parent / "templates"
            config = load_sales_pack_config(config_path)
            pack_dir = generate_sales_pack(
                config,
                root / "sales_pack",
                template_dir=template_dir,
                output_format="md",
            )
            self.assertTrue(pack_dir.is_dir())
            expected = [
                "landing_copy.md",
                "pricing.md",
                "faq.md",
                "short_pitch.md",
                "outreach_messages.md",
                "objections.md",
                "demo_report_notes.md",
                "go_to_market_checklist.md",
                "sales_pack_index.md",
            ]
            for name in expected:
                path = pack_dir / name
                self.assertTrue(path.is_file(), f"missing {name}")

            landing = (pack_dir / "landing_copy.md").read_text(encoding="utf-8")
            self.assertIn("WebReport Weekly", landing)
            self.assertIn("Get a free sample report", landing)
            self.assertIn("recurring reporting service", landing)

            pricing = (pack_dir / "pricing.md").read_text(encoding="utf-8")
            self.assertIn("Agency Lite", pricing)
            self.assertIn("79", pricing)

            index = (pack_dir / "sales_pack_index.md").read_text(encoding="utf-8")
            self.assertIn("landing_copy.md", index)
            self.assertIn("Use order", index)

            checklist = (pack_dir / "go_to_market_checklist.md").read_text(encoding="utf-8")
            self.assertIn("First sales checklist", checklist)
            self.assertIn("20 targeted contacts", checklist)

    def test_html_format_creates_html_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(__file__).resolve().parent.parent / "data" / "sales_pack.example.json"
            template_dir = Path(__file__).resolve().parent.parent / "templates"
            config = load_sales_pack_config(config_path)
            pack_dir = generate_sales_pack(
                config,
                Path(tmp) / "sales_pack",
                template_dir=template_dir,
                output_format="both",
            )
            self.assertTrue((pack_dir / "landing_copy.html").is_file())
            self.assertTrue((pack_dir / "landing_page.html").is_file())
            html = (pack_dir / "landing_copy.html").read_text(encoding="utf-8")
            self.assertIn("<!DOCTYPE html>", html)
            site = (pack_dir / "landing_page.html").read_text(encoding="utf-8")
            self.assertIn("Choose a plan", site)
            self.assertIn("Agency Lite", site)
            self.assertIn("not another dashboard", site)
            self.assertIn("Client login", site)
            self.assertIn("FAQ", site)
            self.assertIn("/signup?plan=starter", site)
            self.assertIn("hello@webreportweekly.example", site)
            self.assertNotIn("hello@example.com", site)


class TestGitignoreSalesPack(unittest.TestCase):
    def test_gitignore_contains_sales_pack(self) -> None:
        content = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(
            encoding="utf-8"
        )
        self.assertIn("sales_pack/*", content)
        self.assertIn("!sales_pack/.gitkeep", content)


class TestCliCompatibility(unittest.TestCase):
    def test_sales_pack_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.sales_pack", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue(
            "generate" in result.stdout.lower() or "generate" in (result.stderr or "").lower()
        )

    def test_preflight_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.preflight", "--help"],
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

    def test_proposal_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.proposal", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)

    def test_client_portal_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.client_portal", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue("create-login-link" in result.stdout or "create-login-link" in (result.stderr or ""))


if __name__ == "__main__":
    unittest.main()
