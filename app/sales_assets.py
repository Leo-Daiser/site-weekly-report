from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

SALES_ASSET_TEMPLATES: dict[str, str] = {
    "landing_copy.md": "sales_landing_copy.md.j2",
    "pricing.md": "sales_pricing.md.j2",
    "faq.md": "sales_faq.md.j2",
    "short_pitch.md": "sales_short_pitch.md.j2",
    "outreach_messages.md": "sales_outreach_messages.md.j2",
    "objections.md": "sales_objections.md.j2",
    "demo_report_notes.md": "sales_demo_report_notes.md.j2",
}


class SalesPlanItem(BaseModel):
    id: str
    name: str
    price: int | float
    description: str = ""


class SalesPackConfig(BaseModel):
    product_name: str
    target_audience: str
    positioning: str
    primary_offer: str
    currency: str = "USD"
    plans: list[SalesPlanItem] = Field(default_factory=list)
    main_benefits: list[str] = Field(default_factory=list)
    demo_report_path: str = ""


def load_sales_pack_config(path: Path) -> SalesPackConfig:
    if not path.is_file():
        raise FileNotFoundError(f"Sales pack config not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return SalesPackConfig.model_validate(data)


def build_template_context(config: SalesPackConfig, *, generated_at: str) -> dict[str, object]:
    agency_lite = next((p for p in config.plans if p.id == "agency-lite"), None)
    return {
        "config": config,
        "product_name": config.product_name,
        "target_audience": config.target_audience,
        "positioning": config.positioning,
        "primary_offer": config.primary_offer,
        "currency": config.currency,
        "plans": config.plans,
        "main_benefits": config.main_benefits,
        "demo_report_path": config.demo_report_path,
        "generated_at": generated_at,
        "agency_lite": agency_lite,
    }


def _template_env(template_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def render_sales_asset(
    template_name: str,
    context: dict[str, object],
    *,
    template_dir: Path,
) -> str:
    env = _template_env(template_dir)
    return env.get_template(template_name).render(**context).strip() + "\n"


def _markdown_to_simple_html(title: str, markdown_body: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{escape(title)}</title>\n"
        "  <style>\n"
        "    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; "
        "line-height: 1.6; color: #1e293b; max-width: 760px; margin: 2rem auto; padding: 0 1rem; }\n"
        "    pre { white-space: pre-wrap; word-wrap: break-word; background: #f8fafc; "
        "border: 1px solid #e2e8f0; border-radius: 8px; padding: 1.25rem; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        f"  <pre>{escape(markdown_body)}</pre>\n"
        "</body>\n"
        "</html>\n"
    )


def _write_asset_files(
    *,
    output_dir: Path,
    filename: str,
    markdown_content: str,
    output_format: str,
) -> list[Path]:
    written: list[Path] = []
    md_path = output_dir / filename
    md_path.write_text(markdown_content, encoding="utf-8")
    written.append(md_path)

    fmt = output_format.lower()
    if fmt in ("html", "both"):
        title = filename.replace(".md", "").replace("_", " ").title()
        html_path = output_dir / filename.replace(".md", ".html")
        html_path.write_text(
            _markdown_to_simple_html(title, markdown_content),
            encoding="utf-8",
        )
        written.append(html_path)
    return written


def generate_sales_pack(
    config: SalesPackConfig,
    output_dir: Path,
    *,
    template_dir: Path,
    output_format: str = "md",
) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    pack_dir = output_dir / f"generated_{stamp}"
    pack_dir.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now().replace(microsecond=0).isoformat(sep=" ")
    context = build_template_context(config, generated_at=generated_at)

    generated_files: list[str] = []
    for filename, template_name in SALES_ASSET_TEMPLATES.items():
        content = render_sales_asset(template_name, context, template_dir=template_dir)
        _write_asset_files(
            output_dir=pack_dir,
            filename=filename,
            markdown_content=content,
            output_format=output_format,
        )
        generated_files.append(filename)

    index_lines = [
        "# Sales Pack Index",
        "",
        f"Product: {config.product_name}",
        f"Generated: {generated_at}",
        "",
    ]
    for name in generated_files:
        index_lines.append(f"- {name}")
    index_content = "\n".join(index_lines) + "\n"
    _write_asset_files(
        output_dir=pack_dir,
        filename="sales_pack_index.md",
        markdown_content=index_content,
        output_format=output_format,
    )

    return pack_dir
