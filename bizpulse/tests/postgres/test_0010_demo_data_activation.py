from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from tests.conftest import run_alembic


def test_0009_upgrades_append_only_with_demo_activation_marker(
    postgres_url: str,
) -> None:
    run_alembic(postgres_url, "upgrade", "0009_prompt_preset_audit")
    before = create_engine(postgres_url)
    try:
        assert "demo_data_imported_at" not in {
            column["name"]
            for column in inspect(before).get_columns("demo_sessions")
        }
    finally:
        before.dispose()

    run_alembic(postgres_url, "upgrade", "head")
    after = create_engine(postgres_url)
    try:
        assert "demo_data_imported_at" in {
            column["name"]
            for column in inspect(after).get_columns("demo_sessions")
        }
        with after.connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM alembic_version")
            ) == "0017_ai_turn_credential_binding"
    finally:
        after.dispose()


def test_demo_activation_migration_downgrades_to_exact_0009(
    postgres_url: str,
) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    run_alembic(postgres_url, "downgrade", "0009_prompt_preset_audit")
    engine = create_engine(postgres_url)
    try:
        assert "demo_data_imported_at" not in {
            column["name"]
            for column in inspect(engine).get_columns("demo_sessions")
        }
    finally:
        engine.dispose()
