from __future__ import annotations

import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.models import CrawledPageResult, LinkItem, TechnicalCheckResult
from app.utils import default_headers, get_base_domain, normalize_domain


def _ssl_expiry(url: str, timeout: float) -> tuple[bool | None, str | None, int | None, str | None]:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host or parsed.scheme != "https":
        return None, None, None, None
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
        not_after = cert.get("notAfter")
        if not not_after:
            return None, None, None, "SSL certificate expiry date not found"
        expires = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        days = (expires - datetime.now(timezone.utc)).days
        return days >= 0, expires.date().isoformat(), days, None
    except Exception as exc:
        return False, None, None, f"SSL check failed: {type(exc).__name__}: {exc}"


def _http_redirects_to_https(url: str, timeout: float) -> bool | None:
    parsed = urlparse(url)
    host = parsed.netloc
    if not host:
        return None
    http_url = f"http://{host}{parsed.path or '/'}"
    try:
        with httpx.Client(timeout=timeout, headers=default_headers(), follow_redirects=True) as client:
            response = client.get(http_url)
        return str(response.url).startswith("https://")
    except Exception:
        return None


def _robots_blocks_homepage(base_url: str, timeout: float) -> bool | None:
    robots_url = f"{get_base_domain(base_url).rstrip('/')}/robots.txt"
    try:
        with httpx.Client(timeout=timeout, headers=default_headers(), follow_redirects=True) as client:
            response = client.get(robots_url)
        if response.status_code >= 400:
            return None
        target = normalize_domain(base_url)
        current_agent_matches = False
        disallows: list[str] = []
        for raw_line in response.text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, value = [part.strip() for part in line.split(":", 1)]
            key = key.lower()
            if key == "user-agent":
                current_agent_matches = value == "*"
            elif key == "disallow" and current_agent_matches:
                disallows.append(value)
        return "/" in disallows
    except Exception:
        return None


def build_technical_checks(
    source_url: str,
    crawled_pages: list[CrawledPageResult],
    timeout: float,
) -> TechnicalCheckResult:
    parsed = urlparse(source_url)
    warnings: list[str] = []
    https_enabled = parsed.scheme == "https"
    if not https_enabled:
        warnings.append("Сайт открыт не через HTTPS")

    redirects = _http_redirects_to_https(source_url, timeout)
    if redirects is False:
        warnings.append("HTTP-версия не перенаправляет на HTTPS")

    ssl_valid, ssl_expires_at, ssl_days, ssl_error = _ssl_expiry(source_url, timeout)
    if ssl_error:
        warnings.append(ssl_error)
    if ssl_days is not None and ssl_days < 14:
        warnings.append(f"SSL-сертификат скоро истекает: {ssl_days} дней")

    noindex_pages = [page.final_url or page.url for page in crawled_pages if page.noindex]
    if noindex_pages:
        warnings.append(f"Найдены страницы с noindex: {len(noindex_pages)}")

    broken_assets: list[LinkItem] = []
    for page in crawled_pages:
        if page.broken_assets_count > 0:
            broken_assets.append(
                LinkItem(
                    url=page.final_url or page.url,
                    is_broken=True,
                    error=f"Broken page assets: {page.broken_assets_count}",
                )
            )
    if broken_assets:
        warnings.append(f"Найдены битые изображения/ассеты: {sum(page.broken_assets_count for page in crawled_pages)}")

    robots_blocks = _robots_blocks_homepage(source_url, timeout)
    if robots_blocks:
        warnings.append("robots.txt запрещает сканирование главной страницы")

    return TechnicalCheckResult(
        https_enabled=https_enabled,
        http_redirects_to_https=redirects,
        ssl_valid=ssl_valid,
        ssl_expires_at=ssl_expires_at,
        ssl_days_remaining=ssl_days,
        robots_blocks_homepage=robots_blocks,
        noindex_pages=noindex_pages,
        broken_assets=broken_assets,
        warnings=warnings,
    )
