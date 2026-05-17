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

- `/signup` for public post-payment setup details;
- `/admin/signups` for pending signups and approval;
- `/admin/clients` for client operations;
- `/admin/runs` for weekly run logs;
- `/admin/outbox` for prepared email batches;
- `/webhooks/stripe` for Stripe events.

For Stripe Checkout, configure the success URL to redirect buyers to:

```text
https://YOUR_DOMAIN/signup?plan=agency-lite
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
```

## 7. Approve Signup

After a buyer submits signup details:

1. Buyer opens `/signup?plan=...` after checkout and submits setup details.
2. Open `/admin/signups`.
3. Review `agency_name`, plan, recipient email, and website URLs.
4. Click `Approve`.

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
- `data/pending_signups.csv`;
- `data/*.sqlite`;
- `reports/`;
- `outbox/`;
- `run_logs/`;
- `client_packages/`;
- `.env`.

Do not commit these runtime files to git.
