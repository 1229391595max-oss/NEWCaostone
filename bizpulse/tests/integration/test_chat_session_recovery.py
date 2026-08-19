from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select

from scripts.maintain_sessions import run_maintenance
from src.ai.contracts import ChatPrincipal
from src.db.schema import ai_chat_turns, demo_action_overlays
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.sessions import SessionRepository
from src.services.action_service import ActionNotFound
from src.services.demo_session_service import DemoSessionService
from tests.import_support import WORKSPACE_ID
from tests.services.test_ai_chat_service import (
    FakeGateway,
    NOW,
    StaticBackend,
    _principal,
    _preset,
    _service,
)
from tests.services.test_action_service import (
    NOW as ACTION_NOW,
    _service as _action_service,
    _source as _action_source,
)


def _demo_principal(
    engine: Engine,
    dataset_version_id,
    *,
    marker: int,
    idle_minutes: int = 30,
    now=NOW,
) -> ChatPrincipal:
    session_id = uuid4()
    with PostgresUnitOfWork(engine) as uow:
        SessionRepository(uow.connection).create_demo_session(
            session_id=session_id,
            workspace_id=WORKSPACE_ID,
            token_hash=bytes([marker]) * 32,
            csrf_hash=bytes([marker + 1]) * 32,
            source_address_hash=bytes([marker + 2]) * 32,
            now=now,
            idle_expires_at=now + timedelta(minutes=idle_minutes),
            absolute_expires_at=now + timedelta(hours=2),
            dataset_version_id=dataset_version_id,
        )
    return ChatPrincipal(
        actor_kind="demo",
        session_id=session_id,
        workspace_id=WORKSPACE_ID,
        dataset_version_id=dataset_version_id,
        store_ids=("SYNTH-STORE-01",),
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 30),
        session_created_at=now,
    )


def test_refresh_restores_turns_and_end_session_deletes_ephemeral_chat(
    migrated_engine: Engine,
) -> None:
    _operator, dataset_version_id = _principal(migrated_engine)
    principal = _demo_principal(
        migrated_engine,
        dataset_version_id,
        marker=21,
    )
    first_gateway = FakeGateway()
    first = _service(migrated_engine, first_gateway, StaticBackend())
    created = first.submit(
        principal,
        **_preset("profit_changes"),
        idempotency_key="recovery-one",
    )

    reopened_gateway = FakeGateway()
    reopened = _service(migrated_engine, reopened_gateway, StaticBackend())
    assert reopened.list(principal) == (created,)
    assert reopened.get(principal, created.id) == created
    assert reopened_gateway.attempts == 0

    sessions = DemoSessionService(
        engine=migrated_engine,
        workspace_id=WORKSPACE_ID,
        session_pepper="session-recovery-pepper",
        clock=lambda: NOW,
    )
    assert sessions.end(principal.session_id, NOW) is True
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ai_chat_turns)) == 0


def test_session_maintenance_expires_only_elapsed_session_chat(
    migrated_engine: Engine,
) -> None:
    _operator, dataset_version_id = _principal(migrated_engine)
    elapsed = _demo_principal(
        migrated_engine,
        dataset_version_id,
        marker=31,
        idle_minutes=1,
    )
    active = _demo_principal(
        migrated_engine,
        dataset_version_id,
        marker=41,
        idle_minutes=30,
    )
    service = _service(migrated_engine, FakeGateway(), StaticBackend())
    for principal, key in ((elapsed, "expired-one"), (active, "active-one")):
        service.submit(
            principal,
            **_preset("advertising_performance"),
            idempotency_key=key,
        )

    maintenance = DemoSessionService(
        engine=migrated_engine,
        workspace_id=WORKSPACE_ID,
        session_pepper="session-maintenance-pepper",
        clock=lambda: NOW,
    )
    assert run_maintenance(
        maintenance,
        now=NOW + timedelta(minutes=2),
    ) == {"expired_demo_sessions": 1}
    assert service.list(elapsed) == ()
    assert len(service.list(active)) == 1


def test_delete_chat_session_clears_only_that_viewers_simulated_actions(
    migrated_engine: Engine,
) -> None:
    actions, _storage, version_id, analysis_id, facts = _action_service(migrated_engine)
    created = actions.create_draft(
        _action_source(version_id, analysis_id, facts),
        facts,
        "chat-clear-action-create",
    )
    reviewed = actions.review(
        created.id,
        created.current_revision,
        "Reviewed for public synthetic session",
        "chat-clear-action-review",
    )
    approved = actions.approve(
        reviewed.id,
        reviewed.current_revision,
        "Approved for public synthetic session",
        "chat-clear-action-approve",
    )
    viewer_now = ACTION_NOW + timedelta(seconds=1)
    actions._clock = lambda: viewer_now
    principal = _demo_principal(
        migrated_engine,
        version_id,
        marker=71,
        now=viewer_now,
    )
    actions.simulate(
        session_id=principal.session_id,
        expected_chat_epoch=principal.chat_epoch,
        dataset_version_id=version_id,
        action_id=approved.id,
        base_revision=approved.current_revision,
        command="review",
        adjustment={},
        reason="My session-only review",
        idempotency_key="chat-clear-overlay",
    )
    chat = _service(migrated_engine, FakeGateway(), StaticBackend())
    chat._clock = lambda: viewer_now
    chat.submit(
        principal,
        **_preset("next_actions"),
        idempotency_key="chat-clear-turn",
    )

    with migrated_engine.connect() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(demo_action_overlays))
            == 1
        )
    assert chat.delete_demo_session(principal) == 1
    with pytest.raises(ActionNotFound):
        actions.simulate(
            session_id=principal.session_id,
            expected_chat_epoch=principal.chat_epoch,
            dataset_version_id=version_id,
            action_id=approved.id,
            base_revision=approved.current_revision,
            command="approve",
            adjustment={},
            reason="Stale command must not recreate a cleared overlay",
            idempotency_key="stale-after-chat-delete",
        )
    with migrated_engine.connect() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(demo_action_overlays))
            == 0
        )
        assert connection.scalar(select(func.count()).select_from(ai_chat_turns)) == 0
