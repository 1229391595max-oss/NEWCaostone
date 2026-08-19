"""Distinguish prepared Demo sources from operator uploads.

Revision ID: 0011_operator_source_kind
Revises: 0010_demo_data_activation
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0011_operator_source_kind"
down_revision: str | None = "0010_demo_data_activation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "import_workflows",
        sa.Column(
            "source_kind",
            sa.Text(),
            nullable=False,
            server_default="legacy_synthetic",
        ),
    )
    op.create_check_constraint(
        "ck_import_workflows_source_kind",
        "import_workflows",
        "source_kind IN ('legacy_synthetic', 'operator_upload')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_import_workflows_source_kind",
        "import_workflows",
        type_="check",
    )
    op.drop_column("import_workflows", "source_kind")
