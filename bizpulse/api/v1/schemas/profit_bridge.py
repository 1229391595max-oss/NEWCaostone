"""Validated Profit Bridge API contracts."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProfitPeriodRequest(BaseModel):
    period_start: date
    period_end: date


class ProfitBridgeScopeRequest(BaseModel):
    currency: Literal["BRL"]
    store_id: str | None = Field(default=None, max_length=100)
    sku_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("store_id")
    @classmethod
    def validate_store_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"SYNTH-[A-Z0-9-]{1,94}", value):
            raise ValueError("profit_bridge_store_invalid")
        return value

    @field_validator("sku_ids")
    @classmethod
    def validate_sku_ids(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = sorted(set(values))
        if not normalized or any(
            not re.fullmatch(r"SYNTH-[A-Z0-9-]{1,94}", value)
            for value in normalized
        ):
            raise ValueError("profit_bridge_sku_invalid")
        return normalized


class ProfitBridgeRunRequest(BaseModel):
    dataset_version_id: UUID
    current_period: ProfitPeriodRequest
    comparison_period: ProfitPeriodRequest
    scope: ProfitBridgeScopeRequest


class ProfitBridgeItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    driver: str
    ordinal: int
    amount_brl: Decimal | None
    evidence_state: Literal["measured", "derived", "assumed", "unknown"]
    formula: str
    source_refs: tuple[str, ...]


class ProfitBridgeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_version_id: UUID
    baseline_analysis_id: UUID
    current_analysis_id: UUID
    formula_version: str
    scope: dict[str, object]
    baseline_period: tuple[date, date]
    current_period: tuple[date, date]
    baseline_contribution_profit_brl: Decimal | None
    current_contribution_profit_brl: Decimal | None
    total_delta_brl: Decimal | None
    residual_brl: Decimal | None
    reconciled: bool
    shared_costs_unallocated: bool
    limitations: tuple[str, ...]
    items: tuple[ProfitBridgeItemResponse, ...]
    created_at: datetime
