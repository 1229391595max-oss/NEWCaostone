from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import run_alembic

ACTION_TABLES = {
    "action_cards",
    "action_card_revisions",
    "action_decisions",
    "action_exports",
    "action_outcomes",
    "demo_action_overlays",
}


def test_0005_creates_action_tables_and_head(postgres_url: str) -> None:
    run_alembic(postgres_url, "upgrade", "0005_actions")
    engine = create_engine(postgres_url)
    try:
        inspector = inspect(engine)
        assert ACTION_TABLES <= set(inspector.get_table_names())
        assert {
            "source_type",
            "status",
            "current_revision",
            "dataset_version_id",
        } <= {column["name"] for column in inspector.get_columns("action_cards")}
        assert {
            "analysis_run_id",
            "forecast_id",
            "bridge_id",
            "chat_turn_id",
            "facts",
        } <= {
            column["name"]
            for column in inspector.get_columns("action_card_revisions")
        }
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0005_actions"
            )
    finally:
        engine.dispose()


def test_database_rejects_state_jump_and_revision_mutation(postgres_url: str) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    engine = create_engine(postgres_url)
    now = datetime.now(UTC)
    workspace_id = "synthetic-demo"
    series_id = uuid4()
    version_id = uuid4()
    action_id = uuid4()
    revision_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO workspaces (id, kind, created_at) "
                    "VALUES (:workspace, 'single_operator_demo', :now)"
                ),
                {"workspace": workspace_id, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO dataset_series (id, workspace_id, name, created_at) "
                    "VALUES (:id, :workspace, 'main', :now)"
                ),
                {"id": series_id, "workspace": workspace_id, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO dataset_versions "
                    "(id, series_id, workspace_id, version_number, status, "
                    "schema_version, content_sha256, created_at) VALUES "
                    "(:id, :series, :workspace, 1, 'complete', 'synthetic.v1', "
                    ":digest, :now)"
                ),
                {
                    "id": version_id,
                    "series": series_id,
                    "workspace": workspace_id,
                    "digest": "1" * 64,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO action_cards "
                    "(id, workspace_id, dataset_version_id, source_type, status, "
                    "current_revision, idempotency_key_hash, request_hash, created_at, "
                    "updated_at, terminal_at) VALUES "
                    "(:id, :workspace, :version, 'deterministic_rule', 'new', 1, "
                    ":key, :request, :now, :now, NULL)"
                ),
                {
                    "id": action_id,
                    "workspace": workspace_id,
                    "version": version_id,
                    "key": b"k" * 32,
                    "request": b"r" * 32,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO action_card_revisions "
                    "(id, action_id, revision, suggestion, target, period_start, "
                    "period_end, scope, quantity, budget_brl, action_date, threshold, "
                    "expected_impact, confidence, limitations, facts, analysis_run_id, "
                    "forecast_id, bridge_id, chat_turn_id, chat_tool, answer_version, "
                    "created_at) VALUES "
                    "(:id, :action, 1, 'Review stock', 'SYNTH-SKU-001', '2026-07-01', "
                    "'2026-07-30', '{\"currency\":\"BRL\"}'::jsonb, 10, 20, NULL, 5, "
                    "'{}'::jsonb, 'medium', '[]'::jsonb, '[]'::jsonb, NULL, NULL, "
                    "NULL, NULL, NULL, NULL, :now)"
                ),
                {"id": revision_id, "action": action_id, "now": now},
            )
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE action_cards SET status='approved', terminal_at=:now "
                        "WHERE id=:id"
                    ),
                    {"id": action_id, "now": now},
                )
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE action_card_revisions SET quantity=99 WHERE id=:id"
                    ),
                    {"id": revision_id},
                )
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO action_card_revisions "
                        "SELECT :new_id, action_id, 2, suggestion, target, period_start, "
                        "period_end, scope, quantity, budget_brl, action_date, threshold, "
                        "expected_impact, confidence, limitations, facts, analysis_run_id, "
                        "forecast_id, bridge_id, chat_turn_id, chat_tool, answer_version, "
                        "created_at FROM action_card_revisions WHERE id=:id"
                    ),
                    {"new_id": uuid4(), "id": revision_id},
                )
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE action_cards SET status='reviewed', "
                        "source_type='profit_bridge', updated_at=:now WHERE id=:id"
                    ),
                    {"id": action_id, "now": now},
                )
    finally:
        engine.dispose()
