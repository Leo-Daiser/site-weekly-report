from __future__ import annotations

import os
from pathlib import Path

CHROMIUM_INSTALL_HINT = "python -m playwright install chromium"

PDF_EXPORT_FAILED = "PDF export failed."

PDF_INSTALL_PLAYWRIGHT = (
    f"{PDF_EXPORT_FAILED} Install Playwright:\n"
    f"  pip install playwright\n"
    f"  {CHROMIUM_INSTALL_HINT}"
)

PDF_INSTALL_CHROMIUM = (
    f"{PDF_EXPORT_FAILED} Install Playwright Chromium:\n"
    f"  {CHROMIUM_INSTALL_HINT}"
)


class PdfExportError(Exception):
    """Ошибка экспорта HTML в PDF."""


def _is_missing_browser_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    markers = (
        "executable doesn't exist",
        "browser_type.launch",
        "failed to launch",
        "chromium",
        "playwright install",
        "headless_shell",
    )
    return any(marker in message for marker in markers)


def _playwright_browsers_dir() -> Path:
    env_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env_path:
        return Path(env_path)
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        return Path(local_app) / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def _find_chromium_executable() -> Path | None:
    root = _playwright_browsers_dir()
    if not root.is_dir():
        return None

    candidates: list[Path] = []
    for chromium_dir in sorted(root.glob("chromium-*"), reverse=True):
        for rel in (
            "chrome-win64/chrome.exe",
            "chrome-linux/chrome",
            "chrome-mac/Chromium.app/Contents/MacOS/Chromium",
        ):
            path = chromium_dir / rel
            if path.is_file():
                candidates.append(path)

    return candidates[0] if candidates else None


def _launch_chromium(playwright: object) -> object:
    chromium = playwright.chromium  # type: ignore[attr-defined]
    try:
        return chromium.launch()
    except Exception as exc:
        if not _is_missing_browser_error(exc):
            raise
        executable = _find_chromium_executable()
        if executable is None:
            raise PdfExportError(PDF_INSTALL_CHROMIUM) from exc
        return chromium.launch(executable_path=str(executable))


def export_html_to_pdf(html_path: Path, pdf_path: Path) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PdfExportError(PDF_INSTALL_PLAYWRIGHT) from exc

    html_uri = html_path.resolve().as_uri()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as playwright:
            browser = _launch_chromium(playwright)
            try:
                page = browser.new_page()
                page.goto(html_uri, wait_until="load")
                page.pdf(
                    path=str(pdf_path),
                    format="A4",
                    print_background=True,
                    margin={
                        "top": "12mm",
                        "bottom": "12mm",
                        "left": "10mm",
                        "right": "10mm",
                    },
                )
            finally:
                browser.close()
    except PdfExportError:
        raise
    except Exception as exc:
        if _is_missing_browser_error(exc):
            raise PdfExportError(PDF_INSTALL_CHROMIUM) from exc
        raise PdfExportError(PDF_INSTALL_CHROMIUM) from exc
