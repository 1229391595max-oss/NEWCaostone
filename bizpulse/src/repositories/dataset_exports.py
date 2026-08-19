"""Immutable normalized dataset export records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection, select

from src.db.schema import dataset_exports


@dataclass(frozen=True, slots=True)
class DatasetExportProjection:
    id: UUID
    workspace_id: str
    dataset_version_id: UUID
    format: str
    status: str
    storage_object_id: UUID
    sha256: str
    byte_count: int
    idempotency_key_hash: bytes
    request_hash: bytes
    failure_code: str | None
    created_at: datetime


class DatasetExportRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def add(self, values: dict[str, object]) -> DatasetExportProjection:
        row = self._connection.execute(
            dataset_exports.insert().values(**values).returning(*dataset_exports.c)
        ).mappings().one()
        return DatasetExportProjection(**row)

    def find_replay(self, workspace_id: str, version_id: UUID, key_hash: bytes):
        row = self._connection.execute(
            select(*dataset_exports.c).where(
                dataset_exports.c.workspace_id == workspace_id,
                dataset_exports.c.dataset_version_id == version_id,
                dataset_exports.c.idempotency_key_hash == key_hash,
            )
        ).mappings().one_or_none()
        return DatasetExportProjection(**row) if row else None

    def get(self, workspace_id: str, version_id: UUID, export_id: UUID):
        row = self._connection.execute(
            select(*dataset_exports.c).where(
                dataset_exports.c.id == export_id,
                dataset_exports.c.workspace_id == workspace_id,
                dataset_exports.c.dataset_version_id == version_id,
            )
        ).mappings().one_or_none()
        return DatasetExportProjection(**row) if row else None

    def list(self, workspace_id: str, version_id: UUID, *, limit: int = 20):
        rows = self._connection.execute(
            select(*dataset_exports.c)
            .where(
                dataset_exports.c.workspace_id == workspace_id,
                dataset_exports.c.dataset_version_id == version_id,
            )
            .order_by(dataset_exports.c.created_at.desc(), dataset_exports.c.id)
            .limit(limit)
        ).mappings()
        return tuple(DatasetExportProjection(**row) for row in rows)
