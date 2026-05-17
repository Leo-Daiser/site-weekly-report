from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.models import WeeklyRunLog


def weekly_run_id(timestamp: datetime | None = None) -> str:
    ts = (timestamp or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
    return f"weekly_run_{ts}"


def run_log_path(run_logs_dir: Path, run_id: str) -> Path:
    run_logs_dir.mkdir(parents=True, exist_ok=True)
    return run_logs_dir / f"{run_id}.json"


def path_for_log(path: Path | None, project_root: Path) -> str | None:
    if path is None:
        return None
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def write_weekly_run_log(run_logs_dir: Path, log: WeeklyRunLog) -> Path:
    path = run_log_path(run_logs_dir, log.run_id)
    payload = log.model_dump(mode="json")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
