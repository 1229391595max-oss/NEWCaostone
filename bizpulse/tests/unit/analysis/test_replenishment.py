from datetime import date
from decimal import Decimal

from src.analysis.replenishment_calculator import calculate_replenishment


def test_replenishment_has_ordered_bands_timing_priority_and_cash() -> None:
    sales = tuple(
        {"date": f"2026-07-{day:02d}", "sku_id": "SKU-A", "units": 2}
        for day in range(1, 31)
    )
    result = calculate_replenishment(
        sales=sales,
        inventory=({"date": "2026-07-30", "sku_id": "SKU-A", "on_hand_units": 8, "inbound_units": 2},),
        policies=({"sku_id": "SKU-A", "lead_time_days": 10, "safety_stock_units": 5, "reorder_point_units": 40, "target_cover_days": 30, "unit_cost_brl": "12.50"},),
        as_of=date(2026, 7, 30),
    )

    item = result.items[0]
    assert (item.low_daily, item.base_daily, item.high_daily) == (Decimal("1.600000"), Decimal("2.000000"), Decimal("2.400000"))
    assert item.recommended_quantity == 69
    assert item.latest_order_date == date(2026, 7, 30)
    assert item.priority == "urgent"
    assert item.cash_required.value == Decimal("862.50")
    assert "inbound_availability_unknown:SKU-A" in result.limitations


def test_replenishment_insufficient_demand_is_explicit() -> None:
    result = calculate_replenishment(
        sales=(),
        inventory=({"date": "2026-07-30", "sku_id": "SKU-A", "on_hand_units": 8, "inbound_units": 0},),
        policies=({"sku_id": "SKU-A", "lead_time_days": 10, "safety_stock_units": 5, "reorder_point_units": 40, "target_cover_days": 30},),
        as_of=date(2026, 7, 30),
    )

    item = result.items[0]
    assert item.recommended_quantity is None
    assert item.cash_required.value is None
    assert item.evidence_state == "unknown"
    assert "demand_history_missing:SKU-A" in result.limitations


def test_replenishment_short_history_does_not_create_precise_quantity() -> None:
    result = calculate_replenishment(
        sales=tuple(
            {"date": f"2026-07-0{day}", "sku_id": "SKU-A", "units": 2}
            for day in range(1, 4)
        ),
        inventory=({"date": "2026-07-30", "sku_id": "SKU-A", "on_hand_units": 8, "inbound_units": 0},),
        policies=({"sku_id": "SKU-A", "lead_time_days": 10, "safety_stock_units": 5, "reorder_point_units": 40, "target_cover_days": 30},),
        as_of=date(2026, 7, 30),
    )

    assert result.items[0].recommended_quantity is None
    assert result.items[0].evidence_state == "unknown"
    assert "demand_history_insufficient:SKU-A:3" in result.limitations


def test_replenishment_without_inventory_source_is_explicitly_unknown() -> None:
    result = calculate_replenishment(
        sales=({"date": "2026-07-01", "sku_id": "SKU-A", "units": 2},),
        inventory=(),
        policies=(),
        as_of=date(2026, 7, 30),
    )

    assert result.items == ()
    assert "inventory_missing" in result.limitations
    assert result.evidence[0].evidence_state == "unknown"


def test_replenishment_uses_calendar_days_including_zero_sale_days() -> None:
    result = calculate_replenishment(
        sales=(
            {"date": "2026-07-01", "sku_id": "SKU-A", "units": 2},
            {"date": "2026-07-07", "sku_id": "SKU-A", "units": 2},
        ),
        inventory=({"date": "2026-07-07", "sku_id": "SKU-A", "on_hand_units": 8, "inbound_units": 0},),
        policies=({"sku_id": "SKU-A", "lead_time_days": 10, "safety_stock_units": 5, "reorder_point_units": 40, "target_cover_days": 30, "unit_cost_brl": "12.50"},),
        period_start=date(2026, 7, 1),
        as_of=date(2026, 7, 7),
    )

    assert result.items[0].base_daily == Decimal("0.571429")
    assert result.items[0].recommended_quantity is not None


def test_replenishment_uses_conservative_floor_for_latest_order_date() -> None:
    result = calculate_replenishment(
        sales=tuple(
            {"date": f"2026-07-{day:02d}", "sku_id": "SKU-A", "units": 5}
            for day in range(1, 14)
        ),
        inventory=(
            {"date": "2026-07-13", "sku_id": "SKU-A", "on_hand_units": 13, "inbound_units": 0},
        ),
        policies=(
            {
                "sku_id": "SKU-A",
                "lead_time_days": 2,
                "safety_stock_units": 0,
                "reorder_point_units": 0,
                "target_cover_days": 7,
            },
        ),
        period_start=date(2026, 7, 1),
        as_of=date(2026, 7, 13),
    )

    assert result.items[0].base_daily == Decimal("5.000000")
    assert result.items[0].latest_order_date == date(2026, 7, 13)


def test_replenishment_uses_latest_inventory_snapshot_at_or_before_as_of() -> None:
    result = calculate_replenishment(
        sales=tuple(
            {"date": f"2026-07-{day:02d}", "sku_id": "SKU-A", "units": 2}
            for day in range(1, 8)
        ),
        inventory=(
            {"date": "2026-07-01", "sku_id": "SKU-A", "on_hand_units": 20, "inbound_units": 0},
            {"date": "2026-07-07", "sku_id": "SKU-A", "on_hand_units": 8, "inbound_units": 0},
            {"date": "2026-08-01", "sku_id": "SKU-A", "on_hand_units": 99, "inbound_units": 0},
        ),
        policies=(
            {
                "sku_id": "SKU-A",
                "lead_time_days": 2,
                "safety_stock_units": 0,
                "reorder_point_units": 0,
                "target_cover_days": 7,
            },
        ),
        period_start=date(2026, 7, 1),
        as_of=date(2026, 7, 7),
    )

    assert result.items[0].latest_order_date == date(2026, 7, 9)
    assert "future_inventory_excluded:SKU-A:2026-08-01" in result.limitations


def test_replenishment_reorder_point_changes_trigger_and_quantity() -> None:
    sales = tuple(
        {"date": f"2026-07-{day:02d}", "sku_id": "SKU-A", "units": 2}
        for day in range(1, 31)
    )
    common = {
        "sku_id": "SKU-A",
        "lead_time_days": 2,
        "safety_stock_units": 5,
        "target_cover_days": 10,
    }
    inventory = (
        {"date": "2026-07-30", "sku_id": "SKU-A", "on_hand_units": 50, "inbound_units": 0},
    )

    low_trigger = calculate_replenishment(
        sales=sales,
        inventory=inventory,
        policies=({**common, "reorder_point_units": 0},),
        period_start=date(2026, 7, 1),
        as_of=date(2026, 7, 30),
    )
    high_trigger = calculate_replenishment(
        sales=sales,
        inventory=inventory,
        policies=({**common, "reorder_point_units": 100},),
        period_start=date(2026, 7, 1),
        as_of=date(2026, 7, 30),
    )

    assert low_trigger.items[0].recommended_quantity == 0
    assert low_trigger.items[0].priority == "planned"
    assert high_trigger.items[0].recommended_quantity == 50
    assert high_trigger.items[0].priority == "urgent"
    assert high_trigger.snapshot_hash != low_trigger.snapshot_hash
