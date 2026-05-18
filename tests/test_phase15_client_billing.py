from __future__ import annotations

import asyncio
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.admin_clients import build_admin_client_rows
from app.billing_store import load_subscriptions, upsert_subscription
from app.client_analytics import build_client_dashboard_analytics
from app.client_portal import (
    ClientBillingRequest,
    approve_billing_request,
    billing_requests_for_email,
    create_billing_request,
    reject_billing_request,
)
from app.client_views import render_client_billing, render_client_dashboard
from app.models import SubscriptionRecord
from app.pricing import load_pricing_config, list_plans


class TestClientAnalyticsAndBilling(unittest.TestCase):
    def _write_clients(self, path: Path) -> None:
        path.write_text(
            "client_name,client_email,brand_name,url,brand_color,brand_logo,footer_text,format,max_links,timeout,max_pages,screenshot\n"
            "Client A,a@example.com,Brand A,https://a.example.com,#2563eb,,,html,5,8,7,true\n"
            "Client B,b@example.com,Brand B,https://b.example.com,#2563eb,,,html,5,8,10,false\n",
            encoding="utf-8",
        )

    def _write_summary(self, path: Path, *, score: str, warnings: str, domain: str = "a.example.com") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "client_name",
                    "brand_name",
                    "url",
                    "normalized_domain",
                    "success",
                    "error",
                    "warnings_count",
                    "broken_links_count",
                    "health_score",
                    "health_label",
                    "top_actions",
                    "pages_checked_count",
                    "broken_assets_count",
                    "html_path",
                    "pdf_path",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "client_name": "Client A",
                    "brand_name": "Brand A",
                    "url": "https://a.example.com",
                    "normalized_domain": domain,
                    "success": "true",
                    "error": "",
                    "warnings_count": warnings,
                    "broken_links_count": "1",
                    "health_score": score,
                    "health_label": "Good",
                    "top_actions": "Fix title | Check broken assets",
                    "pages_checked_count": "4",
                    "broken_assets_count": "2",
                    "html_path": "reports/batch/a_example_com_report.html",
                    "pdf_path": "",
                }
            )

    def test_client_analytics_maps_only_own_sites_and_calculates_trend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clients = root / "clients.csv"
            self._write_clients(clients)
            reports = root / "reports"
            self._write_summary(reports / "batch_1" / "summary.csv", score="70", warnings="5")
            self._write_summary(reports / "batch_2" / "summary.csv", score="82", warnings="3")
            rows = build_admin_client_rows(
                clients_csv=clients,
                subscriptions_path=root / "subscriptions.csv",
                client_status_path=root / "status.csv",
                reports_dir=reports,
                client_packages_dir=root / "client_packages",
                project_root=root,
            )
            rows = [row for row in rows if row.client_email == "a@example.com"]
            analytics = build_client_dashboard_analytics(rows, reports, root)
        self.assertEqual(len(analytics.sites), 1)
        self.assertEqual(analytics.average_health_score, 82)
        self.assertEqual(analytics.open_warnings, 3)
        self.assertEqual(analytics.sites[0].score_delta, 12)
        self.assertEqual(analytics.sites[0].warning_delta, -2)

    def test_dashboard_handles_no_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clients = root / "clients.csv"
            self._write_clients(clients)
            rows = build_admin_client_rows(
                clients_csv=clients,
                subscriptions_path=root / "subscriptions.csv",
                client_status_path=root / "status.csv",
                reports_dir=root / "reports",
                client_packages_dir=root / "client_packages",
                project_root=root,
            )[:1]
            analytics = build_client_dashboard_analytics(rows, root / "reports", root)
            html = render_client_dashboard("a@example.com", analytics, None, None)
        self.assertIn("First report has not been generated yet", html)

    def test_billing_page_renders_without_subscription(self) -> None:
        config, _warnings = load_pricing_config(Path("__missing_pricing__.json"))
        html = render_client_billing(None, list_plans(config), [])
        self.assertIn("No active plan", html)
        self.assertIn("mock checkout", html)
        self.assertIn("Request add-on", html)

    def test_billing_request_approve_updates_subscription(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requests_path = root / "billing.csv"
            subscriptions_path = root / "subscriptions.csv"
            created = create_billing_request(
                requests_path,
                ClientBillingRequest(
                    request_id="",
                    client_email="a@example.com",
                    request_type="plan_change",
                    current_plan="starter",
                    requested_plan="agency-lite",
                ),
            )
            approve_billing_request(requests_path, created.request_id, subscriptions_path)
            subscriptions = load_subscriptions(subscriptions_path)
        self.assertEqual(subscriptions[0].plan_id, "agency-lite")
        self.assertEqual(subscriptions[0].payment_status, "active")

    def test_reject_billing_request_does_not_update_subscription(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requests_path = root / "billing.csv"
            subscriptions_path = root / "subscriptions.csv"
            upsert_subscription(
                subscriptions_path,
                SubscriptionRecord(customer_email="a@example.com", plan_id="starter", payment_status="active"),
            )
            created = create_billing_request(
                requests_path,
                ClientBillingRequest(
                    request_id="",
                    client_email="a@example.com",
                    request_type="plan_change",
                    current_plan="starter",
                    requested_plan="agency",
                ),
            )
            reject_billing_request(requests_path, created.request_id)
            subscriptions = load_subscriptions(subscriptions_path)
            requests = billing_requests_for_email(requests_path, "a@example.com")
        self.assertEqual(subscriptions[0].plan_id, "starter")
        self.assertEqual(requests[0].status, "rejected")

    def test_routes_registered(self) -> None:
        from app.admin_app import app

        paths = {route.path for route in app.routes}
        self.assertIn("/client/billing/request-plan", paths)
        self.assertIn("/client/billing/request-addon", paths)
        self.assertIn("/admin/billing-requests", paths)
        self.assertIn("/admin/billing-requests/{request_id}/approve", paths)
        self.assertIn("/admin/billing-requests/{request_id}/reject", paths)

    def test_client_billing_route_creates_plan_request(self) -> None:
        from app.admin_app import client_billing_request_plan

        class FakeRequest:
            query_params = {}

            async def form(self):
                return {"plan_id": "agency-lite"}

            @property
            def cookies(self):
                return {"client_session": "session"}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("app.admin_app.email_for_session", return_value="a@example.com"), patch(
                "app.admin_app.CLIENT_BILLING_REQUESTS_PATH", root / "billing.csv"
            ), patch("app.admin_app.SUBSCRIPTIONS_PATH", root / "subscriptions.csv"):
                response = asyncio.run(client_billing_request_plan(FakeRequest()))
            requests = billing_requests_for_email(root / "billing.csv", "a@example.com")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(requests[0].requested_plan, "agency-lite")


if __name__ == "__main__":
    unittest.main()
