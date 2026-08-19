"""Exact fixed-order contribution-profit bridge formulas."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from src.profit.contracts import (
    ProfitBridge,
    ProfitBridgeItem,
    ProfitPeriod,
    ProfitSku,
)

FORMULA_VERSION = "profit_bridge.v1"
CENT = Decimal("0.01")
DRIVER_ORDER = (
    "volume",
    "price_discount",
    "mix",
    "advertising",
    "refunds",
    "fulfillment",
    "platform_fees",
    "cogs",
    "fx",
    "tax",
    "other_mapped",
    "residual",
)


def build_profit_bridge(
    current: ProfitPeriod,
    baseline: ProfitPeriod,
    tolerance: Decimal = CENT,
) -> ProfitBridge:
    if not isinstance(current, ProfitPeriod) or not isinstance(
        baseline, ProfitPeriod
    ):
        raise ValueError("profit_period_invalid")
    if (
        not isinstance(tolerance, Decimal)
        or not tolerance.is_finite()
        or tolerance < 0
    ):
        raise ValueError("profit_bridge_tolerance_invalid")
    current_days = (current.period_end - current.period_start).days + 1
    baseline_days = (baseline.period_end - baseline.period_start).days + 1
    complete_months = _is_complete_month(
        current.period_start,
        current.period_end,
    ) and _is_complete_month(
        baseline.period_start,
        baseline.period_end,
    )
    if (
        current_days != baseline_days
        and not complete_months
    ) or baseline.period_end >= current.period_start:
        raise ValueError("profit_bridge_periods_invalid")

    limitations: list[str] = []
    baseline_skus = {item.sku_id: item for item in baseline.skus}
    current_skus = {item.sku_id: item for item in current.skus}
    sku_ids = tuple(sorted(set(baseline_skus) | set(current_skus)))
    complete_baselines = tuple(
        item
        for item in baseline.skus
        if item.net_unit_revenue_brl is not None
        and item.unit_cogs_brl is not None
    )
    assumed = False
    aligned: list[tuple[ProfitSku, ProfitSku]] = []
    for sku_id in sku_ids:
        base = baseline_skus.get(sku_id)
        current_sku = current_skus.get(sku_id)
        if base is None and current_sku is not None:
            reference = _nearest_baseline(current_sku, complete_baselines)
            if reference is None:
                base = ProfitSku(sku_id, 0, None, None)
                limitations.append(f"new_sku_baseline_missing:{sku_id}")
            else:
                base = ProfitSku(
                    sku_id,
                    0,
                    reference.net_unit_revenue_brl,
                    reference.unit_cogs_brl,
                )
                assumed = True
                limitations.append(
                    f"new_sku_baseline_assumption:{sku_id}:{reference.sku_id}"
                )
        if current_sku is None and base is not None:
            current_sku = ProfitSku(
                sku_id,
                0,
                base.net_unit_revenue_brl,
                base.unit_cogs_brl,
            )
            assumed = True
            limitations.append(
                f"discontinued_sku_current_assumption:{sku_id}"
            )
        if base is None or current_sku is None:
            raise AssertionError("aligned_sku_missing")
        aligned.append((base, current_sku))

    q0 = sum((base.quantity for base, _current in aligned), 0)
    q1 = sum((item.quantity for _base, item in aligned), 0)
    all_baseline_margins = tuple(
        (
            base,
            base.net_unit_revenue_brl - base.unit_cogs_brl,
        )
        for base, _current in aligned
        if base.net_unit_revenue_brl is not None
        and base.unit_cogs_brl is not None
    )
    weighted_baseline_margins = tuple(
        (item, margin)
        for item, margin in all_baseline_margins
        if item.quantity > 0
    )
    baseline_margin_complete = (
        q0 > 0
        and sum(
            (item.quantity for item, _margin in weighted_baseline_margins),
            0,
        )
        == q0
    )
    weighted_margin = (
        sum(
            (
                Decimal(item.quantity) * margin
                for item, margin in weighted_baseline_margins
            ),
            Decimal(0),
        )
        / Decimal(q0)
        if baseline_margin_complete
        else None
    )

    margin_by_sku = {
        item.sku_id: margin for item, margin in all_baseline_margins
    }
    if weighted_margin is None or any(
        base.sku_id not in margin_by_sku
        for base, current_sku in aligned
        if base.quantity != current_sku.quantity
    ):
        volume = None
        mix = None
        limitations.extend(("volume_inputs_missing", "mix_inputs_missing"))
    else:
        volume = _money(Decimal(q1 - q0) * weighted_margin)
        mix = _money(
            sum(
                (
                    Decimal(current_sku.quantity - base.quantity)
                    * (margin_by_sku[base.sku_id] - weighted_margin)
                    for base, current_sku in aligned
                ),
                Decimal(0),
            )
        )

    price_discount = _sku_change(
        aligned,
        current_field="net_unit_revenue_brl",
        baseline_field="net_unit_revenue_brl",
        sign=Decimal(1),
    )
    cogs = _sku_change(
        aligned,
        current_field="unit_cogs_brl",
        baseline_field="unit_cogs_brl",
        sign=Decimal(-1),
    )
    if price_discount is None:
        limitations.append("price_discount_inputs_missing")
    if cogs is None:
        limitations.append("cogs_inputs_missing")

    values = {
        "volume": volume,
        "price_discount": price_discount,
        "mix": mix,
        "advertising": _cost_change(
            current.advertising_brl,
            baseline.advertising_brl,
        ),
        "refunds": _cost_change(
            current.refund_loss_brl,
            baseline.refund_loss_brl,
        ),
        "fulfillment": _cost_change(
            current.fulfillment_brl,
            baseline.fulfillment_brl,
        ),
        "platform_fees": _cost_change(
            current.platform_fee_brl,
            baseline.platform_fee_brl,
        ),
        "cogs": cogs,
        "fx": _signed_change(current.fx_effect_brl, baseline.fx_effect_brl),
        "tax": _cost_change(current.tax_brl, baseline.tax_brl),
        "other_mapped": _cost_change(
            current.other_mapped_brl,
            baseline.other_mapped_brl,
        ),
    }
    for driver, field in (
        ("advertising", "advertising"),
        ("refunds", "refund_loss"),
        ("fulfillment", "fulfillment"),
        ("platform_fees", "platform_fee"),
        ("fx", "fx_effect"),
        ("tax", "tax"),
        ("other_mapped", "other_mapped"),
    ):
        if values[driver] is None:
            limitations.append(f"{field}_missing")

    total_change = _signed_change(
        current.contribution_profit_brl,
        baseline.contribution_profit_brl,
    )
    unknown_driver = any(value is None for value in values.values())
    known_driver_sum = sum(
        (value for value in values.values() if value is not None),
        Decimal(0),
    )
    residual = (
        _money(total_change - known_driver_sum)
        if total_change is not None
        else None
    )
    residual_state = (
        "unknown" if total_change is None or unknown_driver else "derived"
    )
    reconciled = bool(
        total_change is not None
        and not unknown_driver
        and residual is not None
        and abs(residual) <= tolerance
    )
    if total_change is None:
        limitations.append("contribution_profit_missing")
    if unknown_driver:
        limitations.append("bridge_inputs_incomplete")
    elif not reconciled:
        limitations.append("residual_outside_tolerance")

    formulas = {
        "volume": "(Q1-Q0)*baseline_weighted_mean_margin",
        "price_discount": "sum(q1_s*(net_unit_revenue1_s-net_unit_revenue0_s))",
        "mix": "sum((q1_s-q0_s)*(baseline_margin_s-baseline_weighted_mean_margin))",
        "advertising": "-(advertising1-advertising0)",
        "refunds": "-(refund_loss1-refund_loss0)",
        "fulfillment": "-(fulfillment1-fulfillment0)",
        "platform_fees": "-(platform_fee1-platform_fee0)",
        "cogs": "-sum(q1_s*(unit_cogs1_s-unit_cogs0_s))",
        "fx": "fx_effect1-fx_effect0",
        "tax": "-(tax1-tax0)",
        "other_mapped": "-(other_variable_cost1-other_variable_cost0)",
        "residual": "total_contribution_profit_change-sum(known_drivers)",
    }
    refs = {
        "volume": ("daily_sales", "inventory_receipt_lot", "outbound_event"),
        "price_discount": ("daily_sales",),
        "mix": ("daily_sales", "inventory_receipt_lot", "outbound_event"),
        "advertising": ("shopee_advertising",),
        "refunds": ("refund",),
        "fulfillment": ("fulfillment_cost",),
        "platform_fees": ("settlement",),
        "cogs": ("inventory_receipt_lot", "outbound_event"),
        "fx": ("fx_effect",),
        "tax": ("tax",),
        "other_mapped": ("other_variable_cost",),
        "residual": ("operating_profit",),
    }
    items = tuple(
        ProfitBridgeItem(
            driver=driver,
            ordinal=ordinal,
            amount_brl=(residual if driver == "residual" else values[driver]),
            evidence_state=(
                residual_state
                if driver == "residual"
                else "unknown"
                if values[driver] is None
                else "assumed"
                if assumed and driver in {"volume", "price_discount", "mix", "cogs"}
                else "derived"
            ),
            formula=formulas[driver],
            source_refs=refs[driver],
        )
        for ordinal, driver in enumerate(DRIVER_ORDER, start=1)
    )
    return ProfitBridge(
        formula_version=FORMULA_VERSION,
        baseline_period=(baseline.period_start, baseline.period_end),
        current_period=(current.period_start, current.period_end),
        baseline_contribution_profit_brl=_money_optional(
            baseline.contribution_profit_brl
        ),
        current_contribution_profit_brl=_money_optional(
            current.contribution_profit_brl
        ),
        total_change_brl=total_change,
        items=items,
        residual_brl=residual,
        reconciled=reconciled,
        limitations=tuple(dict.fromkeys(limitations)),
    )


def _is_complete_month(period_start: date, period_end: date) -> bool:
    if period_start.day != 1:
        return False
    next_month = (
        date(period_start.year + 1, 1, 1)
        if period_start.month == 12
        else date(period_start.year, period_start.month + 1, 1)
    )
    return period_end == next_month - timedelta(days=1)


def _nearest_baseline(
    current: ProfitSku,
    candidates: tuple[ProfitSku, ...],
) -> ProfitSku | None:
    if current.net_unit_revenue_brl is None or not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            abs(item.net_unit_revenue_brl - current.net_unit_revenue_brl),
            item.sku_id,
        ),
    )


def _sku_change(
    aligned: list[tuple[ProfitSku, ProfitSku]],
    *,
    current_field: str,
    baseline_field: str,
    sign: Decimal,
) -> Decimal | None:
    total = Decimal(0)
    for baseline, current in aligned:
        if current.quantity == 0:
            continue
        current_value = getattr(current, current_field)
        baseline_value = getattr(baseline, baseline_field)
        if current_value is None or baseline_value is None:
            return None
        total += Decimal(current.quantity) * (current_value - baseline_value)
    return _money(sign * total)


def _cost_change(
    current: Decimal | None,
    baseline: Decimal | None,
) -> Decimal | None:
    value = _signed_change(current, baseline)
    return _money(-value) if value is not None else None


def _signed_change(
    current: Decimal | None,
    baseline: Decimal | None,
) -> Decimal | None:
    if current is None or baseline is None:
        return None
    return _money(current - baseline)


def _money_optional(value: Decimal | None) -> Decimal | None:
    return _money(value) if value is not None else None


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)
