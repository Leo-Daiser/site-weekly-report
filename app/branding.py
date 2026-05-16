from __future__ import annotations

import json
import re
from pathlib import Path

from app.models import BrandingConfig

DEFAULT_BRAND_COLOR = "#2563eb"
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


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
            config.logo_path = str(logo.resolve())

    return config, warnings
