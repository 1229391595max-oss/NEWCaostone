"""Add append-only Chat session and history ordering fences."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_chat_session_fences"
down_revision: str | None = "0006_ai_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "demo_sessions",
        sa.Column(
            "chat_epoch",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_demo_sessions_chat_epoch",
        "demo_sessions",
        "chat_epoch >= 0",
    )

    op.add_column(
        "ai_chat_turns",
        sa.Column("turn_sequence", sa.BigInteger(), nullable=True),
    )
    op.execute("ALTER TABLE ai_chat_turns DISABLE TRIGGER ai_chat_turns_protected")
    op.execute(
        """
        WITH ordered AS (
            SELECT id, row_number() OVER (
                PARTITION BY actor_kind, operator_session_id, demo_session_id
                ORDER BY created_at, id
            )::bigint AS value
            FROM ai_chat_turns
        )
        UPDATE ai_chat_turns AS target
        SET turn_sequence = ordered.value
        FROM ordered
        WHERE target.id = ordered.id
        """
    )
    op.execute("ALTER TABLE ai_chat_turns ENABLE TRIGGER ai_chat_turns_protected")
    op.alter_column(
        "ai_chat_turns",
        "turn_sequence",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.create_index(
        "uq_ai_chat_turns_operator_sequence",
        "ai_chat_turns",
        ["operator_session_id", "turn_sequence"],
        unique=True,
        postgresql_where=sa.text("actor_kind = 'operator'"),
    )
    op.create_index(
        "uq_ai_chat_turns_demo_sequence",
        "ai_chat_turns",
        ["demo_session_id", "turn_sequence"],
        unique=True,
        postgresql_where=sa.text("actor_kind = 'demo'"),
    )
    op.execute(
        """
        CREATE FUNCTION protect_ai_chat_turn_sequence() RETURNS trigger AS $$
        BEGIN
            IF NEW.turn_sequence IS DISTINCT FROM OLD.turn_sequence THEN
                RAISE EXCEPTION 'immutable_ai_chat_turn_sequence';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER ai_chat_turn_sequence_immutable "
        "BEFORE UPDATE ON ai_chat_turns FOR EACH ROW "
        "EXECUTE FUNCTION protect_ai_chat_turn_sequence()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS ai_chat_turn_sequence_immutable ON ai_chat_turns"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_ai_chat_turn_sequence()")
    op.drop_index(
        "uq_ai_chat_turns_demo_sequence",
        table_name="ai_chat_turns",
    )
    op.drop_index(
        "uq_ai_chat_turns_operator_sequence",
        table_name="ai_chat_turns",
    )
    op.drop_column("ai_chat_turns", "turn_sequence")
    op.drop_constraint(
        "ck_demo_sessions_chat_epoch",
        "demo_sessions",
        type_="check",
    )
    op.drop_column("demo_sessions", "chat_epoch")
