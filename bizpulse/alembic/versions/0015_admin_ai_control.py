"""Add PostgreSQL authority for administrator AI control and audit events.

Revision ID: 0015_admin_ai_control
Revises: 0014_import_base_lineage
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0015_admin_ai_control"
down_revision: str | None = "0014_import_base_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_control_state",
        sa.Column(
            "workspace_id",
            sa.Text(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "operator_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "demo_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("key_version", sa.Text(), nullable=True),
        sa.Column("key_fingerprint", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_by_operator_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 0", name="ck_ai_control_state_revision"),
        sa.CheckConstraint(
            "(key_version IS NULL AND key_fingerprint IS NULL AND verified_at IS NULL) OR "
            "(key_version IS NOT NULL AND key_fingerprint ~ '^[0-9a-f]{64}$' AND verified_at IS NOT NULL)",
            name="ck_ai_control_state_key_binding",
        ),
    )
    op.create_table(
        "admin_audit_events",
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
            sa.ForeignKey("operator_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("safe_error_code", sa.Text(), nullable=True),
        sa.Column("prior_revision", sa.Integer(), nullable=False),
        sa.Column("resulting_revision", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_admin_audit_events_workspace_created_at",
        "admin_audit_events",
        ["workspace_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_admin_audit_events_workspace_created_at",
        table_name="admin_audit_events",
    )
    op.drop_table("admin_audit_events")
    op.drop_table("ai_control_state")
