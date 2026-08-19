from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from tests.conftest import run_alembic


def test_0010_upgrades_with_legacy_backfill_and_operator_constraint(
    postgres_url: str,
) -> None:
    run_alembic(postgres_url, "upgrade", "0010_demo_data_activation")
    engine = create_engine(postgres_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO workspaces (id, kind, created_at) "
                    "VALUES ('legacy-workspace', 'single_operator_demo', now())"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO import_workflows "
                    "(id, workspace_id, status, revision, source_confirmed_synthetic, "
                    "created_at, updated_at) VALUES "
                    "('00000000-0000-0000-0000-000000000011', 'legacy-workspace', "
                    "'created', 0, true, now(), now())"
                )
            )
    finally:
        engine.dispose()

    run_alembic(postgres_url, "upgrade", "head")
    upgraded = create_engine(postgres_url)
    try:
        columns = {
            column["name"]
            for column in inspect(upgraded).get_columns("import_workflows")
        }
        assert "source_kind" in columns
        with upgraded.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT source_kind FROM import_workflows "
                    "WHERE id = '00000000-0000-0000-0000-000000000011'"
                )
            ) == "legacy_synthetic"
    finally:
        upgraded.dispose()


def test_operator_source_kind_downgrades_to_exact_0010(postgres_url: str) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    run_alembic(postgres_url, "downgrade", "0010_demo_data_activation")
    engine = create_engine(postgres_url)
    try:
        assert "source_kind" not in {
            column["name"]
            for column in inspect(engine).get_columns("import_workflows")
        }
    finally:
        engine.dispose()
