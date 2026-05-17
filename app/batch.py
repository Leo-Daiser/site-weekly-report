from __future__ import annotations

import csv
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Literal

import typer
from rich.console import Console

from app.branding import load_branding_config, resolve_branding
from app.config import (
    DEFAULT_DB_PATH,
    DEFAULT_MAX_LINKS,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_TIMEOUT,
)
from app.models import BatchRunResult, BrandingConfig, ReportRunResult
from app.pipeline import SingleReportError, run_single_report
from app.utils import batch_run_dir_name, resolve_project_path

console = Console()

FormatChoice = Literal["html", "pdf", "both"]

CSV_COLUMNS = (
    "client_name",
    "client_email",
    "brand_name",
    "url",
    "brand_color",
    "brand_logo",
    "footer_text",
    "format",
    "max_links",
    "timeout",
)

SUMMARY_CSV_COLUMNS = (
    "client_name",
    "brand_name",
    "url",
    "normalized_domain",
    "success",
    "scan_ok",
    "error",
    "status_code",
    "warnings_count",
    "broken_links_count",
    "changes_count",
    "previous_check_found",
    "health_score",
    "health_label",
    "critical_issues",
    "high_issues",
    "medium_issues",
    "low_issues",
    "top_actions",
    "html_path",
    "pdf_path",
)


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _optional_int(value: str | None) -> int | None:
    text = _empty_to_none(value)
    if text is None:
        return None
    return int(text)


def _optional_float(value: str | None) -> float | None:
    text = _empty_to_none(value)
    if text is None:
        return None
    return float(text)


def load_clients_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"Clients CSV not found: {path}")

    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file is empty or has no header")

        rows: list[dict[str, str]] = []
        for index, row in enumerate(reader, start=2):
            client_name = _empty_to_none(row.get("client_name"))
            url = _empty_to_none(row.get("url"))
            if not client_name:
                raise ValueError(f"Row {index}: client_name is required")
            if not url:
                raise ValueError(f"Row {index}: url is required")
            rows.append({key: (row.get(key) or "") for key in row})

    return rows


def _relative_to_batch(path: str | None, batch_dir: Path) -> str:
    if not path:
        return "-"
    try:
        return Path(path).relative_to(batch_dir).as_posix()
    except ValueError:
        return Path(path).name


def write_summary_csv(path: Path, results: list[ReportRunResult], batch_dir: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_CSV_COLUMNS)
        writer.writeheader()
        for item in results:
            writer.writerow(
                {
                    "client_name": item.client_name or "",
                    "brand_name": item.brand_name or "",
                    "url": item.url,
                    "normalized_domain": item.normalized_domain or "",
                    "success": "true" if item.success else "false",
                    "scan_ok": "true" if item.scan_ok else "false",
                    "error": item.error or "",
                    "status_code": item.status_code if item.status_code is not None else "",
                    "warnings_count": item.warnings_count,
                    "broken_links_count": item.broken_links_count,
                    "changes_count": item.changes_count,
                    "previous_check_found": "true" if item.previous_check_found else "false",
                    "health_score": item.health_score if item.health_score is not None else "",
                    "health_label": item.health_label or "",
                    "critical_issues": item.critical_issues,
                    "high_issues": item.high_issues,
                    "medium_issues": item.medium_issues,
                    "low_issues": item.low_issues,
                    "top_actions": item.top_actions or "",
                    "html_path": _relative_to_batch(item.html_path, batch_dir),
                    "pdf_path": _relative_to_batch(item.pdf_path, batch_dir),
                }
            )


def write_summary_html(path: Path, results: list[ReportRunResult], batch_dir: Path) -> None:
    rows_html: list[str] = []
    for item in results:
        if not item.success:
            report_status = "FAILED"
            row_class = "failed"
        elif not item.scan_ok:
            report_status = "REPORT OK"
            row_class = "scan-fail"
        else:
            report_status = "OK"
            row_class = "ok"
        scan_ok_label = "yes" if item.scan_ok else "no"
        html_link = _relative_to_batch(item.html_path, batch_dir)
        pdf_link = _relative_to_batch(item.pdf_path, batch_dir)

        html_cell = (
            f'<a href="{escape(html_link)}">{escape(html_link)}</a>'
            if html_link != "-"
            else "-"
        )
        pdf_cell = (
            f'<a href="{escape(pdf_link)}">{escape(pdf_link)}</a>'
            if pdf_link != "-"
            else "-"
        )
        error_cell = escape(item.error) if item.error else "-"
        score = item.health_score if item.health_score is not None else "—"
        health_label = escape(item.health_label or "—")
        top_actions_cell = escape(item.top_actions or "—")
        score_class = ""
        if item.health_score is not None:
            if item.health_score < 40:
                score_class = "score-critical"
            elif item.health_score < 60:
                score_class = "score-poor"
            elif item.health_score < 75:
                score_class = "score-warn"

        rows_html.append(
            f"""<tr class="{row_class}">
  <td>{escape(item.client_name or "-")}</td>
  <td><code>{escape(item.url)}</code></td>
  <td>{report_status}</td>
  <td>{scan_ok_label}</td>
  <td class="{score_class}">{score}</td>
  <td class="{score_class}">{health_label}</td>
  <td>{top_actions_cell}</td>
  <td>{item.warnings_count}</td>
  <td>{item.broken_links_count}</td>
  <td>{item.changes_count}</td>
  <td>{html_cell}</td>
  <td>{pdf_cell}</td>
  <td class="err">{error_cell}</td>
</tr>"""
        )

    body_rows = "\n".join(rows_html)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Batch summary</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      margin: 2rem 1rem;
      color: #1a1d26;
      background: #f4f6f9;
    }}
    .card {{
      max-width: 1200px;
      margin: 0 auto;
      background: #fff;
      border: 1px solid #e2e6ef;
      border-radius: 10px;
      padding: 1.25rem;
    }}
    h1 {{ margin-bottom: 0.25rem; }}
    .meta {{ color: #5c6370; margin-bottom: 1rem; font-size: 0.9rem; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th, td {{
      text-align: left;
      padding: 0.55rem 0.65rem;
      border-bottom: 1px solid #e2e6ef;
      vertical-align: top;
    }}
    th {{ background: #f4f6f9; text-transform: uppercase; font-size: 0.75rem; }}
    tr.failed {{ background: #fdecea; }}
    tr.scan-fail {{ background: #fff8e6; }}
    tr.ok td:nth-child(3) {{ color: #0d7a4a; font-weight: 600; }}
    tr.scan-fail td:nth-child(3) {{ color: #9a6700; font-weight: 600; }}
    tr.failed td:nth-child(3) {{ color: #b42318; font-weight: 600; }}
    td.err {{ color: #b42318; }}
    td.score-critical {{ color: #b42318; font-weight: 700; }}
    td.score-poor {{ color: #c2410c; font-weight: 600; }}
    td.score-warn {{ color: #9a6700; font-weight: 600; }}
    code {{ word-break: break-all; }}
    a {{ color: #2563eb; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Batch summary</h1>
    <p class="meta">Generated: {escape(generated)}</p>
    <table>
      <thead>
        <tr>
          <th>Client</th>
          <th>URL</th>
          <th>Report</th>
          <th>Scan OK</th>
          <th>Score</th>
          <th>Health</th>
          <th>Top actions</th>
          <th>Warnings</th>
          <th>Broken links</th>
          <th>Changes</th>
          <th>HTML report</th>
          <th>PDF report</th>
          <th>Error</th>
        </tr>
      </thead>
      <tbody>
{body_rows}
      </tbody>
    </table>
  </div>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def _branding_for_row(
    file_config: BrandingConfig,
    row: dict[str, str],
    project_root: Path,
) -> tuple[BrandingConfig, list[str]]:
    overrides: dict[str, object] = {
        "client_name": _empty_to_none(row.get("client_name")),
        "brand_name": _empty_to_none(row.get("brand_name")),
        "brand_color": _empty_to_none(row.get("brand_color")),
        "logo_path": _empty_to_none(row.get("brand_logo")),
        "footer_text": _empty_to_none(row.get("footer_text")),
    }
    return resolve_branding(file_config, overrides, project_root)


def run_batch_from_clients_csv(
    clients_path: Path,
    output_dir: Path,
    db_path: Path,
    project_root: Path,
    default_format: str,
    default_max_links: int,
    default_timeout: float,
    file_config: BrandingConfig,
    continue_on_error: bool = True,
    limit: int | None = None,
    quiet: bool = False,
) -> BatchRunResult:
    rows = load_clients_csv(clients_path)
    if limit is not None:
        rows = rows[:limit]
    batch_ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    batch_dir = output_dir / batch_run_dir_name(batch_ts)
    batch_dir.mkdir(parents=True, exist_ok=True)

    results: list[ReportRunResult] = []
    total = len(rows)

    for index, row in enumerate(rows, start=1):
        url = _empty_to_none(row.get("url")) or ""
        row_format = _empty_to_none(row.get("format")) or default_format
        row_max_links = _optional_int(row.get("max_links")) or default_max_links
        row_timeout = _optional_float(row.get("timeout")) or default_timeout

        branding, brand_warnings = _branding_for_row(file_config, row, project_root)
        for warning in brand_warnings:
            if not quiet:
                console.print(f"[yellow][{index}/{total}] Warning:[/yellow] {warning}")

        if not quiet:
            console.print(f"[dim][{index}/{total}][/dim] {url} …", end=" ")

        try:
            result = run_single_report(
                url=url,
                max_links=row_max_links,
                timeout=row_timeout,
                output_dir=batch_dir,
                db_path=db_path,
                branding=branding,
                output_format=row_format.lower(),
                project_root=project_root,
                run_timestamp=datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
            )
        except SingleReportError as exc:
            result = exc.result or ReportRunResult(
                url=url,
                client_name=branding.client_name,
                brand_name=branding.brand_name,
                success=False,
                error=str(exc),
            )

        if not quiet:
            for warning in result.branding_warnings:
                console.print(f"[yellow]  PDF:[/yellow] {warning}")

        results.append(result)

        if not quiet:
            if result.success:
                scan_label = "ok" if result.scan_ok else "fail"
                scan_style = "green" if result.scan_ok else "yellow"
                console.print(
                    f"[green]REPORT OK[/green] "
                    f"[{scan_style}]scan={scan_label}[/{scan_style}] "
                    f"warnings={result.warnings_count} broken={result.broken_links_count}"
                )
            else:
                console.print(f"[red]FAILED[/red] error={result.error}")
        if not result.success and not continue_on_error:
            break

    summary_csv = batch_dir / "summary.csv"
    summary_html = batch_dir / "summary.html"
    write_summary_csv(summary_csv, results, batch_dir)
    write_summary_html(summary_html, results, batch_dir)

    successful = sum(1 for item in results if item.success)
    return BatchRunResult(
        batch_dir=batch_dir,
        summary_csv=summary_csv,
        summary_html=summary_html,
        total=len(results),
        successful=successful,
        failed=len(results) - successful,
        results=results,
    )


def run_batch(
    clients_path: Path,
    output_dir: Path,
    db_path: Path,
    project_root: Path,
    default_format: str,
    default_max_links: int,
    default_timeout: float,
    file_config: BrandingConfig,
    continue_on_error: bool = True,
    limit: int | None = None,
) -> tuple[Path, list[ReportRunResult]]:
    """Обратная совместимость: возвращает (batch_dir, results)."""
    batch_result = run_batch_from_clients_csv(
        clients_path=clients_path,
        output_dir=output_dir,
        db_path=db_path,
        project_root=project_root,
        default_format=default_format,
        default_max_links=default_max_links,
        default_timeout=default_timeout,
        file_config=file_config,
        continue_on_error=continue_on_error,
        limit=limit,
    )
    return batch_result.batch_dir, batch_result.results


def main(
    clients: str = typer.Option(..., "--clients", help="CSV со списком клиентов"),
    output_dir: str = typer.Option(
        DEFAULT_OUTPUT_DIR, "--output-dir", help="Базовая папка для batch-отчётов"
    ),
    report_format: FormatChoice = typer.Option(
        "html", "--format", help="Формат по умолчанию: html, pdf, both"
    ),
    max_links: int = typer.Option(
        DEFAULT_MAX_LINKS, "--max-links", help="Макс. внутренних ссылок по умолчанию"
    ),
    timeout: float = typer.Option(
        DEFAULT_TIMEOUT, "--timeout", help="Таймаут по умолчанию (сек)"
    ),
    db_path: str = typer.Option(
        DEFAULT_DB_PATH, "--db-path", help="SQLite-база истории проверок"
    ),
    continue_on_error: bool = typer.Option(
        True,
        "--continue-on-error/--no-continue-on-error",
        help="Продолжать batch при ошибке одного сайта",
    ),
    branding_file: str | None = typer.Option(
        None, "--branding-file", help="JSON с базовым брендингом"
    ),
    create_outbox: bool = typer.Option(
        False,
        "--create-outbox/--no-create-outbox",
        help="После batch создать outbox (без отправки email)",
    ),
    outbox_dir: str = typer.Option("outbox", "--outbox-dir", help="Папка outbox"),
) -> None:
    """Пакетная генерация отчётов по CSV."""
    output_format = report_format.lower()
    if output_format not in ("html", "pdf", "both"):
        console.print("[red]Ошибка:[/red] --format должен быть html, pdf или both")
        raise typer.Exit(code=1)

    project_root = Path(__file__).resolve().parent.parent

    try:
        clients_path = resolve_project_path(clients, project_root)
        if branding_file:
            file_config = load_branding_config(
                str(resolve_project_path(branding_file, project_root))
            )
        else:
            file_config = load_branding_config(None)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Ошибка:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print("\n[bold]Weekly Site Report — Batch[/bold]\n")

    batch_dir, results = run_batch(
        clients_path=clients_path,
        output_dir=resolve_project_path(output_dir, project_root),
        db_path=resolve_project_path(db_path, project_root),
        project_root=project_root,
        default_format=output_format,
        default_max_links=max_links,
        default_timeout=timeout,
        file_config=file_config,
        continue_on_error=continue_on_error,
    )

    successful = sum(1 for item in results if item.success)
    failed = len(results) - successful
    summary_csv = batch_dir / "summary.csv"
    summary_html = batch_dir / "summary.html"

    console.print("\n[bold]Batch finished[/bold]")
    console.print(f"Total: {len(results)}")
    console.print(f"Successful: {successful}")
    console.print(f"Failed: {failed}")
    console.print(f"Summary CSV: {summary_csv}")
    console.print(f"Summary HTML: {summary_html}\n")

    if create_outbox:
        from app.outbox import create_outbox_for_batch

        outbox_result = create_outbox_for_batch(
            batch_dir=batch_dir,
            clients_csv=clients_path,
            outbox_dir=resolve_project_path(outbox_dir, project_root),
            project_root=project_root,
        )
        for warning in outbox_result.warnings:
            console.print(f"[yellow]Outbox warning:[/yellow] {warning}")
        console.print(f"Outbox created: {outbox_result.outbox_dir}")
        console.print(f"Prepared emails: {outbox_result.prepared_count}\n")

    if failed and not continue_on_error:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    typer.run(main)
