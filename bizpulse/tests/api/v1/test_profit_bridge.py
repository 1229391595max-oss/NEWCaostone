from dataclasses import replace

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from api.main import create_app
from src.db.unit_of_work import PostgresUnitOfWork
from src.services.analysis_service import AnalysisService
from src.services.demo_session_service import DemoSessionService
from src.services.profit_bridge_service import ProfitBridgeService
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.auth_support import (
    LOGIN_NAME,
    PASSWORD,
    SESSION_PEPPER,
    activate_demo_data,
    build_container,
    fast_password_hasher,
    initial_clock,
    seed_operator,
)
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID

ORIGIN = "http://testserver"


def _payload(dataset_version_id: str, sku_ids=None) -> dict[str, object]:
    scope: dict[str, object] = {
        "store_id": "SYNTH-STORE-01",
        "currency": "BRL",
    }
    if sku_ids is not None:
        scope["sku_ids"] = sku_ids
    return {
        "dataset_version_id": dataset_version_id,
        "current_period": {
            "period_start": "2026-07-01",
            "period_end": "2026-07-31",
        },
        "comparison_period": {
            "period_start": "2026-06-01",
            "period_end": "2026-06-30",
        },
        "scope": scope,
    }


def test_operator_bridge_flow_and_exact_pinned_viewer_read(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    seed_operator(migrated_engine, fast_password_hasher())
    clock = initial_clock()
    seeded = seed_demo(
        generate_demo(),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=clock(),
    )
    analyses = AnalysisService(migrated_engine, storage, WORKSPACE_ID, clock=clock)
    bridges = ProfitBridgeService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        analysis_service=analyses,
        clock=clock,
    )
    container = replace(
        build_container(migrated_engine, clock),
        workflow_storage=storage,
        analysis_service=analyses,
        profit_bridge_service=bridges,
        demo_session_service=DemoSessionService(
            engine=migrated_engine,
            workspace_id=WORKSPACE_ID,
            session_pepper=SESSION_PEPPER,
            clock=clock,
            profit_bridge_resolver=bridges.completed_id_for_session,
        ),
    )
    payload = _payload(str(seeded.dataset_version_id))
    with TestClient(create_app(container=container)) as client:
        unauthenticated = client.post("/api/v1/profit-bridges", json=payload)
        login = client.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": login.json()["csrf_token"],
        }
        created = client.post(
            "/api/v1/profit-bridges",
            headers=headers,
            json=payload,
        )
        replay = client.post(
            "/api/v1/profit-bridges",
            headers=headers,
            json=payload,
        )
        operator_read = client.get(
            f"/api/v1/profit-bridges/{created.json()['id']}"
        )
        viewer = client.post("/api/demo/sessions", headers={"Origin": ORIGIN})
        activate_demo_data(client, viewer)
        viewer_read = client.get(
            "/api/demo/release/profit-bridge/current",
            params={"store_id": "SYNTH-STORE-01"},
        )
        second = client.post(
            "/api/v1/profit-bridges",
            headers=headers,
            json=_payload(
                str(seeded.dataset_version_id),
                ["SYNTH-SKU-001"],
            ),
        )
        latest = client.get(
            "/api/v1/profit-bridges/latest",
            params={
                "dataset_version_id": str(seeded.dataset_version_id),
                "store_id": "SYNTH-STORE-01",
            },
        )
        default_bridge = client.get(
            "/api/v1/profit-bridges/default",
            params={
                "dataset_version_id": str(seeded.dataset_version_id),
                "store_id": "SYNTH-STORE-01",
            },
        )
        pinned_replay = client.get(
            "/api/demo/release/profit-bridge/current",
            params={"store_id": "SYNTH-STORE-01"},
        )
        next_viewer = client.post("/api/demo/sessions", headers={"Origin": ORIGIN})
        activate_demo_data(client, next_viewer)
        next_viewer_read = client.get(
            "/api/demo/release/profit-bridge/current",
            params={"store_id": "SYNTH-STORE-01"},
        )

    assert unauthenticated.status_code == 401
    assert created.status_code == 200, created.text
    assert created.json()["reconciled"] is True
    assert replay.json() == created.json()
    assert operator_read.json() == created.json()
    assert viewer.status_code == 201
    assert viewer_read.status_code == 200
    assert viewer_read.json() == created.json()
    assert second.status_code == 200, second.text
    assert second.json()["id"] != created.json()["id"]
    assert latest.json() == created.json()
    assert default_bridge.json() == created.json()
    assert pinned_replay.json() == created.json()
    assert next_viewer.status_code == 201
    assert next_viewer_read.json() == created.json()
    assert viewer_read.headers["cache-control"] == "private, no-store"
    assert "object_key" not in viewer_read.text
