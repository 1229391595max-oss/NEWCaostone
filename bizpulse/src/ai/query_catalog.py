"""Versioned closed query-tool catalog and deterministic recommended plans."""

from __future__ import annotations

from types import MappingProxyType

from src.ai.contracts import QueryPlan
from src.ai.prompt_catalog import PromptCatalog

QUERY_CATALOG_VERSION = "query-catalog.v1"
QUERY_TOOL_NAMES = (
    "metric_lookup",
    "trend_compare",
    "sku_rank",
    "profit_bridge_explain",
    "inventory_risk_lookup",
    "forecast_lookup",
    "data_quality_lookup",
    "action_card_lookup",
    "monthly_sales_report_lookup",
)

_CAPABILITIES = MappingProxyType(
    {
        "metric_lookup": {
            "metrics": [
                "gross_sales",
                "net_sales",
                "units",
                "orders",
                "aov",
                "ad_spend",
                "contribution_profit",
                "operating_profit",
            ],
            "periods": ["current", "previous"],
        },
        "trend_compare": {
            "metrics": ["net_sales", "units", "orders", "ad_spend"],
            "comparisons": ["current_vs_previous", "daily_current"],
        },
        "sku_rank": {
            "metrics": [
                "net_sales",
                "units",
                "ad_spend",
                "inventory_cover",
                "replenishment_quantity",
                "replenishment_cash",
                "contribution_profit",
            ],
            "directions": ["top", "bottom"],
            "max_items": 20,
        },
        "profit_bridge_explain": {"views": ["drivers", "summary"]},
        "inventory_risk_lookup": {
            "views": ["risks", "replenishment"],
            "risks": ["all", "stockout", "balanced", "overstock", "unknown"],
            "max_items": 20,
        },
        "forecast_lookup": {
            "horizons": [7, 30, 90],
            "views": ["inputs", "scenarios", "analogs", "limitations"],
        },
        "data_quality_lookup": {
            "sections": [
                "coverage",
                "limitations",
                "evidence",
                "missing",
                "mapping",
            ]
        },
        "action_card_lookup": {
            "statuses": ["all", "new", "reviewed", "approved", "dismissed"],
            "views": ["summary", "revisions", "decisions", "exports", "outcomes"],
            "max_items": 20,
        },
        "monthly_sales_report_lookup": {
            "reports": ["latest_completed"],
        },
    }
)

_PROMPT_INTENTS = MappingProxyType(
    {
        "monthly_sales_report": {
            "tool": "monthly_sales_report_lookup",
            "arguments": {"report": "latest_completed"},
        },
        "profit_changes": {
            "tool": "profit_bridge_explain",
            "arguments": {"view": "drivers"},
        },
        "inventory_risks": {
            "tool": "inventory_risk_lookup",
            "arguments": {"risk": "stockout", "limit": 20},
        },
        "advertising_performance": {
            "tool": "metric_lookup",
            "arguments": {"metric": "ad_spend", "period": "current"},
        },
        "forecast_30_days": {
            "tool": "forecast_lookup",
            "arguments": {"horizon_days": 30, "view": "scenarios"},
        },
        "next_actions": {
            "tool": "action_card_lookup",
            "arguments": {"status": "all", "view": "summary", "limit": 20},
        },
    }
)


class RecommendedQuestionUnknown(ValueError):
    pass


class QueryCatalog:
    version = QUERY_CATALOG_VERSION

    def __init__(self, prompt_catalog: PromptCatalog | None = None) -> None:
        self.prompt_catalog = prompt_catalog or PromptCatalog.default()

    def capability_catalog(self) -> dict[str, object]:
        return {name: dict(_CAPABILITIES[name]) for name in QUERY_TOOL_NAMES}

    def plan_for_recommended(self, question_id: str, scope) -> QueryPlan:
        del scope
        preset = self.prompt_catalog.get(question_id)
        value = _PROMPT_INTENTS.get(preset.intent)
        if value is None:
            raise RecommendedQuestionUnknown("recommended_question_unknown")
        return QueryPlan.model_validate(value)

    def plan_for_intent(self, intent: str, scope) -> QueryPlan:
        del scope
        value = _PROMPT_INTENTS.get(intent)
        if value is None:
            raise RecommendedQuestionUnknown("recommended_question_unknown")
        return QueryPlan.model_validate(value)

    def recommended_ids(self) -> tuple[str, ...]:
        return self.prompt_catalog.ids()

    def recommended_questions(self) -> tuple[dict[str, object], ...]:
        return self.prompt_catalog.public_items()
