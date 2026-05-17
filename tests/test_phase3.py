import json
import tempfile
import unittest
from pathlib import Path

from app.branding import (
    DEFAULT_BRAND_COLOR,
    load_branding_config,
    merge_branding_config,
    prepare_logo_data_uri,
    resolve_branding,
    validate_brand_color,
)
from app.models import BrandingConfig, PageFetchResult, SiteReport
from app.pdf_exporter import CHROMIUM_INSTALL_HINT, PDF_INSTALL_CHROMIUM, export_html_to_pdf
from app.report_builder import render_report


class TestBrandColor(unittest.TestCase):
    def test_accepts_valid_hex(self) -> None:
        self.assertEqual(validate_brand_color("#2563eb"), "#2563eb")

    def test_replaces_invalid_with_default(self) -> None:
        warnings: list[str] = []
        result = validate_brand_color("red", warnings)
        self.assertEqual(result, DEFAULT_BRAND_COLOR)
        self.assertEqual(len(warnings), 1)


class TestBrandingConfig(unittest.TestCase):
    def test_load_branding_config_reads_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "brand.json"
            path.write_text(
                json.dumps(
                    {
                        "brand_name": "From File",
                        "brand_color": "#ff0000",
                    }
                ),
                encoding="utf-8",
            )
            config = load_branding_config(str(path))
            self.assertEqual(config.brand_name, "From File")
            self.assertEqual(config.brand_color, "#ff0000")

    def test_cli_overrides_have_priority(self) -> None:
        file_config = BrandingConfig(brand_name="From File", brand_color="#ff0000")
        merged = merge_branding_config(
            file_config,
            {"brand_name": "From CLI", "client_name": "Client"},
        )
        self.assertEqual(merged.brand_name, "From CLI")
        self.assertEqual(merged.client_name, "Client")
        self.assertEqual(merged.brand_color, "#ff0000")

    def test_webp_logo_shows_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logo = Path(tmp) / "logo.webp"
            logo.write_bytes(b"fake")
            _, warnings = prepare_logo_data_uri(str(logo))
            self.assertTrue(any("Unsupported logo format" in w for w in warnings))

    def test_missing_logo_does_not_crash(self) -> None:
        config, warnings = resolve_branding(
            BrandingConfig(logo_path="assets/missing.png"),
            {},
            Path("."),
        )
        self.assertIsNone(config.logo_path)
        self.assertTrue(any("not found" in w.lower() for w in warnings))


class TestReportBranding(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.template_dir = Path(__file__).resolve().parent.parent / "templates"
        self.report = SiteReport(
            source_url="https://example.com",
            page=PageFetchResult(source_url="https://example.com", status_code=200),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _render(self, branding: BrandingConfig) -> str:
        out = self.root / "test.html"
        _, _warnings = render_report(self.report, self.template_dir, out, branding)
        return out.read_text(encoding="utf-8")

    def test_includes_brand_name(self) -> None:
        html = self._render(BrandingConfig(brand_name="SEO Studio"))
        self.assertIn("SEO Studio", html)

    def test_includes_client_name(self) -> None:
        html = self._render(
            BrandingConfig(brand_name="SEO Studio", client_name="Client Company")
        )
        self.assertIn("Client Company", html)

    def test_works_without_logo(self) -> None:
        html = self._render(BrandingConfig(brand_name="SEO Studio", logo_path=None))
        self.assertIn("SEO Studio", html)
        self.assertNotIn('alt="SEO Studio logo"', html)


class TestPdfExporter(unittest.TestCase):
    def test_export_function_importable(self) -> None:
        self.assertTrue(callable(export_html_to_pdf))

    def test_chromium_hint_message(self) -> None:
        self.assertIn("playwright install chromium", CHROMIUM_INSTALL_HINT)
        self.assertIn("playwright install chromium", PDF_INSTALL_CHROMIUM)


if __name__ == "__main__":
    unittest.main()
