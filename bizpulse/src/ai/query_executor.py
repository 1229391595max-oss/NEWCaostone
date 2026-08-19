"""Validated execution seam for registered read-only Ask BizPulse tools."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json

from pydantic import ValidationError
from sqlalchemy import Connection, select, text

from src.ai.contracts import AuthoritativeFact, QueryPlan, QueryScope, ToolResult
from src.ai.monthly_sales_report import (
    PrecomputedMonthlyReportReaders,
    read_monthly_sales_report,
)
from src.ai.query_catalog import QUERY_TOOL_NAMES
from src.db.schema import upload_records
from src.repositories.datasets import DatasetRepository
from src.services.analysis_service import AnalysisNotFound


class QueryPlanRejected(ValueError):
    pass


class QueryExecutionFailed(RuntimeError):
    pass


class QueryResultTooLarge(QueryExecutionFailed):
    pass


class QueryExecutor:
    """Validate before touching the registered backend and rebind server scope."""

    def __init__(self, *, backend) -> None:
        self._backend = backend

    def execute_unvalidated(
        self,
        raw_plan: object,
        server_scope: QueryScope,
    ) -> ToolResult:
        if not isinstance(raw_plan, Mapping) or raw_plan.get("tool") not in QUERY_TOOL_NAMES:
            raise QueryPlanRejected("unknown_tool")
        try:
            plan = QueryPlan.model_validate(raw_plan)
        except ValidationError as error:
            raise QueryPlanRejected("invalid_plan") from error
        return self.execute(plan, server_scope)

    def execute(self, plan: QueryPlan, server_scope: QueryScope) -> ToolResult:
        if type(plan) is not QueryPlan:
            raise QueryPlanRejected("invalid_plan")
        if type(server_scope) is not QueryScope:
            raise QueryPlanRejected("invalid_scope")
        raw = self._backend.execute(plan, server_scope)
        supplied_hash = None
        if isinstance(raw, ToolResult):
            if raw.tool != plan.tool or raw.scope != server_scope:
                raise QueryExecutionFailed("backend_authority_mismatch")
            supplied_hash = raw.result_hash
            raw = {
                "facts": tuple(
                    item.model_dump(mode="json") for item in raw.facts
                ),
                "limitations": raw.limitations,
                "action_card_draft": (
                    raw.action_card_draft.model_dump(mode="json")
                    if raw.action_card_draft is not None
                    else None
                ),
            }
        if not isinstance(raw, Mapping):
            raise QueryExecutionFailed("backend_result_invalid")
        facts = tuple(AuthoritativeFact.model_validate(item) for item in raw.get("facts", ()))
        limitations = tuple(
            dict.fromkeys(
                ("sample_data_only",)
                + tuple(str(item) for item in raw.get("limitations", ()))
            )
        )
        if len(facts) > 25 or len(limitations) > 50:
            raise QueryResultTooLarge("query_result_too_large")
        evidence_aliases = {
            reference
            for fact in facts
            for reference in fact.evidence_refs
        }
        if len(evidence_aliases) > 10:
            raise QueryResultTooLarge("query_evidence_aliases_too_large")
        payload = {
            "tool": plan.tool,
            "arguments": plan.arguments.model_dump(mode="json"),
            "scope": server_scope.model_dump(mode="json"),
            "facts": [item.model_dump(mode="json") for item in facts],
            "limitations": limitations,
            "action_card_draft": raw.get("action_card_draft"),
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
        if len(encoded) > 64 * 1024:
            raise QueryResultTooLarge("query_result_too_large")
        result_hash = sha256(encoded).hexdigest()
        if supplied_hash is not None and supplied_hash != result_hash:
            raise QueryExecutionFailed("backend_result_hash_mismatch")
        return ToolResult(
            tool=plan.tool,
            scope=server_scope,
            facts=facts,
            limitations=limitations,
            result_hash=result_hash,
            action_card_draft=raw.get("action_card_draft"),
        )


class PostgresQueryBackend:
    """Registered authority readers; no model string reaches a SQL expression."""

    def __init__(
        self,
        *,
        engine,
        analysis_service,
        forecast_service,
        profit_bridge_service,
        action_service,
    ) -> None:
        self._engine = engine
        self._analyses = analysis_service
        self._forecasts = forecast_service
        self._bridges = profit_bridge_service
        self._actions = action_service
        self._handlers = {
            "metric_lookup": self._metric_lookup,
            "trend_compare": self._trend_compare,
            "sku_rank": self._sku_rank,
            "profit_bridge_explain": self._profit_bridge,
            "inventory_risk_lookup": self._inventory_risk,
            "forecast_lookup": self._forecast,
            "data_quality_lookup": self._data_quality,
            "action_card_lookup": self._action_cards,
            "monthly_sales_report_lookup": self._monthly_sales_report,
        }

    def execute(self, plan: QueryPlan, scope: QueryScope) -> dict[str, object]:
        handler = self._handlers.get(plan.tool)
        if handler is None:
            raise QueryPlanRejected("unknown_tool")
        with self._engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(text("SET LOCAL statement_timeout = '5s'"))
                self._assert_query_controls(connection)
                self._validate_read_scope(connection, scope)
                result = handler(plan, scope, connection)
            except QueryExecutionFailed:
                raise
            except Exception as error:
                raise QueryExecutionFailed("query_authority_unavailable") from error
            finally:
                if transaction.is_active:
                    transaction.rollback()
        return {
            "facts": result.get("facts", ()),
            "limitations": tuple(
                dict.fromkeys(
                    ("sample_data_only",) + tuple(result.get("limitations", ()))
                )
            ),
            "action_card_draft": result.get("action_card_draft"),
        }

    def _assert_query_controls(self, connection: Connection) -> None:
        read_only, timeout = connection.execute(
            text(
                "SELECT current_setting('transaction_read_only'), "
                "current_setting('statement_timeout')"
            )
        ).one()
        if read_only != "on" or timeout not in {"5s", "5000ms"}:
            raise QueryExecutionFailed("query_controls_unavailable")

    def _validate_read_scope(
        self,
        connection: Connection,
        scope: QueryScope,
    ) -> None:
        repository = DatasetRepository(connection)
        version = repository.get_version(scope.dataset_version_id)
        if (
            version is None
            or version.workspace_id != scope.workspace_id
            or not repository.is_release_eligible(version)
        ):
            raise QueryExecutionFailed("query_scope_authority_invalid")

    def _analysis(
        self,
        connection: Connection,
        kind: str,
        scope: QueryScope,
        *,
        previous: bool = False,
    ):
        period_start = scope.period_start
        period_end = scope.period_end
        if previous:
            days = (period_end - period_start).days + 1
            period_end = period_start - timedelta(days=1)
            period_start = period_end - timedelta(days=days - 1)
        analysis_scope = {
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "currency": scope.currency,
            **_identity_scope(scope),
        }
        return self._analyses.read_exact_completed(
            connection,
            kind,
            scope.dataset_version_id,
            analysis_scope,
        )

    def _metric_lookup(
        self,
        plan: QueryPlan,
        scope: QueryScope,
        connection: Connection,
    ):
        metric = plan.arguments.metric
        kind = (
            "operating_profit"
            if metric in {"contribution_profit", "operating_profit"}
            else "sales_ads"
        )
        try:
            run, snapshot, _ = self._analysis(
                connection,
                kind,
                scope,
                previous=plan.arguments.period == "previous",
            )
        except AnalysisNotFound:
            return {
                "facts": (),
                "limitations": (f"{plan.arguments.period}_period_analysis_unavailable",),
            }
        item = snapshot.get("result", {}).get(metric)
        fact = _metric_fact("fact-001", metric, item, run.run_id)
        return {
            "facts": (fact,),
            "limitations": tuple(snapshot.get("limitations", ())),
        }

    def _trend_compare(
        self,
        plan: QueryPlan,
        scope: QueryScope,
        connection: Connection,
    ):
        run, snapshot, _ = self._analysis(connection, "sales_ads", scope)
        result = snapshot.get("result", {})
        if plan.arguments.comparison == "daily_current":
            if plan.arguments.metric not in {"net_sales", "ad_spend"}:
                return {
                    "facts": (),
                    "limitations": tuple(snapshot.get("limitations", ()))
                    + (f"daily_{plan.arguments.metric}_unavailable",),
                }
            key = plan.arguments.metric
            facts, aggregate_limitations = _trend_facts(
                tuple(result.get("daily_trends", ())),
                metric=plan.arguments.metric,
                key=key,
                run_id=run.run_id,
            )
            return {
                "facts": facts,
                "limitations": tuple(snapshot.get("limitations", ()))
                + aggregate_limitations,
            }
        current = result.get(plan.arguments.metric)
        facts = [_metric_fact("fact-001", f"current_{plan.arguments.metric}", current, run.run_id)]
        limitations = list(snapshot.get("limitations", ()))
        try:
            prior_run, prior_snapshot, _ = self._analysis(
                connection,
                "sales_ads",
                scope,
                previous=True,
            )
            prior = prior_snapshot.get("result", {}).get(plan.arguments.metric)
            facts.append(
                _metric_fact(
                    "fact-002",
                    f"previous_{plan.arguments.metric}",
                    prior,
                    prior_run.run_id,
                )
            )
        except AnalysisNotFound:
            limitations.append("previous_period_analysis_unavailable")
        return {"facts": tuple(facts), "limitations": tuple(limitations)}

    def _sku_rank(
        self,
        plan: QueryPlan,
        scope: QueryScope,
        connection: Connection,
    ):
        metric = plan.arguments.metric
        if metric == "contribution_profit":
            self._analysis(connection, "operating_profit", scope)
            return {
                "facts": (),
                "limitations": (
                    "sku_contribution_profit_authority_unavailable_without_"
                    "sku_allocated_costs",
                ),
            }
        if metric in {"replenishment_quantity", "replenishment_cash"}:
            run, snapshot, _ = self._analysis(
                connection,
                "replenishment",
                scope,
            )
            rows = list(snapshot.get("result", {}).get("items", ()))
            values = [
                (
                    row.get("sku_id"),
                    (
                        row.get("recommended_quantity")
                        if metric == "replenishment_quantity"
                        else row.get("cash_required", {}).get("value")
                    ),
                    (
                        row.get("evidence_state", "unknown")
                        if metric == "replenishment_quantity"
                        else row.get("cash_required", {}).get(
                            "evidence_state", "unknown"
                        )
                    ),
                )
                for row in rows
            ]
            values.sort(
                key=lambda item: (_decimal_sort(item[1]), str(item[0])),
                reverse=plan.arguments.direction == "top",
            )
            values = values[: plan.arguments.limit]
            evidence_alias = "replenishment_items"
        elif metric == "inventory_cover":
            run, snapshot, _ = self._analysis(
                connection,
                "inventory_risk",
                scope,
            )
            rows = list(snapshot.get("result", {}).get("items", ()))
            rows.sort(
                key=lambda row: (
                    _decimal_sort(row.get("current_cover_days", {}).get("value")),
                    str(row.get("sku_id")),
                ),
                reverse=plan.arguments.direction == "top",
            )
            values = [
                (
                    row.get("sku_id"),
                    row.get("current_cover_days", {}).get("value"),
                    row.get("current_cover_days", {}).get(
                        "evidence_state", "unknown"
                    ),
                )
                for row in rows[: plan.arguments.limit]
            ]
            evidence_alias = "inventory_items"
        else:
            run, snapshot, _ = self._analysis(connection, "sales_ads", scope)
            rows = list(snapshot.get("result", {}).get("sku_ranking", ()))
            rows.sort(
                key=lambda row: (
                    _decimal_sort(row.get(plan.arguments.metric)),
                    str(row.get("sku_id")),
                ),
                reverse=plan.arguments.direction == "top",
            )
            values = [
                (row.get("sku_id"), row.get(metric), "derived")
                for row in rows[: plan.arguments.limit]
            ]
            evidence_alias = "sku_ranking"
        facts = tuple(
            {
                "fact_ref": f"fact-{index:03d}",
                "label": f"{sku} {metric}",
                "value": _value_text(value),
                "evidence_state": state if value is not None else "unknown",
                "evidence_refs": (f"analysis:{run.run_id}:{evidence_alias}",),
            }
            for index, (sku, value, state) in enumerate(values, start=1)
        )
        return {
            "facts": facts,
            "limitations": tuple(snapshot.get("limitations", ())),
        }

    def _profit_bridge(
        self,
        plan: QueryPlan,
        scope: QueryScope,
        connection: Connection,
    ):
        if scope.actor_kind == "demo" and scope.profit_bridge_id is None:
            return {
                "facts": (),
                "limitations": ("profit_bridge_not_pinned_to_session",),
            }
        bridge = self._bridges.read_for_query(
            connection,
            scope.dataset_version_id,
            scope.profit_bridge_id,
            _identity_scope(scope),
        )
        if plan.arguments.view == "summary":
            values = (
                ("Total profit change", bridge.total_delta_brl, "derived"),
                ("Residual", bridge.residual_brl, "derived"),
            )
        else:
            values = tuple(
                (item.driver, item.amount_brl, item.evidence_state)
                for item in bridge.items
            )
        facts = tuple(
            {
                "fact_ref": f"fact-{index:03d}",
                "label": label,
                "value": _value_text(value),
                "evidence_state": state if value is not None else "unknown",
                "evidence_refs": (f"profit_bridge:{bridge.id}:drivers",),
            }
            for index, (label, value, state) in enumerate(values[:25], start=1)
        )
        return {"facts": facts, "limitations": bridge.limitations}

    def _inventory_risk(
        self,
        plan: QueryPlan,
        scope: QueryScope,
        connection: Connection,
    ):
        if plan.arguments.view == "replenishment":
            run, snapshot, _ = self._analysis(connection, "replenishment", scope)
            rows = tuple(snapshot.get("result", {}).get("items", ()))
            facts = tuple(
                {
                    "fact_ref": f"fact-{index:03d}",
                    "label": f"{row.get('sku_id')} replenishment result",
                    "value": (
                        "quantity="
                        f"{_value_text(row.get('recommended_quantity')) or 'unknown'}; "
                        f"priority={row.get('priority', 'unknown')}; "
                        "latest_order_date="
                        f"{row.get('latest_order_date') or 'unknown'}; "
                        "cash_required_brl="
                        f"{_value_text(row.get('cash_required', {}).get('value')) or 'unknown'}"
                    ),
                    "evidence_state": row.get("evidence_state", "unknown"),
                    "evidence_refs": (
                        f"analysis:{run.run_id}:replenishment_items",
                    ),
                }
                for index, row in enumerate(
                    rows[: plan.arguments.limit],
                    start=1,
                )
            )
            return {
                "facts": facts,
                "limitations": tuple(snapshot.get("limitations", ())),
                "action_card_draft": None,
            }
        run, snapshot, _ = self._analysis(connection, "inventory_risk", scope)
        rows = tuple(snapshot.get("result", {}).get("items", ()))
        if plan.arguments.risk != "all":
            rows = tuple(row for row in rows if row.get("risk") == plan.arguments.risk)
        facts = list(
            {
                "fact_ref": f"fact-{index:03d}",
                "label": f"{row.get('sku_id')} inventory risk",
                "value": (
                    f"{row.get('risk')}; cover={_value_text(row.get('current_cover_days', {}).get('value'))}"
                ),
                "evidence_state": row.get("current_cover_days", {}).get(
                    "evidence_state", "unknown"
                ),
                "evidence_refs": (f"analysis:{run.run_id}:inventory_items",),
            }
            for index, row in enumerate(rows[: plan.arguments.limit], start=1)
        )
        limitations = list(snapshot.get("limitations", ()))
        draft = None
        eligible_rows = [
            row
            for row in rows[: plan.arguments.limit]
            if row.get("risk") == "stockout"
            and row.get("current_cover_days", {}).get("value") is not None
        ]
        if len(eligible_rows) == 1:
            target = eligible_rows[0]
            try:
                replenishment_run, replenishment, _ = self._analysis(
                    connection,
                    "replenishment", scope
                )
                replenishment_item = next(
                    (
                        item
                        for item in replenishment.get("result", {}).get("items", ())
                        if item.get("sku_id") == target.get("sku_id")
                    ),
                    None,
                )
                quantity = (
                    replenishment_item.get("recommended_quantity")
                    if replenishment_item is not None
                    else None
                )
                if quantity is not None:
                    quantity_ref = f"fact-{len(facts) + 1:03d}"
                    facts.append(
                        {
                            "fact_ref": quantity_ref,
                            "label": f"{target.get('sku_id')} recommended quantity",
                            "value": str(quantity),
                            "evidence_state": replenishment_item.get(
                                "evidence_state", "unknown"
                            ),
                            "evidence_refs": (
                                f"analysis:{replenishment_run.run_id}:"
                                f"replenishment:{target.get('sku_id')}",
                            ),
                        }
                    )
                    risk_ref = next(
                        fact["fact_ref"]
                        for fact in facts
                        if fact["label"]
                        == f"{target.get('sku_id')} inventory risk"
                    )
                    limitations.extend(replenishment.get("limitations", ()))
                    draft = {
                        "suggestion": (
                            f"Review replenishment for {target.get('sku_id')} "
                            "using the deterministic stockout signal"
                        ),
                        "target": target.get("sku_id"),
                        "quantity": str(quantity),
                        "budget_brl": None,
                        "expected_impact": {
                            "inventory_risk": str(target.get("risk")),
                            "current_cover_days": _value_text(
                                target.get("current_cover_days", {}).get("value")
                            )
                            or "unknown",
                        },
                        "confidence": "medium",
                        "limitations": tuple(
                            dict.fromkeys(
                                ("sample_data_only",) + tuple(limitations)
                            )
                        ),
                        "fact_refs": (risk_ref, quantity_ref),
                    }
            except AnalysisNotFound:
                limitations.append("replenishment_action_authority_unavailable")
        return {
            "facts": tuple(facts),
            "limitations": tuple(limitations),
            "action_card_draft": draft,
        }

    def _forecast(
        self,
        plan: QueryPlan,
        scope: QueryScope,
        connection: Connection,
    ):
        if scope.actor_kind == "demo" and scope.forecast_id is None:
            return {
                "facts": (),
                "limitations": ("forecast_not_pinned_to_session",),
            }
        forecast = self._forecasts.read_completed(
            connection,
            scope.dataset_version_id,
            scope.forecast_id,
            _identity_scope(scope),
        )
        values: list[tuple[str, object, str]] = []
        if plan.arguments.view == "inputs":
            candidate = forecast.input_snapshot.get("candidate", {})
            if not isinstance(candidate, Mapping):
                raise QueryExecutionFailed("forecast_input_authority_invalid")
            values = [
                ("Candidate product", candidate.get("product_name"), "assumed"),
                ("Candidate category", candidate.get("category"), "assumed"),
                (
                    "Candidate attributes",
                    ", ".join(str(item) for item in candidate.get("attributes", ())),
                    "assumed",
                ),
                ("Planned launch date", candidate.get("planned_launch_date"), "assumed"),
                ("Planned price BRL", candidate.get("planned_price_brl"), "assumed"),
                (
                    "Expected discount BRL",
                    candidate.get("expected_discount_brl"),
                    "assumed",
                ),
                ("Unit cost BRL", candidate.get("unit_cost_brl"), "assumed"),
                (
                    "Opening inventory units",
                    candidate.get("opening_inventory_units"),
                    "assumed",
                ),
                ("MOQ units", candidate.get("moq_units"), "assumed"),
                ("Lead time days", candidate.get("lead_time_days"), "assumed"),
                (
                    "Planned daily advertising BRL",
                    candidate.get("planned_daily_ad_brl"),
                    "assumed",
                ),
                (
                    "Safety stock units",
                    forecast.input_snapshot.get("safety_stock_units"),
                    "assumed",
                ),
            ]
        elif plan.arguments.view == "analogs":
            values = [
                (f"Analog {item.sku_id}", item.score, "derived")
                for item in forecast.analogs
                if item.confirmed
            ]
        elif plan.arguments.view == "limitations":
            values = [
                (f"Limitation {index}", item, "assumed")
                for index, item in enumerate(forecast.result.get("limitations", ()), start=1)
            ] if forecast.result else []
        else:
            horizons = forecast.result.get("horizons", ()) if forecast.result else ()
            for horizon in horizons:
                if int(horizon.get("horizon_days", 0)) != plan.arguments.horizon_days:
                    continue
                for scenario in ("low", "base", "high"):
                    item = horizon.get(scenario, {})
                    values.append(
                        (f"{plan.arguments.horizon_days}d {scenario} units", item.get("units"), "derived")
                    )
        facts = tuple(
            {
                "fact_ref": f"fact-{index:03d}",
                "label": label,
                "value": _value_text(value),
                "evidence_state": state if value is not None else "unknown",
                "evidence_refs": (
                    f"forecast:{forecast.id}:"
                    f"{'inputs' if plan.arguments.view == 'inputs' else 'result'}",
                ),
            }
            for index, (label, value, state) in enumerate(values[:25], start=1)
        )
        limitations = tuple(forecast.result.get("limitations", ())) if forecast.result else ("forecast_result_unavailable",)
        return {"facts": facts, "limitations": limitations}

    def _data_quality(
        self,
        plan: QueryPlan,
        scope: QueryScope,
        connection: Connection,
    ):
        repository = DatasetRepository(connection)
        version = repository.get_version(scope.dataset_version_id)
        artifacts = repository.list_artifacts(scope.dataset_version_id)
        if version is None:
            raise QueryExecutionFailed("dataset_version_not_found")
        limitations: tuple[str, ...] = ()
        if plan.arguments.section == "coverage":
            values = (
                ("Schema version", version.schema_version, "measured"),
                ("Artifact count", len(artifacts), "measured"),
                ("Source classification", "pure_synthetic", "measured"),
            )
        elif plan.arguments.section == "limitations":
            values = (
                (
                    "Release eligibility",
                    str(repository.is_release_eligible(version)).lower(),
                    "derived",
                ),
                ("Real-market evidence", "unavailable", "unknown"),
                ("External platform execution", "unavailable", "unknown"),
            )
            limitations = (
                "real_market_data_unavailable",
                "external_platform_execution_unavailable",
            )
        elif plan.arguments.section == "evidence":
            values = (
                ("Dataset content digest", version.content_sha256, "measured"),
                (
                    "Registered artifact kinds",
                    ", ".join(sorted({item.artifact_kind for item in artifacts})),
                    "measured",
                ),
                ("Registered artifact count", len(artifacts), "measured"),
            )
        elif plan.arguments.section == "missing":
            missing_values: list[tuple[str, object, str]] = []
            missing_limitations: list[str] = []
            for kind in (
                "sales_ads",
                "inventory_risk",
                "fifo_cost_aging",
                "replenishment",
                "operating_profit",
            ):
                try:
                    run, snapshot, _ = self._analysis(connection, kind, scope)
                except AnalysisNotFound:
                    missing_values.append((f"{kind} missing state", "analysis unavailable", "unknown"))
                    missing_limitations.append(f"analysis_missing:{kind}")
                    continue
                relevant = tuple(
                    str(item)
                    for item in snapshot.get("limitations", ())
                    if any(
                        token in str(item)
                        for token in ("missing", "unavailable", "unknown", "insufficient")
                    )
                )
                missing_values.append(
                    (
                        f"{kind} missing state",
                        ", ".join(relevant) if relevant else "none declared",
                        "unknown" if relevant else "derived",
                    )
                )
                if relevant:
                    missing_limitations.extend(relevant)
            values = tuple(missing_values)
            limitations = tuple(dict.fromkeys(missing_limitations))
        else:
            if version.source_workflow_id is None:
                values = (
                    ("Mapping mode", "not applicable to declared synthetic seed", "measured"),
                    ("Canonical schema", version.schema_version, "measured"),
                    ("Mapped upload count", 0, "measured"),
                )
            else:
                rows = connection.execute(
                    select(
                        upload_records.c.status,
                        upload_records.c.source_role,
                        upload_records.c.mapping,
                        upload_records.c.mapping_revision,
                        upload_records.c.quality_report,
                    ).where(upload_records.c.workflow_id == version.source_workflow_id)
                ).mappings().all()
                accepted = tuple(row for row in rows if row["status"] == "accepted")
                mapped = tuple(
                    row
                    for row in accepted
                    if isinstance(row["mapping"], Mapping) and row["mapping"]
                )
                missing_fields = sum(
                    len(row["quality_report"].get("missing_required_fields", ()))
                    for row in accepted
                    if isinstance(row["quality_report"], Mapping)
                )
                values = (
                    ("Accepted upload count", len(accepted), "measured"),
                    ("Mapped upload count", len(mapped), "measured"),
                    (
                        "Mapped source roles",
                        ", ".join(
                            sorted(
                                {
                                    str(row["source_role"])
                                    for row in mapped
                                    if row["source_role"] is not None
                                }
                            )
                        )
                        or "none",
                        "measured",
                    ),
                    ("Missing required mapped fields", missing_fields, "measured"),
                )
        facts = tuple(
            {
                "fact_ref": f"fact-{index:03d}",
                "label": label,
                "value": str(value),
                "evidence_state": state,
                "evidence_refs": (f"dataset_version:{version.id}:quality",),
            }
            for index, (label, value, state) in enumerate(values, start=1)
        )
        return {"facts": facts, "limitations": limitations}

    def _action_cards(
        self,
        plan: QueryPlan,
        scope: QueryScope,
        connection: Connection,
    ):
        if scope.actor_kind == "demo":
            if scope.session_created_at is None:
                raise QueryExecutionFailed("demo_session_scope_incomplete")
            cards = self._actions.read_for_query(
                connection,
                scope.dataset_version_id,
                scope.session_created_at,
                _identity_scope(scope),
            )
        else:
            cards = self._actions.read_for_query(
                connection,
                scope.dataset_version_id,
                scope=_identity_scope(scope),
            )
        if plan.arguments.status != "all":
            cards = tuple(card for card in cards if card.status == plan.arguments.status)
        cards = cards[: plan.arguments.limit]
        if len(cards) > 10:
            return {
                "facts": (),
                "limitations": ("action_card_result_too_large_narrow_status",),
            }
        facts = tuple(
            _action_fact(index, card, plan.arguments.view)
            for index, card in enumerate(cards, start=1)
        )
        return {"facts": facts, "limitations": ()}

    def _monthly_sales_report(
        self,
        plan: QueryPlan,
        scope: QueryScope,
        connection: Connection,
    ):
        del plan
        report = read_monthly_sales_report(
            connection,
            scope,
            PrecomputedMonthlyReportReaders(self._analyses, self._actions),
        )
        return {
            "facts": report.facts,
            "limitations": report.limitations,
        }


def _identity_scope(scope: QueryScope) -> dict[str, object]:
    return {
        "currency": scope.currency,
        **(
            {"store_id": scope.store_ids[0]}
            if len(scope.store_ids) == 1
            else {}
        ),
    }


def _metric_fact(ref: str, label: str, item: object, run_id) -> dict[str, object]:
    value = item.get("value") if isinstance(item, Mapping) else None
    state = item.get("evidence_state", "unknown") if isinstance(item, Mapping) else "unknown"
    aliases = item.get("evidence_refs", ()) if isinstance(item, Mapping) else ()
    return {
        "fact_ref": ref,
        "label": label,
        "value": _value_text(value),
        "evidence_state": state if value is not None else "unknown",
        "evidence_refs": tuple(
            f"analysis:{run_id}:{alias}" for alias in aliases
        ) or (f"analysis:{run_id}:{label}",),
    }


def _action_fact(index: int, card, view: str) -> dict[str, object]:
    revision = card.revisions[-1]
    label = f"{revision.target} action {view}"
    source_ref = f"action:{card.id}:revision:{card.current_revision}"
    if view == "summary":
        value: object = {
            "status": card.status,
            "current_revision": card.current_revision,
        }
    elif view == "revisions":
        value = {
            "current_revision": card.current_revision,
            "suggestion": revision.suggestion,
            "target": revision.target,
            "quantity": str(revision.quantity) if revision.quantity is not None else None,
            "budget_brl": (
                str(revision.budget_brl) if revision.budget_brl is not None else None
            ),
            "confidence": revision.confidence,
        }
    elif view == "decisions":
        item = card.decisions[-1] if card.decisions else None
        value = (
            {
                "command": item.command,
                "action_revision": item.action_revision,
                "reason": item.reason,
            }
            if item is not None
            else "not_recorded"
        )
        if item is not None:
            source_ref = f"action:{card.id}:decision:{item.id}"
    elif view == "exports":
        item = card.exports[-1] if card.exports else None
        value = (
            {"status": item.status, "format": item.format, "note": item.note}
            if item is not None
            else "not_recorded"
        )
        if item is not None:
            source_ref = f"action:{card.id}:export:{item.id}"
    else:
        item = card.outcomes[-1] if card.outcomes else None
        value = (
            {
                "conclusion": item.conclusion,
                "review_date": item.review_date.isoformat(),
                "outcome_revision": item.outcome_revision,
            }
            if item is not None
            else "not_recorded"
        )
        if item is not None:
            source_ref = f"action:{card.id}:outcome:{item.id}"
    return {
        "fact_ref": f"fact-{index:03d}",
        "label": label,
        "value": _value_text(value),
        "evidence_state": "measured",
        "evidence_refs": (source_ref,),
    }


def _value_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def _decimal_sort(value: object) -> float:
    if value is None:
        return float("-inf")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")


def _trend_facts(
    rows: tuple[Mapping[str, object], ...],
    *,
    metric: str,
    key: str,
    run_id,
) -> tuple[tuple[dict[str, object], ...], tuple[str, ...]]:
    if not rows:
        return (), ()
    bucket_size = max(1, (len(rows) + 24) // 25)
    buckets = tuple(
        rows[index : index + bucket_size]
        for index in range(0, len(rows), bucket_size)
    )
    facts: list[dict[str, object]] = []
    for index, bucket in enumerate(buckets, start=1):
        values = tuple(row.get(key) for row in bucket)
        value = _sum_decimal_values(values)
        first_date = str(bucket[0].get("date"))
        last_date = str(bucket[-1].get("date"))
        label_date = first_date if first_date == last_date else f"{first_date} to {last_date}"
        facts.append(
            {
                "fact_ref": f"fact-{index:03d}",
                "label": f"{metric} {label_date}",
                "value": _value_text(value),
                "evidence_state": "unknown" if value is None else "derived",
                "evidence_refs": (f"analysis:{run_id}:daily_trends",),
            }
        )
    limitations = (
        ("daily_trend_aggregated_to_bounded_period_buckets",)
        if bucket_size > 1
        else ()
    )
    return tuple(facts), limitations


def _sum_decimal_values(values: tuple[object, ...]) -> Decimal | None:
    if any(value is None for value in values):
        return None
    try:
        return sum((Decimal(str(value)) for value in values), Decimal(0))
    except (InvalidOperation, ValueError):
        return None
