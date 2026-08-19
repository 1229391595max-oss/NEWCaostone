from datetime import date
from decimal import Decimal

from src.forecast.backtest import backtest_hidden_windows
from src.forecast.contracts import (
    Analog,
    BacktestWindow,
    ForecastRequest,
    HistoricalSku,
    ProductCandidate,
)


def _window(*, actual_units: dict[int, int] | None = None) -> BacktestWindow:
    candidate = ProductCandidate(
        product_name="Synthetic Hidden Launch",
        category="travel_bag",
        attributes=("portable",),
        planned_launch_date=date(2026, 7, 1),
        planned_price_brl=Decimal("100"),
        expected_discount_brl=Decimal("0"),
        unit_cost_brl=Decimal("40"),
        opening_inventory_units=100,
        moq_units=20,
        lead_time_days=15,
        planned_daily_ad_brl=Decimal("10"),
    )
    analogs = tuple(
        Analog(
            historical=HistoricalSku(
                sku_id=f"SYNTH-SKU-{index:03d}",
                category="travel_bag",
                attributes=("portable",),
                net_price_brl=Decimal("100"),
                daily_ad_spend_brl=Decimal("10"),
                history_days=90,
                total_units=900 + index * 9,
                unit_cost_brl=Decimal("40"),
                unknown_evidence=(),
            ),
            score=Decimal("1.000000"),
            components={},
        )
        for index in range(1, 4)
    )
    return BacktestWindow(
        window_id="synthetic-hidden-001",
        request=ForecastRequest(
            candidate=candidate,
            safety_stock_units=20,
            assumptions=("hidden_before_launch",),
            missing_fields=(),
        ),
        confirmed_analogs=analogs,
        actual_units=actual_units or {7: 47, 30: 275, 90: 910},
    )


def test_hidden_window_backtest_reports_repeat_coverage_and_sensitivity() -> None:
    first = backtest_hidden_windows((_window(),))
    second = backtest_hidden_windows((_window(),))

    assert first == second
    assert first.exact_repeat is True
    assert first.synthetic_demo_only is True
    assert first.case_count == 3
    assert first.mae_units >= Decimal("0")
    assert first.wape >= Decimal("0")
    assert Decimal("0") <= first.interval_coverage <= Decimal("1")
    assert first.analog_sensitivity >= Decimal("0")
    assert first.evidence["cutoff"] == "history_before_synthetic_launch"


def test_zero_actual_total_keeps_wape_unknown_instead_of_perfect_zero() -> None:
    result = backtest_hidden_windows(
        (_window(actual_units={7: 0, 30: 0, 90: 0}),)
    )

    assert result.wape is None
    assert "wape_undefined_zero_actual_total" in result.evidence["limitations"]
