"""Bounded request and response contracts for workspace Settings."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

KpiName = Literal[
    "net_sales", "orders", "roas", "ad_spend",
    "contribution_profit", "stockout_skus",
]


class PreferenceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: Literal["en", "zh"]
    sidebar_mode: Literal["full", "compact"]
    default_store: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    period_preset: Literal["current_month", "previous_month", "last_30_days"]
    comparison_preset: Literal["none", "previous_period", "previous_year"]
    overview_kpis: list[KpiName] = Field(min_length=2, max_length=6)
    reporting_currency: Literal["BRL", "USD"]
    timezone: Literal["America/Sao_Paulo", "America/Chicago", "UTC"]
    revision: int = Field(default=0, ge=0)

    @field_validator("overview_kpis")
    @classmethod
    def unique_kpis(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("overview_kpis_must_be_unique")
        return value


class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    preferences: PreferenceDocument


class SavedViewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: Literal["overview", "inventory", "sales", "profit", "briefing"]
    priority: Literal["P0", "P1", "P2", "Monitor", "Unavailable"] | None = None
    period_preset: Literal["current_month", "previous_month", "last_30_days"] | None = None
    comparison_preset: Literal["none", "previous_period", "previous_year"] | None = None


class SavedViewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["today", "actions"]
    config: SavedViewConfig


class SavedViewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=80)
    config: SavedViewConfig


class SavedViewResponse(BaseModel):
    id: UUID
    name: str
    kind: Literal["today", "actions"]
    config: dict[str, object]
    revision: int
    updated_at: datetime


class TargetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    revenue_brl: Decimal = Field(ge=0, le=1_000_000_000_000, decimal_places=2)
    orders: int = Field(ge=0, le=1_000_000_000)
    roas: Decimal = Field(ge=0, le=1_000_000, decimal_places=2)
    profit_brl: Decimal = Field(ge=-1_000_000_000_000, le=1_000_000_000_000, decimal_places=2)


class TargetStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    status: Literal["active", "archived"]


class TargetResponse(BaseModel):
    id: UUID
    period: str
    revenue_brl: Decimal
    orders: int
    roas: Decimal
    profit_brl: Decimal
    status: Literal["active", "archived"]
    revision: int
    updated_at: datetime


class AiConnectionStatus(BaseModel):
    status: Literal["available", "disabled", "unavailable"]
    minute_remaining: int | None = Field(default=None, ge=0)
    daily_remaining: int | None = Field(default=None, ge=0)
    limitation_code: str | None = Field(default=None, max_length=100)


class PreferencePermissions(BaseModel):
    reporting_defaults: Literal["editable", "read_only"]
    targets: Literal["editable", "read_only"]
    persistence: Literal["server", "session"]


class SettingsResponse(BaseModel):
    preferences: PreferenceDocument
    saved_views: tuple[SavedViewResponse, ...]
    targets: tuple[TargetResponse, ...]
    ai: AiConnectionStatus
    permissions: PreferencePermissions
