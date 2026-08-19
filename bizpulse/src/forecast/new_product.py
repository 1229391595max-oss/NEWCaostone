"""Exact deterministic 7/30/90-day forecast formulas."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP, localcontext

from src.forecast.contracts import (
    Analog,
    ForecastRequest,
    ForecastResult,
    HorizonForecast,
)

ALGORITHM_VERSION = "new_product_forecast.v1"
HORIZONS = (7, 30, 90)
LAUNCH_RAMP = {
    7: Decimal("0.65"),
    30: Decimal("0.90"),
    90: Decimal("1.00"),
}
SCENARIO_MULTIPLIERS = {
    "high": {
        "low": Decimal("0.70"),
        "base": Decimal("1.00"),
        "high": Decimal("1.30"),
    },
    "medium": {
        "low": Decimal("0.60"),
        "base": Decimal("1.00"),
        "high": Decimal("1.40"),
    },
}
SIX_PLACES = Decimal("0.000001")
MONEY = Decimal("0.01")
TWO_PLACES = Decimal("0.01")


class ForecastBlocked(ValueError):
    """The available confirmed evidence cannot support the requested output."""


def forecast_new_product(
    request: ForecastRequest,
    confirmed_analogs: Sequence[Analog],
) -> ForecastResult:
    analogs = tuple(sorted(confirmed_analogs, key=lambda item: item.sku_id))
    _validate_request(request, analogs)
    confidence, reasons = _confidence(request, analogs)
    assumptions = tuple(sorted(set(request.assumptions)))
    missing = set(request.missing_fields)
    if request.candidate.unit_cost_brl is None:
        missing.add("unit_cost_brl")
    missing_fields = tuple(sorted(missing))
    if confidence == "low":
        return ForecastResult(
            algorithm_version=ALGORITHM_VERSION,
            confidence="low",
            confidence_reasons=reasons,
            by_horizon={},
            recommended_first_order_units=None,
            moq_compliant_first_order_units=None,
            factors={},
            assumptions=assumptions,
            missing_fields=missing_fields,
            limitations=("insufficient_complete_analogs",),
            evidence={
                "algorithm_version": ALGORITHM_VERSION,
                "analog_sku_ids": [item.sku_id for item in analogs],
                "source_classification": "pure_synthetic",
            },
        )

    total_weight = sum((item.score for item in analogs), Decimal("0"))
    if total_weight <= 0:
        raise ForecastBlocked("analog_weight_invalid")
    daily_demand = _weighted(
        analogs,
        (item.historical.daily_units for item in analogs),
        total_weight,
    )
    weighted_price = _weighted(
        analogs,
        (item.historical.net_price_brl for item in analogs),
        total_weight,
    )
    if weighted_price <= 0:
        raise ForecastBlocked("weighted_analog_net_price_invalid")
    ad_values = tuple(item.historical.daily_ad_spend_brl for item in analogs)
    if any(value is None for value in ad_values):
        raise ForecastBlocked("analog_ad_baseline_missing")
    weighted_ad = _weighted(
        analogs,
        (value for value in ad_values if value is not None),
        total_weight,
    )
    planned_net_price = request.candidate.planned_net_price_brl
    if planned_net_price <= 0:
        raise ForecastBlocked("planned_net_price_invalid")
    price_factor = _price_factor(planned_net_price, weighted_price)
    advertising_factor = _advertising_factor(
        request.candidate.planned_daily_ad_brl,
        weighted_ad,
    )
    factors = {
        "daily_analog_demand": daily_demand.quantize(
            SIX_PLACES,
            rounding=ROUND_HALF_UP,
        ),
        "weighted_analog_net_price": weighted_price.quantize(
            SIX_PLACES,
            rounding=ROUND_HALF_UP,
        ),
        "weighted_analog_daily_ad": weighted_ad.quantize(
            SIX_PLACES,
            rounding=ROUND_HALF_UP,
        ),
        "price": price_factor.quantize(SIX_PLACES, rounding=ROUND_HALF_UP),
        "advertising": advertising_factor.quantize(
            SIX_PLACES,
            rounding=ROUND_HALF_UP,
        ),
    }
    multipliers = SCENARIO_MULTIPLIERS[confidence]
    by_horizon: dict[int, HorizonForecast] = {}
    limitations: list[str] = []
    if request.candidate.unit_cost_brl is None:
        limitations.append("contribution_profit_unavailable")
    for horizon in HORIZONS:
        raw_base = (
            daily_demand
            * Decimal(horizon)
            * LAUNCH_RAMP[horizon]
            * price_factor
            * advertising_factor
        )
        units = {
            scenario: _whole_units(raw_base * multiplier)
            for scenario, multiplier in multipliers.items()
        }
        revenue = {
            scenario: (Decimal(value) * planned_net_price).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )
            for scenario, value in units.items()
        }
        profit = {
            scenario: _contribution_profit(
                value,
                horizon,
                planned_net_price,
                request,
            )
            for scenario, value in units.items()
        }
        cover = {
            scenario: _stock_cover(
                request.candidate.opening_inventory_units,
                value,
                horizon,
            )
            for scenario, value in units.items()
        }
        by_horizon[horizon] = HorizonForecast(
            horizon_days=horizon,
            units=units,
            revenue_brl=revenue,
            contribution_profit_brl=profit,
            stock_cover_days=cover,
        )
    guidance_horizon = min(90, max(30, request.candidate.lead_time_days))
    if request.candidate.lead_time_days > 90:
        limitations.append("lead_time_capped_at_90_days")
    guidance_assumptions: tuple[str, ...] = ()
    if guidance_horizon in by_horizon:
        high_units = by_horizon[guidance_horizon].units["high"]
    else:
        high_units = _whole_units(
            Decimal(by_horizon[30].units["high"])
            + (
                Decimal(by_horizon[90].units["high"])
                - Decimal(by_horizon[30].units["high"])
            )
            * Decimal(guidance_horizon - 30)
            / Decimal(60)
        )
        guidance_assumptions = (
            "first_order_high_units_linearly_interpolated_30_90",
        )
    recommended = max(
        0,
        high_units
        + request.safety_stock_units
        - request.candidate.opening_inventory_units,
    )
    moq_compliant = _round_to_moq(recommended, request.candidate.moq_units)
    return ForecastResult(
        algorithm_version=ALGORITHM_VERSION,
        confidence=confidence,
        confidence_reasons=reasons,
        by_horizon=by_horizon,
        recommended_first_order_units=recommended,
        moq_compliant_first_order_units=moq_compliant,
        factors=factors,
        assumptions=tuple(sorted(set((*assumptions, *guidance_assumptions)))),
        missing_fields=missing_fields,
        limitations=tuple(sorted(set(limitations))),
        evidence={
            "algorithm_version": ALGORITHM_VERSION,
            "analog_sku_ids": [item.sku_id for item in analogs],
            "analog_scores": {
                item.sku_id: str(item.score) for item in analogs
            },
            "formula": (
                "weighted_daily_units*horizon*launch_ramp*price_factor*ad_factor"
            ),
            "first_order_horizon_days": guidance_horizon,
            "first_order_horizon_method": (
                "approved_horizon"
                if not guidance_assumptions
                else "linear_interpolation_of_approved_30_90_high_units"
            ),
            "factor_precision": "unquantized_decimal_internal_6dp_display",
            "source_classification": "pure_synthetic",
        },
    )


def _validate_request(request: ForecastRequest, analogs: tuple[Analog, ...]) -> None:
    candidate = request.candidate
    if len({item.sku_id for item in analogs}) != len(analogs):
        raise ForecastBlocked("confirmed_analog_duplicate")
    if not analogs:
        raise ForecastBlocked("confirmed_analogs_missing")
    if (
        candidate.opening_inventory_units < 0
        or candidate.moq_units <= 0
        or candidate.lead_time_days <= 0
        or request.safety_stock_units < 0
        or candidate.planned_daily_ad_brl < 0
    ):
        raise ForecastBlocked("forecast_input_invalid")


def _confidence(
    request: ForecastRequest,
    analogs: tuple[Analog, ...],
) -> tuple[str, tuple[str, ...]]:
    history_days = min((item.historical.history_days for item in analogs), default=0)
    all_costs = request.candidate.unit_cost_brl is not None and all(
        item.historical.unit_cost_brl is not None for item in analogs
    )
    no_unknown = all(not item.historical.unknown_evidence for item in analogs)
    if len(analogs) >= 3 and history_days >= 90 and all_costs and no_unknown:
        return "high", (
            "at_least_three_confirmed_analogs",
            "ninety_complete_days",
            "cost_fields_complete",
            "no_unknown_analog_evidence",
        )
    if len(analogs) >= 2 and history_days >= 30:
        return "medium", (
            "at_least_two_confirmed_analogs",
            "thirty_complete_days",
        )
    return "low", ("fewer_than_two_30_day_confirmed_analogs",)


def _weighted(
    analogs: tuple[Analog, ...],
    values,
    total_weight: Decimal,
) -> Decimal:
    return sum(
        (item.score * value for item, value in zip(analogs, values, strict=True)),
        Decimal("0"),
    ) / total_weight


def _price_factor(planned: Decimal, weighted: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 32
        raw = (planned / weighted) ** Decimal("-1.2")
    return min(Decimal("1.40"), max(Decimal("0.60"), raw))


def _advertising_factor(planned: Decimal, weighted: Decimal) -> Decimal:
    if planned == 0 and weighted == 0:
        return Decimal("1.000000")
    if weighted == 0:
        raise ForecastBlocked("analog_ad_baseline_missing")
    raw = Decimal("1") + Decimal("0.15") * (planned / weighted - Decimal("1"))
    return min(Decimal("1.20"), max(Decimal("0.80"), raw))


def _whole_units(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _contribution_profit(
    units: int,
    horizon: int,
    planned_net_price: Decimal,
    request: ForecastRequest,
) -> Decimal | None:
    unit_cost = request.candidate.unit_cost_brl
    if unit_cost is None:
        return None
    return (
        Decimal(units) * (planned_net_price - unit_cost)
        - request.candidate.planned_daily_ad_brl * Decimal(horizon)
    ).quantize(MONEY, rounding=ROUND_HALF_UP)


def _stock_cover(opening_inventory: int, units: int, horizon: int) -> Decimal | None:
    if units <= 0:
        return None
    return (Decimal(opening_inventory) * Decimal(horizon) / Decimal(units)).quantize(
        TWO_PLACES,
        rounding=ROUND_HALF_UP,
    )


def _round_to_moq(quantity: int, moq: int) -> int:
    if quantity <= 0:
        return 0
    multiples = (Decimal(quantity) / Decimal(moq)).to_integral_value(
        rounding=ROUND_CEILING
    )
    return int(multiples) * moq
