from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from api.main import create_app
from src.db.unit_of_work import PostgresUnitOfWork
from src.services.dataset_export_service import DatasetExportService
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


def test_dataset_export_routes_are_operator_only_and_download_real_xlsx(
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
    library = LibraryService(migrated_engine, storage, WORKSPACE_ID)
    exports = DatasetExportService(migrated_engine, storage, WORKSPACE_ID, library)
    container = replace(
        build_container(migrated_engine, initial_clock()),
        workflow_storage=storage,
        library_service=library,
        dataset_export_service=exports,
    )

    path = f"/api/v1/datasets/versions/{seeded.dataset_version_id}/exports"
    with TestClient(create_app(container=container)) as client:
        assert client.post(path, json={"format": "xlsx"}).status_code == 401
        login = client.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        created = client.post(
            path,
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": login.json()["csrf_token"],
                "Idempotency-Key": "api-dataset-export",
            },
            json={"format": "xlsx"},
        )
        export_id = created.json()["id"]
        downloaded = client.get(f"{path}/{export_id}/download")

    assert created.status_code == 200
    assert downloaded.status_code == 200
    assert downloaded.content[:2] == b"PK"
    assert "object_key" not in created.text
    assert "sha256" not in created.text
