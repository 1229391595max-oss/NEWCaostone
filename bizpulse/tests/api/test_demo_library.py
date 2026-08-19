from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from api.main import create_app
from src.db.unit_of_work import PostgresUnitOfWork
from src.services.library_service import LibraryService
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.auth_support import (
    activate_demo_data,
    build_container,
    fast_password_hasher,
    initial_clock,
    seed_operator,
)
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID

ORIGIN = "http://testserver"


def test_viewer_library_is_activation_gated_and_pinned_to_shared_release(
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
        created = client.post("/api/demo/sessions", headers={"Origin": ORIGIN})
        blocked = client.get("/api/demo/library/current")
        blocked_table = client.get(
            "/api/demo/library/current/tables/daily_sales?page=1&page_size=50"
        )
        activate_demo_data(client, created)
        response = client.get("/api/demo/library/current")
        launch = client.get(
            "/api/demo/library/current?store_id=SYNTH-STORE-02"
        )
        table_page = client.get(
            "/api/demo/library/current/tables/daily_sales"
            "?page=2&page_size=50&store_id=SYNTH-STORE-02"
        )
        invalid_store = client.get(
            "/api/demo/library/current?store_id=NOT-IN-CATALOG"
        )
        operator_history = client.get("/api/v1/library")
        mutation = client.post("/api/demo/library/current")

    assert blocked.status_code == 409
    assert blocked_table.status_code == 409
    assert response.status_code == 200
    assert response.json()["dataset_version_id"] == str(seeded.dataset_version_id)
    assert launch.status_code == 200
    assert launch.json()["resolved_scope"] == {
        "kind": "single",
        "store_ids": ["SYNTH-STORE-02"],
    }
    assert operator_history.status_code == 401
    assert mutation.status_code == 405
    assert table_page.status_code == 200
    assert table_page.json()["role"] == "daily_sales"
    assert table_page.json()["total_rows"] == 72
    assert len(table_page.json()["rows"]) == 22
    assert invalid_store.status_code == 400
    assert invalid_store.json() == {"code": "STORE_SCOPE_INVALID"}
    assert "object_key" not in response.text
