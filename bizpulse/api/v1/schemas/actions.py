"""Validated action-card API contracts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FactRefModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alias: str = Field(min_length=1, max_length=200)
    evidence_state: Literal["measured", "derived", "assumed", "unknown"]
    source_ref: str = Field(min_length=1, max_length=500)
    value: str | None = Field(default=None, max_length=500)


class ActionSourceRequest(BaseModel):
    source_type: Literal[
        "deterministic_rule",
        "new_product_forecast",
        "profit_bridge",
        "operating_advice",
    ]
    dataset_version_id: UUID
    suggestion: str = Field(min_length=1, max_length=1000)
    target: str = Field(min_length=1, max_length=200)
    period_start: date
    period_end: date
    scope: dict[str, object]
    quantity: Decimal | None = Field(default=None, ge=0)
    budget_brl: Decimal | None = Field(default=None, ge=0)
    action_date: date | None = None
    threshold: Decimal | None = None
    expected_impact: dict[str, str]
    confidence: Literal["low", "medium", "high"]
    limitations: tuple[str, ...] = Field(max_length=50)
    analysis_run_id: UUID | None = None
    forecast_id: UUID | None = None
    bridge_id: UUID | None = None
    chat_turn_id: UUID | None = None
    chat_tool: str | None = Field(default=None, max_length=100)
    answer_version: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_period(self):
        if self.period_start > self.period_end:
            raise ValueError("action_period_invalid")
        return self


class ActionCreateRequest(BaseModel):
    source: ActionSourceRequest
    facts: tuple[FactRefModel, ...] = Field(min_length=1, max_length=100)


class ActionAdjustmentRequest(BaseModel):
    suggestion: str | None = Field(default=None, max_length=1000)
    target: str | None = Field(default=None, max_length=200)
    quantity: Decimal | None = Field(default=None, ge=0)
    budget_brl: Decimal | None = Field(default=None, ge=0)
    action_date: date | None = None
    threshold: Decimal | None = None
    expected_impact: dict[str, str] | None = None
    confidence: Literal["low", "medium", "high"] | None = None
    limitations: tuple[str, ...] | None = Field(default=None, max_length=50)


class ActionCommandRequest(BaseModel):
    dataset_version_id: UUID
    store_ids: tuple[str, ...] = Field(default=(), max_length=1)
    revision: int = Field(ge=1)
    command: Literal["review", "adjust", "approve", "dismiss"]
    reason: str = Field(min_length=1, max_length=1000)
    adjustment: ActionAdjustmentRequest | None = None

    @model_validator(mode="after")
    def validate_adjustment(self):
        if (self.command == "adjust") != (self.adjustment is not None):
            raise ValueError("action_adjustment_invalid")
        return self


class ActionExportRequest(BaseModel):
    dataset_version_id: UUID
    store_ids: tuple[str, ...] = Field(default=(), max_length=1)
    revision: int = Field(ge=1)
    format: Literal["xlsx"] = "xlsx"


class ActionOutcomeRequest(BaseModel):
    dataset_version_id: UUID
    store_ids: tuple[str, ...] = Field(default=(), max_length=1)
    revision: int = Field(ge=1)
    review_date: date
    synthetic_result: dict[str, str]
    evidence: tuple[FactRefModel, ...] = Field(min_length=1, max_length=100)
    conclusion: Literal[
        "achieved",
        "partially_achieved",
        "not_achieved",
        "inconclusive",
    ]
    reason: str = Field(min_length=1, max_length=1000)


class DemoActionAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: Decimal | None = Field(
        default=None,
        ge=0,
        le=1_000_000,
        decimal_places=0,
    )
    budget_brl: Decimal | None = Field(
        default=None,
        ge=0,
        le=1_000_000_000,
        decimal_places=2,
    )

    def values_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=True)


class DemoActionCommandRequest(BaseModel):
    store_ids: tuple[str, ...] = Field(default=(), max_length=1)
    base_revision: int = Field(ge=1)
    command: Literal["review", "adjust", "approve", "dismiss"]
    reason: str = Field(min_length=1, max_length=1000)
    adjustment: DemoActionAdjustmentRequest | None = None

    @model_validator(mode="after")
    def validate_adjustment_bounds(self):
        values = self.adjustment.values_dict() if self.adjustment is not None else {}
        if (self.command == "adjust") != bool(values):
            raise ValueError("demo_action_adjustment_invalid")
        if len(
            json.dumps(values, separators=(",", ":")).encode()
        ) > 16_384:
            raise ValueError("demo_action_adjustment_too_large")
        return self


class ActionSimulationInputsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    unit_cost_brl: Decimal | None
    precomputed_daily_velocity: Decimal | None
    baseline_budget_brl: Decimal | None
    currency: Literal["BRL"]


class ActionRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    revision: int
    suggestion: str
    target: str
    period_start: date
    period_end: date
    scope: dict[str, object]
    quantity: Decimal | None
    budget_brl: Decimal | None
    action_date: date | None
    threshold: Decimal | None
    expected_impact: dict[str, str]
    confidence: Literal["low", "medium", "high"]
    limitations: tuple[str, ...]
    facts: tuple[FactRefModel, ...]
    analysis_run_id: UUID | None
    forecast_id: UUID | None
    bridge_id: UUID | None
    chat_turn_id: UUID | None
    chat_tool: str | None
    answer_version: str | None
    created_at: datetime


class ActionDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    decision_ordinal: int
    command: Literal["review", "adjust", "approve", "dismiss"]
    action_revision: int
    reason: str
    decided_by: str
    created_at: datetime


class ActionExportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    action_id: UUID
    action_revision: int
    status: Literal["available"]
    format: Literal["xlsx"]
    sha256: str
    note: Literal["Not sent to an external platform"]
    exported_by: str
    created_at: datetime


class ActionOutcomeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    action_id: UUID
    action_revision: int
    outcome_revision: int
    review_date: date
    synthetic_result: dict[str, str]
    evidence: tuple[FactRefModel, ...]
    conclusion: Literal[
        "achieved",
        "partially_achieved",
        "not_achieved",
        "inconclusive",
    ]
    reason: str
    reviewed_by: str
    created_at: datetime


class ActionCardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: str
    dataset_version_id: UUID
    source_type: str
    status: Literal["new", "reviewed", "approved", "dismissed"]
    current_revision: int
    revisions: tuple[ActionRevisionResponse, ...]
    simulation_inputs: ActionSimulationInputsResponse | None = None
    decisions: tuple[ActionDecisionResponse, ...]
    exports: tuple[ActionExportResponse, ...]
    outcomes: tuple[ActionOutcomeResponse, ...]
    created_at: datetime
    updated_at: datetime
    terminal_at: datetime | None


class ActionListResponse(BaseModel):
    items: tuple[ActionCardResponse, ...]


class DemoActionOverlayResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    demo_session_id: UUID
    action_id: UUID
    base_revision: int
    overlay_revision: int
    command: Literal["review", "adjust", "approve", "dismiss"]
    status: Literal["reviewed", "approved", "dismissed"]
    adjustment: dict[str, object]
    reason: str
    created_at: datetime


class DemoActionOverlayListResponse(BaseModel):
    items: tuple[DemoActionOverlayResponse, ...]


class DemoActionSandboxResetResponse(BaseModel):
    deleted_overlays: int = Field(ge=0)
