"""Add an idempotent per-viewer Demo data activation marker.

Revision ID: 0010_demo_data_activation
Revises: 0009_prompt_preset_audit
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0010_demo_data_activation"
down_revision: str | None = "0009_prompt_preset_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "demo_sessions",
        sa.Column("demo_data_imported_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("demo_sessions", "demo_data_imported_at")
