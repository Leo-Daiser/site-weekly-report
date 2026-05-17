from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

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
from app.client_status_store import set_client_status
from app.weekly import load_weekly_job, execute_weekly_run
from app.send_reports import send_prepared_emails
from app.outbox import read_manifest
from app.signup_store import create_signup, load_signups
from app.signups import approve_signup
from app.models import SignupRecord

ROOT = Path(__file__).resolve().parent.parent
SIGNUPS_PATH = ROOT / "data" / "pending_signups.csv"
SUBSCRIPTIONS_PATH = ROOT / "data" / "subscriptions.csv"
CRM_PATH = ROOT / "data" / "leads_crm.csv"
CLIENTS_CSV = ROOT / "data" / "clients.csv"
PRICING_FILE = ROOT / "data" / "pricing.example.json"
PACKAGES_DIR = ROOT / "client_packages"
RUN_LOGS_DIR = ROOT / "run_logs"
CLIENT_STATUS_PATH = ROOT / "data" / "client_status.csv"
WEEKLY_JOB_PATH = ROOT / "data" / "weekly_jobs.local.json"
DEFAULT_OUTBOX_DIR = ROOT / "outbox"
REPORTS_DIR = ROOT / "reports"
DB_PATH = ROOT / "data" / "checks.sqlite"

app = FastAPI(title="WebReport Weekly Admin")


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
    signup = create_signup(
        SIGNUPS_PATH,
        SignupRecord(
            signup_id="",
            agency_name=str(form.get("agency_name") or "").strip(),
            billing_email=str(form.get("billing_email") or "").strip(),
            report_recipient_email=str(form.get("report_recipient_email") or "").strip(),
            plan_id=str(form.get("plan_id") or "").strip(),
            website_urls=str(form.get("website_urls") or "").strip(),
            brand_name=str(form.get("brand_name") or "").strip(),
            brand_color=str(form.get("brand_color") or "#2563eb").strip() or "#2563eb",
            logo_url=str(form.get("logo_url") or "").strip() or None,
        ),
    )
    return _redirect(f"/signup/thanks/{quote(signup.signup_id)}")


@app.get("/signup/thanks/{signup_id}", response_class=HTMLResponse)
def public_signup_thanks(signup_id: str) -> HTMLResponse:
    return layout("Signup received", render_public_signup_thanks(signup_id), public=True)


@app.get("/admin/signups", response_class=HTMLResponse)
def signups_page(request: Request) -> HTMLResponse:
    _check_admin(request)
    return layout(
        "Signups",
        render_signups_page(load_signups(SIGNUPS_PATH)),
        status=request.query_params.get("status", ""),
        message=request.query_params.get("message", ""),
    )


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
        ),
    )
    return _redirect("/admin/signups", message="Signup created")


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
        )
    except Exception as exc:
        return _redirect("/admin/signups", status="error", message=f"Approve failed: {exc}")
    return _redirect("/admin/signups", message=f"Signup {signup.signup_id} status: {signup.status}")


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
