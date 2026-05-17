from __future__ import annotations

from app.models import ActionOwner, IssueCategory, IssueSeverity, PrioritizedAction, ReportIssue

SEVERITY_RANK: dict[IssueSeverity, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}

IMPACT_BY_SEVERITY: dict[IssueSeverity, str] = {
    "critical": "high",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "info": "low",
}

OWNER_BY_CATEGORY: dict[IssueCategory, ActionOwner] = {
    "availability": "Ops",
    "seo": "SEO",
    "technical": "Developer",
    "forms": "Developer",
    "links": "Content",
    "performance": "Developer",
    "changes": "Ops",
    "security": "Developer",
    "assets": "Developer",
}


def build_prioritized_actions(
    issues: list[ReportIssue],
    limit: int = 3,
) -> list[PrioritizedAction]:
    if not issues:
        return [
            PrioritizedAction(
                title="No urgent actions required",
                reason="Критичных проблем не обнаружено.",
                severity="info",
                category="technical",
                estimated_impact="low",
                owner="Ops",
            )
        ]

    sorted_issues = sorted(
        issues,
        key=lambda item: (SEVERITY_RANK.get(item.severity, 99), -item.weight),
    )
    seen_recommendations: set[str] = set()
    actions: list[PrioritizedAction] = []

    for issue in sorted_issues:
        key = issue.recommendation.strip().lower()
        if not key or key in seen_recommendations:
            continue
        seen_recommendations.add(key)
        actions.append(
            PrioritizedAction(
                title=issue.title,
                reason=issue.description,
                severity=issue.severity,
                category=issue.category,
                estimated_impact=IMPACT_BY_SEVERITY.get(issue.severity, "medium"),
                owner=OWNER_BY_CATEGORY.get(issue.category, "Ops"),
            )
        )
        if len(actions) >= limit:
            break

    if not actions:
        return [
            PrioritizedAction(
                title="No urgent actions required",
                reason="Критичных проблем не обнаружено.",
                severity="info",
                category="technical",
                estimated_impact="low",
                owner="Ops",
            )
        ]

    return actions
