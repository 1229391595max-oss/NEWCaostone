"""Bounded public contracts for Ask BizPulse turns."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "inventory_analysis",
        "profit_bridge",
        "forecast",
        "action_cards",
    ]
    reference: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_exact_pinned_reference(self):
        expected = {
            "inventory_analysis": "inventory_analysis:pinned",
            "profit_bridge": "profit_bridge:pinned",
            "forecast": "forecast:pinned",
            "action_cards": "action_cards:pinned",
        }
        if self.reference != expected[self.kind]:
            raise ValueError("chat_context_invalid")
        return self


class ChatTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2_000)
    store_ids: tuple[str, ...] = Field(default=(), max_length=1)
    recommended_question_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    prompt_locale: Literal["en", "zh"] | None = None
    prompt_template_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    prompt_template_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    context: ChatContextRequest | None = None

    @model_validator(mode="after")
    def require_complete_preset_audit(self):
        values = (
            self.recommended_question_id,
            self.prompt_locale,
            self.prompt_template_version,
            self.prompt_template_sha256,
        )
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError("prompt_preset_contract_invalid")
        return self


class ChatScopeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dataset_version_id: UUID
    store_ids: tuple[str, ...]
    period_start: date
    period_end: date
    currency: Literal["BRL"]


class ChatFactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fact_ref: str
    label: str
    value: str | None
    evidence_state: Literal["measured", "derived", "assumed", "unknown"]
    evidence_refs: tuple[str, ...]


class ChatAnswerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    turn_id: UUID
    status: Literal[
        "answered",
        "clarification_required",
        "unsupported",
        "failed",
    ]
    answer: str
    scope: ChatScopeResponse
    facts: tuple[ChatFactResponse, ...]
    limitations: tuple[str, ...]
    suggested_questions: tuple[str, ...]
    action_card_draft_eligible: bool


class ProviderAttemptAuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: Literal["planning", "answering"]
    status: Literal["started", "succeeded", "failed", "outcome_unknown"]
    reserved_tokens: int = Field(ge=1)
    error_code: str | None


class ProviderAuditResponse(BaseModel):
    attempt_count: int = Field(ge=0, le=2)
    ledger_attempt_count: int = Field(ge=0, le=2)
    reserved_tokens: int = Field(ge=0)
    ledger_reserved_tokens: int = Field(ge=0)
    attempts: tuple[ProviderAttemptAuditResponse, ...]


class ChatTurnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    turn_sequence: int = Field(ge=1)
    dataset_version_id: UUID
    question: str | None
    recommended_question_id: str | None
    prompt_locale: Literal["en", "zh"] | None
    prompt_template_version: str | None
    prompt_template_sha256: str | None
    prompt_audit_state: Literal["recorded", "legacy_unrecorded"]
    status: str
    plan_schema_version: str
    output_schema_version: str
    tool: str | None
    result_hash: str | None
    answer: ChatAnswerResponse | None
    safe_summary: str | None
    error_code: str | None
    action_draft_id: UUID | None
    action_draft: dict[str, object] | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    saved: bool = False
    provider_audit: ProviderAuditResponse | None = None


class RecommendedQuestionResponse(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    labels: dict[Literal["en", "zh"], str]
    templates: dict[Literal["en", "zh"], str]
    template_version: str = Field(min_length=1, max_length=100)
    template_sha256: dict[Literal["en", "zh"], str]
    context_kind: Literal[
        "inventory_analysis",
        "profit_bridge",
        "forecast",
        "action_cards",
    ] | None = None
    intent: str = Field(min_length=1, max_length=100)
    max_chars: int = Field(ge=1, le=2_000)
    available: bool


class ChatTurnListResponse(BaseModel):
    items: tuple[ChatTurnResponse, ...]
    saved_items: tuple[ChatTurnResponse, ...]
    recommended_questions: tuple[RecommendedQuestionResponse, ...]
    availability: Literal["available", "unavailable"]
    unavailable_code: Literal["AI_CHAT_UNAVAILABLE"] | None


class ChatSessionDeleteResponse(BaseModel):
    deleted_turns: int = Field(ge=0)
