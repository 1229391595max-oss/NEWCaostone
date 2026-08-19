from __future__ import annotations

import csv
from dataclasses import replace
from io import StringIO

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from api.main import create_app
from src.services.import_service import ImportService
from tests.auth_support import (
    LOGIN_NAME,
    PASSWORD,
    build_container,
    fast_password_hasher,
    initial_clock,
    seed_operator,
)
from tests.import_support import WORKSPACE_ID, MemoryWorkflowStorage

ORIGIN = "http://testserver"


def _client(engine: Engine) -> TestClient:
    clock = initial_clock()
    storage = MemoryWorkflowStorage()
    container = replace(
        build_container(engine, clock),
        workflow_storage=storage,
        import_service=ImportService(
            engine=engine,
            storage=storage,
            workspace_id=WORKSPACE_ID,
            idempotency_pepper="test-import-idempotency-pepper",
            clock=clock,
        ),
    )
    return TestClient(create_app(container=container))


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/operator/login",
        headers={"Origin": ORIGIN},
        json={"login_name": LOGIN_NAME, "password": PASSWORD},
    )
    assert response.status_code == 201
    return response.json()["csrf_token"]


def _prepare_conflicts(client: TestClient, csrf: str) -> str:
    headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
    rows = [
        "date,store_id,sku_id,spend_brl,impressions,clicks,"
        "attributed_orders"
    ]
    for index in range(51):
        sku_id = "\tSKU-000" if index == 0 else f"SKU-{index:03d}"
        rows.extend(
            (
                f"2026-07-01,BR-STORE-01,{sku_id},10.50,100,10,2",
                f"2026-07-01,BR-STORE-01,{sku_id},11.50,100,10,2",
            )
        )
    created = client.post(
        "/api/v1/import-workflows",
        headers={**headers, "Idempotency-Key": "csv-export-workflow"},
        json={},
    ).json()["workflow"]
    uploaded = client.post(
        f"/api/v1/import-workflows/{created['id']}/uploads",
        params={"filename": "conflicts.csv"},
        headers={
            **headers,
            "Idempotency-Key": "csv-export-upload",
            "Content-Type": "text/csv",
        },
        content=("\n".join(rows) + "\n").encode(),
    ).json()
    recognized = client.post(
        f"/api/v1/import-workflows/{created['id']}/uploads/"
        f"{uploaded['upload']['id']}/recognition",
        headers=headers,
        json={"expected_revision": uploaded["workflow"]["revision"]},
    ).json()
    mapped = client.put(
        f"/api/v1/import-workflows/{created['id']}/uploads/"
        f"{uploaded['upload']['id']}/mapping",
        headers=headers,
        json={
            "expected_revision": recognized["workflow"]["revision"],
            "expected_mapping_revision": recognized["upload"]["mapping_revision"],
            "mapping": recognized["upload"]["recognition"]["suggested_mapping"],
        },
    ).json()
    standardized = client.post(
        f"/api/v1/import-workflows/{created['id']}/uploads/"
        f"{uploaded['upload']['id']}/standardization",
        headers=headers,
        json={"expected_revision": mapped["workflow"]["revision"]},
    )
    assert standardized.status_code == 200, standardized.text
    return created["id"]


def test_conflict_csv_is_complete_private_safe_and_operator_only(
    migrated_engine: Engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    with _client(migrated_engine) as client:
        unauthenticated = client.get(
            "/api/v1/import-workflows/00000000-0000-0000-0000-000000000000/"
            "conflicts.csv"
        )
        csrf = _login(client)
        workflow_id = _prepare_conflicts(client, csrf)
        plan = client.get(
            f"/api/v1/import-workflows/{workflow_id}/commit-plan"
        )
        exported = client.get(
            f"/api/v1/import-workflows/{workflow_id}/conflicts.csv"
        )

    assert unauthenticated.status_code == 401
    assert plan.status_code == 200
    assert len(plan.json()["conflicts"]) == 50
    assert plan.json()["conflicts_truncated"] is True
    assert exported.status_code == 200
    assert exported.headers["cache-control"] == "private, no-store"
    assert exported.headers["content-type"].startswith("text/csv")
    assert "attachment" in exported.headers["content-disposition"]
    records = list(csv.DictReader(StringIO(exported.text)))
    assert len(records) == 51
    assert ImportService._escape_csv_cell("=1+1") == "'=1+1"
    assert ImportService._escape_csv_cell("\tformula") == "'\tformula"
    lowered = exported.text.lower()
    assert "sha256" not in lowered
    assert "object_key" not in lowered
    assert "/staging/" not in lowered
    assert "/versions/" not in lowered
