from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import run_alembic

NEW_TABLES = {
    "storage_objects",
    "import_workflows",
    "upload_records",
    "dataset_series",
    "dataset_versions",
    "dataset_artifacts",
    "public_releases",
}


def test_0002_creates_exact_import_and_version_tables(postgres_url: str) -> None:
    run_alembic(postgres_url, "upgrade", "0002_import_versions")
    engine = create_engine(postgres_url)
    try:
        inspector = inspect(engine)
        assert NEW_TABLES <= set(inspector.get_table_names())
        assert {
            "revision",
            "source_confirmed_synthetic",
        } <= {column["name"] for column in inspector.get_columns("import_workflows")}
        assert {
            "adapter_id",
            "adapter_version",
            "source_role",
            "recognition",
            "mapping",
            "mapping_revision",
            "quality_report",
            "candidate_storage_object_id",
        } <= {column["name"] for column in inspector.get_columns("upload_records")}
        assert "current_version_id" in {
            column["name"] for column in inspector.get_columns("dataset_series")
        }
        assert "source_workflow_id" in {
            column["name"] for column in inspector.get_columns("dataset_versions")
        }
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0002_import_versions"
            )
        demo_foreign_keys = inspector.get_foreign_keys("demo_sessions")
        assert any(
            foreign_key["constrained_columns"]
            == ["workspace_id", "dataset_version_id"]
            and foreign_key["referred_table"] == "dataset_versions"
            for foreign_key in demo_foreign_keys
        )
    finally:
        engine.dispose()


def test_storage_state_and_public_pointer_constraints_are_database_owned(
    postgres_url: str,
) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    engine = create_engine(postgres_url)
    now = datetime.now(UTC)
    workspace_id = "synthetic-demo"
    series_id = uuid4()
    version_one = uuid4()
    version_two = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO workspaces (id, kind, created_at) "
                    "VALUES (:id, 'single_operator_demo', :now)"
                ),
                {"id": workspace_id, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO dataset_series "
                    "(id, workspace_id, name, created_at) "
                    "VALUES (:id, :workspace_id, 'synthetic-main', :now)"
                ),
                {"id": series_id, "workspace_id": workspace_id, "now": now},
            )
            for number, version_id in enumerate((version_one, version_two), start=1):
                connection.execute(
                    text(
                        "INSERT INTO dataset_versions "
                        "(id, series_id, workspace_id, version_number, status, "
                        "schema_version, content_sha256, created_at) VALUES "
                        "(:id, :series_id, :workspace_id, :number, 'complete', "
                        "'synthetic.v1', :digest, :now)"
                    ),
                    {
                        "id": version_id,
                        "series_id": series_id,
                        "workspace_id": workspace_id,
                        "number": number,
                        "digest": f"{number:064x}",
                        "now": now,
                    },
                )
            connection.execute(
                text(
                    "INSERT INTO public_releases "
                    "(id, workspace_id, dataset_version_id, is_active, released_at) "
                    "VALUES (:id, :workspace_id, :version_id, true, :now)"
                ),
                {
                    "id": uuid4(),
                    "workspace_id": workspace_id,
                    "version_id": version_one,
                    "now": now,
                },
            )

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO public_releases "
                        "(id, workspace_id, dataset_version_id, is_active, released_at) "
                        "VALUES (:id, :workspace_id, :version_id, true, :now)"
                    ),
                    {
                        "id": uuid4(),
                        "workspace_id": workspace_id,
                        "version_id": version_two,
                        "now": now,
                    },
                )

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE dataset_versions SET content_sha256 = :digest "
                        "WHERE id = :id"
                    ),
                    {"digest": "f" * 64, "id": version_one},
                )
    finally:
        engine.dispose()


def test_storage_objects_reject_invalid_state_and_digest(postgres_url: str) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    engine = create_engine(postgres_url)
    now = datetime.now(UTC)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO workspaces (id, kind, created_at) "
                    "VALUES ('synthetic-demo', 'single_operator_demo', :now)"
                ),
                {"now": now},
            )
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO storage_objects "
                        "(id, workspace_id, object_key, purpose, state, media_type, "
                        "size_bytes, sha256, created_at, updated_at) VALUES "
                        "(:id, 'synthetic-demo', 'bad/state', 'temporary_upload', "
                        "'published', 'text/csv', 1, 'not-a-digest', :now, :now)"
                    ),
                    {"id": uuid4(), "now": now},
                )
    finally:
        engine.dispose()


def test_dataset_and_release_pointers_cannot_cross_workspace(
    postgres_url: str,
) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    engine = create_engine(postgres_url)
    now = datetime.now(UTC)
    first_series = uuid4()
    second_series = uuid4()
    first_version = uuid4()
    try:
        with engine.begin() as connection:
            for workspace_id in ("synthetic-demo", "synthetic-other"):
                connection.execute(
                    text(
                        "INSERT INTO workspaces (id, kind, created_at) "
                        "VALUES (:id, 'single_operator_demo', :now)"
                    ),
                    {"id": workspace_id, "now": now},
                )
            connection.execute(
                text(
                    "INSERT INTO dataset_series (id, workspace_id, name, created_at) "
                    "VALUES (:first, 'synthetic-demo', 'main', :now), "
                    "(:second, 'synthetic-other', 'other', :now)"
                ),
                {"first": first_series, "second": second_series, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO dataset_versions "
                    "(id, series_id, workspace_id, version_number, status, "
                    "schema_version, content_sha256, created_at) VALUES "
                    "(:id, :series, 'synthetic-demo', 1, 'complete', "
                    "'synthetic.v1', :digest, :now)"
                ),
                {
                    "id": first_version,
                    "series": first_series,
                    "digest": "1" * 64,
                    "now": now,
                },
            )

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE dataset_series SET current_version_id = :version "
                        "WHERE id = :series"
                    ),
                    {"version": first_version, "series": second_series},
                )

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO public_releases "
                        "(id, workspace_id, dataset_version_id, is_active, "
                        "released_at) VALUES "
                        "(:id, 'synthetic-other', :version, true, :now)"
                    ),
                    {"id": uuid4(), "version": first_version, "now": now},
                )
    finally:
        engine.dispose()
