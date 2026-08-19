from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
import json
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.datasets import DatasetRepository
from src.repositories.operators import OperatorRepository
from src.repositories.storage_objects import StorageObjectRepository
from src.services.analysis_service import AnalysisInvalid, AnalysisService
from src.services.store_scope import StoreScopeInvalid, StoreScopeResolver
from src.storage.keys import dataset_object_key
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID


def test_store_scope_resolves_catalog_order_default_all_and_one_store(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    seeded = seed_demo(
        generate_demo(seed=20260816),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 16, tzinfo=UTC),
    )
    resolver = StoreScopeResolver(migrated_engine, storage, WORKSPACE_ID)

    catalog = resolver.catalog(seeded.dataset_version_id)
    all_stores = resolver.resolve(seeded.dataset_version_id, None)
    all_stores_from_empty_selection = resolver.resolve(
        seeded.dataset_version_id,
        [],
    )
    launch = resolver.resolve(
        seeded.dataset_version_id,
        ("SYNTH-STORE-02",),
    )

    assert [item.store_id for item in catalog] == [
        "SYNTH-STORE-01",
        "SYNTH-STORE-02",
    ]
    assert catalog[1].display_name_en == "Brazil Launch Store"
    assert catalog[1].display_name_zh == "巴西新店"
    assert all_stores.kind == "all"
    assert all_stores.store_ids == ("SYNTH-STORE-01", "SYNTH-STORE-02")
    assert all_stores_from_empty_selection == all_stores
    assert launch.kind == "single"
    assert launch.store_ids == ("SYNTH-STORE-02",)


def test_store_scope_rejects_unknown_or_multiple_requested_stores(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    seeded = seed_demo(
        generate_demo(seed=20260816),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 16, tzinfo=UTC),
    )
    resolver = StoreScopeResolver(migrated_engine, storage, WORKSPACE_ID)

    with pytest.raises(StoreScopeInvalid) as unknown:
        resolver.resolve(seeded.dataset_version_id, ("NOT-IN-CATALOG",))
    with pytest.raises(StoreScopeInvalid):
        resolver.resolve(
            seeded.dataset_version_id,
            ("SYNTH-STORE-02", "SYNTH-STORE-01"),
        )

    assert unknown.value.code == "STORE_SCOPE_INVALID"


def test_store_catalog_falls_back_to_exact_stores_rows(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    version_id = _seed_payload(
        migrated_engine,
        storage,
        {
            "schema_version": "canonical.import.v1",
            "tables": {
                "stores": [
                    {
                        "store_id": "STORE-B",
                        "display_name_en": "Second",
                        "display_name_zh": "第二店",
                        "currency": "BRL",
                        "opened_on": "2026-07-08",
                        "lifecycle": "new",
                        "has_data": True,
                    },
                    {
                        "store_id": "STORE-A",
                        "display_name_en": "Main",
                        "display_name_zh": "主店",
                        "currency": "BRL",
                        "opened_on": "2026-05-01",
                        "lifecycle": "established",
                        "has_data": True,
                    },
                ]
            },
        },
    )

    catalog = StoreScopeResolver(
        migrated_engine,
        storage,
        WORKSPACE_ID,
    ).catalog(version_id)

    assert [item.store_id for item in catalog] == ["STORE-B", "STORE-A"]
    assert catalog[0].opened_on.isoformat() == "2026-07-08"


def test_analysis_rejects_store_outside_the_version_catalog(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    seeded = seed_demo(
        generate_demo(seed=20260816),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 16, tzinfo=UTC),
    )
    service = AnalysisService(migrated_engine, storage, WORKSPACE_ID)

    with pytest.raises(AnalysisInvalid, match="analysis_store_scope_invalid"):
        service.plan(
            "sales_ads",
            seeded.dataset_version_id,
            {
                "store_id": "NOT-IN-CATALOG",
                "period_start": "2026-07-01",
                "period_end": "2026-07-31",
                "currency": "BRL",
            },
        )


def _seed_payload(
    engine: Engine,
    storage: MemoryWorkflowStorage,
    payload: dict[str, object],
):
    now = datetime(2026, 8, 16, tzinfo=UTC)
    content = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = sha256(content).hexdigest()
    staged = storage.put_staging(
        BytesIO(content),
        max_bytes=len(content),
        media_type="application/json",
    )
    version_id = uuid4()
    available = storage.promote(
        staged.key,
        dataset_object_key(WORKSPACE_ID, str(version_id), digest),
        digest,
    )
    with PostgresUnitOfWork(engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
        datasets = DatasetRepository(uow.connection)
        series = datasets.create_series(
            workspace_id=WORKSPACE_ID,
            name=f"scope-{version_id}",
            now=now,
        )
        version = datasets.create_version(
            series_id=series.id,
            workspace_id=WORKSPACE_ID,
            source_workflow_id=None,
            version_number=1,
            schema_version="canonical.import.v1",
            content_sha256=digest,
            now=now,
            version_id=version_id,
        )
        stored = StorageObjectRepository(uow.connection).create_available(
            object_id=uuid4(),
            workspace_id=WORKSPACE_ID,
            available=available,
            purpose="normalized_dataset",
            media_type="application/json",
            now=now,
        )
        datasets.create_artifact(
            dataset_version_id=version.id,
            storage_object_id=stored.id,
            artifact_kind="canonical_bundle",
            sha256=digest,
            now=now,
        )
    storage.delete(staged.key, expected_etag=staged.etag)
    return version_id
