"""Create deterministic forecast and profit-bridge persistence."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_forecast_profit"
down_revision: str | None = "0003_analysis_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "new_product_forecasts",
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
    op.create_index(
        "ix_new_product_forecasts_workspace_version_created",
        "new_product_forecasts",
        ["workspace_id", "dataset_version_id", "created_at"],
    )
    op.add_column(
        "demo_sessions",
        sa.Column("forecast_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_demo_sessions_forecast",
        "demo_sessions",
        "new_product_forecasts",
        ["workspace_id", "dataset_version_id", "forecast_id"],
        ["workspace_id", "dataset_version_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "forecast_analogs",
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
    op.create_table(
        "forecast_scenarios",
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
        sa.CheckConstraint("horizon_days IN (7, 30, 90)", name="ck_forecast_scenarios_horizon"),
        sa.CheckConstraint("scenario IN ('low', 'base', 'high')", name="ck_forecast_scenarios_name"),
        sa.CheckConstraint("units >= 0 AND revenue_brl >= 0", name="ck_forecast_scenarios_values"),
        sa.UniqueConstraint(
            "forecast_id",
            "horizon_days",
            "scenario",
            name="uq_forecast_scenarios_exact",
        ),
    )
    op.create_table(
        "profit_bridges",
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
    op.add_column(
        "demo_sessions",
        sa.Column("profit_bridge_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_demo_sessions_profit_bridge",
        "demo_sessions",
        "profit_bridges",
        ["workspace_id", "dataset_version_id", "profit_bridge_id"],
        ["workspace_id", "dataset_version_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "profit_bridge_items",
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
        sa.CheckConstraint("ordinal BETWEEN 1 AND 12", name="ck_profit_bridge_items_ordinal"),
        sa.CheckConstraint(
            "evidence_state IN ('measured', 'derived', 'assumed', 'unknown')",
            name="ck_profit_bridge_items_evidence_state",
        ),
        sa.UniqueConstraint("bridge_id", "driver", name="uq_profit_bridge_items_driver"),
        sa.UniqueConstraint("bridge_id", "ordinal", name="uq_profit_bridge_items_ordinal"),
    )
    op.execute(
        """
        CREATE FUNCTION prevent_terminal_forecast_mutation() RETURNS trigger AS $$
        BEGIN
            IF OLD.status IN ('completed', 'blocked') THEN
                RAISE EXCEPTION 'immutable_terminal_forecast';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER new_product_forecasts_immutable_terminal "
        "BEFORE UPDATE OR DELETE ON new_product_forecasts FOR EACH ROW "
        "EXECUTE FUNCTION prevent_terminal_forecast_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION prevent_terminal_forecast_child_insert() RETURNS trigger AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM new_product_forecasts
                WHERE id = NEW.forecast_id AND status IN ('completed', 'blocked')
            ) THEN
                RAISE EXCEPTION 'immutable_terminal_forecast_child';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_terminal_forecast_child_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.forecast_id <> OLD.forecast_id THEN
                RAISE EXCEPTION 'immutable_forecast_child_parent';
            END IF;
            IF EXISTS (
                SELECT 1 FROM new_product_forecasts
                WHERE id = OLD.forecast_id AND status IN ('completed', 'blocked')
            ) THEN
                RAISE EXCEPTION 'immutable_terminal_forecast_child';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("forecast_analogs", "forecast_scenarios"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable_insert BEFORE INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION prevent_terminal_forecast_child_insert()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_immutable_mutation BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION prevent_terminal_forecast_child_mutation()"
        )
    op.execute(
        """
        CREATE FUNCTION prevent_profit_bridge_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'immutable_profit_bridge';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER profit_bridges_immutable "
        "BEFORE UPDATE OR DELETE ON profit_bridges FOR EACH ROW "
        "EXECUTE FUNCTION prevent_profit_bridge_mutation()"
    )
    op.execute(
        "CREATE TRIGGER profit_bridge_items_immutable "
        "BEFORE UPDATE OR DELETE ON profit_bridge_items FOR EACH ROW "
        "EXECUTE FUNCTION prevent_profit_bridge_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS profit_bridge_items_immutable "
        "ON profit_bridge_items"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS profit_bridges_immutable ON profit_bridges"
    )
    for table in ("forecast_scenarios", "forecast_analogs"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable_insert ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable_mutation ON {table}")
    op.execute(
        "DROP TRIGGER IF EXISTS new_product_forecasts_immutable_terminal "
        "ON new_product_forecasts"
    )
    op.drop_constraint(
        "fk_demo_sessions_profit_bridge",
        "demo_sessions",
        type_="foreignkey",
    )
    op.drop_column("demo_sessions", "profit_bridge_id")
    op.drop_table("profit_bridge_items")
    op.drop_table("profit_bridges")
    op.drop_table("forecast_scenarios")
    op.drop_table("forecast_analogs")
    op.drop_constraint(
        "fk_demo_sessions_forecast",
        "demo_sessions",
        type_="foreignkey",
    )
    op.drop_column("demo_sessions", "forecast_id")
    op.drop_index(
        "ix_new_product_forecasts_workspace_version_created",
        table_name="new_product_forecasts",
    )
    op.drop_table("new_product_forecasts")
    op.execute("DROP FUNCTION IF EXISTS prevent_terminal_forecast_child_mutation()")
    op.execute("DROP FUNCTION IF EXISTS prevent_terminal_forecast_child_insert()")
    op.execute("DROP FUNCTION IF EXISTS prevent_terminal_forecast_mutation()")
    op.execute("DROP FUNCTION IF EXISTS prevent_profit_bridge_mutation()")
