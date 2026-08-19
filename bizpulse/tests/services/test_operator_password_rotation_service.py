from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from argon2 import PasswordHasher, Type
from sqlalchemy import Engine, func, select

from src.db.schema import ai_chat_saved_records, ai_chat_turns, operator_accounts, operator_sessions
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.ai_chat import AIChatRepository
from src.repositories.operators import OperatorRepository
from src.repositories.sessions import SessionRepository
from src.services.operator_password_rotation_service import (
    OperatorPasswordRotationAuthorityError,
    OperatorPasswordRotationConflict,
    OperatorPasswordRotationService,
)
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.import_support import MemoryWorkflowStorage


WORKSPACE_ID = "synthetic-demo"
LOGIN_NAME = "operator"
NOW = datetime(2026, 8, 17, 17, 0, tzinfo=UTC)


def _password_hash(password: str) -> str:
    return PasswordHasher(
        time_cost=3,
        memory_cost=65_536,
        parallelism=1,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    ).hash(password)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _service(engine: Engine) -> OperatorPasswordRotationService:
    return OperatorPasswordRotationService(
        engine=engine,
        workspace_id=WORKSPACE_ID,
        login_name=LOGIN_NAME,
        clock=lambda: NOW,
    )


def _seed_operator_with_sessions(
    engine: Engine,
    *,
    password_hash: str,
) -> tuple[UUID, tuple[UUID, UUID], UUID]:
    with PostgresUnitOfWork(engine) as uow:
        operators = OperatorRepository(uow.connection)
        operators.create_workspace(WORKSPACE_ID, now=NOW)
        operator = operators.create_operator(
            workspace_id=WORKSPACE_ID,
            login_name=LOGIN_NAME,
            password_hash=password_hash,
            now=NOW,
        )
        sessions = SessionRepository(uow.connection)
        active_ids = (uuid4(), uuid4())
        revoked_id = uuid4()
        for index, session_id in enumerate((*active_ids, revoked_id), start=1):
            sessions.create_operator_session(
                session_id=session_id,
                workspace_id=WORKSPACE_ID,
                operator_id=operator.id,
                token_hash=bytes([index]) * 32,
                csrf_hash=bytes([index + 10]) * 32,
                now=NOW,
                idle_expires_at=NOW + timedelta(minutes=30),
                absolute_expires_at=NOW + timedelta(hours=2),
            )
        assert sessions.revoke_operator_session(revoked_id, NOW) is True
    return operator.id, active_ids, revoked_id


def _insert_turn(
    engine: Engine,
    *,
    dataset_version_id: UUID,
    session_id: UUID,
    operator_id: UUID,
    saved: bool,
) -> UUID:
    turn_id = uuid4()
    with PostgresUnitOfWork(engine) as uow:
        chats = AIChatRepository(uow.connection)
        chats.insert_turn(
            turn_id=turn_id,
            workspace_id=WORKSPACE_ID,
            dataset_version_id=dataset_version_id,
            actor_kind="operator",
            session_id=session_id,
            question="What changed?",
            recommended_question_id=None,
            question_digest="a" * 64,
            scope={},
            plan_schema_version="query-plan.v1",
            output_schema_version="chat-answer.v1",
            key_hash=hashlib.sha256(b"rotation-key:" + turn_id.bytes).digest(),
            request_hash=hashlib.sha256(
                b"rotation-request:" + turn_id.bytes
            ).digest(),
            now=NOW,
            lease_expires_at=NOW + timedelta(minutes=5),
        )
        if saved:
            assert chats.transition(
                turn_id,
                expected_status="planning",
                status="querying",
                now=NOW,
                lease_expires_at=NOW + timedelta(minutes=5),
            ) is not None
            assert chats.transition(
                turn_id,
                expected_status="querying",
                status="answering",
                now=NOW,
                lease_expires_at=NOW + timedelta(minutes=5),
            ) is not None
            assert chats.transition(
                turn_id,
                expected_status="answering",
                status="answered",
                now=NOW,
                safe_summary="Saved synthetic answer.",
            ) is not None
            assert chats.save_answer(
                turn_id=turn_id,
                operator_id=operator_id,
                answer_hash="b" * 64,
                now=NOW,
            )
    return turn_id


def test_rotation_updates_exact_authority_revokes_active_sessions_and_clears_only_ephemeral_chat(
    migrated_engine: Engine,
) -> None:
    old_hash = _password_hash("old-operator-password")
    new_hash = _password_hash("replacement-operator-password")
    operator_id, active_ids, revoked_id = _seed_operator_with_sessions(
        migrated_engine,
        password_hash=old_hash,
    )
    seeded = seed_demo(
        generate_demo(),
        PostgresUnitOfWork(migrated_engine),
        MemoryWorkflowStorage(),
        now=NOW,
    )
    ephemeral_turn_id = _insert_turn(
        migrated_engine,
        dataset_version_id=seeded.dataset_version_id,
        session_id=active_ids[0],
        operator_id=operator_id,
        saved=False,
    )
    saved_turn_id = _insert_turn(
        migrated_engine,
        dataset_version_id=seeded.dataset_version_id,
        session_id=active_ids[1],
        operator_id=operator_id,
        saved=True,
    )

    result = _service(migrated_engine).rotate(
        expected_hash_fingerprint=_fingerprint(old_hash),
        replacement_password_hash=new_hash,
    )

    assert result.status == "rotated"
    assert result.revoked_session_count == 2
    assert result.deleted_ephemeral_chat_count == 1
    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(operator_accounts.c.password_hash).where(
                operator_accounts.c.id == operator_id
            )
        ) == new_hash
        revoked_at = dict(
            connection.execute(
                select(operator_sessions.c.id, operator_sessions.c.revoked_at)
            ).all()
        )
        assert revoked_at[active_ids[0]] == NOW
        assert revoked_at[active_ids[1]] == NOW
        assert revoked_at[revoked_id] == NOW
        remaining_turn_ids = set(connection.scalars(select(ai_chat_turns.c.id)))
        assert ephemeral_turn_id not in remaining_turn_ids
        assert saved_turn_id in remaining_turn_ids
        assert connection.scalar(
            select(func.count()).select_from(ai_chat_saved_records)
        ) == 1


def test_rotation_rejects_unexpected_old_hash_without_revoking_sessions(
    migrated_engine: Engine,
) -> None:
    old_hash = _password_hash("old-operator-password")
    new_hash = _password_hash("replacement-operator-password")
    _operator_id, active_ids, _revoked_id = _seed_operator_with_sessions(
        migrated_engine,
        password_hash=old_hash,
    )

    with pytest.raises(OperatorPasswordRotationConflict, match="expected_hash_mismatch"):
        _service(migrated_engine).rotate(
            expected_hash_fingerprint=_fingerprint("not-the-current-hash"),
            replacement_password_hash=new_hash,
        )

    with migrated_engine.connect() as connection:
        assert connection.scalar(select(operator_accounts.c.password_hash)) == old_hash
        active_session_count = connection.scalar(
            select(func.count())
            .select_from(operator_sessions)
            .where(
                operator_sessions.c.id.in_(active_ids),
                operator_sessions.c.revoked_at.is_(None),
            )
        )
        assert active_session_count == 2


def test_repeated_rotation_returns_already_rotated_without_re_revoking_sessions(
    migrated_engine: Engine,
) -> None:
    old_hash = _password_hash("old-operator-password")
    new_hash = _password_hash("replacement-operator-password")
    _operator_id, _active_ids, _revoked_id = _seed_operator_with_sessions(
        migrated_engine,
        password_hash=old_hash,
    )
    service = _service(migrated_engine)

    first = service.rotate(
        expected_hash_fingerprint=_fingerprint(old_hash),
        replacement_password_hash=new_hash,
    )
    replay = service.rotate(
        expected_hash_fingerprint=_fingerprint(old_hash),
        replacement_password_hash=new_hash,
    )

    assert first.status == "rotated"
    assert replay.status == "already_rotated"
    assert replay.revoked_session_count == 0
    assert replay.deleted_ephemeral_chat_count == 0


def test_rotation_rejects_missing_active_operator_authority(
    migrated_engine: Engine,
) -> None:
    with pytest.raises(
        OperatorPasswordRotationAuthorityError,
        match="operator_rotation_authority_missing",
    ):
        _service(migrated_engine).rotate(
            expected_hash_fingerprint="a" * 64,
            replacement_password_hash=_password_hash("replacement-operator-password"),
        )
