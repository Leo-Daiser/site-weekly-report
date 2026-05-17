from __future__ import annotations

from pathlib import Path


class ScreenshotError(Exception):
    pass


def capture_homepage_screenshot(url: str, output_path: Path, timeout_ms: int = 15000) -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise ScreenshotError("Playwright is not available; install Chromium to enable screenshots") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1365, "height": 900})
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            page.screenshot(path=str(output_path), full_page=False)
            browser.close()
    except Exception as exc:
        raise ScreenshotError(f"Screenshot failed: {type(exc).__name__}: {exc}") from exc
    return output_path
