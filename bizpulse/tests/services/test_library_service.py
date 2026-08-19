from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.services.library_service import LibraryService
from src.services import library_service as library_module
from src.services.canonical_contracts import StoreScope
from src.services.store_scope import StoreScopeInvalid
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID


def test_library_lists_and_previews_existing_authoritative_dataset(
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
    service = LibraryService(migrated_engine, storage, WORKSPACE_ID)

    versions = service.list_versions()
    detail = service.get_version(seeded.dataset_version_id, preview_limit=4)

    assert [item.dataset_version_id for item in versions] == [
        seeded.dataset_version_id
    ]
    summary = versions[0]
    assert summary.version_number == 1
    assert summary.lifecycle == "current"
    assert summary.period_start.isoformat() == "2026-05-01"
    assert summary.period_end.isoformat() == "2026-07-31"
    assert summary.stores == 2
    assert summary.skus == 6
    assert summary.row_count > 0
    assert "daily_sales" in summary.source_roles
    assert summary.quality.status == "complete"
    assert summary.quality.missing_roles == ()
    assert detail.dataset_version_id == seeded.dataset_version_id
    assert [item.store_id for item in detail.store_catalog] == [
        "SYNTH-STORE-01",
        "SYNTH-STORE-02",
    ]
    assert detail.resolved_scope == StoreScope(
        "all",
        ("SYNTH-STORE-01", "SYNTH-STORE-02"),
    )
    assert all(len(table.preview) <= 4 for table in detail.tables)
    assert all("object_key" not in row for table in detail.tables for row in table.preview)
    assert all(not hasattr(item, "storage_object_id") for item in detail.provenance)


def test_library_detail_is_exact_version_and_bounded(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    first = seed_demo(
        generate_demo(seed=20260815),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 15, tzinfo=UTC),
    )
    second = seed_demo(
        generate_demo(seed=20260816),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 16, tzinfo=UTC),
    )
    service = LibraryService(migrated_engine, storage, WORKSPACE_ID)

    detail = service.get_version(first.dataset_version_id, preview_limit=3)

    assert detail.dataset_version_id == first.dataset_version_id
    assert detail.dataset_version_id != second.dataset_version_id
    assert len(detail.tables) <= 32
    assert len(detail.provenance) <= 20


def test_library_table_page_returns_complete_bounded_safe_rows(
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
    service = LibraryService(migrated_engine, storage, WORKSPACE_ID)

    first = service.get_table_page(
        seeded.dataset_version_id,
        "daily_sales",
        page=1,
        page_size=50,
    )
    last = service.get_table_page(
        seeded.dataset_version_id,
        "daily_sales",
        page=13,
        page_size=50,
    )

    assert first.role == "daily_sales"
    assert first.page == 1
    assert first.page_size == 50
    assert first.total_rows == 624
    assert first.total_pages == 13
    assert len(first.rows) == 50
    assert len(last.rows) == 24
    assert first.scope_kind == "store"
    assert first.columns == tuple(sorted(first.columns))
    assert all(
        "object_key" not in row and "sha256" not in row and "digest" not in row
        for row in first.rows
    )


def test_library_table_page_rejects_unknown_role_and_unbounded_page_size(
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
    service = LibraryService(migrated_engine, storage, WORKSPACE_ID)

    with pytest.raises(RuntimeError) as missing:
        service.get_table_page(seeded.dataset_version_id, "not_a_table")
    assert missing.value.code == "LIBRARY_TABLE_NOT_FOUND"
    with pytest.raises(ValueError, match="LIBRARY_PAGE_SIZE_INVALID"):
        service.get_table_page(
            seeded.dataset_version_id,
            "daily_sales",
            page_size=30,
        )
    with pytest.raises(ValueError, match="LIBRARY_PAGE_SIZE_INVALID"):
        service.get_table_page(
            seeded.dataset_version_id,
            "daily_sales",
            page_size=50.0,
        )


def test_library_single_store_filters_scoped_rows_and_keeps_shared_tables(
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
    service = LibraryService(migrated_engine, storage, WORKSPACE_ID)

    detail = service.get_version(
        seeded.dataset_version_id,
        preview_limit=5,
        store_ids=("SYNTH-STORE-02",),
    )
    sales = next(item for item in detail.tables if item.role == "daily_sales")
    catalog = next(item for item in detail.tables if item.role == "product_catalog")
    expenses = next(
        item for item in detail.tables if item.role == "operating_expense"
    )
    sales_page = service.get_table_page(
        seeded.dataset_version_id,
        "daily_sales",
        page=2,
        page_size=50,
        store_ids=("SYNTH-STORE-02",),
    )

    assert detail.resolved_scope == StoreScope("single", ("SYNTH-STORE-02",))
    assert sales.scope_kind == "store"
    assert sales.row_count == 72
    assert all(row["store_id"] == "SYNTH-STORE-02" for row in sales.preview)
    assert catalog.scope_kind == "shared"
    assert catalog.row_count == 6
    assert expenses.scope_kind == "store"
    assert expenses.row_count == 4
    assert sales_page.total_rows == 72
    assert len(sales_page.rows) == 22

    with pytest.raises(StoreScopeInvalid):
        service.get_version(
            seeded.dataset_version_id,
            store_ids=("NOT-IN-CATALOG",),
        )


def test_library_table_page_keeps_all_safe_columns_and_sanitizes_only_the_slice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = LibraryService.__new__(LibraryService)
    wide = {f"field_{index:02d}": index for index in range(45)}
    rows = tuple(
        {
            **wide,
            "row_number": index,
            "source_classification": "pure_synthetic",
            "metadata": {
                "label": f"row-{index}",
                "sha256": "hidden",
                "nested": [{"object_key": "hidden", "safe": "visible"}],
            },
        }
        for index in range(100)
    )
    monkeypatch.setattr(service, "_load_table", lambda _version_id, _role: rows, raising=False)
    service._store_scopes = _AllScopeResolver()
    sanitized = []
    original_safe_row = library_module._safe_row

    def track_safe_row(row):
        sanitized.append(row["row_number"])
        return original_safe_row(row)

    monkeypatch.setattr(library_module, "_safe_row", track_safe_row)

    page = service.get_table_page(uuid4(), "wide_table", page=2, page_size=25)

    assert len(page.columns) > 40
    assert page.rows[0]["row_number"] == 25
    assert sanitized == list(range(25, 50))
    assert "source_classification" not in page.rows[0]
    assert "sha256" not in page.rows[0]["metadata"]
    assert page.rows[0]["metadata"]["nested"] == [{"safe": "visible"}]


class _AllScopeResolver:
    def resolve(self, _version_id, _store_ids):
        return StoreScope("all", ())
