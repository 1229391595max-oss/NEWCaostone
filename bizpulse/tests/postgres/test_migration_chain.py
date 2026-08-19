from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from src.db.readiness import (
    EXPECTED_SCHEMA_REVISION,
    FORWARD_COMPATIBLE_SCHEMA_REVISIONS,
    readiness,
)
from src.db.schema import metadata
from tests.conftest import run_alembic

EXPECTED_TABLES = {
    "alembic_version",
    "workspaces",
    "operator_accounts",
    "operator_sessions",
    "demo_sessions",
    "idempotency_receipts",
    "storage_objects",
    "import_workflows",
    "upload_records",
    "dataset_series",
    "dataset_versions",
    "dataset_artifacts",
    "dataset_exports",
    "workspace_preferences",
    "saved_views",
    "workspace_targets",
    "public_releases",
    "analysis_runs",
    "analysis_dependencies",
    "analysis_artifacts",
    "evidence_items",
    "new_product_forecasts",
    "forecast_analogs",
    "forecast_scenarios",
    "profit_bridges",
    "profit_bridge_items",
    "action_cards",
    "action_card_revisions",
    "action_decisions",
    "action_exports",
    "action_outcomes",
    "demo_action_overlays",
    "ai_chat_turns",
    "ai_chat_tool_runs",
    "ai_chat_evidence",
    "ai_chat_attempts",
    "ai_budget_ledger",
    "ai_chat_saved_records",
    "ai_control_state",
    "admin_audit_events",
}
EXPECTED_HEAD = EXPECTED_SCHEMA_REVISION


def test_readiness_expectation_matches_the_unique_alembic_head() -> None:
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")

    heads = ScriptDirectory.from_config(config).get_heads()

    assert heads == [EXPECTED_SCHEMA_REVISION]


def current_revision(database_url: str) -> str:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return str(connection.scalar(text("SELECT version_num FROM alembic_version")))
    finally:
        engine.dispose()


def test_empty_database_upgrades_to_exact_foundation_head(postgres_url: str) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    engine = create_engine(postgres_url)
    try:
        assert current_revision(postgres_url) == EXPECTED_HEAD
        assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    finally:
        engine.dispose()


def test_foundation_schema_contains_hashes_but_no_raw_secrets(postgres_url: str) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    engine = create_engine(postgres_url)
    try:
        inspector = inspect(engine)
        columns = {
            table: {column["name"] for column in inspector.get_columns(table)}
            for table in EXPECTED_TABLES - {"alembic_version"}
        }

        assert {"password_hash"} <= columns["operator_accounts"]
        assert {"token_hash", "csrf_hash"} <= columns["operator_sessions"]
        assert {"token_hash", "csrf_hash", "source_address_hash"} <= columns[
            "demo_sessions"
        ]
        assert {
            "key_hash",
            "request_hash",
            "response_body_hash",
            "response_projection",
        } <= columns["idempotency_receipts"]
        assert {
            "question",
            "credential_binding_id",
            "credential_control_revision",
            "credential_request_id",
            "prompt_locale",
            "prompt_template_version",
            "prompt_template_sha256",
            "prompt_audit_state",
        } <= columns["ai_chat_turns"]
        assert {"base_dataset_version_id"} <= columns["import_workflows"]
        assert {"assigned_store_id"} <= columns["upload_records"]
        assert {"base_version_id"} <= columns["dataset_versions"]
        assert not {
            "password",
            "token",
            "csrf_token",
            "key",
            "request_body",
            "response_body",
        }.intersection(set().union(*columns.values()))
    finally:
        engine.dispose()


def test_alembic_head_columns_match_declared_sqlalchemy_metadata(
    postgres_url: str,
) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    engine = create_engine(postgres_url)
    try:
        inspector = inspect(engine)
        for table_name, table in metadata.tables.items():
            observed = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            expected = {column.name for column in table.columns}
            assert observed == expected, table_name
    finally:
        engine.dispose()


def test_foundation_can_downgrade_and_restart_before_acceptance(
    postgres_url: str,
) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    run_alembic(postgres_url, "downgrade", "base")
    engine = create_engine(postgres_url)
    try:
        assert inspect(engine).get_table_names() == ["alembic_version"]
    finally:
        engine.dispose()

    run_alembic(postgres_url, "upgrade", "head")
    assert current_revision(postgres_url) == EXPECTED_HEAD


def test_readiness_reports_revision_and_writability_without_connection_data(
    migrated_engine,
) -> None:
    result = readiness(migrated_engine)

    assert result.revision == EXPECTED_HEAD
    assert result.writable is True
    assert result.latency_ms >= 0
    assert not hasattr(result, "database_url")
    assert not hasattr(result, "connection")


def test_current_0014_candidate_readiness_reaches_0017_after_one_job_start(
    postgres_url: str,
) -> None:
    run_alembic(postgres_url, "upgrade", "0014_import_base_lineage")
    engine = create_engine(postgres_url)
    try:
        before = readiness(engine)
        assert before.revision == "0014_import_base_lineage"
        assert before.revision in FORWARD_COMPATIBLE_SCHEMA_REVISIONS

        starts = 0

        def start_migration_job_once() -> None:
            nonlocal starts
            starts += 1
            run_alembic(postgres_url, "upgrade", "head")

        start_migration_job_once()

        after = readiness(engine)
        assert starts == 1
        assert after.revision == EXPECTED_SCHEMA_REVISION
        assert after.revision in FORWARD_COMPATIBLE_SCHEMA_REVISIONS
    finally:
        engine.dispose()

    run_alembic(postgres_url, "downgrade", "0013_workspace_preferences")
    unsupported_engine = create_engine(postgres_url)
    try:
        unsupported = readiness(unsupported_engine)
        assert unsupported.revision == "0013_workspace_preferences"
        assert unsupported.revision not in FORWARD_COMPATIBLE_SCHEMA_REVISIONS
    finally:
        unsupported_engine.dispose()
