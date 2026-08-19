from __future__ import annotations

from datetime import timedelta

from sqlalchemy import Engine
from sqlalchemy import select

from src.db.schema import demo_sessions
from src.services.demo_session_service import DemoSessionService
from tests.auth_support import (
    SESSION_PEPPER,
    WORKSPACE_ID,
    fast_password_hasher,
    initial_clock,
    seed_public_release,
    seed_operator,
)


def service(engine: Engine, clock) -> DemoSessionService:
    return DemoSessionService(
        engine=engine,
        workspace_id=WORKSPACE_ID,
        session_pepper=SESSION_PEPPER,
        clock=clock,
    )


def test_idle_expiry_extends_without_moving_absolute_expiry(
    migrated_engine: Engine,
) -> None:
    clock = initial_clock()
    seed_operator(migrated_engine, fast_password_hasher())
    seed_public_release(migrated_engine)
    issued = service(migrated_engine, clock).create("source-hash", clock.now)

    assert issued.principal.idle_expires_at == clock.now + timedelta(minutes=30)
    assert issued.principal.absolute_expires_at == clock.now + timedelta(hours=2)

    clock.now += timedelta(minutes=20)
    resumed = service(migrated_engine, clock).resolve(issued.session_token, clock.now)

    assert resumed is not None
    assert resumed.idle_expires_at == clock.now + timedelta(minutes=30)
    assert resumed.absolute_expires_at == issued.principal.absolute_expires_at


def test_expired_session_cannot_resume(migrated_engine: Engine) -> None:
    clock = initial_clock()
    seed_operator(migrated_engine, fast_password_hasher())
    seed_public_release(migrated_engine)
    issued = service(migrated_engine, clock).create("source-hash", clock.now)
    clock.now += timedelta(minutes=31)

    assert service(migrated_engine, clock).resolve(issued.session_token, clock.now) is None


def test_maintenance_marks_expired_sessions(migrated_engine: Engine) -> None:
    clock = initial_clock()
    seed_operator(migrated_engine, fast_password_hasher())
    seed_public_release(migrated_engine)
    issued = service(migrated_engine, clock).create("source-hash", clock.now)
    clock.now += timedelta(minutes=31)

    expired_count = service(migrated_engine, clock).expire_sessions(clock.now)

    with migrated_engine.connect() as connection:
        status = connection.scalar(
            select(demo_sessions.c.status).where(
                demo_sessions.c.id == issued.principal.session_id
            )
        )
    assert expired_count == 1
    assert status == "expired"


def test_release_validation_runs_without_holding_a_database_connection(
    migrated_engine: Engine,
) -> None:
    clock = initial_clock()
    seed_operator(migrated_engine, fast_password_hasher())
    seed_public_release(migrated_engine)
    checked_out = []
    sessions = DemoSessionService(
        engine=migrated_engine,
        workspace_id=WORKSPACE_ID,
        session_pepper=SESSION_PEPPER,
        clock=clock,
        release_validator=lambda _version_id: (
            checked_out.append(migrated_engine.pool.checkedout()) or True
        ),
    )

    issued = sessions.create("source-hash", clock.now)

    assert issued.principal.dataset_version_id is not None
    assert checked_out == [0]


def test_demo_data_activation_is_an_idempotent_session_marker(
    migrated_engine: Engine,
) -> None:
    clock = initial_clock()
    seed_operator(migrated_engine, fast_password_hasher())
    seed_public_release(migrated_engine)
    sessions = service(migrated_engine, clock)
    issued = sessions.create("source-hash", clock.now)

    assert issued.principal.demo_data_imported_at is None

    first = sessions.import_demo_data(issued.principal.session_id, clock.now)
    clock.now += timedelta(minutes=1)
    second = sessions.import_demo_data(issued.principal.session_id, clock.now)

    assert first is not None
    assert second is not None
    assert first.demo_data_imported_at == issued.principal.created_at
    assert second.demo_data_imported_at == first.demo_data_imported_at
