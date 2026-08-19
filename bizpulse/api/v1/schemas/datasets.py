"""Schemas for immutable dataset versions and manual public releases."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DatasetVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    series_id: UUID
    source_workflow_id: UUID | None
    version_number: int
    status: str
    schema_version: str
    content_sha256: str
    created_at: datetime


class DatasetVersionsResponse(BaseModel):
    versions: tuple[DatasetVersionResponse, ...]


class PreparationDomainResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: Literal["sales_ads", "inventory", "profit", "forecast", "actions"]
    status: Literal["ready", "running", "failed", "unavailable"]
    limitation_code: str | None = None


class DatasetPreparationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dataset_version_id: UUID
    status: Literal["ready", "partial", "failed"]
    domains: tuple[PreparationDomainResponse, ...]


class PublicReleaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    release_id: UUID
    dataset_version_id: UUID
    version_number: int
    schema_version: str
    content_sha256: str
    released_at: datetime
    source_classification: str
    reporting_period: tuple[str, str]
    current_period: tuple[str, str]
    comparison_period: tuple[str, str]
    currency: str
    source_roles: tuple[str, ...]


class PublishDatasetRequest(BaseModel):
    expected_current_id: UUID | None


class PublishDatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    release_id: UUID
    dataset_version_id: UUID
    previous_dataset_version_id: UUID | None
    released_at: datetime
    created: bool
    replayed: bool


class DatasetExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["xlsx"] = "xlsx"


class DatasetExportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    dataset_version_id: UUID
    status: Literal["available", "failed"]
    format: Literal["xlsx"]
    byte_count: int | None
    created_at: datetime
