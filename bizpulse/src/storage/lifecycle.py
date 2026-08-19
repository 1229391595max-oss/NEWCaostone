"""Converge PostgreSQL object authority with Azure Blob side effects."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine

from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.storage_objects import StorageObjectRepository
from src.storage.protocol import AvailableObject, StagedObject, WorkflowStorage


@dataclass(frozen=True, slots=True)
class OrphanInventory:
    blob_orphan_keys: tuple[str, ...]
    database_missing_keys: tuple[str, ...]


class StorageLifecycle:
    def __init__(
        self,
        engine: Engine,
        storage: WorkflowStorage,
        workspace_id: str,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._engine = engine
        self._storage = storage
        self._workspace_id = workspace_id
        self._clock = clock

    def finalize_success(
        self,
        object_id: UUID,
        staged: StagedObject,
        final_key: str,
        *,
        now: datetime,
        before_commit: Callable[[], None] = lambda: None,
    ) -> AvailableObject:
        available = self._storage.promote(
            staged.key,
            final_key,
            staged.sha256,
        )
        try:
            with PostgresUnitOfWork(self._engine) as uow:
                StorageObjectRepository(uow.connection).mark_available(
                    object_id,
                    object_key=available.key,
                    etag=available.etag,
                    now=now,
                )
                before_commit()
        except BaseException as primary_error:
            try:
                self._storage.delete(
                    available.key,
                    expected_etag=available.etag,
                )
            except Exception:
                primary_error.add_note("blob_compensation_failed")
            raise

        self._storage.delete(staged.key, expected_etag=staged.etag)
        return available

    def finalize_failure(
        self,
        object_id: UUID,
        staged_key: str,
        *,
        now: datetime,
        expected_etag: str | None = None,
    ) -> None:
        try:
            self._storage.delete(staged_key, expected_etag=expected_etag)
        except Exception:
            with PostgresUnitOfWork(self._engine) as uow:
                StorageObjectRepository(uow.connection).mark_quarantined(
                    object_id,
                    now=now,
                )
            raise
        with PostgresUnitOfWork(self._engine) as uow:
            StorageObjectRepository(uow.connection).mark_deleted(object_id, now=now)

    def expire(self, now: datetime) -> int:
        with self._engine.connect() as connection:
            expired = StorageObjectRepository(connection).list_expired_temporary(
                self._workspace_id,
                now,
            )
        completed = 0
        for record in expired:
            try:
                self._storage.delete(record.object_key, expected_etag=record.etag)
            except Exception:
                with PostgresUnitOfWork(self._engine) as uow:
                    StorageObjectRepository(uow.connection).mark_quarantined(
                        record.id,
                        now=now,
                    )
                continue
            with PostgresUnitOfWork(self._engine) as uow:
                StorageObjectRepository(uow.connection).mark_deleted(
                    record.id,
                    now=now,
                )
            completed += 1
        return completed

    def orphan_inventory(self, prefix: str) -> OrphanInventory:
        blob_objects = self._storage.inventory(prefix)
        blob_keys = {item.key for item in blob_objects}
        with self._engine.connect() as connection:
            live_records = StorageObjectRepository(connection).list_live(
                self._workspace_id
            )
        database_keys = {record.object_key for record in live_records}
        missing_records = [
            record for record in live_records if record.object_key not in blob_keys
        ]
        if missing_records:
            now = self._clock()
            with PostgresUnitOfWork(self._engine) as uow:
                repository = StorageObjectRepository(uow.connection)
                for record in missing_records:
                    repository.mark_quarantined(record.id, now=now)
        return OrphanInventory(
            blob_orphan_keys=tuple(sorted(blob_keys - database_keys)),
            database_missing_keys=tuple(
                sorted(record.object_key for record in missing_records)
            ),
        )
