from __future__ import annotations

import time

import httpx

from app.models import PageFetchResult, ResourceCheckResult
from app.utils import default_headers, get_base_domain


def _is_html_response(content_type: str, body_preview: str) -> bool:
    if "text/html" in content_type.lower():
        return True
    return "<html" in body_preview[:500].lower()


def fetch_page(url: str, timeout: float) -> PageFetchResult:
    result = PageFetchResult(source_url=url)
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers=default_headers(),
            verify=True,
        ) as client:
            start = time.perf_counter()
            response = client.get(url)
            elapsed_ms = (time.perf_counter() - start) * 1000

            result.final_url = str(response.url)
            result.status_code = response.status_code
            result.response_time_ms = round(elapsed_ms, 2)

            content_type = response.headers.get("content-type", "")
            if _is_html_response(content_type, response.text):
                result.html = response.text
            else:
                result.html = None
                result.error = f"Ответ не похож на HTML: {content_type or 'не указан'}"
    except httpx.TimeoutException:
        result.error = "Таймаут при загрузке страницы"
    except httpx.ConnectError as exc:
        result.error = f"Ошибка подключения: {exc}"
    except httpx.HTTPStatusError as exc:
        result.error = f"HTTP ошибка: {exc}"
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"

    return result


def check_resource(
    base_url: str,
    path: str,
    resource_type: str,
    timeout: float,
) -> ResourceCheckResult:
    resource_url = f"{get_base_domain(base_url).rstrip('/')}{path}"
    check = ResourceCheckResult(
        resource_type=resource_type,  # type: ignore[arg-type]
        url=resource_url,
    )
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers=default_headers(),
        ) as client:
            response = client.head(resource_url)
            if response.status_code == 405:
                response = client.get(resource_url)
            check.status_code = response.status_code
            check.exists = response.status_code < 400
    except Exception as exc:
        check.error = f"{type(exc).__name__}: {exc}"
        check.exists = False

    return check


def check_robots_and_sitemap(
    base_url: str, timeout: float
) -> tuple[ResourceCheckResult, ResourceCheckResult]:
    robots = check_resource(base_url, "/robots.txt", "robots.txt", timeout)
    sitemap = check_resource(base_url, "/sitemap.xml", "sitemap.xml", timeout)
    return robots, sitemap
