from decimal import Decimal

from src.analysis.sales_ads_calculator import calculate_sales_ads


def test_sales_ads_exact_totals_rankings_and_evidence() -> None:
    result = calculate_sales_ads(
        sales=(
            {"date": "2026-07-01", "order_id": "O-1", "sku_id": "SKU-A", "units": 2, "gross_sales_brl": "200.00", "discount_brl": "10.00"},
            {"date": "2026-07-02", "order_id": "O-2", "sku_id": "SKU-B", "units": 1, "gross_sales_brl": "80.00", "discount_brl": "0.00"},
        ),
        advertising=(
            {"date": "2026-07-01", "sku_id": "SKU-A", "spend_brl": "25.00", "impressions": 500, "clicks": 25, "attributed_orders": 1},
            {"date": "2026-07-02", "sku_id": "SKU-B", "spend_brl": "15.00", "impressions": 300, "clicks": 15, "attributed_orders": 1},
        ),
    )

    assert result.gross_sales.value == Decimal("280.00")
    assert result.net_sales.value == Decimal("270.00")
    assert result.aov.value == Decimal("135.00")
    assert result.roas.value is None
    assert result.acos.value is None
    assert tuple(row.sku_id for row in result.sku_ranking) == ("SKU-A", "SKU-B")
    assert result.gross_sales.evidence_state == "measured"
    assert result.roas.evidence_state == "unknown"
    assert "attributed_revenue_missing" in result.limitations
    assert result.snapshot_hash == calculate_sales_ads(
        sales=tuple(reversed((
            {"date": "2026-07-01", "order_id": "O-1", "sku_id": "SKU-A", "units": 2, "gross_sales_brl": "200.00", "discount_brl": "10.00"},
            {"date": "2026-07-02", "order_id": "O-2", "sku_id": "SKU-B", "units": 1, "gross_sales_brl": "80.00", "discount_brl": "0.00"},
        ))),
        advertising=tuple(reversed((
            {"date": "2026-07-01", "sku_id": "SKU-A", "spend_brl": "25.00", "impressions": 500, "clicks": 25, "attributed_orders": 1},
            {"date": "2026-07-02", "sku_id": "SKU-B", "spend_brl": "15.00", "impressions": 300, "clicks": 15, "attributed_orders": 1},
        ))),
    ).snapshot_hash


def test_sales_ads_without_advertising_is_explicitly_unavailable() -> None:
    result = calculate_sales_ads(
        sales=({"date": "2026-07-01", "order_id": "O-1", "sku_id": "SKU-A", "units": 1, "gross_sales_brl": "20.00", "discount_brl": "0.00"},),
        advertising=(),
    )

    assert result.roas.value is None
    assert result.roas.evidence_state == "unknown"
    assert result.ad_spend.value is None
    assert result.ad_spend.evidence_state == "unknown"
    assert all(row.ad_spend is None for row in result.sku_ranking)
    assert all(row.ad_spend is None for row in result.daily_trends)
    assert "advertising_missing" in result.limitations


def test_sales_ads_without_sales_never_publishes_measured_zero() -> None:
    result = calculate_sales_ads(sales=(), advertising=())

    for metric in (
        result.gross_sales,
        result.net_sales,
        result.units,
        result.orders,
        result.aov,
    ):
        assert metric.value is None
        assert metric.evidence_state == "unknown"
    assert "sales_missing" in result.limitations
    evidence_states = {item.alias: item.evidence_state for item in result.evidence}
    assert evidence_states["sales.gross"] == "unknown"
    assert evidence_states["sales.net"] == "unknown"
    assert evidence_states["sales.activity"] == "unknown"
    assert evidence_states["advertising.total"] == "unknown"
    assert evidence_states["sales_ads.roas"] == "unknown"
    assert result.daily_trends == ()


def test_sales_ads_missing_discount_does_not_publish_known_net_sales() -> None:
    result = calculate_sales_ads(
        sales=(
            {
                "date": "2026-07-01",
                "order_id": "O-1",
                "sku_id": "SKU-A",
                "units": 1,
                "gross_sales_brl": "20.00",
            },
        ),
        advertising=(),
    )

    assert result.gross_sales.value == Decimal("20.00")
    assert result.gross_sales.evidence_state == "measured"
    assert result.net_sales.value is None
    assert result.aov.value is None
    assert result.sku_ranking == ()
    assert result.daily_trends == ()
    assert "daily_sales.discount_brl_missing" in result.limitations
