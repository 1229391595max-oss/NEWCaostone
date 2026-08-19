from datetime import date
from decimal import Decimal

import pytest

from src.forecast.contracts import (
    Analog,
    ForecastRequest,
    HistoricalSku,
    ProductCandidate,
)
from src.forecast.new_product import ForecastBlocked, forecast_new_product


def _candidate(**overrides) -> ProductCandidate:
    values = {
        "product_name": "Synthetic Travel Organizer",
        "category": "travel_bag",
        "attributes": ("portable", "zippered"),
        "planned_launch_date": date(2026, 8, 20),
        "planned_price_brl": Decimal("100.00"),
        "expected_discount_brl": Decimal("0.00"),
        "unit_cost_brl": Decimal("40.00"),
        "opening_inventory_units": 50,
        "moq_units": 24,
        "lead_time_days": 20,
        "planned_daily_ad_brl": Decimal("10.00"),
    }
    values.update(overrides)
    return ProductCandidate(**values)


def _analog(sku_id: str, **overrides) -> Analog:
    historical = {
        "sku_id": sku_id,
        "category": "travel_bag",
        "attributes": ("portable", "zippered"),
        "net_price_brl": Decimal("100.00"),
        "daily_ad_spend_brl": Decimal("10.00"),
        "history_days": 30,
        "total_units": 300,
        "unit_cost_brl": Decimal("40.00"),
        "unknown_evidence": (),
    }
    historical.update(overrides)
    return Analog(
        historical=HistoricalSku(**historical),
        score=Decimal("1.000000"),
        components={
            "category_match": Decimal("1.000000"),
            "attribute_jaccard": Decimal("1.000000"),
            "price_proximity": Decimal("1.000000"),
            "launch_window_coverage": Decimal("0.333333"),
        },
    )


def _request(**overrides) -> ForecastRequest:
    values = {
        "candidate": _candidate(),
        "safety_stock_units": 20,
        "assumptions": ("pure_synthetic_history",),
        "missing_fields": (),
    }
    values.update(overrides)
    return ForecastRequest(**values)


def test_forecast_is_reproducible_ordered_and_uses_exact_medium_multipliers() -> None:
    analogs = (_analog("SYNTH-SKU-001"), _analog("SYNTH-SKU-002"))

    first = forecast_new_product(_request(), analogs)
    second = forecast_new_product(_request(), tuple(reversed(analogs)))

    assert first == second
    assert first.confidence == "medium"
    assert first.by_horizon[7].units == {"low": 27, "base": 46, "high": 64}
    assert first.by_horizon[30].units == {"low": 162, "base": 270, "high": 378}
    assert first.by_horizon[90].units == {"low": 540, "base": 900, "high": 1260}
    for horizon in (7, 30, 90):
        result = first.by_horizon[horizon]
        assert result.units["low"] <= result.units["base"] <= result.units["high"]
        assert result.revenue_brl["base"] == Decimal(result.units["base"] * 100)
        assert result.contribution_profit_brl["base"] is not None
    assert first.recommended_first_order_units == 348
    assert first.moq_compliant_first_order_units == 360
    assert first.evidence["algorithm_version"] == "new_product_forecast.v1"


def test_low_evidence_never_returns_precise_scenarios() -> None:
    result = forecast_new_product(_request(), (_analog("SYNTH-SKU-001"),))

    assert result.confidence == "low"
    assert result.by_horizon == {}
    assert result.recommended_first_order_units is None
    assert "insufficient_complete_analogs" in result.limitations


def test_positive_ad_plan_with_zero_analog_baseline_is_blocked() -> None:
    analogs = (
        _analog("SYNTH-SKU-001", daily_ad_spend_brl=Decimal("0")),
        _analog("SYNTH-SKU-002", daily_ad_spend_brl=Decimal("0")),
    )

    with pytest.raises(ForecastBlocked, match="analog_ad_baseline_missing"):
        forecast_new_product(_request(), analogs)


def test_zero_planned_and_analog_ad_uses_neutral_factor() -> None:
    analogs = (
        _analog("SYNTH-SKU-001", daily_ad_spend_brl=Decimal("0")),
        _analog("SYNTH-SKU-002", daily_ad_spend_brl=Decimal("0")),
    )

    result = forecast_new_product(
        _request(candidate=_candidate(planned_daily_ad_brl=Decimal("0"))),
        analogs,
    )

    assert result.factors["advertising"] == Decimal("1.000000")


def test_missing_cost_keeps_profit_unknown_instead_of_zero() -> None:
    result = forecast_new_product(
        _request(candidate=_candidate(unit_cost_brl=None), missing_fields=("unit_cost_brl",)),
        (_analog("SYNTH-SKU-001"), _analog("SYNTH-SKU-002")),
    )

    assert result.confidence == "medium"
    assert result.by_horizon[30].contribution_profit_brl == {
        "low": None,
        "base": None,
        "high": None,
    }
    assert "contribution_profit_unavailable" in result.limitations


def test_missing_candidate_cost_cannot_receive_high_confidence() -> None:
    analogs = tuple(
        _analog(
            f"SYNTH-SKU-{index:03d}",
            history_days=90,
            total_units=900,
        )
        for index in range(1, 4)
    )

    result = forecast_new_product(
        _request(candidate=_candidate(unit_cost_brl=None), missing_fields=()),
        analogs,
    )

    assert result.confidence == "medium"
    assert result.by_horizon[90].contribution_profit_brl["base"] is None
    assert "unit_cost_brl" in result.missing_fields


def test_non_positive_net_price_is_rejected() -> None:
    with pytest.raises(ForecastBlocked, match="planned_net_price_invalid"):
        forecast_new_product(
            _request(
                candidate=_candidate(
                    planned_price_brl=Decimal("10"),
                    expected_discount_brl=Decimal("10"),
                )
            ),
            (_analog("SYNTH-SKU-001"), _analog("SYNTH-SKU-002")),
        )


@pytest.mark.parametrize(
    ("lead_time_days", "expected_horizon"),
    ((45, 45), (60, 60), (120, 90)),
)
def test_first_order_uses_the_exact_clamped_lead_time_horizon(
    lead_time_days: int,
    expected_horizon: int,
) -> None:
    result = forecast_new_product(
        _request(candidate=_candidate(lead_time_days=lead_time_days)),
        (_analog("SYNTH-SKU-001"), _analog("SYNTH-SKU-002")),
    )

    assert result.evidence["first_order_horizon_days"] == expected_horizon
    if lead_time_days == 120:
        assert "lead_time_capped_at_90_days" in result.limitations


def test_unquantized_factors_drive_final_half_up_unit_rounding() -> None:
    analogs = (
        _analog("SYNTH-SKU-001", total_units=3_000_000),
        _analog("SYNTH-SKU-002", total_units=3_000_000),
    )

    result = forecast_new_product(
        _request(
            candidate=_candidate(
                planned_price_brl=Decimal("101.00"),
                expected_discount_brl=Decimal("0"),
            )
        ),
        analogs,
    )

    assert result.by_horizon[90].units["high"] == 12_450_446
    assert result.factors["price"] == Decimal("0.988131")
    assert result.evidence["factor_precision"] == (
        "unquantized_decimal_internal_6dp_display"
    )
