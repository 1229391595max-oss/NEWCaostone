"""PostgreSQL authority for Blob object references and states."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Connection, Text, cast, literal, select, update

from src.db.schema import storage_objects
from src.storage.protocol import AvailableObject, StagedObject


@dataclass(frozen=True, slots=True)
class StorageObjectProjection:
    id: UUID
    workspace_id: str
    object_key: str
    purpose: str
    state: str
    media_type: str
    size_bytes: int
    sha256: str
    etag: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None


class StorageObjectRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create_staging(
        self,
        *,
        workspace_id: str,
        staged: StagedObject,
        purpose: str,
        now: datetime,
        expires_at: datetime | None,
        object_id: UUID | None = None,
    ) -> StorageObjectProjection:
        resolved_id = object_id or uuid4()
        row = self._connection.execute(
            storage_objects.insert()
            .values(
                id=resolved_id,
                workspace_id=workspace_id,
                object_key=staged.key,
                purpose=purpose,
                state="staging",
                media_type=staged.media_type,
                size_bytes=staged.size_bytes,
                sha256=staged.sha256,
                etag=staged.etag,
                created_at=now,
                updated_at=now,
                expires_at=expires_at,
            )
            .returning(*storage_objects.c)
        ).mappings().one()
        return StorageObjectProjection(**row)

    def create_available(
        self,
        *,
        object_id: UUID,
        workspace_id: str,
        available: AvailableObject,
        purpose: str,
        media_type: str,
        now: datetime,
        expires_at: datetime | None = None,
    ) -> StorageObjectProjection:
        row = self._connection.execute(
            storage_objects.insert()
            .values(
                id=object_id,
                workspace_id=workspace_id,
                object_key=available.key,
                purpose=purpose,
                state="available",
                media_type=media_type,
                size_bytes=available.size_bytes,
                sha256=available.sha256,
                etag=available.etag,
                created_at=now,
                updated_at=now,
                expires_at=expires_at,
            )
            .returning(*storage_objects.c)
        ).mappings().one()
        return StorageObjectProjection(**row)

    def create_promotion_reservation(
        self,
        *,
        object_id: UUID,
        workspace_id: str,
        object_key: str,
        size_bytes: int,
        sha256: str,
        media_type: str,
        now: datetime,
        expires_at: datetime,
    ) -> StorageObjectProjection:
        row = self._connection.execute(
            storage_objects.insert()
            .values(
                id=object_id,
                workspace_id=workspace_id,
                object_key=object_key,
                purpose="temporary_upload",
                state="staging",
                media_type=media_type,
                size_bytes=size_bytes,
                sha256=sha256,
                etag=None,
                created_at=now,
                updated_at=now,
                expires_at=expires_at,
            )
            .returning(*storage_objects.c)
        ).mappings().one()
        return StorageObjectProjection(**row)

    def get(self, object_id: UUID) -> StorageObjectProjection | None:
        row = self._connection.execute(
            select(*storage_objects.c).where(storage_objects.c.id == object_id)
        ).mappings().one_or_none()
        return StorageObjectProjection(**row) if row is not None else None

    def get_by_key(self, object_key: str) -> StorageObjectProjection | None:
        row = self._connection.execute(
            select(*storage_objects.c).where(
                storage_objects.c.object_key == object_key
            )
        ).mappings().one_or_none()
        return StorageObjectProjection(**row) if row is not None else None

    def mark_available(
        self,
        object_id: UUID,
        *,
        object_key: str,
        etag: str,
        now: datetime,
        purpose: str | None = None,
    ) -> StorageObjectProjection:
        values: dict[str, object] = {
            "object_key": object_key,
            "state": "available",
            "etag": etag,
            "updated_at": now,
            "expires_at": None,
        }
        if purpose is not None:
            values["purpose"] = purpose
        row = self._connection.execute(
            update(storage_objects)
            .where(
                storage_objects.c.id == object_id,
                storage_objects.c.state == "staging",
            )
            .values(**values)
            .returning(*storage_objects.c)
        ).mappings().one_or_none()
        if row is None:
            raise RuntimeError("storage_object_not_staging")
        return StorageObjectProjection(**row)

    def adopt_quarantined_available(
        self,
        object_id: UUID,
        *,
        object_key: str,
        sha256: str,
        etag: str,
        purpose: str,
        now: datetime,
    ) -> StorageObjectProjection:
        row = self._connection.execute(
            update(storage_objects)
            .where(
                storage_objects.c.id == object_id,
                storage_objects.c.object_key == object_key,
                storage_objects.c.sha256 == sha256,
                storage_objects.c.etag == etag,
                storage_objects.c.purpose == "temporary_upload",
                storage_objects.c.state == "quarantined",
            )
            .values(
                purpose=purpose,
                state="available",
                updated_at=now,
                expires_at=None,
            )
            .returning(*storage_objects.c)
        ).mappings().one_or_none()
        if row is None:
            raise RuntimeError("storage_object_not_adoptable")
        return StorageObjectProjection(**row)

    def record_promoted_quarantined(
        self,
        object_id: UUID,
        *,
        object_key: str,
        sha256: str,
        size_bytes: int,
        etag: str,
        now: datetime,
        expires_at: datetime,
    ) -> StorageObjectProjection:
        row = self._connection.execute(
            update(storage_objects)
            .where(
                storage_objects.c.id == object_id,
                storage_objects.c.object_key == object_key,
                storage_objects.c.sha256 == sha256,
                storage_objects.c.size_bytes == size_bytes,
                storage_objects.c.purpose == "temporary_upload",
                storage_objects.c.state == "staging",
                storage_objects.c.etag.is_(None),
            )
            .values(
                state="quarantined",
                etag=etag,
                updated_at=now,
                expires_at=expires_at,
            )
            .returning(*storage_objects.c)
        ).mappings().one_or_none()
        if row is None:
            raise RuntimeError("storage_promotion_reservation_not_adoptable")
        return StorageObjectProjection(**row)

    def mark_quarantined(
        self,
        object_id: UUID,
        *,
        now: datetime,
    ) -> StorageObjectProjection:
        row = self._connection.execute(
            update(storage_objects)
            .where(
                storage_objects.c.id == object_id,
                storage_objects.c.state != "deleted",
            )
            .values(state="quarantined", updated_at=now)
            .returning(*storage_objects.c)
        ).mappings().one()
        return StorageObjectProjection(**row)

    def mark_cleanup_pending(
        self,
        object_id: UUID,
        *,
        now: datetime,
    ) -> StorageObjectProjection:
        row = self._connection.execute(
            update(storage_objects)
            .where(
                storage_objects.c.id == object_id,
                storage_objects.c.purpose == "temporary_upload",
                storage_objects.c.state.in_(("staging", "quarantined")),
            )
            .values(
                state="quarantined",
                updated_at=now,
                expires_at=now,
            )
            .returning(*storage_objects.c)
        ).mappings().one_or_none()
        if row is None:
            raise RuntimeError("storage_object_not_cleanup_candidate")
        return StorageObjectProjection(**row)

    def mark_deleted(
        self,
        object_id: UUID,
        *,
        now: datetime,
    ) -> StorageObjectProjection:
        row = self._connection.execute(
            update(storage_objects)
            .where(
                storage_objects.c.id == object_id,
                storage_objects.c.purpose == "temporary_upload",
                storage_objects.c.state.in_(("staging", "quarantined")),
            )
            .values(
                object_key=literal("deleted/") + cast(storage_objects.c.id, Text),
                state="deleted",
                updated_at=now,
                etag=None,
            )
            .returning(*storage_objects.c)
        ).mappings().one_or_none()
        if row is None:
            raise RuntimeError("only_temporary_storage_can_be_deleted")
        return StorageObjectProjection(**row)

    def list_expired_temporary(
        self,
        workspace_id: str,
        now: datetime,
    ) -> tuple[StorageObjectProjection, ...]:
        rows = self._connection.execute(
            select(*storage_objects.c).where(
                storage_objects.c.workspace_id == workspace_id,
                storage_objects.c.purpose == "temporary_upload",
                storage_objects.c.state.in_(("staging", "quarantined")),
                storage_objects.c.expires_at.is_not(None),
                storage_objects.c.expires_at <= now,
            )
        ).mappings()
        return tuple(StorageObjectProjection(**row) for row in rows)

    def list_live(
        self,
        workspace_id: str,
    ) -> tuple[StorageObjectProjection, ...]:
        rows = self._connection.execute(
            select(*storage_objects.c).where(
                storage_objects.c.workspace_id == workspace_id,
                storage_objects.c.state != "deleted",
            )
        ).mappings()
        return tuple(StorageObjectProjection(**row) for row in rows)
