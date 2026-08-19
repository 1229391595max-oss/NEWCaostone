"""Deterministic layered operating-profit calculation with unknown propagation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from src.analysis.evidence import Evidence, Metric, money, nonnegative_decimal, stable_hash

ALGORITHM_VERSION = "operating_profit.v2"


@dataclass(frozen=True, slots=True)
class OperatingProfitResult:
    algorithm_version: str
    net_revenue: Metric
    gross_profit: Metric
    contribution_profit: Metric
    operating_profit: Metric
    components: tuple[tuple[str, Decimal | None], ...]
    evidence: tuple[Evidence, ...]
    limitations: tuple[str, ...]
    snapshot_hash: str


def calculate_operating_profit(
    inputs: Mapping[str, Sequence[Mapping[str, object]]],
) -> OperatingProfitResult:
    limitations: list[str] = []
    gross_sales = _sum(inputs, "daily_sales", "gross_sales_brl", limitations)
    discounts = _sum(inputs, "daily_sales", "discount_brl", limitations)
    refunds = _sum(inputs, "refund", "refund_brl", limitations)
    cogs = _sum(inputs, "fifo_cogs", "cogs_brl", limitations)
    platform = _sum(inputs, "settlement", "fee_brl", limitations)
    advertising = _sum(inputs, "shopee_advertising", "spend_brl", limitations)
    fulfillment = _sum(inputs, "fulfillment_cost", "cost_brl", limitations)
    operating_expense = _sum(inputs, "operating_expense", "amount_brl", limitations)
    tax = _sum_optional(inputs, "tax", "tax_brl", limitations)
    other_mapped = _sum(
        inputs,
        "other_variable_cost",
        "cost_brl",
        limitations,
    )
    fx_rows = inputs.get("fx_assumption", ())
    for row in fx_rows:
        rate = nonnegative_decimal(row.get("brl_per_usd"), "brl_per_usd")
        if not rate:
            raise ValueError("brl_per_usd_zero")
    fx_effect = _sum_signed(inputs, "fx_effect", "effect_brl", limitations)
    if fx_effect is None:
        limitations.append("fx_effect_unavailable_brl_only_inputs")

    revenue_known = (
        (gross_sales or Decimal(0))
        - (discounts or Decimal(0))
        - (refunds or Decimal(0))
    )
    net_value = (
        money(gross_sales - discounts - refunds)
        if None not in (gross_sales, discounts, refunds)
        else None
    )
    net = _metric(net_value, money(revenue_known), ("profit.net_revenue",))

    gross_known = (net_value if net_value is not None else revenue_known) - (cogs or Decimal(0))
    gross_value = money(net_value - cogs) if net_value is not None and cogs is not None else None
    gross = _metric(gross_value, money(gross_known), ("profit.gross",))

    contribution_costs = (platform, advertising, fulfillment, tax, other_mapped)
    contribution_known = (gross_value if gross_value is not None else gross_known) - sum(
        (value for value in contribution_costs if value is not None), Decimal(0)
    ) + (fx_effect or Decimal(0))
    contribution_value = (
        money(
            gross_value
            - sum(contribution_costs, Decimal(0))
            + fx_effect
        )
        if (
            gross_value is not None
            and all(value is not None for value in contribution_costs)
            and fx_effect is not None
        )
        else None
    )
    contribution = _metric(
        contribution_value,
        money(contribution_known),
        ("profit.contribution",),
    )

    operating_known = (
        contribution_value if contribution_value is not None else contribution_known
    ) - (operating_expense or Decimal(0))
    operating_value = (
        money(contribution_value - operating_expense)
        if contribution_value is not None and operating_expense is not None
        else None
    )
    operating = _metric(operating_value, money(operating_known), ("profit.operating",))
    components = (
        ("gross_sales", gross_sales),
        ("discounts", discounts),
        ("refunds", refunds),
        ("cogs", cogs),
        ("platform_fees", platform),
        ("advertising", advertising),
        ("fulfillment", fulfillment),
        ("tax", tax),
        ("other_mapped", other_mapped),
        ("operating_expense", operating_expense),
        ("fx_effect", fx_effect),
    )
    evidence = (
        Evidence("profit.net_revenue", net.evidence_state, "gross-discounts-refunds", ("daily_sales", "refund")),
        Evidence("profit.gross", gross.evidence_state, "net_revenue-fifo_cogs", ("daily_sales", "refund", "fifo_cogs")),
        Evidence("profit.contribution", contribution.evidence_state, "gross_profit-platform-advertising-fulfillment-tax-other_mapped+fx_effect", ("settlement", "shopee_advertising", "fulfillment_cost", "tax", "other_variable_cost", "fx_effect")),
        Evidence("profit.operating", operating.evidence_state, "contribution_profit-operating_expense", ("operating_expense",)),
        Evidence(
            "profit.other_mapped",
            "measured" if other_mapped is not None else "unknown",
            "sum(other_variable_cost.cost_brl)",
            ("other_variable_cost",),
        ),
        Evidence(
            "profit.fx_effect",
            "measured" if fx_effect is not None else "unknown",
            (
                "sum(fx_effect.effect_brl)"
                if fx_effect is not None
                else "no explicit BRL FX effect is available"
            ),
            ("fx_effect", "fx_assumption"),
        ),
    )
    payload = {
        "algorithm_version": ALGORITHM_VERSION,
        "components": components,
        "net_revenue": net,
        "gross_profit": gross,
        "contribution_profit": contribution,
        "operating_profit": operating,
        "limitations": tuple(limitations),
    }
    return OperatingProfitResult(
        ALGORITHM_VERSION,
        net,
        gross,
        contribution,
        operating,
        components,
        evidence,
        tuple(limitations),
        stable_hash(payload),
    )


def _sum(
    inputs: Mapping[str, Sequence[Mapping[str, object]]],
    role: str,
    field: str,
    limitations: list[str],
) -> Decimal | None:
    rows = inputs.get(role)
    if not rows:
        limitation = f"{role}_missing"
        if limitation not in limitations:
            limitations.append(limitation)
        return None
    if any(field not in row or row[field] is None for row in rows):
        limitations.append(f"{role}.{field}_missing")
        return None
    return money(sum((nonnegative_decimal(row[field], field) for row in rows), Decimal(0)))


def _sum_optional(
    inputs: Mapping[str, Sequence[Mapping[str, object]]],
    role: str,
    field: str,
    limitations: list[str],
) -> Decimal | None:
    rows = inputs.get(role)
    if not rows:
        return Decimal(0)
    if any(field not in row or row[field] is None for row in rows):
        limitations.append(f"{role}.{field}_missing")
        return None
    return money(sum((nonnegative_decimal(row[field], field) for row in rows), Decimal(0)))


def _sum_signed(
    inputs: Mapping[str, Sequence[Mapping[str, object]]],
    role: str,
    field: str,
    limitations: list[str],
) -> Decimal | None:
    rows = inputs.get(role)
    if not rows:
        limitation = f"{role}_missing"
        if limitation not in limitations:
            limitations.append(limitation)
        return None
    if any(field not in row or row[field] is None for row in rows):
        limitations.append(f"{role}.{field}_missing")
        return None
    values: list[Decimal] = []
    for row in rows:
        value = Decimal(str(row[field]))
        if not value.is_finite():
            raise ValueError(f"{field}_invalid")
        values.append(value)
    return money(sum(values, Decimal(0)))


def _metric(
    value: Decimal | None,
    known_subtotal: Decimal,
    refs: tuple[str, ...],
) -> Metric:
    return Metric(
        value,
        "derived" if value is not None else "unknown",
        refs,
        value if value is not None else known_subtotal,
    )
