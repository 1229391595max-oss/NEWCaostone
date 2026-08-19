"""Deterministic existing-SKU replenishment bands and order guidance."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from src.analysis.evidence import Evidence, Metric, money, nonnegative_decimal, ratio, stable_hash

ALGORITHM_VERSION = "replenishment.v1"


@dataclass(frozen=True, slots=True)
class ReplenishmentItem:
    sku_id: str
    low_daily: Decimal | None
    base_daily: Decimal | None
    high_daily: Decimal | None
    recommended_quantity: int | None
    latest_order_date: date | None
    priority: str
    cash_required: Metric
    evidence_state: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplenishmentResult:
    algorithm_version: str
    as_of: date
    items: tuple[ReplenishmentItem, ...]
    evidence: tuple[Evidence, ...]
    limitations: tuple[str, ...]
    snapshot_hash: str


def calculate_replenishment(
    *,
    sales: Sequence[Mapping[str, object]],
    inventory: Sequence[Mapping[str, object]],
    policies: Sequence[Mapping[str, object]],
    as_of: date,
    period_start: date | None = None,
) -> ReplenishmentResult:
    if not isinstance(as_of, date):
        raise ValueError("as_of_invalid")
    if period_start is not None and (
        not isinstance(period_start, date) or period_start > as_of
    ):
        raise ValueError("period_start_invalid")
    units: dict[str, Decimal] = defaultdict(Decimal)
    days: dict[str, set[str]] = defaultdict(set)
    for row in sales:
        sku = _text(row.get("sku_id"), "sku_id")
        sale_date = _date_value(row.get("date"), "date")
        if sale_date > as_of or (period_start is not None and sale_date < period_start):
            continue
        units[sku] += nonnegative_decimal(row.get("units"), "units")
        days[sku].add(sale_date.isoformat())
    limitations: list[str] = []
    inventory_by_sku = _latest_inventory_by_sku(inventory, as_of, limitations)
    policy_by_sku = _unique_by_sku(policies, "policy")
    evidence: list[Evidence] = []
    items: list[ReplenishmentItem] = []
    if not inventory_by_sku:
        limitations.append("inventory_missing")
        evidence.append(
            Evidence(
                "replenishment.inventory",
                "unknown",
                "exact-SKU inventory source required",
                ("product_inventory_sales",),
            )
        )
    for sku, inventory_row in sorted(inventory_by_sku.items()):
        policy = policy_by_sku.get(sku)
        if policy is None:
            limitations.append(f"policy_missing:{sku}")
            evidence.append(
                Evidence(
                    f"replenishment:{sku}",
                    "unknown",
                    "exact-SKU replenishment policy required",
                    ("replenishment_policy",),
                )
            )
            items.append(_unknown_item(sku))
            continue
        sku_dates = days.get(sku, ())
        coverage_start = period_start or (
            min(date.fromisoformat(item) for item in sku_dates) if sku_dates else None
        )
        history_days = (
            (as_of - coverage_start).days + 1 if coverage_start is not None else 0
        )
        coverage_complete = period_start is not None or len(sku_dates) == history_days
        if not history_days or units[sku] == 0:
            limitations.append(f"demand_history_missing:{sku}")
            evidence.append(
                Evidence(
                    f"replenishment:{sku}",
                    "unknown",
                    "no exact-SKU demand history",
                    ("daily_sales",),
                )
            )
            items.append(_unknown_item(sku))
            continue
        if not coverage_complete:
            limitations.append(
                f"demand_history_insufficient:{sku}:{len(sku_dates)}"
            )
            evidence.append(
                Evidence(
                    f"replenishment:{sku}",
                    "unknown",
                    "daily coverage is incomplete and no explicit period_start was supplied",
                    ("daily_sales",),
                )
            )
            items.append(_unknown_item(sku))
            continue
        if history_days < 7:
            limitations.append(f"demand_history_insufficient:{sku}:{history_days}")
            evidence.append(
                Evidence(
                    f"replenishment:{sku}",
                    "unknown",
                    "at least 7 covered days required",
                    ("daily_sales",),
                )
            )
            items.append(_unknown_item(sku))
            continue
        base = ratio(units[sku] / history_days)
        low = ratio(base * Decimal("0.80"))
        high = ratio(base * Decimal("1.20"))
        on_hand = _whole(nonnegative_decimal(inventory_row.get("on_hand_units"), "on_hand_units"), "on_hand_units")
        inbound = _whole(nonnegative_decimal(inventory_row.get("inbound_units", 0), "inbound_units"), "inbound_units")
        available_inbound = 0
        if inbound:
            limitations.append(f"inbound_availability_unknown:{sku}")
        lead = _whole(nonnegative_decimal(policy.get("lead_time_days"), "lead_time_days"), "lead_time_days")
        safety = _whole(nonnegative_decimal(policy.get("safety_stock_units"), "safety_stock_units"), "safety_stock_units")
        reorder_point = _whole(
            nonnegative_decimal(
                policy.get("reorder_point_units"),
                "reorder_point_units",
            ),
            "reorder_point_units",
        )
        target_cover = _whole(nonnegative_decimal(policy.get("target_cover_days"), "target_cover_days"), "target_cover_days")
        target_units = max(
            high * target_cover + safety,
            Decimal(reorder_point),
        )
        quantity = max(
            0,
            int(
                (
                    target_units
                    - on_hand
                    - available_inbound
                ).to_integral_value(rounding=ROUND_CEILING)
            ),
        )
        on_hand_days = int(
            (Decimal(on_hand) / base).to_integral_value(rounding=ROUND_FLOOR)
        )
        policy_triggered = on_hand <= reorder_point
        latest_order = (
            as_of
            if policy_triggered
            else as_of + timedelta(days=on_hand_days - lead)
        )
        priority = "urgent" if latest_order <= as_of else "soon" if latest_order <= as_of + timedelta(days=7) else "planned"
        unit_cost_raw = policy.get("unit_cost_brl")
        if unit_cost_raw is None:
            cash = Metric(None, "unknown", (f"replenishment:{sku}",))
            limitations.append(f"unit_cost_missing:{sku}")
        else:
            unit_cost = nonnegative_decimal(unit_cost_raw, "unit_cost_brl")
            cash = Metric(money(unit_cost * quantity), "derived", (f"replenishment:{sku}",))
        alias = f"replenishment:{sku}"
        evidence.append(Evidence(alias, "derived", "max(high_demand*target_cover+safety,reorder_point)-available_inventory; reorder threshold can trigger now", ("daily_sales", "product_inventory_sales", "replenishment_policy")))
        items.append(ReplenishmentItem(sku, low, base, high, quantity, latest_order, priority, cash, "derived", (alias,)))
    payload = {
        "algorithm_version": ALGORITHM_VERSION,
        "as_of": as_of,
        "items": tuple(items),
        "limitations": tuple(limitations),
    }
    return ReplenishmentResult(ALGORITHM_VERSION, as_of, tuple(items), tuple(evidence), tuple(limitations), stable_hash(payload))


def _unique_by_sku(
    rows: Sequence[Mapping[str, object]],
    kind: str,
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for row in rows:
        sku = _text(row.get("sku_id"), "sku_id")
        if sku in result:
            raise ValueError(f"duplicate_{kind}:{sku}")
        result[sku] = row
    return result


def _latest_inventory_by_sku(
    rows: Sequence[Mapping[str, object]],
    as_of: date,
    limitations: list[str],
) -> dict[str, Mapping[str, object]]:
    candidates: dict[str, list[tuple[date, Mapping[str, object]]]] = defaultdict(
        list
    )
    for row in rows:
        sku = _text(row.get("sku_id"), "sku_id")
        snapshot_date = _date_value(row.get("date"), "date")
        if snapshot_date > as_of:
            limitations.append(f"future_inventory_excluded:{sku}:{snapshot_date}")
            continue
        candidates[sku].append((snapshot_date, row))
    result: dict[str, Mapping[str, object]] = {}
    for sku, sku_candidates in candidates.items():
        sku_candidates.sort(key=lambda item: item[0], reverse=True)
        if (
            len(sku_candidates) > 1
            and sku_candidates[0][0] == sku_candidates[1][0]
        ):
            raise ValueError(f"duplicate_inventory:{sku}:{sku_candidates[0][0]}")
        result[sku] = sku_candidates[0][1]
    return result


def _unknown_item(sku: str) -> ReplenishmentItem:
    return ReplenishmentItem(sku, None, None, None, None, None, "blocked", Metric(None, "unknown", ()), "unknown", ())


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
