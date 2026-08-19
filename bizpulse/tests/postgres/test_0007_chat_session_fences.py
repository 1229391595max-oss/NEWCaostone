from __future__ import annotations

from datetime import timedelta
import json
from uuid import uuid4

from sqlalchemy import create_engine, inspect, select, text

from src.db.schema import ai_chat_turns
from tests.conftest import run_alembic
from tests.import_support import WORKSPACE_ID
from tests.services.test_ai_chat_service import NOW


def test_committed_0006_database_upgrades_append_only_to_chat_fences(
    postgres_url: str,
) -> None:
    run_alembic(postgres_url, "upgrade", "0006_ai_chat")
    engine = create_engine(postgres_url)
    try:
        inspector = inspect(engine)
        assert "chat_epoch" not in {
            column["name"] for column in inspector.get_columns("demo_sessions")
        }
        assert "turn_sequence" not in {
            column["name"] for column in inspector.get_columns("ai_chat_turns")
        }
        series_id = uuid4()
        dataset_version_id = uuid4()
        operator_id = uuid4()
        session_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO workspaces (id, kind, created_at) "
                    "VALUES (:id, 'single_operator_demo', :created_at)"
                ),
                {"id": WORKSPACE_ID, "created_at": NOW},
            )
            connection.execute(
                text(
                    "INSERT INTO dataset_series "
                    "(id, workspace_id, name, current_version_id, created_at) "
                    "VALUES (:id, :workspace_id, 'legacy-main', NULL, :created_at)"
                ),
                {"id": series_id, "workspace_id": WORKSPACE_ID, "created_at": NOW},
            )
            connection.execute(
                text(
                    "INSERT INTO dataset_versions "
                    "(id, series_id, workspace_id, source_workflow_id, "
                    "version_number, status, schema_version, content_sha256, "
                    "created_at) VALUES (:id, :series_id, :workspace_id, NULL, 1, "
                    "'complete', 'synthetic.v1', :content_sha256, :created_at)"
                ),
                {
                    "id": dataset_version_id,
                    "series_id": series_id,
                    "workspace_id": WORKSPACE_ID,
                    "content_sha256": "c" * 64,
                    "created_at": NOW,
                },
            )
            connection.execute(
                text(
                    "UPDATE dataset_series SET current_version_id = :version_id "
                    "WHERE id = :series_id"
                ),
                {"version_id": dataset_version_id, "series_id": series_id},
            )
            connection.execute(
                text(
                    "INSERT INTO operator_accounts "
                    "(id, workspace_id, login_name, password_hash, status, "
                    "created_at, updated_at) VALUES (:id, :workspace_id, 'operator', "
                    "'legacy-hash', 'active', :created_at, :created_at)"
                ),
                {
                    "id": operator_id,
                    "workspace_id": WORKSPACE_ID,
                    "created_at": NOW,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO operator_sessions "
                    "(id, workspace_id, operator_id, token_hash, csrf_hash, "
                    "created_at, last_seen_at, idle_expires_at, absolute_expires_at, "
                    "revoked_at) VALUES (:id, :workspace_id, :operator_id, "
                    ":token_hash, :csrf_hash, :created_at, :created_at, "
                    ":idle_expires_at, :absolute_expires_at, NULL)"
                ),
                {
                    "id": session_id,
                    "workspace_id": WORKSPACE_ID,
                    "operator_id": operator_id,
                    "token_hash": b"legacy-chat-token",
                    "csrf_hash": b"legacy-chat-csrf",
                    "created_at": NOW,
                    "idle_expires_at": NOW + timedelta(minutes=30),
                    "absolute_expires_at": NOW + timedelta(hours=2),
                },
            )
            for index, status in enumerate(("failed", "planning")):
                created_at = NOW + timedelta(seconds=index)
                connection.execute(
                    text(
                        """
                        INSERT INTO ai_chat_turns (
                            id, workspace_id, dataset_version_id, actor_kind,
                            operator_session_id, demo_session_id, question,
                            recommended_question_id, question_digest, status,
                            scope, plan_schema_version, output_schema_version,
                            idempotency_key_hash, request_hash, error_code,
                            created_at, updated_at, lease_expires_at, completed_at
                        ) VALUES (
                            :id, :workspace_id, :dataset_version_id, 'operator',
                            :session_id, NULL, NULL, 'revenue_change', :digest, :status,
                            CAST(:scope AS jsonb), 'query-plan.v1', 'chat-answer.v1',
                            :key_hash, :request_hash, :error_code,
                            :created_at, :created_at, :lease_expires_at, :completed_at
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "workspace_id": WORKSPACE_ID,
                        "dataset_version_id": dataset_version_id,
                        "session_id": session_id,
                        "digest": f"{index + 1}" * 64,
                        "status": status,
                        "scope": json.dumps({"source": "legacy-0006"}),
                        "key_hash": bytes([index + 1]) * 32,
                        "request_hash": bytes([index + 3]) * 32,
                        "error_code": "legacy_failure" if status == "failed" else None,
                        "created_at": created_at,
                        "lease_expires_at": (
                            created_at + timedelta(minutes=2)
                            if status == "planning"
                            else None
                        ),
                        "completed_at": created_at if status == "failed" else None,
                    },
                )
    finally:
        engine.dispose()

    run_alembic(postgres_url, "upgrade", "head")
    upgraded = create_engine(postgres_url)
    try:
        inspector = inspect(upgraded)
        assert "chat_epoch" in {
            column["name"] for column in inspector.get_columns("demo_sessions")
        }
        assert "turn_sequence" in {
            column["name"] for column in inspector.get_columns("ai_chat_turns")
        }
        with upgraded.connect() as connection:
            assert tuple(
                connection.scalars(
                    select(ai_chat_turns.c.turn_sequence).order_by(
                        ai_chat_turns.c.created_at
                    )
                )
            ) == (1, 2)
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0017_ai_turn_credential_binding"
            )
    finally:
        upgraded.dispose()


def test_chat_session_fence_downgrade_restores_exact_committed_0006(
    postgres_url: str,
) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    run_alembic(postgres_url, "downgrade", "0006_ai_chat")
    engine = create_engine(postgres_url)
    try:
        inspector = inspect(engine)
        assert "chat_epoch" not in {
            column["name"] for column in inspector.get_columns("demo_sessions")
        }
        assert "turn_sequence" not in {
            column["name"] for column in inspector.get_columns("ai_chat_turns")
        }
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM alembic_version")
            ) == ("0006_ai_chat")
    finally:
        engine.dispose()
