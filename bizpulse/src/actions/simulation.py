"""Read-only inputs for the bounded Viewer Action Sandbox."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN

from src.actions.contracts import ActionSimulationInputs

MONEY_QUANTUM = Decimal("0.01")


def _nonnegative(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite() or result < 0:
        return None
    return result


def _positive(value: object) -> Decimal | None:
    result = _nonnegative(value)
    return result if result is not None and result > 0 else None


def _matching_item(
    target: object,
    completed_replenishment_snapshot: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    if not isinstance(target, str) or not isinstance(
        completed_replenishment_snapshot, Mapping
    ):
        return None
    result = completed_replenishment_snapshot.get("result")
    items = result.get("items") if isinstance(result, Mapping) else None
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return None
    matching = tuple(
        item
        for item in items
        if isinstance(item, Mapping) and item.get("sku_id") == target
    )
    return matching[0] if len(matching) == 1 else None


def _unit_cost(item: Mapping[str, object] | None) -> Decimal | None:
    if item is None:
        return None
    direct = _nonnegative(item.get("unit_cost_brl"))
    if direct is not None:
        return direct.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
    cash_required = item.get("cash_required")
    cash = _nonnegative(
        cash_required.get("value") if isinstance(cash_required, Mapping) else None
    )
    quantity = _positive(item.get("recommended_quantity"))
    if cash is None or quantity is None:
        return None
    return (cash / quantity).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)


def project_simulation_inputs(
    action_revision,
    completed_replenishment_snapshot: Mapping[str, object] | None,
) -> ActionSimulationInputs:
    """Project only named numeric fields from one completed replenishment snapshot."""

    item = _matching_item(
        getattr(action_revision, "target", None),
        completed_replenishment_snapshot,
    )
    velocity = _positive(
        item.get("precomputed_daily_velocity", item.get("base_daily"))
        if item is not None
        else None
    )
    baseline = _nonnegative(getattr(action_revision, "budget_brl", None))
    return ActionSimulationInputs(
        unit_cost_brl=_unit_cost(item),
        precomputed_daily_velocity=velocity,
        baseline_budget_brl=(
            baseline.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
            if baseline is not None
            else None
        ),
    )
