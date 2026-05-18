# WebReport Weekly

Local-first service toolkit for weekly white-label website reports.

WebReport Weekly is not just a scanner script. It is an operator-focused workflow for agencies, SEO freelancers, and small web studios that need to send regular website health reports to their clients.

The project can generate reports, prepare demo sales assets, manage clients, run weekly batches, prepare email outbox, and expose a simple FastAPI site with:

- public marketing page;
- signup/setup form;
- admin-only operator panel;
- client portal with magic-link login;
- mock billing flow for local development.

The current version is an open-source local/VPS Operator MVP. It intentionally uses CSV, SQLite, and local files instead of a full multi-tenant SaaS stack.

## What The Service Does

For each website, WebReport Weekly can check and report:

- whether the site is reachable;
- basic SEO: title, meta description, H1, canonical, language;
- internal links and broken links;
- forms;
- robots.txt and sitemap.xml;
- HTTPS, HTTP to HTTPS redirect, SSL expiry;
- noindex pages;
- broken images/assets;
- changes compared with the previous run;
- Site Health Score;
- Top 3 recommended actions with owner: SEO, Developer, Content, or Ops.

Reports are generated as white-label HTML and optionally PDF.

## Product Shape

This repository supports a semi-automated service workflow:

1. Generate demo reports and sales materials.
2. Send prospects a sample report manually.
3. Convert a client into `data/clients.csv`.
4. Run the first report from admin.
5. Run weekly reports manually or through a scheduler.
6. Prepare an email outbox.
7. Send emails only when explicitly requested.

The service is designed so one operator can serve early clients without editing code for every new report.

## Current Status

Implemented:

- single-site scanner and report generator;
- batch report generation from CSV;
- weekly runner;
- outbox and SMTP sending;
- white-label branding;
- SQLite history and diff;
- health score and top actions;
- demo reports;
- sales pack generator;
- local CRM and proposal tools;
- signup/payment reconciliation foundation;
- admin panel;
- client portal;
- mock billing requests.

Not implemented as production SaaS yet:

- multi-tenant Postgres storage;
- hardened auth/permissions for public SaaS scale;
- real self-serve billing UI connected directly to Stripe Checkout;
- client-side plan changes without operator approval;
- managed deployment automation.

## Tech Stack

| Area | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI |
| CLI | Typer |
| Templates | Jinja2 |
| Storage | CSV + SQLite + local artifacts |
| Reports | HTML, optional PDF via Playwright/Chromium |
| Billing foundation | Stripe-compatible webhook/local sync |
| Tests | `unittest` |

## Repository Structure

```text
app/                 Python modules: scanner, batch, weekly, admin app, client portal
templates/           Jinja2 report/email templates
data/                example configs and local CSV/SQLite runtime files
branding/            branding config example
reports/             generated reports, ignored by git
outbox/              prepared email drafts, ignored by git
run_logs/            weekly/admin run logs, ignored by git
sales_pack/          generated sales assets and demo reports, ignored by git
client_packages/     onboarding packages, ignored by git
docs/                operator runbook
tests/               regression tests
```

## Quick Start

Run commands from the repository root.

### 1. Create Environment

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Optional PDF/screenshot support:

```bash
python -m playwright install chromium
```

### 2. Verify Installation

```bash
python -m app.preflight
python -m unittest discover -v
```

Expected local result: preflight should be `READY: yes`. It may warn that production env variables are not configured. That is normal for local development.

### 3. Generate Demo Reports And Sales Pack

```bash
python -m app.demo_reports generate
python -m app.sales_pack generate --format both
```

Generated files:

- `sales_pack/demo_reports/good_site_demo.html`;
- `sales_pack/demo_reports/medium_site_demo.html`;
- `sales_pack/demo_reports/problem_site_demo.html`;
- `sales_pack/generated_YYYY-MM-DD_HH-MM-SS/landing_page.html`;
- outreach, FAQ, pricing, objections, and checklist files.

### 4. Start The Web App

For local development:

```bash
uvicorn app.admin_app:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Useful pages:

- `http://127.0.0.1:8000/` — public landing page;
- `http://127.0.0.1:8000/signup` — setup form;
- `http://127.0.0.1:8000/admin/signups` — admin signups;
- `http://127.0.0.1:8000/admin/clients` — admin clients;
- `http://127.0.0.1:8000/admin/billing-requests` — mock billing requests;
- `http://127.0.0.1:8000/client/login` — client login.

By default, if `ADMIN_PASSWORD` is not set, admin routes are open locally. For any VPS or shared machine, set `ADMIN_PASSWORD`.

PowerShell example:

```powershell
$env:ADMIN_PASSWORD="replace-with-strong-password"
$env:BASE_URL="http://127.0.0.1:8000"
uvicorn app.admin_app:app --host 127.0.0.1 --port 8000
```

Then open:

```text
http://127.0.0.1:8000/admin/login
```

## Minimal Local Operator Demo

Use the example clients file:

```powershell
Copy-Item data\clients.example.csv data\clients.csv
```

Create a client login link:

```bash
python -m app.client_portal create-login-link --email client@example.com --base-url http://127.0.0.1:8000
```

Open the printed link. The client portal includes:

- dashboard with site metrics and latest report state;
- reports page;
- sites page;
- settings requests;
- billing page with mock upgrade/add-on requests.

Mock billing does not charge money. A client request creates `data/client_billing_requests.csv`; the operator approves or rejects it in `/admin/billing-requests`.

## Generate One Report

```bash
python -m app.main --url https://example.com --format html
```

White-label example:

```bash
python -m app.main `
  --url https://example.com `
  --brand-name "SEO Studio" `
  --client-name "Client Company" `
  --brand-color "#147a68" `
  --format both
```

Linux/macOS:

```bash
python -m app.main \
  --url https://example.com \
  --brand-name "SEO Studio" \
  --client-name "Client Company" \
  --brand-color "#147a68" \
  --format both
```

Important options:

| Option | Default | Description |
|---|---:|---|
| `--url` | required | Website URL |
| `--format` | `html` | `html`, `pdf`, or `both` |
| `--max-links` | `30` | Internal links to check |
| `--max-pages` | `10` | Pages to crawl |
| `--screenshot` | `false` | Homepage screenshot via Playwright |
| `--output-dir` | `reports` | Report output folder |
| `--db-path` | `data/checks.sqlite` | SQLite history |

## Batch Reports

Run reports for multiple clients:

```bash
python -m app.batch --clients data/clients.example.csv --output-dir reports --format html
```

With outbox preparation:

```bash
python -m app.batch --clients data/clients.example.csv --output-dir reports --format both --create-outbox
```

Client CSV fields:

- required: `client_name`, `url`;
- recommended: `client_email`, `brand_name`;
- optional: `brand_color`, `brand_logo`, `footer_text`, `format`, `max_links`, `max_pages`, `screenshot`, `timeout`.

Batch output:

```text
reports/batch_YYYY-MM-DD_HH-MM-SS/
  summary.csv
  summary.html
  *.html
  *.pdf
```

## Weekly Runner

Prepare a local weekly job file:

```powershell
Copy-Item data\weekly_jobs.example.json data\weekly_jobs.local.json
```

Dry run:

```bash
python -m app.weekly --job-file data/weekly_jobs.local.json --mode dry-run
```

Generate reports only:

```bash
python -m app.weekly --job-file data/weekly_jobs.local.json --mode generate
```

Generate reports and email outbox, but do not send:

```bash
python -m app.weekly --job-file data/weekly_jobs.local.json --mode outbox --active-only true
```

Send through SMTP:

```bash
python -m app.weekly --job-file data/weekly_jobs.local.json --mode send --active-only true
```

`--active-only true` skips paused, cancelled, payment failed, and needs-review clients.

## Email Delivery

Email sending is explicit. The project does not silently send reports.

Prepare outbox from a batch:

```bash
python -m app.send_reports --batch-dir reports/batch_YYYY-MM-DD_HH-MM-SS --clients data/clients.csv --dry-run
```

Send prepared emails:

```bash
python -m app.send_reports --batch-dir reports/batch_YYYY-MM-DD_HH-MM-SS --clients data/clients.csv --no-dry-run
```

SMTP must be configured through environment variables or CLI flags.

## Environment Variables

`.env.example` documents the expected variables, but this project does not depend on `.env` autoloading in every command. For local development, set environment variables in your shell, process manager, Docker, or hosting platform.

Common variables:

| Variable | Required For | Description |
|---|---|---|
| `ADMIN_PASSWORD` | VPS/admin safety | Password for admin routes |
| `BASE_URL` | magic links, public URLs | Public base URL |
| `CLIENT_PORTAL_ENABLED` | client portal | Defaults to `true` |
| `CLIENT_MAGIC_LINK_TTL_MINUTES` | client portal | Defaults to `30` |
| `CLIENT_SESSION_DAYS` | client portal | Defaults to `7` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` | email sending | SMTP delivery |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | real Stripe webhook mode | Optional |

For local development without Stripe/SMTP, the app still works in manual/mock mode.

## Client Portal

Client login uses one-time magic links. Passwords are not stored.

CLI:

```bash
python -m app.client_portal create-login-link --email client@example.com --base-url http://127.0.0.1:8000
python -m app.client_portal list-requests
python -m app.client_portal approve-request --request-id client_req_0001
python -m app.client_portal list-billing-requests
python -m app.client_portal approve-billing-request --request-id billing_req_0001
python -m app.client_portal reject-billing-request --request-id billing_req_0001
```

Local client portal files:

- `data/client_portal_sessions.csv`;
- `data/client_settings_requests.csv`;
- `data/client_billing_requests.csv`.

These files are ignored by git.

## Admin App

Start:

```bash
uvicorn app.admin_app:app --host 127.0.0.1 --port 8000
```

Admin routes:

- `/admin/signups` — signup review and approval;
- `/admin/clients` — clients, latest report, status, run now;
- `/admin/client-requests` — client settings requests;
- `/admin/billing-requests` — mock billing requests;
- `/admin/runs` — run logs;
- `/admin/outbox` — prepared emails.

Static artifact routes:

- `/reports/...`;
- `/sales_pack/...`;
- `/client_packages/...`.

## Billing

There are two billing layers:

1. Mock billing in the client portal.
2. Stripe-compatible webhook/local sync foundation.

Mock billing:

- used by `/client/billing`;
- creates approval requests;
- does not charge money;
- operator approves or rejects requests in `/admin/billing-requests`;
- approving a plan change updates `data/subscriptions.csv` with `payment_status=active`.

Stripe foundation:

```bash
python -m app.billing verify-config
python -m app.billing list
python -m app.billing sync-local --event-file stripe_event.json
```

Supported events:

- `checkout.session.completed`;
- `invoice.paid`;
- `invoice.payment_failed`;
- `customer.subscription.deleted`.

For a real checkout link, use this success URL:

```text
https://YOUR_DOMAIN/signup?plan=agency-lite&session_id={CHECKOUT_SESSION_ID}
```

## Sales Workflow

Generate stable demo reports:

```bash
python -m app.demo_reports generate
```

Generate sales material:

```bash
python -m app.sales_pack generate --format both
```

Recommended early sales loop:

1. Find SEO freelancer, agency, or marketer.
2. Send a relevant demo report.
3. Offer a free sample report for one site.
4. If interested, create proposal.
5. Convert lead to client.
6. Add client to weekly workflow.

Related CLI tools:

```bash
python -m app.crm --help
python -m app.onboard --help
python -m app.proposal --help
python -m app.convert_client --help
```

## Backups

Create a local backup:

```bash
python -m app.backup
```

Include `.env` only when needed:

```bash
python -m app.backup --include-env
```

Backup archives are written to `backups/` and ignored by git.

## Tests

Run full regression:

```bash
python -m unittest discover -v
```

Useful smoke commands:

```bash
python -m app.preflight
python -m app.main --help
python -m app.batch --help
python -m app.weekly --help
python -m app.client_portal --help
```

## What Is Ignored By Git

Runtime artifacts and private local data are intentionally ignored:

- generated reports: `reports/*`;
- email drafts: `outbox/*`;
- run logs: `run_logs/*`;
- backups: `backups/*`;
- generated sales assets: `sales_pack/*`;
- local CRM/proposals/leads/client packages;
- SQLite databases: `data/*.sqlite`, `data/*.db`;
- local client/subscription/signup CSV files;
- `.env`, virtual environments, Python caches.

Example files such as `data/clients.example.csv`, `data/weekly_jobs.example.json`, and `data/pricing.example.json` are tracked.

## Production Notes

Before running this outside your machine:

1. Set `ADMIN_PASSWORD`.
2. Put the app behind HTTPS.
3. Set `BASE_URL` to the real domain.
4. Configure SMTP before using `--mode send`.
5. Configure Stripe env only when using real webhook verification.
6. Back up `data/`, `reports/`, `outbox/`, `run_logs/`, and `client_packages/`.
7. Treat CSV/SQLite as local MVP storage, not high-scale SaaS infrastructure.

For detailed local/VPS operations, read:

```text
docs/LOCAL_OPERATOR_RUNBOOK.md
```

## License

MIT. See `LICENSE`.
