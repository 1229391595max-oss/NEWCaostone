"""Hidden-window deterministic forecast evaluation for the synthetic Demo."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, ROUND_HALF_UP

from src.forecast.contracts import BacktestResult, BacktestWindow
from src.forecast.new_product import forecast_new_product

SIX_PLACES = Decimal("0.000001")
TWO_PLACES = Decimal("0.01")


def backtest_hidden_windows(
    windows: Sequence[BacktestWindow],
) -> BacktestResult:
    if not windows:
        raise ValueError("backtest_windows_missing")
    absolute_errors: list[Decimal] = []
    actual_total = Decimal("0")
    covered = 0
    repeat = True
    sensitivities: list[Decimal] = []
    case_count = 0
    for window in sorted(windows, key=lambda item: item.window_id):
        first = forecast_new_product(window.request, window.confirmed_analogs)
        second = forecast_new_product(window.request, window.confirmed_analogs)
        repeat = repeat and first == second
        if first.confidence == "low":
            raise ValueError("backtest_window_insufficient_evidence")
        for horizon in sorted(window.actual_units):
            if horizon not in first.by_horizon or window.actual_units[horizon] < 0:
                raise ValueError("backtest_actual_invalid")
            actual = Decimal(window.actual_units[horizon])
            forecast = first.by_horizon[horizon]
            base = Decimal(forecast.units["base"])
            absolute_errors.append(abs(base - actual))
            actual_total += actual
            covered += int(
                forecast.units["low"] <= actual <= forecast.units["high"]
            )
            case_count += 1
        if len(window.confirmed_analogs) >= 3:
            for omitted in window.confirmed_analogs:
                remaining = tuple(
                    item
                    for item in window.confirmed_analogs
                    if item.sku_id != omitted.sku_id
                )
                alternative = forecast_new_product(window.request, remaining)
                if alternative.confidence == "low":
                    continue
                for horizon in sorted(window.actual_units):
                    base = Decimal(first.by_horizon[horizon].units["base"])
                    alternative_base = Decimal(
                        alternative.by_horizon[horizon].units["base"]
                    )
                    sensitivities.append(
                        abs(alternative_base - base) / max(base, Decimal("1"))
                    )
    if case_count == 0:
        raise ValueError("backtest_actual_missing")
    total_error = sum(absolute_errors, Decimal("0"))
    limitations: list[str] = []
    if actual_total == 0:
        limitations.append("wape_undefined_zero_actual_total")
    return BacktestResult(
        case_count=case_count,
        mae_units=(total_error / Decimal(case_count)).quantize(
            TWO_PLACES,
            rounding=ROUND_HALF_UP,
        ),
        wape=(
            (total_error / actual_total).quantize(
                SIX_PLACES,
                rounding=ROUND_HALF_UP,
            )
            if actual_total > 0
            else None
        ),
        interval_coverage=(Decimal(covered) / Decimal(case_count)).quantize(
            SIX_PLACES,
            rounding=ROUND_HALF_UP,
        ),
        analog_sensitivity=max(sensitivities, default=Decimal("0")).quantize(
            SIX_PLACES,
            rounding=ROUND_HALF_UP,
        ),
        exact_repeat=repeat,
        synthetic_demo_only=True,
        evidence={
            "cutoff": "history_before_synthetic_launch",
            "source_classification": "pure_synthetic",
            "claim_boundary": "synthetic_demo_behavior_not_market_accuracy",
            "limitations": limitations,
        },
    )
