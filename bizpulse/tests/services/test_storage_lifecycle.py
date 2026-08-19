from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.repositories.storage_objects import StorageObjectRepository
from src.storage.lifecycle import StorageLifecycle
from src.storage.protocol import AvailableObject, InventoryObject, StagedObject

WORKSPACE_ID = "synthetic-demo"


class InjectedCommitFailure(RuntimeError):
    pass


@dataclass
class MemoryObject:
    data: bytes
    sha256: str
    etag: str


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, MemoryObject] = {}

    def add_staged(self, staged: StagedObject, data: bytes) -> None:
        self.objects[staged.key] = MemoryObject(data, staged.sha256, staged.etag)

    def promote(self, staged_key: str, final_key: str, expected_sha256: str):
        source = self.objects[staged_key]
        assert source.sha256 == expected_sha256
        created = final_key not in self.objects
        self.objects[final_key] = MemoryObject(source.data, source.sha256, "final-etag")
        return AvailableObject(
            key=final_key,
            size_bytes=len(source.data),
            sha256=source.sha256,
            etag="final-etag",
            created=created,
        )

    def delete(self, key: str, *, expected_etag: str | None = None) -> None:
        current = self.objects.get(key)
        if current is None:
            return
        assert expected_etag is None or current.etag == expected_etag
        del self.objects[key]

    def inventory(self, prefix: str):
        return tuple(
            InventoryObject(key, len(value.data), value.etag)
            for key, value in sorted(self.objects.items())
            if key.startswith(prefix)
        )

    def put_staging(self, stream: BytesIO, *, max_bytes: int, media_type: str):
        raise NotImplementedError

    def open_verified(self, key: str, expected_sha256: str, max_bytes: int):
        raise NotImplementedError


def seed_workspace(engine: Engine) -> None:
    with PostgresUnitOfWork(engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)


def register_staged(
    engine: Engine,
    storage: MemoryStorage,
    *,
    now: datetime,
    expires_at: datetime | None = None,
) -> tuple[object, StagedObject]:
    digest = "a" * 64
    staged = StagedObject(
        key=f"workspaces/staging/{uuid4().hex}.part",
        size_bytes=9,
        sha256=digest,
        etag="staged-etag",
        media_type="text/csv",
    )
    storage.add_staged(staged, b"synthetic")
    with PostgresUnitOfWork(engine) as uow:
        record = StorageObjectRepository(uow.connection).create_staging(
            workspace_id=WORKSPACE_ID,
            staged=staged,
            purpose="temporary_upload",
            now=now,
            expires_at=expires_at,
        )
    return record, staged


def test_blob_success_is_not_available_before_database_commit(
    migrated_engine: Engine,
) -> None:
    seed_workspace(migrated_engine)
    now = datetime.now(UTC)
    storage = MemoryStorage()
    record, staged = register_staged(migrated_engine, storage, now=now)
    lifecycle = StorageLifecycle(migrated_engine, storage, WORKSPACE_ID)
    final_key = f"workspaces/versions/{staged.sha256}.csv"

    with pytest.raises(InjectedCommitFailure):
        lifecycle.finalize_success(
            record.id,
            staged,
            final_key,
            before_commit=lambda: (_ for _ in ()).throw(InjectedCommitFailure()),
            now=now,
        )

    with migrated_engine.connect() as connection:
        persisted = StorageObjectRepository(connection).get(record.id)
    assert persisted.state == "staging"
    assert staged.key in storage.objects
    assert final_key not in storage.objects


def test_success_commits_available_ledger_before_staging_cleanup(
    migrated_engine: Engine,
) -> None:
    seed_workspace(migrated_engine)
    now = datetime.now(UTC)
    storage = MemoryStorage()
    record, staged = register_staged(migrated_engine, storage, now=now)
    final_key = f"workspaces/versions/{staged.sha256}.csv"

    available = StorageLifecycle(
        migrated_engine,
        storage,
        WORKSPACE_ID,
    ).finalize_success(record.id, staged, final_key, now=now)

    with migrated_engine.connect() as connection:
        persisted = StorageObjectRepository(connection).get(record.id)
    assert persisted.state == "available"
    assert persisted.object_key == final_key
    assert available.key == final_key
    assert staged.key not in storage.objects
    assert final_key in storage.objects


def test_expire_deletes_only_temporary_objects_and_orphans_are_not_deleted(
    migrated_engine: Engine,
) -> None:
    seed_workspace(migrated_engine)
    now = datetime.now(UTC)
    storage = MemoryStorage()
    expired, staged = register_staged(
        migrated_engine,
        storage,
        now=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    orphan_key = "workspaces/orphans/unknown.bin"
    storage.objects[orphan_key] = MemoryObject(b"orphan", "b" * 64, "orphan-etag")
    lifecycle = StorageLifecycle(migrated_engine, storage, WORKSPACE_ID)

    expired_count = lifecycle.expire(now)
    report = lifecycle.orphan_inventory("workspaces/")

    with migrated_engine.connect() as connection:
        persisted = StorageObjectRepository(connection).get(expired.id)
    assert expired_count == 1
    assert persisted.state == "deleted"
    assert staged.key not in storage.objects
    assert orphan_key in storage.objects
    assert report.blob_orphan_keys == (orphan_key,)
