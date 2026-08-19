"""Secret-safe administrator request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AIChannelsUpdateRequest(StrictRequest):
    expected_revision: int = Field(ge=0)
    operator_enabled: bool
    demo_enabled: bool
    current_password: SecretStr = Field(min_length=1, max_length=1024)


class AIKeyRotationRequest(StrictRequest):
    expected_revision: int = Field(ge=0)
    candidate_key: SecretStr = Field(min_length=1, max_length=1024)
    current_password: SecretStr = Field(min_length=1, max_length=1024)


class AICredentialProjection(BaseModel):
    configured: bool
    fingerprint: str | None
    verified_at: datetime | None


class AIControlResponse(BaseModel):
    revision: int
    operator_enabled: bool
    demo_enabled: bool
    credential: AICredentialProjection


class AdminAIStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: Literal["ready", "unavailable"]
    revision: int | None
    operator_enabled: bool
    demo_enabled: bool
    credential: AICredentialProjection


class AIKeyRotationResponse(BaseModel):
    revision: int
    credential: AICredentialProjection
    result_code: Literal["ADMIN_AI_KEY_ROTATED"]


class AITurnBindingAuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    turn_id: UUID
    actor_kind: Literal["operator", "demo"]
    request_id: str
    credential_binding_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    credential_control_revision: int = Field(ge=0)
    status: str


class AITurnBindingAuditListResponse(BaseModel):
    items: tuple[AITurnBindingAuditResponse, ...]


class AIMutationAuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: str
    action: Literal["key.rotate", "channels.update"]
    result: Literal["succeeded", "failed"]
    safe_error_code: str | None
    prior_revision: int = Field(ge=0)
    resulting_revision: int = Field(ge=0)
    requested_operator_enabled: bool | None
    requested_demo_enabled: bool | None


class AIMutationAuditListResponse(BaseModel):
    items: tuple[AIMutationAuditResponse, ...]


class AdminSystemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    database: Literal["ready", "unavailable"]
    blob: Literal["ready", "unavailable"]
    configuration: Literal["valid", "invalid"]
    migration: str | None


class AdminPublishedDatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dataset_version_id: UUID
    version_number: int
    released_at: datetime


class AdminImportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workflow_id: UUID
    status: str
    failure_code: str | None
    updated_at: datetime


class AdminActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: Literal["import", "publish"]
    status: str
    occurred_at: datetime


class AdminSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    system: AdminSystemResponse
    published_dataset: AdminPublishedDatasetResponse | None
    latest_import: AdminImportResponse | None
    actionable_failure_count: int = Field(ge=0)
    recent_activity: tuple[AdminActivityResponse, ...]
    ai: AdminAIStatusResponse
