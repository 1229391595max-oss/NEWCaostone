from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from api.main import create_app
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.datasets import DatasetRepository
from src.services.action_service import ActionService
from src.services.demo_session_service import DemoSessionService
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
from tests.services.test_action_service import _action_authority, _source

ORIGIN = "http://testserver"


def test_operator_authority_and_viewer_overlay_isolation(migrated_engine: Engine) -> None:
    storage = MemoryWorkflowStorage()
    clock = initial_clock()
    seed_operator(migrated_engine, fast_password_hasher())
    seeded = seed_demo(
        generate_demo(),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=clock(),
    )
    with PostgresUnitOfWork(migrated_engine) as uow:
        DatasetRepository(uow.connection).activate_release(
            workspace_id=WORKSPACE_ID,
            dataset_version_id=seeded.dataset_version_id,
            now=clock(),
        )
    actions = ActionService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=clock,
    )
    analysis_run_id, facts = _action_authority(
        migrated_engine,
        storage,
        seeded.dataset_version_id,
    )
    draft = actions.create_draft(
        _source(seeded.dataset_version_id, analysis_run_id, facts),
        facts,
        "draft-a",
    )
    reviewed = actions.review(draft.id, 1, "Reviewed", "review-a")
    approved = actions.approve(reviewed.id, 1, "Approved", "approve-a")
    container = replace(
        build_container(migrated_engine, clock),
        workflow_storage=storage,
        action_service=actions,
        demo_session_service=DemoSessionService(
            engine=migrated_engine,
            workspace_id=WORKSPACE_ID,
            session_pepper=SESSION_PEPPER,
            clock=clock,
        ),
    )
    app = create_app(container=container)

    with TestClient(app) as anonymous:
        assert anonymous.get("/api/v1/actions").status_code == 401

    with TestClient(app) as operator:
        login = operator.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": login.json()["csrf_token"],
            "Idempotency-Key": "export-api-a",
        }
        listed = operator.get(
            "/api/v1/actions",
            params={
                "dataset_version_id": str(seeded.dataset_version_id),
                "store_id": "SYNTH-STORE-01",
            },
        )
        exported = operator.post(
            f"/api/v1/actions/{approved.id}/exports",
            headers=headers,
            json={
                "dataset_version_id": str(seeded.dataset_version_id),
                "store_ids": ["SYNTH-STORE-01"],
                "revision": 1,
                "format": "xlsx",
            },
        )
        downloaded = operator.get(
            f"/api/v1/actions/{approved.id}/exports/"
            f"{exported.json()['id']}/download"
        )

    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["status"] == "approved"
    assert exported.status_code == 200, exported.text
    assert exported.json()["status"] == "available"
    assert "object_key" not in exported.text
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"PK")
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert "SYNTH-ACTION" in downloaded.headers["content-disposition"]

    clock.now += timedelta(seconds=1)
    with TestClient(app) as viewer_a:
        session = viewer_a.post("/api/demo/sessions", headers={"Origin": ORIGIN})
        csrf = session.json()["csrf_token"]
        activate_demo_data(viewer_a, session)
        templates = viewer_a.get(
            "/api/demo/release/actions",
            params={"store_id": "SYNTH-STORE-01"},
        )
        review = viewer_a.post(
            f"/api/demo/actions/{approved.id}/commands",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "viewer-review-a",
            },
            json={
                "store_ids": ["SYNTH-STORE-01"],
                "base_revision": 1,
                "command": "review",
                "reason": "Simulated review",
                "adjustment": {},
            },
        )
        cross_scope = viewer_a.post(
            f"/api/demo/actions/{approved.id}/commands",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "viewer-cross-scope",
            },
            json={
                "store_ids": ["SYNTH-STORE-02"],
                "base_revision": 1,
                "command": "review",
                "reason": "Wrong selected store",
                "adjustment": {},
            },
        )
        adjust = viewer_a.post(
            f"/api/demo/actions/{approved.id}/commands",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "viewer-adjust-a",
            },
            json={
                "store_ids": ["SYNTH-STORE-01"],
                "base_revision": 1,
                "command": "adjust",
                "reason": "Simulated adjustment",
                "adjustment": {"quantity": "52", "budget_brl": "900.00"},
            },
        )
        unsafe_adjustment = viewer_a.post(
            f"/api/demo/actions/{approved.id}/commands",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "viewer-unsafe-adjustment",
            },
            json={
                "store_ids": ["SYNTH-STORE-01"],
                "base_revision": 1,
                "command": "adjust",
                "reason": "Simulated adjustment",
                "adjustment": {"suggestion": "Contact person@example.test"},
            },
        )
        oversized_adjustment = viewer_a.post(
            f"/api/demo/actions/{approved.id}/commands",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "viewer-oversized-adjustment",
            },
            json={
                "store_ids": ["SYNTH-STORE-01"],
                "base_revision": 1,
                "command": "adjust",
                "reason": "Oversized simulated adjustment",
                "adjustment": {
                    "expected_impact": {
                        f"impact_{index}": "synthetic" for index in range(21)
                    }
                },
            },
        )
        oversized_number = viewer_a.post(
            f"/api/demo/actions/{approved.id}/commands",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "viewer-oversized-number",
            },
            json={
                "store_ids": ["SYNTH-STORE-01"],
                "base_revision": 1,
                "command": "adjust",
                "reason": "Oversized numeric simulation",
                "adjustment": {"quantity": "9" * 20_000},
            },
        )
        calculated_adjustment = viewer_a.post(
            f"/api/demo/actions/{approved.id}/commands",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "viewer-calculated-adjustment",
            },
            json={
                "store_ids": ["SYNTH-STORE-01"],
                "base_revision": 1,
                "command": "adjust",
                "reason": "Client-calculated values are forbidden",
                "adjustment": {
                    "quantity": "40",
                    "unit_cost_brl": "12.50",
                    "precomputed_daily_velocity": "5",
                    "purchase_cash_brl": "500.00",
                },
            },
        )
        approve = viewer_a.post(
            f"/api/demo/actions/{approved.id}/commands",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "viewer-approve-a",
            },
            json={
                "store_ids": ["SYNTH-STORE-01"],
                "base_revision": 1,
                "command": "approve",
                "reason": "Simulated approval",
                "adjustment": {},
            },
        )
        actions.export(approved.id, 1, "export-after-viewer-session")
        actions.record_outcome(
            approved.id,
            1,
            review_date=clock().date(),
            synthetic_result={"human_review": "synthetic_follow_up"},
            evidence=facts,
            conclusion="inconclusive",
            reason="Recorded after the viewer session started",
            idempotency_key="outcome-after-viewer-session",
        )
        pinned_templates = viewer_a.get(
            "/api/demo/release/actions",
            params={"store_id": "SYNTH-STORE-01"},
        )
        history_a = viewer_a.get(
            f"/api/demo/actions/{approved.id}/overlays",
            params={"store_id": "SYNTH-STORE-01"},
        )
        reset = viewer_a.delete(
            "/api/demo/action-sandbox",
            params={"store_id": "SYNTH-STORE-01"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        reset_history_a = viewer_a.get(
            f"/api/demo/actions/{approved.id}/overlays",
            params={"store_id": "SYNTH-STORE-01"},
        )
        viewer_export = viewer_a.post(
            f"/api/v1/actions/{approved.id}/exports",
            json={
                "dataset_version_id": str(seeded.dataset_version_id),
                "store_ids": ["SYNTH-STORE-01"],
                "revision": 1,
                "format": "xlsx",
            },
        )

    clock.now += timedelta(seconds=1)
    with TestClient(app) as viewer_b:
        session_b = viewer_b.post("/api/demo/sessions", headers={"Origin": ORIGIN})
        activate_demo_data(viewer_b, session_b)
        later_templates = viewer_b.get(
            "/api/demo/release/actions",
            params={"store_id": "SYNTH-STORE-01"},
        )
        history_b = viewer_b.get(
            f"/api/demo/actions/{approved.id}/overlays",
            params={"store_id": "SYNTH-STORE-01"},
        )

    assert templates.status_code == 200
    template = next(
        item for item in templates.json()["items"] if item["id"] == str(approved.id)
    )
    simulation_inputs = template["simulation_inputs"]
    assert simulation_inputs["unit_cost_brl"] is not None
    assert simulation_inputs["precomputed_daily_velocity"] is not None
    assert simulation_inputs["currency"] == "BRL"
    assert review.status_code == 200 and review.json()["status"] == "reviewed"
    assert cross_scope.status_code == 409
    assert cross_scope.json() == {"code": "ACTION_SCOPE_CONFLICT"}
    assert adjust.status_code == 200 and adjust.json()["status"] == "reviewed"
    assert unsafe_adjustment.status_code == 422
    assert oversized_adjustment.status_code == 422
    assert oversized_number.status_code == 422
    assert calculated_adjustment.status_code == 422
    assert approve.status_code == 200 and approve.json()["status"] == "approved"
    pinned_template = next(
        item
        for item in pinned_templates.json()["items"]
        if item["id"] == str(approved.id)
    )
    later_template = next(
        item
        for item in later_templates.json()["items"]
        if item["id"] == str(approved.id)
    )
    assert len(pinned_template["exports"]) == 1
    assert pinned_template["outcomes"] == []
    assert len(later_template["exports"]) == 2
    assert len(later_template["outcomes"]) == 1
    assert [item["status"] for item in history_a.json()["items"]] == [
        "reviewed",
        "reviewed",
        "approved",
    ]
    assert reset.status_code == 200
    assert reset.json() == {"deleted_overlays": 3}
    assert reset_history_a.json()["items"] == []
    assert history_b.json()["items"] == []
    assert viewer_export.status_code == 401
    assert actions.get(approved.id).status == "approved"
