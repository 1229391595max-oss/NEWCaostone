"""Create immutable deterministic analysis runs, artifacts, and evidence."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_analysis_evidence"
down_revision: str | None = "0002b_import_replay"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
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
            "AND failure_code IS NULL AND lease_expires_at IS NOT NULL) OR "
            "(status = 'failed' AND completed_at IS NOT NULL AND failure_code IS NOT NULL "
            "AND lease_expires_at IS NULL)",
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
    op.create_table(
        "analysis_dependencies",
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
    op.create_table(
        "analysis_artifacts",
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
    op.create_table(
        "evidence_items",
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
    op.execute(
        """
        CREATE FUNCTION prevent_completed_analysis_mutation() RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'completed' THEN
                RAISE EXCEPTION 'immutable_completed_analysis';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER analysis_runs_immutable_completed BEFORE UPDATE OR DELETE "
        "ON analysis_runs FOR EACH ROW EXECUTE FUNCTION "
        "prevent_completed_analysis_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION prevent_completed_analysis_child_insert() RETURNS trigger AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM analysis_runs
                WHERE id = NEW.run_id AND status = 'completed'
            ) THEN
                RAISE EXCEPTION 'immutable_completed_analysis_child';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_analysis_child_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'immutable_analysis_record';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("analysis_dependencies", "analysis_artifacts", "evidence_items"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable_insert BEFORE INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION "
            "prevent_completed_analysis_child_insert()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION prevent_analysis_child_mutation()"
        )


def downgrade() -> None:
    for table in ("evidence_items", "analysis_artifacts", "analysis_dependencies"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable_insert ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP TRIGGER IF EXISTS analysis_runs_immutable_completed ON analysis_runs")
    op.drop_table("evidence_items")
    op.drop_table("analysis_artifacts")
    op.drop_table("analysis_dependencies")
    op.drop_table("analysis_runs")
    op.execute("DROP FUNCTION IF EXISTS prevent_analysis_child_mutation()")
    op.execute("DROP FUNCTION IF EXISTS prevent_completed_analysis_child_insert()")
    op.execute("DROP FUNCTION IF EXISTS prevent_completed_analysis_mutation()")
