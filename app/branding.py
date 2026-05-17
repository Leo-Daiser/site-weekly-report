from __future__ import annotations

import base64
import json
import re
from pathlib import Path

from app.models import BrandingConfig

DEFAULT_BRAND_COLOR = "#2563eb"
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_LOGO_MIME: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
}
_SUPPORTED_LOGO_EXTENSIONS = frozenset(_LOGO_MIME.keys())


def validate_brand_color(color: str, warnings: list[str] | None = None) -> str:
    normalized = (color or "").strip()
    if _HEX_COLOR_RE.match(normalized):
        return normalized
    if warnings is not None:
        warnings.append(f"Невалидный brand color '{color}', используется {DEFAULT_BRAND_COLOR}")
    return DEFAULT_BRAND_COLOR


def load_branding_config(path: str | None) -> BrandingConfig:
    if path is None:
        return BrandingConfig()
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Branding file not found: {path}")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return BrandingConfig.model_validate(data)


def merge_branding_config(
    file_config: BrandingConfig,
    cli_overrides: dict[str, object],
) -> BrandingConfig:
    merged = file_config.model_dump()
    for key, value in cli_overrides.items():
        if value is not None:
            merged[key] = value
    return BrandingConfig.model_validate(merged)


def prepare_logo_data_uri(logo_path: str | None) -> tuple[str | None, list[str]]:
    if not logo_path:
        return None, []

    path = Path(logo_path)
    warnings: list[str] = []
    suffix = path.suffix.lower()
    if suffix not in _SUPPORTED_LOGO_EXTENSIONS:
        warnings.append(f"Unsupported logo format: {suffix or '(none)'}")
        return None, warnings

    mime = _LOGO_MIME[suffix]
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError as exc:
        warnings.append(f"Could not read logo file: {exc}")
        return None, warnings

    return f"data:{mime};base64,{encoded}", warnings


def resolve_branding(
    file_config: BrandingConfig,
    cli_overrides: dict[str, object],
    project_root: Path,
) -> tuple[BrandingConfig, list[str]]:
    warnings: list[str] = []
    config = merge_branding_config(file_config, cli_overrides)
    config.brand_color = validate_brand_color(config.brand_color, warnings)

    if config.logo_path:
        logo = Path(config.logo_path)
        if not logo.is_absolute():
            logo = project_root / logo
        if not logo.is_file():
            warnings.append(f"Logo file not found: {config.logo_path}")
            config.logo_path = None
        else:
            resolved = str(logo.resolve())
            suffix = logo.suffix.lower()
            if suffix not in _SUPPORTED_LOGO_EXTENSIONS:
                warnings.append(f"Unsupported logo format: {suffix or '(none)'}")
                config.logo_path = None
            else:
                config.logo_path = resolved

    return config, warnings
