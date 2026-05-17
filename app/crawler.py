from __future__ import annotations

import time
from collections import deque
from html import unescape
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from app.link_checker import collect_links
from app.models import CrawledPageResult
from app.seo_checks import run_seo_checks
from app.utils import default_headers, get_base_domain, is_same_domain, resolve_internal_url


def extract_sitemap_urls(xml_text: str, base_url: str, limit: int) -> list[str]:
    urls: list[str] = []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return urls

    for element in root.iter():
        if element.tag.lower().endswith("loc") and element.text:
            loc = unescape(element.text.strip())
            if is_same_domain(base_url, loc):
                urls.append(loc)
            if len(urls) >= limit:
                break
    return urls


def fetch_sitemap_urls(base_url: str, timeout: float, limit: int) -> list[str]:
    sitemap_url = f"{get_base_domain(base_url).rstrip('/')}/sitemap.xml"
    try:
        with httpx.Client(timeout=timeout, headers=default_headers(), follow_redirects=True) as client:
            response = client.get(sitemap_url)
            if response.status_code >= 400:
                return []
            return extract_sitemap_urls(response.text, base_url, limit)
    except Exception:
        return []


def has_noindex(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or meta.get("http-equiv") or "").strip().lower()
        content = (meta.get("content") or "").lower()
        if name in ("robots", "googlebot") and "noindex" in content:
            return True
    return False


def collect_asset_urls(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    assets: list[str] = []
    for tag_name, attr in (("img", "src"), ("script", "src"), ("link", "href")):
        for tag in soup.find_all(tag_name):
            if tag_name == "link":
                rel = " ".join(tag.get("rel") or []).lower()
                if rel and not any(key in rel for key in ("stylesheet", "icon", "preload")):
                    continue
            url = resolve_internal_url(page_url, tag.get(attr) or "")
            if url:
                assets.append(url)
    return list(dict.fromkeys(assets))


def count_broken_assets(html: str, page_url: str, timeout: float, limit: int = 20) -> int:
    broken = 0
    assets = collect_asset_urls(html, page_url)[:limit]
    with httpx.Client(timeout=timeout, headers=default_headers(), follow_redirects=True) as client:
        for asset in assets:
            try:
                response = client.head(asset)
                if response.status_code == 405:
                    response = client.get(asset)
                if response.status_code >= 400:
                    broken += 1
            except Exception:
                broken += 1
    return broken


def _page_result_from_response(url: str, response: httpx.Response, elapsed_ms: float, timeout: float) -> CrawledPageResult:
    html = response.text if "text/html" in response.headers.get("content-type", "").lower() or "<html" in response.text[:500].lower() else ""
    seo = run_seo_checks(html) if html else None
    return CrawledPageResult(
        url=url,
        final_url=str(response.url),
        status_code=response.status_code,
        response_time_ms=round(elapsed_ms, 2),
        title=seo.title if seo else None,
        h1_count=seo.h1_count if seo else 0,
        noindex=has_noindex(html) if html else False,
        broken_assets_count=count_broken_assets(html, str(response.url), timeout) if html else 0,
    )


def crawl_site(start_url: str, start_html: str | None, max_pages: int, timeout: float) -> list[CrawledPageResult]:
    if max_pages <= 0:
        return []

    queue: deque[str] = deque()
    seen: set[str] = set()

    for url in fetch_sitemap_urls(start_url, timeout, max_pages):
        if url not in seen:
            queue.append(url)
            seen.add(url)

    if start_url not in seen:
        queue.appendleft(start_url)
        seen.add(start_url)

    if start_html:
        internal, _ = collect_links(start_html, start_url)
        for url in internal:
            if len(seen) >= max_pages:
                break
            if url not in seen and is_same_domain(start_url, url):
                queue.append(url)
                seen.add(url)

    results: list[CrawledPageResult] = []
    with httpx.Client(timeout=timeout, headers=default_headers(), follow_redirects=True) as client:
        while queue and len(results) < max_pages:
            url = queue.popleft()
            try:
                start = time.perf_counter()
                response = client.get(url)
                elapsed = (time.perf_counter() - start) * 1000
                results.append(_page_result_from_response(url, response, elapsed, timeout))
            except Exception as exc:
                results.append(CrawledPageResult(url=url, error=f"{type(exc).__name__}: {exc}"))
    return results
