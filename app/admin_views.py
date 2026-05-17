from __future__ import annotations

import json
from html import escape
from pathlib import Path
from urllib.parse import quote

from fastapi.responses import HTMLResponse

from app.admin_clients import AdminClientRow
from app.models import EmailManifestEntry, SignupRecord


def h(value: object) -> str:
    return escape("" if value is None else str(value))


def badge(value: str, *, kind: str | None = None) -> str:
    status = (kind or value or "neutral").lower()
    css = {
        "active": "ok",
        "pass": "ok",
        "sent": "ok",
        "approved": "ok",
        "prepared": "warn",
        "pending": "warn",
        "warning": "warn",
        "payment_failed": "bad",
        "cancelled": "bad",
        "paused": "muted",
        "needs_review": "warn",
        "fail": "bad",
        "failed": "bad",
        "error": "bad",
    }.get(status, "neutral")
    return f'<span class="badge {css}">{h(value or "—")}</span>'


def flash_html(status: str = "", message: str = "") -> str:
    if not message:
        return ""
    css = "ok" if status == "ok" else "bad" if status == "error" else "warn"
    return f'<div class="flash {css}">{h(message)}</div>'


def layout(
    title: str,
    body: str,
    *,
    status: str = "",
    message: str = "",
    public: bool = False,
) -> HTMLResponse:
    nav = (
        '<a href="/signup">Signup</a>'
        if public
        else (
            '<a href="/admin/signups">Signups</a>'
            '<a href="/admin/clients">Clients</a>'
            '<a href="/admin/runs">Runs</a>'
            '<a href="/admin/outbox">Outbox</a>'
        )
    )
    return HTMLResponse(
        f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{h(title)}</title>
  <style>
    :root {{ --ink:#172033; --muted:#5f6b7a; --line:#d9e0ea; --wash:#f6f8fb; --ok:#0d7a4a; --warn:#9a6700; --bad:#b42318; }}
    body {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 0; color: var(--ink); background: #fff; }}
    header {{ border-bottom: 1px solid var(--line); background: var(--wash); }}
    nav {{ max-width: 1280px; margin: 0 auto; padding: 14px 24px; display: flex; gap: 14px; align-items: center; }}
    nav a {{ color: var(--ink); text-decoration: none; font-weight: 650; }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 16px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 9px; text-align: left; vertical-align: top; }}
    th {{ background: var(--wash); color: var(--muted); font-size: 12px; text-transform: uppercase; }}
    input, textarea, select {{ width: 100%; padding: 8px; margin: 4px 0 12px; border: 1px solid var(--line); border-radius: 6px; }}
    button, .button {{ display:inline-block; padding: 7px 10px; border: 1px solid var(--line); border-radius: 6px; background:#fff; color:var(--ink); text-decoration:none; cursor:pointer; }}
    form.inline {{ display:inline; margin-right: 4px; }}
    .muted {{ color: var(--muted); }}
    .badge {{ display:inline-block; padding: 2px 7px; border-radius: 999px; font-size: 12px; font-weight: 700; background: var(--wash); }}
    .badge.ok, .flash.ok {{ color: var(--ok); background:#e6f5ee; }}
    .badge.warn, .flash.warn {{ color: var(--warn); background:#fff8e6; }}
    .badge.bad, .flash.bad {{ color: var(--bad); background:#fdecea; }}
    .badge.muted {{ color: var(--muted); }}
    .flash {{ padding: 10px 12px; border-radius: 8px; margin-bottom: 16px; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }}
    .card {{ border:1px solid var(--line); border-radius:8px; padding:14px; background:#fff; }}
    code, pre {{ background: var(--wash); border-radius: 6px; }}
    code {{ padding: 1px 4px; word-break: break-all; }}
    pre {{ padding: 12px; overflow:auto; }}
    .actions {{ display:flex; flex-wrap:wrap; gap:4px; }}
  </style>
</head>
<body>
  <header><nav>{nav}</nav></header>
  <main>
    {flash_html(status, message)}
    {body}
  </main>
</body>
</html>"""
    )


def render_admin_login(message: str = "") -> str:
    return (
        "<h1>Admin login</h1>"
        f"{flash_html('error', message)}"
        "<form method='post' action='/admin/login'>"
        "<label>Password<input name='admin_password' type='password' required></label>"
        "<button type='submit'>Login</button>"
        "</form>"
    )


def render_public_signup(plan_id: str = "", status: str = "", message: str = "") -> str:
    selected = {
        "starter": " selected" if plan_id == "starter" else "",
        "agency-lite": " selected" if plan_id == "agency-lite" else "",
        "agency": " selected" if plan_id == "agency" else "",
    }
    return f"""
<h1>Finish setup</h1>
<p class="muted">Submit the website and branding details needed to start weekly reports.</p>
{flash_html(status, message)}
<form method="post" action="/signup">
  <label>Agency name<input name="agency_name" required></label>
  <label>Billing email<input name="billing_email" type="email" required></label>
  <label>Report recipient email<input name="report_recipient_email" type="email" required></label>
  <label>Plan<select name="plan_id" required>
    <option value="starter"{selected["starter"]}>Starter</option>
    <option value="agency-lite"{selected["agency-lite"]}>Agency Lite</option>
    <option value="agency"{selected["agency"]}>Agency</option>
  </select></label>
  <label>Website URLs<textarea name="website_urls" required placeholder="https://example.com"></textarea></label>
  <label>Brand name<input name="brand_name"></label>
  <label>Brand color<input name="brand_color" value="#2563eb"></label>
  <label>Logo URL or path<input name="logo_url"></label>
  <button type="submit">Submit setup</button>
</form>
"""


def render_public_signup_thanks(signup_id: str) -> str:
    return (
        "<h1>Setup received</h1>"
        "<p>Your setup details were saved. The first report will be prepared after review.</p>"
        f"<p class='muted'>Reference: {h(signup_id)}</p>"
    )


def artifact_link(path: str, label: str) -> str:
    if not path:
        return "—"
    return f'<a class="button" href="/{h(path)}">{h(label)}</a>'


def hidden(name: str, value: str) -> str:
    return f'<input type="hidden" name="{h(name)}" value="{h(value)}">'


def client_detail_url(row: AdminClientRow) -> str:
    return (
        f"/admin/clients/detail?client_email={quote(row.client_email)}"
        f"&url={quote(row.url)}"
    )


def render_clients_page(rows: list[AdminClientRow]) -> str:
    body_rows: list[str] = []
    for row in rows:
        fields = hidden("client_email", row.client_email) + hidden("url", row.url)
        actions = (
            f'<a class="button" href="{h(client_detail_url(row))}">Detail</a>'
            f'<form class="inline" method="post" action="/admin/clients/run-now">{fields}<button>Run now</button></form>'
            f'<form class="inline" method="post" action="/admin/clients/pause">{fields}<button>Pause</button></form>'
            f'<form class="inline" method="post" action="/admin/clients/resume">{fields}<button>Resume</button></form>'
            f'<form class="inline" method="post" action="/admin/clients/needs-review">{fields}<button>Needs review</button></form>'
        )
        body_rows.append(
            "<tr>"
            f"<td>{h(row.client_name)}<br><span class='muted'>{h(row.client_email)}</span></td>"
            f"<td><code>{h(row.url)}</code></td>"
            f"<td>{h(row.brand_name)}</td>"
            f"<td>{h(row.plan_id or '—')}<br>{badge(row.payment_status)}</td>"
            f"<td>{badge(row.operational_status)}</td>"
            f"<td>{artifact_link(row.latest_report_path, 'Report')}</td>"
            f"<td>{h(row.latest_summary)}</td>"
            f"<td>{artifact_link(row.client_package_path, 'Package')}</td>"
            f"<td><div class='actions'>{actions}</div></td>"
            "</tr>"
        )
    return (
        "<h1>Clients</h1>"
        "<p class='muted'>Merged from clients.csv, subscriptions, client statuses, reports, and packages.</p>"
        "<table><tr><th>Client</th><th>URL</th><th>Brand</th><th>Plan / payment</th>"
        "<th>Operational</th><th>Latest report</th><th>Latest summary</th><th>Package</th><th>Actions</th></tr>"
        f"{''.join(body_rows)}</table>"
    )


def render_client_detail(row: AdminClientRow, latest_run: dict[str, object] | None) -> str:
    run_html = "<p class='muted'>No run log found.</p>"
    if latest_run:
        run_html = "<pre>" + h(json.dumps(latest_run, ensure_ascii=False, indent=2)) + "</pre>"
    return (
        f"<h1>{h(row.client_name)}</h1>"
        "<div class='grid'>"
        f"<div class='card'><h3>Client</h3><p>Email: {h(row.client_email)}</p><p>URL: <code>{h(row.url)}</code></p><p>Brand: {h(row.brand_name)}</p></div>"
        f"<div class='card'><h3>Status</h3><p>Payment: {badge(row.payment_status)}</p><p>Operational: {badge(row.operational_status)}</p><p>Plan: {h(row.plan_id or '—')}</p></div>"
        f"<div class='card'><h3>Artifacts</h3><p>{artifact_link(row.latest_report_path, 'Open latest report')}</p><p>{artifact_link(row.client_package_path, 'Open client package')}</p></div>"
        f"<div class='card'><h3>Latest summary</h3><p>{h(row.latest_summary)}</p></div>"
        "</div>"
        "<h2>Latest run</h2>"
        f"{run_html}"
    )


def render_signups_page(signups: list[SignupRecord]) -> str:
    rows = []
    for signup in signups:
        rows.append(
            f"<tr><td>{h(signup.signup_id)}</td><td>{h(signup.agency_name)}</td><td>{h(signup.plan_id)}</td>"
            f"<td>{badge(signup.status)}</td><td><code>{h(signup.website_urls)}</code></td>"
            f"<td><form class='inline' method='post' action='/admin/signups/{h(signup.signup_id)}/approve'><button>Approve</button></form></td></tr>"
        )
    return f"""
<h1>Pending signups</h1>
<form method="post" action="/admin/signups">
  <label>Agency name<input name="agency_name" required></label>
  <label>Billing email<input name="billing_email" type="email" required></label>
  <label>Report recipient email<input name="report_recipient_email" type="email" required></label>
  <label>Plan<select name="plan_id"><option value="starter">Starter</option><option value="agency-lite">Agency Lite</option><option value="agency">Agency</option></select></label>
  <label>Website URLs<textarea name="website_urls" required></textarea></label>
  <label>Brand name<input name="brand_name"></label>
  <label>Brand color<input name="brand_color" value="#2563eb"></label>
  <button type="submit">Create signup</button>
</form>
<table><tr><th>ID</th><th>Agency</th><th>Plan</th><th>Status</th><th>Sites</th><th>Action</th></tr>{''.join(rows)}</table>
"""


def render_runs_page(logs: list[tuple[str, dict[str, object]]]) -> str:
    cards = []
    for name, payload in logs:
        success = payload.get("success")
        status = "pass" if success is True else "fail" if success is False else "warning"
        label = payload.get("mode") or payload.get("run_type") or "run"
        cards.append(
            "<div class='card'>"
            f"<h3>{h(name)} {badge(str(label), kind=status)}</h3>"
            f"<p>Started: {h(payload.get('started_at') or payload.get('created_at') or '—')}</p>"
            f"<p>Total: {h(payload.get('total', '—'))} Successful: {h(payload.get('successful', '—'))} Failed: {h(payload.get('failed', '—'))}</p>"
            f"<p>Error: {h(payload.get('error') or '—')}</p>"
            f"<a class='button' href='/admin/runs/detail?file={quote(name)}'>Open detail</a>"
            "</div>"
        )
    return (
        "<h1>Weekly runs</h1>"
        "<form method='post' action='/admin/runs/run-now'><button type='submit'>Run batch now</button></form>"
        f"<div class='grid'>{''.join(cards)}</div>"
    )


def render_run_detail(name: str, payload: dict[str, object]) -> str:
    links = []
    for key in ("batch_dir", "outbox_dir", "summary_html", "html_path", "pdf_path"):
        value = payload.get(key)
        if value:
            links.append(f"<p>{h(key)}: {artifact_link(str(value), str(value))}</p>")
    links_html = "".join(links) or '<p class="muted">No artifact links.</p>'
    return (
        f"<h1>Run detail: {h(name)}</h1>"
        f"<div class='card'>{links_html}</div>"
        "<pre>" + h(json.dumps(payload, ensure_ascii=False, indent=2)) + "</pre>"
    )


def render_outbox_page(items: list[tuple[Path, list[EmailManifestEntry]]]) -> str:
    rows = []
    for path, entries in items:
        counts = {status: sum(1 for entry in entries if entry.status == status) for status in ("prepared", "sent", "failed", "skipped")}
        rows.append(
            f"<tr><td>{h(path.name)}</td><td>{badge(str(counts['prepared']) + ' prepared', kind='prepared')} {badge(str(counts['sent']) + ' sent', kind='sent')} {badge(str(counts['failed']) + ' failed', kind='failed')}</td>"
            f"<td><form class='inline' method='post' action='/admin/outbox/resend'>{hidden('batch_dir', 'reports/' + path.name)}{hidden('outbox_dir', path.as_posix())}<button>Send prepared</button></form></td></tr>"
        )
    return (
        "<h1>Outbox</h1><p class='muted'>SMTP env must be configured before sending.</p>"
        f"<table><tr><th>Outbox</th><th>Status</th><th>Action</th></tr>{''.join(rows)}</table>"
    )
