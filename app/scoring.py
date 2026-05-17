from __future__ import annotations

from app.models import (
    HealthScore,
    IssueCategory,
    IssueSeverity,
    PrioritizedAction,
    ReportDiff,
    ReportIssue,
    ReportRunResult,
    SiteReport,
    StoredCheck,
)

SEVERITY_PENALTIES: dict[str, int] = {
    "critical": 25,
    "high": 15,
    "medium": 7,
    "low": 3,
    "info": 0,
}

LABEL_EXCELLENT = "Excellent"
LABEL_GOOD = "Good"
LABEL_NEEDS_ATTENTION = "Needs attention"
LABEL_POOR = "Poor"
LABEL_CRITICAL = "Critical"


def _issue(
    code: str,
    title: str,
    description: str,
    severity: IssueSeverity,
    category: IssueCategory,
    recommendation: str,
    *,
    weight: int | None = None,
) -> ReportIssue:
    return ReportIssue(
        code=code,
        title=title,
        description=description,
        severity=severity,
        category=category,
        recommendation=recommendation,
        weight=weight if weight is not None else SEVERITY_PENALTIES[severity],
    )


def _add_issue(issues: list[ReportIssue], seen: set[str], issue: ReportIssue) -> None:
    if issue.code in seen:
        return
    seen.add(issue.code)
    issues.append(issue)


def build_report_issues(
    report: SiteReport,
    diff: ReportDiff | None = None,
    previous: StoredCheck | None = None,
) -> list[ReportIssue]:
    issues: list[ReportIssue] = []
    seen: set[str] = set()
    page = report.page
    seo = report.seo
    links = report.links

    if page.error:
        _add_issue(
            issues,
            seen,
            _issue(
                "page_error",
                "Сайт недоступен",
                f"Ошибка при загрузке: {page.error}",
                "critical",
                "availability",
                "Устранить проблему доступности сайта и повторить проверку.",
            ),
        )

    if page.status_code is None and not page.error:
        _add_issue(
            issues,
            seen,
            _issue(
                "status_missing",
                "HTTP-статус не получен",
                "Не удалось определить HTTP-статус главной страницы.",
                "critical",
                "availability",
                "Проверить доступность сервера и корректность URL.",
            ),
        )
    elif page.status_code is not None:
        if page.status_code >= 500:
            _add_issue(
                issues,
                seen,
                _issue(
                    "status_5xx",
                    "Ошибка сервера",
                    f"Главная страница возвращает HTTP {page.status_code}.",
                    "critical",
                    "availability",
                    "Исправить ошибку сервера (5xx) на главной странице.",
                ),
            )
        elif page.status_code >= 400:
            _add_issue(
                issues,
                seen,
                _issue(
                    "status_4xx",
                    "Ошибка клиента HTTP",
                    f"Главная страница возвращает HTTP {page.status_code}.",
                    "high",
                    "availability",
                    "Исправить HTTP-ошибку (4xx) на главной странице.",
                ),
            )

    if page.response_time_ms is not None:
        if page.response_time_ms > 3000:
            _add_issue(
                issues,
                seen,
                _issue(
                    "response_slow",
                    "Медленный ответ сервера",
                    f"Время ответа главной страницы: {page.response_time_ms:.0f} мс.",
                    "medium",
                    "performance",
                    "Ускорить загрузку главной страницы (хостинг, кэш, оптимизация).",
                ),
            )
        elif page.response_time_ms > 1000:
            _add_issue(
                issues,
                seen,
                _issue(
                    "response_elevated",
                    "Повышенное время ответа",
                    f"Время ответа главной страницы: {page.response_time_ms:.0f} мс.",
                    "low",
                    "performance",
                    "Проверить производительность сервера и кэширование.",
                ),
            )

    if seo:
        if not seo.title:
            _add_issue(
                issues,
                seen,
                _issue(
                    "title_missing",
                    "Отсутствует title",
                    "На главной странице нет тега title.",
                    "high",
                    "seo",
                    "Добавить тег title на главную страницу.",
                ),
            )
        elif seo.title_length < 20:
            _add_issue(
                issues,
                seen,
                _issue(
                    "title_short",
                    "Короткий title",
                    f"Длина title: {seo.title_length} символов (рекомендуется 20–70).",
                    "medium",
                    "seo",
                    "Расширить title до 20–70 символов.",
                ),
            )
        elif seo.title_length > 70:
            _add_issue(
                issues,
                seen,
                _issue(
                    "title_long",
                    "Длинный title",
                    f"Длина title: {seo.title_length} символов (рекомендуется 20–70).",
                    "low",
                    "seo",
                    "Сократить title до 20–70 символов.",
                ),
            )

        if not seo.meta_description:
            _add_issue(
                issues,
                seen,
                _issue(
                    "description_missing",
                    "Отсутствует meta description",
                    "На главной странице нет meta description.",
                    "high",
                    "seo",
                    "Добавить meta description на главную страницу.",
                ),
            )
        elif seo.meta_description_length < 50:
            _add_issue(
                issues,
                seen,
                _issue(
                    "description_short",
                    "Короткий meta description",
                    f"Длина description: {seo.meta_description_length} символов.",
                    "medium",
                    "seo",
                    "Расширить meta description до 50–160 символов.",
                ),
            )
        elif seo.meta_description_length > 160:
            _add_issue(
                issues,
                seen,
                _issue(
                    "description_long",
                    "Длинный meta description",
                    f"Длина description: {seo.meta_description_length} символов.",
                    "low",
                    "seo",
                    "Сократить meta description до 50–160 символов.",
                ),
            )

        if seo.h1_count == 0:
            _add_issue(
                issues,
                seen,
                _issue(
                    "h1_missing",
                    "Отсутствует H1",
                    "На главной странице нет заголовка H1.",
                    "high",
                    "seo",
                    "Добавить один заголовок H1 на страницу.",
                ),
            )
        elif seo.h1_count > 1:
            _add_issue(
                issues,
                seen,
                _issue(
                    "h1_multiple",
                    "Несколько H1",
                    f"На странице найдено {seo.h1_count} заголовков H1.",
                    "medium",
                    "seo",
                    "Оставить только один H1 на странице.",
                ),
            )

        if not seo.canonical_url:
            _add_issue(
                issues,
                seen,
                _issue(
                    "canonical_missing",
                    "Отсутствует canonical",
                    "На главной странице нет canonical URL.",
                    "low",
                    "seo",
                    "Добавить canonical URL на главную страницу.",
                ),
            )

    if report.robots and not report.robots.exists:
        _add_issue(
            issues,
            seen,
            _issue(
                "robots_missing",
                "robots.txt не найден",
                "Файл robots.txt отсутствует или недоступен.",
                "medium",
                "technical",
                "Добавить и проверить robots.txt.",
            ),
        )

    if report.sitemap and not report.sitemap.exists:
        _add_issue(
            issues,
            seen,
            _issue(
                "sitemap_missing",
                "sitemap.xml не найден",
                "Файл sitemap.xml отсутствует или недоступен.",
                "medium",
                "technical",
                "Добавить sitemap.xml и указать его в robots.txt.",
            ),
        )

    for index, form in enumerate(report.forms):
        if form.input_count > 0 and not (form.action or "").strip():
            _add_issue(
                issues,
                seen,
                _issue(
                    f"form_no_action_{index}",
                    "Форма без action",
                    "На странице найдена форма без указанного action.",
                    "medium",
                    "forms",
                    "Указать корректный action для формы.",
                ),
            )
        if form.input_count > 0 and not form.has_submit:
            _add_issue(
                issues,
                seen,
                _issue(
                    f"form_no_submit_{index}",
                    "Форма без submit",
                    "На странице найдена форма без кнопки submit.",
                    "medium",
                    "forms",
                    "Добавить кнопку или элемент submit в форму.",
                ),
            )

    broken = links.broken_count if links else 0
    if broken >= 5:
        _add_issue(
            issues,
            seen,
            _issue(
                "broken_links_high",
                "Много битых ссылок",
                f"Найдено {broken} битых внутренних ссылок.",
                "high",
                "links",
                "Исправить битые внутренние ссылки.",
            ),
        )
    elif broken >= 1:
        _add_issue(
            issues,
            seen,
            _issue(
                "broken_links_medium",
                "Битые внутренние ссылки",
                f"Найдено {broken} битых внутренних ссылок.",
                "medium",
                "links",
                "Исправить битые внутренние ссылки.",
            ),
        )

    if previous is not None:
        cur_status = page.status_code
        old_status = previous.status_code
        if (
            old_status is not None
            and old_status < 400
            and cur_status is not None
            and cur_status >= 500
        ):
            _add_issue(
                issues,
                seen,
                _issue(
                    "diff_status_critical",
                    "HTTP-статус ухудшился",
                    f"Статус изменился: {old_status} → {cur_status}.",
                    "critical",
                    "changes",
                    "Срочно восстановить доступность сайта.",
                ),
            )

        old_broken = previous.broken_links_count
        new_broken = broken
        if new_broken > old_broken:
            delta = new_broken - old_broken
            severity: IssueSeverity = "high" if delta >= 3 or new_broken >= 5 else "medium"
            _add_issue(
                issues,
                seen,
                _issue(
                    "diff_broken_increased",
                    "Больше битых ссылок",
                    f"Битых ссылок стало больше: {old_broken} → {new_broken}.",
                    severity,
                    "changes",
                    "Исправить новые битые внутренние ссылки.",
                ),
            )

        if previous.warnings_count < len(report.all_warnings):
            _add_issue(
                issues,
                seen,
                _issue(
                    "diff_warnings_increased",
                    "Больше предупреждений",
                    f"Предупреждений стало больше: {previous.warnings_count} → {len(report.all_warnings)}.",
                    "medium",
                    "changes",
                    "Разобрать новые предупреждения в отчёте.",
                ),
            )

        if previous.sitemap_exists and report.sitemap and not report.sitemap.exists:
            _add_issue(
                issues,
                seen,
                _issue(
                    "diff_sitemap_lost",
                    "sitemap.xml пропал",
                    "sitemap.xml был доступен ранее, сейчас не найден.",
                    "high",
                    "changes",
                    "Восстановить sitemap.xml.",
                ),
            )

        if previous.robots_exists and report.robots and not report.robots.exists:
            _add_issue(
                issues,
                seen,
                _issue(
                    "diff_robots_lost",
                    "robots.txt пропал",
                    "robots.txt был доступен ранее, сейчас не найден.",
                    "medium",
                    "changes",
                    "Восстановить robots.txt.",
                ),
            )

    if diff and diff.has_previous:
        for change in diff.changes:
            if change.severity == "critical" and "HTTP" in change.message:
                if "diff_status_critical" not in seen:
                    _add_issue(
                        issues,
                        seen,
                        _issue(
                            "diff_status_from_changes",
                            "Критическое изменение HTTP",
                            change.message,
                            "critical",
                            "changes",
                            "Проверить доступность сайта после изменения статуса.",
                        ),
                    )

    return issues


def score_label(score: int) -> str:
    if score >= 90:
        return LABEL_EXCELLENT
    if score >= 75:
        return LABEL_GOOD
    if score >= 60:
        return LABEL_NEEDS_ATTENTION
    if score >= 40:
        return LABEL_POOR
    return LABEL_CRITICAL


def calculate_health_score(issues: list[ReportIssue]) -> HealthScore:
    score = 100
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for issue in issues:
        score -= SEVERITY_PENALTIES.get(issue.severity, 0)
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    score = max(0, min(100, score))
    return HealthScore(
        score=score,
        label=score_label(score),
        issues_total=len(issues),
        critical_count=counts["critical"],
        high_count=counts["high"],
        medium_count=counts["medium"],
        low_count=counts["low"],
        top_actions=[],
    )


def enrich_report_with_health(
    report: SiteReport,
    previous: StoredCheck | None = None,
) -> HealthScore:
    from app.actions import build_prioritized_actions

    issues = build_report_issues(report, report.diff, previous)
    health = calculate_health_score(issues)
    health.top_actions = build_prioritized_actions(issues)
    report.issues = issues
    report.health_score = health
    return health


def format_top_actions_pipe(actions: list[PrioritizedAction]) -> str:
    return " | ".join(action.title for action in actions)


def copy_health_to_run_result(result: ReportRunResult, health: HealthScore) -> None:
    result.health_score = health.score
    result.health_label = health.label
    result.critical_issues = health.critical_count
    result.high_issues = health.high_count
    result.medium_issues = health.medium_count
    result.low_issues = health.low_count
    result.top_actions = format_top_actions_pipe(health.top_actions)
