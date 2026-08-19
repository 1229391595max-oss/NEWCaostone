from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from src.ai.contracts import ChatPrincipal
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.sessions import SessionRepository
from src.services.ai_chat_service import AIChatNotFound
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


def _viewer(
    engine: Engine,
    dataset_version_id,
    marker: int,
    created_at=NOW,
    idle_minutes: int = 30,
) -> ChatPrincipal:
    session_id = uuid4()
    with PostgresUnitOfWork(engine) as uow:
        SessionRepository(uow.connection).create_demo_session(
            session_id=session_id,
            workspace_id=WORKSPACE_ID,
            token_hash=bytes([marker]) * 32,
            csrf_hash=bytes([marker + 1]) * 32,
            source_address_hash=bytes([marker + 2]) * 32,
            now=created_at,
            idle_expires_at=created_at + timedelta(minutes=idle_minutes),
            absolute_expires_at=created_at + timedelta(hours=2),
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
        session_created_at=created_at,
    )


def test_two_viewers_cannot_read_or_act_on_each_others_chat_turns(
    migrated_engine: Engine,
) -> None:
    _operator, dataset_version_id = _principal(migrated_engine)
    first = _viewer(migrated_engine, dataset_version_id, 51)
    second = _viewer(migrated_engine, dataset_version_id, 61)
    service = _service(migrated_engine, FakeGateway(), StaticBackend())
    turn = service.submit(
        first,
        **_preset("advertising_performance"),
        idempotency_key="viewer-one-turn",
    )

    assert service.list(second) == ()
    with pytest.raises(AIChatNotFound):
        service.get(second, turn.id)
    with pytest.raises(AIChatNotFound):
        service.create_action_draft(
            second,
            turn.id,
            idempotency_key="viewer-two-cross-draft",
        )
    with pytest.raises(AIChatNotFound):
        service.delete_demo_session(
            replace(first, dataset_version_id=uuid4())
        )
    assert service.list(first) == (turn,)


def test_resetting_one_action_sandbox_cannot_delete_another_session(
    migrated_engine: Engine,
) -> None:
    from tests.services.test_action_service import (
        NOW as ACTION_NOW,
        _service as action_service_fixture,
        _source,
    )
    from src.services.action_service import ActionService

    actions, storage, version_id, analysis_run_id, facts = action_service_fixture(
        migrated_engine
    )
    draft = actions.create_draft(
        _source(version_id, analysis_run_id, facts),
        facts,
        "cross-session-action",
    )
    reviewed = actions.review(draft.id, 1, "Reviewed", "cross-session-review")
    approved = actions.approve(reviewed.id, 1, "Approved", "cross-session-approve")
    first = _viewer(
        migrated_engine,
        version_id,
        71,
        ACTION_NOW + timedelta(seconds=1),
    )
    second = _viewer(
        migrated_engine,
        version_id,
        81,
        ACTION_NOW + timedelta(seconds=1),
    )
    sandbox = ActionService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=lambda: ACTION_NOW + timedelta(seconds=2),
    )
    for principal, key in ((first, "first-overlay"), (second, "second-overlay")):
        sandbox.simulate(
            session_id=principal.session_id,
            expected_chat_epoch=principal.chat_epoch,
            dataset_version_id=version_id,
            action_id=approved.id,
            base_revision=1,
            command="review",
            adjustment={},
            reason="Session-only review",
            idempotency_key=key,
        )

    assert sandbox.reset_simulation(
        session_id=first.session_id,
        expected_chat_epoch=first.chat_epoch,
        dataset_version_id=version_id,
    ) == 1
    assert sandbox.overlays(first.session_id, approved.id) == ()
    assert len(sandbox.overlays(second.session_id, approved.id)) == 1


def test_expiring_one_viewer_clears_only_its_chat_and_action_overlay(
    migrated_engine: Engine,
) -> None:
    from tests.services.test_action_service import (
        NOW as ACTION_NOW,
        _service as action_service_fixture,
        _source,
    )
    from src.services.action_service import ActionService

    actions, storage, version_id, analysis_run_id, facts = action_service_fixture(
        migrated_engine
    )
    draft = actions.create_draft(
        _source(version_id, analysis_run_id, facts),
        facts,
        "expiry-isolation-action",
    )
    reviewed = actions.review(draft.id, 1, "Reviewed", "expiry-isolation-review")
    approved = actions.approve(
        reviewed.id,
        1,
        "Approved",
        "expiry-isolation-approve",
    )
    viewer_now = ACTION_NOW + timedelta(seconds=1)
    first = _viewer(
        migrated_engine,
        version_id,
        91,
        created_at=viewer_now,
        idle_minutes=1,
    )
    second = _viewer(
        migrated_engine,
        version_id,
        101,
        created_at=viewer_now,
        idle_minutes=30,
    )
    sandbox = ActionService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=lambda: viewer_now,
    )
    chat = _service(migrated_engine, FakeGateway(), StaticBackend())
    chat._clock = lambda: viewer_now
    for principal, key in ((first, "expiry-first"), (second, "expiry-second")):
        sandbox.simulate(
            session_id=principal.session_id,
            expected_chat_epoch=principal.chat_epoch,
            dataset_version_id=version_id,
            action_id=approved.id,
            base_revision=1,
            command="review",
            adjustment={},
            reason="Session-only expiry proof",
            idempotency_key=f"{key}-overlay",
        )
        chat.submit(
            principal,
            **_preset("advertising_performance"),
            idempotency_key=f"{key}-chat",
        )

    expiry_time = viewer_now + timedelta(minutes=2)
    sessions = DemoSessionService(
        engine=migrated_engine,
        workspace_id=WORKSPACE_ID,
        session_pepper="security-expiry-isolation-pepper",
        clock=lambda: expiry_time,
    )
    assert sessions.expire_sessions(expiry_time) == 1
    assert chat.list(first) == ()
    assert len(chat.list(second)) == 1
    assert sandbox.overlays(first.session_id, approved.id) == ()
    assert len(sandbox.overlays(second.session_id, approved.id)) == 1
