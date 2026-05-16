from __future__ import annotations

from bs4 import BeautifulSoup

from app.models import FormCheckResult, SeoCheckResult


def run_seo_checks(html: str) -> SeoCheckResult:
    soup = BeautifulSoup(html, "html.parser")
    warnings: list[str] = []

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None
    title_length = len(title) if title else 0

    desc_tag = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "description"})
    meta_description = desc_tag.get("content", "").strip() if desc_tag else None
    if meta_description == "":
        meta_description = None
    desc_length = len(meta_description) if meta_description else 0

    h1_list = [h.get_text(strip=True) for h in soup.find_all("h1")]
    h1_count = len(h1_list)

    canonical_tag = soup.find("link", rel=lambda v: v and "canonical" in v.lower())
    canonical_url = canonical_tag.get("href") if canonical_tag else None

    html_tag = soup.find("html")
    html_lang = html_tag.get("lang") if html_tag else None

    if not title:
        warnings.append("title отсутствует")
    elif title_length < 20:
        warnings.append("title слишком короткий (< 20 символов)")
    elif title_length > 70:
        warnings.append("title слишком длинный (> 70 символов)")

    if not meta_description:
        warnings.append("description отсутствует")
    elif desc_length < 50:
        warnings.append("description слишком короткий (< 50 символов)")
    elif desc_length > 160:
        warnings.append("description слишком длинный (> 160 символов)")

    if h1_count == 0:
        warnings.append("H1 отсутствует")
    elif h1_count > 1:
        warnings.append("H1 больше одного")

    if not canonical_url:
        warnings.append("canonical отсутствует")

    return SeoCheckResult(
        title=title,
        title_length=title_length,
        meta_description=meta_description,
        meta_description_length=desc_length,
        h1_list=h1_list,
        h1_count=h1_count,
        canonical_url=canonical_url,
        html_lang=html_lang,
        warnings=warnings,
    )


def check_forms(html: str) -> list[FormCheckResult]:
    soup = BeautifulSoup(html, "html.parser")
    forms: list[FormCheckResult] = []

    for form in soup.find_all("form"):
        method = (form.get("method") or "get").lower()
        action = form.get("action")
        if action == "":
            action = None

        inputs = form.find_all("input")
        input_count = len(inputs)

        has_submit = bool(
            form.find("button", type="submit")
            or form.find("input", type="submit")
            or form.find("button", attrs={"type": None})
        )

        form_warnings: list[str] = []
        if not action:
            form_warnings.append("форма есть, но action отсутствует")
        if not has_submit:
            form_warnings.append("форма есть, но submit не найден")

        forms.append(
            FormCheckResult(
                method=method,
                action=action,
                input_count=input_count,
                has_submit=has_submit,
                warnings=form_warnings,
            )
        )

    return forms
