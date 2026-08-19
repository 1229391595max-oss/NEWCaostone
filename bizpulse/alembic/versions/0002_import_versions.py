"""Create Blob ledger, imports, immutable dataset versions, and releases."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_import_versions"
down_revision: str | None = "0001_demo_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "storage_objects",
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
    op.create_index(
        "ix_storage_objects_workspace_state_expiry",
        "storage_objects",
        ["workspace_id", "state", "expires_at"],
    )
    op.create_table(
        "import_workflows",
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
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('created', 'uploading', 'recognized', 'ready', "
            "'committing', 'committed', 'rejected', 'failed', 'cancelled')",
            name="ck_import_workflows_status",
        ),
        sa.CheckConstraint("revision >= 0", name="ck_import_workflows_revision"),
    )
    op.create_table(
        "upload_records",
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
    op.create_table(
        "dataset_series",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Text(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
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
    op.create_table(
        "dataset_versions",
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
        sa.ForeignKeyConstraint(
            ["workspace_id", "series_id"],
            ["dataset_series.workspace_id", "dataset_series.id"],
            name="fk_dataset_versions_workspace_series",
            ondelete="RESTRICT",
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
    op.create_foreign_key(
        "fk_dataset_series_current_version",
        "dataset_series",
        "dataset_versions",
        ["id", "current_version_id"],
        ["series_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "dataset_artifacts",
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
    op.create_table(
        "public_releases",
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
    op.create_index(
        "uq_public_releases_one_active_per_workspace",
        "public_releases",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_foreign_key(
        "fk_demo_sessions_dataset_version",
        "demo_sessions",
        "dataset_versions",
        ["workspace_id", "dataset_version_id"],
        ["workspace_id", "id"],
        ondelete="RESTRICT",
    )

    op.execute(
        """
        CREATE FUNCTION prevent_dataset_immutable_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'immutable_dataset_record';
        END;
        $$
        """
    )
    for table_name in ("dataset_versions", "dataset_artifacts"):
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_immutable "
            f"BEFORE UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION prevent_dataset_immutable_mutation()"
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_dataset_artifacts_immutable ON dataset_artifacts")
    op.execute("DROP TRIGGER trg_dataset_versions_immutable ON dataset_versions")
    op.execute("DROP FUNCTION prevent_dataset_immutable_mutation")
    op.drop_constraint(
        "fk_demo_sessions_dataset_version",
        "demo_sessions",
        type_="foreignkey",
    )
    op.drop_index(
        "uq_public_releases_one_active_per_workspace",
        table_name="public_releases",
    )
    op.drop_table("public_releases")
    op.drop_table("dataset_artifacts")
    op.drop_constraint(
        "fk_dataset_series_current_version",
        "dataset_series",
        type_="foreignkey",
    )
    op.drop_table("dataset_versions")
    op.drop_table("dataset_series")
    op.drop_table("upload_records")
    op.drop_table("import_workflows")
    op.drop_index(
        "ix_storage_objects_workspace_state_expiry",
        table_name="storage_objects",
    )
    op.drop_table("storage_objects")
