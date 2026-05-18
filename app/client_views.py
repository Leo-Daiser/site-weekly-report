from __future__ import annotations

from html import escape
from urllib.parse import quote

from app.admin_clients import AdminClientRow
from app.client_portal import ClientSettingsRequest
from app.models import SubscriptionRecord


def h(value: object) -> str:
    return escape("" if value is None else str(value))


def badge(value: str, *, kind: str | None = None) -> str:
    status = (kind or value or "neutral").lower()
    css = {
        "active": "ok",
        "approved": "ok",
        "sent": "ok",
        "pending": "warn",
        "pending_payment": "warn",
        "prepared": "warn",
        "needs_review": "warn",
        "paused": "muted",
        "payment_failed": "bad",
        "cancelled": "bad",
        "rejected": "bad",
        "failed": "bad",
        "error": "bad",
    }.get(status, "neutral")
    return f'<span class="badge {css}">{h(value or "—")}</span>'


def flash_html(status: str = "", message: str = "") -> str:
    if not message:
        return ""
    css = "ok" if status == "ok" else "bad" if status == "error" else "warn"
    return f'<div class="flash {css}">{h(message)}</div>'


def client_layout(title: str, body: str, *, email: str = "", status: str = "", message: str = "", public: bool = False):
    if public:
        nav = '<a href="/">Home</a><a href="/#pricing">Pricing</a><a href="/client/login">Client login</a>'
    else:
        nav = (
            '<a href="/client">Dashboard</a>'
            '<a href="/client/reports">Reports</a>'
            '<a href="/client/sites">Sites</a>'
            '<a href="/client/settings">Settings</a>'
            '<a href="/client/billing">Billing</a>'
            '<form method="post" action="/client/logout"><button>Logout</button></form>'
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{h(title)}</title>
  <style>
    :root {{ --ink:#172033; --muted:#5f6b7a; --line:#d9e0ea; --wash:#f6f8fb; --ok:#0d7a4a; --warn:#9a6700; --bad:#b42318; --accent:#147a68; }}
    body {{ margin:0; font-family:system-ui,-apple-system,Segoe UI,sans-serif; color:var(--ink); background:#fff; }}
    header {{ border-bottom:1px solid var(--line); background:var(--wash); }}
    nav {{ max-width:1180px; margin:0 auto; padding:14px 22px; display:flex; gap:14px; align-items:center; flex-wrap:wrap; }}
    nav a {{ color:var(--ink); text-decoration:none; font-weight:650; }}
    nav form {{ margin-left:auto; }}
    main {{ max-width:1180px; margin:0 auto; padding:24px 22px; }}
    h1 {{ margin:0 0 16px; }}
    h2 {{ margin-top:28px; }}
    .muted {{ color:var(--muted); }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }}
    .card {{ border:1px solid var(--line); border-radius:8px; padding:16px; background:#fff; }}
    table {{ border-collapse:collapse; width:100%; margin-top:16px; font-size:14px; }}
    th, td {{ border-bottom:1px solid var(--line); padding:9px; text-align:left; vertical-align:top; }}
    th {{ background:var(--wash); color:var(--muted); font-size:12px; text-transform:uppercase; }}
    input, textarea, select {{ width:100%; padding:8px; margin:4px 0 12px; border:1px solid var(--line); border-radius:6px; }}
    button, .button {{ display:inline-block; padding:8px 11px; border:1px solid var(--line); border-radius:6px; background:#fff; color:var(--ink); text-decoration:none; cursor:pointer; }}
    .button.primary, button.primary {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
    .badge {{ display:inline-block; padding:2px 7px; border-radius:999px; font-size:12px; font-weight:700; background:var(--wash); }}
    .badge.ok, .flash.ok {{ color:var(--ok); background:#e6f5ee; }}
    .badge.warn, .flash.warn {{ color:var(--warn); background:#fff8e6; }}
    .badge.bad, .flash.bad {{ color:var(--bad); background:#fdecea; }}
    .badge.muted {{ color:var(--muted); }}
    .flash {{ padding:10px 12px; border-radius:8px; margin-bottom:16px; }}
    code {{ background:var(--wash); padding:1px 4px; border-radius:4px; word-break:break-all; }}
  </style>
</head>
<body>
  <header><nav>{nav}</nav></header>
  <main>{flash_html(status, message)}{body}</main>
</body>
</html>"""


def render_client_login(status: str = "", message: str = "", link: str = "") -> str:
    link_html = f"<div class='card'><p class='muted'>Local/dev login link:</p><p><a href='{h(link)}'>{h(link)}</a></p></div>" if link else ""
    return f"""
<h1>Client login</h1>
<p class="muted">Enter the email used for reports or billing. We will create a one-time login link.</p>
{flash_html(status, message)}
{link_html}
<form method="post" action="/client/login">
  <label>Email<input name="email" type="email" required></label>
  <button class="primary" type="submit">Send magic link</button>
</form>
"""


def report_link(path: str, label: str = "Open report") -> str:
    if not path:
        return "—"
    return f'<a class="button" href="/{h(path)}">{h(label)}</a>'


def render_client_dashboard(email: str, rows: list[AdminClientRow], subscription: SubscriptionRecord | None, latest_run: dict[str, object] | None) -> str:
    cards = []
    for row in rows:
        cards.append(
            "<div class='card'>"
            f"<h3>{h(row.brand_name or row.client_name)}</h3>"
            f"<p><code>{h(row.url)}</code></p>"
            f"<p>Operational: {badge(row.operational_status)}</p>"
            f"<p>Latest: {h(row.latest_summary)}</p>"
            f"<p>{report_link(row.latest_report_path)}</p>"
            "</div>"
        )
    sub = subscription.payment_status if subscription else "unknown"
    plan = subscription.plan_id if subscription else "—"
    latest = latest_run.get("_file") if latest_run else "—"
    site_cards = "".join(cards) if cards else "<p class='muted'>No sites found for this email.</p>"
    return (
        f"<h1>Client dashboard</h1><p class='muted'>{h(email)}</p>"
        "<div class='grid'>"
        f"<div class='card'><h3>Subscription</h3><p>Plan: {h(plan)}</p><p>Status: {badge(sub)}</p></div>"
        f"<div class='card'><h3>Sites</h3><p>{len(rows)} site(s) connected.</p></div>"
        f"<div class='card'><h3>Latest run</h3><p>{h(latest)}</p></div>"
        "</div>"
        "<h2>Your sites</h2>"
        f"<div class='grid'>{site_cards}</div>"
    )


def render_client_reports(rows: list[AdminClientRow]) -> str:
    trs = []
    for row in rows:
        trs.append(
            f"<tr><td>{h(row.client_name)}</td><td><code>{h(row.url)}</code></td>"
            f"<td>{h(row.latest_summary)}</td><td>{report_link(row.latest_report_path)}</td></tr>"
        )
    return "<h1>Reports</h1><table><tr><th>Client</th><th>Site</th><th>Latest summary</th><th>Report</th></tr>" + "".join(trs) + "</table>"


def render_client_sites(rows: list[AdminClientRow]) -> str:
    trs = []
    for row in rows:
        trs.append(
            f"<tr><td>{h(row.client_name)}</td><td><code>{h(row.url)}</code></td><td>{h(row.report_format)}</td>"
            f"<td>{h(row.max_links)}</td><td>{badge(row.operational_status)}</td></tr>"
        )
    return "<h1>Sites</h1><p class='muted'>Site configuration is read-only. Request changes in Settings.</p><table><tr><th>Client</th><th>URL</th><th>Format</th><th>Max links</th><th>Status</th></tr>" + "".join(trs) + "</table>"


def render_client_settings(email: str, rows: list[AdminClientRow], requests: list[ClientSettingsRequest], status: str = "", message: str = "") -> str:
    options = "".join(f"<option value='{h(row.url)}'>{h(row.url)}</option>" for row in rows)
    req_rows = "".join(
        f"<tr><td>{h(item.request_id)}</td><td>{h(item.url or 'all')}</td><td>{badge(item.status)}</td><td>{h(item.created_at)}</td><td>{h(item.notes)}</td></tr>"
        for item in requests
    )
    return f"""
<h1>Settings</h1>
<p class="muted">Request branding or recipient changes. The operator reviews changes before they affect weekly delivery.</p>
{flash_html(status, message)}
<form method="post" action="/client/settings">
  <label>Site<select name="url"><option value="">All sites for this email</option>{options}</select></label>
  <label>Brand name<input name="brand_name"></label>
  <label>Brand color<input name="brand_color" placeholder="#147a68"></label>
  <label>Logo URL/path<input name="logo_url"></label>
  <label>Report recipient email<input name="report_recipient_email" type="email" value="{h(email)}"></label>
  <label>Notes<textarea name="notes"></textarea></label>
  <button class="primary" type="submit">Request changes</button>
</form>
<h2>Recent requests</h2>
<table><tr><th>ID</th><th>Site</th><th>Status</th><th>Created</th><th>Notes</th></tr>{req_rows}</table>
"""


def render_client_billing(subscription: SubscriptionRecord | None) -> str:
    if not subscription:
        return "<h1>Billing</h1><p class='muted'>No subscription record found for this email.</p>"
    return (
        "<h1>Billing</h1>"
        "<div class='grid'>"
        f"<div class='card'><h3>Plan</h3><p>{h(subscription.plan_id)}</p></div>"
        f"<div class='card'><h3>Payment status</h3><p>{badge(subscription.payment_status)}</p></div>"
        f"<div class='card'><h3>Stripe</h3><p>Customer: <code>{h(subscription.stripe_customer_id or '—')}</code></p><p>Subscription: <code>{h(subscription.stripe_subscription_id or '—')}</code></p></div>"
        "</div>"
        "<p class='muted'>Billing changes are handled through support or a checkout link in this MVP.</p>"
    )


def render_admin_client_requests(requests: list[ClientSettingsRequest]) -> str:
    rows = []
    for item in requests:
        rows.append(
            f"<tr><td>{h(item.request_id)}</td><td>{h(item.client_email)}</td><td><code>{h(item.url or 'all')}</code></td>"
            f"<td>{h(item.brand_name)}<br>{h(item.brand_color)}<br>{h(item.logo_url)}<br>{h(item.report_recipient_email)}</td>"
            f"<td>{h(item.notes)}</td><td>{badge(item.status)}</td>"
            f"<td><form class='inline' method='post' action='/admin/client-requests/{quote(item.request_id)}/approve'><button>Approve</button></form>"
            f"<form class='inline' method='post' action='/admin/client-requests/{quote(item.request_id)}/reject'><button>Reject</button></form></td></tr>"
        )
    return "<h1>Client requests</h1><table><tr><th>ID</th><th>Email</th><th>Site</th><th>Requested fields</th><th>Notes</th><th>Status</th><th>Actions</th></tr>" + "".join(rows) + "</table>"
