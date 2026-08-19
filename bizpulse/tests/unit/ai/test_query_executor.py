from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest

from src.ai.contracts import AuthoritativeFact, QueryPlan, QueryScope, ToolResult
from src.ai.query_executor import (
    QueryExecutionFailed,
    QueryExecutor,
    QueryPlanRejected,
    QueryResultTooLarge,
)


class CountingBackend:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, plan, scope):
        self.calls += 1
        return {
            "facts": [
                {
                    "fact_ref": "fact-001",
                    "label": "Net sales",
                    "value": "100.00 BRL",
                    "evidence_state": "measured",
                    "evidence_refs": ["analysis:sales_ads:net_sales"],
                }
            ],
            "limitations": [],
            "action_card_draft": None,
        }


def fixed_scope() -> QueryScope:
    return QueryScope(
        workspace_id="synthetic-demo",
        dataset_version_id=UUID("00000000-0000-0000-0000-000000000001"),
        store_ids=("SYNTH-STORE-01",),
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 30),
        currency="BRL",
    )


def test_model_plan_cannot_supply_scope_or_sql() -> None:
    backend = CountingBackend()
    executor = QueryExecutor(backend=backend)
    plan = QueryPlan.model_validate(
        {
            "tool": "metric_lookup",
            "arguments": {"metric": "net_sales", "period": "current"},
        }
    )

    result = executor.execute(plan, fixed_scope())

    assert result.scope.dataset_version_id == fixed_scope().dataset_version_id
    assert result.scope.store_ids == ("SYNTH-STORE-01",)
    assert "sql" not in result.model_dump_json().lower()
    assert backend.calls == 1


def test_monthly_report_plan_has_no_model_controlled_scope_fields() -> None:
    backend = CountingBackend()
    executor = QueryExecutor(backend=backend)

    result = executor.execute_unvalidated(
        {
            "tool": "monthly_sales_report_lookup",
            "arguments": {"report": "latest_completed"},
        },
        fixed_scope(),
    )

    assert result.tool == "monthly_sales_report_lookup"
    assert result.scope == fixed_scope()
    assert backend.calls == 1

    with pytest.raises(QueryPlanRejected, match="invalid_plan"):
        executor.execute_unvalidated(
            {
                "tool": "monthly_sales_report_lookup",
                "arguments": {
                    "report": "latest_completed",
                    "period_start": "2026-01-01",
                },
            },
            fixed_scope(),
        )


@pytest.mark.parametrize("tool", ["sql", "schema_lookup", "export_rows", "write_action"])
def test_unknown_or_mutating_tool_fails_before_backend(tool: str) -> None:
    backend = CountingBackend()
    executor = QueryExecutor(backend=backend)

    with pytest.raises(QueryPlanRejected, match="unknown_tool"):
        executor.execute_unvalidated({"tool": tool, "arguments": {}}, fixed_scope())

    assert backend.calls == 0


def test_more_than_ten_evidence_aliases_fails_closed() -> None:
    class TooManyAliasesBackend:
        def execute(self, plan, scope):
            del plan, scope
            return {
                "facts": [
                    {
                        "fact_ref": f"fact-{index:03d}",
                        "label": f"Synthetic fact {index}",
                        "value": "known",
                        "evidence_state": "measured",
                        "evidence_refs": [f"analysis:synthetic:alias-{index}"],
                    }
                    for index in range(1, 12)
                ],
                "limitations": [],
                "action_card_draft": None,
            }

    executor = QueryExecutor(backend=TooManyAliasesBackend())
    plan = QueryPlan.model_validate(
        {
            "tool": "metric_lookup",
            "arguments": {"metric": "net_sales", "period": "current"},
        }
    )

    with pytest.raises(QueryResultTooLarge, match="query_evidence_aliases_too_large"):
        executor.execute(plan, fixed_scope())


def test_prebuilt_tool_result_is_revalidated_and_hash_must_match() -> None:
    class PrebuiltBackend:
        def execute(self, plan, scope):
            return ToolResult(
                tool=plan.tool,
                scope=scope,
                facts=(
                    AuthoritativeFact(
                        fact_ref="fact-001",
                        label="Net sales",
                        value="100.00 BRL",
                        evidence_state="measured",
                        evidence_refs=("analysis:synthetic:net_sales",),
                    ),
                ),
                limitations=("sample_data_only",),
                result_hash="f" * 64,
                action_card_draft=None,
            )

    executor = QueryExecutor(backend=PrebuiltBackend())
    plan = QueryPlan.model_validate(
        {
            "tool": "metric_lookup",
            "arguments": {"metric": "net_sales", "period": "current"},
        }
    )

    with pytest.raises(QueryExecutionFailed, match="backend_result_hash_mismatch"):
        executor.execute(plan, fixed_scope())
