from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.ai.contracts import QueryPlan
from src.ai.query_catalog import QUERY_TOOL_NAMES, QueryCatalog


EXPECTED_TOOLS = {
    "metric_lookup",
    "trend_compare",
    "sku_rank",
    "profit_bridge_explain",
    "inventory_risk_lookup",
    "forecast_lookup",
    "data_quality_lookup",
    "action_card_lookup",
    "monthly_sales_report_lookup",
}


def test_catalog_exposes_only_the_approved_nine_tools() -> None:
    assert set(QUERY_TOOL_NAMES) == EXPECTED_TOOLS
    assert set(QueryCatalog().capability_catalog()) == EXPECTED_TOOLS


def test_recommended_plan_is_deterministic_and_has_no_server_scope() -> None:
    plan = QueryCatalog().plan_for_recommended(
        "advertising_performance",
        {
            "dataset_version_id": "00000000-0000-0000-0000-000000000001",
            "store_ids": ["SYNTH-STORE-01"],
        },
    )

    assert plan.tool == "metric_lookup"
    assert plan.arguments.metric == "ad_spend"
    payload = plan.model_dump(mode="json")
    assert "dataset_version_id" not in str(payload)
    assert "store_ids" not in str(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"tool": "sql", "arguments": {}},
        {
            "tool": "metric_lookup",
            "arguments": {"metric": "net_sales", "period": "current", "sql": "x"},
        },
        {
            "tool": "metric_lookup",
            "arguments": {
                "metric": "net_sales",
                "period": "current",
                "dataset_version_id": "00000000-0000-0000-0000-000000000001",
            },
        },
    ],
)
def test_plan_rejects_unknown_tools_sql_and_model_scope(payload) -> None:
    with pytest.raises(ValidationError):
        QueryPlan.model_validate(payload)
