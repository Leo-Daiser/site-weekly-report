from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from app.email_sender import send_email_with_attachments, smtp_config_from_env
from app.outbox import (
    create_outbox_for_batch,
    pick_attachments,
    read_manifest,
    write_manifest,
)
from app.models import EmailRunResult
from app.utils import resolve_project_path

console = Console()


def _parse_dry_run(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in ("1", "true", "yes", "on")


def send_prepared_emails(
    batch_dir: Path,
    outbox_dir: Path,
    smtp_overrides: dict[str, object],
    limit: int | None = None,
) -> tuple[int, int]:
    smtp_config = smtp_config_from_env(**smtp_overrides)
    manifest_path = outbox_dir / "manifest.csv"
    entries = read_manifest(manifest_path)

    sent = 0
    failed = 0
    processed = 0

    for entry in entries:
        if entry.status != "prepared":
            continue
        if limit is not None and processed >= limit:
            break
        if not entry.client_email:
            entry.status = "failed"
            entry.error = "client_email is missing"
            failed += 1
            processed += 1
            continue

        text_file = outbox_dir / entry.text_path
        html_file = outbox_dir / entry.html_path
        text_body = text_file.read_text(encoding="utf-8") if text_file.is_file() else ""
        html_body = html_file.read_text(encoding="utf-8") if html_file.is_file() else None
        attachments = pick_attachments(batch_dir, entry)

        if not attachments:
            entry.status = "failed"
            entry.error = "No report attachment found"
            failed += 1
            processed += 1
            continue

        try:
            send_email_with_attachments(
                to_email=entry.client_email,
                subject=entry.subject,
                text_body=text_body,
                html_body=html_body,
                attachments=attachments,
                smtp_config=smtp_config,
            )
            entry.status = "sent"
            entry.error = ""
            sent += 1
        except Exception as exc:
            entry.status = "failed"
            entry.error = f"{type(exc).__name__}: {exc}"
            failed += 1
        processed += 1

    write_manifest(manifest_path, entries)
    return sent, failed


def prepare_and_optionally_send_reports(
    batch_dir: Path,
    outbox_base_dir: Path,
    project_root: Path,
    clients_csv: Path | None = None,
    *,
    dry_run: bool = True,
    smtp_overrides: dict[str, object] | None = None,
    send_limit: int | None = None,
) -> EmailRunResult:
    """Создаёт outbox и при dry_run=False отправляет письма через SMTP."""
    outbox_result = create_outbox_for_batch(
        batch_dir=batch_dir,
        clients_csv=clients_csv,
        outbox_dir=outbox_base_dir,
        project_root=project_root,
    )

    emails_sent = 0
    emails_failed = 0

    if not dry_run:
        sent, failed = send_prepared_emails(
            batch_dir=batch_dir,
            outbox_dir=outbox_result.outbox_dir,
            smtp_overrides=smtp_overrides or {},
            limit=send_limit,
        )
        emails_sent = sent
        emails_failed = failed

    return EmailRunResult(
        outbox_dir=outbox_result.outbox_dir,
        emails_prepared=outbox_result.prepared_count,
        emails_sent=emails_sent,
        emails_failed=emails_failed,
        skipped_count=outbox_result.skipped_count,
        warnings=list(outbox_result.warnings),
    )


def main(
    batch_dir: str = typer.Option(..., "--batch-dir", help="Папка batch-отчёта"),
    clients: str | None = typer.Option(
        None, "--clients", help="CSV клиентов (для client_email)"
    ),
    outbox_dir: str = typer.Option("outbox", "--outbox-dir", help="Папка outbox"),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Только подготовить outbox, не отправлять SMTP",
    ),
    limit: int = typer.Option(10, "--limit", help="Макс. писем для отправки"),
    smtp_host: str | None = typer.Option(None, "--smtp-host"),
    smtp_port: int | None = typer.Option(None, "--smtp-port"),
    smtp_username: str | None = typer.Option(None, "--smtp-username"),
    smtp_password: str | None = typer.Option(None, "--smtp-password"),
    smtp_from_email: str | None = typer.Option(None, "--smtp-from-email"),
    smtp_from_name: str | None = typer.Option(None, "--smtp-from-name"),
    smtp_use_tls: bool | None = typer.Option(None, "--smtp-use-tls/--no-smtp-use-tls"),
) -> None:
    """Подготовка outbox и опциональная отправка отчётов по email."""
    project_root = Path(__file__).resolve().parent.parent
    batch_path = resolve_project_path(batch_dir, project_root)
    outbox_path = resolve_project_path(outbox_dir, project_root)

    if not batch_path.is_dir():
        console.print(f"[red]Ошибка:[/red] batch dir not found: {batch_path}")
        raise typer.Exit(code=1)

    clients_path: Path | None = None
    if clients:
        clients_path = resolve_project_path(clients, project_root)

    console.print("\n[bold]Weekly Site Report — Send[/bold]\n")

    smtp_overrides = {
        "host": smtp_host,
        "port": smtp_port,
        "username": smtp_username,
        "password": smtp_password,
        "from_email": smtp_from_email,
        "from_name": smtp_from_name,
        "use_tls": smtp_use_tls,
    }

    try:
        email_result = prepare_and_optionally_send_reports(
            batch_dir=batch_path,
            outbox_base_dir=outbox_path,
            project_root=project_root,
            clients_csv=clients_path,
            dry_run=_parse_dry_run(dry_run),
            smtp_overrides=smtp_overrides,
            send_limit=limit if limit > 0 else None,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Ошибка:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    for warning in email_result.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")

    console.print(f"Outbox: {email_result.outbox_dir}")
    console.print(f"Prepared emails: {email_result.emails_prepared}")
    console.print(f"Skipped: {email_result.skipped_count}")
    manifest_path = email_result.outbox_dir / "manifest.csv"
    console.print(f"Manifest: {manifest_path}\n")

    entries = read_manifest(manifest_path)
    table = Table(show_header=True)
    table.add_column("Client")
    table.add_column("Email")
    table.add_column("Status")
    for entry in entries:
        if entry.status == "prepared":
            table.add_row(entry.client_name, entry.client_email, entry.status)
    if table.row_count:
        console.print(table)
        console.print()

    if _parse_dry_run(dry_run):
        console.print("[cyan]Dry-run mode:[/cyan] emails were not sent.")
        console.print("Review files in outbox before sending with --no-dry-run")
        return

    console.print(f"[green]Sent:[/green] {email_result.emails_sent}")
    console.print(f"[red]Failed:[/red] {email_result.emails_failed}")
    console.print(f"Updated manifest: {manifest_path}\n")


if __name__ == "__main__":
    typer.run(main)
