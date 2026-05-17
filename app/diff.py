from __future__ import annotations

from app.models import DiffChange, DiffSeverity, ReportDiff, SiteReport, StoredCheck

FIRST_CHECK_MESSAGE = "Предыдущая проверка не найдена. Это базовый отчёт."
NO_CHANGES_MESSAGE = "Существенных изменений с прошлой проверки не найдено."


def _fmt(value: object) -> str:
    if value is None:
        return "—"
    return str(value)


def _append(
    changes: list[DiffChange],
    message: str,
    severity: DiffSeverity,
) -> None:
    changes.append(DiffChange(message=message, severity=severity))


def _status_severity(old: int | None, new: int | None) -> DiffSeverity:
    if new is not None and new >= 500:
        return "critical"
    if new is not None and new >= 400:
        return "warning"
    if old is not None and old >= 400 and new is not None and new < 400:
        return "positive"
    return "neutral"


def _is_significant_response_time_change(old: float, new: float) -> bool:
    diff_abs = abs(new - old)
    if diff_abs < 100:
        return False
    baseline = max(old, new, 1.0)
    diff_rel = diff_abs / baseline
    return diff_rel >= 0.30


def _response_time_severity(old: float, new: float) -> DiffSeverity:
    if new > old * 1.5:
        return "warning"
    if new < old:
        return "positive"
    return "neutral"


def _count_severity(field: str, old: int, new: int) -> DiffSeverity:
    if field == "broken_links_count" and new > old:
        return "warning"
    if field == "broken_links_count" and new < old:
        return "positive"
    if field == "warnings_count" and new < old:
        return "positive"
    if field == "warnings_count" and new > old:
        return "warning"
    if field == "h1_count" and (new == 0 or new > 1):
        return "warning"
    return "neutral"


def build_report_diff(previous: StoredCheck | None, current: SiteReport) -> ReportDiff:
    if previous is None:
        return ReportDiff(
            has_previous=False,
            first_check_message=FIRST_CHECK_MESSAGE,
        )

    from app.storage import metrics_from_report
    from app.utils import normalize_domain

    domain = normalize_domain(current.page.final_url or current.source_url)
    cur = metrics_from_report(current, domain)
    changes: list[DiffChange] = []

    if cur["status_code"] != previous.status_code:
        _append(
            changes,
            f"HTTP-статус изменился: {_fmt(previous.status_code)} → {_fmt(cur['status_code'])}",
            _status_severity(previous.status_code, cur["status_code"]),
        )

    old_rt = previous.response_time_ms
    new_rt = cur["response_time_ms"]
    if (
        old_rt is not None
        and new_rt is not None
        and _is_significant_response_time_change(old_rt, new_rt)
    ):
        if new_rt > old_rt:
            verb = "выросло"
        else:
            verb = "снизилось"
        _append(
            changes,
            f"Время ответа {verb}: {old_rt:.0f} мс → {new_rt:.0f} мс",
            _response_time_severity(old_rt, new_rt),
        )

    if cur["title"] != previous.title:
        _append(changes, "Title изменился", "neutral")

    if cur["description"] != previous.description:
        _append(changes, "Description изменился", "neutral")

    if cur["h1_count"] != previous.h1_count:
        _append(
            changes,
            f"Количество H1 изменилось: {previous.h1_count} → {cur['h1_count']}",
            _count_severity("h1_count", previous.h1_count or 0, cur["h1_count"] or 0),
        )

    if cur["canonical_url"] != previous.canonical_url:
        _append(changes, "Canonical URL изменился", "neutral")

    if cur["robots_exists"] != previous.robots_exists:
        if cur["robots_exists"]:
            _append(changes, "robots.txt появился", "positive")
        else:
            _append(changes, "robots.txt пропал", "warning")

    if cur["sitemap_exists"] != previous.sitemap_exists:
        if cur["sitemap_exists"]:
            _append(changes, "sitemap.xml появился", "positive")
        else:
            _append(changes, "sitemap.xml пропал", "warning")

    if cur["forms_count"] != previous.forms_count:
        _append(
            changes,
            f"Количество форм изменилось: {previous.forms_count} → {cur['forms_count']}",
            "neutral",
        )

    if cur["broken_links_count"] != previous.broken_links_count:
        old_b, new_b = previous.broken_links_count, cur["broken_links_count"]
        if new_b > old_b:
            verb = "выросло"
        elif new_b < old_b:
            verb = "снизилось"
        else:
            verb = "изменилось"
        _append(
            changes,
            f"Количество битых внутренних ссылок {verb}: {old_b} → {new_b}",
            _count_severity("broken_links_count", old_b, new_b),
        )

    if cur["internal_links_count"] != previous.internal_links_count:
        _append(
            changes,
            f"Количество внутренних ссылок изменилось: {previous.internal_links_count} → {cur['internal_links_count']}",
            "neutral",
        )

    if cur["external_links_count"] != previous.external_links_count:
        _append(
            changes,
            f"Количество внешних ссылок изменилось: {previous.external_links_count} → {cur['external_links_count']}",
            "neutral",
        )

    if cur["warnings_count"] != previous.warnings_count:
        old_w, new_w = previous.warnings_count, cur["warnings_count"]
        if new_w < old_w:
            verb = "снизилось"
        elif new_w > old_w:
            verb = "выросло"
        else:
            verb = "изменилось"
        _append(
            changes,
            f"Количество предупреждений {verb}: {old_w} → {new_w}",
            _count_severity("warnings_count", old_w, new_w),
        )

    diff = ReportDiff(
        has_previous=True,
        previous_created_at=previous.created_at,
        changes=changes,
    )
    if not changes:
        diff.no_changes_message = NO_CHANGES_MESSAGE
    return diff
