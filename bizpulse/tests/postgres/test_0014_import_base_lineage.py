from __future__ import annotations

from sqlalchemy import create_engine, inspect

from tests.conftest import run_alembic


def test_0014_adds_scoped_lineage_and_store_assignment(postgres_url: str) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    engine = create_engine(postgres_url)
    try:
        inspector = inspect(engine)
        columns = {
            table: {column["name"] for column in inspector.get_columns(table)}
            for table in ("import_workflows", "upload_records", "dataset_versions")
        }
        foreign_keys = {
            constraint["name"]
            for table in ("import_workflows", "dataset_versions")
            for constraint in inspector.get_foreign_keys(table)
        }
        indexes = {
            index["name"]
            for table in ("import_workflows", "dataset_versions")
            for index in inspector.get_indexes(table)
        }
        ai_attempt_checks = {
            constraint["name"]: constraint["sqltext"]
            for constraint in inspector.get_check_constraints("ai_chat_attempts")
        }

        assert "base_dataset_version_id" in columns["import_workflows"]
        assert "assigned_store_id" in columns["upload_records"]
        assert "base_version_id" in columns["dataset_versions"]
        assert "fk_import_workflows_base_dataset_version" in foreign_keys
        assert "fk_dataset_versions_base_version" in foreign_keys
        assert "ix_import_workflows_base_dataset_version" in indexes
        assert "ix_dataset_versions_base_version" in indexes
        assert "gpt-5.4-nano-2026-03-17" in ai_attempt_checks[
            "ck_ai_chat_attempts_model"
        ]
    finally:
        engine.dispose()


def test_0014_downgrades_to_exact_0013(postgres_url: str) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    run_alembic(postgres_url, "downgrade", "0013_workspace_preferences")
    engine = create_engine(postgres_url)
    try:
        inspector = inspect(engine)
        assert "base_dataset_version_id" not in {
            column["name"] for column in inspector.get_columns("import_workflows")
        }
        assert "assigned_store_id" not in {
            column["name"] for column in inspector.get_columns("upload_records")
        }
        assert "base_version_id" not in {
            column["name"] for column in inspector.get_columns("dataset_versions")
        }
        ai_attempt_checks = {
            constraint["name"]: constraint["sqltext"]
            for constraint in inspector.get_check_constraints("ai_chat_attempts")
        }
        assert "gpt-5.4-mini-2026-03-17" in ai_attempt_checks[
            "ck_ai_chat_attempts_model"
        ]
    finally:
        engine.dispose()
