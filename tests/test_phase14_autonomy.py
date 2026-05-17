import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.admin_clients import (
    build_admin_client_rows,
    client_package_for,
    latest_report_for_url,
)
from app.admin_app import app as admin_fastapi_app
from app.admin_views import render_clients_page, render_run_detail
from app.billing import apply_stripe_event
from app.billing_store import upsert_subscription
from app.billing_store import load_subscriptions
from app.client_status_store import paused_client_keys, set_client_status
from app.crawler import extract_sitemap_urls, has_noindex
from app.demo_reports import generate_demo_reports
from app.models import SignupRecord, SubscriptionRecord
from app.signup_store import create_signup, load_signups


class TestCrawlerQuality(unittest.TestCase):
    def test_extract_sitemap_urls_same_domain(self) -> None:
        xml = """<urlset><url><loc>https://example.com/a</loc></url><url><loc>https://other.com/b</loc></url></urlset>"""
        self.assertEqual(extract_sitemap_urls(xml, "https://example.com", 10), ["https://example.com/a"])

    def test_has_noindex(self) -> None:
        html = '<html><head><meta name="robots" content="noindex,follow"></head></html>'
        self.assertTrue(has_noindex(html))


class TestDemoReports(unittest.TestCase):
    def test_generates_three_demo_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(__file__).resolve().parent.parent
            written = generate_demo_reports(Path(tmp), root / "templates")
            self.assertEqual(len(written), 3)
            self.assertTrue((Path(tmp) / "problem_site_demo.html").is_file())
            problem = (Path(tmp) / "problem_site_demo.html").read_text(encoding="utf-8")
            self.assertIn("Site Health Score", problem)
            self.assertIn("Technical checks", problem)


class TestBillingEvents(unittest.TestCase):
    def test_checkout_completed_creates_active_subscription(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subscriptions.csv"
            event = {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "customer": "cus_123",
                        "subscription": "sub_123",
                        "customer_email": "client@example.com",
                        "metadata": {"plan_id": "agency-lite"},
                    }
                },
            }
            record = apply_stripe_event(event, path)
            self.assertIsNotNone(record)
            records = load_subscriptions(path)
            self.assertEqual(records[0].payment_status, "active")
            self.assertEqual(records[0].plan_id, "agency-lite")

    def test_payment_failed_updates_subscription(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subscriptions.csv"
            apply_stripe_event(
                {
                    "type": "checkout.session.completed",
                    "data": {"object": {"subscription": "sub_123", "customer_email": "client@example.com"}},
                },
                path,
            )
            apply_stripe_event(
                {"type": "invoice.payment_failed", "data": {"object": {"subscription": "sub_123"}}},
                path,
            )
            self.assertEqual(load_subscriptions(path)[0].payment_status, "payment_failed")


class TestSignupStore(unittest.TestCase):
    def test_create_signup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pending_signups.csv"
            signup = create_signup(
                path,
                SignupRecord(
                    signup_id="",
                    agency_name="Demo Agency",
                    billing_email="billing@example.com",
                    report_recipient_email="reports@example.com",
                    plan_id="starter",
                    website_urls="https://example.com",
                ),
            )
            self.assertEqual(signup.signup_id, "signup_0001")
            self.assertEqual(load_signups(path)[0].status, "pending")


class TestClientStatus(unittest.TestCase):
    def test_pause_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "client_status.csv"
            set_client_status(
                path,
                client_email="client@example.com",
                url="https://example.com",
                status="paused",
                reason="test",
            )
            self.assertIn(("client@example.com", "https://example.com"), paused_client_keys(path))


class TestAdminClientDashboard(unittest.TestCase):
    def test_merges_clients_with_subscription_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clients = root / "clients.csv"
            clients.write_text(
                "client_name,client_email,brand_name,url,brand_color,brand_logo,footer_text,format,max_links,timeout\n"
                "Client A,client@example.com,Brand A,https://example.com,#2563eb,,,html,5,8\n",
                encoding="utf-8",
            )
            subscriptions = root / "subscriptions.csv"
            upsert_subscription(
                subscriptions,
                SubscriptionRecord(
                    customer_email="client@example.com",
                    plan_id="agency-lite",
                    payment_status="active",
                ),
            )
            status = root / "client_status.csv"
            set_client_status(
                status,
                client_email="client@example.com",
                url="https://example.com",
                status="paused",
            )
            rows = build_admin_client_rows(
                clients_csv=clients,
                subscriptions_path=subscriptions,
                client_status_path=status,
                reports_dir=root / "reports",
                client_packages_dir=root / "client_packages",
                project_root=root,
            )
            self.assertEqual(rows[0].plan_id, "agency-lite")
            self.assertEqual(rows[0].payment_status, "active")
            self.assertEqual(rows[0].operational_status, "paused")

    def test_latest_report_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp) / "reports"
            reports.mkdir()
            old = reports / "example_com_2026-01-01_00-00-00.html"
            new = reports / "example_com_2026-01-02_00-00-00.html"
            old.write_text("old", encoding="utf-8")
            new.write_text("new", encoding="utf-8")
            self.assertEqual(latest_report_for_url(reports, "https://example.com"), new)

    def test_client_package_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "demo-client-example-com"
            package.mkdir()
            self.assertEqual(client_package_for(root, "Demo Client", "https://example.com"), package)

    def test_admin_client_routes_registered(self) -> None:
        paths = {route.path for route in admin_fastapi_app.routes}
        self.assertIn("/signup", paths)
        self.assertIn("/signup/thanks/{signup_id}", paths)
        self.assertIn("/admin/login", paths)
        self.assertIn("/admin/clients", paths)
        self.assertIn("/admin/clients/detail", paths)
        self.assertIn("/admin/clients/needs-review", paths)
        self.assertIn("/admin/clients/run-now", paths)
        self.assertIn("/admin/runs/detail", paths)

    def test_admin_run_now_route_uses_runner(self) -> None:
        from app.admin_app import run_client_now_page

        class FakeRequest:
            async def form(self):
                return {"client_email": "client@example.com", "url": "https://example.com"}

        with patch("app.admin_app.run_admin_single_client_report") as runner:
            import asyncio

            response = asyncio.run(run_client_now_page(FakeRequest()))
        self.assertEqual(response.status_code, 303)
        runner.assert_called_once()

    def test_admin_clients_page_escapes_user_values(self) -> None:
        rows = build_admin_client_rows(
            clients_csv=Path(__file__).resolve().parent.parent / "data/clients.example.csv",
            subscriptions_path=Path("__missing__.csv"),
            client_status_path=Path("__missing_status__.csv"),
            reports_dir=Path("__missing_reports__"),
            client_packages_dir=Path("__missing_packages__"),
            project_root=Path(__file__).resolve().parent.parent,
        )
        rows[0].client_name = "<script>alert(1)</script>"
        html = render_clients_page(rows)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_run_detail_escapes_payload_and_links(self) -> None:
        html = render_run_detail(
            "run.json",
            {"success": False, "error": "<b>bad</b>", "html_path": "reports/demo.html"},
        )
        self.assertNotIn("<b>bad</b>", html)
        self.assertIn("&lt;b&gt;bad&lt;/b&gt;", html)
        self.assertIn("/reports/demo.html", html)

    def test_public_signup_submit_creates_pending_signup(self) -> None:
        from app.admin_app import public_signup_submit

        class FakeRequest:
            async def form(self):
                return {
                    "agency_name": "Demo Agency",
                    "billing_email": "billing@example.com",
                    "report_recipient_email": "reports@example.com",
                    "plan_id": "agency-lite",
                    "website_urls": "https://example.com",
                    "brand_name": "Demo Brand",
                    "brand_color": "#123456",
                    "logo_url": "https://example.com/logo.png",
                }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pending_signups.csv"
            with patch("app.admin_app.SIGNUPS_PATH", path):
                import asyncio

                response = asyncio.run(public_signup_submit(FakeRequest()))
                rows = load_signups(path)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(rows[0].status, "pending")
        self.assertEqual(rows[0].logo_url, "https://example.com/logo.png")

    def test_admin_cookie_auth_allows_request(self) -> None:
        from app.admin_app import _check_admin

        class FakeRequest:
            query_params = {}
            headers = {}
            cookies = {"admin_session": "secret"}

        with patch.dict(os.environ, {"ADMIN_PASSWORD": "secret"}, clear=True):
            _check_admin(FakeRequest())

    def test_form_reader_falls_back_without_python_multipart(self) -> None:
        from app.admin_app import _read_form

        class FakeRequest:
            async def form(self):
                raise AssertionError("The `python-multipart` library must be installed to use form parsing.")

            async def body(self):
                return b"agency_name=Demo+Agency&plan_id=agency-lite"

        import asyncio

        form = asyncio.run(_read_form(FakeRequest()))
        self.assertEqual(form["agency_name"], "Demo Agency")
        self.assertEqual(form["plan_id"], "agency-lite")


class TestCliSmoke(unittest.TestCase):
    def test_admin_app_importable(self) -> None:
        import app.admin_app as admin_app

        self.assertEqual(admin_app.app.title, "WebReport Weekly Admin")


if __name__ == "__main__":
    unittest.main()
