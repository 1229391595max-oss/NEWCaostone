from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from tests.conftest import run_alembic

AI_CHAT_TABLES = {
    "ai_chat_turns",
    "ai_chat_tool_runs",
    "ai_chat_evidence",
    "ai_chat_attempts",
    "ai_chat_saved_records",
}


def test_0006_creates_bounded_chat_authority_and_exact_head(
    postgres_url: str,
) -> None:
    run_alembic(postgres_url, "upgrade", "0006_ai_chat")
    engine = create_engine(postgres_url)
    try:
        inspector = inspect(engine)
        assert AI_CHAT_TABLES <= set(inspector.get_table_names())
        turn_columns = {
            column["name"] for column in inspector.get_columns("ai_chat_turns")
        }
        assert {
            "dataset_version_id",
            "question_digest",
            "plan_schema_version",
            "output_schema_version",
            "idempotency_key_hash",
            "request_hash",
            "result_hash",
            "safe_summary",
            "lease_expires_at",
        } <= turn_columns
        assert not {
            "sql",
            "database_url",
            "api_key",
            "provider_body",
            "raw_rows",
        }.intersection(turn_columns)
        attempt_columns = {
            column["name"] for column in inspector.get_columns("ai_chat_attempts")
        }
        assert {
            "model",
            "reasoning_effort",
            "input_tokens",
            "output_tokens",
            "reserved_tokens",
        } <= (
            attempt_columns
        )
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0006_ai_chat"
            )
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger "
                    "WHERE tgname = 'ai_chat_attempts_protected' "
                    "AND NOT tgisinternal"
                )
            ) == 1
    finally:
        engine.dispose()


def test_0006_adds_chat_turn_foreign_key_without_mutable_payload_columns(
    postgres_url: str,
) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    engine = create_engine(postgres_url)
    try:
        inspector = inspect(engine)
        foreign_keys = inspector.get_foreign_keys("action_card_revisions")
        assert any(
            key["name"] == "fk_action_card_revisions_chat_turn"
            and key["referred_table"] == "ai_chat_turns"
            for key in foreign_keys
        )
        tool_columns = {
            column["name"] for column in inspector.get_columns("ai_chat_tool_runs")
        }
        assert not {"sql", "raw_query", "connection_string"}.intersection(tool_columns)
    finally:
        engine.dispose()
