from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Connection, Engine, text

from src.ai.contracts import QueryPlan, QueryScope
from src.ai.query_catalog import QueryCatalog
from src.ai.query_executor import (
    PostgresQueryBackend,
    QueryExecutionFailed,
    QueryExecutor,
)
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.services.action_service import ActionService
from src.services.analysis_service import AnalysisAuthorityUnavailable, AnalysisService
from src.services.forecast_service import ForecastService
from src.services.profit_bridge_service import ProfitBridgeService
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID
from tests.services.test_action_service import _action_authority, _source
from tests.services.test_forecast_service import _request

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def _assert_query_controls(connection: Connection) -> None:
    read_only, timeout = connection.execute(
        text(
            "SELECT current_setting('transaction_read_only'), "
            "current_setting('statement_timeout')"
        )
    ).one()
    assert read_only == "on"
    assert timeout in {"5s", "5000ms"}


class _ControlledAnalysisService(AnalysisService):
    probes: set[str]

    def get_exact_completed(self, *args, **kwargs):
        raise AssertionError("uncontrolled analysis connection")

    def read_exact_completed(self, connection, *args, **kwargs):
        _assert_query_controls(connection)
        self.probes.add("analysis")
        return super().read_exact_completed(connection, *args, **kwargs)


class _ControlledForecastService(ForecastService):
    probes: set[str]

    def latest_completed(self, *args, **kwargs):
        raise AssertionError("uncontrolled forecast connection")

    def get_completed_for_session(self, *args, **kwargs):
        raise AssertionError("uncontrolled forecast connection")

    def read_completed(self, connection, *args, **kwargs):
        _assert_query_controls(connection)
        self.probes.add("forecast")
        return super().read_completed(connection, *args, **kwargs)


class _ControlledProfitBridgeService(ProfitBridgeService):
    probes: set[str]

    def default(self, *args, **kwargs):
        raise AssertionError("uncontrolled profit bridge connection")

    def get_for_session(self, *args, **kwargs):
        raise AssertionError("uncontrolled profit bridge connection")

    def read_for_query(self, connection, *args, **kwargs):
        _assert_query_controls(connection)
        self.probes.add("profit_bridge")
        return super().read_for_query(connection, *args, **kwargs)


class _ControlledActionService(ActionService):
    probes: set[str]

    def list(self, *args, **kwargs):
        raise AssertionError("uncontrolled action connection")

    def list_public(self, *args, **kwargs):
        raise AssertionError("uncontrolled action connection")

    def read_for_query(self, connection, *args, **kwargs):
        _assert_query_controls(connection)
        self.probes.add("action")
        return super().read_for_query(connection, *args, **kwargs)


def test_all_registered_tools_read_only_exact_synthetic_authorities(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    seeded = seed_demo(
        generate_demo(),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=NOW,
    )
    analyses = AnalysisService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=lambda: NOW,
    )
    forecasts = ForecastService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=lambda: NOW,
    )
    forecast = forecasts.create(
        seeded.dataset_version_id,
        _request(),
        scope={"currency": "BRL", "store_id": "SYNTH-STORE-01"},
        idempotency_key="ai-tool-forecast",
    )
    forecasts.confirm_analogs(
        forecast.id,
        tuple(item.sku_id for item in forecast.analogs[:2]),
    )
    completed_forecast = forecasts.run(forecast.id)
    bridges = ProfitBridgeService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        analysis_service=analyses,
        clock=lambda: NOW,
    )
    bridge = bridges.default(
        seeded.dataset_version_id,
        {"currency": "BRL", "store_id": "SYNTH-STORE-01"},
    )
    actions = ActionService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=lambda: NOW,
    )
    analysis_run_id, action_facts = _action_authority(
        migrated_engine,
        storage,
        seeded.dataset_version_id,
    )
    actions.create_draft(
        _source(seeded.dataset_version_id, analysis_run_id, action_facts),
        action_facts,
        "ai-tool-action",
    )
    scope = QueryScope(
        workspace_id=WORKSPACE_ID,
        actor_kind="operator",
        dataset_version_id=seeded.dataset_version_id,
        store_ids=("SYNTH-STORE-01",),
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        forecast_id=completed_forecast.id,
        profit_bridge_id=bridge.id,
    )
    probes: set[str] = set()
    controlled_analyses = _ControlledAnalysisService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=lambda: NOW,
    )
    controlled_analyses.probes = probes
    controlled_forecasts = _ControlledForecastService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=lambda: NOW,
    )
    controlled_forecasts.probes = probes
    controlled_bridges = _ControlledProfitBridgeService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        analysis_service=controlled_analyses,
        clock=lambda: NOW,
    )
    controlled_bridges.probes = probes
    controlled_actions = _ControlledActionService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=lambda: NOW,
    )
    controlled_actions.probes = probes
    executor = QueryExecutor(
        backend=PostgresQueryBackend(
            engine=migrated_engine,
            analysis_service=controlled_analyses,
            forecast_service=controlled_forecasts,
            profit_bridge_service=controlled_bridges,
            action_service=controlled_actions,
        )
    )
    catalog = QueryCatalog()

    for preset in catalog.prompt_catalog.items():
        if not preset.available:
            continue
        plan = catalog.plan_for_recommended(preset.id, scope)
        result = executor.execute(plan, scope)

        assert result.tool == plan.tool
        assert result.scope == scope
        assert len(result.facts) <= 25
        assert "sample_data_only" in result.limitations
        serialized = result.model_dump_json().lower()
        assert "postgresql" not in serialized
        assert "select " not in serialized
        assert "database_url" not in serialized
        if preset.id == "monthly_sales_report":
            facts = {fact.label: fact.value for fact in result.facts}
            assert facts["report_period"] == "2026-07-01..2026-07-31"
            assert "net_sales_brl" in facts
            assert "previous_net_sales_brl" in facts

    assert probes == {"analysis", "forecast", "profit_bridge", "action"}

    trend = executor.execute(
        QueryPlan.model_validate(
            {
                "tool": "trend_compare",
                "arguments": {
                    "metric": "net_sales",
                    "comparison": "daily_current",
                },
            }
        ),
        scope,
    )
    assert len(trend.facts) <= 25
    assert "daily_trend_aggregated_to_bounded_period_buckets" in trend.limitations

    for metric in ("units", "orders"):
        result = executor.execute(
            QueryPlan.model_validate(
                {
                    "tool": "trend_compare",
                    "arguments": {
                        "metric": metric,
                        "comparison": "daily_current",
                    },
                }
            ),
            scope,
        )
        assert result.facts == ()
        assert f"daily_{metric}_unavailable" in result.limitations

    quality_labels = {}
    for section in ("coverage", "limitations", "evidence", "missing", "mapping"):
        result = executor.execute(
            QueryPlan.model_validate(
                {
                    "tool": "data_quality_lookup",
                    "arguments": {"section": section},
                }
            ),
            scope,
        )
        quality_labels[section] = tuple(fact.label for fact in result.facts)
    assert len(set(quality_labels.values())) == 5

    replenishment_lookup = executor.execute(
        QueryPlan.model_validate(
            {
                "tool": "inventory_risk_lookup",
                "arguments": {
                    "view": "replenishment",
                    "risk": "all",
                    "limit": 20,
                },
            }
        ),
        scope,
    )
    assert replenishment_lookup.facts
    assert all("replenishment result" in fact.label for fact in replenishment_lookup.facts)

    replenishment_rank = executor.execute(
        QueryPlan.model_validate(
            {
                "tool": "sku_rank",
                "arguments": {
                    "metric": "replenishment_quantity",
                    "direction": "top",
                    "limit": 10,
                },
            }
        ),
        scope,
    )
    assert replenishment_rank.facts
    assert all("replenishment_quantity" in fact.label for fact in replenishment_rank.facts)

    sku_profit = executor.execute(
        QueryPlan.model_validate(
            {
                "tool": "sku_rank",
                "arguments": {
                    "metric": "contribution_profit",
                    "direction": "top",
                    "limit": 10,
                },
            }
        ),
        scope,
    )
    assert sku_profit.facts == ()
    assert (
        "sku_contribution_profit_authority_unavailable_without_sku_allocated_costs"
        in sku_profit.limitations
    )

    forecast_inputs = executor.execute(
        QueryPlan.model_validate(
            {
                "tool": "forecast_lookup",
                "arguments": {"horizon_days": 30, "view": "inputs"},
            }
        ),
        scope,
    )
    assert forecast_inputs.facts
    assert {fact.label for fact in forecast_inputs.facts} >= {
        "Candidate product",
        "Planned price BRL",
        "MOQ units",
        "Lead time days",
    }

    for view in ("summary", "revisions", "decisions", "exports", "outcomes"):
        result = executor.execute(
            QueryPlan.model_validate(
                {
                    "tool": "action_card_lookup",
                    "arguments": {"status": "all", "view": view, "limit": 10},
                }
            ),
            scope,
        )
        assert all(f"action {view}" in fact.label for fact in result.facts)

    unpinned_demo_scope = scope.model_copy(
        update={
            "actor_kind": "demo",
            "forecast_id": None,
            "profit_bridge_id": None,
        }
    )
    unpinned_forecast = executor.execute(
        catalog.plan_for_recommended("forecast_30_days", unpinned_demo_scope),
        unpinned_demo_scope,
    )
    assert unpinned_forecast.facts == ()
    assert "forecast_not_pinned_to_session" in unpinned_forecast.limitations
    unpinned_bridge = executor.execute(
        catalog.plan_for_recommended("profit_changes", unpinned_demo_scope),
        unpinned_demo_scope,
    )
    assert unpinned_bridge.facts == ()
    assert "profit_bridge_not_pinned_to_session" in unpinned_bridge.limitations

    class UnavailableAnalysisService:
        def read_exact_completed(self, *args, **kwargs):
            del args, kwargs
            raise AnalysisAuthorityUnavailable("verified_blob_read_failed")

    unavailable_executor = QueryExecutor(
        backend=PostgresQueryBackend(
            engine=migrated_engine,
            analysis_service=UnavailableAnalysisService(),
            forecast_service=controlled_forecasts,
            profit_bridge_service=controlled_bridges,
            action_service=controlled_actions,
        )
    )
    with pytest.raises(QueryExecutionFailed, match="query_authority_unavailable"):
        unavailable_executor.execute(
            catalog.plan_for_recommended("advertising_performance", scope),
            scope,
        )


def test_query_scope_accepts_server_resolved_ids_but_rejects_malformed_tuples() -> None:
    resolved = QueryScope(
        workspace_id=WORKSPACE_ID,
        actor_kind="operator",
        dataset_version_id="8df2ff5e-ed7e-5ae2-b3e8-4bb5ae9e2550",
        store_ids=("REAL-STORE-01",),
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 30),
    )
    assert resolved.store_ids == ("REAL-STORE-01",)

    for malformed in (("",), (" STORE-01",), ("STORE-01", "STORE-01")):
        with pytest.raises(ValueError, match="query_scope_store_invalid"):
            QueryScope(
                workspace_id=WORKSPACE_ID,
                actor_kind="operator",
                dataset_version_id="8df2ff5e-ed7e-5ae2-b3e8-4bb5ae9e2550",
                store_ids=malformed,
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 30),
            )
