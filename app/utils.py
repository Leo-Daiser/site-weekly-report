from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse

from app.config import USER_AGENT


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("URL не может быть пустым")
    parsed = urlparse(url)
    if not parsed.scheme:
        url = f"https://{url}"
    return url


def normalize_domain(url: str) -> str:
    """example.com из https://www.example.com/page; sub.example.com сохраняется."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or "unknown"


def get_base_domain(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def is_same_domain(base_url: str, link_url: str) -> bool:
    base = urlparse(base_url)
    link = urlparse(link_url)
    return base.netloc.lower() == link.netloc.lower()


def strip_fragment(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=""))


def resolve_internal_url(base_url: str, href: str) -> str | None:
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https"):
        return None
    return strip_fragment(absolute)


def domain_to_filename(url: str) -> str:
    netloc = urlparse(url).netloc or "unknown"
    safe = netloc.replace(".", "_").replace(":", "_")
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    return f"{safe}_{timestamp}.html"


def default_headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
