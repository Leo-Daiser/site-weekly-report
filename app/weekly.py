from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

import typer
from rich.console import Console

from app.batch import load_clients_csv, run_batch_from_clients_csv
from app.branding import load_branding_config
from app.email_sender import smtp_config_from_env
from app.models import WeeklyJobConfig, WeeklyMode, WeeklyRunLog
from app.run_logs import path_for_log, utc_now_iso, weekly_run_id, write_weekly_run_log
from app.send_reports import prepare_and_optionally_send_reports
from app.utils import resolve_project_path

console = Console()

ModeChoice = Literal["dry-run", "generate", "outbox", "send"]


def load_weekly_job(path: Path) -> WeeklyJobConfig:
    if not path.is_file():
        raise FileNotFoundError(f"Weekly job file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return WeeklyJobConfig.model_validate(data)


def _resolve_format(job_format: str, cli_format: str | None) -> str:
    fmt = (cli_format or job_format).lower()
    if fmt not in ("html", "pdf", "both"):
        raise ValueError("--format должен быть html, pdf или both")
    return fmt


def _smtp_overrides_from_cli(
    smtp_host: str | None,
    smtp_port: int | None,
    smtp_username: str | None,
    smtp_password: str | None,
    smtp_from_email: str | None,
    smtp_from_name: str | None,
    smtp_use_tls: bool | None,
) -> dict[str, object]:
    return {
        "host": smtp_host,
        "port": smtp_port,
        "username": smtp_username,
        "password": smtp_password,
        "from_email": smtp_from_email,
        "from_name": smtp_from_name,
        "use_tls": smtp_use_tls,
    }


def validate_smtp_before_send(smtp_overrides: dict[str, object]) -> None:
    """Проверяет полноту SMTP без подключения к серверу."""
    smtp_config_from_env(**smtp_overrides)


def _would_create_outbox(mode: WeeklyMode) -> bool:
    return mode in ("outbox", "send")


def _would_send_email(mode: WeeklyMode) -> bool:
    return mode == "send"


def _would_generate_reports(mode: WeeklyMode) -> bool:
    return mode != "dry-run"


def execute_weekly_run(
    job: WeeklyJobConfig,
    *,
    mode: WeeklyMode,
    project_root: Path,
    run_logs_dir: Path,
    clients_limit: int | None = None,
    report_format: str | None = None,
    smtp_overrides: dict[str, object] | None = None,
) -> tuple[WeeklyRunLog, Path]:
    started = utc_now_iso()
    run_id = weekly_run_id()
    log_path = run_logs_dir / f"{run_id}.json"

    clients_path = resolve_project_path(job.clients_csv, project_root)
    output_dir = resolve_project_path(job.output_dir, project_root)
    outbox_base = resolve_project_path(job.outbox_dir, project_root)
    db_path = resolve_project_path(job.db_path, project_root)
    limit = clients_limit if clients_limit is not None else job.limit
    fmt = _resolve_format(job.format, report_format)
    smtp = smtp_overrides or {}

    log = WeeklyRunLog(
        run_id=run_id,
        job_name=job.job_name,
        mode=mode,
        started_at=started,
        clients_csv=path_for_log(clients_path, project_root),
    )

    exit_code = 0

    try:
        if not clients_path.is_file():
            raise FileNotFoundError(f"Clients CSV not found: {clients_path}")

        rows = load_clients_csv(clients_path)
        effective_rows = rows[:limit] if limit is not None else rows
        log.total = len(effective_rows)

        if job.branding_file:
            branding_path = resolve_project_path(job.branding_file, project_root)
            file_config = load_branding_config(str(branding_path))
        else:
            file_config = load_branding_config(None)

        if mode == "dry-run":
            if job.send_email:
                console.print(
                    "[dim]Note:[/dim] job send_email=true ignored unless --mode send"
                )

            log.successful = log.total
            log.success = True
            _print_dry_run_plan(
                job,
                mode,
                clients_path,
                len(effective_rows),
                path_for_log(log_path, project_root) or str(log_path),
            )
        else:
            if mode == "send":
                validate_smtp_before_send(smtp)

            batch_result = run_batch_from_clients_csv(
                clients_path=clients_path,
                output_dir=output_dir,
                db_path=db_path,
                project_root=project_root,
                default_format=fmt,
                default_max_links=job.max_links,
                default_timeout=job.timeout,
                file_config=file_config,
                continue_on_error=job.continue_on_error,
                limit=limit,
            )

            log.batch_dir = path_for_log(batch_result.batch_dir, project_root)
            log.summary_csv = path_for_log(batch_result.summary_csv, project_root)
            log.summary_html = path_for_log(batch_result.summary_html, project_root)
            log.successful = batch_result.successful
            log.failed = batch_result.failed
            log.total = batch_result.total

            if _would_create_outbox(mode):
                email_result = prepare_and_optionally_send_reports(
                    batch_dir=batch_result.batch_dir,
                    outbox_base_dir=outbox_base,
                    project_root=project_root,
                    clients_csv=clients_path,
                    dry_run=not _would_send_email(mode),
                    smtp_overrides=smtp,
                )
                log.outbox_dir = path_for_log(email_result.outbox_dir, project_root)
                log.emails_prepared = email_result.emails_prepared
                log.emails_sent = email_result.emails_sent
                log.emails_failed = email_result.emails_failed

            log.success = True
            _print_finished(mode, log)

    except Exception as exc:
        log.success = False
        log.error = f"{type(exc).__name__}: {exc}"
        exit_code = 1
        console.print(f"[red]Weekly run failed:[/red] {log.error}")
    finally:
        log.finished_at = utc_now_iso()
        written = write_weekly_run_log(run_logs_dir, log)
        if mode != "dry-run":
            console.print(f"Run log: {path_for_log(written, project_root)}")

    if exit_code:
        raise typer.Exit(code=exit_code)

    return log, log_path


def _print_dry_run_plan(
    job: WeeklyJobConfig,
    mode: WeeklyMode,
    clients_path: Path,
    clients_found: int,
    log_path: Path,
) -> None:
    console.print("\n[bold]Weekly job dry-run[/bold]")
    console.print(f"Job: {job.job_name}")
    console.print(f"Clients CSV: {clients_path}")
    console.print(f"Clients found: {clients_found}")
    console.print(f"Mode: {mode}")
    console.print(
        f"Would generate reports: {'yes' if _would_generate_reports(mode) else 'no'}"
    )
    console.print(
        f"Would create outbox: {'yes' if _would_create_outbox(mode) else 'no'}"
    )
    console.print(
        f"Would send email: {'yes' if _would_send_email(mode) else 'no'}"
    )
    console.print(f"Run log: {log_path}\n")


def _print_finished(mode: WeeklyMode, log: WeeklyRunLog) -> None:
    console.print("\n[bold]Weekly run finished[/bold]")
    console.print(f"Mode: {mode}")
    if log.batch_dir:
        console.print(f"Batch dir: {log.batch_dir}")
    if log.summary_html:
        console.print(f"Summary HTML: {log.summary_html}")
    if log.outbox_dir:
        console.print(f"Outbox dir: {log.outbox_dir}")
    console.print(f"Total: {log.total}")
    console.print(f"Successful: {log.successful}")
    console.print(f"Failed: {log.failed}")
    console.print(f"Emails prepared: {log.emails_prepared}")
    console.print(f"Emails sent: {log.emails_sent}")
    console.print()


def main(
    job_file: str = typer.Option(
        ..., "--job-file", help="JSON-файл weekly job"
    ),
    mode: ModeChoice = typer.Option(
        "dry-run",
        "--mode",
        help="dry-run | generate | outbox | send",
    ),
    limit: int | None = typer.Option(
        None, "--limit", help="Ограничить число клиентов из CSV"
    ),
    report_format: str | None = typer.Option(
        None, "--format", help="Переопределить format из job-файла"
    ),
    run_logs_dir: str = typer.Option(
        "run_logs", "--run-logs-dir", help="Папка для JSON run-log"
    ),
    smtp_host: str | None = typer.Option(None, "--smtp-host"),
    smtp_port: int | None = typer.Option(None, "--smtp-port"),
    smtp_username: str | None = typer.Option(None, "--smtp-username"),
    smtp_password: str | None = typer.Option(None, "--smtp-password"),
    smtp_from_email: str | None = typer.Option(None, "--smtp-from-email"),
    smtp_from_name: str | None = typer.Option(None, "--smtp-from-name"),
    smtp_use_tls: bool | None = typer.Option(None, "--smtp-use-tls/--no-smtp-use-tls"),
) -> None:
    """Еженедельный оркестратор: batch, outbox и опциональная отправка email."""
    project_root = Path(__file__).resolve().parent.parent

    try:
        job_path = resolve_project_path(job_file, project_root)
        job = load_weekly_job(job_path)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Ошибка:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    logs_dir = resolve_project_path(run_logs_dir, project_root)
    smtp_overrides = _smtp_overrides_from_cli(
        smtp_host,
        smtp_port,
        smtp_username,
        smtp_password,
        smtp_from_email,
        smtp_from_name,
        smtp_use_tls,
    )

    try:
        execute_weekly_run(
            job,
            mode=mode,
            project_root=project_root,
            run_logs_dir=logs_dir,
            clients_limit=limit,
            report_format=report_format,
            smtp_overrides=smtp_overrides,
        )
    except typer.Exit:
        raise
    except ValueError as exc:
        console.print(f"[red]Ошибка:[/red] {exc}")
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    typer.run(main)
