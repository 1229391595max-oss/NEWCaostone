"""Add immutable normalized dataset workbook exports.

Revision ID: 0012_dataset_exports
Revises: 0011_operator_source_kind
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0012_dataset_exports"
down_revision: str | None = "0011_operator_source_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dataset_exports",
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
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dataset_exports_sha256",
        ),
        sa.CheckConstraint("byte_count > 0", name="ck_dataset_exports_byte_count"),
        sa.UniqueConstraint(
            "workspace_id",
            "dataset_version_id",
            "idempotency_key_hash",
            name="uq_dataset_exports_idempotency",
        ),
    )


def downgrade() -> None:
    op.drop_table("dataset_exports")
