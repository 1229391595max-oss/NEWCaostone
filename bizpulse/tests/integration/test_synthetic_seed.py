from __future__ import annotations

import json
from dataclasses import dataclass, replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError

from src.db.schema import (
    action_cards,
    action_decisions,
    analysis_runs,
    dataset_artifacts,
    dataset_versions,
    new_product_forecasts,
    public_releases,
    storage_objects,
)
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.services.demo_action_authority import DemoActionAuthority
from src.storage.protocol import AvailableObject, InventoryObject, StagedObject
from src.synthetic.manifest import load_bundle
from src.synthetic.generator import generate_demo
from src.synthetic.seed import ensure_demo_action, seed_demo

WORKSPACE_ID = "synthetic-demo"
FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic" / "v1"


@dataclass
class MemoryBlob:
    content: bytes
    etag: str


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, MemoryBlob] = {}
        self.put_calls = 0

    def put_staging(self, stream, *, max_bytes: int, media_type: str) -> StagedObject:
        content = stream.read()
        assert len(content) <= max_bytes
        self.put_calls += 1
        key = f"workspaces/staging/{uuid4().hex}.part"
        digest = sha256(content).hexdigest()
        etag = uuid4().hex
        self.objects[key] = MemoryBlob(content, etag)
        return StagedObject(key, len(content), digest, etag, media_type)

    def promote(self, staged_key, final_key, expected_sha256) -> AvailableObject:
        source = self.objects[staged_key]
        assert sha256(source.content).hexdigest() == expected_sha256
        created = final_key not in self.objects
        if created:
            self.objects[final_key] = MemoryBlob(source.content, uuid4().hex)
        target = self.objects[final_key]
        assert sha256(target.content).hexdigest() == expected_sha256
        return AvailableObject(
            final_key,
            len(target.content),
            expected_sha256,
            target.etag,
            created,
        )

    def delete(self, key, *, expected_etag=None) -> None:
        current = self.objects.get(key)
        if current is None:
            return
        assert expected_etag is None or expected_etag == current.etag
        del self.objects[key]

    def open_verified(self, key, expected_sha256, max_bytes):
        content = self.objects[key].content
        assert len(content) <= max_bytes
        assert sha256(content).hexdigest() == expected_sha256
        return BytesIO(content)

    def inventory(self, prefix):
        return tuple(
            InventoryObject(key, len(item.content), item.etag)
            for key, item in sorted(self.objects.items())
            if key.startswith(prefix)
        )


class FailingPromoteStorage(MemoryStorage):
    def promote(self, staged_key, final_key, expected_sha256):
        del staged_key, final_key, expected_sha256
        raise RuntimeError("injected_promotion_failure")


def counts(engine: Engine) -> tuple[int, int, int, int]:
    with engine.connect() as connection:
        return tuple(
            int(connection.scalar(select(func.count()).select_from(table)) or 0)
            for table in (
                storage_objects,
                dataset_versions,
                dataset_artifacts,
                public_releases,
            )
        )


def test_seed_is_idempotent_by_manifest_hash_and_storage_counts(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    bundle = load_bundle(FIXTURE_ROOT)
    storage = MemoryStorage()

    first = seed_demo(bundle, PostgresUnitOfWork(migrated_engine), storage)
    first_counts = counts(migrated_engine)
    first_blob_count = len(storage.objects)
    first_put_calls = storage.put_calls
    with migrated_engine.connect() as connection:
        first_analysis_count = int(
            connection.scalar(select(func.count()).select_from(analysis_runs)) or 0
        )
        first_forecast_count = int(
            connection.scalar(
                select(func.count()).select_from(new_product_forecasts)
            )
            or 0
        )
    second = seed_demo(bundle, PostgresUnitOfWork(migrated_engine), storage)

    assert second.series_id == first.series_id
    assert second.dataset_version_id == first.dataset_version_id
    assert second.public_release_id == first.public_release_id
    assert second.manifest_sha256 == first.manifest_sha256
    assert first.created is True
    assert second.created is False
    assert counts(migrated_engine) == first_counts
    assert len(storage.objects) == first_blob_count
    assert storage.put_calls == first_put_calls
    assert first.public_release_id is not None
    # Each of all/main/launch has nine monthly/current evidence Blobs plus
    # durable cleanup tombstones. Bridges reuse operating-profit runs.
    assert first_counts == (len(bundle.files) + 55, 1, len(bundle.files) + 1, 1)
    assert first_analysis_count == 27
    assert first_forecast_count == 3
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(analysis_runs)) == 27
        assert (
            connection.scalar(select(func.count()).select_from(new_product_forecasts))
            == 3
        )
    assert all("staging" not in key for key in storage.objects)


def test_seeded_analysis_bundle_preserves_the_two_store_catalog(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryStorage()

    seed_demo(
        load_bundle(FIXTURE_ROOT),
        PostgresUnitOfWork(migrated_engine),
        storage,
    )

    payloads = []
    for blob in storage.objects.values():
        try:
            payloads.append(json.loads(blob.content))
        except (UnicodeDecodeError, ValueError):
            continue
    analysis = next(
        payload for payload in payloads
        if payload.get("schema_version") == "canonical.analysis.v1"
    )
    assert [item["store_id"] for item in analysis["store_catalog"]] == [
        "SYNTH-STORE-01",
        "SYNTH-STORE-02",
    ]


def test_seed_rejects_manifest_store_catalog_drift_before_storage_write(
    migrated_engine: Engine,
) -> None:
    bundle = generate_demo(seed=20260813)
    tampered = replace(
        bundle,
        manifest=replace(
            bundle.manifest,
            store_catalog=tuple(reversed(bundle.manifest.store_catalog)),
        ),
    )
    storage = MemoryStorage()

    with pytest.raises(ValueError, match="synthetic_manifest_content_mismatch"):
        seed_demo(
            tampered,
            PostgresUnitOfWork(migrated_engine),
            storage,
        )

    assert storage.put_calls == 0


def test_hosted_seed_action_is_approved_and_idempotent(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryStorage()
    seeded = seed_demo(
        load_bundle(FIXTURE_ROOT),
        PostgresUnitOfWork(migrated_engine),
        storage,
    )

    first = ensure_demo_action(
        migrated_engine,
        storage,
        seeded.dataset_version_id,
    )
    second = ensure_demo_action(
        migrated_engine,
        storage,
        seeded.dataset_version_id,
    )

    assert second.id == first.id
    assert second.status == first.status == "approved"
    with migrated_engine.connect() as connection:
        seeded_actions = int(
            connection.scalar(select(func.count()).select_from(action_cards)) or 0
        )
        seeded_decisions = int(
            connection.scalar(select(func.count()).select_from(action_decisions)) or 0
        )
    assert seeded_actions == 3
    assert seeded_decisions == 6


def test_demo_action_authority_reports_only_an_approved_exact_version_ready(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryStorage()
    seeded = seed_demo(
        load_bundle(FIXTURE_ROOT),
        PostgresUnitOfWork(migrated_engine),
        storage,
    )
    authority = DemoActionAuthority(migrated_engine, storage, WORKSPACE_ID)

    assert authority.ready(seeded.dataset_version_id) is True
    action = authority.ensure(seeded.dataset_version_id)

    assert action.status == "approved"
    assert authority.ready(seeded.dataset_version_id) is True


def test_seed_rejects_manifest_content_mismatch_before_storage_write(
    migrated_engine: Engine,
) -> None:
    bundle = load_bundle(FIXTURE_ROOT)
    tampered_file = replace(bundle.files[0], content=b"tampered")
    tampered_bundle = replace(
        bundle,
        files=(tampered_file, *bundle.files[1:]),
    )
    storage = MemoryStorage()

    with pytest.raises(ValueError, match="synthetic_manifest_content_mismatch"):
        seed_demo(
            tampered_bundle,
            PostgresUnitOfWork(migrated_engine),
            storage,
        )

    assert storage.put_calls == 0


def test_seed_compensates_staging_when_promotion_fails(
    migrated_engine: Engine,
) -> None:
    storage = FailingPromoteStorage()

    with pytest.raises(RuntimeError, match="injected_promotion_failure"):
        seed_demo(
            load_bundle(FIXTURE_ROOT),
            PostgresUnitOfWork(migrated_engine),
            storage,
        )

    assert storage.objects == {}


def test_seed_compensates_created_blobs_when_database_commit_fails(
    migrated_engine: Engine,
) -> None:
    storage = MemoryStorage()

    with pytest.raises(IntegrityError):
        seed_demo(
            load_bundle(FIXTURE_ROOT),
            PostgresUnitOfWork(migrated_engine),
            storage,
        )

    assert storage.objects == {}
