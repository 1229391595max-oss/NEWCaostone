"""Preserve immutable AI budget usage after ephemeral Chat cleanup."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_ai_budget_ledger"
down_revision: str | None = "0007_chat_session_fences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_budget_ledger",
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Text(),
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "stage IN ('planning','answering')",
            name="ck_ai_budget_ledger_stage",
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND reserved_tokens > 0 "
            "AND input_tokens + output_tokens <= reserved_tokens",
            name="ck_ai_budget_ledger_tokens",
        ),
        sa.CheckConstraint(
            "status IN ('started','succeeded','failed','outcome_unknown')",
            name="ck_ai_budget_ledger_status",
        ),
        sa.CheckConstraint(
            "(error_code IS NULL OR length(error_code) <= 100) AND "
            "((status = 'started' AND completed_at IS NULL) OR "
            "(status IN ('succeeded','failed','outcome_unknown') "
            "AND completed_at IS NOT NULL))",
            name="ck_ai_budget_ledger_completion",
        ),
    )
    op.create_index(
        "ix_ai_budget_ledger_created",
        "ai_budget_ledger",
        ["created_at"],
    )
    op.execute(
        """
        INSERT INTO ai_budget_ledger (
            attempt_id, workspace_id, stage, input_tokens, output_tokens,
            reserved_tokens, status, error_code, created_at, completed_at
        )
        SELECT
            attempts.id, turns.workspace_id, attempts.stage,
            attempts.input_tokens, attempts.output_tokens,
            attempts.reserved_tokens, attempts.status, attempts.error_code,
            attempts.created_at, attempts.completed_at
        FROM ai_chat_attempts AS attempts
        JOIN ai_chat_turns AS turns ON turns.id = attempts.turn_id
        """
    )
    op.execute(
        """
        CREATE FUNCTION sync_ai_budget_ledger_insert() RETURNS trigger AS $$
        DECLARE
            target_workspace text;
        BEGIN
            SELECT workspace_id INTO target_workspace
            FROM ai_chat_turns
            WHERE id = NEW.turn_id;
            IF target_workspace IS NULL THEN
                RAISE EXCEPTION 'ai_budget_parent_missing';
            END IF;
            INSERT INTO ai_budget_ledger (
                attempt_id, workspace_id, stage, input_tokens, output_tokens,
                reserved_tokens, status, error_code, created_at, completed_at
            ) VALUES (
                NEW.id, target_workspace, NEW.stage, NEW.input_tokens,
                NEW.output_tokens, NEW.reserved_tokens, NEW.status,
                NEW.error_code, NEW.created_at, NEW.completed_at
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER ai_budget_ledger_insert_sync "
        "AFTER INSERT ON ai_chat_attempts FOR EACH ROW "
        "EXECUTE FUNCTION sync_ai_budget_ledger_insert()"
    )
    op.execute(
        """
        CREATE FUNCTION protect_ai_budget_ledger() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' OR OLD.status <> 'started' THEN
                RAISE EXCEPTION 'immutable_ai_budget_ledger';
            END IF;
            IF NEW.attempt_id IS DISTINCT FROM OLD.attempt_id
               OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
               OR NEW.stage IS DISTINCT FROM OLD.stage
               OR NEW.reserved_tokens IS DISTINCT FROM OLD.reserved_tokens
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.status NOT IN ('succeeded','failed','outcome_unknown')
               OR NEW.completed_at IS NULL THEN
                RAISE EXCEPTION 'invalid_ai_budget_ledger_transition';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER ai_budget_ledger_protected "
        "BEFORE UPDATE OR DELETE ON ai_budget_ledger FOR EACH ROW "
        "EXECUTE FUNCTION protect_ai_budget_ledger()"
    )
    op.execute(
        """
        CREATE FUNCTION sync_ai_budget_ledger_update() RETURNS trigger AS $$
        BEGIN
            UPDATE ai_budget_ledger
            SET input_tokens = NEW.input_tokens,
                output_tokens = NEW.output_tokens,
                status = NEW.status,
                error_code = NEW.error_code,
                completed_at = NEW.completed_at
            WHERE attempt_id = NEW.id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'ai_budget_ledger_missing';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER ai_budget_ledger_update_sync "
        "AFTER UPDATE ON ai_chat_attempts FOR EACH ROW "
        "EXECUTE FUNCTION sync_ai_budget_ledger_update()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS ai_budget_ledger_update_sync ON ai_chat_attempts"
    )
    op.execute("DROP FUNCTION IF EXISTS sync_ai_budget_ledger_update()")
    op.execute(
        "DROP TRIGGER IF EXISTS ai_budget_ledger_protected ON ai_budget_ledger"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_ai_budget_ledger()")
    op.execute(
        "DROP TRIGGER IF EXISTS ai_budget_ledger_insert_sync ON ai_chat_attempts"
    )
    op.execute("DROP FUNCTION IF EXISTS sync_ai_budget_ledger_insert()")
    op.drop_index("ix_ai_budget_ledger_created", table_name="ai_budget_ledger")
    op.drop_table("ai_budget_ledger")
