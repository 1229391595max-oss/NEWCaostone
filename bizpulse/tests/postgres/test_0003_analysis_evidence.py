from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import run_alembic

ANALYSIS_TABLES = {
    "analysis_runs",
    "analysis_dependencies",
    "analysis_artifacts",
    "evidence_items",
}


def test_0003_creates_exact_analysis_tables_and_head(postgres_url: str) -> None:
    run_alembic(postgres_url, "upgrade", "0003_analysis_evidence")
    engine = create_engine(postgres_url)
    try:
        inspector = inspect(engine)
        assert ANALYSIS_TABLES <= set(inspector.get_table_names())
        assert {
            "analysis_kind",
            "algorithm_version",
            "input_hash",
            "scope",
            "scope_hash",
            "status",
            "failure_code",
            "lease_expires_at",
        } <= {column["name"] for column in inspector.get_columns("analysis_runs")}
        assert {"alias", "evidence_state", "formula", "source_refs"} <= {
            column["name"] for column in inspector.get_columns("evidence_items")
        }
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003_analysis_evidence"
    finally:
        engine.dispose()


def test_completed_analysis_and_evidence_are_database_immutable(postgres_url: str) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    engine = create_engine(postgres_url)
    now = datetime.now(UTC)
    workspace_id = "synthetic-demo"
    series_id = uuid4()
    version_id = uuid4()
    run_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO workspaces (id, kind, created_at) VALUES (:id, 'single_operator_demo', :now)"), {"id": workspace_id, "now": now})
            connection.execute(text("INSERT INTO dataset_series (id, workspace_id, name, created_at) VALUES (:id, :workspace, 'main', :now)"), {"id": series_id, "workspace": workspace_id, "now": now})
            connection.execute(text("INSERT INTO dataset_versions (id, series_id, workspace_id, version_number, status, schema_version, content_sha256, created_at) VALUES (:id, :series, :workspace, 1, 'complete', 'synthetic.v1', :digest, :now)"), {"id": version_id, "series": series_id, "workspace": workspace_id, "digest": "1" * 64, "now": now})
            connection.execute(text("INSERT INTO analysis_runs (id, workspace_id, dataset_version_id, analysis_kind, algorithm_version, input_hash, scope, scope_hash, status, created_at, lease_expires_at) VALUES (:id, :workspace, :version, 'sales_ads', 'sales_ads.v1', :digest, '{}'::jsonb, :digest, 'running', :now, :now)"), {"id": run_id, "workspace": workspace_id, "version": version_id, "digest": "2" * 64, "now": now})
            connection.execute(text("INSERT INTO evidence_items (id, run_id, alias, evidence_state, formula, source_refs, created_at) VALUES (:id, :run, 'sales.total', 'measured', 'sum(gross)', '[]'::jsonb, :now)"), {"id": uuid4(), "run": run_id, "now": now})
            connection.execute(text("UPDATE analysis_runs SET status = 'completed', completed_at = :now, lease_expires_at = NULL WHERE id = :id"), {"id": run_id, "now": now})

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(text("UPDATE analysis_runs SET input_hash = :digest WHERE id = :id"), {"digest": "3" * 64, "id": run_id})
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(text("UPDATE evidence_items SET formula = 'changed' WHERE run_id = :id"), {"id": run_id})
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO evidence_items (id, run_id, alias, evidence_state, formula, source_refs, created_at) VALUES (:id, :run, 'late.evidence', 'derived', 'late', '[]'::jsonb, :now)"), {"id": uuid4(), "run": run_id, "now": now})
    finally:
        engine.dispose()
