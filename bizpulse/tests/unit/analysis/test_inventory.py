from datetime import date
from decimal import Decimal

from src.analysis.inventory_risk_calculator import calculate_inventory_risk


def test_inventory_cover_uses_only_exact_sku_mapping() -> None:
    result = calculate_inventory_risk(
        sales=(
            {"date": "2026-07-01", "sku_id": "SKU-A", "units": 3},
            {"date": "2026-07-02", "sku_id": "SKU-A", "units": 1},
            {"date": "2026-07-01", "sku_id": "SKU-NOT-IN-INVENTORY", "units": 8},
        ),
        inventory=(
            {"date": "2026-07-02", "sku_id": "SKU-A", "on_hand_units": 4, "inbound_units": 2},
            {"date": "2026-07-02", "sku_id": "SKU-B", "on_hand_units": 50, "inbound_units": 0},
        ),
        as_of=date(2026, 7, 2),
    )

    sku_a, sku_b = result.items
    assert sku_a.sku_id == "SKU-A"
    assert sku_a.daily_velocity == Decimal("2.000000")
    assert sku_a.current_cover_days.value == Decimal("2.00")
    assert sku_a.projected_cover_days.value == Decimal("3.00")
    assert sku_a.risk == "stockout"
    assert sku_b.current_cover_days.value is None
    assert sku_b.risk == "unknown"
    assert "sales_without_inventory:SKU-NOT-IN-INVENTORY" in result.limitations
    assert "velocity_missing:SKU-B" in result.limitations


def test_inventory_without_inventory_source_is_explicitly_unknown() -> None:
    result = calculate_inventory_risk(
        sales=({"date": "2026-07-01", "sku_id": "SKU-A", "units": 3},),
        inventory=(),
        as_of=date(2026, 7, 2),
    )

    assert result.items == ()
    assert "inventory_missing" in result.limitations
    assert result.evidence[0].evidence_state == "unknown"


def test_inventory_uses_calendar_coverage_and_latest_as_of_snapshot() -> None:
    result = calculate_inventory_risk(
        sales=(
            {"date": "2026-07-01", "sku_id": "SKU-A", "units": 2},
            {"date": "2026-07-03", "sku_id": "SKU-A", "units": 2},
        ),
        inventory=(
            {"date": "2026-07-01", "sku_id": "SKU-A", "on_hand_units": 10, "inbound_units": 0},
            {"date": "2026-07-03", "sku_id": "SKU-A", "on_hand_units": 4, "inbound_units": 2},
        ),
        period_start=date(2026, 7, 1),
        as_of=date(2026, 7, 3),
    )

    assert result.items[0].on_hand_units == 4
    assert result.items[0].daily_velocity == Decimal("1.333333")
    assert result.items[0].current_cover_days.value == Decimal("3.00")
