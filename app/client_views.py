from __future__ import annotations

from html import escape
from urllib.parse import quote

from app.admin_clients import AdminClientRow
from app.client_analytics import ClientDashboardAnalytics, ClientSiteAnalytics
from app.client_portal import ClientBillingRequest, ClientSettingsRequest
from app.models import PricingPlan, SubscriptionRecord


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
        "unknown": "muted",
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
    :root {{ --ink:#172033; --muted:#5f6b7a; --line:#d9e0ea; --wash:#f6f8fb; --panel:#ffffff; --ok:#0d7a4a; --warn:#9a6700; --bad:#b42318; --accent:#147a68; --accent-2:#2f5f9f; }}
    body {{ margin:0; font-family:system-ui,-apple-system,Segoe UI,sans-serif; color:var(--ink); background:#f7f9fc; }}
    header {{ border-bottom:1px solid var(--line); background:#ffffff; position:sticky; top:0; z-index:2; }}
    nav {{ max-width:1180px; margin:0 auto; padding:14px 22px; display:flex; gap:14px; align-items:center; flex-wrap:wrap; }}
    nav a {{ color:var(--ink); text-decoration:none; font-weight:650; }}
    nav form {{ margin-left:auto; }}
    main {{ max-width:1180px; margin:0 auto; padding:24px 22px; }}
    h1 {{ margin:0 0 16px; }}
    h2 {{ margin-top:28px; }}
    h3 {{ margin:0 0 8px; }}
    .muted {{ color:var(--muted); }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }}
    .metric-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin:16px 0 20px; }}
    .metric {{ border:1px solid var(--line); border-radius:8px; padding:14px; background:var(--panel); }}
    .metric strong {{ display:block; font-size:28px; line-height:1.1; }}
    .card {{ border:1px solid var(--line); border-radius:8px; padding:16px; background:var(--panel); box-shadow:0 1px 1px rgba(23,32,51,.03); }}
    .site-card {{ display:flex; flex-direction:column; gap:10px; }}
    .score {{ width:72px; height:72px; border-radius:999px; display:grid; place-items:center; font-size:24px; font-weight:800; background:#e6f5ee; color:var(--ok); }}
    .score.warn {{ background:#fff8e6; color:var(--warn); }}
    .score.bad {{ background:#fdecea; color:var(--bad); }}
    .score.muted {{ background:var(--wash); color:var(--muted); }}
    .site-top {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }}
    .actions-list {{ margin:8px 0 0; padding-left:18px; }}
    .actions-list li {{ margin:3px 0; }}
    table {{ border-collapse:collapse; width:100%; margin-top:16px; font-size:14px; }}
    th, td {{ border-bottom:1px solid var(--line); padding:9px; text-align:left; vertical-align:top; }}
    th {{ background:var(--wash); color:var(--muted); font-size:12px; text-transform:uppercase; }}
    input, textarea, select {{ width:100%; padding:8px; margin:4px 0 12px; border:1px solid var(--line); border-radius:6px; }}
    button, .button {{ display:inline-block; padding:8px 11px; border:1px solid var(--line); border-radius:6px; background:#fff; color:var(--ink); text-decoration:none; cursor:pointer; }}
    .button.primary, button.primary {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
    .button.secondary, button.secondary {{ background:var(--accent-2); color:#fff; border-color:var(--accent-2); }}
    form.inline {{ display:inline; }}
    .badge {{ display:inline-block; padding:2px 7px; border-radius:999px; font-size:12px; font-weight:700; background:var(--wash); }}
    .badge.ok, .flash.ok {{ color:var(--ok); background:#e6f5ee; }}
    .badge.warn, .flash.warn {{ color:var(--warn); background:#fff8e6; }}
    .badge.bad, .flash.bad {{ color:var(--bad); background:#fdecea; }}
    .badge.muted {{ color:var(--muted); }}
    .flash {{ padding:10px 12px; border-radius:8px; margin-bottom:16px; }}
    .empty {{ border:1px dashed var(--line); border-radius:8px; padding:18px; background:#fff; color:var(--muted); }}
    .price {{ font-size:28px; font-weight:800; margin:8px 0; }}
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


def _score_class(score: int | None) -> str:
    if score is None:
        return "muted"
    if score < 60:
        return "bad"
    if score < 80:
        return "warn"
    return ""


def _score_html(score: int | None) -> str:
    return f"<div class='score {_score_class(score)}'>{h(score if score is not None else '—')}</div>"


def _delta(value: int | None, *, inverse: bool = False) -> str:
    if value is None:
        return "—"
    if value == 0:
        return "no change"
    good = value > 0
    if inverse:
        good = value < 0
    sign = "+" if value > 0 else ""
    return badge(f"{sign}{value}", kind="active" if good else "warning")


def _top_actions_html(actions: list[str]) -> str:
    if not actions:
        return "<p class='muted'>No priority actions recorded yet.</p>"
    return "<ol class='actions-list'>" + "".join(f"<li>{h(item)}</li>" for item in actions[:3]) + "</ol>"


def _site_card(item: ClientSiteAnalytics) -> str:
    row = item.row
    latest = item.latest
    if not latest:
        return (
            "<div class='card site-card'>"
            f"<div class='site-top'><div><h3>{h(row.brand_name or row.client_name)}</h3><p><code>{h(row.url)}</code></p></div>{_score_html(None)}</div>"
            f"<p>Operational: {badge(row.operational_status)}</p>"
            "<div class='empty'>First report has not been generated yet. Ask the operator to run the first check from admin.</div>"
            "</div>"
        )
    report = latest.html_path or row.latest_report_path
    return (
        "<div class='card site-card'>"
        f"<div class='site-top'><div><h3>{h(row.brand_name or row.client_name)}</h3><p><code>{h(row.url)}</code></p></div>{_score_html(latest.health_score)}</div>"
        f"<p>{badge(latest.health_label or 'Report ready', kind='active' if latest.success else 'error')} {badge(row.operational_status)}</p>"
        "<div class='grid'>"
        f"<div><strong>{h(latest.warnings_count)}</strong><br><span class='muted'>warnings</span></div>"
        f"<div><strong>{h(latest.broken_links_count)}</strong><br><span class='muted'>broken links</span></div>"
        f"<div><strong>{h(latest.broken_assets_count)}</strong><br><span class='muted'>broken assets</span></div>"
        f"<div><strong>{h(latest.pages_checked_count)}</strong><br><span class='muted'>pages checked</span></div>"
        "</div>"
        f"<p class='muted'>Score trend: {_delta(item.score_delta)} · Warning trend: {_delta(item.warning_delta, inverse=True)}</p>"
        f"<h3>Top actions</h3>{_top_actions_html(latest.top_actions)}"
        f"<p>{report_link(report)}</p>"
        "</div>"
    )


def render_client_dashboard(
    email: str,
    analytics: ClientDashboardAnalytics,
    subscription: SubscriptionRecord | None,
    latest_run: dict[str, object] | None,
) -> str:
    sub = subscription.payment_status if subscription else "unknown"
    plan = subscription.plan_id if subscription else "—"
    latest = analytics.latest_report_date or (latest_run.get("_file") if latest_run else "—")
    score = analytics.average_health_score if analytics.average_health_score is not None else "—"
    site_cards = "".join(_site_card(item) for item in analytics.sites) if analytics.sites else "<div class='empty'>No sites found for this email.</div>"
    return (
        f"<h1>Client dashboard</h1><p class='muted'>{h(email)}</p>"
        "<div class='metric-grid'>"
        f"<div class='metric'><strong>{h(score)}</strong><span class='muted'>average health score</span></div>"
        f"<div class='metric'><strong>{h(analytics.active_sites)}</strong><span class='muted'>active sites</span></div>"
        f"<div class='metric'><strong>{h(analytics.open_warnings)}</strong><span class='muted'>open warnings</span></div>"
        f"<div class='metric'><strong>{h(analytics.broken_links)}</strong><span class='muted'>broken links</span></div>"
        "</div>"
        "<div class='grid'>"
        f"<div class='card'><h3>Subscription</h3><p>Plan: {h(plan)}</p><p>Status: {badge(sub)}</p><p><a class='button primary' href='/client/billing'>Manage billing</a></p></div>"
        f"<div class='card'><h3>Latest report</h3><p>{h(latest)}</p><p><a class='button' href='/client/reports'>View all reports</a></p></div>"
        f"<div class='card'><h3>Settings</h3><p class='muted'>Branding and recipient changes are reviewed before weekly delivery changes.</p><p><a class='button' href='/client/settings'>Request changes</a></p></div>"
        "</div>"
        "<h2>Your sites</h2>"
        f"<div class='grid'>{site_cards}</div>"
    )


def render_client_reports(analytics: ClientDashboardAnalytics) -> str:
    trs = []
    for item in analytics.sites:
        row = item.row
        latest = item.latest
        if latest:
            report = latest.html_path or row.latest_report_path
            summary = f"{latest.health_score if latest.health_score is not None else '—'} / {latest.health_label or '—'}"
            warnings = latest.warnings_count
            broken = latest.broken_links_count
            date = latest.created_at
        else:
            report = ""
            summary = "First report pending"
            warnings = "—"
            broken = "—"
            date = "—"
        trs.append(
            f"<tr><td>{h(row.client_name)}</td><td><code>{h(row.url)}</code></td>"
            f"<td>{h(date)}</td><td>{h(summary)}</td><td>{h(warnings)}</td><td>{h(broken)}</td><td>{report_link(report)}</td></tr>"
        )
    if not trs:
        return "<h1>Reports</h1><div class='empty'>No connected sites or reports yet.</div>"
    return "<h1>Reports</h1><table><tr><th>Client</th><th>Site</th><th>Date</th><th>Score</th><th>Warnings</th><th>Broken links</th><th>Report</th></tr>" + "".join(trs) + "</table>"


def render_client_sites(analytics: ClientDashboardAnalytics) -> str:
    trs = []
    for item in analytics.sites:
        row = item.row
        latest = item.latest
        score = latest.health_score if latest and latest.health_score is not None else "—"
        trs.append(
            f"<tr><td>{h(row.client_name)}</td><td><code>{h(row.url)}</code></td><td>{h(row.report_format)}</td>"
            f"<td>{h(row.max_links)}</td><td>{h(row.max_pages)}</td><td>{badge('on' if row.screenshot else 'off', kind='active' if row.screenshot else 'muted')}</td>"
            f"<td>{h(score)}</td><td>{badge(row.operational_status)}</td></tr>"
        )
    if not trs:
        return "<h1>Sites</h1><div class='empty'>No sites found for this login.</div>"
    return "<h1>Sites</h1><p class='muted'>Site configuration is read-only. Request changes in Settings.</p><table><tr><th>Client</th><th>URL</th><th>Format</th><th>Max links</th><th>Max pages</th><th>Screenshot</th><th>Latest score</th><th>Status</th></tr>" + "".join(trs) + "</table>"


def render_client_settings(email: str, rows: list[AdminClientRow], requests: list[ClientSettingsRequest], status: str = "", message: str = "") -> str:
    options = "".join(f"<option value='{h(row.url)}'>{h(row.url)}</option>" for row in rows)
    req_rows = "".join(
        f"<tr><td>{h(item.request_id)}</td><td>{h(item.url or 'all')}</td><td>{badge(item.status)}</td><td>{h(item.created_at)}</td><td>{h(item.notes)}</td></tr>"
        for item in requests
    )
    requests_table = (
        "<table><tr><th>ID</th><th>Site</th><th>Status</th><th>Created</th><th>Notes</th></tr>"
        f"{req_rows}</table>"
        if req_rows
        else "<div class='empty'>No settings requests yet.</div>"
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
{requests_table}
"""


def _plan_card(plan: PricingPlan, current_plan: str) -> str:
    features = "".join(f"<li>{h(item)}</li>" for item in plan.features[:5])
    label = "Current plan" if plan.plan_id == current_plan else "Request this plan"
    button_class = "secondary" if plan.plan_id == current_plan else "primary"
    disabled = " disabled" if plan.plan_id == current_plan else ""
    return (
        "<div class='card'>"
        f"<h3>{h(plan.name)}</h3>"
        f"<div class='price'>${h(plan.price_monthly)}<span class='muted'>/mo</span></div>"
        f"<p class='muted'>{h(plan.description)}</p>"
        f"<p>{h(plan.sites_included)} site(s) included · setup ${h(plan.setup_fee)}</p>"
        f"<ul>{features}</ul>"
        f"<form method='post' action='/client/billing/request-plan'>"
        f"<input type='hidden' name='plan_id' value='{h(plan.plan_id)}'>"
        f"<button class='{button_class}' type='submit'{disabled}>{h(label)}</button>"
        "</form>"
        "</div>"
    )


def _billing_requests_table(requests: list[ClientBillingRequest]) -> str:
    if not requests:
        return "<div class='empty'>No billing requests yet.</div>"
    rows = []
    for item in requests:
        requested = item.requested_plan or item.addon
        rows.append(
            f"<tr><td>{h(item.request_id)}</td><td>{h(item.request_type)}</td><td>{h(requested)}</td>"
            f"<td>{badge(item.status)}</td><td>{h(item.created_at)}</td><td>{h(item.notes)}</td></tr>"
        )
    return "<table><tr><th>ID</th><th>Type</th><th>Requested</th><th>Status</th><th>Created</th><th>Notes</th></tr>" + "".join(rows) + "</table>"


def render_client_billing(
    subscription: SubscriptionRecord | None,
    plans: list[PricingPlan],
    requests: list[ClientBillingRequest],
) -> str:
    current_plan = subscription.plan_id if subscription else ""
    status = subscription.payment_status if subscription else "not configured"
    plan_cards = "".join(_plan_card(plan, current_plan) for plan in plans)
    return (
        "<h1>Billing</h1>"
        "<p class='muted'>Local/dev billing is a mock checkout. Requests below do not charge money; they create an operator approval item.</p>"
        "<div class='grid'>"
        f"<div class='card'><h3>Current plan</h3><p>{h(current_plan or 'No active plan')}</p></div>"
        f"<div class='card'><h3>Payment status</h3><p>{badge(status)}</p></div>"
        f"<div class='card'><h3>Billing mode</h3><p>{badge('mock checkout', kind='warning')}</p><p class='muted'>Stripe can be connected later without changing the client workflow.</p></div>"
        "</div>"
        "<h2>Plans</h2>"
        f"<div class='grid'>{plan_cards}</div>"
        "<h2>Add-ons</h2>"
        "<div class='grid'>"
        "<div class='card'><h3>Additional site slot</h3><p class='price'>$10<span class='muted'>/mo</span></p><p class='muted'>Use when the agency wants one more tracked website before changing plan.</p><form method='post' action='/client/billing/request-addon'><input type='hidden' name='addon' value='additional_site_slot'><button class='primary'>Request add-on</button></form></div>"
        "<div class='card'><h3>Setup / report review</h3><p class='price'>$49<span class='muted'> one-time</span></p><p class='muted'>Operator reviews report quality, branding, and delivery setup before the next weekly run.</p><form method='post' action='/client/billing/request-addon'><input type='hidden' name='addon' value='setup_report_review'><button class='primary'>Request review</button></form></div>"
        "</div>"
        "<h2>Billing requests</h2>"
        f"{_billing_requests_table(requests)}"
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


def render_admin_billing_requests(requests: list[ClientBillingRequest]) -> str:
    rows = []
    for item in requests:
        requested = item.requested_plan or item.addon
        actions = ""
        if item.status == "pending":
            actions = (
                f"<form class='inline' method='post' action='/admin/billing-requests/{quote(item.request_id)}/approve'><button>Approve</button></form>"
                f"<form class='inline' method='post' action='/admin/billing-requests/{quote(item.request_id)}/reject'><button>Reject</button></form>"
            )
        rows.append(
            f"<tr><td>{h(item.request_id)}</td><td>{h(item.client_email)}</td><td>{h(item.request_type)}</td>"
            f"<td>{h(item.current_plan or '—')}</td><td>{h(requested)}</td><td>{badge(item.status)}</td>"
            f"<td>{h(item.created_at)}</td><td>{h(item.notes)}</td><td>{actions or '—'}</td></tr>"
        )
    if not rows:
        return "<h1>Billing requests</h1><div class='empty'>No client billing requests yet.</div>"
    return "<h1>Billing requests</h1><p class='muted'>Mock checkout requests. Approving plan changes updates local subscriptions.csv with active status.</p><table><tr><th>ID</th><th>Email</th><th>Type</th><th>Current</th><th>Requested</th><th>Status</th><th>Created</th><th>Notes</th><th>Actions</th></tr>" + "".join(rows) + "</table>"
