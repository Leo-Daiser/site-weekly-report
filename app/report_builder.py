from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.branding import prepare_logo_data_uri
from app.models import BrandingConfig, SiteReport

WARNING_TO_RECOMMENDATION: dict[str, str] = {
    "title отсутствует": "Добавить тег title на главную страницу.",
    "title слишком короткий": "Расширить title до 20–70 символов.",
    "title слишком длинный": "Сократить title до 20–70 символов.",
    "description отсутствует": "Добавить meta description.",
    "description слишком короткий": "Расширить meta description до 50–160 символов.",
    "description слишком длинный": "Сократить meta description до 50–160 символов.",
    "H1 отсутствует": "Добавить один заголовок H1 на страницу.",
    "H1 больше одного": "Оставить только один H1.",
    "canonical отсутствует": "Добавить canonical URL.",
    "форма есть, но action отсутствует": "Проверить форму: отсутствует action.",
    "форма есть, но submit не найден": "Добавить кнопку submit в форму.",
}

RECOMMENDATION_KEYWORDS = [
    ("битая внутренняя ссылка", "Исправить битые внутренние ссылки."),
]

def build_recommendations(report: SiteReport) -> list[str]:
    recommendations: list[str] = []
    seen: set[str] = set()

    for warning in report.all_warnings:
        matched = False
        for key, rec in WARNING_TO_RECOMMENDATION.items():
            if key in warning and rec not in seen:
                recommendations.append(rec)
                seen.add(rec)
                matched = True
                break
        if not matched:
            for key, rec in RECOMMENDATION_KEYWORDS:
                if key in warning.lower() and rec not in seen:
                    recommendations.append(rec)
                    seen.add(rec)
                    break

    if report.robots and not report.robots.exists:
        rec = "Добавить robots.txt."
        if rec not in seen:
            recommendations.append(rec)
            seen.add(rec)

    if report.sitemap and not report.sitemap.exists:
        rec = "Добавить sitemap.xml."
        if rec not in seen:
            recommendations.append(rec)
            seen.add(rec)

    if report.links and report.links.broken_count > 0:
        rec = "Исправить битые внутренние ссылки."
        if rec not in seen:
            recommendations.append(rec)
            seen.add(rec)

    if report.technical:
        technical_recs = [
            (not report.technical.https_enabled, "Перевести сайт на HTTPS."),
            (
                report.technical.http_redirects_to_https is False,
                "Настроить редирект HTTP на HTTPS.",
            ),
            (
                bool(report.technical.noindex_pages),
                "Проверить noindex на важных страницах.",
            ),
            (
                bool(report.technical.broken_assets),
                "Исправить битые изображения и ассеты.",
            ),
            (
                report.technical.robots_blocks_homepage is True,
                "Проверить robots.txt: главная страница закрыта от сканирования.",
            ),
        ]
        for condition, rec in technical_recs:
            if condition and rec not in seen:
                recommendations.append(rec)
                seen.add(rec)

    return recommendations


def collect_all_warnings(report: SiteReport) -> list[str]:
    warnings: list[str] = []

    if report.page.error:
        warnings.append(f"Страница недоступна: {report.page.error}")

    if report.seo:
        warnings.extend(report.seo.warnings)

    if report.robots and not report.robots.exists:
        warnings.append("robots.txt не найден или недоступен")

    if report.sitemap and not report.sitemap.exists:
        warnings.append("sitemap.xml не найден или недоступен")

    for form in report.forms:
        warnings.extend(form.warnings)

    if report.links:
        warnings.extend(report.links.warnings)

    if report.technical:
        warnings.extend(report.technical.warnings)

    return warnings


def status_class(ok: bool, warning: bool = False) -> str:
    if ok:
        return "status-ok"
    if warning:
        return "status-warning"
    return "status-error"


def health_summary_text(score: int | None) -> str:
    if score is None:
        return "The site was checked, but there is not enough data to calculate a reliable health summary."
    if score >= 90:
        return "The site is stable this week. Keep monitoring it so regressions are caught before clients notice them."
    if score >= 75:
        return "The site is mostly healthy, with a few items worth cleaning up during regular maintenance."
    if score >= 60:
        return "The site works, but there are visible issues that should be assigned and fixed before they accumulate."
    if score >= 40:
        return "The site needs attention. Prioritize the top actions before sending traffic or campaigns to this website."
    return "The site has serious issues. Treat this report as an operational fix list, not just a monitoring update."


BUSINESS_IMPACT_BY_CATEGORY: dict[str, str] = {
    "availability": "Visitors or clients may see a broken site instead of the intended page.",
    "seo": "Search snippets and indexability may be weaker than they should be.",
    "technical": "Search engines or monitoring tools may have trouble reading the site correctly.",
    "forms": "Lead capture can fail or create friction for potential customers.",
    "links": "Users and search engines can hit dead ends inside the site.",
    "performance": "Slow responses can reduce conversions and make campaigns less efficient.",
    "changes": "The site changed compared with the previous check and should be reviewed.",
    "security": "Trust and browser safety signals may be weaker than expected.",
    "assets": "Broken images, CSS, or scripts can make the page look unfinished or malfunction.",
}


def issue_business_impact(category: str) -> str:
    return BUSINESS_IMPACT_BY_CATEGORY.get(
        category,
        "This issue can reduce the quality of the client-facing website experience.",
    )


def action_next_step(owner: str) -> str:
    if owner == "SEO":
        return "Review the affected page metadata/indexing and update the SEO fields."
    if owner == "Developer":
        return "Check the implementation or hosting configuration and deploy a fix."
    if owner == "Content":
        return "Update the affected content, links, or page references."
    return "Assign the issue, confirm priority, and track it through the next weekly report."


def render_report(
    report: SiteReport,
    template_dir: Path,
    output_path: Path,
    branding: BrandingConfig,
) -> tuple[Path, list[str]]:
    logo_data_uri, logo_warnings = prepare_logo_data_uri(branding.logo_path)

    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("report.html.j2")
    html = template.render(
        report=report,
        branding=branding,
        logo_data_uri=logo_data_uri,
        status_class=status_class,
        health_summary_text=health_summary_text,
        issue_business_impact=issue_business_impact,
        action_next_step=action_next_step,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path, logo_warnings
