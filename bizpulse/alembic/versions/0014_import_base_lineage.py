"""Bind imports and dataset versions to immutable base lineage.

Revision ID: 0014_import_base_lineage
Revises: 0013_workspace_preferences
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0014_import_base_lineage"
down_revision: str | None = "0013_workspace_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_ai_chat_attempts_model",
        "ai_chat_attempts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_chat_attempts_model",
        "ai_chat_attempts",
        "model = 'gpt-5.4-nano-2026-03-17'",
    )
    op.add_column(
        "import_workflows",
        sa.Column(
            "base_dataset_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_import_workflows_base_dataset_version",
        "import_workflows",
        "dataset_versions",
        ["workspace_id", "base_dataset_version_id"],
        ["workspace_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_import_workflows_base_dataset_version",
        "import_workflows",
        ["base_dataset_version_id"],
    )

    op.add_column(
        "upload_records",
        sa.Column("assigned_store_id", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_upload_records_assigned_store_id",
        "upload_records",
        "assigned_store_id IS NULL OR length(assigned_store_id) BETWEEN 1 AND 100",
    )

    op.add_column(
        "dataset_versions",
        sa.Column(
            "base_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_dataset_versions_base_version",
        "dataset_versions",
        "dataset_versions",
        ["series_id", "base_version_id"],
        ["series_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_dataset_versions_base_version",
        "dataset_versions",
        ["base_version_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_dataset_versions_base_version", table_name="dataset_versions")
    op.drop_constraint(
        "fk_dataset_versions_base_version",
        "dataset_versions",
        type_="foreignkey",
    )
    op.drop_column("dataset_versions", "base_version_id")

    op.drop_constraint(
        "ck_upload_records_assigned_store_id",
        "upload_records",
        type_="check",
    )
    op.drop_column("upload_records", "assigned_store_id")

    op.drop_index(
        "ix_import_workflows_base_dataset_version",
        table_name="import_workflows",
    )
    op.drop_constraint(
        "fk_import_workflows_base_dataset_version",
        "import_workflows",
        type_="foreignkey",
    )
    op.drop_column("import_workflows", "base_dataset_version_id")
    op.drop_constraint(
        "ck_ai_chat_attempts_model",
        "ai_chat_attempts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_chat_attempts_model",
        "ai_chat_attempts",
        "model = 'gpt-5.4-mini-2026-03-17'",
    )
