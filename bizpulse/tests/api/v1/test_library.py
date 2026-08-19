from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from api.main import create_app
from src.db.unit_of_work import PostgresUnitOfWork
from src.services.library_service import LibraryService
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.auth_support import (
    LOGIN_NAME,
    PASSWORD,
    build_container,
    fast_password_hasher,
    initial_clock,
    seed_operator,
)
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID

ORIGIN = "http://testserver"


def test_operator_library_is_authenticated_and_version_explicit(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    seed_operator(migrated_engine, fast_password_hasher())
    seeded = seed_demo(
        generate_demo(seed=20260816),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 16, tzinfo=UTC),
    )
    container = replace(
        build_container(migrated_engine, initial_clock()),
        workflow_storage=storage,
        library_service=LibraryService(migrated_engine, storage, WORKSPACE_ID),
    )

    with TestClient(create_app(container=container)) as client:
        assert client.get("/api/v1/library").status_code == 401
        login = client.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        listing = client.get("/api/v1/library")
        detail = client.get(f"/api/v1/library/{seeded.dataset_version_id}")
        table_page = client.get(
            f"/api/v1/library/{seeded.dataset_version_id}/tables/daily_sales"
            "?page=13&page_size=50"
        )
        launch_detail = client.get(
            f"/api/v1/library/{seeded.dataset_version_id}"
            "?store_id=SYNTH-STORE-02"
        )
        launch_page = client.get(
            f"/api/v1/library/{seeded.dataset_version_id}/tables/daily_sales"
            "?page=2&page_size=50&store_id=SYNTH-STORE-02"
        )
        invalid_store = client.get(
            f"/api/v1/library/{seeded.dataset_version_id}"
            "?store_id=NOT-IN-CATALOG"
        )
        multiple_stores = client.get(
            f"/api/v1/library/{seeded.dataset_version_id}"
            "?store_id=SYNTH-STORE-01&store_id=SYNTH-STORE-02"
        )
        invalid_size = client.get(
            f"/api/v1/library/{seeded.dataset_version_id}/tables/daily_sales"
            "?page_size=30"
        )
        missing_table = client.get(
            f"/api/v1/library/{seeded.dataset_version_id}/tables/not_a_table"
        )

    assert login.status_code == 201
    assert listing.status_code == 200
    assert listing.json()["versions"][0]["version_number"] == 1
    assert detail.status_code == 200
    assert detail.json()["dataset_version_id"] == str(seeded.dataset_version_id)
    assert [item["store_id"] for item in detail.json()["store_catalog"]] == [
        "SYNTH-STORE-01",
        "SYNTH-STORE-02",
    ]
    assert detail.json()["resolved_scope"] == {
        "kind": "all",
        "store_ids": ["SYNTH-STORE-01", "SYNTH-STORE-02"],
    }
    assert table_page.status_code == 200
    assert table_page.json()["role"] == "daily_sales"
    assert table_page.json()["total_rows"] == 624
    assert table_page.json()["total_pages"] == 13
    assert len(table_page.json()["rows"]) == 24
    assert table_page.json()["scope_kind"] == "store"
    assert launch_detail.status_code == 200
    assert launch_detail.json()["resolved_scope"] == {
        "kind": "single",
        "store_ids": ["SYNTH-STORE-02"],
    }
    assert launch_page.status_code == 200
    assert launch_page.json()["total_rows"] == 72
    assert len(launch_page.json()["rows"]) == 22
    assert invalid_store.status_code == 400
    assert invalid_store.json() == {"code": "STORE_SCOPE_INVALID"}
    assert multiple_stores.status_code == 400
    assert multiple_stores.json() == {"code": "STORE_SCOPE_INVALID"}
    assert invalid_size.status_code == 422
    assert missing_table.status_code == 404
    assert missing_table.json() == {"code": "LIBRARY_TABLE_NOT_FOUND"}
    serialized = detail.text
    assert "object_key" not in serialized
    assert "content_sha256" not in serialized


def test_operator_library_table_page_requires_authentication(
    migrated_engine: Engine,
) -> None:
    container = replace(
        build_container(migrated_engine, initial_clock()),
        library_service=LibraryService(migrated_engine, None, WORKSPACE_ID),
    )

    with TestClient(create_app(container=container)) as client:
        response = client.get(
            f"/api/v1/library/{uuid4()}/tables/daily_sales"
        )

    assert response.status_code == 401
