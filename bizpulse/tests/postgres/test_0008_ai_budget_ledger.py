from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from tests.conftest import run_alembic


def test_0008_adds_durable_ai_budget_ledger_and_sync_triggers(
    postgres_url: str,
) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    engine = create_engine(postgres_url)
    try:
        inspector = inspect(engine)
        assert "ai_budget_ledger" in inspector.get_table_names()
        columns = {
            column["name"] for column in inspector.get_columns("ai_budget_ledger")
        }
        assert {
            "attempt_id",
            "workspace_id",
            "stage",
            "input_tokens",
            "output_tokens",
            "reserved_tokens",
            "status",
            "created_at",
            "completed_at",
        } <= columns
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM alembic_version")
            ) == "0017_ai_turn_credential_binding"
            trigger_count = connection.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgname IN "
                    "('ai_budget_ledger_insert_sync', "
                    "'ai_budget_ledger_update_sync', "
                    "'ai_budget_ledger_protected') AND NOT tgisinternal"
                )
            )
        assert trigger_count == 3
    finally:
        engine.dispose()
