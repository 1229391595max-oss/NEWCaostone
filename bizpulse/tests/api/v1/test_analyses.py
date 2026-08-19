from dataclasses import replace
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from api.main import create_app
from src.services.analysis_service import AnalysisService
from tests.auth_support import (
    LOGIN_NAME,
    PASSWORD,
    build_container,
    fast_password_hasher,
    initial_clock,
    seed_operator,
)
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID
from tests.integration.test_analysis_vertical import _seed_version

ORIGIN = "http://testserver"


def test_operator_runs_and_reads_hash_verified_analysis_api(
    migrated_engine: Engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    storage = MemoryWorkflowStorage()
    version_id = _seed_version(migrated_engine, storage)
    clock = initial_clock()
    service = AnalysisService(migrated_engine, storage, WORKSPACE_ID, clock=clock)
    container = replace(
        build_container(migrated_engine, clock),
        workflow_storage=storage,
        analysis_service=service,
    )
    with TestClient(create_app(container=container)) as client:
        login = client.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": login.json()["csrf_token"],
            "Idempotency-Key": "analysis-api-1",
        }
        created = client.post(
            "/api/v1/analyses/runs",
            headers=headers,
            json={
                "kind": "sales_ads",
                "dataset_version_id": str(version_id),
                "scope": {
                    "store_id": "SYNTH-STORE-01",
                    "period_start": "2026-07-01",
                    "period_end": "2026-07-30",
                    "currency": "BRL",
                },
            },
        )
        run_id = created.json()["run_id"]
        run = client.get(f"/api/v1/analyses/{run_id}")
        snapshot = client.get(f"/api/v1/analyses/{run_id}/snapshot")
        evidence_id = str(service.get_evidence(UUID(created.json()["run_id"]))[0].id)
        evidence = client.get(
            f"/api/v1/analyses/{run_id}/evidence/{evidence_id}"
        )

    assert created.status_code == 201
    assert created.json()["status"] == "completed"
    assert run.status_code == 200
    assert run.json()["artifact_sha256"] == created.json()["artifact_sha256"]
    assert snapshot.status_code == 200
    assert snapshot.json()["input_hash"] == created.json()["input_hash"]
    assert evidence.status_code == 200
    assert evidence.json()["evidence_state"] in {
        "measured",
        "derived",
        "assumed",
        "unknown",
    }
    assert "object_key" not in evidence.text


def test_analysis_mutation_requires_operator_and_csrf(migrated_engine: Engine) -> None:
    storage = MemoryWorkflowStorage()
    version_id = _seed_version(migrated_engine, storage)
    service = AnalysisService(migrated_engine, storage, WORKSPACE_ID)
    container = replace(
        build_container(migrated_engine, initial_clock()),
        workflow_storage=storage,
        analysis_service=service,
    )
    with TestClient(create_app(container=container)) as client:
        rejected = client.post(
            "/api/v1/analyses/runs",
            headers={"Idempotency-Key": "not-authorized"},
            json={
                "kind": "sales_ads",
                "dataset_version_id": str(version_id),
                "scope": {"period_end": "2026-07-30", "currency": "BRL"},
            },
        )

    assert rejected.status_code == 401
