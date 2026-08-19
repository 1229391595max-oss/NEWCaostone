from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine

from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.services.dataset_export_service import DatasetExportService
from src.services.library_service import LibraryService
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID


def test_dataset_export_is_exact_bounded_and_idempotent(migrated_engine: Engine) -> None:
    storage = MemoryWorkflowStorage()
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    seeded = seed_demo(
        generate_demo(seed=20260816),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 16, tzinfo=UTC),
    )
    library = LibraryService(migrated_engine, storage, WORKSPACE_ID)
    service = DatasetExportService(migrated_engine, storage, WORKSPACE_ID, library)

    created = service.generate(
        seeded.dataset_version_id,
        idempotency_key="dataset-export-1",
    )
    replay = service.generate(
        seeded.dataset_version_id,
        idempotency_key="dataset-export-1",
    )
    content = service.open(seeded.dataset_version_id, created.id)

    assert replay == created
    assert created.status == "available"
    assert created.byte_count == len(content)
    assert content[:2] == b"PK"
    detail = library.get_version(seeded.dataset_version_id)
    assert detail.export_available is True
    assert detail.exports[0].id == created.id
