import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from app.backup import create_backup
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
from app.client_portal import (
    ClientSettingsRequest,
    approve_settings_request,
    clients_for_email,
    consume_magic_token,
    create_magic_link,
    create_settings_request,
    email_for_session,
    load_settings_requests,
    load_tokens,
    set_settings_request_status,
)
from app.crawler import extract_sitemap_urls, has_noindex
from app.demo_reports import generate_demo_reports
from app.models import SignupRecord, SubscriptionRecord
from app.signup_store import create_signup, load_signups
from app.signups import (
    approve_signup,
    reconcile_signup_payments,
    validate_signup_for_plan,
)


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
            self.assertIn("Business impact", problem)
            self.assertIn("Expected impact", problem)
            medium = (Path(tmp) / "medium_site_demo.html").read_text(encoding="utf-8")
            self.assertIn("One internal link became broken", medium)
            good = (Path(tmp) / "good_site_demo.html").read_text(encoding="utf-8")
            self.assertIn("No meaningful regressions", good)


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

    def test_validate_signup_for_plan_limits_site_count(self) -> None:
        root = Path(__file__).resolve().parent.parent
        signup = SignupRecord(
            signup_id="",
            agency_name="Demo Agency",
            billing_email="billing@example.com",
            report_recipient_email="reports@example.com",
            plan_id="starter",
            website_urls="example.com, https://second.example.com",
        )
        errors = validate_signup_for_plan(signup, root / "data/pricing.example.json")
        self.assertTrue(errors)
        self.assertIn("includes 1 site", errors[0])

    def test_old_signup_csv_loads_with_payment_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pending_signups.csv"
            path.write_text(
                "signup_id,agency_name,billing_email,report_recipient_email,plan_id,website_urls,brand_name,brand_color,logo_url,status,created_at,approved_at,notes\n"
                "signup_0001,Demo,billing@example.com,reports@example.com,starter,https://example.com,,#2563eb,,pending,,,\n",
                encoding="utf-8",
            )
            signup = load_signups(path)[0]
        self.assertEqual(signup.payment_status, "pending_payment")

    def test_reconcile_signup_payments_maps_by_email(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            signups_path = root / "pending_signups.csv"
            subscriptions_path = root / "subscriptions.csv"
            create_signup(
                signups_path,
                SignupRecord(
                    signup_id="",
                    agency_name="Demo Agency",
                    billing_email="billing@example.com",
                    report_recipient_email="reports@example.com",
                    plan_id="agency-lite",
                    website_urls="https://example.com",
                    status="pending_payment",
                ),
            )
            upsert_subscription(
                subscriptions_path,
                SubscriptionRecord(
                    customer_email="billing@example.com",
                    plan_id="agency-lite",
                    payment_status="active",
                ),
            )
            total, updated = reconcile_signup_payments(
                signups_path=signups_path,
                subscriptions_path=subscriptions_path,
            )
            signup = load_signups(signups_path)[0]
        self.assertEqual((total, updated), (1, 1))
        self.assertEqual(signup.status, "pending")
        self.assertEqual(signup.payment_status, "active")

    def test_approve_blocks_payment_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            signups_path = root / "pending_signups.csv"
            subscriptions_path = root / "subscriptions.csv"
            create_signup(
                signups_path,
                SignupRecord(
                    signup_id="",
                    agency_name="Demo Agency",
                    billing_email="billing@example.com",
                    report_recipient_email="reports@example.com",
                    plan_id="starter",
                    website_urls="https://example.com",
                    status="pending",
                ),
            )
            upsert_subscription(
                subscriptions_path,
                SubscriptionRecord(
                    customer_email="billing@example.com",
                    plan_id="starter",
                    payment_status="payment_failed",
                ),
            )
            signup = approve_signup(
                signup_id="signup_0001",
                signups_path=signups_path,
                crm_path=root / "leads_crm.csv",
                clients_csv=root / "clients.csv",
                pricing_file=Path(__file__).resolve().parent.parent / "data/pricing.example.json",
                packages_dir=root / "client_packages",
                template_dir=Path(__file__).resolve().parent.parent / "templates",
                project_root=Path(__file__).resolve().parent.parent,
                subscriptions_path=subscriptions_path,
                require_payment=True,
            )
        self.assertEqual(signup.status, "needs_review")
        self.assertFalse((root / "clients.csv").exists())

    def test_approve_paid_signup_creates_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_root = Path(__file__).resolve().parent.parent
            signups_path = root / "pending_signups.csv"
            subscriptions_path = root / "subscriptions.csv"
            create_signup(
                signups_path,
                SignupRecord(
                    signup_id="",
                    agency_name="Demo Agency",
                    billing_email="billing@example.com",
                    report_recipient_email="reports@example.com",
                    plan_id="starter",
                    website_urls="https://example.com",
                    status="pending",
                ),
            )
            upsert_subscription(
                subscriptions_path,
                SubscriptionRecord(
                    customer_email="billing@example.com",
                    plan_id="starter",
                    payment_status="active",
                ),
            )
            signup = approve_signup(
                signup_id="signup_0001",
                signups_path=signups_path,
                crm_path=root / "leads_crm.csv",
                clients_csv=root / "clients.csv",
                pricing_file=repo_root / "data/pricing.example.json",
                packages_dir=root / "client_packages",
                template_dir=repo_root / "templates",
                project_root=repo_root,
                subscriptions_path=subscriptions_path,
                require_payment=True,
            )
            self.assertEqual(signup.status, "approved")
            self.assertTrue((root / "clients.csv").is_file())

    def test_approve_blocks_plan_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            signups_path = root / "pending_signups.csv"
            subscriptions_path = root / "subscriptions.csv"
            create_signup(
                signups_path,
                SignupRecord(
                    signup_id="",
                    agency_name="Demo Agency",
                    billing_email="billing@example.com",
                    report_recipient_email="reports@example.com",
                    plan_id="agency",
                    website_urls="https://example.com",
                    status="pending",
                ),
            )
            upsert_subscription(
                subscriptions_path,
                SubscriptionRecord(
                    customer_email="billing@example.com",
                    plan_id="starter",
                    payment_status="active",
                ),
            )
            signup = approve_signup(
                signup_id="signup_0001",
                signups_path=signups_path,
                crm_path=root / "leads_crm.csv",
                clients_csv=root / "clients.csv",
                pricing_file=Path(__file__).resolve().parent.parent / "data/pricing.example.json",
                packages_dir=root / "client_packages",
                template_dir=Path(__file__).resolve().parent.parent / "templates",
                project_root=Path(__file__).resolve().parent.parent,
                subscriptions_path=subscriptions_path,
                require_payment=True,
            )
        self.assertEqual(signup.status, "needs_review")
        self.assertIn("Plan mismatch", signup.notes)


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
        self.assertIn("/", paths)
        self.assertIn("/signup", paths)
        self.assertIn("/signup/thanks/{signup_id}", paths)
        self.assertIn("/admin/login", paths)
        self.assertIn("/admin/signups/reconcile-payments", paths)
        self.assertIn("/admin/signups/{signup_id}/needs-review", paths)
        self.assertIn("/admin/signups/{signup_id}/reject", paths)
        self.assertIn("/client/login", paths)
        self.assertIn("/client/magic", paths)
        self.assertIn("/client", paths)
        self.assertIn("/client/reports", paths)
        self.assertIn("/client/sites", paths)
        self.assertIn("/client/settings", paths)
        self.assertIn("/client/billing", paths)
        self.assertIn("/admin/client-requests", paths)
        self.assertIn("/admin/client-requests/{request_id}/approve", paths)
        self.assertIn("/admin/client-requests/{request_id}/reject", paths)
        self.assertIn("/admin/clients/send-login-link", paths)
        self.assertIn("/admin/clients", paths)
        self.assertIn("/admin/clients/detail", paths)
        self.assertIn("/admin/clients/needs-review", paths)
        self.assertIn("/admin/clients/run-now", paths)
        self.assertIn("/admin/runs/detail", paths)

    def test_static_mounts_registered(self) -> None:
        names = {route.name for route in admin_fastapi_app.routes}
        self.assertIn("reports", names)
        self.assertIn("sales_pack", names)
        self.assertIn("client_packages", names)

    def test_public_landing_page_renders_signup_cta(self) -> None:
        from app.admin_app import public_landing_page

        response = public_landing_page()
        body = response.body.decode("utf-8")
        self.assertIn("WebReport Weekly", body)
        self.assertTrue("signup" in body or "buy.stripe.com" in body)

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

    def test_public_signup_submit_creates_payment_aware_signup(self) -> None:
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
                    "session_id": "cs_test_123",
                }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pending_signups.csv"
            with patch("app.admin_app.SIGNUPS_PATH", path):
                import asyncio

                response = asyncio.run(public_signup_submit(FakeRequest()))
                rows = load_signups(path)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(rows[0].status, "pending_payment")
        self.assertEqual(rows[0].stripe_checkout_session_id, "cs_test_123")
        self.assertEqual(rows[0].logo_url, "https://example.com/logo.png")

    def test_admin_reconcile_action_redirects(self) -> None:
        from app.admin_app import reconcile_signups_page

        class FakeRequest:
            query_params = {}
            headers = {}
            cookies = {}

        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.admin_app.SIGNUPS_PATH", Path(tmp) / "pending_signups.csv"), patch(
                "app.admin_app.SUBSCRIPTIONS_PATH", Path(tmp) / "subscriptions.csv"
            ):
                response = reconcile_signups_page(FakeRequest())
        self.assertEqual(response.status_code, 303)
        self.assertIn("Reconciled", response.headers["location"])

    def test_admin_reject_and_needs_review_actions_update_signup(self) -> None:
        from app.admin_app import needs_review_signup_page, reject_signup_page

        class FakeRequest:
            query_params = {}
            headers = {}
            cookies = {}

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pending_signups.csv"
            create_signup(
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
            with patch("app.admin_app.SIGNUPS_PATH", path):
                needs_review_signup_page(FakeRequest(), "signup_0001")
                self.assertEqual(load_signups(path)[0].status, "needs_review")
                reject_signup_page(FakeRequest(), "signup_0001")
                self.assertEqual(load_signups(path)[0].status, "rejected")

    def test_public_signup_rejects_too_many_sites_for_plan(self) -> None:
        from app.admin_app import public_signup_submit

        class FakeRequest:
            async def form(self):
                return {
                    "agency_name": "Demo Agency",
                    "billing_email": "billing@example.com",
                    "report_recipient_email": "reports@example.com",
                    "plan_id": "starter",
                    "website_urls": "https://example.com, https://second.example.com",
                }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pending_signups.csv"
            with patch("app.admin_app.SIGNUPS_PATH", path):
                import asyncio

                response = asyncio.run(public_signup_submit(FakeRequest()))
                rows = load_signups(path)
        self.assertEqual(response.status_code, 303)
        self.assertIn("status=error", response.headers["location"])
        self.assertEqual(rows, [])

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


class TestClientPortal(unittest.TestCase):
    def test_magic_link_hashes_token_and_creates_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sessions.csv"
            link, record = create_magic_link(
                sessions_path=path,
                email="Client@Example.com",
                base_url="https://reports.example.com",
                ttl_minutes=30,
            )
            self.assertIn("/client/magic?token=", link)
            raw_token = link.split("token=", 1)[1]
            self.assertNotIn(raw_token, path.read_text(encoding="utf-8"))
            self.assertEqual(record.email, "client@example.com")
            email, session = consume_magic_token(
                sessions_path=path,
                raw_token=raw_token,
                session_days=7,
            )
            self.assertEqual(email, "client@example.com")
            self.assertEqual(email_for_session(path, session), "client@example.com")
            with self.assertRaises(ValueError):
                consume_magic_token(sessions_path=path, raw_token=raw_token)
            self.assertEqual(len(load_tokens(path)), 2)

    def test_clients_for_email_only_returns_matching_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clients = root / "clients.csv"
            clients.write_text(
                "client_name,client_email,brand_name,url,brand_color,brand_logo,footer_text,format,max_links,timeout\n"
                "Client A,a@example.com,Brand A,https://a.example.com,#2563eb,,,html,5,8\n"
                "Client B,b@example.com,Brand B,https://b.example.com,#2563eb,,,html,5,8\n",
                encoding="utf-8",
            )
            rows = clients_for_email(
                email="a@example.com",
                clients_csv=clients,
                subscriptions_path=root / "subscriptions.csv",
                client_status_path=root / "client_status.csv",
                reports_dir=root / "reports",
                client_packages_dir=root / "client_packages",
                project_root=root,
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].url, "https://a.example.com")

    def test_settings_request_lifecycle_and_approve_updates_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requests_path = root / "client_settings_requests.csv"
            clients = root / "clients.csv"
            clients.write_text(
                "client_name,client_email,brand_name,url,brand_color,brand_logo,footer_text,format,max_links,timeout\n"
                "Client A,a@example.com,Old Brand,https://a.example.com,#2563eb,,,html,5,8\n",
                encoding="utf-8",
            )
            request = create_settings_request(
                requests_path,
                ClientSettingsRequest(
                    request_id="",
                    client_email="a@example.com",
                    url="https://a.example.com",
                    brand_name="New Brand",
                    brand_color="#147a68",
                    logo_url="https://a.example.com/logo.png",
                ),
            )
            self.assertEqual(request.request_id, "client_req_0001")
            self.assertEqual(load_settings_requests(requests_path)[0].status, "pending")
            approve_settings_request(requests_path, "client_req_0001", clients)
            content = clients.read_text(encoding="utf-8")
            self.assertIn("New Brand", content)
            self.assertIn("#147a68", content)
            self.assertEqual(load_settings_requests(requests_path)[0].status, "approved")

    def test_reject_settings_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "requests.csv"
            create_settings_request(
                path,
                ClientSettingsRequest(request_id="", client_email="a@example.com"),
            )
            request = set_settings_request_status(path, "client_req_0001", "rejected")
        self.assertEqual(request.status, "rejected")

    def test_client_login_route_creates_local_link(self) -> None:
        from app.admin_app import client_login_submit

        class FakeRequest:
            base_url = "http://localhost:8000/"
            cookies = {}
            query_params = {}
            headers = {}

            async def form(self):
                return {"email": "client@example.com"}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clients = root / "clients.csv"
            clients.write_text(
                "client_name,client_email,brand_name,url,brand_color,brand_logo,footer_text,format,max_links,timeout\n"
                "Client,client@example.com,Brand,https://example.com,#2563eb,,,html,5,8\n",
                encoding="utf-8",
            )
            with patch("app.admin_app.CLIENTS_CSV", clients), patch(
                "app.admin_app.CLIENT_PORTAL_SESSIONS_PATH", root / "sessions.csv"
            ), patch("app.admin_app.SUBSCRIPTIONS_PATH", root / "subscriptions.csv"), patch(
                "app.admin_app.CLIENT_STATUS_PATH", root / "client_status.csv"
            ), patch("app.admin_app.REPORTS_DIR", root / "reports"), patch(
                "app.admin_app.PACKAGES_DIR", root / "client_packages"
            ), patch.dict(os.environ, {}, clear=True):
                import asyncio

                response = asyncio.run(client_login_submit(FakeRequest()))
        self.assertEqual(response.status_code, 303)
        self.assertIn("link=", response.headers["location"])


class TestCliSmoke(unittest.TestCase):
    def test_admin_app_importable(self) -> None:
        import app.admin_app as admin_app

        self.assertEqual(admin_app.app.title, "WebReport Weekly Admin")

    def test_client_portal_importable(self) -> None:
        import app.client_portal as client_portal

        self.assertTrue(hasattr(client_portal, "create_magic_link"))


class TestOperatorBackup(unittest.TestCase):
    def test_create_backup_includes_operator_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            (data / "clients.csv").write_text("client_name,url\nA,https://example.com\n", encoding="utf-8")
            reports = root / "reports"
            reports.mkdir()
            (reports / "report.html").write_text("report", encoding="utf-8")
            archive = create_backup(
                project_root=root,
                output_dir=root / "backups",
                timestamp="2026-01-01_00-00-00",
            )
            with ZipFile(archive) as handle:
                names = set(handle.namelist())
        self.assertIn("data/clients.csv", names)
        self.assertIn("reports/report.html", names)


if __name__ == "__main__":
    unittest.main()
