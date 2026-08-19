"""Immutable contracts for deterministic new-product forecasting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

Confidence = Literal["low", "medium", "high"]
ScenarioName = Literal["low", "base", "high"]


@dataclass(frozen=True, slots=True)
class ProductCandidate:
    product_name: str
    category: str
    attributes: tuple[str, ...]
    planned_launch_date: date
    planned_price_brl: Decimal
    expected_discount_brl: Decimal
    unit_cost_brl: Decimal | None
    opening_inventory_units: int
    moq_units: int
    lead_time_days: int
    planned_daily_ad_brl: Decimal

    @property
    def planned_net_price_brl(self) -> Decimal:
        return self.planned_price_brl - self.expected_discount_brl

    def as_dict(self) -> dict[str, object]:
        """Return constructor-compatible values for explicit deterministic copies."""

        return {
            "product_name": self.product_name,
            "category": self.category,
            "attributes": self.attributes,
            "planned_launch_date": self.planned_launch_date,
            "planned_price_brl": self.planned_price_brl,
            "expected_discount_brl": self.expected_discount_brl,
            "unit_cost_brl": self.unit_cost_brl,
            "opening_inventory_units": self.opening_inventory_units,
            "moq_units": self.moq_units,
            "lead_time_days": self.lead_time_days,
            "planned_daily_ad_brl": self.planned_daily_ad_brl,
        }


@dataclass(frozen=True, slots=True)
class HistoricalSku:
    sku_id: str
    category: str
    attributes: tuple[str, ...]
    net_price_brl: Decimal
    daily_ad_spend_brl: Decimal | None
    history_days: int
    total_units: int
    unit_cost_brl: Decimal | None
    unknown_evidence: tuple[str, ...]

    @property
    def daily_units(self) -> Decimal:
        if self.history_days <= 0:
            return Decimal("0")
        return Decimal(self.total_units) / Decimal(self.history_days)


@dataclass(frozen=True, slots=True)
class Analog:
    historical: HistoricalSku
    score: Decimal
    components: dict[str, Decimal]

    @property
    def sku_id(self) -> str:
        return self.historical.sku_id


@dataclass(frozen=True, slots=True)
class ForecastRequest:
    candidate: ProductCandidate
    safety_stock_units: int
    assumptions: tuple[str, ...]
    missing_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HorizonForecast:
    horizon_days: int
    units: dict[ScenarioName, int]
    revenue_brl: dict[ScenarioName, Decimal]
    contribution_profit_brl: dict[ScenarioName, Decimal | None]
    stock_cover_days: dict[ScenarioName, Decimal | None]


@dataclass(frozen=True, slots=True)
class ForecastResult:
    algorithm_version: str
    confidence: Confidence
    confidence_reasons: tuple[str, ...]
    by_horizon: dict[int, HorizonForecast]
    recommended_first_order_units: int | None
    moq_compliant_first_order_units: int | None
    factors: dict[str, Decimal]
    assumptions: tuple[str, ...]
    missing_fields: tuple[str, ...]
    limitations: tuple[str, ...]
    evidence: dict[str, object]


@dataclass(frozen=True, slots=True)
class BacktestWindow:
    window_id: str
    request: ForecastRequest
    confirmed_analogs: tuple[Analog, ...]
    actual_units: dict[int, int]


@dataclass(frozen=True, slots=True)
class BacktestResult:
    case_count: int
    mae_units: Decimal
    wape: Decimal | None
    interval_coverage: Decimal
    analog_sensitivity: Decimal
    exact_repeat: bool
    synthetic_demo_only: bool
    evidence: dict[str, object]
