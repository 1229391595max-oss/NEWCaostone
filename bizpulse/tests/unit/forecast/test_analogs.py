from datetime import date
from decimal import Decimal

import pytest

from src.forecast.analogs import select_analogs
from src.forecast.contracts import HistoricalSku, ProductCandidate


def _candidate() -> ProductCandidate:
    return ProductCandidate(
        product_name="Synthetic Travel Organizer",
        category=" Travel_Bag ",
        attributes=("Portable", "Zippered", "portable"),
        planned_launch_date=date(2026, 8, 20),
        planned_price_brl=Decimal("100.00"),
        expected_discount_brl=Decimal("0.00"),
        unit_cost_brl=Decimal("40.00"),
        opening_inventory_units=50,
        moq_units=24,
        lead_time_days=20,
        planned_daily_ad_brl=Decimal("10.00"),
    )


def _sku(sku_id: str, **overrides) -> HistoricalSku:
    values = {
        "sku_id": sku_id,
        "category": "travel_bag",
        "attributes": ("portable", "zippered"),
        "net_price_brl": Decimal("100.00"),
        "daily_ad_spend_brl": Decimal("10.00"),
        "history_days": 90,
        "total_units": 900,
        "unit_cost_brl": Decimal("40.00"),
        "unknown_evidence": (),
    }
    values.update(overrides)
    return HistoricalSku(**values)


def test_analog_ranking_is_deterministic_and_exposes_score_components() -> None:
    catalog = (
        _sku("SYNTH-SKU-002", category="other", attributes=("portable",)),
        _sku("SYNTH-SKU-001"),
        _sku("SYNTH-SKU-003", net_price_brl=Decimal("125.00")),
    )

    first = select_analogs(_candidate(), catalog)
    second = select_analogs(_candidate(), tuple(reversed(catalog)))

    assert first == second
    assert [item.sku_id for item in first] == [
        "SYNTH-SKU-001",
        "SYNTH-SKU-003",
        "SYNTH-SKU-002",
    ]
    assert first[0].score == Decimal("1.000000")
    assert first[0].components == {
        "category_match": Decimal("1.000000"),
        "attribute_jaccard": Decimal("1.000000"),
        "price_proximity": Decimal("1.000000"),
        "launch_window_coverage": Decimal("1.000000"),
    }


def test_analog_selection_caps_at_five_and_breaks_ties_by_sku_key() -> None:
    catalog = tuple(_sku(f"SYNTH-SKU-{index:03d}") for index in range(8, 0, -1))

    selected = select_analogs(_candidate(), catalog)

    assert [item.sku_id for item in selected] == [
        "SYNTH-SKU-001",
        "SYNTH-SKU-002",
        "SYNTH-SKU-003",
        "SYNTH-SKU-004",
        "SYNTH-SKU-005",
    ]


def test_analog_selection_rejects_non_positive_planned_price() -> None:
    candidate = ProductCandidate(
        **{
            **_candidate().as_dict(),
            "planned_price_brl": Decimal("0.00"),
        }
    )

    with pytest.raises(ValueError, match="planned_net_price_invalid"):
        select_analogs(candidate, (_sku("SYNTH-SKU-001"),))
