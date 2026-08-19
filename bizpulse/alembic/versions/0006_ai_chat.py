"""Create evidence-constrained Ask BizPulse persistence."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_ai_chat"
down_revision: str | None = "0005_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_chat_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_kind", sa.Text(), nullable=False),
        sa.Column("operator_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("demo_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("recommended_question_id", sa.Text(), nullable=True),
        sa.Column("question_digest", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("scope", postgresql.JSONB(), nullable=False),
        sa.Column("plan_schema_version", sa.Text(), nullable=False),
        sa.Column("output_schema_version", sa.Text(), nullable=False),
        sa.Column("idempotency_key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=True),
        sa.Column("result_hash", sa.Text(), nullable=True),
        sa.Column(
            "answer_projection",
            postgresql.JSONB(none_as_null=True),
            nullable=True,
        ),
        sa.Column("safe_summary", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("action_draft_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "action_draft_projection",
            postgresql.JSONB(none_as_null=True),
            nullable=True,
        ),
        sa.Column("action_draft_key_hash", sa.LargeBinary(), nullable=True),
        sa.Column("action_draft_request_hash", sa.LargeBinary(), nullable=True),
        sa.Column("action_draft_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "dataset_version_id"],
            ["dataset_versions.workspace_id", "dataset_versions.id"],
            name="fk_ai_chat_turns_workspace_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["operator_session_id"],
            ["operator_sessions.id"],
            name="fk_ai_chat_turns_operator_session",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["demo_session_id"],
            ["demo_sessions.id"],
            name="fk_ai_chat_turns_demo_session",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "actor_kind IN ('operator', 'demo')",
            name="ck_ai_chat_turns_actor_kind",
        ),
        sa.CheckConstraint(
            "(actor_kind = 'operator' AND operator_session_id IS NOT NULL "
            "AND demo_session_id IS NULL) OR "
            "(actor_kind = 'demo' AND demo_session_id IS NOT NULL "
            "AND operator_session_id IS NULL)",
            name="ck_ai_chat_turns_actor_session",
        ),
        sa.CheckConstraint(
            "(question IS NOT NULL AND recommended_question_id IS NULL) OR "
            "(question IS NULL AND recommended_question_id IS NOT NULL)",
            name="ck_ai_chat_turns_question_choice",
        ),
        sa.CheckConstraint(
            "(question IS NULL OR length(question) BETWEEN 1 AND 2000) AND "
            "(recommended_question_id IS NULL OR "
            "length(recommended_question_id) BETWEEN 1 AND 100)",
            name="ck_ai_chat_turns_question_bounds",
        ),
        sa.CheckConstraint(
            "question_digest ~ '^[0-9a-f]{64}$'",
            name="ck_ai_chat_turns_question_digest",
        ),
        sa.CheckConstraint(
            "status IN ('planning','querying','answering','answered',"
            "'clarification_required','unsupported','failed','outcome_unknown')",
            name="ck_ai_chat_turns_status",
        ),
        sa.CheckConstraint(
            "tool_name IS NULL OR tool_name IN ("
            "'metric_lookup','trend_compare','sku_rank','profit_bridge_explain',"
            "'inventory_risk_lookup','forecast_lookup','data_quality_lookup',"
            "'action_card_lookup')",
            name="ck_ai_chat_turns_tool",
        ),
        sa.CheckConstraint(
            "result_hash IS NULL OR result_hash ~ '^[0-9a-f]{64}$'",
            name="ck_ai_chat_turns_result_hash",
        ),
        sa.CheckConstraint(
            "plan_schema_version = 'query-plan.v1' AND "
            "output_schema_version = 'chat-answer.v1' AND "
            "octet_length(idempotency_key_hash) = 32 AND "
            "octet_length(request_hash) = 32 AND "
            "jsonb_typeof(scope) = 'object' AND pg_column_size(scope) <= 8192 AND "
            "(answer_projection IS NULL OR "
            "(jsonb_typeof(answer_projection) = 'object' AND "
            "pg_column_size(answer_projection) <= 65536)) AND "
            "(action_draft_projection IS NULL OR "
            "(jsonb_typeof(action_draft_projection) = 'object' AND "
            "pg_column_size(action_draft_projection) <= 32768)) AND "
            "(safe_summary IS NULL OR length(safe_summary) <= 1000) AND "
            "(error_code IS NULL OR length(error_code) <= 100)",
            name="ck_ai_chat_turns_bounded_authority",
        ),
        sa.CheckConstraint(
            "(status IN ('planning','querying','answering') AND completed_at IS NULL "
            "AND lease_expires_at IS NOT NULL AND lease_expires_at > updated_at) OR "
            "(status IN ('answered','clarification_required','unsupported','failed',"
            "'outcome_unknown') AND completed_at IS NOT NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_ai_chat_turns_completion",
        ),
        sa.CheckConstraint(
            "(action_draft_id IS NULL AND action_draft_projection IS NULL "
            "AND action_draft_key_hash IS NULL AND action_draft_request_hash IS NULL "
            "AND action_draft_created_at IS NULL) OR "
            "(status = 'answered' AND action_draft_id IS NOT NULL "
            "AND action_draft_projection IS NOT NULL "
            "AND action_draft_key_hash IS NOT NULL "
            "AND action_draft_request_hash IS NOT NULL "
            "AND action_draft_created_at IS NOT NULL)",
            name="ck_ai_chat_turns_action_draft",
        ),
    )
    op.create_index(
        "uq_ai_chat_turns_operator_idempotency",
        "ai_chat_turns",
        ["operator_session_id", "idempotency_key_hash"],
        unique=True,
        postgresql_where=sa.text("actor_kind = 'operator'"),
    )
    op.create_index(
        "uq_ai_chat_turns_demo_idempotency",
        "ai_chat_turns",
        ["demo_session_id", "idempotency_key_hash"],
        unique=True,
        postgresql_where=sa.text("actor_kind = 'demo'"),
    )
    op.create_index(
        "uq_ai_chat_turns_operator_inflight",
        "ai_chat_turns",
        ["operator_session_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('planning','querying','answering')"),
    )
    op.create_index(
        "uq_ai_chat_turns_demo_inflight",
        "ai_chat_turns",
        ["demo_session_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('planning','querying','answering')"),
    )
    op.create_index(
        "ix_ai_chat_turns_session_created",
        "ai_chat_turns",
        ["actor_kind", "operator_session_id", "demo_session_id", "created_at"],
    )

    op.create_table(
        "ai_chat_tool_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "turn_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_chat_turns.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=False),
        sa.Column(
            "result_summary",
            postgresql.JSONB(none_as_null=True),
            nullable=True,
        ),
        sa.Column("result_hash", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "tool_name IN ('metric_lookup','trend_compare','sku_rank',"
            "'profit_bridge_explain','inventory_risk_lookup','forecast_lookup',"
            "'data_quality_lookup','action_card_lookup')",
            name="ck_ai_chat_tool_runs_tool",
        ),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed','timeout')",
            name="ck_ai_chat_tool_runs_status",
        ),
        sa.CheckConstraint(
            "result_hash IS NULL OR result_hash ~ '^[0-9a-f]{64}$'",
            name="ck_ai_chat_tool_runs_hash",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(arguments) = 'object' AND "
            "pg_column_size(arguments) <= 8192 AND "
            "(result_summary IS NULL OR "
            "(jsonb_typeof(result_summary) = 'object' AND "
            "pg_column_size(result_summary) <= 65536)) AND "
            "(error_code IS NULL OR length(error_code) <= 100) AND "
            "((status = 'succeeded' AND result_summary IS NOT NULL "
            "AND result_hash IS NOT NULL AND completed_at IS NOT NULL) OR "
            "(status IN ('failed','timeout') AND result_summary IS NULL "
            "AND result_hash IS NULL AND completed_at IS NOT NULL) OR "
            "(status = 'running' AND result_summary IS NULL "
            "AND result_hash IS NULL AND completed_at IS NULL))",
            name="ck_ai_chat_tool_runs_bounded_result",
        ),
    )

    op.create_table(
        "ai_chat_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "turn_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_chat_turns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fact_ref", sa.Text(), nullable=False),
        sa.Column("analysis_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_alias", sa.Text(), nullable=False),
        sa.Column("evidence_state", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            name="fk_ai_chat_evidence_analysis",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "fact_ref ~ '^fact-[0-9]{3}$'",
            name="ck_ai_chat_evidence_fact_ref",
        ),
        sa.CheckConstraint(
            "evidence_state IN ('measured','derived','assumed','unknown')",
            name="ck_ai_chat_evidence_state",
        ),
        sa.CheckConstraint(
            "length(evidence_alias) BETWEEN 1 AND 500 AND "
            "length(source_ref) BETWEEN 1 AND 1000",
            name="ck_ai_chat_evidence_bounds",
        ),
        sa.UniqueConstraint("turn_id", "fact_ref", name="uq_ai_chat_evidence_fact"),
    )

    op.create_table(
        "ai_chat_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "turn_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_chat_turns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("reasoning_effort", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "stage IN ('planning','answering')",
            name="ck_ai_chat_attempts_stage",
        ),
        sa.CheckConstraint(
            "model = 'gpt-5.4-mini-2026-03-17'",
            name="ck_ai_chat_attempts_model",
        ),
        sa.CheckConstraint(
            "reasoning_effort = 'low'",
            name="ck_ai_chat_attempts_effort",
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND reserved_tokens > 0 "
            "AND input_tokens + output_tokens <= reserved_tokens",
            name="ck_ai_chat_attempts_tokens",
        ),
        sa.CheckConstraint(
            "status IN ('started','succeeded','failed','outcome_unknown')",
            name="ck_ai_chat_attempts_status",
        ),
        sa.CheckConstraint(
            "(error_code IS NULL OR length(error_code) <= 100) AND "
            "((status = 'started' AND completed_at IS NULL) OR "
            "(status IN ('succeeded','failed','outcome_unknown') "
            "AND completed_at IS NOT NULL))",
            name="ck_ai_chat_attempts_completion",
        ),
        sa.UniqueConstraint("turn_id", "stage", name="uq_ai_chat_attempts_stage"),
    )

    op.create_table(
        "ai_chat_saved_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "turn_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_chat_turns.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "operator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operator_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("answer_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "answer_hash ~ '^[0-9a-f]{64}$'",
            name="ck_ai_chat_saved_records_hash",
        ),
    )

    op.create_foreign_key(
        "fk_action_card_revisions_chat_turn",
        "action_card_revisions",
        "ai_chat_turns",
        ["chat_turn_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.execute(
        """
        CREATE FUNCTION protect_ai_chat_turn() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
               OR NEW.dataset_version_id IS DISTINCT FROM OLD.dataset_version_id
               OR NEW.actor_kind IS DISTINCT FROM OLD.actor_kind
               OR NEW.operator_session_id IS DISTINCT FROM OLD.operator_session_id
               OR NEW.demo_session_id IS DISTINCT FROM OLD.demo_session_id
               OR NEW.question IS DISTINCT FROM OLD.question
               OR NEW.recommended_question_id IS DISTINCT FROM OLD.recommended_question_id
               OR NEW.question_digest IS DISTINCT FROM OLD.question_digest
               OR NEW.scope IS DISTINCT FROM OLD.scope
               OR NEW.plan_schema_version IS DISTINCT FROM OLD.plan_schema_version
               OR NEW.output_schema_version IS DISTINCT FROM OLD.output_schema_version
               OR NEW.idempotency_key_hash IS DISTINCT FROM OLD.idempotency_key_hash
               OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'immutable_ai_chat_authority';
            END IF;
            IF OLD.status = 'answered' AND NEW.status = 'answered'
               AND OLD.action_draft_id IS NULL AND NEW.action_draft_id IS NOT NULL
               AND OLD.action_draft_projection IS NULL
               AND NEW.action_draft_projection IS NOT NULL
               AND OLD.action_draft_key_hash IS NULL
               AND NEW.action_draft_key_hash IS NOT NULL
               AND OLD.action_draft_request_hash IS NULL
               AND NEW.action_draft_request_hash IS NOT NULL
               AND OLD.action_draft_created_at IS NULL
               AND NEW.action_draft_created_at IS NOT NULL
               AND NEW.tool_name IS NOT DISTINCT FROM OLD.tool_name
               AND NEW.result_hash IS NOT DISTINCT FROM OLD.result_hash
               AND NEW.answer_projection IS NOT DISTINCT FROM OLD.answer_projection
               AND NEW.safe_summary IS NOT DISTINCT FROM OLD.safe_summary
               AND NEW.error_code IS NOT DISTINCT FROM OLD.error_code
               AND NEW.lease_expires_at IS NOT DISTINCT FROM OLD.lease_expires_at
               AND NEW.updated_at >= OLD.updated_at
               AND NEW.completed_at IS NOT DISTINCT FROM OLD.completed_at THEN
                RETURN NEW;
            END IF;
            IF OLD.status IN ('answered','clarification_required','unsupported','failed','outcome_unknown') THEN
                RAISE EXCEPTION 'immutable_ai_chat_terminal';
            END IF;
            IF NOT (
                (OLD.status = 'planning' AND NEW.status IN ('querying','clarification_required','unsupported','failed','outcome_unknown')) OR
                (OLD.status = 'querying' AND NEW.status IN ('answering','clarification_required','failed','outcome_unknown')) OR
                (OLD.status = 'answering' AND NEW.status IN ('answered','clarification_required','failed','outcome_unknown'))
            ) THEN
                RAISE EXCEPTION 'invalid_ai_chat_transition';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER ai_chat_turns_protected BEFORE UPDATE ON ai_chat_turns "
        "FOR EACH ROW EXECUTE FUNCTION protect_ai_chat_turn()"
    )
    op.execute(
        """
        CREATE FUNCTION protect_ai_chat_attempt() RETURNS trigger AS $$
        BEGIN
            IF OLD.status <> 'started' THEN
                RAISE EXCEPTION 'immutable_ai_chat_attempt';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.turn_id IS DISTINCT FROM OLD.turn_id
               OR NEW.stage IS DISTINCT FROM OLD.stage
               OR NEW.model IS DISTINCT FROM OLD.model
               OR NEW.reasoning_effort IS DISTINCT FROM OLD.reasoning_effort
               OR NEW.reserved_tokens IS DISTINCT FROM OLD.reserved_tokens
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.status NOT IN ('succeeded','failed','outcome_unknown')
               OR NEW.completed_at IS NULL THEN
                RAISE EXCEPTION 'invalid_ai_chat_attempt_transition';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER ai_chat_attempts_protected BEFORE UPDATE ON ai_chat_attempts "
        "FOR EACH ROW EXECUTE FUNCTION protect_ai_chat_attempt()"
    )
    op.execute(
        """
        CREATE FUNCTION enforce_ai_chat_child_insert() RETURNS trigger AS $$
        DECLARE
            parent_status text;
        BEGIN
            SELECT status INTO parent_status
            FROM ai_chat_turns
            WHERE id = NEW.turn_id
            FOR KEY SHARE;
            IF parent_status IS NULL THEN
                RAISE EXCEPTION 'ai_chat_parent_missing';
            END IF;
            IF TG_TABLE_NAME = 'ai_chat_attempts' THEN
                IF NOT (
                    (NEW.stage = 'planning' AND parent_status = 'planning') OR
                    (NEW.stage = 'answering' AND parent_status = 'answering')
                ) THEN
                    RAISE EXCEPTION 'invalid_ai_chat_attempt_parent_state';
                END IF;
            ELSIF TG_TABLE_NAME = 'ai_chat_tool_runs' THEN
                IF parent_status <> 'querying' THEN
                    RAISE EXCEPTION 'invalid_ai_chat_tool_parent_state';
                END IF;
            ELSIF TG_TABLE_NAME = 'ai_chat_evidence' THEN
                IF parent_status <> 'answering' THEN
                    RAISE EXCEPTION 'invalid_ai_chat_evidence_parent_state';
                END IF;
            ELSIF TG_TABLE_NAME = 'ai_chat_saved_records' THEN
                IF parent_status <> 'answered' THEN
                    RAISE EXCEPTION 'invalid_ai_chat_saved_parent_state';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in (
        "ai_chat_attempts",
        "ai_chat_tool_runs",
        "ai_chat_evidence",
        "ai_chat_saved_records",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_insert_guard BEFORE INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION enforce_ai_chat_child_insert()"
        )
    op.execute(
        """
        CREATE FUNCTION prevent_ai_chat_child_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'immutable_ai_chat_record';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("ai_chat_tool_runs", "ai_chat_evidence", "ai_chat_saved_records"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION prevent_ai_chat_child_update()"
        )


def downgrade() -> None:
    op.drop_constraint(
        "fk_action_card_revisions_chat_turn",
        "action_card_revisions",
        type_="foreignkey",
    )
    for table in ("ai_chat_saved_records", "ai_chat_evidence", "ai_chat_tool_runs"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS prevent_ai_chat_child_update()")
    for table in (
        "ai_chat_saved_records",
        "ai_chat_evidence",
        "ai_chat_tool_runs",
        "ai_chat_attempts",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_insert_guard ON {table}")
    op.execute("DROP FUNCTION IF EXISTS enforce_ai_chat_child_insert()")
    op.execute("DROP TRIGGER IF EXISTS ai_chat_attempts_protected ON ai_chat_attempts")
    op.execute("DROP FUNCTION IF EXISTS protect_ai_chat_attempt()")
    op.execute("DROP TRIGGER IF EXISTS ai_chat_turns_protected ON ai_chat_turns")
    op.execute("DROP FUNCTION IF EXISTS protect_ai_chat_turn()")
    op.drop_table("ai_chat_saved_records")
    op.drop_table("ai_chat_attempts")
    op.drop_table("ai_chat_evidence")
    op.drop_table("ai_chat_tool_runs")
    op.drop_index("ix_ai_chat_turns_session_created", table_name="ai_chat_turns")
    op.drop_index("uq_ai_chat_turns_demo_inflight", table_name="ai_chat_turns")
    op.drop_index("uq_ai_chat_turns_operator_inflight", table_name="ai_chat_turns")
    op.drop_index("uq_ai_chat_turns_demo_idempotency", table_name="ai_chat_turns")
    op.drop_index("uq_ai_chat_turns_operator_idempotency", table_name="ai_chat_turns")
    op.drop_table("ai_chat_turns")
