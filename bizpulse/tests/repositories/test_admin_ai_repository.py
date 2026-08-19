from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from src.db.schema import admin_audit_events, metadata
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.admin_ai import (
    AIControlBusy,
    AIControlKeyBindingError,
    AIControlRepository,
)
from src.repositories.operators import OperatorRepository
from tests.conftest import run_alembic

WORKSPACE_ID = "synthetic-demo"


def seed_operator(engine: Engine):
    with PostgresUnitOfWork(engine) as uow:
        operators = OperatorRepository(uow.connection)
        operators.create_workspace(WORKSPACE_ID)
        return operators.create_operator(
            workspace_id=WORKSPACE_ID,
            login_name="operator",
            password_hash="$argon2id$test-only-hash",
        )


def test_control_defaults_fail_closed_and_audit_is_secret_free(
    migrated_engine: Engine,
) -> None:
    operator = seed_operator(migrated_engine)
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    with PostgresUnitOfWork(migrated_engine) as uow:
        repository = AIControlRepository(uow.connection)
        state = repository.get_or_create(WORKSPACE_ID, now=now)
        event = repository.append_audit(
            workspace_id=WORKSPACE_ID,
            operator_id=operator.id,
            action="channels.update",
            result="succeeded",
            safe_error_code=None,
            prior_revision=state.revision,
            resulting_revision=state.revision,
            request_id="request-1",
            now=now,
        )

    assert state.operator_enabled is False
    assert state.demo_enabled is False
    assert state.key_version is None
    assert event.action == "channels.update"
    assert "key" not in repr(event).lower()


def test_control_updates_are_revisioned_and_lockable(migrated_engine: Engine) -> None:
    operator = seed_operator(migrated_engine)
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    with PostgresUnitOfWork(migrated_engine) as uow:
        repository = AIControlRepository(uow.connection)
        initial = repository.get_or_create(WORKSPACE_ID, now=now)
        locked = repository.lock(WORKSPACE_ID)
        activated = repository.activate_key(
            workspace_id=WORKSPACE_ID,
            expected_revision=locked.revision,
            key_name="bizpulse-openai",
            key_version="version-1",
            key_reference="bizpulse-openai/version-1",
            key_fingerprint="a" * 64,
            verified_at=now,
            updated_by_operator_id=operator.id,
            now=now,
        )
        enabled = repository.set_channels(
            workspace_id=WORKSPACE_ID,
            expected_revision=activated.revision,
            operator_enabled=True,
            demo_enabled=False,
            updated_by_operator_id=operator.id,
            now=now,
        )
        lost_update = repository.set_channels(
            workspace_id=WORKSPACE_ID,
            expected_revision=initial.revision,
            operator_enabled=False,
            demo_enabled=True,
            updated_by_operator_id=operator.id,
            now=now,
        )

    assert locked == initial
    assert activated is not None
    assert activated.key_name == "bizpulse-openai"
    assert activated.key_version == "version-1"
    assert activated.revision == 1
    assert enabled is not None
    assert enabled.operator_enabled is True
    assert enabled.demo_enabled is False
    assert enabled.revision == 2
    assert lost_update is None


def test_channel_enablement_rejects_an_unconfigured_control(
    migrated_engine: Engine,
) -> None:
    operator = seed_operator(migrated_engine)
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    with PostgresUnitOfWork(migrated_engine) as uow:
        repository = AIControlRepository(uow.connection)
        state = repository.get_or_create(WORKSPACE_ID, now=now)
        with pytest.raises(AIControlKeyBindingError) as raised:
            repository.set_channels(
                workspace_id=WORKSPACE_ID,
                expected_revision=state.revision,
                operator_enabled=True,
                demo_enabled=False,
                updated_by_operator_id=operator.id,
                now=now,
            )

    assert raised.value.code == "ADMIN_AI_KEY_UNVERIFIED"


def test_database_rejects_enabled_channels_without_a_verified_exact_key_binding(
    migrated_engine: Engine,
) -> None:
    seed_operator(migrated_engine)
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    with PostgresUnitOfWork(migrated_engine) as uow:
        AIControlRepository(uow.connection).get_or_create(WORKSPACE_ID, now=now)

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE ai_control_state SET operator_enabled = true "
                    "WHERE workspace_id = :workspace_id"
                ),
                {"workspace_id": WORKSPACE_ID},
            )

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE ai_control_state SET demo_enabled = true, "
                    "key_name = 'bizpulse-openai', key_version = 'version-1', "
                    "key_reference = 'wrong-reference', "
                    "key_fingerprint = repeat('a', 64), verified_at = :now, "
                    "key_validation_state = 'verified' "
                    "WHERE workspace_id = :workspace_id"
                ),
                {"workspace_id": WORKSPACE_ID, "now": now},
            )


def test_control_lock_returns_a_domain_busy_error_without_waiting(
    migrated_engine: Engine,
) -> None:
    seed_operator(migrated_engine)
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    with PostgresUnitOfWork(migrated_engine) as uow:
        AIControlRepository(uow.connection).get_or_create(WORKSPACE_ID, now=now)

    holder = PostgresUnitOfWork(migrated_engine).begin()
    contender = PostgresUnitOfWork(migrated_engine).begin()
    try:
        AIControlRepository(holder.connection).lock(WORKSPACE_ID)
        contender.connection.execute(text("SET LOCAL lock_timeout = '50ms'"))
        with pytest.raises(AIControlBusy) as raised:
            AIControlRepository(contender.connection).lock(WORKSPACE_ID)
    finally:
        contender.rollback()
        holder.rollback()

    assert raised.value.code == "ADMIN_AI_OPERATION_BUSY"


def test_audit_events_are_immutable_and_keep_workspace_operator_aligned(
    migrated_engine: Engine,
) -> None:
    operator = seed_operator(migrated_engine)
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    with PostgresUnitOfWork(migrated_engine) as uow:
        repository = AIControlRepository(uow.connection)
        state = repository.get_or_create(WORKSPACE_ID, now=now)
        event = repository.append_audit(
            workspace_id=WORKSPACE_ID,
            operator_id=operator.id,
            action="channels.update",
            result="succeeded",
            safe_error_code=None,
            prior_revision=state.revision,
            resulting_revision=state.revision,
            requested_operator_enabled=True,
            requested_demo_enabled=False,
            request_id="request-append-only",
            now=now,
        )
        OperatorRepository(uow.connection).create_workspace("other-workspace")

    for statement in (
        text("UPDATE admin_audit_events SET action = 'changed' WHERE id = :id"),
        text("DELETE FROM admin_audit_events WHERE id = :id"),
    ):
        with pytest.raises(DBAPIError, match="immutable_admin_audit_event"):
            with migrated_engine.begin() as connection:
                connection.execute(statement, {"id": event.id})

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                admin_audit_events.insert().values(
                    id=uuid4(),
                    workspace_id="other-workspace",
                    operator_id=operator.id,
                    action="channels.update",
                    result="succeeded",
                    safe_error_code=None,
                    prior_revision=0,
                    resulting_revision=0,
                    requested_operator_enabled=True,
                    requested_demo_enabled=False,
                    request_id="cross-workspace",
                    created_at=now,
                )
            )

    assert event.requested_operator_enabled is True
    assert event.requested_demo_enabled is False


def test_admin_ai_migration_matches_schema_metadata(postgres_url: str) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    engine = create_engine(postgres_url)
    try:
        inspector = inspect(engine)
        for table_name in ("ai_control_state", "admin_audit_events"):
            assert {
                column["name"] for column in inspector.get_columns(table_name)
            } == {column.name for column in metadata.tables[table_name].columns}

        control_checks = {
            constraint["name"] for constraint in inspector.get_check_constraints("ai_control_state")
        }
        audit_foreign_keys = {
            constraint["name"] for constraint in inspector.get_foreign_keys("admin_audit_events")
        }
        audit_indexes = {
            index["name"] for index in inspector.get_indexes("admin_audit_events")
        }

        assert {
            "ck_ai_control_state_revision",
            "ck_ai_control_state_key_binding",
            "ck_ai_control_state_enabled_requires_verified_key",
        } <= control_checks
        assert "admin_audit_events_workspace_id_fkey" in audit_foreign_keys
        assert "fk_admin_audit_events_workspace_operator" in audit_foreign_keys
        assert "ix_admin_audit_events_workspace_created_at" in audit_indexes
    finally:
        engine.dispose()


def test_admin_ai_migration_downgrades_audit_before_control(postgres_url: str) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    run_alembic(postgres_url, "downgrade", "0014_import_base_lineage")
    engine = create_engine(postgres_url)
    try:
        table_names = set(inspect(engine).get_table_names())
        assert "admin_audit_events" not in table_names
        assert "ai_control_state" not in table_names
    finally:
        engine.dispose()
