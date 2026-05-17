from __future__ import annotations

import json
from pathlib import Path

from app.models import PricingConfig, PricingPlan

DEFAULT_PRICING: dict[str, object] = {
    "currency": "USD",
    "plans": {
        "starter": {
            "name": "Starter",
            "price_monthly": 29,
            "setup_fee": 0,
            "sites_included": 1,
            "description": "Weekly report for one website",
            "features": [
                "1 website",
                "Weekly HTML report",
                "Availability check",
                "Basic SEO checks",
                "Broken internal links",
                "Top 3 actions",
            ],
        },
        "agency-lite": {
            "name": "Agency Lite",
            "price_monthly": 79,
            "setup_fee": 99,
            "sites_included": 5,
            "description": "White-label weekly reports for up to 5 websites",
            "features": [
                "Up to 5 websites",
                "White-label HTML/PDF reports",
                "Weekly site health score",
                "SEO basics",
                "Broken links",
                "Forms check",
                "Change tracking",
                "Email-ready report package",
            ],
        },
        "agency": {
            "name": "Agency",
            "price_monthly": 149,
            "setup_fee": 149,
            "sites_included": 15,
            "description": "White-label reporting package for small agencies",
            "features": [
                "Up to 15 websites",
                "White-label HTML/PDF reports",
                "Batch reports",
                "Weekly change tracking",
                "Outbox/email delivery support",
                "Priority report customization",
            ],
        },
    },
}


def _parse_pricing_data(data: dict[str, object]) -> PricingConfig:
    currency = str(data.get("currency") or "USD")
    raw_plans = data.get("plans")
    if not isinstance(raw_plans, dict):
        raise ValueError("pricing config must contain a 'plans' object")

    plans: dict[str, PricingPlan] = {}
    for plan_id, plan_data in raw_plans.items():
        if not isinstance(plan_data, dict):
            continue
        plans[plan_id] = PricingPlan(
            plan_id=plan_id,
            name=str(plan_data.get("name") or plan_id),
            price_monthly=plan_data.get("price_monthly", 0),  # type: ignore[arg-type]
            setup_fee=plan_data.get("setup_fee", 0),  # type: ignore[arg-type]
            sites_included=int(plan_data.get("sites_included", 1)),  # type: ignore[arg-type]
            description=str(plan_data.get("description") or ""),
            features=[
                str(item)
                for item in (plan_data.get("features") or [])
                if str(item).strip()
            ],
        )
    return PricingConfig(currency=currency, plans=plans)


def load_pricing_config(path: Path) -> tuple[PricingConfig, list[str]]:
    """Load pricing config. Returns (config, warnings)."""
    warnings: list[str] = []
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Invalid pricing config: {path}")
        return _parse_pricing_data(data), warnings

    warnings.append(
        f"Pricing file not found ({path}); using built-in default pricing config."
    )
    return _parse_pricing_data(DEFAULT_PRICING), warnings


def get_plan(config: PricingConfig, plan_id: str) -> PricingPlan:
    needle = plan_id.strip().lower()
    for key, plan in config.plans.items():
        if key.lower() == needle:
            return plan
    available = ", ".join(sorted(config.plans.keys()))
    raise ValueError(f"Unknown plan_id '{plan_id}'. Available plans: {available}")


def list_plans(config: PricingConfig) -> list[PricingPlan]:
    return [config.plans[key] for key in sorted(config.plans.keys())]
