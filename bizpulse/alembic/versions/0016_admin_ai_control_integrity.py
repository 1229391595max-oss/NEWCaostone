"""Enforce administrator AI control and audit integrity.

Revision ID: 0016_admin_ai_control_integrity
Revises: 0015_admin_ai_control
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0016_admin_ai_control_integrity"
down_revision: str | None = "0015_admin_ai_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_ai_control_state_key_binding",
        "ai_control_state",
        type_="check",
    )
    op.add_column("ai_control_state", sa.Column("key_name", sa.Text(), nullable=True))
    op.add_column(
        "ai_control_state",
        sa.Column("key_reference", sa.Text(), nullable=True),
    )
    op.add_column(
        "ai_control_state",
        sa.Column(
            "key_validation_state",
            sa.Text(),
            nullable=False,
            server_default="unconfigured",
        ),
    )
    op.create_check_constraint(
        "ck_ai_control_state_key_binding",
        "ai_control_state",
        "(key_name IS NULL AND key_version IS NULL AND key_reference IS NULL AND "
        "key_fingerprint IS NULL AND verified_at IS NULL AND "
        "key_validation_state = 'unconfigured') OR "
        "(key_name IS NOT NULL AND length(key_name) BETWEEN 1 AND 127 AND "
        "key_version IS NOT NULL AND length(key_version) BETWEEN 1 AND 255 AND "
        "key_reference = key_name || '/' || key_version AND "
        "key_fingerprint ~ '^[0-9a-f]{64}$' AND verified_at IS NOT NULL AND "
        "key_validation_state = 'verified')",
    )
    op.create_check_constraint(
        "ck_ai_control_state_enabled_requires_verified_key",
        "ai_control_state",
        "(operator_enabled = FALSE AND demo_enabled = FALSE) OR "
        "(key_name IS NOT NULL AND key_version IS NOT NULL AND "
        "key_reference = key_name || '/' || key_version AND "
        "key_fingerprint ~ '^[0-9a-f]{64}$' AND verified_at IS NOT NULL AND "
        "key_validation_state = 'verified')",
    )

    op.add_column(
        "admin_audit_events",
        sa.Column("requested_operator_enabled", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "admin_audit_events",
        sa.Column("requested_demo_enabled", sa.Boolean(), nullable=True),
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM admin_audit_events AS event
                JOIN operator_accounts AS operator
                  ON operator.id = event.operator_id
                WHERE operator.workspace_id <> event.workspace_id
            ) THEN
                RAISE EXCEPTION 'admin_audit_operator_workspace_mismatch';
            END IF;
        END;
        $$
        """
    )
    op.create_unique_constraint(
        "uq_operator_accounts_workspace_id",
        "operator_accounts",
        ["workspace_id", "id"],
    )
    op.drop_constraint(
        "admin_audit_events_operator_id_fkey",
        "admin_audit_events",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_admin_audit_events_workspace_operator",
        "admin_audit_events",
        "operator_accounts",
        ["workspace_id", "operator_id"],
        ["workspace_id", "id"],
        ondelete="RESTRICT",
    )
    op.execute(
        """
        CREATE FUNCTION prevent_admin_audit_event_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'immutable_admin_audit_event';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER admin_audit_events_immutable BEFORE UPDATE OR DELETE "
        "ON admin_audit_events FOR EACH ROW EXECUTE FUNCTION "
        "prevent_admin_audit_event_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS admin_audit_events_immutable ON admin_audit_events"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_admin_audit_event_mutation()")
    op.drop_constraint(
        "fk_admin_audit_events_workspace_operator",
        "admin_audit_events",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "admin_audit_events_operator_id_fkey",
        "admin_audit_events",
        "operator_accounts",
        ["operator_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_operator_accounts_workspace_id",
        "operator_accounts",
        type_="unique",
    )
    op.drop_column("admin_audit_events", "requested_demo_enabled")
    op.drop_column("admin_audit_events", "requested_operator_enabled")

    op.drop_constraint(
        "ck_ai_control_state_enabled_requires_verified_key",
        "ai_control_state",
        type_="check",
    )
    op.drop_constraint(
        "ck_ai_control_state_key_binding",
        "ai_control_state",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_control_state_key_binding",
        "ai_control_state",
        "(key_version IS NULL AND key_fingerprint IS NULL AND verified_at IS NULL) OR "
        "(key_version IS NOT NULL AND key_fingerprint ~ '^[0-9a-f]{64}$' AND "
        "verified_at IS NOT NULL)",
    )
    op.drop_column("ai_control_state", "key_validation_state")
    op.drop_column("ai_control_state", "key_reference")
    op.drop_column("ai_control_state", "key_name")
