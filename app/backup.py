from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import typer
from rich.console import Console

cli = typer.Typer(help="Create local backups of operator data and artifacts.")
console = Console()

DEFAULT_INCLUDE = (
    "data/clients.csv",
    "data/subscriptions.csv",
    "data/client_status.csv",
    "data/pending_signups.csv",
    "data/leads_crm.csv",
    "data/checks.sqlite",
    "reports",
    "outbox",
    "run_logs",
    "client_packages",
)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def iter_backup_paths(project_root: Path, include_env: bool = False) -> list[Path]:
    paths = [project_root / item for item in DEFAULT_INCLUDE]
    if include_env:
        paths.append(project_root / ".env")
    return [path for path in paths if path.exists()]


def create_backup(
    *,
    project_root: Path,
    output_dir: Path,
    include_env: bool = False,
    timestamp: str | None = None,
) -> Path:
    stamp = timestamp or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"operator_backup_{stamp}.zip"
    paths = iter_backup_paths(project_root, include_env=include_env)

    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in paths:
            if path.is_file():
                archive.write(path, path.relative_to(project_root).as_posix())
                continue
            for child in path.rglob("*"):
                if child.is_file():
                    archive.write(child, child.relative_to(project_root).as_posix())
    return archive_path


@cli.command("create")
def create_cmd(
    output_dir: str = typer.Option("backups", "--output-dir"),
    include_env: bool = typer.Option(False, "--include-env/--no-include-env"),
) -> None:
    root = _project_root()
    archive = create_backup(
        project_root=root,
        output_dir=root / output_dir,
        include_env=include_env,
    )
    console.print(f"[green]Backup created:[/green] {archive}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
