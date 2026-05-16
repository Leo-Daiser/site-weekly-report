from __future__ import annotations

import time
import httpx
from bs4 import BeautifulSoup

from app.models import LinkCheckResult, LinkItem
from app.utils import default_headers, is_same_domain, resolve_internal_url


def _fetch_link(client: httpx.Client, url: str) -> httpx.Response:
    response = client.head(url)
    if response.status_code in (403, 405):
        response = client.get(url)
    return response


def collect_links(html: str, page_url: str) -> tuple[list[str], list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    internal: list[str] = []
    external: list[str] = []
    seen_internal: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        resolved = resolve_internal_url(page_url, href)
        if not resolved:
            continue

        if is_same_domain(page_url, resolved):
            if resolved not in seen_internal:
                seen_internal.add(resolved)
                internal.append(resolved)
        else:
            if resolved not in external:
                external.append(resolved)

    return internal, external


def check_internal_links(
    links: list[str],
    max_links: int,
    timeout: float,
) -> LinkCheckResult:
    to_check = links[:max_links]
    checked: list[LinkItem] = []
    warnings: list[str] = []
    broken_count = 0

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers=default_headers(),
        ) as client:
            for link_url in to_check:
                item = LinkItem(url=link_url)
                try:
                    start = time.perf_counter()
                    response = _fetch_link(client, link_url)
                    elapsed_ms = (time.perf_counter() - start) * 1000

                    item.status_code = response.status_code
                    item.response_time_ms = round(elapsed_ms, 2)

                    if response.status_code >= 400:
                        item.is_broken = True
                        broken_count += 1
                        warnings.append(
                            f"битая внутренняя ссылка: {link_url} (HTTP {response.status_code})"
                        )
                except Exception as exc:
                    item.error = f"{type(exc).__name__}: {exc}"
                    item.is_broken = True
                    broken_count += 1
                    warnings.append(f"битая внутренняя ссылка: {link_url} ({item.error})")

                checked.append(item)
    except Exception:
        for link_url in to_check:
            if not any(c.url == link_url for c in checked):
                item = LinkItem(
                    url=link_url,
                    error="Не удалось проверить ссылку",
                    is_broken=True,
                )
                checked.append(item)
                broken_count += 1

    return LinkCheckResult(
        internal_links=links,
        external_links=[],
        checked_links=checked,
        broken_count=broken_count,
        warnings=warnings,
    )


def run_link_checks(
    html: str,
    page_url: str,
    max_links: int,
    timeout: float,
) -> LinkCheckResult:
    internal, external = collect_links(html, page_url)
    result = check_internal_links(internal, max_links, timeout)
    result.external_links = external
    return result
