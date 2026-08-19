from datetime import date
from decimal import Decimal

from src.analysis.fifo_cost_aging_calculator import calculate_fifo_cost_aging


def test_fifo_allocates_oldest_lot_and_reports_aging() -> None:
    result = calculate_fifo_cost_aging(
        receipt_lots=(
            {"lot_id": "L-OLD", "receipt_date": "2026-03-01", "sku_id": "SKU-A", "quantity_received": 5, "unit_cost_brl": "10.00"},
            {"lot_id": "L-NEW", "receipt_date": "2026-07-01", "sku_id": "SKU-A", "quantity_received": 5, "unit_cost_brl": "12.00"},
        ),
        outbound_events=({"outbound_id": "OUT-1", "date": "2026-07-30", "sku_id": "SKU-A", "quantity": 7},),
        as_of=date(2026, 7, 30),
    )

    assert tuple((row.lot_id, row.quantity) for row in result.allocations) == (("L-OLD", 5), ("L-NEW", 2))
    assert result.cogs.value == Decimal("74.00")
    assert result.cogs.evidence_state == "derived"
    assert result.ending_inventory_value.value == Decimal("36.00")
    assert result.aging_90_units == 0
    assert result.aging_120_units == 0


def test_fifo_partial_cost_coverage_never_invents_missing_lots() -> None:
    result = calculate_fifo_cost_aging(
        receipt_lots=({"lot_id": "L-1", "receipt_date": "2026-07-01", "sku_id": "SKU-A", "quantity_received": 2, "unit_cost_brl": "10.00"},),
        outbound_events=({"outbound_id": "OUT-1", "date": "2026-07-30", "sku_id": "SKU-A", "quantity": 3},),
        as_of=date(2026, 7, 30),
    )

    assert result.cogs.value is None
    assert result.cogs.known_subtotal == Decimal("20.00")
    assert result.cogs.evidence_state == "unknown"
    assert result.ending_inventory_value.value is None
    assert result.ending_inventory_value.evidence_state == "unknown"
    assert result.aging_90_units is None
    assert result.aging_120_units is None
    assert "uncovered_outbound:SKU-A:1" in result.limitations


def test_fifo_without_sources_never_publishes_derived_zero() -> None:
    result = calculate_fifo_cost_aging(
        receipt_lots=(),
        outbound_events=(),
        as_of=date(2026, 7, 30),
    )

    assert result.cogs.value is None
    assert result.cogs.evidence_state == "unknown"
    assert result.ending_inventory_value.value is None
    assert result.aging_90_units is None
    assert result.aging_120_units is None
    assert result.ending_inventory_value.evidence_state == "unknown"
    assert "receipt_lots_missing" in result.limitations
    assert "outbound_events_missing" in result.limitations


def test_fifo_never_uses_a_lot_received_after_the_outbound() -> None:
    result = calculate_fifo_cost_aging(
        receipt_lots=({"lot_id": "L-LATE", "receipt_date": "2026-07-10", "sku_id": "SKU-A", "quantity_received": 2, "unit_cost_brl": "7.00"},),
        outbound_events=({"outbound_id": "OUT-EARLY", "date": "2026-07-01", "sku_id": "SKU-A", "quantity": 1},),
        as_of=date(2026, 7, 30),
    )

    assert result.allocations == ()
    assert result.cogs.value is None
    assert result.cogs.known_subtotal == Decimal("0.00")
    assert "uncovered_outbound:SKU-A:1" in result.limitations


def test_fifo_excludes_future_lots_and_outbound_events() -> None:
    result = calculate_fifo_cost_aging(
        receipt_lots=({"lot_id": "L-FUTURE", "receipt_date": "2026-08-01", "sku_id": "SKU-A", "quantity_received": 2, "unit_cost_brl": "7.00"},),
        outbound_events=({"outbound_id": "OUT-FUTURE", "date": "2026-08-01", "sku_id": "SKU-A", "quantity": 1},),
        as_of=date(2026, 7, 30),
    )

    assert result.cogs.value is None
    assert result.ending_inventory_value.value is None
    assert "future_receipt_excluded:L-FUTURE" in result.limitations
    assert "future_outbound_excluded:OUT-FUTURE" in result.limitations


def test_fifo_uses_history_for_ending_inventory_but_period_only_for_cogs() -> None:
    result = calculate_fifo_cost_aging(
        receipt_lots=(
            {
                "lot_id": "L-1",
                "receipt_date": "2026-06-01",
                "sku_id": "SKU-A",
                "quantity_received": 10,
                "unit_cost_brl": "10.00",
            },
        ),
        outbound_events=(
            {
                "outbound_id": "OUT-JUNE",
                "date": "2026-06-15",
                "sku_id": "SKU-A",
                "quantity": 4,
            },
            {
                "outbound_id": "OUT-JULY",
                "date": "2026-07-10",
                "sku_id": "SKU-A",
                "quantity": 2,
            },
        ),
        period_start=date(2026, 7, 1),
        as_of=date(2026, 7, 30),
    )

    assert result.cogs.value == Decimal("20.00")
    assert result.ending_inventory_value.value == Decimal("40.00")
    assert len(result.allocations) == 2
