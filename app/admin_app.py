from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.admin_clients import (
    build_admin_client_rows,
    find_admin_client,
    latest_run_for_client,
    run_admin_single_client_report,
)
from app.admin_views import (
    layout,
    render_admin_login,
    render_client_detail,
    render_clients_page,
    render_outbox_page,
    render_public_signup,
    render_public_signup_thanks,
    render_run_detail,
    render_runs_page,
    render_signups_page,
)
from app.billing import apply_stripe_event
from app.client_analytics import build_client_dashboard_analytics
from app.client_portal import (
    ClientBillingRequest,
    ClientSettingsRequest,
    approve_billing_request,
    approve_settings_request,
    billing_requests_for_email,
    clients_for_email,
    consume_magic_token,
    create_billing_request,
    create_magic_link,
    create_settings_request,
    email_for_session,
    load_billing_requests,
    load_settings_requests,
    reject_billing_request,
    requests_for_email,
    revoke_session,
    set_settings_request_status,
    subscription_for_email,
)
from app.client_views import (
    client_layout,
    render_admin_billing_requests,
    render_admin_client_requests,
    render_client_billing,
    render_client_dashboard,
    render_client_login,
    render_client_reports,
    render_client_settings,
    render_client_sites,
)
from app.client_status_store import set_client_status
from app.email_sender import send_email_with_attachments, smtp_config_from_env
from app.weekly import load_weekly_job, execute_weekly_run
from app.send_reports import send_prepared_emails
from app.outbox import read_manifest
from app.signup_store import create_signup, load_signups
from app.signups import (
    approve_signup,
    apply_payment_record_to_signup,
    reconcile_signup_payments,
    set_signup_status,
    subscription_for_signup,
    validate_signup_for_plan,
)
from app.models import SignupRecord
from app.pricing import list_plans, load_pricing_config
from app.sales_assets import load_sales_pack_config, render_sales_asset, SALES_SITE_TEMPLATE

ROOT = Path(__file__).resolve().parent.parent
SIGNUPS_PATH = ROOT / "data" / "pending_signups.csv"
SUBSCRIPTIONS_PATH = ROOT / "data" / "subscriptions.csv"
CRM_PATH = ROOT / "data" / "leads_crm.csv"
CLIENTS_CSV = ROOT / "data" / "clients.csv"
PRICING_FILE = ROOT / "data" / "pricing.example.json"
PACKAGES_DIR = ROOT / "client_packages"
RUN_LOGS_DIR = ROOT / "run_logs"
CLIENT_STATUS_PATH = ROOT / "data" / "client_status.csv"
CLIENT_PORTAL_SESSIONS_PATH = ROOT / "data" / "client_portal_sessions.csv"
CLIENT_SETTINGS_REQUESTS_PATH = ROOT / "data" / "client_settings_requests.csv"
CLIENT_BILLING_REQUESTS_PATH = ROOT / "data" / "client_billing_requests.csv"
WEEKLY_JOB_PATH = ROOT / "data" / "weekly_jobs.local.json"
DEFAULT_OUTBOX_DIR = ROOT / "outbox"
REPORTS_DIR = ROOT / "reports"
DB_PATH = ROOT / "data" / "checks.sqlite"

app = FastAPI(title="WebReport Weekly Admin")

app.mount("/reports", StaticFiles(directory=REPORTS_DIR, check_dir=False), name="reports")
app.mount("/sales_pack", StaticFiles(directory=ROOT / "sales_pack", check_dir=False), name="sales_pack")
app.mount("/client_packages", StaticFiles(directory=PACKAGES_DIR, check_dir=False), name="client_packages")


def _check_admin(request: Request) -> None:
    password = os.getenv("ADMIN_PASSWORD")
    if not password:
        return
    supplied = (
        request.query_params.get("admin_password")
        or request.headers.get("x-admin-password")
        or request.cookies.get("admin_session")
    )
    if supplied != password:
        raise HTTPException(status_code=401, detail="Admin password required")


def _redirect(path: str, *, status: str = "ok", message: str = "") -> RedirectResponse:
    if message:
        return RedirectResponse(
            f"{path}?status={quote(status)}&message={quote(message)}",
            status_code=303,
        )
    return RedirectResponse(path, status_code=303)


def _stripe_required() -> bool:
    return bool(os.getenv("STRIPE_SECRET_KEY") or os.getenv("STRIPE_WEBHOOK_SECRET"))


def _client_portal_enabled() -> bool:
    return os.getenv("CLIENT_PORTAL_ENABLED", "true").lower() not in ("0", "false", "no", "off")


def _base_url(request: Request) -> str:
    return os.getenv("BASE_URL") or str(request.base_url).rstrip("/")


def _client_ttl_minutes() -> int:
    return int(os.getenv("CLIENT_MAGIC_LINK_TTL_MINUTES", "30"))


def _client_session_days() -> int:
    return int(os.getenv("CLIENT_SESSION_DAYS", "7"))


def _require_client_email(request: Request) -> str:
    if not _client_portal_enabled():
        raise HTTPException(status_code=404, detail="Client portal disabled")
    email = email_for_session(CLIENT_PORTAL_SESSIONS_PATH, request.cookies.get("client_session"))
    if not email:
        raise HTTPException(status_code=401, detail="Client login required")
    return email


def _client_rows(email: str):
    return clients_for_email(
        email=email,
        clients_csv=CLIENTS_CSV,
        subscriptions_path=SUBSCRIPTIONS_PATH,
        client_status_path=CLIENT_STATUS_PATH,
        reports_dir=REPORTS_DIR,
        client_packages_dir=PACKAGES_DIR,
        project_root=ROOT,
    )


def _latest_client_run(email: str, rows) -> dict[str, object] | None:
    for row in rows:
        found = latest_run_for_client(RUN_LOGS_DIR, email, row.url)
        if found:
            return found
    return None


def _client_analytics(rows):
    return build_client_dashboard_analytics(rows, REPORTS_DIR, ROOT)


def _pricing_plans():
    config, _warnings = load_pricing_config(PRICING_FILE)
    return list_plans(config)


def _send_magic_link_email(email: str, link: str) -> None:
    smtp_config = smtp_config_from_env()
    send_email_with_attachments(
        to_email=email,
        subject="Your WebReport Weekly login link",
        text_body=(
            "Use this one-time link to open your WebReport Weekly client portal:\n\n"
            f"{link}\n\n"
            "The link expires automatically. If you did not request it, ignore this email."
        ),
        html_body=(
            "<p>Use this one-time link to open your WebReport Weekly client portal:</p>"
            f"<p><a href=\"{link}\">{link}</a></p>"
            "<p>The link expires automatically. If you did not request it, ignore this email.</p>"
        ),
        attachments=[],
        smtp_config=smtp_config,
    )


async def _read_form(request: Request) -> dict[str, str]:
    try:
        form = await request.form()
        return {key: str(value) for key, value in form.items()}
    except AssertionError as exc:
        if "python-multipart" not in str(exc):
            raise
    if not hasattr(request, "body"):
        form = await request.form()
        return {key: str(value) for key, value in form.items()}
    body = await request.body()
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


@app.get("/", response_class=HTMLResponse)
def public_landing_page() -> HTMLResponse:
    config_path = ROOT / "data" / "sales_pack.local.example.json"
    if not config_path.is_file():
        config_path = ROOT / "data" / "sales_pack.example.json"
    config = load_sales_pack_config(config_path)
    html = render_sales_asset(
        SALES_SITE_TEMPLATE,
        {
            "config": config,
            "product_name": config.product_name,
            "target_audience": config.target_audience,
            "positioning": config.positioning,
            "primary_offer": config.primary_offer,
            "currency": config.currency,
            "contact_email": config.contact_email,
            "signup_url": config.signup_url,
            "plans": config.plans,
            "main_benefits": config.main_benefits,
            "demo_report_path": config.demo_report_path,
            "demo_reports": config.demo_reports,
            "generated_at": "dynamic",
            "agency_lite": next((p for p in config.plans if p.id == "agency-lite"), None),
        },
        template_dir=ROOT / "templates",
    )
    return HTMLResponse(html)


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request) -> HTMLResponse:
    if not os.getenv("ADMIN_PASSWORD"):
        return layout("Admin login", "<h1>Admin login disabled</h1><p class='muted'>ADMIN_PASSWORD is not set.</p>")
    return layout(
        "Admin login",
        render_admin_login(request.query_params.get("message", "")),
        public=True,
    )


@app.post("/admin/login")
async def admin_login_submit(request: Request) -> RedirectResponse:
    form = await _read_form(request)
    password = os.getenv("ADMIN_PASSWORD")
    supplied = str(form.get("admin_password") or "")
    if not password or supplied != password:
        return _redirect("/admin/login", status="error", message="Invalid password")
    response = _redirect("/admin/signups", message="Logged in")
    response.set_cookie("admin_session", supplied, httponly=True, samesite="lax")
    return response


@app.post("/admin/logout")
def admin_logout() -> RedirectResponse:
    response = _redirect("/admin/login", message="Logged out")
    response.delete_cookie("admin_session")
    return response


@app.get("/signup", response_class=HTMLResponse)
def public_signup_page(request: Request) -> HTMLResponse:
    return layout(
        "Signup",
        render_public_signup(
            plan_id=request.query_params.get("plan", ""),
            status=request.query_params.get("status", ""),
            message=request.query_params.get("message", ""),
            session_id=request.query_params.get("session_id", ""),
            customer_email=request.query_params.get("customer_email", ""),
        ),
        public=True,
    )


@app.post("/signup")
async def public_signup_submit(request: Request) -> RedirectResponse:
    form = await _read_form(request)
    required = ("agency_name", "billing_email", "report_recipient_email", "plan_id", "website_urls")
    missing = [name for name in required if not str(form.get(name) or "").strip()]
    if missing:
        return _redirect(
            "/signup",
            status="error",
            message="Missing required fields: " + ", ".join(missing),
        )
    signup_data = SignupRecord(
        signup_id="",
        agency_name=str(form.get("agency_name") or "").strip(),
        billing_email=str(form.get("billing_email") or "").strip(),
        report_recipient_email=str(form.get("report_recipient_email") or "").strip(),
        plan_id=str(form.get("plan_id") or "").strip(),
        website_urls=str(form.get("website_urls") or "").strip(),
        brand_name=str(form.get("brand_name") or "").strip(),
        brand_color=str(form.get("brand_color") or "#2563eb").strip() or "#2563eb",
        logo_url=str(form.get("logo_url") or "").strip() or None,
        status="pending_payment",
        stripe_checkout_session_id=str(form.get("session_id") or "").strip() or None,
    )
    subscription = subscription_for_signup(signup_data, SUBSCRIPTIONS_PATH)
    apply_payment_record_to_signup(signup_data, subscription)
    validation_errors = validate_signup_for_plan(signup_data, PRICING_FILE)
    if validation_errors:
        return _redirect(
            f"/signup?plan={quote(signup_data.plan_id)}",
            status="error",
            message="; ".join(validation_errors),
        )
    signup = create_signup(SIGNUPS_PATH, signup_data)
    return _redirect(f"/signup/thanks/{quote(signup.signup_id)}")


@app.get("/signup/thanks/{signup_id}", response_class=HTMLResponse)
def public_signup_thanks(signup_id: str) -> HTMLResponse:
    return layout("Signup received", render_public_signup_thanks(signup_id), public=True)


@app.get("/client/login", response_class=HTMLResponse)
def client_login_page(request: Request) -> HTMLResponse:
    return HTMLResponse(
        client_layout(
            "Client login",
            render_client_login(
                request.query_params.get("status", ""),
                request.query_params.get("message", ""),
                request.query_params.get("link", ""),
            ),
            public=True,
        )
    )


@app.post("/client/login")
async def client_login_submit(request: Request) -> RedirectResponse:
    if not _client_portal_enabled():
        raise HTTPException(status_code=404, detail="Client portal disabled")
    form = await _read_form(request)
    email = str(form.get("email") or "").strip().lower()
    if not email:
        return _redirect("/client/login", status="error", message="Email is required")
    rows = _client_rows(email)
    subscription = subscription_for_email(SUBSCRIPTIONS_PATH, email)
    if not rows and not subscription:
        return _redirect("/client/login", status="error", message="No client found for this email")
    link, _record = create_magic_link(
        sessions_path=CLIENT_PORTAL_SESSIONS_PATH,
        email=email,
        base_url=_base_url(request),
        ttl_minutes=_client_ttl_minutes(),
    )
    if os.getenv("SMTP_HOST"):
        try:
            _send_magic_link_email(email, link)
        except Exception as exc:
            return _redirect("/client/login", status="error", message=f"Login email failed: {exc}")
        return _redirect("/client/login", message="Login link sent")
    return _redirect("/client/login", message="Local login link created", status="ok") if os.getenv("BASE_URL") else RedirectResponse(
        f"/client/login?status=ok&message={quote('Local login link created')}&link={quote(link)}",
        status_code=303,
    )


@app.get("/client/magic")
def client_magic_login(token: str) -> RedirectResponse:
    try:
        _email, session_token = consume_magic_token(
            sessions_path=CLIENT_PORTAL_SESSIONS_PATH,
            raw_token=token,
            session_days=_client_session_days(),
        )
    except Exception as exc:
        return _redirect("/client/login", status="error", message=str(exc))
    response = _redirect("/client", message="Logged in")
    response.set_cookie("client_session", session_token, httponly=True, samesite="lax")
    return response


@app.post("/client/logout")
def client_logout(request: Request) -> RedirectResponse:
    revoke_session(CLIENT_PORTAL_SESSIONS_PATH, request.cookies.get("client_session"))
    response = _redirect("/client/login", message="Logged out")
    response.delete_cookie("client_session")
    return response


@app.get("/client", response_class=HTMLResponse)
def client_dashboard_page(request: Request) -> HTMLResponse:
    email = _require_client_email(request)
    rows = _client_rows(email)
    return HTMLResponse(
        client_layout(
            "Client dashboard",
            render_client_dashboard(
                email,
                _client_analytics(rows),
                subscription_for_email(SUBSCRIPTIONS_PATH, email),
                _latest_client_run(email, rows),
            ),
            email=email,
            status=request.query_params.get("status", ""),
            message=request.query_params.get("message", ""),
        )
    )


@app.get("/client/reports", response_class=HTMLResponse)
def client_reports_page(request: Request) -> HTMLResponse:
    email = _require_client_email(request)
    rows = _client_rows(email)
    return HTMLResponse(client_layout("Client reports", render_client_reports(_client_analytics(rows)), email=email))


@app.get("/client/sites", response_class=HTMLResponse)
def client_sites_page(request: Request) -> HTMLResponse:
    email = _require_client_email(request)
    rows = _client_rows(email)
    return HTMLResponse(client_layout("Client sites", render_client_sites(_client_analytics(rows)), email=email))


@app.get("/client/settings", response_class=HTMLResponse)
def client_settings_page(request: Request) -> HTMLResponse:
    email = _require_client_email(request)
    return HTMLResponse(
        client_layout(
            "Client settings",
            render_client_settings(
                email,
                _client_rows(email),
                requests_for_email(CLIENT_SETTINGS_REQUESTS_PATH, email),
                request.query_params.get("status", ""),
                request.query_params.get("message", ""),
            ),
            email=email,
        )
    )


@app.post("/client/settings")
async def client_settings_submit(request: Request) -> RedirectResponse:
    email = _require_client_email(request)
    form = await _read_form(request)
    create_settings_request(
        CLIENT_SETTINGS_REQUESTS_PATH,
        ClientSettingsRequest(
            request_id="",
            client_email=email,
            url=str(form.get("url") or "").strip(),
            brand_name=str(form.get("brand_name") or "").strip(),
            brand_color=str(form.get("brand_color") or "").strip(),
            logo_url=str(form.get("logo_url") or "").strip(),
            report_recipient_email=str(form.get("report_recipient_email") or "").strip(),
            notes=str(form.get("notes") or "").strip(),
        ),
    )
    return _redirect("/client/settings", message="Settings request submitted")


@app.get("/client/billing", response_class=HTMLResponse)
def client_billing_page(request: Request) -> HTMLResponse:
    email = _require_client_email(request)
    return HTMLResponse(
        client_layout(
            "Client billing",
            render_client_billing(
                subscription_for_email(SUBSCRIPTIONS_PATH, email),
                _pricing_plans(),
                billing_requests_for_email(CLIENT_BILLING_REQUESTS_PATH, email),
            ),
            email=email,
            status=request.query_params.get("status", ""),
            message=request.query_params.get("message", ""),
        )
    )


@app.post("/client/billing/request-plan")
async def client_billing_request_plan(request: Request) -> RedirectResponse:
    email = _require_client_email(request)
    form = await _read_form(request)
    plan_id = str(form.get("plan_id") or "").strip()
    if not plan_id:
        return _redirect("/client/billing", status="error", message="Plan is required")
    subscription = subscription_for_email(SUBSCRIPTIONS_PATH, email)
    create_billing_request(
        CLIENT_BILLING_REQUESTS_PATH,
        ClientBillingRequest(
            request_id="",
            client_email=email,
            request_type="plan_change",
            current_plan=subscription.plan_id if subscription else "",
            requested_plan=plan_id,
            notes="Created from client portal mock checkout",
        ),
    )
    return _redirect("/client/billing", message="Mock plan change request created")


@app.post("/client/billing/request-addon")
async def client_billing_request_addon(request: Request) -> RedirectResponse:
    email = _require_client_email(request)
    form = await _read_form(request)
    addon = str(form.get("addon") or "").strip()
    if not addon:
        return _redirect("/client/billing", status="error", message="Add-on is required")
    subscription = subscription_for_email(SUBSCRIPTIONS_PATH, email)
    create_billing_request(
        CLIENT_BILLING_REQUESTS_PATH,
        ClientBillingRequest(
            request_id="",
            client_email=email,
            request_type="addon",
            current_plan=subscription.plan_id if subscription else "",
            addon=addon,
            notes="Created from client portal mock checkout",
        ),
    )
    return _redirect("/client/billing", message="Mock add-on request created")


@app.get("/admin/signups", response_class=HTMLResponse)
def signups_page(request: Request) -> HTMLResponse:
    _check_admin(request)
    return layout(
        "Signups",
        render_signups_page(load_signups(SIGNUPS_PATH)),
        status=request.query_params.get("status", ""),
        message=request.query_params.get("message", ""),
    )


@app.get("/admin/client-requests", response_class=HTMLResponse)
def admin_client_requests_page(request: Request) -> HTMLResponse:
    _check_admin(request)
    return layout(
        "Client requests",
        render_admin_client_requests(load_settings_requests(CLIENT_SETTINGS_REQUESTS_PATH)),
        status=request.query_params.get("status", ""),
        message=request.query_params.get("message", ""),
    )


@app.post("/admin/client-requests/{request_id}/approve")
def admin_approve_client_request_page(request: Request, request_id: str) -> RedirectResponse:
    _check_admin(request)
    try:
        approve_settings_request(CLIENT_SETTINGS_REQUESTS_PATH, request_id, CLIENTS_CSV)
    except Exception as exc:
        return _redirect("/admin/client-requests", status="error", message=f"Approve failed: {exc}")
    return _redirect("/admin/client-requests", message="Client request approved")


@app.post("/admin/client-requests/{request_id}/reject")
def admin_reject_client_request_page(request: Request, request_id: str) -> RedirectResponse:
    _check_admin(request)
    try:
        set_settings_request_status(CLIENT_SETTINGS_REQUESTS_PATH, request_id, "rejected", admin_notes="Rejected from admin")
    except Exception as exc:
        return _redirect("/admin/client-requests", status="error", message=f"Reject failed: {exc}")
    return _redirect("/admin/client-requests", status="warning", message="Client request rejected")


@app.get("/admin/billing-requests", response_class=HTMLResponse)
def admin_billing_requests_page(request: Request) -> HTMLResponse:
    _check_admin(request)
    return layout(
        "Billing requests",
        render_admin_billing_requests(load_billing_requests(CLIENT_BILLING_REQUESTS_PATH)),
        status=request.query_params.get("status", ""),
        message=request.query_params.get("message", ""),
    )


@app.post("/admin/billing-requests/{request_id}/approve")
def admin_approve_billing_request_page(request: Request, request_id: str) -> RedirectResponse:
    _check_admin(request)
    try:
        approve_billing_request(CLIENT_BILLING_REQUESTS_PATH, request_id, SUBSCRIPTIONS_PATH)
    except Exception as exc:
        return _redirect("/admin/billing-requests", status="error", message=f"Approve failed: {exc}")
    return _redirect("/admin/billing-requests", message="Billing request approved")


@app.post("/admin/billing-requests/{request_id}/reject")
def admin_reject_billing_request_page(request: Request, request_id: str) -> RedirectResponse:
    _check_admin(request)
    try:
        reject_billing_request(CLIENT_BILLING_REQUESTS_PATH, request_id)
    except Exception as exc:
        return _redirect("/admin/billing-requests", status="error", message=f"Reject failed: {exc}")
    return _redirect("/admin/billing-requests", status="warning", message="Billing request rejected")


@app.post("/admin/signups")
async def create_signup_page(request: Request) -> RedirectResponse:
    _check_admin(request)
    form = await _read_form(request)
    create_signup(
        SIGNUPS_PATH,
        SignupRecord(
            signup_id="",
            agency_name=str(form.get("agency_name") or ""),
            billing_email=str(form.get("billing_email") or ""),
            report_recipient_email=str(form.get("report_recipient_email") or ""),
            plan_id=str(form.get("plan_id") or ""),
            website_urls=str(form.get("website_urls") or ""),
            brand_name=str(form.get("brand_name") or ""),
            brand_color=str(form.get("brand_color") or "#2563eb"),
            status="pending",
        ),
    )
    return _redirect("/admin/signups", message="Signup created")


@app.post("/admin/signups/reconcile-payments")
def reconcile_signups_page(request: Request) -> RedirectResponse:
    _check_admin(request)
    total, updated = reconcile_signup_payments(
        signups_path=SIGNUPS_PATH,
        subscriptions_path=SUBSCRIPTIONS_PATH,
    )
    return _redirect("/admin/signups", message=f"Reconciled {updated}/{total} signup(s)")


@app.post("/admin/signups/{signup_id}/approve")
def approve_signup_page(request: Request, signup_id: str) -> RedirectResponse:
    _check_admin(request)
    try:
        signup = approve_signup(
            signup_id=signup_id,
            signups_path=SIGNUPS_PATH,
            crm_path=CRM_PATH,
            clients_csv=CLIENTS_CSV,
            pricing_file=PRICING_FILE,
            packages_dir=PACKAGES_DIR,
            template_dir=ROOT / "templates",
            project_root=ROOT,
            weekly_job_file=ROOT / "data" / "weekly_jobs.local.json",
            subscriptions_path=SUBSCRIPTIONS_PATH,
            require_payment=_stripe_required(),
        )
    except Exception as exc:
        return _redirect("/admin/signups", status="error", message=f"Approve failed: {exc}")
    return _redirect("/admin/signups", message=f"Signup {signup.signup_id} status: {signup.status}")


@app.post("/admin/signups/{signup_id}/needs-review")
def needs_review_signup_page(request: Request, signup_id: str) -> RedirectResponse:
    _check_admin(request)
    try:
        set_signup_status(
            signup_id=signup_id,
            signups_path=SIGNUPS_PATH,
            status="needs_review",
            notes="Marked from admin",
        )
    except Exception as exc:
        return _redirect("/admin/signups", status="error", message=f"Update failed: {exc}")
    return _redirect("/admin/signups", status="warning", message="Signup marked as needs_review")


@app.post("/admin/signups/{signup_id}/reject")
def reject_signup_page(request: Request, signup_id: str) -> RedirectResponse:
    _check_admin(request)
    try:
        set_signup_status(
            signup_id=signup_id,
            signups_path=SIGNUPS_PATH,
            status="rejected",
            notes="Rejected from admin",
        )
    except Exception as exc:
        return _redirect("/admin/signups", status="error", message=f"Reject failed: {exc}")
    return _redirect("/admin/signups", status="warning", message="Signup rejected")


@app.get("/admin/clients", response_class=HTMLResponse)
def clients_page(request: Request) -> HTMLResponse:
    _check_admin(request)
    clients = build_admin_client_rows(
        clients_csv=CLIENTS_CSV,
        subscriptions_path=SUBSCRIPTIONS_PATH,
        client_status_path=CLIENT_STATUS_PATH,
        reports_dir=REPORTS_DIR,
        client_packages_dir=PACKAGES_DIR,
        project_root=ROOT,
    )
    return layout(
        "Clients",
        render_clients_page(clients),
        status=request.query_params.get("status", ""),
        message=request.query_params.get("message", ""),
    )


@app.get("/admin/clients/detail", response_class=HTMLResponse)
def client_detail_page(request: Request, client_email: str, url: str) -> HTMLResponse:
    _check_admin(request)
    rows = build_admin_client_rows(
        clients_csv=CLIENTS_CSV,
        subscriptions_path=SUBSCRIPTIONS_PATH,
        client_status_path=CLIENT_STATUS_PATH,
        reports_dir=REPORTS_DIR,
        client_packages_dir=PACKAGES_DIR,
        project_root=ROOT,
    )
    target = next(
        (
            row
            for row in rows
            if row.client_email.lower() == client_email.lower()
            and row.url.rstrip("/").lower() == url.rstrip("/").lower()
        ),
        None,
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Client not found")
    latest_run = latest_run_for_client(RUN_LOGS_DIR, client_email, url)
    return layout("Client detail", render_client_detail(target, latest_run))


@app.post("/admin/clients/pause")
async def pause_client_page(request: Request) -> RedirectResponse:
    _check_admin(request)
    form = await _read_form(request)
    set_client_status(
        CLIENT_STATUS_PATH,
        client_email=str(form.get("client_email") or ""),
        url=str(form.get("url") or ""),
        status="paused",
        reason="Paused from admin",
    )
    return _redirect("/admin/clients", message="Client paused")


@app.post("/admin/clients/resume")
async def resume_client_page(request: Request) -> RedirectResponse:
    _check_admin(request)
    form = await _read_form(request)
    set_client_status(
        CLIENT_STATUS_PATH,
        client_email=str(form.get("client_email") or ""),
        url=str(form.get("url") or ""),
        status="active",
        reason="Resumed from admin",
    )
    return _redirect("/admin/clients", message="Client resumed")


@app.post("/admin/clients/needs-review")
async def needs_review_client_page(request: Request) -> RedirectResponse:
    _check_admin(request)
    form = await _read_form(request)
    set_client_status(
        CLIENT_STATUS_PATH,
        client_email=str(form.get("client_email") or ""),
        url=str(form.get("url") or ""),
        status="needs_review",
        reason="Marked from admin",
    )
    return _redirect("/admin/clients", status="warning", message="Client marked as needs_review")


@app.post("/admin/clients/run-now")
async def run_client_now_page(request: Request) -> RedirectResponse:
    _check_admin(request)
    form = await _read_form(request)
    try:
        result = run_admin_single_client_report(
            clients_csv=CLIENTS_CSV,
            client_email=str(form.get("client_email") or ""),
            url=str(form.get("url") or ""),
            output_root=REPORTS_DIR,
            db_path=DB_PATH,
            project_root=ROOT,
            run_logs_dir=RUN_LOGS_DIR,
        )
    except Exception as exc:
        return _redirect("/admin/clients", status="error", message=f"Run failed: {exc}")
    if result.success:
        return _redirect("/admin/clients", message="Single-site report generated")
    return _redirect("/admin/clients", status="error", message=f"Report failed: {result.error or 'unknown error'}")


@app.post("/admin/clients/send-login-link")
async def send_client_login_link_page(request: Request) -> RedirectResponse:
    _check_admin(request)
    form = await _read_form(request)
    email = str(form.get("email") or "").strip().lower()
    if not email:
        return _redirect("/admin/clients", status="error", message="Client email is required")
    link, _record = create_magic_link(
        sessions_path=CLIENT_PORTAL_SESSIONS_PATH,
        email=email,
        base_url=_base_url(request),
        ttl_minutes=_client_ttl_minutes(),
    )
    if os.getenv("SMTP_HOST"):
        try:
            _send_magic_link_email(email, link)
        except Exception as exc:
            return _redirect("/admin/clients", status="error", message=f"Login email failed: {exc}")
        return _redirect("/admin/clients", message="Client login link sent")
    return _redirect("/admin/clients", message=f"Client login link: {link}")


@app.get("/admin/runs", response_class=HTMLResponse)
def runs_page(request: Request) -> HTMLResponse:
    _check_admin(request)
    logs: list[tuple[str, dict[str, object]]] = []
    for path in sorted(RUN_LOGS_DIR.glob("*.json"), reverse=True)[:50]:
        try:
            logs.append((path.name, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            logs.append((path.name, {"success": False, "error": "Cannot parse run log"}))
    return layout(
        "Runs",
        render_runs_page(logs),
        status=request.query_params.get("status", ""),
        message=request.query_params.get("message", ""),
    )


@app.get("/admin/runs/detail", response_class=HTMLResponse)
def run_detail_page(request: Request, file: str) -> HTMLResponse:
    _check_admin(request)
    path = RUN_LOGS_DIR / Path(file).name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Run log not found")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    return layout("Run detail", render_run_detail(path.name, payload))


@app.post("/admin/runs/run-now")
def run_now_page(request: Request) -> RedirectResponse:
    _check_admin(request)
    job_path = WEEKLY_JOB_PATH if WEEKLY_JOB_PATH.is_file() else ROOT / "data" / "weekly_jobs.example.json"
    job = load_weekly_job(job_path)
    execute_weekly_run(
        job,
        mode="outbox",
        project_root=ROOT,
        run_logs_dir=RUN_LOGS_DIR,
        active_only=True,
        subscriptions_path=SUBSCRIPTIONS_PATH,
        client_status_path=CLIENT_STATUS_PATH,
    )
    return _redirect("/admin/runs", message="Weekly outbox run finished")


@app.get("/admin/outbox", response_class=HTMLResponse)
def outbox_page(request: Request) -> HTMLResponse:
    _check_admin(request)
    dirs = sorted(DEFAULT_OUTBOX_DIR.glob("batch_*"), reverse=True)
    items = [(path, read_manifest(path / "manifest.csv")) for path in dirs[:30]]
    return layout(
        "Outbox",
        render_outbox_page(items),
        status=request.query_params.get("status", ""),
        message=request.query_params.get("message", ""),
    )


@app.post("/admin/outbox/resend")
async def resend_outbox_page(request: Request) -> RedirectResponse:
    _check_admin(request)
    form = await _read_form(request)
    batch_dir = ROOT / str(form.get("batch_dir") or "")
    outbox_dir = Path(str(form.get("outbox_dir") or ""))
    if not outbox_dir.is_absolute():
        outbox_dir = ROOT / outbox_dir
    try:
        sent, failed = send_prepared_emails(
            batch_dir=batch_dir,
            outbox_dir=outbox_dir,
            smtp_overrides={},
            limit=10,
        )
    except Exception as exc:
        return _redirect("/admin/outbox", status="error", message=f"Send failed: {exc}")
    return _redirect("/admin/outbox", message=f"Sent={sent}, failed={failed}")


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request) -> JSONResponse:
    payload = await request.body()
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if webhook_secret:
        try:
            import stripe

            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=request.headers.get("stripe-signature", ""),
                secret=webhook_secret,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Stripe signature verification failed: {exc}") from exc
    else:
        try:
            event = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    record = apply_stripe_event(event, SUBSCRIPTIONS_PATH)
    return JSONResponse(
        {
            "received": True,
            "event_type": event.get("type"),
            "updated": record.model_dump() if record else None,
        }
    )
