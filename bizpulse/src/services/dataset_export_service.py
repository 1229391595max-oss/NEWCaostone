"""Operator-only immutable normalized dataset workbook exports."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
import json
from uuid import UUID, uuid5

from sqlalchemy import Engine

from src.db.unit_of_work import PostgresUnitOfWork
from src.exports.dataset_workbook import MAX_EXPORT_BYTES, build_dataset_workbook
from src.repositories.dataset_exports import DatasetExportRepository
from src.repositories.datasets import DatasetRepository
from src.repositories.storage_objects import StorageObjectRepository
from src.storage.keys import export_object_key

EXPORT_NAMESPACE = UUID("514490e8-ea3f-40c8-a1cf-56df5ba4cf59")
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class DatasetExportNotFound(RuntimeError):
    code = "DATASET_EXPORT_NOT_FOUND"


class DatasetExportInvalid(ValueError):
    code = "DATASET_EXPORT_INVALID"


class DatasetExportIdempotencyConflict(RuntimeError):
    code = "DATASET_EXPORT_IDEMPOTENCY_CONFLICT"


class DatasetExportService:
    def __init__(
        self,
        engine: Engine,
        storage,
        workspace_id: str,
        library_service,
        *,
        clock=None,
    ) -> None:
        self._engine = engine
        self._storage = storage
        self._workspace_id = workspace_id
        self._library = library_service
        self._clock = clock or (lambda: datetime.now(UTC))

    def generate(self, version_id: UUID, *, idempotency_key: str, format: str = "xlsx"):
        if format != "xlsx" or not 8 <= len(idempotency_key) <= 128:
            raise DatasetExportInvalid
        key_hash = sha256(idempotency_key.encode()).digest()
        request_hash = sha256(
            json.dumps(
                {"version_id": str(version_id), "format": format},
                sort_keys=True,
            ).encode()
        ).digest()
        with self._engine.connect() as connection:
            version = DatasetRepository(connection).get_version(version_id)
            replay = DatasetExportRepository(connection).find_replay(
                self._workspace_id,
                version_id,
                key_hash,
            )
        if version is None or version.workspace_id != self._workspace_id:
            raise DatasetExportNotFound
        if replay is not None:
            if replay.request_hash != request_hash:
                raise DatasetExportIdempotencyConflict
            return replay
        tables = self._library.tables_for_export(version_id)
        content = build_dataset_workbook(version.version_number, tables)
        staged = self._storage.put_staging(
            BytesIO(content),
            max_bytes=MAX_EXPORT_BYTES,
            media_type=XLSX_MEDIA_TYPE,
        )
        final_key = export_object_key(
            self._workspace_id,
            f"dataset-{version_id}",
            staged.sha256,
        )
        available = self._storage.promote(staged.key, final_key, staged.sha256)
        object_id = uuid5(EXPORT_NAMESPACE, f"object:{available.key}")
        export_id = uuid5(
            EXPORT_NAMESPACE,
            f"export:{self._workspace_id}:{version_id}:{key_hash.hex()}",
        )
        try:
            with PostgresUnitOfWork(self._engine) as uow:
                objects = StorageObjectRepository(uow.connection)
                stored = objects.get_by_key(available.key)
                if stored is None:
                    stored = objects.create_available(
                        object_id=object_id,
                        workspace_id=self._workspace_id,
                        available=available,
                        purpose="export",
                        media_type=XLSX_MEDIA_TYPE,
                        now=self._clock(),
                    )
                elif stored.sha256 != available.sha256 or stored.state != "available":
                    raise DatasetExportInvalid("DATASET_EXPORT_STORAGE_CONFLICT")
                result = DatasetExportRepository(uow.connection).add(
                    {
                        "id": export_id,
                        "workspace_id": self._workspace_id,
                        "dataset_version_id": version_id,
                        "format": "xlsx",
                        "status": "available",
                        "storage_object_id": stored.id,
                        "sha256": available.sha256,
                        "byte_count": available.size_bytes,
                        "idempotency_key_hash": key_hash,
                        "request_hash": request_hash,
                        "failure_code": None,
                        "created_at": self._clock(),
                    }
                )
        finally:
            try:
                self._storage.delete(staged.key, expected_etag=staged.etag)
            except Exception:
                pass
        return result

    def open(self, version_id: UUID, export_id: UUID) -> bytes:
        with self._engine.connect() as connection:
            exported = DatasetExportRepository(connection).get(
                self._workspace_id,
                version_id,
                export_id,
            )
            stored = (
                StorageObjectRepository(connection).get(exported.storage_object_id)
                if exported else None
            )
        if (
            exported is None
            or stored is None
            or stored.workspace_id != self._workspace_id
            or stored.purpose != "export"
            or stored.state != "available"
            or stored.sha256 != exported.sha256
        ):
            raise DatasetExportNotFound
        with self._storage.open_verified(
            stored.object_key,
            exported.sha256,
            exported.byte_count,
        ) as opened:
            return opened.read()
