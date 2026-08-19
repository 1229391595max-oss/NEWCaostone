"""Deterministic sales-and-advertising metrics for canonical synthetic rows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from src.analysis.evidence import (
    Evidence,
    Metric,
    integer_value,
    money,
    nonnegative_decimal,
    stable_hash,
)

ALGORITHM_VERSION = "sales_ads.v1"


@dataclass(frozen=True, slots=True)
class SkuSales:
    sku_id: str
    net_sales: Decimal
    units: int
    ad_spend: Decimal | None
    roas: Decimal | None


@dataclass(frozen=True, slots=True)
class DailySales:
    date: str
    net_sales: Decimal
    ad_spend: Decimal | None


@dataclass(frozen=True, slots=True)
class SalesAdsResult:
    algorithm_version: str
    gross_sales: Metric
    net_sales: Metric
    units: Metric
    orders: Metric
    aov: Metric
    ad_spend: Metric
    roas: Metric
    acos: Metric
    sku_ranking: tuple[SkuSales, ...]
    daily_trends: tuple[DailySales, ...]
    anomalies: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    limitations: tuple[str, ...]
    snapshot_hash: str


def calculate_sales_ads(
    *,
    sales: Sequence[Mapping[str, object]],
    advertising: Sequence[Mapping[str, object]],
) -> SalesAdsResult:
    sales_rows = tuple(sales)
    ad_rows = tuple(advertising)
    gross = Decimal(0)
    discounts = Decimal(0)
    known_net_sales = Decimal(0)
    discounts_complete = True
    units = 0
    orders: set[str] = set()
    sku_sales: dict[str, list[Decimal | int]] = defaultdict(
        lambda: [Decimal(0), 0, Decimal(0)]
    )
    daily: dict[str, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for row in sales_rows:
        sku = _required_text(row.get("sku_id"), "sku_id")
        day = _required_text(row.get("date"), "date")
        row_units = integer_value(row.get("units"), "units")
        if row_units < 0:
            raise ValueError("units_negative")
        row_gross = nonnegative_decimal(row.get("gross_sales_brl"), "gross_sales_brl")
        if "discount_brl" not in row or row["discount_brl"] is None:
            discounts_complete = False
            row_discount = None
        else:
            row_discount = nonnegative_decimal(row["discount_brl"], "discount_brl")
            if row_discount > row_gross:
                raise ValueError("discount_exceeds_gross")
        gross += row_gross
        if row_discount is not None:
            discounts += row_discount
        units += row_units
        order_id = _required_text(row.get("order_id"), "order_id")
        orders.add(order_id)
        if row_discount is not None:
            net = row_gross - row_discount
            known_net_sales += net
            sku_sales[sku][0] += net
            sku_sales[sku][1] += row_units
            daily[day][0] += net

    spend = Decimal(0)
    for row in ad_rows:
        sku = _required_text(row.get("sku_id"), "sku_id")
        day = _required_text(row.get("date"), "date")
        row_spend = nonnegative_decimal(row.get("spend_brl"), "spend_brl")
        for field in ("impressions", "clicks", "attributed_orders"):
            if integer_value(row.get(field), field) < 0:
                raise ValueError(f"{field}_negative")
        spend += row_spend
        sku_sales[sku][2] += row_spend
        daily[day][1] += row_spend

    net_sales = gross - discounts if discounts_complete else known_net_sales
    gross_refs = ("sales.gross",)
    net_refs = ("sales.net",)
    activity_refs = ("sales.activity",)
    ad_refs = ("advertising.total",)
    limitations: list[str] = []
    if not sales_rows:
        limitations.append("sales_missing")
    elif not discounts_complete:
        limitations.append("daily_sales.discount_brl_missing")
    if not ad_rows:
        limitations.append("advertising_missing")
    aov_value = (
        money(net_sales / len(orders))
        if orders and discounts_complete
        else None
    )
    roas_value = None
    acos_value = None
    if sales_rows and ad_rows:
        limitations.append("attributed_revenue_missing")
    sku_ranking = tuple(
        SkuSales(
            sku,
            money(values[0]),
            int(values[1]),
            money(values[2]) if ad_rows else None,
            None,
        )
        for sku, values in sorted(
            sku_sales.items(),
            key=lambda item: (-Decimal(item[1][0]), item[0]),
        )
    ) if sales_rows and discounts_complete else ()
    trends = tuple(
        DailySales(
            day,
            money(values[0]),
            money(values[1]) if ad_rows else None,
        )
        for day, values in sorted(daily.items())
    ) if sales_rows and discounts_complete else ()
    anomalies = _anomalies(trends)
    evidence = (
        Evidence(
            "sales.gross",
            "measured" if sales_rows else "unknown",
            "sum(gross_sales_brl)",
            ("daily_sales",),
        ),
        Evidence(
            "sales.net",
            "derived" if sales_rows and discounts_complete else "unknown",
            "sum(gross_sales_brl)-sum(discount_brl)",
            ("daily_sales",),
        ),
        Evidence(
            "sales.activity",
            "measured" if sales_rows else "unknown",
            "sum(units) and distinct(order_id)",
            ("daily_sales",),
        ),
        Evidence(
            "advertising.total",
            "measured" if ad_rows else "unknown",
            "sum(spend)",
            ("shopee_advertising",),
        ),
        Evidence(
            "sales_ads.roas",
            "unknown",
            "requires attributed_revenue; total sales is not advertising revenue",
            ("daily_sales", "shopee_advertising"),
        ),
    )
    hash_payload = {
        "algorithm_version": ALGORITHM_VERSION,
        "sales": sorted((dict(row) for row in sales_rows), key=stable_hash),
        "advertising": sorted((dict(row) for row in ad_rows), key=stable_hash),
        "sku_ranking": sku_ranking,
        "daily_trends": trends,
        "limitations": tuple(limitations),
    }
    unknown = Metric(None, "unknown", (), None)
    sales_state = "measured" if sales_rows else "unknown"
    derived_sales_state = (
        "derived" if sales_rows and discounts_complete else "unknown"
    )
    return SalesAdsResult(
        ALGORITHM_VERSION,
        Metric(money(gross), sales_state, gross_refs) if sales_rows else unknown,
        Metric(
            money(net_sales) if discounts_complete else None,
            derived_sales_state,
            net_refs,
            money(net_sales),
        )
        if sales_rows
        else unknown,
        Metric(Decimal(units), sales_state, activity_refs) if sales_rows else unknown,
        Metric(Decimal(len(orders)), sales_state, activity_refs) if sales_rows else unknown,
        Metric(aov_value, "derived", net_refs) if aov_value is not None else unknown,
        Metric(money(spend), "measured", ad_refs) if ad_rows else unknown,
        Metric(roas_value, "unknown", net_refs + ad_refs),
        Metric(acos_value, "unknown", net_refs + ad_refs),
        sku_ranking,
        trends,
        anomalies,
        evidence,
        tuple(limitations),
        stable_hash(hash_payload),
    )


def _anomalies(trends: tuple[DailySales, ...]) -> tuple[str, ...]:
    if len(trends) < 2:
        return ()
    average = sum((row.net_sales for row in trends), Decimal(0)) / len(trends)
    if not average:
        return ()
    return tuple(
        f"sales_spike:{row.date}"
        for row in trends
        if row.net_sales >= average * Decimal("1.5")
    )


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}_invalid")
    return value.strip()
