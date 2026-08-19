"""Bounded public schemas for the BP data library."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class QualitySummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    status: str
    missing_roles: tuple[str, ...]
    issue_count: int


class PreparationSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    status: str
    domains: tuple[str, ...]


class LibraryVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    dataset_version_id: UUID
    version_number: int
    lifecycle: str
    created_at: datetime
    period_start: date | None
    period_end: date | None
    stores: int
    skus: int
    source_roles: tuple[str, ...]
    row_count: int
    quality: QualitySummaryResponse
    preparation: PreparationSummaryResponse
    preview_available: bool
    export_available: bool


class LibraryVersionsResponse(BaseModel):
    versions: tuple[LibraryVersionResponse, ...]


class LibraryTableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    role: str
    scope_kind: Literal["store", "shared"]
    row_count: int
    columns: tuple[str, ...]
    preview: tuple[dict[str, object], ...]


class LibraryTablePageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    role: str
    scope_kind: Literal["store", "shared"]
    columns: tuple[str, ...]
    rows: tuple[dict[str, object], ...]
    page: int
    page_size: int
    total_rows: int
    total_pages: int


class LibraryProvenanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    source_name: str
    source_role: str
    status: str
    adapter: str | None
    row_count: int | None


class LibraryExportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    dataset_version_id: UUID
    format: str
    status: str
    byte_count: int
    created_at: datetime


class StoreDescriptorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    store_id: str
    display_name_en: str
    display_name_zh: str
    currency: str
    opened_on: date | None
    lifecycle: Literal["established", "new"]
    has_data: bool


class StoreScopeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    kind: Literal["all", "single"]
    store_ids: tuple[str, ...]


class LibraryVersionDetailResponse(LibraryVersionResponse):
    store_catalog: tuple[StoreDescriptorResponse, ...]
    resolved_scope: StoreScopeResponse
    tables: tuple[LibraryTableResponse, ...]
    provenance: tuple[LibraryProvenanceResponse, ...]
    analyses: tuple[str, ...]
    exports: tuple[LibraryExportResponse, ...]
