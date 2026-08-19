"""SQLAlchemy Core authority for the BizPulse foundation schema."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

metadata = sa.MetaData()

workspaces = sa.Table(
    "workspaces",
    metadata,
    sa.Column("id", sa.Text(), primary_key=True),
    sa.Column("kind", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind = 'single_operator_demo'", name="ck_workspaces_kind"),
)

operator_accounts = sa.Table(
    "operator_accounts",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "workspace_id",
        sa.Text(),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("login_name", sa.Text(), nullable=False),
    sa.Column("password_hash", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "status IN ('active', 'disabled')",
        name="ck_operator_accounts_status",
    ),
    sa.UniqueConstraint(
        "workspace_id",
        "login_name",
        name="uq_operator_accounts_workspace_login",
    ),
    sa.UniqueConstraint(
        "workspace_id",
        "id",
        name="uq_operator_accounts_workspace_id",
    ),
)
sa.Index(
    "uq_operator_accounts_one_active_per_workspace",
    operator_accounts.c.workspace_id,
    unique=True,
    postgresql_where=operator_accounts.c.status == "active",
)

operator_sessions = sa.Table(
    "operator_sessions",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "workspace_id",
        sa.Text(),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "operator_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("operator_accounts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("token_hash", sa.LargeBinary(), nullable=False, unique=True),
    sa.Column("csrf_hash", sa.LargeBinary(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint(
        "idle_expires_at <= absolute_expires_at",
        name="ck_operator_sessions_expiry_order",
    ),
)

demo_sessions = sa.Table(
    "demo_sessions",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "workspace_id",
        sa.Text(),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("token_hash", sa.LargeBinary(), nullable=False, unique=True),
    sa.Column("csrf_hash", sa.LargeBinary(), nullable=False),
    sa.Column("source_address_hash", sa.LargeBinary(), nullable=False),
    sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("forecast_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("profit_bridge_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("demo_data_imported_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column(
        "chat_epoch",
        sa.Integer(),
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(
        ["workspace_id", "dataset_version_id"],
        ["dataset_versions.workspace_id", "dataset_versions.id"],
        name="fk_demo_sessions_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["workspace_id", "dataset_version_id", "forecast_id"],
        [
            "new_product_forecasts.workspace_id",
            "new_product_forecasts.dataset_version_id",
            "new_product_forecasts.id",
        ],
        name="fk_demo_sessions_forecast",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["workspace_id", "dataset_version_id", "profit_bridge_id"],
        [
            "profit_bridges.workspace_id",
            "profit_bridges.dataset_version_id",
            "profit_bridges.id",
        ],
        name="fk_demo_sessions_profit_bridge",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint(
        "status IN ('active', 'ended', 'expired')",
        name="ck_demo_sessions_status",
    ),
    sa.CheckConstraint(
        "chat_epoch >= 0",
        name="ck_demo_sessions_chat_epoch",
    ),
    sa.CheckConstraint(
        "idle_expires_at <= absolute_expires_at",
        name="ck_demo_sessions_expiry_order",
    ),
)

idempotency_receipts = sa.Table(
    "idempotency_receipts",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("scope_type", sa.Text(), nullable=False),
    sa.Column("scope_id", sa.Text(), nullable=False),
    sa.Column("operation", sa.Text(), nullable=False),
    sa.Column("key_hash", sa.LargeBinary(), nullable=False),
    sa.Column("request_hash", sa.LargeBinary(), nullable=False),
    sa.Column("response_status", sa.Integer(), nullable=True),
    sa.Column("response_body_hash", sa.LargeBinary(), nullable=True),
    sa.Column("response_projection", postgresql.JSONB(), nullable=True),
    sa.Column("outcome", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "outcome IN ('in_progress', 'succeeded', 'failed')",
        name="ck_idempotency_receipts_outcome",
    ),
    sa.CheckConstraint(
        "response_status IS NULL OR response_status BETWEEN 100 AND 599",
        name="ck_idempotency_receipts_response_status",
    ),
    sa.UniqueConstraint(
        "scope_type",
        "scope_id",
        "operation",
        "key_hash",
        name="uq_idempotency_receipts_scope_operation_key",
    ),
)

storage_objects = sa.Table(
    "storage_objects",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "workspace_id",
        sa.Text(),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("object_key", sa.Text(), nullable=False, unique=True),
    sa.Column("purpose", sa.Text(), nullable=False),
    sa.Column("state", sa.Text(), nullable=False),
    sa.Column("media_type", sa.Text(), nullable=False),
    sa.Column("size_bytes", sa.BigInteger(), nullable=False),
    sa.Column("sha256", sa.Text(), nullable=False),
    sa.Column("etag", sa.Text(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint(
        "purpose IN ('temporary_upload', 'normalized_dataset', 'evidence', 'export')",
        name="ck_storage_objects_purpose",
    ),
    sa.CheckConstraint(
        "state IN ('staging', 'available', 'quarantined', 'deleted')",
        name="ck_storage_objects_state",
    ),
    sa.CheckConstraint("size_bytes >= 0", name="ck_storage_objects_size"),
    sa.CheckConstraint(
        "sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_storage_objects_sha256",
    ),
)
sa.Index(
    "ix_storage_objects_workspace_state_expiry",
    storage_objects.c.workspace_id,
    storage_objects.c.state,
    storage_objects.c.expires_at,
)

import_workflows = sa.Table(
    "import_workflows",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "workspace_id",
        sa.Text(),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("source_confirmed_synthetic", sa.Boolean(), nullable=False),
    sa.Column(
        "source_kind",
        sa.Text(),
        nullable=False,
        server_default="legacy_synthetic",
    ),
    sa.Column(
        "base_dataset_version_id",
        postgresql.UUID(as_uuid=True),
        nullable=True,
    ),
    sa.Column("failure_code", sa.Text(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint(
        "status IN ('created', 'uploading', 'recognized', 'ready', 'committing', "
        "'committed', 'rejected', 'failed', 'cancelled')",
        name="ck_import_workflows_status",
    ),
    sa.CheckConstraint("revision >= 0", name="ck_import_workflows_revision"),
    sa.CheckConstraint(
        "source_kind IN ('legacy_synthetic', 'operator_upload')",
        name="ck_import_workflows_source_kind",
    ),
    sa.ForeignKeyConstraint(
        ["workspace_id", "base_dataset_version_id"],
        ["dataset_versions.workspace_id", "dataset_versions.id"],
        name="fk_import_workflows_base_dataset_version",
        ondelete="RESTRICT",
    ),
)
sa.Index(
    "ix_import_workflows_base_dataset_version",
    import_workflows.c.base_dataset_version_id,
)

upload_records = sa.Table(
    "upload_records",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "workflow_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("import_workflows.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "storage_object_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("storage_objects.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("source_filename", sa.Text(), nullable=False),
    sa.Column("media_type", sa.Text(), nullable=False),
    sa.Column("size_bytes", sa.BigInteger(), nullable=False),
    sa.Column("sha256", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("adapter_id", sa.Text(), nullable=True),
    sa.Column("adapter_version", sa.Text(), nullable=True),
    sa.Column("source_role", sa.Text(), nullable=True),
    sa.Column("recognition", postgresql.JSONB(), nullable=True),
    sa.Column("mapping", postgresql.JSONB(), nullable=True),
    sa.Column("mapping_revision", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("assigned_store_id", sa.Text(), nullable=True),
    sa.Column("quality_report", postgresql.JSONB(), nullable=True),
    sa.Column(
        "candidate_storage_object_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("storage_objects.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    sa.Column("standardized_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "status IN ('staged', 'recognized', 'accepted', 'rejected', 'deleted')",
        name="ck_upload_records_status",
    ),
    sa.CheckConstraint(
        "mapping_revision >= 0",
        name="ck_upload_records_mapping_revision",
    ),
    sa.CheckConstraint(
        "assigned_store_id IS NULL OR length(assigned_store_id) BETWEEN 1 AND 100",
        name="ck_upload_records_assigned_store_id",
    ),
    sa.CheckConstraint("size_bytes >= 0", name="ck_upload_records_size"),
    sa.CheckConstraint(
        "sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_upload_records_sha256",
    ),
    sa.UniqueConstraint(
        "workflow_id",
        "sha256",
        name="uq_upload_records_workflow_sha256",
    ),
)

dataset_series = sa.Table(
    "dataset_series",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "workspace_id",
        sa.Text(),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("name", sa.Text(), nullable=False),
    sa.Column(
        "current_version_id",
        postgresql.UUID(as_uuid=True),
        nullable=True,
    ),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["id", "current_version_id"],
        ["dataset_versions.series_id", "dataset_versions.id"],
        name="fk_dataset_series_current_version",
        ondelete="RESTRICT",
    ),
    sa.UniqueConstraint(
        "workspace_id",
        "id",
        name="uq_dataset_series_workspace_id",
    ),
    sa.UniqueConstraint(
        "workspace_id",
        "name",
        name="uq_dataset_series_workspace_name",
    ),
)

dataset_versions = sa.Table(
    "dataset_versions",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "series_id",
        postgresql.UUID(as_uuid=True),
        nullable=False,
    ),
    sa.Column(
        "workspace_id",
        sa.Text(),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "source_workflow_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("import_workflows.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    ),
    sa.Column(
        "base_version_id",
        postgresql.UUID(as_uuid=True),
        nullable=True,
    ),
    sa.Column("version_number", sa.Integer(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("schema_version", sa.Text(), nullable=False),
    sa.Column("content_sha256", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("version_number >= 1", name="ck_dataset_versions_number"),
    sa.CheckConstraint(
        "status IN ('complete', 'invalid')",
        name="ck_dataset_versions_status",
    ),
    sa.CheckConstraint(
        "content_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_dataset_versions_sha256",
    ),
    sa.ForeignKeyConstraint(
        ["workspace_id", "series_id"],
        ["dataset_series.workspace_id", "dataset_series.id"],
        name="fk_dataset_versions_workspace_series",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["series_id", "base_version_id"],
        ["dataset_versions.series_id", "dataset_versions.id"],
        name="fk_dataset_versions_base_version",
        ondelete="RESTRICT",
    ),
    sa.UniqueConstraint(
        "series_id",
        "id",
        name="uq_dataset_versions_series_id",
    ),
    sa.UniqueConstraint(
        "workspace_id",
        "id",
        name="uq_dataset_versions_workspace_id",
    ),
    sa.UniqueConstraint(
        "series_id",
        "version_number",
        name="uq_dataset_versions_series_number",
    ),
    sa.UniqueConstraint(
        "workspace_id",
        "content_sha256",
        name="uq_dataset_versions_workspace_content",
    ),
)
sa.Index(
    "ix_dataset_versions_base_version",
    dataset_versions.c.base_version_id,
)

dataset_artifacts = sa.Table(
    "dataset_artifacts",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "dataset_version_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "storage_object_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("storage_objects.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("artifact_kind", sa.Text(), nullable=False),
    sa.Column("sha256", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_dataset_artifacts_sha256",
    ),
    sa.UniqueConstraint(
        "dataset_version_id",
        "artifact_kind",
        name="uq_dataset_artifacts_version_kind",
    ),
)

dataset_exports = sa.Table(
    "dataset_exports",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("workspace_id", sa.Text(), nullable=False),
    sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("format", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column(
        "storage_object_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("storage_objects.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("sha256", sa.Text(), nullable=False),
    sa.Column("byte_count", sa.BigInteger(), nullable=False),
    sa.Column("idempotency_key_hash", sa.LargeBinary(), nullable=False),
    sa.Column("request_hash", sa.LargeBinary(), nullable=False),
    sa.Column("failure_code", sa.Text(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["workspace_id", "dataset_version_id"],
        ["dataset_versions.workspace_id", "dataset_versions.id"],
        name="fk_dataset_exports_workspace_version",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint("format = 'xlsx'", name="ck_dataset_exports_format"),
    sa.CheckConstraint("status = 'available'", name="ck_dataset_exports_status"),
    sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_dataset_exports_sha256"),
    sa.CheckConstraint("byte_count > 0", name="ck_dataset_exports_byte_count"),
    sa.UniqueConstraint(
        "workspace_id",
        "dataset_version_id",
        "idempotency_key_hash",
        name="uq_dataset_exports_idempotency",
    ),
)

public_releases = sa.Table(
    "public_releases",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "workspace_id",
        sa.Text(),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "dataset_version_id",
        postgresql.UUID(as_uuid=True),
        nullable=False,
    ),
    sa.Column("is_active", sa.Boolean(), nullable=False),
    sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint(
        "(is_active AND retired_at IS NULL) OR "
        "(NOT is_active AND retired_at IS NOT NULL)",
        name="ck_public_releases_active_retired",
    ),
    sa.ForeignKeyConstraint(
        ["workspace_id", "dataset_version_id"],
        ["dataset_versions.workspace_id", "dataset_versions.id"],
        name="fk_public_releases_workspace_version",
        ondelete="RESTRICT",
    ),
)
sa.Index(
    "uq_public_releases_one_active_per_workspace",
    public_releases.c.workspace_id,
    unique=True,
    postgresql_where=public_releases.c.is_active,
)

analysis_runs = sa.Table(
    "analysis_runs",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("workspace_id", sa.Text(), nullable=False),
    sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("analysis_kind", sa.Text(), nullable=False),
    sa.Column("algorithm_version", sa.Text(), nullable=False),
    sa.Column("input_hash", sa.Text(), nullable=False),
    sa.Column("scope", postgresql.JSONB(), nullable=False),
    sa.Column("scope_hash", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("failure_code", sa.Text(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(
        ["workspace_id", "dataset_version_id"],
        ["dataset_versions.workspace_id", "dataset_versions.id"],
        name="fk_analysis_runs_workspace_version",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint(
        "analysis_kind IN ('sales_ads', 'inventory_risk', 'fifo_cost_aging', "
        "'operating_profit', 'replenishment')",
        name="ck_analysis_runs_kind",
    ),
    sa.CheckConstraint(
        "status IN ('running', 'completed', 'failed')",
        name="ck_analysis_runs_status",
    ),
    sa.CheckConstraint(
        "input_hash ~ '^[0-9a-f]{64}$' AND scope_hash ~ '^[0-9a-f]{64}$'",
        name="ck_analysis_runs_hashes",
    ),
    sa.CheckConstraint(
        "(status = 'completed' AND completed_at IS NOT NULL AND failure_code IS NULL "
        "AND lease_expires_at IS NULL) OR (status = 'running' AND completed_at IS NULL "
        "AND failure_code IS NULL AND lease_expires_at IS NOT NULL) OR (status = 'failed' "
        "AND completed_at IS NOT NULL AND failure_code IS NOT NULL AND lease_expires_at IS NULL)",
        name="ck_analysis_runs_outcome",
    ),
    sa.UniqueConstraint(
        "workspace_id",
        "dataset_version_id",
        "analysis_kind",
        "algorithm_version",
        "input_hash",
        "scope_hash",
        name="uq_analysis_runs_exact_input",
    ),
)

analysis_dependencies = sa.Table(
    "analysis_dependencies",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "run_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "dataset_artifact_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("dataset_artifacts.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("artifact_sha256", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "artifact_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_analysis_dependencies_sha256",
    ),
    sa.UniqueConstraint(
        "run_id",
        "dataset_artifact_id",
        name="uq_analysis_dependencies_run_artifact",
    ),
)

analysis_artifacts = sa.Table(
    "analysis_artifacts",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "run_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    sa.Column(
        "storage_object_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("storage_objects.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    sa.Column("snapshot_sha256", sa.Text(), nullable=False),
    sa.Column("media_type", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "snapshot_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_analysis_artifacts_sha256",
    ),
)

evidence_items = sa.Table(
    "evidence_items",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "run_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("alias", sa.Text(), nullable=False),
    sa.Column("evidence_state", sa.Text(), nullable=False),
    sa.Column("formula", sa.Text(), nullable=False),
    sa.Column("source_refs", postgresql.JSONB(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "evidence_state IN ('measured', 'derived', 'assumed', 'unknown')",
        name="ck_evidence_items_state",
    ),
    sa.UniqueConstraint("run_id", "alias", name="uq_evidence_items_run_alias"),
)

new_product_forecasts = sa.Table(
    "new_product_forecasts",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("workspace_id", sa.Text(), nullable=False),
    sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("algorithm_version", sa.Text(), nullable=False),
    sa.Column("input_snapshot", postgresql.JSONB(), nullable=False),
    sa.Column("input_hash", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("confidence", sa.Text(), nullable=True),
    sa.Column("assumptions", postgresql.JSONB(), nullable=False),
    sa.Column("evidence", postgresql.JSONB(), nullable=False),
    sa.Column("result", postgresql.JSONB(), nullable=True),
    sa.Column("backtest", postgresql.JSONB(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(
        ["workspace_id", "dataset_version_id"],
        ["dataset_versions.workspace_id", "dataset_versions.id"],
        name="fk_new_product_forecasts_workspace_version",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint(
        "status IN ('draft', 'analogs_confirmed', 'completed', 'blocked')",
        name="ck_new_product_forecasts_status",
    ),
    sa.CheckConstraint(
        "confidence IS NULL OR confidence IN ('low', 'medium', 'high')",
        name="ck_new_product_forecasts_confidence",
    ),
    sa.CheckConstraint(
        "input_hash ~ '^[0-9a-f]{64}$'",
        name="ck_new_product_forecasts_hash",
    ),
    sa.CheckConstraint(
        "(status IN ('draft', 'analogs_confirmed') AND completed_at IS NULL) OR "
        "(status IN ('completed', 'blocked') AND completed_at IS NOT NULL)",
        name="ck_new_product_forecasts_completion",
    ),
    sa.UniqueConstraint(
        "workspace_id",
        "dataset_version_id",
        "id",
        name="uq_new_product_forecasts_session_pin",
    ),
)
sa.Index(
    "ix_new_product_forecasts_workspace_version_created",
    new_product_forecasts.c.workspace_id,
    new_product_forecasts.c.dataset_version_id,
    new_product_forecasts.c.created_at,
)

forecast_analogs = sa.Table(
    "forecast_analogs",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "forecast_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("new_product_forecasts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("sku_id", sa.Text(), nullable=False),
    sa.Column("rank", sa.Integer(), nullable=False),
    sa.Column("score", sa.Numeric(8, 6), nullable=False),
    sa.Column("components", postgresql.JSONB(), nullable=False),
    sa.Column("historical_snapshot", postgresql.JSONB(), nullable=False),
    sa.Column("confirmed", sa.Boolean(), nullable=False),
    sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("rank BETWEEN 1 AND 5", name="ck_forecast_analogs_rank"),
    sa.CheckConstraint("score BETWEEN 0 AND 1", name="ck_forecast_analogs_score"),
    sa.CheckConstraint(
        "(confirmed AND confirmed_at IS NOT NULL) OR "
        "(NOT confirmed AND confirmed_at IS NULL)",
        name="ck_forecast_analogs_confirmation",
    ),
    sa.UniqueConstraint("forecast_id", "sku_id", name="uq_forecast_analogs_sku"),
    sa.UniqueConstraint("forecast_id", "rank", name="uq_forecast_analogs_rank"),
)

forecast_scenarios = sa.Table(
    "forecast_scenarios",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "forecast_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("new_product_forecasts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("horizon_days", sa.Integer(), nullable=False),
    sa.Column("scenario", sa.Text(), nullable=False),
    sa.Column("units", sa.Integer(), nullable=False),
    sa.Column("revenue_brl", sa.Numeric(18, 2), nullable=False),
    sa.Column("contribution_profit_brl", sa.Numeric(18, 2), nullable=True),
    sa.Column("stock_cover_days", sa.Numeric(18, 2), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "horizon_days IN (7, 30, 90)",
        name="ck_forecast_scenarios_horizon",
    ),
    sa.CheckConstraint(
        "scenario IN ('low', 'base', 'high')",
        name="ck_forecast_scenarios_name",
    ),
    sa.CheckConstraint(
        "units >= 0 AND revenue_brl >= 0",
        name="ck_forecast_scenarios_values",
    ),
    sa.UniqueConstraint(
        "forecast_id",
        "horizon_days",
        "scenario",
        name="uq_forecast_scenarios_exact",
    ),
)

profit_bridges = sa.Table(
    "profit_bridges",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("workspace_id", sa.Text(), nullable=False),
    sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("baseline_analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("current_analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("formula_version", sa.Text(), nullable=False),
    sa.Column("scope", postgresql.JSONB(), nullable=False),
    sa.Column("total_delta_brl", sa.Numeric(18, 2), nullable=True),
    sa.Column("residual_brl", sa.Numeric(18, 2), nullable=True),
    sa.Column("reconciled", sa.Boolean(), nullable=False),
    sa.Column("evidence", postgresql.JSONB(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["workspace_id", "dataset_version_id"],
        ["dataset_versions.workspace_id", "dataset_versions.id"],
        name="fk_profit_bridges_workspace_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["baseline_analysis_id"],
        ["analysis_runs.id"],
        name="fk_profit_bridges_baseline_analysis",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["current_analysis_id"],
        ["analysis_runs.id"],
        name="fk_profit_bridges_current_analysis",
        ondelete="RESTRICT",
    ),
    sa.UniqueConstraint(
        "workspace_id",
        "baseline_analysis_id",
        "current_analysis_id",
        "formula_version",
        name="uq_profit_bridges_exact",
    ),
    sa.UniqueConstraint(
        "workspace_id",
        "dataset_version_id",
        "id",
        name="uq_profit_bridges_session_pin",
    ),
)

profit_bridge_items = sa.Table(
    "profit_bridge_items",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "bridge_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("profit_bridges.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("driver", sa.Text(), nullable=False),
    sa.Column("ordinal", sa.Integer(), nullable=False),
    sa.Column("amount_brl", sa.Numeric(18, 2), nullable=True),
    sa.Column("evidence_state", sa.Text(), nullable=False),
    sa.Column("formula", sa.Text(), nullable=False),
    sa.Column("source_refs", postgresql.JSONB(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "ordinal BETWEEN 1 AND 12",
        name="ck_profit_bridge_items_ordinal",
    ),
    sa.CheckConstraint(
        "evidence_state IN ('measured', 'derived', 'assumed', 'unknown')",
        name="ck_profit_bridge_items_evidence_state",
    ),
    sa.UniqueConstraint("bridge_id", "driver", name="uq_profit_bridge_items_driver"),
    sa.UniqueConstraint("bridge_id", "ordinal", name="uq_profit_bridge_items_ordinal"),
)

action_cards = sa.Table(
    "action_cards",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("workspace_id", sa.Text(), nullable=False),
    sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("source_type", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("current_revision", sa.Integer(), nullable=False),
    sa.Column("idempotency_key_hash", sa.LargeBinary(), nullable=False),
    sa.Column("request_hash", sa.LargeBinary(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(
        ["workspace_id", "dataset_version_id"],
        ["dataset_versions.workspace_id", "dataset_versions.id"],
        name="fk_action_cards_workspace_version",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint(
        "source_type IN ('deterministic_rule', 'new_product_forecast', "
        "'profit_bridge', 'operating_advice', 'chat_box_draft')",
        name="ck_action_cards_source_type",
    ),
    sa.CheckConstraint(
        "status IN ('new', 'reviewed', 'approved', 'dismissed')",
        name="ck_action_cards_status",
    ),
    sa.CheckConstraint("current_revision >= 1", name="ck_action_cards_revision"),
    sa.CheckConstraint(
        "(status IN ('new', 'reviewed') AND terminal_at IS NULL) OR "
        "(status IN ('approved', 'dismissed') AND terminal_at IS NOT NULL)",
        name="ck_action_cards_terminal",
    ),
    sa.UniqueConstraint(
        "workspace_id",
        "idempotency_key_hash",
        name="uq_action_cards_create_idempotency",
    ),
)
sa.Index(
    "ix_action_cards_workspace_version_created",
    action_cards.c.workspace_id,
    action_cards.c.dataset_version_id,
    action_cards.c.created_at,
)

action_card_revisions = sa.Table(
    "action_card_revisions",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "action_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("action_cards.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.Column("suggestion", sa.Text(), nullable=False),
    sa.Column("target", sa.Text(), nullable=False),
    sa.Column("period_start", sa.Date(), nullable=False),
    sa.Column("period_end", sa.Date(), nullable=False),
    sa.Column("scope", postgresql.JSONB(), nullable=False),
    sa.Column("quantity", sa.Numeric(18, 4), nullable=True),
    sa.Column("budget_brl", sa.Numeric(18, 2), nullable=True),
    sa.Column("action_date", sa.Date(), nullable=True),
    sa.Column("threshold", sa.Numeric(18, 4), nullable=True),
    sa.Column("expected_impact", postgresql.JSONB(), nullable=False),
    sa.Column("confidence", sa.Text(), nullable=False),
    sa.Column("limitations", postgresql.JSONB(), nullable=False),
    sa.Column("facts", postgresql.JSONB(), nullable=False),
    sa.Column("analysis_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("forecast_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("bridge_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("chat_turn_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("chat_tool", sa.Text(), nullable=True),
    sa.Column("answer_version", sa.Text(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["analysis_run_id"],
        ["analysis_runs.id"],
        name="fk_action_card_revisions_analysis",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["forecast_id"],
        ["new_product_forecasts.id"],
        name="fk_action_card_revisions_forecast",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["bridge_id"],
        ["profit_bridges.id"],
        name="fk_action_card_revisions_bridge",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["chat_turn_id"],
        ["ai_chat_turns.id"],
        name="fk_action_card_revisions_chat_turn",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint("revision >= 1", name="ck_action_card_revisions_revision"),
    sa.CheckConstraint(
        "period_start <= period_end",
        name="ck_action_card_revisions_period",
    ),
    sa.CheckConstraint(
        "confidence IN ('low', 'medium', 'high')",
        name="ck_action_card_revisions_confidence",
    ),
    sa.CheckConstraint(
        "quantity IS NULL OR quantity >= 0",
        name="ck_action_card_revisions_quantity",
    ),
    sa.CheckConstraint(
        "budget_brl IS NULL OR budget_brl >= 0",
        name="ck_action_card_revisions_budget",
    ),
    sa.UniqueConstraint("action_id", "revision", name="uq_action_card_revisions_exact"),
)

action_decisions = sa.Table(
    "action_decisions",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "action_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("action_cards.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("action_revision", sa.Integer(), nullable=False),
    sa.Column("decision_ordinal", sa.Integer(), nullable=False),
    sa.Column("command", sa.Text(), nullable=False),
    sa.Column("reason", sa.Text(), nullable=False),
    sa.Column("decided_by", sa.Text(), nullable=False),
    sa.Column("idempotency_key_hash", sa.LargeBinary(), nullable=False),
    sa.Column("request_hash", sa.LargeBinary(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["action_id", "action_revision"],
        ["action_card_revisions.action_id", "action_card_revisions.revision"],
        name="fk_action_decisions_revision",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint(
        "command IN ('review', 'adjust', 'approve', 'dismiss')",
        name="ck_action_decisions_command",
    ),
    sa.CheckConstraint(
        "decision_ordinal >= 1",
        name="ck_action_decisions_ordinal",
    ),
    sa.UniqueConstraint(
        "action_id",
        "decision_ordinal",
        name="uq_action_decisions_ordinal",
    ),
    sa.UniqueConstraint(
        "action_id", "idempotency_key_hash", name="uq_action_decisions_idempotency"
    ),
    sa.CheckConstraint(
        "decided_by = 'single_operator'", name="ck_action_decisions_actor"
    ),
)

action_exports = sa.Table(
    "action_exports",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "action_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("action_cards.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("action_revision", sa.Integer(), nullable=False),
    sa.Column("format", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column(
        "storage_object_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("storage_objects.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("sha256", sa.Text(), nullable=False),
    sa.Column("note", sa.Text(), nullable=False),
    sa.Column("exported_by", sa.Text(), nullable=False),
    sa.Column("idempotency_key_hash", sa.LargeBinary(), nullable=False),
    sa.Column("request_hash", sa.LargeBinary(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["action_id", "action_revision"],
        ["action_card_revisions.action_id", "action_card_revisions.revision"],
        name="fk_action_exports_revision",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint("format = 'xlsx'", name="ck_action_exports_format"),
    sa.CheckConstraint("status = 'available'", name="ck_action_exports_status"),
    sa.CheckConstraint(
        "note = 'Not sent to an external platform'",
        name="ck_action_exports_note",
    ),
    sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_action_exports_sha256"),
    sa.CheckConstraint(
        "exported_by = 'single_operator'", name="ck_action_exports_actor"
    ),
    sa.UniqueConstraint(
        "action_id", "idempotency_key_hash", name="uq_action_exports_idempotency"
    ),
)

action_outcomes = sa.Table(
    "action_outcomes",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "action_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("action_cards.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("action_revision", sa.Integer(), nullable=False),
    sa.Column("outcome_revision", sa.Integer(), nullable=False),
    sa.Column("review_date", sa.Date(), nullable=False),
    sa.Column("synthetic_result", postgresql.JSONB(), nullable=False),
    sa.Column("evidence", postgresql.JSONB(), nullable=False),
    sa.Column("conclusion", sa.Text(), nullable=False),
    sa.Column("reason", sa.Text(), nullable=False),
    sa.Column("reviewed_by", sa.Text(), nullable=False),
    sa.Column("idempotency_key_hash", sa.LargeBinary(), nullable=False),
    sa.Column("request_hash", sa.LargeBinary(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["action_id", "action_revision"],
        ["action_card_revisions.action_id", "action_card_revisions.revision"],
        name="fk_action_outcomes_revision",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint(
        "conclusion IN ('achieved', 'partially_achieved', 'not_achieved', 'inconclusive')",
        name="ck_action_outcomes_conclusion",
    ),
    sa.CheckConstraint(
        "reviewed_by = 'single_operator'", name="ck_action_outcomes_actor"
    ),
    sa.UniqueConstraint(
        "action_id", "outcome_revision", name="uq_action_outcomes_revision"
    ),
    sa.UniqueConstraint(
        "action_id", "idempotency_key_hash", name="uq_action_outcomes_idempotency"
    ),
)

demo_action_overlays = sa.Table(
    "demo_action_overlays",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "demo_session_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("demo_sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "action_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("action_cards.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("base_revision", sa.Integer(), nullable=False),
    sa.Column("overlay_revision", sa.Integer(), nullable=False),
    sa.Column("command", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("adjustment", postgresql.JSONB(), nullable=False),
    sa.Column("reason", sa.Text(), nullable=False),
    sa.Column("idempotency_key_hash", sa.LargeBinary(), nullable=False),
    sa.Column("request_hash", sa.LargeBinary(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["action_id", "base_revision"],
        ["action_card_revisions.action_id", "action_card_revisions.revision"],
        name="fk_demo_action_overlays_revision",
        ondelete="CASCADE",
    ),
    sa.CheckConstraint(
        "command IN ('review', 'adjust', 'approve', 'dismiss')",
        name="ck_demo_action_overlays_command",
    ),
    sa.CheckConstraint(
        "status IN ('reviewed', 'approved', 'dismissed')",
        name="ck_demo_action_overlays_status",
    ),
    sa.CheckConstraint("base_revision >= 1", name="ck_demo_action_overlays_base_revision"),
    sa.CheckConstraint(
        "overlay_revision >= 1", name="ck_demo_action_overlays_revision"
    ),
    sa.UniqueConstraint(
        "demo_session_id",
        "action_id",
        "overlay_revision",
        name="uq_demo_action_overlays_revision",
    ),
    sa.UniqueConstraint(
        "demo_session_id",
        "idempotency_key_hash",
        name="uq_demo_action_overlays_idempotency",
    ),
)

ai_chat_turns = sa.Table(
    "ai_chat_turns",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "turn_sequence",
        sa.BigInteger(),
        nullable=False,
    ),
    sa.Column("workspace_id", sa.Text(), nullable=False),
    sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("actor_kind", sa.Text(), nullable=False),
    sa.Column("operator_session_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("demo_session_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("question", sa.Text(), nullable=True),
    sa.Column("recommended_question_id", sa.Text(), nullable=True),
    sa.Column("prompt_locale", sa.Text(), nullable=True),
    sa.Column("prompt_template_version", sa.Text(), nullable=True),
    sa.Column("prompt_template_sha256", sa.Text(), nullable=True),
    sa.Column(
        "prompt_audit_state",
        sa.Text(),
        nullable=False,
        server_default="legacy_unrecorded",
    ),
    sa.Column("question_digest", sa.Text(), nullable=False),
    sa.Column("credential_binding_id", sa.Text(), nullable=True),
    sa.Column("credential_control_revision", sa.BigInteger(), nullable=True),
    sa.Column("credential_request_id", sa.Text(), nullable=True),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("scope", postgresql.JSONB(), nullable=False),
    sa.Column("plan_schema_version", sa.Text(), nullable=False),
    sa.Column("output_schema_version", sa.Text(), nullable=False),
    sa.Column("idempotency_key_hash", sa.LargeBinary(), nullable=False),
    sa.Column("request_hash", sa.LargeBinary(), nullable=False),
    sa.Column("tool_name", sa.Text(), nullable=True),
    sa.Column("result_hash", sa.Text(), nullable=True),
    sa.Column(
        "answer_projection",
        postgresql.JSONB(none_as_null=True),
        nullable=True,
    ),
    sa.Column("safe_summary", sa.Text(), nullable=True),
    sa.Column("error_code", sa.Text(), nullable=True),
    sa.Column("action_draft_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column(
        "action_draft_projection",
        postgresql.JSONB(none_as_null=True),
        nullable=True,
    ),
    sa.Column("action_draft_key_hash", sa.LargeBinary(), nullable=True),
    sa.Column("action_draft_request_hash", sa.LargeBinary(), nullable=True),
    sa.Column("action_draft_created_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(
        ["workspace_id", "dataset_version_id"],
        ["dataset_versions.workspace_id", "dataset_versions.id"],
        name="fk_ai_chat_turns_workspace_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["operator_session_id"],
        ["operator_sessions.id"],
        name="fk_ai_chat_turns_operator_session",
        ondelete="CASCADE",
    ),
    sa.ForeignKeyConstraint(
        ["demo_session_id"],
        ["demo_sessions.id"],
        name="fk_ai_chat_turns_demo_session",
        ondelete="CASCADE",
    ),
    sa.CheckConstraint(
        "actor_kind IN ('operator', 'demo')",
        name="ck_ai_chat_turns_actor_kind",
    ),
    sa.CheckConstraint(
        "(actor_kind = 'operator' AND operator_session_id IS NOT NULL "
        "AND demo_session_id IS NULL) OR "
        "(actor_kind = 'demo' AND demo_session_id IS NOT NULL "
        "AND operator_session_id IS NULL)",
        name="ck_ai_chat_turns_actor_session",
    ),
    sa.CheckConstraint(
        "(prompt_audit_state = 'recorded' AND question IS NOT NULL AND "
        "((recommended_question_id IS NULL AND prompt_locale IS NULL AND "
        "prompt_template_version IS NULL AND prompt_template_sha256 IS NULL) OR "
        "(recommended_question_id IS NOT NULL AND prompt_locale IS NOT NULL AND "
        "prompt_template_version IS NOT NULL AND prompt_template_sha256 IS NOT NULL))) "
        "OR (prompt_audit_state = 'legacy_unrecorded' AND "
        "prompt_locale IS NULL AND prompt_template_version IS NULL AND "
        "prompt_template_sha256 IS NULL AND "
        "((question IS NOT NULL AND recommended_question_id IS NULL) OR "
        "(question IS NULL AND recommended_question_id IS NOT NULL)))",
        name="ck_ai_chat_turns_question_choice",
    ),
    sa.CheckConstraint(
        "(question IS NULL OR length(question) BETWEEN 1 AND 2000) AND "
        "(recommended_question_id IS NULL OR "
        "length(recommended_question_id) BETWEEN 1 AND 100)",
        name="ck_ai_chat_turns_question_bounds",
    ),
    sa.CheckConstraint(
        "prompt_audit_state IN ('recorded','legacy_unrecorded') AND "
        "(prompt_locale IS NULL OR prompt_locale IN ('en','zh')) AND "
        "(prompt_template_version IS NULL OR "
        "length(prompt_template_version) BETWEEN 1 AND 100) AND "
        "(prompt_template_sha256 IS NULL OR "
        "prompt_template_sha256 ~ '^[0-9a-f]{64}$')",
        name="ck_ai_chat_turns_prompt_audit",
    ),
    sa.CheckConstraint(
        "question_digest ~ '^[0-9a-f]{64}$'",
        name="ck_ai_chat_turns_question_digest",
    ),
    sa.CheckConstraint(
        "(credential_binding_id IS NULL AND credential_control_revision IS NULL "
        "AND credential_request_id IS NULL) OR "
        "(credential_binding_id ~ '^[0-9a-f]{64}$' "
        "AND credential_control_revision >= 0 "
        "AND length(credential_request_id) BETWEEN 3 AND 128)",
        name="ck_ai_chat_turns_credential_binding",
    ),
    sa.CheckConstraint(
        "status IN ('planning','querying','answering','answered',"
        "'clarification_required','unsupported','failed','outcome_unknown')",
        name="ck_ai_chat_turns_status",
    ),
    sa.CheckConstraint(
        "tool_name IS NULL OR tool_name IN ("
        "'metric_lookup','trend_compare','sku_rank','profit_bridge_explain',"
        "'inventory_risk_lookup','forecast_lookup','data_quality_lookup',"
        "'action_card_lookup','monthly_sales_report_lookup')",
        name="ck_ai_chat_turns_tool",
    ),
    sa.CheckConstraint(
        "result_hash IS NULL OR result_hash ~ '^[0-9a-f]{64}$'",
        name="ck_ai_chat_turns_result_hash",
    ),
    sa.CheckConstraint(
        "plan_schema_version = 'query-plan.v1' AND "
        "output_schema_version = 'chat-answer.v1' AND "
        "octet_length(idempotency_key_hash) = 32 AND "
        "octet_length(request_hash) = 32 AND "
        "jsonb_typeof(scope) = 'object' AND pg_column_size(scope) <= 8192 AND "
        "(answer_projection IS NULL OR "
        "(jsonb_typeof(answer_projection) = 'object' AND "
        "pg_column_size(answer_projection) <= 65536)) AND "
        "(action_draft_projection IS NULL OR "
        "(jsonb_typeof(action_draft_projection) = 'object' AND "
        "pg_column_size(action_draft_projection) <= 32768)) AND "
        "(safe_summary IS NULL OR length(safe_summary) <= 1000) AND "
        "(error_code IS NULL OR length(error_code) <= 100)",
        name="ck_ai_chat_turns_bounded_authority",
    ),
    sa.CheckConstraint(
        "(status IN ('planning','querying','answering') AND completed_at IS NULL "
        "AND lease_expires_at IS NOT NULL AND lease_expires_at > updated_at) OR "
        "(status IN ('answered','clarification_required','unsupported','failed',"
        "'outcome_unknown') AND completed_at IS NOT NULL "
        "AND lease_expires_at IS NULL)",
        name="ck_ai_chat_turns_completion",
    ),
    sa.CheckConstraint(
        "(action_draft_id IS NULL AND action_draft_projection IS NULL "
        "AND action_draft_key_hash IS NULL AND action_draft_request_hash IS NULL "
        "AND action_draft_created_at IS NULL) OR "
        "(status = 'answered' AND action_draft_id IS NOT NULL "
        "AND action_draft_projection IS NOT NULL "
        "AND action_draft_key_hash IS NOT NULL "
        "AND action_draft_request_hash IS NOT NULL "
        "AND action_draft_created_at IS NOT NULL)",
        name="ck_ai_chat_turns_action_draft",
    ),
)
sa.Index(
    "uq_ai_chat_turns_credential_request",
    ai_chat_turns.c.workspace_id,
    ai_chat_turns.c.credential_request_id,
    unique=True,
    postgresql_where=ai_chat_turns.c.credential_request_id.is_not(None),
)
sa.Index(
    "uq_ai_chat_turns_operator_sequence",
    ai_chat_turns.c.operator_session_id,
    ai_chat_turns.c.turn_sequence,
    unique=True,
    postgresql_where=ai_chat_turns.c.actor_kind == "operator",
)
sa.Index(
    "uq_ai_chat_turns_demo_sequence",
    ai_chat_turns.c.demo_session_id,
    ai_chat_turns.c.turn_sequence,
    unique=True,
    postgresql_where=ai_chat_turns.c.actor_kind == "demo",
)
sa.Index(
    "uq_ai_chat_turns_operator_idempotency",
    ai_chat_turns.c.operator_session_id,
    ai_chat_turns.c.idempotency_key_hash,
    unique=True,
    postgresql_where=ai_chat_turns.c.actor_kind == "operator",
)
sa.Index(
    "uq_ai_chat_turns_demo_idempotency",
    ai_chat_turns.c.demo_session_id,
    ai_chat_turns.c.idempotency_key_hash,
    unique=True,
    postgresql_where=ai_chat_turns.c.actor_kind == "demo",
)
sa.Index(
    "uq_ai_chat_turns_operator_inflight",
    ai_chat_turns.c.operator_session_id,
    unique=True,
    postgresql_where=ai_chat_turns.c.status.in_(("planning", "querying", "answering")),
)
sa.Index(
    "uq_ai_chat_turns_demo_inflight",
    ai_chat_turns.c.demo_session_id,
    unique=True,
    postgresql_where=ai_chat_turns.c.status.in_(("planning", "querying", "answering")),
)
sa.Index(
    "ix_ai_chat_turns_session_created",
    ai_chat_turns.c.actor_kind,
    ai_chat_turns.c.operator_session_id,
    ai_chat_turns.c.demo_session_id,
    ai_chat_turns.c.created_at,
)

ai_chat_tool_runs = sa.Table(
    "ai_chat_tool_runs",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "turn_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("ai_chat_turns.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    sa.Column("tool_name", sa.Text(), nullable=False),
    sa.Column("arguments", postgresql.JSONB(), nullable=False),
    sa.Column(
        "result_summary",
        postgresql.JSONB(none_as_null=True),
        nullable=True,
    ),
    sa.Column("result_hash", sa.Text(), nullable=True),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("error_code", sa.Text(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint(
        "tool_name IN ('metric_lookup','trend_compare','sku_rank',"
        "'profit_bridge_explain','inventory_risk_lookup','forecast_lookup',"
        "'data_quality_lookup','action_card_lookup','monthly_sales_report_lookup')",
        name="ck_ai_chat_tool_runs_tool",
    ),
    sa.CheckConstraint(
        "status IN ('running','succeeded','failed','timeout')",
        name="ck_ai_chat_tool_runs_status",
    ),
    sa.CheckConstraint(
        "result_hash IS NULL OR result_hash ~ '^[0-9a-f]{64}$'",
        name="ck_ai_chat_tool_runs_hash",
    ),
    sa.CheckConstraint(
        "jsonb_typeof(arguments) = 'object' AND "
        "pg_column_size(arguments) <= 8192 AND "
        "(result_summary IS NULL OR "
        "(jsonb_typeof(result_summary) = 'object' AND "
        "pg_column_size(result_summary) <= 65536)) AND "
        "(error_code IS NULL OR length(error_code) <= 100) AND "
        "((status = 'succeeded' AND result_summary IS NOT NULL "
        "AND result_hash IS NOT NULL AND completed_at IS NOT NULL) OR "
        "(status IN ('failed','timeout') AND result_summary IS NULL "
        "AND result_hash IS NULL AND completed_at IS NOT NULL) OR "
        "(status = 'running' AND result_summary IS NULL "
        "AND result_hash IS NULL AND completed_at IS NULL))",
        name="ck_ai_chat_tool_runs_bounded_result",
    ),
)

ai_chat_evidence = sa.Table(
    "ai_chat_evidence",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "turn_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("ai_chat_turns.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("fact_ref", sa.Text(), nullable=False),
    sa.Column(
        "analysis_run_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("analysis_runs.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    sa.Column("evidence_alias", sa.Text(), nullable=False),
    sa.Column("evidence_state", sa.Text(), nullable=False),
    sa.Column("source_ref", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "fact_ref ~ '^fact-[0-9]{3}$'",
        name="ck_ai_chat_evidence_fact_ref",
    ),
    sa.CheckConstraint(
        "evidence_state IN ('measured','derived','assumed','unknown')",
        name="ck_ai_chat_evidence_state",
    ),
    sa.CheckConstraint(
        "length(evidence_alias) BETWEEN 1 AND 500 AND "
        "length(source_ref) BETWEEN 1 AND 1000",
        name="ck_ai_chat_evidence_bounds",
    ),
    sa.UniqueConstraint("turn_id", "fact_ref", name="uq_ai_chat_evidence_fact"),
)

ai_chat_attempts = sa.Table(
    "ai_chat_attempts",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "turn_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("ai_chat_turns.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("stage", sa.Text(), nullable=False),
    sa.Column("model", sa.Text(), nullable=False),
    sa.Column("reasoning_effort", sa.Text(), nullable=False),
    sa.Column("input_tokens", sa.Integer(), nullable=False),
    sa.Column("output_tokens", sa.Integer(), nullable=False),
    sa.Column("reserved_tokens", sa.Integer(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("error_code", sa.Text(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("stage IN ('planning','answering')", name="ck_ai_chat_attempts_stage"),
    sa.CheckConstraint("model = 'gpt-5.4-nano-2026-03-17'", name="ck_ai_chat_attempts_model"),
    sa.CheckConstraint("reasoning_effort = 'low'", name="ck_ai_chat_attempts_effort"),
    sa.CheckConstraint(
        "input_tokens >= 0 AND output_tokens >= 0 AND reserved_tokens > 0 "
        "AND input_tokens + output_tokens <= reserved_tokens",
        name="ck_ai_chat_attempts_tokens",
    ),
    sa.CheckConstraint(
        "status IN ('started','succeeded','failed','outcome_unknown')",
        name="ck_ai_chat_attempts_status",
    ),
    sa.CheckConstraint(
        "(error_code IS NULL OR length(error_code) <= 100) AND "
        "((status = 'started' AND completed_at IS NULL) OR "
        "(status IN ('succeeded','failed','outcome_unknown') "
        "AND completed_at IS NOT NULL))",
        name="ck_ai_chat_attempts_completion",
    ),
    sa.UniqueConstraint("turn_id", "stage", name="uq_ai_chat_attempts_stage"),
)

ai_budget_ledger = sa.Table(
    "ai_budget_ledger",
    metadata,
    sa.Column("attempt_id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "workspace_id",
        sa.Text(),
        sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("stage", sa.Text(), nullable=False),
    sa.Column("input_tokens", sa.Integer(), nullable=False),
    sa.Column("output_tokens", sa.Integer(), nullable=False),
    sa.Column("reserved_tokens", sa.Integer(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("error_code", sa.Text(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint(
        "stage IN ('planning','answering')",
        name="ck_ai_budget_ledger_stage",
    ),
    sa.CheckConstraint(
        "input_tokens >= 0 AND output_tokens >= 0 AND reserved_tokens > 0 "
        "AND input_tokens + output_tokens <= reserved_tokens",
        name="ck_ai_budget_ledger_tokens",
    ),
    sa.CheckConstraint(
        "status IN ('started','succeeded','failed','outcome_unknown')",
        name="ck_ai_budget_ledger_status",
    ),
    sa.CheckConstraint(
        "(error_code IS NULL OR length(error_code) <= 100) AND "
        "((status = 'started' AND completed_at IS NULL) OR "
        "(status IN ('succeeded','failed','outcome_unknown') "
        "AND completed_at IS NOT NULL))",
        name="ck_ai_budget_ledger_completion",
    ),
)
sa.Index("ix_ai_budget_ledger_created", ai_budget_ledger.c.created_at)

ai_chat_saved_records = sa.Table(
    "ai_chat_saved_records",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "turn_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("ai_chat_turns.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    sa.Column(
        "operator_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("operator_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("answer_hash", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "answer_hash ~ '^[0-9a-f]{64}$'",
        name="ck_ai_chat_saved_records_hash",
    ),
)

workspace_preferences = sa.Table(
    "workspace_preferences",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("workspace_id", sa.Text(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    sa.Column("operator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("operator_accounts.id", ondelete="CASCADE"), nullable=False),
    sa.Column("locale", sa.Text(), nullable=False),
    sa.Column("sidebar_mode", sa.Text(), nullable=False),
    sa.Column("default_store", sa.Text(), nullable=False),
    sa.Column("period_preset", sa.Text(), nullable=False),
    sa.Column("comparison_preset", sa.Text(), nullable=False),
    sa.Column("overview_kpis", postgresql.JSONB(), nullable=False),
    sa.Column("reporting_currency", sa.Text(), nullable=False),
    sa.Column("timezone", sa.Text(), nullable=False),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("locale IN ('en','zh')", name="ck_workspace_preferences_locale"),
    sa.CheckConstraint("sidebar_mode IN ('full','compact')", name="ck_workspace_preferences_sidebar_mode"),
    sa.CheckConstraint("period_preset IN ('current_month','previous_month','last_30_days')", name="ck_workspace_preferences_period"),
    sa.CheckConstraint("comparison_preset IN ('none','previous_period','previous_year')", name="ck_workspace_preferences_comparison"),
    sa.CheckConstraint("reporting_currency ~ '^[A-Z]{3}$'", name="ck_workspace_preferences_currency"),
    sa.CheckConstraint("revision >= 1", name="ck_workspace_preferences_revision"),
    sa.CheckConstraint("octet_length(overview_kpis::text) <= 2048", name="ck_workspace_preferences_kpis_size"),
    sa.UniqueConstraint("workspace_id", "operator_id", name="uq_workspace_preferences_owner"),
)

saved_views = sa.Table(
    "saved_views",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("workspace_id", sa.Text(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    sa.Column("operator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("operator_accounts.id", ondelete="CASCADE"), nullable=False),
    sa.Column("name", sa.Text(), nullable=False),
    sa.Column("kind", sa.Text(), nullable=False),
    sa.Column("config", postgresql.JSONB(), nullable=False),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('today','actions')", name="ck_saved_views_kind"),
    sa.CheckConstraint("length(name) BETWEEN 1 AND 80", name="ck_saved_views_name"),
    sa.CheckConstraint("revision >= 1", name="ck_saved_views_revision"),
    sa.CheckConstraint("octet_length(config::text) <= 4096", name="ck_saved_views_config_size"),
)
sa.Index("ix_saved_views_owner_updated", saved_views.c.workspace_id, saved_views.c.operator_id, saved_views.c.updated_at)

workspace_targets = sa.Table(
    "workspace_targets",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("workspace_id", sa.Text(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    sa.Column("operator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("operator_accounts.id", ondelete="CASCADE"), nullable=False),
    sa.Column("period", sa.Text(), nullable=False),
    sa.Column("revenue_brl", sa.Numeric(18, 2), nullable=False),
    sa.Column("orders", sa.Integer(), nullable=False),
    sa.Column("roas", sa.Numeric(12, 2), nullable=False),
    sa.Column("profit_brl", sa.Numeric(18, 2), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("period ~ '^[0-9]{4}-[0-9]{2}$'", name="ck_workspace_targets_period"),
    sa.CheckConstraint("revenue_brl >= 0 AND orders >= 0 AND roas >= 0", name="ck_workspace_targets_nonnegative"),
    sa.CheckConstraint("status IN ('active','archived')", name="ck_workspace_targets_status"),
    sa.CheckConstraint("revision >= 1", name="ck_workspace_targets_revision"),
)
sa.Index("ix_workspace_targets_owner_period", workspace_targets.c.workspace_id, workspace_targets.c.operator_id, workspace_targets.c.period)

ai_control_state = sa.Table(
    "ai_control_state",
    metadata,
    sa.Column(
        "workspace_id",
        sa.Text(),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("operator_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("demo_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("key_name", sa.Text(), nullable=True),
    sa.Column("key_version", sa.Text(), nullable=True),
    sa.Column("key_reference", sa.Text(), nullable=True),
    sa.Column("key_fingerprint", sa.Text(), nullable=True),
    sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column(
        "key_validation_state",
        sa.Text(),
        nullable=False,
        server_default="unconfigured",
    ),
    sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("updated_by_operator_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("revision >= 0", name="ck_ai_control_state_revision"),
    sa.CheckConstraint(
        "(key_name IS NULL AND key_version IS NULL AND key_reference IS NULL AND "
        "key_fingerprint IS NULL AND verified_at IS NULL AND "
        "key_validation_state = 'unconfigured') OR "
        "(key_name IS NOT NULL AND length(key_name) BETWEEN 1 AND 127 AND "
        "key_version IS NOT NULL AND length(key_version) BETWEEN 1 AND 255 AND "
        "key_reference = key_name || '/' || key_version AND "
        "key_fingerprint ~ '^[0-9a-f]{64}$' AND verified_at IS NOT NULL AND "
        "key_validation_state = 'verified')",
        name="ck_ai_control_state_key_binding",
    ),
    sa.CheckConstraint(
        "(operator_enabled = FALSE AND demo_enabled = FALSE) OR "
        "(key_name IS NOT NULL AND key_version IS NOT NULL AND "
        "key_reference = key_name || '/' || key_version AND "
        "key_fingerprint ~ '^[0-9a-f]{64}$' AND verified_at IS NOT NULL AND "
        "key_validation_state = 'verified')",
        name="ck_ai_control_state_enabled_requires_verified_key",
    ),
)

admin_audit_events = sa.Table(
    "admin_audit_events",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "workspace_id",
        sa.Text(),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("action", sa.Text(), nullable=False),
    sa.Column("result", sa.Text(), nullable=False),
    sa.Column("safe_error_code", sa.Text(), nullable=True),
    sa.Column("prior_revision", sa.Integer(), nullable=False),
    sa.Column("resulting_revision", sa.Integer(), nullable=False),
    sa.Column("requested_operator_enabled", sa.Boolean(), nullable=True),
    sa.Column("requested_demo_enabled", sa.Boolean(), nullable=True),
    sa.Column("request_id", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["workspace_id", "operator_id"],
        ["operator_accounts.workspace_id", "operator_accounts.id"],
        name="fk_admin_audit_events_workspace_operator",
        ondelete="RESTRICT",
    ),
)
sa.Index(
    "ix_admin_audit_events_workspace_created_at",
    admin_audit_events.c.workspace_id,
    admin_audit_events.c.created_at,
)
