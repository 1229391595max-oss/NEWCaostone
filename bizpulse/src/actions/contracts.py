"""Validated immutable action-card values."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Mapping
from uuid import UUID

EvidenceState = Literal["measured", "derived", "assumed", "unknown"]
Confidence = Literal["low", "medium", "high"]
SourceType = Literal[
    "deterministic_rule",
    "new_product_forecast",
    "profit_bridge",
    "operating_advice",
    "chat_box_draft",
]


@dataclass(frozen=True, slots=True)
class ActionSimulationInputs:
    unit_cost_brl: Decimal | None
    precomputed_daily_velocity: Decimal | None
    baseline_budget_brl: Decimal | None
    currency: Literal["BRL"] = "BRL"


@dataclass(frozen=True, slots=True)
class FactRef:
    alias: str
    evidence_state: EvidenceState
    source_ref: str
    value: str | None


@dataclass(frozen=True, slots=True)
class ActionSource:
    source_type: SourceType
    dataset_version_id: UUID
    suggestion: str
    target: str
    period_start: date
    period_end: date
    scope: Mapping[str, object]
    quantity: Decimal | None
    budget_brl: Decimal | None
    action_date: date | None
    threshold: Decimal | None
    expected_impact: Mapping[str, str]
    confidence: Confidence
    limitations: tuple[str, ...]
    analysis_run_id: UUID | None
    forecast_id: UUID | None
    bridge_id: UUID | None
    chat_turn_id: UUID | None
    chat_tool: str | None
    answer_version: str | None


@dataclass(frozen=True, slots=True)
class ActionAdjustment:
    suggestion: str | None = None
    target: str | None = None
    quantity: Decimal | None = None
    budget_brl: Decimal | None = None
    action_date: date | None = None
    threshold: Decimal | None = None
    expected_impact: Mapping[str, str] | None = None
    confidence: Confidence | None = None
    limitations: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class ActionRevision:
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
    confidence: Confidence
    limitations: tuple[str, ...]
    facts: tuple[FactRef, ...]
    analysis_run_id: UUID | None
    forecast_id: UUID | None
    bridge_id: UUID | None
    chat_turn_id: UUID | None
    chat_tool: str | None
    answer_version: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ActionDecision:
    id: UUID
    decision_ordinal: int
    command: Literal["review", "adjust", "approve", "dismiss"]
    action_revision: int
    reason: str
    decided_by: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ActionExport:
    id: UUID
    action_id: UUID
    action_revision: int
    status: Literal["available"]
    format: Literal["xlsx"]
    storage_object_id: UUID | None
    sha256: str
    note: Literal["Not sent to an external platform"]
    exported_by: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    id: UUID
    action_id: UUID
    action_revision: int
    outcome_revision: int
    review_date: date
    synthetic_result: dict[str, str]
    evidence: tuple[FactRef, ...]
    conclusion: Literal["achieved", "partially_achieved", "not_achieved", "inconclusive"]
    reason: str
    reviewed_by: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ActionCard:
    id: UUID
    workspace_id: str
    dataset_version_id: UUID
    source_type: SourceType
    status: Literal["new", "reviewed", "approved", "dismissed"]
    current_revision: int
    revisions: tuple[ActionRevision, ...]
    simulation_inputs: ActionSimulationInputs | None = None
    decisions: tuple[ActionDecision, ...] = field(default_factory=tuple)
    exports: tuple[ActionExport, ...] = field(default_factory=tuple)
    outcomes: tuple[ActionOutcome, ...] = field(default_factory=tuple)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    terminal_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DemoActionOverlay:
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
