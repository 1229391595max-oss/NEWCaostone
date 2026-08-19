"""Idempotent public Action authority for the pure-synthetic Demo."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.actions.contracts import ActionSource, FactRef
from src.services.action_service import ActionService
from src.services.analysis_service import AnalysisService
from src.services.profit_bridge_service import ProfitBridgeService
from src.services.public_release_service import PUBLIC_ANALYSIS_SCOPE
from src.synthetic.release_profile import PUBLIC_RELEASE_PROFILE


class DemoActionAuthority:
    """Prepare and verify one evidence-backed approved Action per release."""

    def __init__(
        self,
        engine,
        storage,
        workspace_id: str,
        *,
        clock=None,
        profit_bridge_service=None,
    ) -> None:
        self._analyses = AnalysisService(
            engine,
            storage,
            workspace_id,
            clock=clock,
        )
        self._actions = ActionService(
            engine,
            storage,
            workspace_id,
            clock=clock,
        )
        self._bridges = profit_bridge_service or ProfitBridgeService(
            engine,
            storage,
            workspace_id,
            analysis_service=self._analyses,
            clock=clock,
        )

    def ensure(self, dataset_version_id, scope=None):
        identity_scope = dict(scope or {"currency": "BRL"})
        analysis_scope = {
            **PUBLIC_ANALYSIS_SCOPE,
            **identity_scope,
        }
        if "store_id" not in identity_scope:
            analysis_scope.pop("store_id", None)
        scope_token = str(identity_scope.get("store_id", "all"))
        run, snapshot, evidence_rows = self._analyses.get_exact_completed(
            "replenishment",
            dataset_version_id,
            analysis_scope,
        )
        evidence = {item.alias: item for item in evidence_rows}
        try:
            item = next(
                candidate
                for candidate in snapshot["result"]["items"]
                if candidate.get("sku_id")
                and candidate.get("recommended_quantity") is not None
                and candidate.get("latest_order_date") is not None
                and candidate.get("priority") is not None
            )
            sku_id = str(item["sku_id"])
            base_alias = f"replenishment:{sku_id}"
            authority = evidence[base_alias]
        except (KeyError, StopIteration, TypeError):
            return self._ensure_profit_review(dataset_version_id, identity_scope)
        fact_values = (
            ("recommended_quantity", item["recommended_quantity"]),
            ("latest_order_date", item["latest_order_date"]),
            ("priority", item["priority"]),
            ("cash_required.value", item.get("cash_required", {}).get("value")),
        )
        facts = tuple(
            FactRef(
                alias=f"{base_alias}|result.items.{sku_id}.{field}",
                evidence_state=authority.evidence_state,
                source_ref=(
                    f"analysis:{run.run_id}:{base_alias}|"
                    f"result.items.{sku_id}.{field}"
                ),
                value=str(value) if value is not None else None,
            )
            for field, value in fact_values
        )
        source = ActionSource(
            source_type="deterministic_rule",
            dataset_version_id=dataset_version_id,
            suggestion=f"Reorder {facts[0].value} units",
            target=sku_id,
            period_start=PUBLIC_RELEASE_PROFILE.current_period[0],
            period_end=PUBLIC_RELEASE_PROFILE.current_period[1],
            scope=dict(analysis_scope),
            quantity=Decimal(facts[0].value),
            budget_brl=(
                Decimal(fact_values[3][1])
                if fact_values[3][1] is not None
                else None
            ),
            action_date=date.fromisoformat(facts[1].value),
            threshold=None,
            expected_impact={"priority": facts[2].value},
            confidence="medium",
            limitations=("synthetic_demo_only",),
            analysis_run_id=run.run_id,
            forecast_id=None,
            bridge_id=None,
            chat_turn_id=None,
            chat_tool=None,
            answer_version=None,
        )
        action = self._actions.create_draft(
            source,
            facts,
            f"seed-action-create-{dataset_version_id}-{scope_token}",
        )
        reviewed = self._actions.review(
            action.id,
            action.current_revision,
            "Synthetic seed evidence reviewed",
            f"seed-action-review-{dataset_version_id}-{scope_token}",
        )
        return self._actions.approve(
            reviewed.id,
            reviewed.current_revision,
            "Synthetic seed action approved",
            f"seed-action-approve-{dataset_version_id}-{scope_token}",
        )

    def _ensure_profit_review(self, dataset_version_id, scope):
        scope_token = str(scope.get("store_id", "all"))
        bridge_id = self._bridges.completed_id_for_session(
            dataset_version_id,
            scope,
        )
        if bridge_id is None:
            raise ValueError("synthetic_action_authority_unavailable")
        bridge = self._bridges.get_for_session(dataset_version_id, bridge_id)
        if not bridge.items:
            raise ValueError("synthetic_action_authority_unavailable")
        facts = tuple(
            FactRef(
                alias=f"items.{item.driver}.amount_brl",
                evidence_state=item.evidence_state,
                source_ref=(
                    f"profit_bridge:{bridge.id}:items.{item.driver}.amount_brl"
                ),
                value=(
                    str(item.amount_brl)
                    if item.amount_brl is not None
                    else None
                ),
            )
            for item in bridge.items
        )
        source = ActionSource(
            source_type="profit_bridge",
            dataset_version_id=dataset_version_id,
            suggestion="Review synthetic contribution profit evidence",
            target=str(scope.get("store_id", "all_stores")),
            period_start=bridge.current_period[0],
            period_end=bridge.current_period[1],
            scope=dict(bridge.scope),
            quantity=None,
            budget_brl=None,
            action_date=None,
            threshold=None,
            expected_impact={},
            confidence=(
                "low"
                if any(item.evidence_state == "unknown" for item in bridge.items)
                else "medium"
            ),
            limitations=tuple(
                sorted({"synthetic_demo_only", *bridge.limitations})
            ),
            analysis_run_id=None,
            forecast_id=None,
            bridge_id=bridge.id,
            chat_turn_id=None,
            chat_tool=None,
            answer_version=None,
        )
        action = self._actions.create_draft(
            source,
            facts,
            f"seed-action-create-{dataset_version_id}-{scope_token}",
        )
        reviewed = self._actions.review(
            action.id,
            action.current_revision,
            "Synthetic Demo evidence reviewed",
            f"seed-action-review-{dataset_version_id}-{scope_token}",
        )
        return self._actions.approve(
            reviewed.id,
            reviewed.current_revision,
            "Synthetic Demo action approved",
            f"seed-action-approve-{dataset_version_id}-{scope_token}",
        )

    def ready(self, dataset_version_id, scope=None) -> bool:
        return any(
            action.status == "approved"
            for action in self._actions.list(dataset_version_id, scope)
        )
