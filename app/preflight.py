from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

import typer
from jinja2 import Environment, FileSystemLoader, select_autoescape
from rich.console import Console
from rich.table import Table

from app.models import PreflightReport
from app.preflight_checks import PreflightContext, run_preflight_checks
from app.utils import resolve_project_path

console = Console()

FormatChoice = Literal["console", "md", "both"]

DEFAULT_CLIENTS_CSV = "data/clients.example.csv"
DEFAULT_WEEKLY_JOB = "data/weekly_jobs.example.json"
DEFAULT_PRICING_FILE = "data/pricing.example.json"
DEFAULT_CRM_PATH = "data/leads_crm.csv"
DEFAULT_OUTPUT_DIR = "preflight_reports"
DEFAULT_BRANDING_FILE = "branding/default.json"


def _parse_bool_option(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _status_style(status: str) -> str:
    styles = {
        "pass": "green",
        "warning": "yellow",
        "fail": "red",
        "skipped": "dim",
    }
    return styles.get(status, "white")


def print_console_report(report: PreflightReport) -> None:
    ready_label = "yes" if report.ready else "no"
    ready_style = "green" if report.ready else "red bold"
    console.print("\n[bold]Preflight report[/bold]\n")
    console.print(f"READY: [{ready_style}]{ready_label}[/]\n")

    table = Table(show_header=True)
    table.add_column("Status")
    table.add_column("Check")
    table.add_column("Message")
    for item in report.results:
        table.add_row(
            f"[{_status_style(item.status)}]{item.status.upper()}[/]",
            item.name,
            item.message[:120],
        )
    console.print(table)

    console.print(
        f"\n[bold]Summary[/bold]\n"
        f"Passed: {report.passed}\n"
        f"Warnings: {report.warnings}\n"
        f"Failed: {report.failed}\n"
        f"Skipped: {report.skipped}\n"
    )

    recommendations = [r.recommendation for r in report.results if r.recommendation]
    if recommendations:
        console.print("[bold]Recommendation(s):[/bold]")
        for text in recommendations:
            console.print(f"- {text}")


def write_markdown_report(
    report: PreflightReport,
    *,
    output_dir: Path,
    template_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = output_dir / f"preflight_{stamp}.md"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    content = env.get_template("preflight_report.md.j2").render(
        finished_at=report.finished_at,
        ready=report.ready,
        passed=report.passed,
        warnings=report.warnings,
        failed=report.failed,
        skipped=report.skipped,
        results=report.results,
    )
    path.write_text(content, encoding="utf-8")
    return path


def main(
    clients_csv: str = typer.Option(DEFAULT_CLIENTS_CSV, "--clients-csv"),
    weekly_job_file: str = typer.Option(DEFAULT_WEEKLY_JOB, "--weekly-job-file"),
    pricing_file: str = typer.Option(DEFAULT_PRICING_FILE, "--pricing-file"),
    crm_path: str = typer.Option(DEFAULT_CRM_PATH, "--crm-path"),
    output_dir: str = typer.Option(DEFAULT_OUTPUT_DIR, "--output-dir"),
    check_smtp: str = typer.Option("false", "--check-smtp"),
    check_pdf: str = typer.Option("false", "--check-pdf"),
    run_smoke_tests: str = typer.Option("true", "--run-smoke-tests"),
    strict: str = typer.Option("false", "--strict"),
    output_format: FormatChoice = typer.Option("console", "--format"),
) -> None:
    """Check project readiness before sending reports to clients."""
    root = _project_root()
    clients_path = resolve_project_path(clients_csv, root)
    weekly_path = resolve_project_path(weekly_job_file, root)
    pricing_path = resolve_project_path(pricing_file, root)
    crm_file = resolve_project_path(crm_path, root)
    reports_dir = resolve_project_path(output_dir, root)
    branding_path = resolve_project_path(DEFAULT_BRANDING_FILE, root)

    ctx = PreflightContext(
        project_root=root,
        clients_csv=clients_path,
        weekly_job_file=weekly_path,
        pricing_file=pricing_path,
        crm_path=crm_file,
        branding_file=branding_path,
        check_smtp=_parse_bool_option(check_smtp),
        check_pdf=_parse_bool_option(check_pdf),
        run_smoke_tests=_parse_bool_option(run_smoke_tests),
        strict=_parse_bool_option(strict),
        is_example_clients="clients.example.csv" in clients_path.name,
    )

    report = run_preflight_checks(ctx)
    fmt = output_format.lower()

    if fmt in ("console", "both"):
        print_console_report(report)

    if fmt in ("md", "both"):
        md_path = write_markdown_report(
            report,
            output_dir=reports_dir,
            template_dir=root / "templates",
        )
        console.print(f"\nMarkdown report: {md_path}")

    if not report.ready:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    typer.run(main)
