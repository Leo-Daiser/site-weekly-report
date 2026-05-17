from __future__ import annotations

import csv
import importlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.branding import load_branding_config, validate_brand_color
from app.models import PreflightCheckResult, PreflightReport, WeeklyJobConfig
from app.pdf_exporter import CHROMIUM_INSTALL_HINT, _find_chromium_executable
from app.pricing import get_plan, load_pricing_config
from app.utils import resolve_project_path

REQUIRED_PROJECT_PATHS = (
    "app/main.py",
    "app/batch.py",
    "app/weekly.py",
    "app/onboard.py",
    "app/crm.py",
    "app/proposal.py",
    "app/convert_client.py",
    "app/admin_app.py",
    "app/admin_clients.py",
    "app/admin_views.py",
    "app/billing.py",
    "app/signups.py",
    "app/pipeline.py",
    "templates/report.html.j2",
    "data/clients.example.csv",
    "data/weekly_jobs.example.json",
    "data/sales_pack.local.example.json",
    "data/pricing.example.json",
    "branding/default.json",
    "reports/.gitkeep",
    "outbox/.gitkeep",
    "run_logs/.gitkeep",
    "leads/.gitkeep",
    "crm_exports/.gitkeep",
    "proposals/.gitkeep",
    "client_packages/.gitkeep",
)

GITIGNORE_REQUIRED_PATTERNS = (
    "reports/*",
    "!reports/.gitkeep",
    "outbox/*",
    "!outbox/.gitkeep",
    "run_logs/*",
    "!run_logs/.gitkeep",
    "leads/*",
    "!leads/.gitkeep",
    "crm_exports/*",
    "!crm_exports/.gitkeep",
    "proposals/*",
    "!proposals/.gitkeep",
    "client_packages/*",
    "!client_packages/.gitkeep",
    "data/*.sqlite",
    "data/leads_crm.csv",
    "data/clients.csv",
    "data/clients.local.csv",
    "data/weekly_jobs.local.json",
    "data/subscriptions.csv",
    "data/pending_signups.csv",
    "data/client_status.csv",
    ".env",
    "__pycache__/",
    "*.pyc",
    ".pytest_cache/",
)

CLIENTS_CSV_COLUMNS = (
    "client_name",
    "client_email",
    "brand_name",
    "url",
    "brand_color",
    "brand_logo",
    "footer_text",
    "format",
    "max_links",
    "max_pages",
    "screenshot",
    "timeout",
)

WEEKLY_JOB_FIELDS = (
    "job_name",
    "clients_csv",
    "output_dir",
    "outbox_dir",
    "db_path",
    "branding_file",
    "format",
    "max_links",
    "max_pages",
    "screenshot",
    "timeout",
    "create_outbox",
    "send_email",
    "continue_on_error",
)

REQUIRED_PRICING_PLANS = ("starter", "agency-lite", "agency")

RUNTIME_DIRS = (
    "reports",
    "outbox",
    "run_logs",
    "leads",
    "crm_exports",
    "proposals",
    "client_packages",
    "data",
)

GIT_ARTIFACT_MARKERS = (
    "reports/",
    "outbox/",
    "run_logs/",
    "leads/",
    "crm_exports/",
    "proposals/",
    "client_packages/",
    "preflight_reports/",
    "data/checks.sqlite",
    "data/leads_crm.csv",
    "data/clients.csv",
    "data/clients.local.csv",
    "data/weekly_jobs.local.json",
    ".env",
    "__pycache__",
    ".pytest_cache",
)

SMTP_ENV_VARS = (
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_FROM_EMAIL",
    "SMTP_FROM_NAME",
    "SMTP_USE_TLS",
)

ADMIN_ENV_VARS = ("ADMIN_PASSWORD",)

STRIPE_ENV_VARS = (
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
)

SMOKE_MODULES = (
    "app.main",
    "app.batch",
    "app.weekly",
    "app.onboard",
    "app.crm",
    "app.proposal",
    "app.convert_client",
    "app.admin_app",
    "app.billing",
    "app.signups",
)

DEMO_EMAIL_MARKERS = ("demo@example.com", "client@example.com", "example.com")


@dataclass
class PreflightContext:
    project_root: Path
    clients_csv: Path
    weekly_job_file: Path
    pricing_file: Path
    crm_path: Path
    branding_file: Path
    check_smtp: bool = False
    check_pdf: bool = False
    run_smoke_tests: bool = True
    strict: bool = False
    is_example_clients: bool = False


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _result(
    name: str,
    status: str,
    message: str,
    *,
    details: str | None = None,
    recommendation: str | None = None,
) -> PreflightCheckResult:
    return PreflightCheckResult(
        name=name,
        status=status,  # type: ignore[arg-type]
        message=message,
        details=details,
        recommendation=recommendation,
    )


def compute_ready(results: list[PreflightCheckResult], *, strict: bool) -> bool:
    for item in results:
        if item.status == "fail":
            return False
        if strict and item.status == "warning":
            return False
    return True


def summarize_report(
    results: list[PreflightCheckResult],
    *,
    started_at: str,
    finished_at: str,
    strict: bool,
) -> PreflightReport:
    passed = sum(1 for r in results if r.status == "pass")
    warnings = sum(1 for r in results if r.status == "warning")
    failed = sum(1 for r in results if r.status == "fail")
    skipped = sum(1 for r in results if r.status == "skipped")
    return PreflightReport(
        started_at=started_at,
        finished_at=finished_at,
        ready=compute_ready(results, strict=strict),
        checks_total=len(results),
        passed=passed,
        warnings=warnings,
        failed=failed,
        skipped=skipped,
        results=results,
    )


def check_project_structure(ctx: PreflightContext) -> PreflightCheckResult:
    missing = [
        rel for rel in REQUIRED_PROJECT_PATHS if not (ctx.project_root / rel).exists()
    ]
    if missing:
        return _result(
            "Project structure",
            "fail",
            f"Missing {len(missing)} required path(s).",
            details=", ".join(missing),
            recommendation="Restore missing files or folders from the repository template.",
        )
    return _result(
        "Project structure",
        "pass",
        f"All {len(REQUIRED_PROJECT_PATHS)} required paths are present.",
    )


def check_gitignore(ctx: PreflightContext) -> PreflightCheckResult:
    path = ctx.project_root / ".gitignore"
    if not path.is_file():
        return _result(
            ".gitignore",
            "fail",
            ".gitignore file is missing.",
            recommendation="Add a .gitignore file with runtime artifact rules.",
        )
    content = path.read_text(encoding="utf-8")
    missing = [pattern for pattern in GITIGNORE_REQUIRED_PATTERNS if pattern not in content]
    if missing:
        return _result(
            ".gitignore",
            "fail",
            f"Missing {len(missing)} required ignore pattern(s).",
            details=", ".join(missing),
            recommendation="Update .gitignore to exclude local runtime artifacts.",
        )
    return _result(
        ".gitignore",
        "pass",
        "Required ignore patterns are present.",
    )


def check_example_files(ctx: PreflightContext) -> PreflightCheckResult:
    paths = (
        ctx.project_root / "data/clients.example.csv",
        ctx.project_root / "data/weekly_jobs.example.json",
        ctx.project_root / "data/pricing.example.json",
        ctx.branding_file,
    )
    errors: list[str] = []
    for path in paths:
        try:
            if path.suffix == ".json":
                json.loads(path.read_text(encoding="utf-8"))
            elif path.suffix == ".csv":
                with path.open(encoding="utf-8-sig", newline="") as handle:
                    list(csv.DictReader(handle))
        except OSError as exc:
            errors.append(f"{path.name}: {exc}")
        except (json.JSONDecodeError, csv.Error) as exc:
            errors.append(f"{path.name}: {exc}")

    if errors:
        return _result(
            "Example files",
            "fail",
            "Failed to read example configuration files.",
            details="; ".join(errors),
        )
    return _result("Example files", "pass", "Example configuration files are readable.")


def check_clients_csv(ctx: PreflightContext) -> PreflightCheckResult:
    path = ctx.clients_csv
    if not path.is_file():
        return _result(
            "Clients CSV",
            "fail",
            f"Clients CSV not found: {path}",
            recommendation="Create the file or pass --clients-csv with a valid path.",
        )

    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                return _result("Clients CSV", "fail", "Clients CSV has no header row.")
            missing_cols = [c for c in CLIENTS_CSV_COLUMNS if c not in reader.fieldnames]
            if missing_cols:
                return _result(
                    "Clients CSV",
                    "fail",
                    "Clients CSV is missing required columns.",
                    details=", ".join(missing_cols),
                )
            rows = list(reader)
    except OSError as exc:
        return _result("Clients CSV", "fail", f"Cannot read clients CSV: {exc}")
    except csv.Error as exc:
        return _result("Clients CSV", "fail", f"Invalid CSV: {exc}")

    if not rows:
        return _result(
            "Clients CSV",
            "fail",
            "Clients CSV has no data rows.",
            recommendation="Add at least one client row before running batch/weekly.",
        )

    row_errors: list[str] = []
    demo_warnings: list[str] = []
    for index, row in enumerate(rows, start=2):
        url = (row.get("url") or "").strip()
        if not url:
            row_errors.append(f"line {index}: empty url")
        fmt = (row.get("format") or "").strip().lower()
        if fmt not in ("html", "pdf", "both"):
            row_errors.append(f"line {index}: invalid format '{fmt}'")
        try:
            int((row.get("max_links") or "").strip())
        except ValueError:
            row_errors.append(f"line {index}: max_links is not an integer")
        try:
            float((row.get("timeout") or "").strip())
        except ValueError:
            row_errors.append(f"line {index}: timeout is not a number")

        if not ctx.is_example_clients:
            email = (row.get("client_email") or "").strip().lower()
            if any(marker in email for marker in DEMO_EMAIL_MARKERS):
                demo_warnings.append(f"line {index}: demo/example email '{email}'")

    if row_errors:
        return _result(
            "Clients CSV",
            "fail",
            "Clients CSV validation failed.",
            details="; ".join(row_errors[:8]),
        )

    if demo_warnings:
        return _result(
            "Clients CSV",
            "warning",
            f"Validated {len(rows)} row(s); demo emails detected.",
            details="; ".join(demo_warnings[:5]),
            recommendation="Replace demo emails before sending reports to real clients.",
        )

    return _result(
        "Clients CSV",
        "pass",
        f"Validated {len(rows)} client row(s) in {path.name}.",
    )


def check_weekly_job(ctx: PreflightContext) -> PreflightCheckResult:
    path = ctx.weekly_job_file
    if not path.is_file():
        return _result(
            "Weekly job",
            "fail",
            f"Weekly job file not found: {path}",
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        job = WeeklyJobConfig.model_validate(data)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return _result("Weekly job", "fail", f"Invalid weekly job JSON: {exc}")

    missing_fields = [field for field in WEEKLY_JOB_FIELDS if field not in data]
    details_parts: list[str] = []
    if missing_fields:
        details_parts.append(f"missing keys: {', '.join(missing_fields)}")

    clients_path = resolve_project_path(job.clients_csv, ctx.project_root)
    if not clients_path.is_file():
        details_parts.append(f"clients_csv not found: {job.clients_csv}")

    if job.format not in ("html", "pdf", "both"):
        return _result(
            "Weekly job",
            "fail",
            f"Invalid weekly job format: {job.format}",
        )

    if job.send_email:
        return _result(
            "Weekly job",
            "warning",
            "send_email=true in weekly job config.",
            details="; ".join(details_parts) if details_parts else None,
            recommendation="Use weekly mode 'send' only when SMTP is configured; dry-run/outbox are safer.",
        )

    if details_parts:
        return _result(
            "Weekly job",
            "warning",
            "Weekly job loaded with warnings.",
            details="; ".join(details_parts),
            recommendation="Fix clients_csv path or add missing JSON keys.",
        )

    message = "Weekly job config is valid."
    if not job.send_email:
        message += " send_email=false (safe by default)."
    return _result("Weekly job", "pass", message)


def check_pricing(ctx: PreflightContext) -> PreflightCheckResult:
    try:
        config, warnings = load_pricing_config(ctx.pricing_file)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return _result("Pricing", "fail", f"Cannot load pricing config: {exc}")

    missing_plans = [plan_id for plan_id in REQUIRED_PRICING_PLANS if plan_id not in config.plans]
    plan_errors: list[str] = []
    for plan_id in REQUIRED_PRICING_PLANS:
        if plan_id not in config.plans:
            continue
        plan = config.plans[plan_id]
        try:
            get_plan(config, plan_id)
        except ValueError as exc:
            plan_errors.append(str(exc))
        if not plan.features:
            plan_errors.append(f"{plan_id}: empty features list")

    if missing_plans or plan_errors:
        return _result(
            "Pricing",
            "fail",
            "Pricing config is incomplete.",
            details="; ".join(missing_plans + plan_errors),
        )

    if warnings:
        return _result(
            "Pricing",
            "warning",
            "Using fallback/default pricing config.",
            details="; ".join(warnings),
        )

    return _result(
        "Pricing",
        "pass",
        f"Pricing config OK ({len(config.plans)} plan(s)).",
    )


def check_branding(ctx: PreflightContext) -> PreflightCheckResult:
    if not ctx.branding_file.is_file():
        return _result(
            "Branding",
            "fail",
            f"Branding file not found: {ctx.branding_file}",
        )

    warnings: list[str] = []
    try:
        branding = load_branding_config(str(ctx.branding_file))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return _result("Branding", "fail", f"Cannot load branding: {exc}")

    validate_brand_color(branding.brand_color, warnings)
    if branding.logo_path:
        logo = Path(branding.logo_path)
        if not logo.is_file():
            if not (ctx.project_root / branding.logo_path).is_file():
                warnings.append(f"logo_path file not found: {branding.logo_path}")

    if warnings:
        return _result(
            "Branding",
            "warning",
            "Branding config loaded with warnings.",
            details="; ".join(warnings),
        )
    return _result("Branding", "pass", "Branding config is valid.")


def check_runtime_folders(ctx: PreflightContext) -> PreflightCheckResult:
    missing = [name for name in RUNTIME_DIRS if not (ctx.project_root / name).is_dir()]
    if missing:
        return _result(
            "Runtime folders",
            "fail",
            f"Missing runtime folder(s): {', '.join(missing)}",
            recommendation="Create folders manually or copy .gitkeep templates from the repo.",
        )
    return _result(
        "Runtime folders",
        "pass",
        f"All {len(RUNTIME_DIRS)} runtime folders exist.",
    )


def check_playwright_pdf(ctx: PreflightContext) -> PreflightCheckResult:
    if not ctx.check_pdf:
        return _result(
            "Playwright PDF",
            "skipped",
            "PDF check disabled (use --check-pdf true).",
        )

    try:
        import playwright  # noqa: F401
    except ImportError:
        return _result(
            "Playwright PDF",
            "fail",
            "Playwright is not installed.",
            recommendation="pip install playwright\npython -m playwright install chromium",
        )

    if _find_chromium_executable() is None:
        return _result(
            "Playwright PDF",
            "fail",
            "Chromium browser is not available for Playwright.",
            recommendation=CHROMIUM_INSTALL_HINT,
        )

    return _result(
        "Playwright PDF",
        "pass",
        "Playwright and Chromium appear to be available.",
    )


def check_smtp_config(ctx: PreflightContext) -> PreflightCheckResult:
    if not ctx.check_smtp:
        return _result(
            "SMTP config",
            "skipped",
            "SMTP check disabled (use --check-smtp true).",
        )

    missing = [name for name in SMTP_ENV_VARS if not os.environ.get(name, "").strip()]
    if missing:
        return _result(
            "SMTP config",
            "fail",
            f"Missing SMTP environment variable(s): {', '.join(missing)}",
            recommendation="Set SMTP_* variables in .env before using weekly mode send.",
        )
    return _result("SMTP config", "pass", "All SMTP environment variables are set.")


def check_smoke_tests(ctx: PreflightContext) -> PreflightCheckResult:
    if not ctx.run_smoke_tests:
        return _result(
            "Smoke tests",
            "skipped",
            "Smoke tests disabled (use --run-smoke-tests true).",
        )

    errors: list[str] = []
    for module_name in SMOKE_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")

    try:
        load_pricing_config(ctx.pricing_file)
        WeeklyJobConfig.model_validate(
            json.loads(ctx.weekly_job_file.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        errors.append(f"config parse: {exc}")

    if errors:
        return _result(
            "Smoke tests",
            "fail",
            "Module import or config parsing failed.",
            details="; ".join(errors),
        )
    return _result(
        "Smoke tests",
        "pass",
        f"Imported {len(SMOKE_MODULES)} CLI modules; configs parse OK.",
    )


def check_operator_config(ctx: PreflightContext) -> PreflightCheckResult:
    warnings: list[str] = []
    errors: list[str] = []

    sales_config = ctx.project_root / "data/sales_pack.local.example.json"
    if not sales_config.is_file():
        errors.append("data/sales_pack.local.example.json is missing")
    else:
        try:
            json.loads(sales_config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"sales_pack.local.example.json: {exc}")

    try:
        weekly_data = json.loads(ctx.weekly_job_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"weekly job config unreadable: {exc}")
        weekly_data = {}

    if weekly_data:
        missing_weekly = [
            field for field in ("max_pages", "screenshot") if field not in weekly_data
        ]
        if missing_weekly:
            warnings.append(
                "weekly job config missing operator fields: "
                + ", ".join(missing_weekly)
            )

    missing_admin = [
        name for name in ADMIN_ENV_VARS if not os.environ.get(name, "").strip()
    ]
    if missing_admin:
        warnings.append(
            "admin password env is not set: " + ", ".join(missing_admin)
        )

    missing_stripe = [
        name for name in STRIPE_ENV_VARS if not os.environ.get(name, "").strip()
    ]
    if missing_stripe:
        warnings.append(
            "Stripe env is not set: " + ", ".join(missing_stripe)
        )

    if errors:
        return _result(
            "Operator config",
            "fail",
            "Operator MVP configuration has blocking issue(s).",
            details="; ".join(errors),
        )
    if warnings:
        return _result(
            "Operator config",
            "warning",
            "Operator MVP can run locally, but production env is incomplete.",
            details="; ".join(warnings),
            recommendation="Set ADMIN_PASSWORD and Stripe env on the VPS before live use.",
        )
    return _result(
        "Operator config",
        "pass",
        "Operator config files and production env are present.",
    )


def check_git_status(ctx: PreflightContext) -> PreflightCheckResult:
    git_dir = ctx.project_root / ".git"
    if not git_dir.exists():
        return _result(
            "Git status",
            "skipped",
            "Not a git repository.",
        )

    try:
        proc = subprocess.run(
            ["git", "status", "--short"],
            cwd=ctx.project_root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _result(
            "Git status",
            "skipped",
            f"Could not run git status: {exc}",
        )

    if proc.returncode != 0:
        return _result(
            "Git status",
            "skipped",
            "git status failed.",
            details=(proc.stderr or proc.stdout or "").strip() or None,
        )

    tracked_artifacts: list[str] = []
    for line in proc.stdout.splitlines():
        path_part = line[3:].strip() if len(line) > 3 else line.strip()
        if not path_part:
            continue
        normalized = path_part.replace("\\", "/")
        for marker in GIT_ARTIFACT_MARKERS:
            is_dir_marker = marker.endswith("/") or "/" in marker
            if normalized == marker.rstrip("/") or (is_dir_marker and normalized.startswith(marker)):
                tracked_artifacts.append(normalized)
                break

    if not tracked_artifacts:
        return _result(
            "Git status",
            "pass",
            "No runtime artifacts appear in git status.",
        )

    status = "warning"
    recommendation = "Add paths to .gitignore and remove tracked runtime files from git."
    return _result(
        "Git status",
        status,
        f"Found {len(tracked_artifacts)} runtime artifact(s) in git status.",
        details=", ".join(tracked_artifacts[:10]),
        recommendation=recommendation,
    )


def run_preflight_checks(ctx: PreflightContext) -> PreflightReport:
    started = utc_now_iso()
    checks = [
        check_project_structure,
        check_gitignore,
        check_example_files,
        check_clients_csv,
        check_weekly_job,
        check_pricing,
        check_branding,
        check_runtime_folders,
        check_playwright_pdf,
        check_smtp_config,
        check_smoke_tests,
        check_operator_config,
        check_git_status,
    ]
    results = [checker(ctx) for checker in checks]
    finished = utc_now_iso()
    return summarize_report(results, started_at=started, finished_at=finished, strict=ctx.strict)
