from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from api.main import create_app
from src.services.dataset_service import DatasetService
from src.services.analysis_service import AnalysisService
from src.services.import_service import ImportService
from src.services.public_release_service import PublicReleaseService
from tests.auth_support import (
    LOGIN_NAME,
    PASSWORD,
    build_container,
    fast_password_hasher,
    initial_clock,
    seed_public_release,
    seed_operator,
)
from tests.import_support import WORKSPACE_ID, MemoryWorkflowStorage, fixture_bytes

ORIGIN = "http://testserver"
XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _client(engine: Engine) -> TestClient:
    clock = initial_clock()
    storage = MemoryWorkflowStorage()
    base = build_container(engine, clock)
    analyses = AnalysisService(engine, storage, WORKSPACE_ID, clock=clock)
    container = replace(
        base,
        workflow_storage=storage,
        import_service=ImportService(
            engine=engine,
            storage=storage,
            workspace_id=WORKSPACE_ID,
            idempotency_pepper="test-import-idempotency-pepper",
            clock=clock,
        ),
        dataset_service=DatasetService(engine, WORKSPACE_ID),
        analysis_service=analyses,
        public_release_service=PublicReleaseService(
            engine,
            WORKSPACE_ID,
            idempotency_pepper="test-release-idempotency-pepper",
            clock=clock,
            analysis_service=analyses,
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


def test_import_api_runs_explicit_six_phase_workflow_and_manual_publish(
    migrated_engine: Engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    with _client(migrated_engine) as client:
        csrf = _login(client)
        mutation_headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}

        created = client.post(
            "/api/v1/import-workflows",
            headers={**mutation_headers, "Idempotency-Key": "workflow-api-1"},
            json={},
        )
        workflow = created.json()["workflow"]
        uploaded = client.post(
            f"/api/v1/import-workflows/{workflow['id']}/uploads",
            params={"filename": "operator_import.xlsx"},
            headers={
                **mutation_headers,
                "Idempotency-Key": "upload-api-1",
                "Content-Type": XLSX_MEDIA_TYPE,
            },
            content=fixture_bytes("operator_import.xlsx"),
        )
        recognized = client.post(
            f"/api/v1/import-workflows/{workflow['id']}/uploads/"
            f"{uploaded.json()['upload']['id']}/recognition",
            headers=mutation_headers,
            json={"expected_revision": uploaded.json()["workflow"]["revision"]},
        )
        mapped = client.put(
            f"/api/v1/import-workflows/{workflow['id']}/uploads/"
            f"{uploaded.json()['upload']['id']}/mapping",
            headers=mutation_headers,
            json={
                "expected_revision": recognized.json()["workflow"]["revision"],
                "expected_mapping_revision": recognized.json()["upload"][
                    "mapping_revision"
                ],
                "mapping": recognized.json()["upload"]["recognition"][
                    "suggested_mapping"
                ],
            },
        )
        standardized = client.post(
            f"/api/v1/import-workflows/{workflow['id']}/uploads/"
            f"{uploaded.json()['upload']['id']}/standardization",
            headers=mutation_headers,
            json={"expected_revision": mapped.json()["workflow"]["revision"]},
        )
        replayed_upload = client.post(
            f"/api/v1/import-workflows/{workflow['id']}/uploads",
            params={"filename": "operator_import.xlsx"},
            headers={
                **mutation_headers,
                "Idempotency-Key": "upload-api-1",
                "Content-Type": XLSX_MEDIA_TYPE,
            },
            content=fixture_bytes("operator_import.xlsx"),
        )
        preview = client.get(
            f"/api/v1/import-workflows/{workflow['id']}/uploads/"
            f"{uploaded.json()['upload']['id']}/preview",
        )
        plan = client.get(
            f"/api/v1/import-workflows/{workflow['id']}/commit-plan"
        )
        committed = client.post(
            f"/api/v1/import-workflows/{workflow['id']}/commit",
            headers={**mutation_headers, "Idempotency-Key": "commit-api-1"},
            json={
                "expected_revision": standardized.json()["workflow"]["revision"]
            },
        )
        replayed_commit = client.post(
            f"/api/v1/import-workflows/{workflow['id']}/commit",
            headers={**mutation_headers, "Idempotency-Key": "commit-api-1"},
            json={
                "expected_revision": standardized.json()["workflow"]["revision"]
            },
        )
        replayed_created = client.post(
            "/api/v1/import-workflows",
            headers={**mutation_headers, "Idempotency-Key": "workflow-api-1"},
            json={},
        )
        versions = client.get("/api/v1/datasets/versions")
        published = client.post(
            f"/api/v1/datasets/versions/"
            f"{committed.json()['dataset_version_id']}/publish",
            headers={
                **mutation_headers,
                "Idempotency-Key": "publish-import-api-1",
            },
            json={"expected_current_id": None},
        )

    assert created.status_code == 201
    assert created.json()["workflow"]["source_kind"] == "operator_upload"
    assert created.json()["workflow"]["source_confirmed_synthetic"] is False
    assert uploaded.status_code == 201
    assert recognized.status_code == 200
    assert mapped.status_code == 200
    assert standardized.status_code == 200
    assert replayed_upload.json() == uploaded.json()
    assert preview.status_code == 200
    assert preview.json()["records"]
    assert plan.status_code == 200
    assert plan.json()["ready"] is True
    assert committed.status_code == 201
    assert replayed_commit.json() == committed.json()
    assert replayed_created.json() == created.json()
    assert versions.status_code == 200
    assert versions.json()["versions"][0]["id"] == committed.json()[
        "dataset_version_id"
    ]
    assert published.status_code == 200, published.text
    assert published.json()["dataset_version_id"] == committed.json()[
        "dataset_version_id"
    ]


def test_import_api_is_operator_csrf_protected_and_redacts_boundary_input(
    migrated_engine: Engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    seed_public_release(migrated_engine)
    with _client(migrated_engine) as client:
        unauthenticated = client.post(
            "/api/v1/import-workflows",
            headers={"Idempotency-Key": "not-authorized"},
            json={},
        )
        viewer = client.post("/api/demo/sessions", headers={"Origin": ORIGIN})
        viewer_attempt = client.post(
            "/api/v1/import-workflows",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": viewer.json()["csrf_token"],
                "Idempotency-Key": "viewer-not-authorized",
            },
            json={},
        )
        csrf = _login(client)
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "workflow-boundary",
        }
        rejected = client.post(
            "/api/v1/import-workflows",
            headers=headers,
            json={"source_confirmed_synthetic": True},
        )

    assert unauthenticated.status_code == 401
    assert viewer.status_code == 201
    assert viewer_attempt.status_code == 401
    assert rejected.status_code == 422
    assert rejected.json() == {"code": "REQUEST_VALIDATION_FAILED"}
    assert "source_confirmed_synthetic" not in rejected.text


def test_commit_plan_returns_bounded_structured_conflicts(
    migrated_engine: Engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    content = (
        "date,store_id,sku_id,spend_brl,impressions,clicks,"
        "attributed_orders\n"
        "2026-07-01,BR-STORE-01,SKU-001,10.50,100,10,2\n"
        "2026-07-01,BR-STORE-01,SKU-001,11.50,100,10,2\n"
    ).encode()
    with _client(migrated_engine) as client:
        csrf = _login(client)
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        created = client.post(
            "/api/v1/import-workflows",
            headers={**headers, "Idempotency-Key": "conflict-api-workflow"},
            json={},
        ).json()["workflow"]
        uploaded = client.post(
            f"/api/v1/import-workflows/{created['id']}/uploads",
            params={"filename": "conflict.csv"},
            headers={
                **headers,
                "Idempotency-Key": "conflict-api-upload",
                "Content-Type": "text/csv",
            },
            content=content,
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
                "expected_mapping_revision": recognized["upload"][
                    "mapping_revision"
                ],
                "mapping": recognized["upload"]["recognition"][
                    "suggested_mapping"
                ],
            },
        ).json()
        standardized = client.post(
            f"/api/v1/import-workflows/{created['id']}/uploads/"
            f"{uploaded['upload']['id']}/standardization",
            headers=headers,
            json={"expected_revision": mapped["workflow"]["revision"]},
        ).json()

        plan = client.get(
            f"/api/v1/import-workflows/{created['id']}/commit-plan"
        )
        commit = client.post(
            f"/api/v1/import-workflows/{created['id']}/commit",
            headers={**headers, "Idempotency-Key": "conflict-api-commit"},
            json={
                "expected_revision": standardized["workflow"]["revision"]
            },
        )

    assert plan.status_code == 200
    payload = plan.json()
    assert payload["ready"] is False
    assert payload["content_sha256"] is None
    assert payload["dedupe"] == {
        "rows_read": 2,
        "rows_retained": 1,
        "duplicates_removed": 0,
        "conflicts": 1,
        "per_role": {
            "shopee_advertising": {
                "rows_read": 2,
                "rows_retained": 1,
                "duplicates_removed": 0,
                "conflicts": 1,
            }
        },
    }
    assert len(payload["conflicts"]) == 1
    assert payload["conflicts"][0]["fields"] == ["spend_brl"]
    assert payload["conflicts_truncated"] is False
    assert payload["conflict_download_url"].endswith(
        f"/{created['id']}/conflicts.csv"
    )
    assert commit.status_code == 409
    assert commit.json() == {"code": "IMPORT_DEDUPE_CONFLICT"}
