from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, create_engine, insert, inspect, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import run_alembic
from tests.import_support import WORKSPACE_ID


def test_0009_preserves_legacy_prompt_shape_without_inventing_question(
    postgres_url: str,
) -> None:
    run_alembic(postgres_url, "upgrade", "0008_ai_budget_ledger")
    engine = create_engine(postgres_url)
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    series_id = uuid4()
    dataset_version_id = uuid4()
    session_id = uuid4()
    turn_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO workspaces (id, kind, created_at) "
                "VALUES (:id, 'single_operator_demo', :created_at)"
            ),
            {"id": WORKSPACE_ID, "created_at": now},
        )
        connection.execute(
            text(
                "INSERT INTO dataset_series "
                "(id, workspace_id, name, current_version_id, created_at) "
                "VALUES (:id, :workspace_id, 'legacy-main', NULL, :created_at)"
            ),
            {"id": series_id, "workspace_id": WORKSPACE_ID, "created_at": now},
        )
        connection.execute(
            text(
                "INSERT INTO dataset_versions "
                "(id, series_id, workspace_id, source_workflow_id, version_number, "
                "status, schema_version, content_sha256, created_at) "
                "VALUES (:id, :series_id, :workspace_id, NULL, 1, 'complete', "
                "'synthetic.v1', :content_sha256, :created_at)"
            ),
            {
                "id": dataset_version_id,
                "series_id": series_id,
                "workspace_id": WORKSPACE_ID,
                "content_sha256": "d" * 64,
                "created_at": now,
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
                "INSERT INTO demo_sessions "
                "(id, workspace_id, token_hash, csrf_hash, source_address_hash, "
                "dataset_version_id, status, created_at, last_seen_at, "
                "idle_expires_at, absolute_expires_at, ended_at, chat_epoch) "
                "VALUES (:id, :workspace_id, :token_hash, :csrf_hash, :source_hash, "
                ":dataset_version_id, 'active', :created_at, :created_at, "
                ":idle_expires_at, :absolute_expires_at, NULL, 0)"
            ),
            {
                "id": session_id,
                "workspace_id": WORKSPACE_ID,
                "token_hash": b"legacy-prompt-token",
                "csrf_hash": b"legacy-prompt-csrf",
                "source_hash": b"legacy-prompt-source",
                "dataset_version_id": dataset_version_id,
                "created_at": now,
                "idle_expires_at": now + timedelta(minutes=30),
                "absolute_expires_at": now + timedelta(hours=2),
            },
        )
        legacy_turns = Table(
            "ai_chat_turns",
            MetaData(),
            autoload_with=connection,
        )
        connection.execute(
            insert(legacy_turns).values(
                id=turn_id,
                turn_sequence=1,
                workspace_id=WORKSPACE_ID,
                dataset_version_id=dataset_version_id,
                actor_kind="demo",
                operator_session_id=None,
                demo_session_id=session_id,
                question=None,
                recommended_question_id="inventory_risks",
                question_digest="a" * 64,
                scope={
                    "dataset_version_id": str(dataset_version_id),
                    "store_ids": ["SYNTH-STORE-01"],
                    "period_start": "2026-07-01",
                    "period_end": "2026-07-31",
                    "currency": "BRL",
                },
                status="planning",
                plan_schema_version="query-plan.v1",
                output_schema_version="chat-answer.v1",
                idempotency_key_hash=b"k" * 32,
                request_hash=b"r" * 32,
                created_at=now,
                updated_at=now,
                lease_expires_at=now + timedelta(minutes=15),
            )
        )
    engine.dispose()

    run_alembic(postgres_url, "upgrade", "head")
    migrated = create_engine(postgres_url)
    try:
        columns = {
            column["name"] for column in inspect(migrated).get_columns("ai_chat_turns")
        }
        turn_checks = {
            item["name"]: str(item["sqltext"])
            for item in inspect(migrated).get_check_constraints("ai_chat_turns")
        }
        tool_run_checks = {
            item["name"]: str(item["sqltext"])
            for item in inspect(migrated).get_check_constraints("ai_chat_tool_runs")
        }
        assert {
            "prompt_template_version",
            "prompt_template_sha256",
            "prompt_locale",
            "prompt_audit_state",
        } <= columns
        assert "monthly_sales_report_lookup" in turn_checks["ck_ai_chat_turns_tool"]
        assert (
            "monthly_sales_report_lookup"
            in tool_run_checks["ck_ai_chat_tool_runs_tool"]
        )
        with migrated.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT question, recommended_question_id, prompt_audit_state, "
                        "prompt_template_version, prompt_template_sha256, prompt_locale "
                        "FROM ai_chat_turns WHERE id = :turn_id"
                    ),
                    {"turn_id": turn_id},
                )
                .mappings()
                .one()
            )
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0017_ai_turn_credential_binding"
            )
        assert row["question"] is None
        assert row["recommended_question_id"] == "inventory_risks"
        assert row["prompt_audit_state"] == "legacy_unrecorded"
        assert row["prompt_template_version"] is None
        assert row["prompt_template_sha256"] is None
        assert row["prompt_locale"] is None
        with pytest.raises(DBAPIError):
            with migrated.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE ai_chat_turns SET prompt_audit_state = 'recorded' "
                        "WHERE id = :turn_id"
                    ),
                    {"turn_id": turn_id},
                )
    finally:
        migrated.dispose()
