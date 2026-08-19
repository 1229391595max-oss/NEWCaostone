from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, insert, select
from sqlalchemy.exc import IntegrityError

from src.db.schema import workspaces
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.repositories.sessions import SessionRepository

WORKSPACE_ID = "synthetic-demo"


def seed_operator(uow: PostgresUnitOfWork):
    operators = OperatorRepository(uow.connection)
    operators.create_workspace(WORKSPACE_ID)
    return operators.create_operator(
        workspace_id=WORKSPACE_ID,
        login_name="operator",
        password_hash="$argon2id$test-only-hash",
    )


def test_unit_of_work_rolls_back_all_rows(migrated_engine: Engine) -> None:
    with pytest.raises(RuntimeError, match="injected"):
        with PostgresUnitOfWork(migrated_engine) as uow:
            uow.execute(
                insert(workspaces).values(
                    id=WORKSPACE_ID,
                    kind="single_operator_demo",
                    created_at=datetime.now(UTC),
                )
            )
            raise RuntimeError("injected")

    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(workspaces)) == 0


def test_operator_projection_never_returns_password_hash(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        operator = seed_operator(uow)

    assert operator.workspace_id == WORKSPACE_ID
    assert operator.login_name == "operator"
    assert not hasattr(operator, "password_hash")

    with migrated_engine.connect() as connection:
        loaded = OperatorRepository(connection).get_active(WORKSPACE_ID)
    assert loaded == operator


def test_database_enforces_one_active_operator_per_workspace(
    migrated_engine: Engine,
) -> None:
    with pytest.raises(IntegrityError):
        with PostgresUnitOfWork(migrated_engine) as uow:
            operators = OperatorRepository(uow.connection)
            operators.create_workspace(WORKSPACE_ID)
            operators.create_operator(
                workspace_id=WORKSPACE_ID,
                login_name="operator-one",
                password_hash="$argon2id$first-test-hash",
            )
            operators.create_operator(
                workspace_id=WORKSPACE_ID,
                login_name="operator-two",
                password_hash="$argon2id$second-test-hash",
            )


def test_sessions_survive_engine_restart_without_exposing_hashes(
    migrated_engine: Engine,
) -> None:
    now = datetime.now(UTC)
    operator_token_hash = b"operator-token-hash"
    viewer_token_hash = b"viewer-token-hash"

    with PostgresUnitOfWork(migrated_engine) as uow:
        operator = seed_operator(uow)
        sessions = SessionRepository(uow.connection)
        operator_session = sessions.create_operator_session(
            session_id=uuid4(),
            workspace_id=WORKSPACE_ID,
            operator_id=operator.id,
            token_hash=operator_token_hash,
            csrf_hash=b"operator-csrf-hash",
            now=now,
            idle_expires_at=now + timedelta(minutes=30),
            absolute_expires_at=now + timedelta(hours=2),
        )
        demo_session = sessions.create_demo_session(
            session_id=uuid4(),
            workspace_id=WORKSPACE_ID,
            token_hash=viewer_token_hash,
            csrf_hash=b"viewer-csrf-hash",
            source_address_hash=b"source-address-hash",
            now=now,
            idle_expires_at=now + timedelta(minutes=30),
            absolute_expires_at=now + timedelta(hours=2),
        )

    assert not hasattr(operator_session, "token_hash")
    assert not hasattr(operator_session, "csrf_hash")
    assert not hasattr(demo_session, "source_address_hash")

    migrated_engine.dispose()
    restarted = migrated_engine.execution_options()
    with restarted.connect() as connection:
        sessions = SessionRepository(connection)
        assert sessions.get_active_operator_session(operator_token_hash, now) == (
            operator_session
        )
        assert sessions.get_active_demo_session(viewer_token_hash, now) == demo_session
    restarted.dispose()


def test_expired_or_ended_viewer_sessions_fail_closed(migrated_engine: Engine) -> None:
    now = datetime.now(UTC)
    expired_hash = b"expired-viewer-token-hash"

    with PostgresUnitOfWork(migrated_engine) as uow:
        seed_operator(uow)
        SessionRepository(uow.connection).create_demo_session(
            session_id=uuid4(),
            workspace_id=WORKSPACE_ID,
            token_hash=expired_hash,
            csrf_hash=b"expired-csrf-hash",
            source_address_hash=b"expired-source-hash",
            now=now - timedelta(hours=3),
            idle_expires_at=now - timedelta(hours=2, minutes=30),
            absolute_expires_at=now - timedelta(hours=1),
        )

    with migrated_engine.connect() as connection:
        assert SessionRepository(connection).get_active_demo_session(expired_hash, now) is None


def test_idempotency_projection_exposes_no_request_or_key_hash(
    migrated_engine: Engine,
) -> None:
    now = datetime.now(UTC)
    with PostgresUnitOfWork(migrated_engine) as uow:
        receipt = SessionRepository(uow.connection).create_idempotency_receipt(
            scope_type="operator",
            scope_id="operator-session",
            operation="synthetic-import",
            key_hash=b"idempotency-key-hash",
            request_hash=b"request-body-hash",
            created_at=now,
            expires_at=now + timedelta(hours=2),
        )

    assert receipt.outcome == "in_progress"
    assert not hasattr(receipt, "key_hash")
    assert not hasattr(receipt, "request_hash")
    assert not hasattr(receipt, "response_body_hash")
