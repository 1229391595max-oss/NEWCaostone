"""Closed contracts for Ask BizPulse plans, facts, answers, and turns."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

ToolName = Literal[
    "metric_lookup",
    "trend_compare",
    "sku_rank",
    "profit_bridge_explain",
    "inventory_risk_lookup",
    "forecast_lookup",
    "data_quality_lookup",
    "action_card_lookup",
    "monthly_sales_report_lookup",
]
EvidenceState = Literal["measured", "derived", "assumed", "unknown"]
FactReference = Annotated[str, Field(pattern=r"^fact-[0-9]{3}$")]
EvidenceReference = Annotated[str, Field(min_length=1, max_length=1_000)]
LimitationText = Annotated[str, Field(min_length=1, max_length=500)]
SuggestedQuestion = Annotated[str, Field(min_length=1, max_length=200)]
ChatStatus = Literal[
    "planning",
    "querying",
    "answering",
    "answered",
    "clarification_required",
    "unsupported",
    "failed",
    "outcome_unknown",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


MetricName = Literal[
    "gross_sales",
    "net_sales",
    "units",
    "orders",
    "aov",
    "ad_spend",
    "contribution_profit",
    "operating_profit",
]


class MetricLookupArguments(_StrictModel):
    metric: MetricName
    period: Literal["current", "previous"] = "current"


class TrendCompareArguments(_StrictModel):
    metric: Literal["net_sales", "units", "orders", "ad_spend"]
    comparison: Literal["current_vs_previous", "daily_current"] = (
        "current_vs_previous"
    )


class SkuRankArguments(_StrictModel):
    metric: Literal[
        "net_sales",
        "units",
        "ad_spend",
        "inventory_cover",
        "replenishment_quantity",
        "replenishment_cash",
        "contribution_profit",
    ]
    direction: Literal["top", "bottom"] = "top"
    limit: int = Field(default=10, ge=1, le=20)


class ProfitBridgeArguments(_StrictModel):
    view: Literal["drivers", "summary"] = "drivers"


class InventoryRiskArguments(_StrictModel):
    view: Literal["risks", "replenishment"] = "risks"
    risk: Literal["all", "stockout", "balanced", "overstock", "unknown"] = "all"
    limit: int = Field(default=20, ge=1, le=20)


class ForecastArguments(_StrictModel):
    horizon_days: Literal[7, 30, 90] = 30
    view: Literal["inputs", "scenarios", "analogs", "limitations"] = "scenarios"


class DataQualityArguments(_StrictModel):
    section: Literal[
        "coverage",
        "limitations",
        "evidence",
        "missing",
        "mapping",
    ] = "coverage"


class ActionCardArguments(_StrictModel):
    status: Literal["all", "new", "reviewed", "approved", "dismissed"] = "all"
    view: Literal["summary", "revisions", "decisions", "exports", "outcomes"] = (
        "summary"
    )
    limit: int = Field(default=20, ge=1, le=20)


class MonthlySalesReportArguments(_StrictModel):
    report: Literal["latest_completed"] = "latest_completed"


QueryArguments = (
    MetricLookupArguments
    | TrendCompareArguments
    | SkuRankArguments
    | ProfitBridgeArguments
    | InventoryRiskArguments
    | ForecastArguments
    | DataQualityArguments
    | ActionCardArguments
    | MonthlySalesReportArguments
)

ARGUMENT_MODELS = {
    "metric_lookup": MetricLookupArguments,
    "trend_compare": TrendCompareArguments,
    "sku_rank": SkuRankArguments,
    "profit_bridge_explain": ProfitBridgeArguments,
    "inventory_risk_lookup": InventoryRiskArguments,
    "forecast_lookup": ForecastArguments,
    "data_quality_lookup": DataQualityArguments,
    "action_card_lookup": ActionCardArguments,
    "monthly_sales_report_lookup": MonthlySalesReportArguments,
}


class QueryPlan(_StrictModel):
    tool: ToolName
    arguments: QueryArguments

    @model_validator(mode="before")
    @classmethod
    def bind_arguments_to_tool(cls, value):
        if not isinstance(value, dict):
            return value
        tool = value.get("tool")
        model = ARGUMENT_MODELS.get(tool)
        if model is None:
            return value
        parsed = model.model_validate(value.get("arguments", {}))
        return {**value, "arguments": parsed}

    @model_validator(mode="after")
    def reject_cross_tool_arguments(self):
        expected = ARGUMENT_MODELS[self.tool]
        if type(self.arguments) is not expected:
            raise ValueError("query_arguments_do_not_match_tool")
        return self


class PlanningDecision(_StrictModel):
    status: Literal["planned", "clarification_required", "unsupported"]
    plan: QueryPlan | None = None

    @model_validator(mode="after")
    def require_plan_only_for_planned_status(self):
        if (self.status == "planned") != (self.plan is not None):
            raise ValueError("planning_decision_shape_invalid")
        return self


class QueryScope(_StrictModel):
    workspace_id: str = Field(min_length=1, max_length=100, exclude=True)
    actor_kind: Literal["operator", "demo"] | None = Field(default=None, exclude=True)
    session_id: UUID | None = Field(default=None, exclude=True)
    session_created_at: datetime | None = Field(default=None, exclude=True)
    forecast_id: UUID | None = Field(default=None, exclude=True)
    profit_bridge_id: UUID | None = Field(default=None, exclude=True)
    context_kind: Literal[
        "inventory_analysis",
        "profit_bridge",
        "forecast",
        "action_cards",
    ] | None = Field(default=None, exclude=True)
    context_reference: str | None = Field(default=None, exclude=True, max_length=100)
    dataset_version_id: UUID
    store_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    period_start: date
    period_end: date
    currency: Literal["BRL"] = "BRL"

    @model_validator(mode="after")
    def validate_scope(self):
        if self.period_start > self.period_end:
            raise ValueError("query_scope_period_invalid")
        if (
            len(set(self.store_ids)) != len(self.store_ids)
            or any(
                not isinstance(item, str)
                or not item
                or len(item) > 100
                or item != item.strip()
                for item in self.store_ids
            )
        ):
            raise ValueError("query_scope_store_invalid")
        expected = {
            "inventory_analysis": "inventory_analysis:pinned",
            "profit_bridge": "profit_bridge:pinned",
            "forecast": "forecast:pinned",
            "action_cards": "action_cards:pinned",
        }
        if (self.context_kind is None) != (self.context_reference is None):
            raise ValueError("query_scope_context_incomplete")
        if (
            self.context_kind is not None
            and self.context_reference != expected[self.context_kind]
        ):
            raise ValueError("query_scope_context_invalid")
        return self


class AuthoritativeFact(_StrictModel):
    fact_ref: FactReference
    label: str = Field(min_length=1, max_length=200)
    value: str | None = Field(default=None, max_length=500)
    evidence_state: EvidenceState
    evidence_refs: tuple[EvidenceReference, ...] = Field(max_length=10)


class ActionDraftSpec(_StrictModel):
    suggestion: str = Field(min_length=1, max_length=1000)
    target: str = Field(pattern=r"^SYNTH-[A-Za-z0-9._:-]+$", max_length=200)
    quantity: Decimal | None = Field(default=None, ge=0)
    budget_brl: Decimal | None = Field(default=None, ge=0)
    expected_impact: dict[str, str]
    confidence: Literal["low", "medium", "high"]
    limitations: tuple[LimitationText, ...] = Field(max_length=50)
    fact_refs: tuple[FactReference, ...] = Field(min_length=1, max_length=10)


class ToolResult(_StrictModel):
    tool: ToolName
    scope: QueryScope
    facts: tuple[AuthoritativeFact, ...] = Field(max_length=25)
    limitations: tuple[LimitationText, ...] = Field(max_length=50)
    result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    action_card_draft: ActionDraftSpec | None

    @field_validator("facts")
    @classmethod
    def fact_refs_must_be_unique(cls, value):
        refs = [item.fact_ref for item in value]
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate_fact_ref")
        return value


class ModelExplanation(_StrictModel):
    answer: str = Field(min_length=1, max_length=4000)
    fact_refs: tuple[FactReference, ...] = Field(max_length=25)
    suggested_questions: tuple[SuggestedQuestion, ...] = Field(max_length=4)


class ChatAnswer(_StrictModel):
    turn_id: UUID
    status: Literal[
        "answered", "clarification_required", "unsupported", "failed"
    ]
    answer: str = Field(max_length=4000)
    scope: QueryScope
    facts: tuple[AuthoritativeFact, ...] = Field(max_length=25)
    limitations: tuple[LimitationText, ...] = Field(max_length=50)
    suggested_questions: tuple[SuggestedQuestion, ...] = Field(max_length=4)
    action_card_draft_eligible: bool


@dataclass(frozen=True, slots=True)
class ChatPrincipal:
    actor_kind: Literal["operator", "demo"]
    session_id: UUID
    workspace_id: str
    dataset_version_id: UUID
    store_ids: tuple[str, ...]
    period_start: date
    period_end: date
    currency: Literal["BRL"] = "BRL"
    session_created_at: datetime | None = None
    forecast_id: UUID | None = None
    profit_bridge_id: UUID | None = None
    operator_id: UUID | None = None
    chat_epoch: int = 0

    def scope(
        self,
        *,
        context_kind: str | None = None,
        context_reference: str | None = None,
    ) -> QueryScope:
        return QueryScope(
            workspace_id=self.workspace_id,
            actor_kind=self.actor_kind,
            session_id=self.session_id,
            session_created_at=self.session_created_at,
            forecast_id=self.forecast_id,
            profit_bridge_id=self.profit_bridge_id,
            context_kind=context_kind,
            context_reference=context_reference,
            dataset_version_id=self.dataset_version_id,
            store_ids=self.store_ids,
            period_start=self.period_start,
            period_end=self.period_end,
            currency=self.currency,
        )


@dataclass(frozen=True, slots=True)
class ChatTurn:
    id: UUID
    turn_sequence: int
    actor_kind: str
    session_id: UUID
    dataset_version_id: UUID
    question: str | None
    recommended_question_id: str | None
    prompt_locale: Literal["en", "zh"] | None
    prompt_template_version: str | None
    prompt_template_sha256: str | None
    prompt_audit_state: Literal["recorded", "legacy_unrecorded"]
    credential_binding_id: str | None
    credential_control_revision: int | None
    credential_request_id: str | None
    status: str
    plan_schema_version: str
    output_schema_version: str
    tool: str | None
    result_hash: str | None
    answer: ChatAnswer | None
    safe_summary: str | None
    error_code: str | None
    action_draft_id: UUID | None
    action_draft: dict[str, object] | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    saved: bool = False
    replayed: bool = field(default=False, compare=False)


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ProviderResult(Generic[T]):
    value: T
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if (
            type(self.input_tokens) is not int
            or type(self.output_tokens) is not int
            or self.input_tokens <= 0
            or self.output_tokens < 0
        ):
            raise ValueError("provider_usage_invalid")
