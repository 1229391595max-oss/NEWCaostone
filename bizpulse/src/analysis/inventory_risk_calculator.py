"""Deterministic inventory-cover and stock-risk calculation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN

from src.analysis.evidence import Evidence, Metric, nonnegative_decimal, ratio, stable_hash

ALGORITHM_VERSION = "inventory_risk.v1"


@dataclass(frozen=True, slots=True)
class InventoryRiskItem:
    sku_id: str
    on_hand_units: int
    inbound_units: int
    daily_velocity: Decimal | None
    current_cover_days: Metric
    projected_cover_days: Metric
    risk: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InventoryRiskResult:
    algorithm_version: str
    as_of: date
    items: tuple[InventoryRiskItem, ...]
    evidence: tuple[Evidence, ...]
    limitations: tuple[str, ...]
    snapshot_hash: str


def calculate_inventory_risk(
    *,
    sales: Sequence[Mapping[str, object]],
    inventory: Sequence[Mapping[str, object]],
    as_of: date,
    period_start: date | None = None,
) -> InventoryRiskResult:
    if not isinstance(as_of, date):
        raise ValueError("as_of_invalid")
    if period_start is not None and (
        not isinstance(period_start, date) or period_start > as_of
    ):
        raise ValueError("period_start_invalid")
    inventory_candidates: dict[str, list[tuple[date, Mapping[str, object]]]] = defaultdict(list)
    limitations: list[str] = []
    for row in inventory:
        sku = _text(row.get("sku_id"), "sku_id")
        snapshot_date = _date_value(row.get("date"), "date")
        if snapshot_date > as_of:
            limitations.append(f"future_inventory_excluded:{sku}:{snapshot_date}")
            continue
        inventory_candidates[sku].append((snapshot_date, row))
    inventory_by_sku: dict[str, Mapping[str, object]] = {}
    for sku, candidates in inventory_candidates.items():
        candidates.sort(key=lambda item: item[0], reverse=True)
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            raise ValueError(f"duplicate_inventory:{sku}:{candidates[0][0]}")
        inventory_by_sku[sku] = candidates[0][1]

    units_by_sku: dict[str, Decimal] = defaultdict(Decimal)
    dates_by_sku: dict[str, set[str]] = defaultdict(set)
    evidence: list[Evidence] = []
    if not inventory_by_sku:
        limitations.append("inventory_missing")
        evidence.append(
            Evidence(
                "inventory.source",
                "unknown",
                "exact-SKU inventory source required",
                ("product_inventory_sales",),
            )
        )
    for row in sales:
        sku = _text(row.get("sku_id"), "sku_id")
        sale_date = _date_value(row.get("date"), "date")
        if sale_date > as_of or (period_start is not None and sale_date < period_start):
            limitations.append(f"sales_outside_period_excluded:{sku}:{sale_date}")
            continue
        units_by_sku[sku] += nonnegative_decimal(row.get("units"), "units")
        dates_by_sku[sku].add(sale_date.isoformat())
    for sku in sorted(set(units_by_sku) - set(inventory_by_sku)):
        limitations.append(f"sales_without_inventory:{sku}")

    items: list[InventoryRiskItem] = []
    for sku, row in sorted(inventory_by_sku.items()):
        on_hand = _whole(nonnegative_decimal(row.get("on_hand_units"), "on_hand_units"), "on_hand_units")
        inbound = _whole(nonnegative_decimal(row.get("inbound_units", 0), "inbound_units"), "inbound_units")
        evidence_alias = f"inventory:{sku}"
        velocity_alias = f"velocity:{sku}"
        evidence.append(Evidence(evidence_alias, "measured", "latest exact-SKU inventory row", ("product_inventory_sales",)))
        sku_dates = dates_by_sku.get(sku, ())
        coverage_start = period_start or (
            min(date.fromisoformat(item) for item in sku_dates) if sku_dates else None
        )
        days = (as_of - coverage_start).days + 1 if coverage_start is not None else 0
        coverage_complete = period_start is not None or len(sku_dates) == days
        if not days or not coverage_complete or units_by_sku[sku] == 0:
            limitations.append(f"velocity_missing:{sku}")
            if days and not coverage_complete:
                limitations.append(f"sales_coverage_incomplete:{sku}")
            unknown = Metric(None, "unknown", (evidence_alias,))
            items.append(
                InventoryRiskItem(sku, on_hand, inbound, None, unknown, unknown, "unknown", (evidence_alias,))
            )
            continue
        velocity = ratio(units_by_sku[sku] / days)
        current = _days(Decimal(on_hand) / velocity)
        projected = _days(Decimal(on_hand + inbound) / velocity)
        risk = "stockout" if current < Decimal(7) else "overstock" if current > Decimal(90) else "balanced"
        evidence.append(Evidence(velocity_alias, "derived", "sum(exact_sku_units)/covered_days", ("daily_sales",)))
        refs = (evidence_alias, velocity_alias)
        items.append(
            InventoryRiskItem(
                sku,
                on_hand,
                inbound,
                velocity,
                Metric(current, "derived", refs),
                Metric(projected, "derived", refs),
                risk,
                refs,
            )
        )
    payload = {
        "algorithm_version": ALGORITHM_VERSION,
        "as_of": as_of,
        "items": tuple(items),
        "limitations": tuple(limitations),
    }
    return InventoryRiskResult(ALGORITHM_VERSION, as_of, tuple(items), tuple(evidence), tuple(limitations), stable_hash(payload))


def _days(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _whole(value: Decimal, field: str) -> int:
    if value != value.to_integral_value():
        raise ValueError(f"{field}_not_integer")
    return int(value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}_invalid")
    return value.strip()


def _date_value(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field}_invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field}_invalid") from error
