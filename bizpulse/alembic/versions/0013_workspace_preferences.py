"""Add bounded Operator workspace preferences, saved views, and targets.

Revision ID: 0013_workspace_preferences
Revises: 0012_dataset_exports
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0013_workspace_preferences"
down_revision: str | None = "0012_dataset_exports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"], ["operator_accounts.id"], ondelete="CASCADE",
        ),
        sa.CheckConstraint("locale IN ('en','zh')", name="ck_workspace_preferences_locale"),
        sa.CheckConstraint(
            "sidebar_mode IN ('full','compact')",
            name="ck_workspace_preferences_sidebar_mode",
        ),
        sa.CheckConstraint(
            "period_preset IN ('current_month','previous_month','last_30_days')",
            name="ck_workspace_preferences_period",
        ),
        sa.CheckConstraint(
            "comparison_preset IN ('none','previous_period','previous_year')",
            name="ck_workspace_preferences_comparison",
        ),
        sa.CheckConstraint(
            "reporting_currency ~ '^[A-Z]{3}$'",
            name="ck_workspace_preferences_currency",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_workspace_preferences_revision"),
        sa.CheckConstraint(
            "octet_length(overview_kpis::text) <= 2048",
            name="ck_workspace_preferences_kpis_size",
        ),
        sa.UniqueConstraint(
            "workspace_id", "operator_id", name="uq_workspace_preferences_owner",
        ),
    )
    op.create_table(
        "saved_views",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"], ["operator_accounts.id"], ondelete="CASCADE",
        ),
        sa.CheckConstraint("kind IN ('today','actions')", name="ck_saved_views_kind"),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 80", name="ck_saved_views_name"),
        sa.CheckConstraint("revision >= 1", name="ck_saved_views_revision"),
        sa.CheckConstraint(
            "octet_length(config::text) <= 4096", name="ck_saved_views_config_size",
        ),
    )
    op.create_index(
        "ix_saved_views_owner_updated",
        "saved_views",
        ["workspace_id", "operator_id", "updated_at"],
    )
    op.create_table(
        "workspace_targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("revenue_brl", sa.Numeric(18, 2), nullable=False),
        sa.Column("orders", sa.Integer(), nullable=False),
        sa.Column("roas", sa.Numeric(12, 2), nullable=False),
        sa.Column("profit_brl", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"], ["operator_accounts.id"], ondelete="CASCADE",
        ),
        sa.CheckConstraint("period ~ '^[0-9]{4}-[0-9]{2}$'", name="ck_workspace_targets_period"),
        sa.CheckConstraint(
            "revenue_brl >= 0 AND orders >= 0 AND roas >= 0",
            name="ck_workspace_targets_nonnegative",
        ),
        sa.CheckConstraint(
            "status IN ('active','archived')", name="ck_workspace_targets_status",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_workspace_targets_revision"),
    )
    op.create_index(
        "ix_workspace_targets_owner_period",
        "workspace_targets",
        ["workspace_id", "operator_id", "period"],
    )


def downgrade() -> None:
    op.drop_index("ix_workspace_targets_owner_period", table_name="workspace_targets")
    op.drop_table("workspace_targets")
    op.drop_index("ix_saved_views_owner_updated", table_name="saved_views")
    op.drop_table("saved_views")
    op.drop_table("workspace_preferences")
