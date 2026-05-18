# Local / VPS Operator Runbook

This runbook describes the minimum path for running WebReport Weekly as a one-operator MVP.

## 1. Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

For PDF export and screenshots:

```bash
python -m playwright install chromium
```

## 2. Configure Environment

Copy `.env.example` to `.env` on the machine that runs the service and set real values:

```text
ADMIN_PASSWORD=replace-with-strong-password
BASE_URL=https://reports.example.com
CLIENT_PORTAL_ENABLED=true
CLIENT_MAGIC_LINK_TTL_MINUTES=30
CLIENT_SESSION_DAYS=7
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM_EMAIL=reports@example.com
SMTP_FROM_NAME=WebReport Weekly
SMTP_USE_TLS=true
```

The project still runs in local/manual mode without Stripe and SMTP env, but live payments and email sending require them.

## 3. Configure Sales Page

Use `data/sales_pack.local.example.json` as the starting point for local sales settings:

- set `contact_email`;
- set real Stripe Checkout or Payment Link URLs in `checkout_url`;
- keep secrets out of this JSON file.

Generate sales materials and demo reports:

```bash
python -m app.demo_reports generate
```

The generated landing page and demo reports are written under `sales_pack/`.

Before outreach, review the service deliverables:

- `sales_pack/demo_reports/good_site_demo.html` should read as a stable weekly confirmation report.
- `sales_pack/demo_reports/medium_site_demo.html` should show realistic maintenance work.
- `sales_pack/demo_reports/problem_site_demo.html` should make urgent issues obvious.
- The report header should show `Executive summary`, `Site Health Score`, `Top 3 actions`, owner, next step, and business impact.
- The sales page should position the offer as a recurring white-label report service, not as another dashboard.

If these files are clear enough to send to a prospect, the service is ready for first manual sales attempts.

Use `go_to_market_checklist.md` from the generated sales pack for the first outreach cycle. Treat the service as validated only after real prospects ask for a sample report, agree to a paid trial, or confirm that the report can be forwarded to their clients with minimal editing.

## 4. Run Preflight

```bash
python -m app.preflight
python -m app.preflight --strict true
```

Warnings for missing live Stripe/Admin/SMTP env are expected in local development. Fix them before VPS/live use.

## 5. Start Admin App

```bash
uvicorn app.admin_app:app --host 0.0.0.0 --port 8000
```

Open:

```text
http://localhost:8000/admin/login
```

Admin pages:

- `/` for the public landing page rendered from sales config;
- `/signup` for public post-payment setup details;
- `/client/login` for client magic-link login;
- `/client` for the client dashboard;
- `/client/reports`, `/client/sites`, `/client/settings`, `/client/billing` for client self-service;
- `/admin/signups` for pending signups and approval;
- `/admin/clients` for client operations;
- `/admin/client-requests` for client settings requests;
- `/admin/runs` for weekly run logs;
- `/admin/outbox` for prepared email batches;
- `/webhooks/stripe` for Stripe events.

Artifact routes:

- `/reports/...`;
- `/sales_pack/...`;
- `/client_packages/...`.

For Stripe Checkout, configure the success URL to redirect buyers to:

```text
https://YOUR_DOMAIN/signup?plan=agency-lite&session_id={CHECKOUT_SESSION_ID}
```

Use the matching plan id for each Stripe price/payment link.

## 6. Stripe Webhook

Point Stripe webhook events to:

```text
https://YOUR_DOMAIN/webhooks/stripe
```

Enable these events:

- `checkout.session.completed`;
- `invoice.paid`;
- `invoice.payment_failed`;
- `customer.subscription.deleted`.

For local testing without Stripe signature verification:

```bash
python -m app.billing sync-local --event-file stripe_event.json
python -m app.signups reconcile-payments
```

## 7. Approve Signup

After a buyer submits signup details:

1. Buyer opens `/signup?plan=...` after checkout and submits setup details.
2. Stripe webhook or `app.billing sync-local` records payment status.
3. Run `python -m app.signups reconcile-payments` or click `Reconcile payments`.
4. Open `/admin/signups`.
5. Review `agency_name`, plan, recipient email, payment status, and website URLs.
6. Click `Approve`.

Approve is blocked into `needs_review` when payment is failed/cancelled, missing in production mode, or the Stripe plan does not match the signup plan.

Approval creates/updates:

- CRM lead;
- `data/clients.csv`;
- client package under `client_packages/`;
- local weekly job if configured.

## 8. Operate Clients

Open `/admin/clients`.

Use:

- `Detail` to inspect config, status, latest report, package, and run log;
- `Run now` to generate a single-site report without sending email;
- `Pause` to skip a client in weekly runs;
- `Needs review` when the client or site requires manual attention;
- `Resume` to reactivate a client.

## 8.1 Client Portal

Create a local client login link:

```bash
python -m app.client_portal create-login-link --email client@example.com --base-url http://localhost:8000
```

Client flow:

1. Client opens `/client/login`.
2. Client enters the report/billing email.
3. In local/dev mode, the app shows the magic link on screen.
4. The magic link opens `/client`.
5. The client can view dashboard analytics, reports, sites, billing status, and submit settings or mock billing requests.

Settings requests are stored in:

```text
data/client_settings_requests.csv
```

Mock billing requests are stored in:

```text
data/client_billing_requests.csv
```

Admin reviews them at:

```text
/admin/client-requests
```

Approve applies safe brand/recipient changes to `data/clients.csv`. Reject leaves the weekly workflow unchanged.

Billing requests are reviewed at:

```text
/admin/billing-requests
```

In local/dev mode this is not a real payment processor. Approving a plan change updates `data/subscriptions.csv` with `payment_status=active`; approving an add-on records the operator decision only.

## 9. Weekly Delivery

Manual dry run:

```bash
python -m app.weekly --job-file data/weekly_jobs.local.json --mode dry-run --active-only true
```

Generate reports and outbox without sending:

```bash
python -m app.weekly --job-file data/weekly_jobs.local.json --mode outbox --active-only true
```

Send prepared reports through SMTP:

```bash
python -m app.weekly --job-file data/weekly_jobs.local.json --mode send --active-only true
```

`active-only` skips cancelled, payment failed, paused, and needs-review clients.

## 10. Scheduler

Windows Task Scheduler action:

```text
Program: C:\path\to\.venv\Scripts\python.exe
Arguments: -m app.weekly --job-file data/weekly_jobs.local.json --mode outbox --active-only true
Start in: C:\path\to\site-weekly-report
```

Linux cron example:

```cron
0 9 * * MON cd /srv/site-weekly-report && .venv/bin/python -m app.weekly --job-file data/weekly_jobs.local.json --mode outbox --active-only true
```

Use `send` only after SMTP is verified.

## 11. Backup

Back up these local folders/files:

- `data/clients.csv`;
- `data/subscriptions.csv`;
- `data/client_status.csv`;
- `data/client_portal_sessions.csv`;
- `data/client_settings_requests.csv`;
- `data/pending_signups.csv`;
- `data/*.sqlite`;
- `reports/`;
- `outbox/`;
- `run_logs/`;
- `client_packages/`;
- `.env`.

Do not commit these runtime files to git.

Create an operator backup archive:

```bash
python -m app.backup
```

Include `.env` only for secure machine-level backups:

```bash
python -m app.backup --include-env
```
