"""Bind every new AI turn to one immutable exact credential selection.

Revision ID: 0017_ai_turn_credential_binding
Revises: 0016_admin_ai_control_integrity
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0017_ai_turn_credential_binding"
down_revision = "0016_admin_ai_control_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_chat_turns",
        sa.Column("credential_binding_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "ai_chat_turns",
        sa.Column("credential_control_revision", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "ai_chat_turns",
        sa.Column("credential_request_id", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_ai_chat_turns_credential_binding",
        "ai_chat_turns",
        "(credential_binding_id IS NULL AND credential_control_revision IS NULL "
        "AND credential_request_id IS NULL) OR "
        "(credential_binding_id ~ '^[0-9a-f]{64}$' "
        "AND credential_control_revision >= 0 "
        "AND length(credential_request_id) BETWEEN 3 AND 128)",
    )
    op.create_index(
        "uq_ai_chat_turns_credential_request",
        "ai_chat_turns",
        ["workspace_id", "credential_request_id"],
        unique=True,
        postgresql_where=sa.text("credential_request_id IS NOT NULL"),
    )
    op.execute(
        """
        CREATE FUNCTION protect_ai_chat_credential_binding() RETURNS trigger AS $$
        BEGIN
            IF NEW.credential_binding_id IS DISTINCT FROM OLD.credential_binding_id
               OR NEW.credential_control_revision IS DISTINCT FROM OLD.credential_control_revision
               OR NEW.credential_request_id IS DISTINCT FROM OLD.credential_request_id THEN
                RAISE EXCEPTION 'immutable_ai_chat_credential_binding';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER ai_chat_credential_binding_immutable "
        "BEFORE UPDATE ON ai_chat_turns FOR EACH ROW "
        "EXECUTE FUNCTION protect_ai_chat_credential_binding()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS ai_chat_credential_binding_immutable "
        "ON ai_chat_turns"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_ai_chat_credential_binding()")
    op.drop_index(
        "uq_ai_chat_turns_credential_request",
        table_name="ai_chat_turns",
    )
    op.drop_constraint(
        "ck_ai_chat_turns_credential_binding",
        "ai_chat_turns",
        type_="check",
    )
    op.drop_column("ai_chat_turns", "credential_request_id")
    op.drop_column("ai_chat_turns", "credential_control_revision")
    op.drop_column("ai_chat_turns", "credential_binding_id")
