"""Record actual prompt text and complete preset audit metadata."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_prompt_preset_audit"
down_revision: str | None = "0008_ai_budget_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_chat_turns", sa.Column("prompt_locale", sa.Text()))
    op.add_column(
        "ai_chat_turns",
        sa.Column("prompt_template_version", sa.Text()),
    )
    op.add_column(
        "ai_chat_turns",
        sa.Column("prompt_template_sha256", sa.Text()),
    )
    op.add_column(
        "ai_chat_turns",
        sa.Column(
            "prompt_audit_state",
            sa.Text(),
            nullable=False,
            server_default="legacy_unrecorded",
        ),
    )
    op.drop_constraint(
        "ck_ai_chat_turns_question_choice",
        "ai_chat_turns",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_chat_turns_question_choice",
        "ai_chat_turns",
        "(prompt_audit_state = 'recorded' AND question IS NOT NULL AND "
        "((recommended_question_id IS NULL AND prompt_locale IS NULL AND "
        "prompt_template_version IS NULL AND prompt_template_sha256 IS NULL) OR "
        "(recommended_question_id IS NOT NULL AND prompt_locale IS NOT NULL AND "
        "prompt_template_version IS NOT NULL AND prompt_template_sha256 IS NOT NULL))) "
        "OR (prompt_audit_state = 'legacy_unrecorded' AND "
        "prompt_locale IS NULL AND prompt_template_version IS NULL AND "
        "prompt_template_sha256 IS NULL AND "
        "((question IS NOT NULL AND recommended_question_id IS NULL) OR "
        "(question IS NULL AND recommended_question_id IS NOT NULL)))",
    )
    op.create_check_constraint(
        "ck_ai_chat_turns_prompt_audit",
        "ai_chat_turns",
        "prompt_audit_state IN ('recorded','legacy_unrecorded') AND "
        "(prompt_locale IS NULL OR prompt_locale IN ('en','zh')) AND "
        "(prompt_template_version IS NULL OR "
        "length(prompt_template_version) BETWEEN 1 AND 100) AND "
        "(prompt_template_sha256 IS NULL OR "
        "prompt_template_sha256 ~ '^[0-9a-f]{64}$')",
    )
    op.drop_constraint(
        "ck_ai_chat_turns_tool",
        "ai_chat_turns",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_chat_turns_tool",
        "ai_chat_turns",
        "tool_name IS NULL OR tool_name IN ("
        "'metric_lookup','trend_compare','sku_rank','profit_bridge_explain',"
        "'inventory_risk_lookup','forecast_lookup','data_quality_lookup',"
        "'action_card_lookup','monthly_sales_report_lookup')",
    )
    op.drop_constraint(
        "ck_ai_chat_tool_runs_tool",
        "ai_chat_tool_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_chat_tool_runs_tool",
        "ai_chat_tool_runs",
        "tool_name IN ('metric_lookup','trend_compare','sku_rank',"
        "'profit_bridge_explain','inventory_risk_lookup','forecast_lookup',"
        "'data_quality_lookup','action_card_lookup',"
        "'monthly_sales_report_lookup')",
    )
    op.execute(
        """
        CREATE FUNCTION protect_ai_chat_prompt_audit() RETURNS trigger AS $$
        BEGIN
            IF NEW.prompt_locale IS DISTINCT FROM OLD.prompt_locale
               OR NEW.prompt_template_version IS DISTINCT FROM OLD.prompt_template_version
               OR NEW.prompt_template_sha256 IS DISTINCT FROM OLD.prompt_template_sha256
               OR NEW.prompt_audit_state IS DISTINCT FROM OLD.prompt_audit_state THEN
                RAISE EXCEPTION 'immutable_ai_chat_prompt_audit';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER ai_chat_prompt_audit_immutable "
        "BEFORE UPDATE ON ai_chat_turns FOR EACH ROW "
        "EXECUTE FUNCTION protect_ai_chat_prompt_audit()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS ai_chat_prompt_audit_immutable ON ai_chat_turns"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_ai_chat_prompt_audit()")
    op.drop_constraint(
        "ck_ai_chat_tool_runs_tool",
        "ai_chat_tool_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_chat_tool_runs_tool",
        "ai_chat_tool_runs",
        "tool_name IN ('metric_lookup','trend_compare','sku_rank',"
        "'profit_bridge_explain','inventory_risk_lookup','forecast_lookup',"
        "'data_quality_lookup','action_card_lookup')",
    )
    op.drop_constraint(
        "ck_ai_chat_turns_tool",
        "ai_chat_turns",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_chat_turns_tool",
        "ai_chat_turns",
        "tool_name IS NULL OR tool_name IN ("
        "'metric_lookup','trend_compare','sku_rank','profit_bridge_explain',"
        "'inventory_risk_lookup','forecast_lookup','data_quality_lookup',"
        "'action_card_lookup')",
    )
    op.drop_constraint(
        "ck_ai_chat_turns_prompt_audit",
        "ai_chat_turns",
        type_="check",
    )
    op.drop_constraint(
        "ck_ai_chat_turns_question_choice",
        "ai_chat_turns",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_chat_turns_question_choice",
        "ai_chat_turns",
        "(question IS NOT NULL AND recommended_question_id IS NULL) OR "
        "(question IS NULL AND recommended_question_id IS NOT NULL)",
    )
    op.drop_column("ai_chat_turns", "prompt_audit_state")
    op.drop_column("ai_chat_turns", "prompt_template_sha256")
    op.drop_column("ai_chat_turns", "prompt_template_version")
    op.drop_column("ai_chat_turns", "prompt_locale")
