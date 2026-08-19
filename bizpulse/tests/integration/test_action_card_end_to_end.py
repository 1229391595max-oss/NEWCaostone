from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import timedelta
from queue import Queue
import time
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import Engine, func, select, text

from api.main import create_app
from src.db.schema import demo_action_overlays
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.actions import ActionRepository
from src.repositories.datasets import DatasetRepository
from src.repositories.sessions import SessionRepository
from src.services.action_service import ActionNotFound, ActionService
from src.services.demo_session_service import DemoSessionService
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.auth_support import (
    LOGIN_NAME,
    PASSWORD,
    SESSION_PEPPER,
    build_container,
    fast_password_hasher,
    initial_clock,
    seed_operator,
)
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID
from tests.services.test_action_service import _action_authority, _source

ORIGIN = "http://testserver"


class CommitAcknowledgementLostUnitOfWork(PostgresUnitOfWork):
    def commit(self) -> None:
        super().commit()
        raise RuntimeError("injected_action_commit_acknowledgement_lost")


def test_action_card_operator_restart_and_viewer_expiry(migrated_engine: Engine) -> None:
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
    run_id, facts = _action_authority(
        migrated_engine,
        storage,
        seeded.dataset_version_id,
    )
    actions = ActionService(migrated_engine, storage, WORKSPACE_ID, clock=clock)
    sessions = DemoSessionService(
        engine=migrated_engine,
        workspace_id=WORKSPACE_ID,
        session_pepper=SESSION_PEPPER,
        clock=clock,
    )
    container = replace(
        build_container(migrated_engine, clock),
        workflow_storage=storage,
        action_service=actions,
        demo_session_service=sessions,
    )
    source = _source(seeded.dataset_version_id, run_id, facts)
    create_payload = {
        "source": {
            **asdict(source),
            "dataset_version_id": str(source.dataset_version_id),
            "period_start": source.period_start.isoformat(),
            "period_end": source.period_end.isoformat(),
            "quantity": str(source.quantity),
            "budget_brl": (
                str(source.budget_brl) if source.budget_brl is not None else None
            ),
            "action_date": source.action_date.isoformat(),
            "threshold": str(source.threshold) if source.threshold is not None else None,
            "analysis_run_id": str(source.analysis_run_id),
        },
        "facts": [asdict(item) for item in facts],
    }
    app = create_app(container=container)
    with TestClient(app) as operator:
        login = operator.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        base_headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": login.json()["csrf_token"],
        }
        created = operator.post(
            "/api/v1/actions",
            headers={**base_headers, "Idempotency-Key": "integration-create"},
            json=create_payload,
        )
        reviewed = operator.post(
            f"/api/v1/actions/{created.json()['id']}/commands",
            headers={**base_headers, "Idempotency-Key": "integration-review"},
            json={
                "dataset_version_id": str(source.dataset_version_id),
                "store_ids": ["SYNTH-STORE-01"],
                "revision": 1,
                "command": "review",
                "reason": "Evidence reviewed",
            },
        )
        adjusted = operator.post(
            f"/api/v1/actions/{created.json()['id']}/commands",
            headers={**base_headers, "Idempotency-Key": "integration-adjust"},
            json={
                "dataset_version_id": str(source.dataset_version_id),
                "store_ids": ["SYNTH-STORE-01"],
                "revision": 1,
                "command": "adjust",
                "reason": "Synthetic supplier MOQ",
                "adjustment": {"quantity": "48", "budget_brl": "960.00"},
            },
        )
        approved = operator.post(
            f"/api/v1/actions/{created.json()['id']}/commands",
            headers={**base_headers, "Idempotency-Key": "integration-approve"},
            json={
                "dataset_version_id": str(source.dataset_version_id),
                "store_ids": ["SYNTH-STORE-01"],
                "revision": 2,
                "command": "approve",
                "reason": "Approved for Demo follow-up",
            },
        )
        outcome = operator.post(
            f"/api/v1/actions/{created.json()['id']}/outcomes",
            headers={**base_headers, "Idempotency-Key": "integration-outcome"},
            json={
                "dataset_version_id": str(source.dataset_version_id),
                "store_ids": ["SYNTH-STORE-01"],
                "revision": 2,
                "review_date": "2026-08-31",
                "synthetic_result": {"units_received": "48"},
                "evidence": [asdict(item) for item in facts],
                "conclusion": "achieved",
                "reason": "Synthetic outcome reached",
            },
        )

    assert created.status_code == 200, created.text
    assert reviewed.json()["status"] == "reviewed"
    assert adjusted.json()["current_revision"] == 2
    assert approved.json()["status"] == "approved"
    assert outcome.json()["outcome_revision"] == 1

    restarted = ActionService(migrated_engine, storage, WORKSPACE_ID, clock=clock)
    recovered = restarted.get(UUID(approved.json()["id"]))
    assert recovered.status == "approved"
    assert recovered.revisions[0].facts == facts
    assert recovered.revisions[1].quantity == 48
    assert recovered.outcomes[0].conclusion == "achieved"

    clock.now += timedelta(seconds=1)
    issued = sessions.create("source-hash", clock())
    expired_actions = ActionService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=lambda: issued.principal.idle_expires_at,
    )
    with pytest.raises(ActionNotFound):
        expired_actions.simulate(
            session_id=issued.principal.session_id,
            expected_chat_epoch=issued.principal.chat_epoch,
            dataset_version_id=seeded.dataset_version_id,
            action_id=recovered.id,
            base_revision=2,
            command="review",
            adjustment={},
            reason="Expired session must fail before maintenance",
            idempotency_key="expired-without-sweeper",
        )
    ack_lost = ActionService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=clock,
        uow_factory=CommitAcknowledgementLostUnitOfWork,
    )
    overlay = ack_lost.simulate(
        session_id=issued.principal.session_id,
        expected_chat_epoch=issued.principal.chat_epoch,
        dataset_version_id=seeded.dataset_version_id,
        action_id=recovered.id,
        base_revision=2,
        command="review",
        adjustment={},
        reason="Viewer simulation",
        idempotency_key="viewer-overlay",
    )
    replayed_overlay = restarted.simulate(
        session_id=issued.principal.session_id,
        expected_chat_epoch=issued.principal.chat_epoch,
        dataset_version_id=seeded.dataset_version_id,
        action_id=recovered.id,
        base_revision=2,
        command="review",
        adjustment={},
        reason="Viewer simulation",
        idempotency_key="viewer-overlay",
    )
    assert replayed_overlay == overlay
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(demo_action_overlays)) == 1

    backend_pid: Queue[int] = Queue()

    def end_session() -> bool:
        with migrated_engine.connect() as connection:
            pid = connection.scalar(text("SELECT pg_backend_pid()"))
            assert pid is not None
            connection.commit()
            backend_pid.put(pid)
            with connection.begin():
                return SessionRepository(connection).end_demo_session(
                    issued.principal.session_id,
                    clock(),
                )

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        repository = ActionRepository(connection)
        assert repository.viewer_template_eligible(
            issued.principal.session_id,
            recovered.id,
            clock(),
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            ending = executor.submit(end_session)
            pid = backend_pid.get(timeout=2)
            wait_event_type = None
            for _ in range(100):
                with migrated_engine.connect() as observer:
                    wait_event_type = observer.scalar(
                        text(
                            "SELECT wait_event_type FROM pg_stat_activity "
                            "WHERE pid=:pid"
                        ),
                        {"pid": pid},
                    )
                if wait_event_type == "Lock":
                    break
                time.sleep(0.01)
            assert wait_event_type == "Lock"
            repository.add_overlay(
                {
                    "id": uuid4(),
                    "demo_session_id": issued.principal.session_id,
                    "action_id": recovered.id,
                    "base_revision": 2,
                    "overlay_revision": 2,
                    "command": "approve",
                    "status": "approved",
                    "adjustment": {},
                    "reason": "Concurrent viewer simulation",
                    "idempotency_key_hash": b"c" * 32,
                    "request_hash": b"r" * 32,
                    "created_at": clock(),
                }
            )
            transaction.commit()
            assert ending.result(timeout=2) is True

    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(demo_action_overlays)) == 0
