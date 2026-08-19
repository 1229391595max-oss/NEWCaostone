"""Persist safe import response projections for exact idempotent replay."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002b_import_replay"
down_revision: str | None = "0002_import_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "idempotency_receipts",
        sa.Column("response_projection", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("idempotency_receipts", "response_projection")
