"""Validated deterministic-analysis API contracts."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

AnalysisKind = Literal[
    "sales_ads",
    "inventory_risk",
    "fifo_cost_aging",
    "operating_profit",
    "replenishment",
]


class AnalysisRunRequest(BaseModel):
    kind: AnalysisKind
    dataset_version_id: UUID
    scope: dict[str, object] = Field(default_factory=dict)


class AnalysisRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: UUID
    dataset_version_id: UUID
    kind: AnalysisKind
    algorithm_version: str
    input_hash: str
    status: Literal["completed"]
    disposition: Literal["created", "reused", "read"]
    artifact_sha256: str
    evidence_count: int


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    alias: str
    evidence_state: Literal["measured", "derived", "assumed", "unknown"]
    formula: str
    source_refs: list[str]
