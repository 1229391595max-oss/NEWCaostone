"""Create human-controlled action cards and session overlays."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_actions"
down_revision: str | None = "0004_forecast_profit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "action_cards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "dataset_version_id"],
            ["dataset_versions.workspace_id", "dataset_versions.id"],
            name="fk_action_cards_workspace_version",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "source_type IN ('deterministic_rule', 'new_product_forecast', "
            "'profit_bridge', 'operating_advice', 'chat_box_draft')",
            name="ck_action_cards_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('new', 'reviewed', 'approved', 'dismissed')",
            name="ck_action_cards_status",
        ),
        sa.CheckConstraint("current_revision >= 1", name="ck_action_cards_revision"),
        sa.CheckConstraint(
            "(status IN ('new', 'reviewed') AND terminal_at IS NULL) OR "
            "(status IN ('approved', 'dismissed') AND terminal_at IS NOT NULL)",
            name="ck_action_cards_terminal",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key_hash",
            name="uq_action_cards_create_idempotency",
        ),
    )
    op.create_index(
        "ix_action_cards_workspace_version_created",
        "action_cards",
        ["workspace_id", "dataset_version_id", "created_at"],
    )
    op.create_table(
        "action_card_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("action_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("scope", postgresql.JSONB(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("budget_brl", sa.Numeric(18, 2), nullable=True),
        sa.Column("action_date", sa.Date(), nullable=True),
        sa.Column("threshold", sa.Numeric(18, 4), nullable=True),
        sa.Column("expected_impact", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("limitations", postgresql.JSONB(), nullable=False),
        sa.Column("facts", postgresql.JSONB(), nullable=False),
        sa.Column("analysis_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("forecast_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("bridge_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("chat_turn_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("chat_tool", sa.Text(), nullable=True),
        sa.Column("answer_version", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            name="fk_action_card_revisions_analysis",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["forecast_id"],
            ["new_product_forecasts.id"],
            name="fk_action_card_revisions_forecast",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["bridge_id"],
            ["profit_bridges.id"],
            name="fk_action_card_revisions_bridge",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_action_card_revisions_revision"),
        sa.CheckConstraint(
            "period_start <= period_end", name="ck_action_card_revisions_period"
        ),
        sa.CheckConstraint(
            "confidence IN ('low', 'medium', 'high')",
            name="ck_action_card_revisions_confidence",
        ),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity >= 0",
            name="ck_action_card_revisions_quantity",
        ),
        sa.CheckConstraint(
            "budget_brl IS NULL OR budget_brl >= 0",
            name="ck_action_card_revisions_budget",
        ),
        sa.UniqueConstraint(
            "action_id", "revision", name="uq_action_card_revisions_exact"
        ),
    )
    op.create_table(
        "action_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("action_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action_revision", sa.Integer(), nullable=False),
        sa.Column("decision_ordinal", sa.Integer(), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.Text(), nullable=False),
        sa.Column("idempotency_key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["action_id", "action_revision"],
            ["action_card_revisions.action_id", "action_card_revisions.revision"],
            name="fk_action_decisions_revision",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "command IN ('review', 'adjust', 'approve', 'dismiss')",
            name="ck_action_decisions_command",
        ),
        sa.CheckConstraint(
            "decision_ordinal >= 1",
            name="ck_action_decisions_ordinal",
        ),
        sa.UniqueConstraint(
            "action_id",
            "decision_ordinal",
            name="uq_action_decisions_ordinal",
        ),
        sa.UniqueConstraint(
            "action_id", "idempotency_key_hash", name="uq_action_decisions_idempotency"
        ),
        sa.CheckConstraint(
            "decided_by = 'single_operator'", name="ck_action_decisions_actor"
        ),
    )
    op.create_table(
        "action_exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("action_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action_revision", sa.Integer(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "storage_object_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("storage_objects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("exported_by", sa.Text(), nullable=False),
        sa.Column("idempotency_key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["action_id", "action_revision"],
            ["action_card_revisions.action_id", "action_card_revisions.revision"],
            name="fk_action_exports_revision",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("format = 'xlsx'", name="ck_action_exports_format"),
        sa.CheckConstraint("status = 'available'", name="ck_action_exports_status"),
        sa.CheckConstraint(
            "note = 'Not sent to an external platform'", name="ck_action_exports_note"
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name="ck_action_exports_sha256"
        ),
        sa.CheckConstraint(
            "exported_by = 'single_operator'", name="ck_action_exports_actor"
        ),
        sa.UniqueConstraint(
            "action_id", "idempotency_key_hash", name="uq_action_exports_idempotency"
        ),
    )
    op.create_table(
        "action_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("action_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action_revision", sa.Integer(), nullable=False),
        sa.Column("outcome_revision", sa.Integer(), nullable=False),
        sa.Column("review_date", sa.Date(), nullable=False),
        sa.Column("synthetic_result", postgresql.JSONB(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("conclusion", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reviewed_by", sa.Text(), nullable=False),
        sa.Column("idempotency_key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["action_id", "action_revision"],
            ["action_card_revisions.action_id", "action_card_revisions.revision"],
            name="fk_action_outcomes_revision",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "conclusion IN ('achieved', 'partially_achieved', 'not_achieved', 'inconclusive')",
            name="ck_action_outcomes_conclusion",
        ),
        sa.CheckConstraint(
            "reviewed_by = 'single_operator'", name="ck_action_outcomes_actor"
        ),
        sa.UniqueConstraint(
            "action_id", "outcome_revision", name="uq_action_outcomes_revision"
        ),
        sa.UniqueConstraint(
            "action_id", "idempotency_key_hash", name="uq_action_outcomes_idempotency"
        ),
    )
    op.create_table(
        "demo_action_overlays",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "demo_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("demo_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("action_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("overlay_revision", sa.Integer(), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("adjustment", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["action_id", "base_revision"],
            ["action_card_revisions.action_id", "action_card_revisions.revision"],
            name="fk_demo_action_overlays_revision",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "command IN ('review', 'adjust', 'approve', 'dismiss')",
            name="ck_demo_action_overlays_command",
        ),
        sa.CheckConstraint(
            "status IN ('reviewed', 'approved', 'dismissed')",
            name="ck_demo_action_overlays_status",
        ),
        sa.CheckConstraint(
            "base_revision >= 1", name="ck_demo_action_overlays_base_revision"
        ),
        sa.CheckConstraint(
            "overlay_revision >= 1", name="ck_demo_action_overlays_revision"
        ),
        sa.UniqueConstraint(
            "demo_session_id",
            "action_id",
            "overlay_revision",
            name="uq_demo_action_overlays_revision",
        ),
        sa.UniqueConstraint(
            "demo_session_id",
            "idempotency_key_hash",
            name="uq_demo_action_overlays_idempotency",
        ),
    )
    op.execute(
        """
        CREATE FUNCTION prevent_action_append_record_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'immutable_action_record';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in (
        "action_card_revisions",
        "action_decisions",
        "action_exports",
        "action_outcomes",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION prevent_action_append_record_mutation()"
        )
    op.execute(
        """
        CREATE FUNCTION protect_action_card_state() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'immutable_action_card';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
               OR NEW.dataset_version_id IS DISTINCT FROM OLD.dataset_version_id
               OR NEW.source_type IS DISTINCT FROM OLD.source_type
               OR NEW.idempotency_key_hash IS DISTINCT FROM OLD.idempotency_key_hash
               OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'immutable_action_authority';
            END IF;
            IF OLD.status IN ('approved', 'dismissed') THEN
                RAISE EXCEPTION 'immutable_terminal_action';
            END IF;
            IF NOT (
                (OLD.status = 'new' AND NEW.status = 'reviewed'
                 AND NEW.current_revision = OLD.current_revision) OR
                (OLD.status = 'reviewed' AND NEW.status = 'reviewed'
                 AND NEW.current_revision = OLD.current_revision + 1) OR
                (OLD.status = 'reviewed' AND NEW.status IN ('approved', 'dismissed')
                 AND NEW.current_revision = OLD.current_revision)
            ) THEN
                RAISE EXCEPTION 'invalid_action_transition';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER action_cards_protected BEFORE UPDATE OR DELETE ON action_cards "
        "FOR EACH ROW EXECUTE FUNCTION protect_action_card_state()"
    )
    op.execute(
        """
        CREATE FUNCTION validate_action_revision_insert() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM action_cards
                WHERE id = NEW.action_id
                  AND current_revision = NEW.revision
                  AND status IN ('new', 'reviewed')
            ) THEN
                RAISE EXCEPTION 'invalid_action_revision_insert';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER action_card_revisions_valid_insert BEFORE INSERT "
        "ON action_card_revisions FOR EACH ROW "
        "EXECUTE FUNCTION validate_action_revision_insert()"
    )
    op.execute(
        """
        CREATE FUNCTION validate_action_decision_insert() RETURNS trigger AS $$
        BEGIN
            IF NEW.decision_ordinal <> (
                SELECT COUNT(*) + 1
                FROM action_decisions
                WHERE action_id = NEW.action_id
            ) THEN
                RAISE EXCEPTION 'invalid_action_decision_ordinal';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM action_cards
                WHERE id = NEW.action_id
                  AND current_revision = NEW.action_revision
                  AND (
                    (NEW.command IN ('review', 'adjust') AND status = 'reviewed') OR
                    (NEW.command = 'approve' AND status = 'approved') OR
                    (NEW.command = 'dismiss' AND status = 'dismissed')
                  )
            ) THEN
                RAISE EXCEPTION 'invalid_action_decision_insert';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER action_decisions_valid_insert BEFORE INSERT ON action_decisions "
        "FOR EACH ROW EXECUTE FUNCTION validate_action_decision_insert()"
    )
    op.execute(
        """
        CREATE FUNCTION validate_approved_action_child() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM action_cards
                WHERE id = NEW.action_id
                  AND status = 'approved'
                  AND current_revision = NEW.action_revision
            ) THEN
                RAISE EXCEPTION 'action_not_approved';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("action_exports", "action_outcomes"):
        op.execute(
            f"CREATE TRIGGER {table}_approved_insert BEFORE INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION validate_approved_action_child()"
        )
    op.execute(
        """
        CREATE FUNCTION validate_demo_action_overlay() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM demo_sessions s
                JOIN action_cards a
                  ON a.workspace_id = s.workspace_id
                 AND a.dataset_version_id = s.dataset_version_id
                WHERE s.id = NEW.demo_session_id
                  AND s.status = 'active'
                  AND s.ended_at IS NULL
                  AND s.idle_expires_at > NEW.created_at
                  AND s.absolute_expires_at > NEW.created_at
                  AND a.id = NEW.action_id
                  AND a.status = 'approved'
                  AND a.terminal_at < s.created_at
                  AND a.current_revision = NEW.base_revision
            ) THEN
                RAISE EXCEPTION 'invalid_demo_action_scope';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER demo_action_overlays_valid_insert BEFORE INSERT "
        "ON demo_action_overlays FOR EACH ROW "
        "EXECUTE FUNCTION validate_demo_action_overlay()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS demo_action_overlays_valid_insert ON demo_action_overlays"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_demo_action_overlay")
    for table in ("action_outcomes", "action_exports"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_approved_insert ON {table}")
    op.execute("DROP FUNCTION IF EXISTS validate_approved_action_child")
    op.execute("DROP TRIGGER IF EXISTS action_decisions_valid_insert ON action_decisions")
    op.execute("DROP FUNCTION IF EXISTS validate_action_decision_insert")
    op.execute(
        "DROP TRIGGER IF EXISTS action_card_revisions_valid_insert "
        "ON action_card_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_action_revision_insert")
    op.execute("DROP TRIGGER IF EXISTS action_cards_protected ON action_cards")
    op.execute("DROP FUNCTION IF EXISTS protect_action_card_state")
    for table in (
        "action_outcomes",
        "action_exports",
        "action_decisions",
        "action_card_revisions",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS prevent_action_append_record_mutation")
    op.drop_table("demo_action_overlays")
    op.drop_table("action_outcomes")
    op.drop_table("action_exports")
    op.drop_table("action_decisions")
    op.drop_table("action_card_revisions")
    op.drop_index("ix_action_cards_workspace_version_created", table_name="action_cards")
    op.drop_table("action_cards")
