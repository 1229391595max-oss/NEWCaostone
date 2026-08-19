"""Validated deterministic forecast API contracts."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.synthetic.boundary import (
    SyntheticSourceBoundaryError,
    validate_synthetic_records,
)

FORBIDDEN_TEXT = re.compile(
    r"(?:https?://|\b[^\s@]+@[^\s@]+\.[^\s@]+\b|sk-(?:proj-)?[A-Za-z0-9_-]{12,}|AccountKey=|-----BEGIN)",
    re.IGNORECASE,
)


def _safe_text(value: str) -> str:
    normalized = " ".join(value.strip().split())
    try:
        validate_synthetic_records(({"operator_text": normalized},))
    except SyntheticSourceBoundaryError as error:
        raise ValueError("synthetic_forecast_text_invalid") from error
    if not normalized or FORBIDDEN_TEXT.search(normalized):
        raise ValueError("synthetic_forecast_text_invalid")
    return normalized


def _safe_label(value: str) -> str:
    normalized = _safe_text(value)
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", normalized):
        raise ValueError("synthetic_forecast_label_invalid")
    return normalized


class ProductCandidateRequest(BaseModel):
    product_name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    attributes: list[str] = Field(min_length=1, max_length=20)
    planned_launch_date: date
    planned_price_brl: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    expected_discount_brl: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    unit_cost_brl: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=2,
    )
    opening_inventory_units: int = Field(ge=0, le=1_000_000)
    moq_units: int = Field(gt=0, le=1_000_000)
    lead_time_days: int = Field(gt=0, le=365)
    planned_daily_ad_brl: Decimal = Field(ge=0, max_digits=18, decimal_places=2)

    @field_validator("product_name")
    @classmethod
    def validate_product_name(cls, value: str) -> str:
        normalized = _safe_text(value)
        if not re.fullmatch(
            r"Synthetic [A-Za-z0-9][A-Za-z0-9 _-]{0,100}",
            normalized,
        ):
            raise ValueError("synthetic_product_name_required")
        return normalized

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        return _safe_label(value)

    @field_validator("attributes")
    @classmethod
    def validate_attributes(cls, values: list[str]) -> list[str]:
        normalized = sorted({_safe_label(value) for value in values})
        if not normalized:
            raise ValueError("synthetic_forecast_attributes_invalid")
        return normalized


class ForecastCreateRequest(BaseModel):
    dataset_version_id: UUID
    candidate: ProductCandidateRequest
    safety_stock_units: int = Field(ge=0, le=1_000_000)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    missing_fields: list[str] = Field(default_factory=list, max_length=20)
    scope: dict[str, object] = Field(default_factory=lambda: {"currency": "BRL"})

    @field_validator("assumptions", "missing_fields")
    @classmethod
    def validate_labels(cls, values: list[str]) -> list[str]:
        return sorted({_safe_label(value) for value in values})


class AnalogConfirmationRequest(BaseModel):
    sku_ids: list[str] = Field(min_length=1, max_length=5)

    @field_validator("sku_ids")
    @classmethod
    def validate_skus(cls, values: list[str]) -> list[str]:
        normalized = sorted({_safe_text(value) for value in values})
        if any(
            not re.fullmatch(r"SYNTH-[A-Z0-9-]{1,100}", value)
            for value in normalized
        ):
            raise ValueError("forecast_analog_selection_invalid")
        if not normalized:
            raise ValueError("forecast_analog_selection_invalid")
        return normalized


class ForecastAnalogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku_id: str
    rank: int
    score: Decimal
    components: dict[str, str]
    historical_snapshot: dict[str, object]
    confirmed: bool


class ForecastResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_version_id: UUID
    algorithm_version: str
    input_snapshot: dict[str, object]
    input_hash: str
    status: Literal["draft", "analogs_confirmed", "completed", "blocked"]
    confidence: Literal["low", "medium", "high"] | None
    assumptions: list[str]
    evidence: dict[str, object]
    result: dict[str, object] | None
    backtest: dict[str, object] | None
    analogs: tuple[ForecastAnalogResponse, ...]
    created_at: datetime
    completed_at: datetime | None
