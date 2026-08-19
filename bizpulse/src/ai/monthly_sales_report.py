"""Bounded monthly report projection from immutable completed snapshots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from src.services.analysis_service import AnalysisNotFound


@dataclass(frozen=True, slots=True)
class MonthlySalesReport:
    facts: tuple[dict[str, object], ...]
    limitations: tuple[str, ...]


class PrecomputedMonthlyReportReaders:
    """Adapters for the existing services; every read stays in the caller transaction."""

    def __init__(self, analysis_service, action_service) -> None:
        self._analyses = analysis_service
        self._actions = action_service

    def completed_analysis(
        self,
        connection,
        kind: str,
        scope,
        *,
        previous: bool = False,
    ):
        period_start = scope.period_start
        period_end = scope.period_end
        if previous:
            period_end = period_start - timedelta(days=1)
            period_start = period_end.replace(day=1)
        analysis_scope = {
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "currency": scope.currency,
            **(
                {"store_id": scope.store_ids[0]}
                if len(scope.store_ids) == 1
                else {}
            ),
        }
        try:
            run, snapshot, _ = self._analyses.read_exact_completed(
                connection,
                kind,
                scope.dataset_version_id,
                analysis_scope,
            )
        except AnalysisNotFound:
            return None
        return run, snapshot

    def pinned_actions(self, connection, scope):
        if scope.actor_kind == "demo":
            if scope.session_created_at is None:
                return ()
            return self._actions.read_for_query(
                connection,
                scope.dataset_version_id,
                scope.session_created_at,
                {
                    "currency": scope.currency,
                    **(
                        {"store_id": scope.store_ids[0]}
                        if len(scope.store_ids) == 1
                        else {}
                    ),
                },
            )
        return self._actions.read_for_query(
            connection,
            scope.dataset_version_id,
            scope={
                "currency": scope.currency,
                **(
                    {"store_id": scope.store_ids[0]}
                    if len(scope.store_ids) == 1
                    else {}
                ),
            },
        )


def read_monthly_sales_report(connection, scope, readers) -> MonthlySalesReport:
    """Compose one report without imports, jobs, raw scans, or clock-derived periods."""

    snapshots = {
        "current_sales": readers.completed_analysis(
            connection,
            "sales_ads",
            scope,
            previous=False,
        ),
        "previous_sales": readers.completed_analysis(
            connection,
            "sales_ads",
            scope,
            previous=True,
        ),
        "operating_profit": readers.completed_analysis(
            connection,
            "operating_profit",
            scope,
            previous=False,
        ),
        "inventory_risk": readers.completed_analysis(
            connection,
            "inventory_risk",
            scope,
            previous=False,
        ),
        "replenishment": readers.completed_analysis(
            connection,
            "replenishment",
            scope,
            previous=False,
        ),
    }
    actions = tuple(readers.pinned_actions(connection, scope) or ())
    facts: list[dict[str, object]] = []
    limitations: list[str] = []
    release_ref = f"dataset_version:{scope.dataset_version_id}:monthly_report"

    def add(
        label: str,
        value: object,
        state: str,
        evidence_refs: Sequence[str],
    ) -> None:
        facts.append(
            {
                "fact_ref": f"fact-{len(facts) + 1:03d}",
                "label": label,
                "value": None if value is None else str(value),
                "evidence_state": state if value is not None else "unknown",
                "evidence_refs": tuple(evidence_refs),
            }
        )

    add(
        "report_period",
        f"{scope.period_start.isoformat()}..{scope.period_end.isoformat()}",
        "measured",
        (release_ref,),
    )
    add("currency", scope.currency, "measured", (release_ref,))

    current = _snapshot(snapshots["current_sales"])
    previous = _snapshot(snapshots["previous_sales"])
    current_ref = _analysis_ref(snapshots["current_sales"], "sales_ads")
    previous_ref = _analysis_ref(snapshots["previous_sales"], "sales_ads_prior")
    if current is None:
        limitations.append("monthly_report_current_sales_unavailable")
    else:
        result = _result(current)
        for name in ("net_sales", "orders", "units", "aov", "ad_spend", "roas"):
            item = result.get(name)
            add(
                f"{name}_brl" if name in {"net_sales", "aov", "ad_spend"} else name,
                _metric_value(item),
                _metric_state(item),
                (current_ref,),
            )
        rankings = tuple(
            row
            for row in result.get("sku_ranking", ())
            if isinstance(row, Mapping)
        )
        ranked = sorted(
            rankings,
            key=lambda row: (_decimal(row.get("net_sales")), str(row.get("sku_id"))),
            reverse=True,
        )
        if ranked:
            add("top_sku", _sku_value(ranked[0]), "derived", (current_ref,))
            add("bottom_sku", _sku_value(ranked[-1]), "derived", (current_ref,))
        limitations.extend(_limitations(current))

    if previous is None:
        limitations.append("monthly_report_previous_sales_unavailable")
    else:
        prior_result = _result(previous)
        for name in ("net_sales", "orders", "units"):
            item = prior_result.get(name)
            add(
                f"previous_{name}_brl" if name == "net_sales" else f"previous_{name}",
                _metric_value(item),
                _metric_state(item),
                (previous_ref,),
            )
        limitations.extend(_limitations(previous))

    if current is not None and previous is not None:
        current_sales = _decimal_or_none(_metric_value(_result(current).get("net_sales")))
        prior_sales = _decimal_or_none(_metric_value(_result(previous).get("net_sales")))
        if current_sales is not None and prior_sales is not None:
            add(
                "net_sales_change_brl",
                f"{current_sales - prior_sales:.2f}",
                "derived",
                (current_ref, previous_ref),
            )

    profit = _snapshot(snapshots["operating_profit"])
    if profit is None:
        limitations.append("monthly_report_operating_profit_unavailable")
    else:
        profit_ref = _analysis_ref(snapshots["operating_profit"], "operating_profit")
        for name in ("contribution_profit", "operating_profit"):
            item = _result(profit).get(name)
            add(f"{name}_brl", _metric_value(item), _metric_state(item), (profit_ref,))
        limitations.extend(_limitations(profit))

    inventory = _snapshot(snapshots["inventory_risk"])
    if inventory is None:
        limitations.append("monthly_report_inventory_risk_unavailable")
    else:
        inventory_ref = _analysis_ref(snapshots["inventory_risk"], "inventory_risk")
        items = tuple(
            row for row in _result(inventory).get("items", ()) if isinstance(row, Mapping)
        )
        add(
            "stockout_risk_skus",
            sum(row.get("risk") == "stockout" for row in items),
            "derived",
            (inventory_ref,),
        )
        add(
            "overstock_risk_skus",
            sum(row.get("risk") == "overstock" for row in items),
            "derived",
            (inventory_ref,),
        )
        limitations.extend(_limitations(inventory))

    replenishment = _snapshot(snapshots["replenishment"])
    if replenishment is None:
        limitations.append("monthly_report_replenishment_unavailable")
    else:
        replenishment_ref = _analysis_ref(
            snapshots["replenishment"],
            "replenishment",
        )
        items = tuple(
            row
            for row in _result(replenishment).get("items", ())
            if isinstance(row, Mapping)
        )
        if items:
            add(
                "highest_priority_replenishment",
                _replenishment_value(items[0]),
                "derived",
                (replenishment_ref,),
            )
        limitations.extend(_limitations(replenishment))

    add(
        "pinned_action_count",
        len(actions),
        "measured",
        ("action:monthly_report",),
    )
    add(
        "approved_action_count",
        sum(getattr(action, "status", None) == "approved" for action in actions),
        "measured",
        ("action:monthly_report",),
    )
    return MonthlySalesReport(
        facts=tuple(facts[:25]),
        limitations=tuple(dict.fromkeys(limitations))[:50],
    )


def _snapshot(value):
    if not isinstance(value, tuple) or len(value) != 2:
        return None
    return value[1] if isinstance(value[1], Mapping) else None


def _analysis_ref(value, fallback: str) -> str:
    run = value[0] if isinstance(value, tuple) and value else None
    return f"analysis:{getattr(run, 'run_id', fallback)}:monthly_report"


def _result(snapshot: Mapping[str, object]) -> Mapping[str, object]:
    value = snapshot.get("result")
    return value if isinstance(value, Mapping) else {}


def _limitations(snapshot: Mapping[str, object]) -> tuple[str, ...]:
    value = snapshot.get("limitations", ())
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item) for item in value)


def _metric_value(item: object) -> object:
    return item.get("value") if isinstance(item, Mapping) else None


def _metric_state(item: object) -> str:
    value = item.get("evidence_state", "unknown") if isinstance(item, Mapping) else "unknown"
    return str(value) if value in {"measured", "derived", "assumed", "unknown"} else "unknown"


def _decimal(value: object) -> Decimal:
    result = _decimal_or_none(value)
    return result if result is not None else Decimal("-Infinity")


def _decimal_or_none(value: object) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _sku_value(row: Mapping[str, object]) -> str:
    return f"{row.get('sku_id')}; net_sales_brl={row.get('net_sales')}"


def _replenishment_value(row: Mapping[str, object]) -> str:
    cash = row.get("cash_required")
    cash_value = cash.get("value") if isinstance(cash, Mapping) else None
    return (
        f"{row.get('sku_id')}; priority={row.get('priority')}; "
        f"quantity={row.get('recommended_quantity')}; cash_required_brl={cash_value}"
    )
