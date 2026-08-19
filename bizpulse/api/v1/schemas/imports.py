"""Schemas for the revisioned operator import workflow."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateWorkflowRequest(StrictRequest):
    pass


class RevisionRequest(StrictRequest):
    expected_revision: int = Field(ge=0)


class MappingRequest(RevisionRequest):
    expected_mapping_revision: int = Field(ge=0)
    mapping: dict[str, str] = Field(min_length=1, max_length=64)
    assigned_store_id: str | None = Field(default=None, min_length=1, max_length=100)


class WorkflowProjection(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    revision: int
    source_confirmed_synthetic: bool
    source_kind: str
    base_dataset_version_id: UUID | None
    failure_code: str | None
    created_at: datetime
    updated_at: datetime
    committed_at: datetime | None


class UploadProjection(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_filename: str
    media_type: str
    size_bytes: int
    sha256: str
    status: str
    adapter_id: str | None
    adapter_version: str | None
    source_role: str | None
    recognition: dict[str, object] | None
    mapping: dict[str, object] | None
    mapping_revision: int
    assigned_store_id: str | None
    quality_report: dict[str, object] | None


class WorkflowResponse(BaseModel):
    workflow: WorkflowProjection
    replayed: bool


class UploadResponse(BaseModel):
    workflow: WorkflowProjection
    upload: UploadProjection
    replayed: bool


class PreviewResponse(BaseModel):
    workflow_id: UUID
    upload_id: UUID
    candidate_sha256: str
    records: tuple[dict[str, object], ...]


class DedupeSummaryProjection(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rows_read: int
    rows_retained: int
    duplicates_removed: int
    conflicts: int
    per_role: dict[str, dict[str, int]]


class RowOriginProjection(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_kind: str
    source_name: str
    sheet_name: str | None
    row_number: int | None


class DedupeConflictProjection(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role: str
    business_key: tuple[tuple[str, str], ...]
    fields: tuple[str, ...]
    existing: RowOriginProjection
    incoming: RowOriginProjection


class CommitPlanResponse(BaseModel):
    workflow_id: UUID
    expected_revision: int
    ready: bool
    candidate_sha256s: tuple[str, ...]
    content_sha256: str | None
    dedupe: DedupeSummaryProjection
    conflicts: tuple[DedupeConflictProjection, ...]
    conflicts_truncated: bool
    conflict_download_url: str


class CommitResponse(BaseModel):
    workflow_id: UUID
    dataset_version_id: UUID
    version_number: int
    content_sha256: str
    created: bool
