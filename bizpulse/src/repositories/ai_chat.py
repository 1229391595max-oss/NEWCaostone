"""PostgreSQL authority for bounded Ask BizPulse turns and evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Connection, case, delete, exists, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.ai.contracts import ChatAnswer, ChatTurn, QueryPlan, ToolResult
from src.config import APPROVED_OPENAI_MODEL, APPROVED_REASONING_EFFORT
from src.db.schema import (
    ai_budget_ledger,
    ai_chat_attempts,
    ai_chat_evidence,
    ai_chat_saved_records,
    ai_chat_tool_runs,
    ai_chat_turns,
)


@dataclass(frozen=True, slots=True)
class ToolRunProjection:
    id: UUID
    turn_id: UUID
    tool_name: str
    arguments: dict[str, object]
    result_summary: dict[str, object] | None
    result_hash: str | None
    status: str
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ChatEvidenceProjection:
    id: UUID
    turn_id: UUID
    fact_ref: str
    analysis_run_id: UUID | None
    evidence_alias: str
    evidence_state: str
    source_ref: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AttemptProjection:
    id: UUID
    turn_id: UUID
    stage: str
    model: str
    reasoning_effort: str
    input_tokens: int
    output_tokens: int
    reserved_tokens: int
    status: str
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class CredentialBindingAuditProjection:
    turn_id: UUID
    actor_kind: str
    request_id: str
    credential_binding_id: str
    credential_control_revision: int
    status: str


class AIChatRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def lock_session(self, actor_kind: str, session_id: UUID) -> None:
        self._connection.exec_driver_sql(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"ai-chat:{actor_kind}:{session_id}",),
        )

    def lock_budget(self) -> None:
        self._connection.exec_driver_sql(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            ("ai-chat:global-budget",),
        )

    def active_turn_count(self) -> int:
        value = self._connection.scalar(
            select(func.count())
            .select_from(ai_chat_turns)
            .where(ai_chat_turns.c.status.in_(("planning", "querying", "answering")))
        )
        return int(value or 0)

    def safe_history(
        self,
        actor_kind: str,
        session_id: UUID,
        dataset_version_id: UUID,
        store_ids: tuple[str, ...],
        *,
        limit: int = 4,
    ) -> tuple[str, ...]:
        session_column = (
            ai_chat_turns.c.operator_session_id
            if actor_kind == "operator"
            else ai_chat_turns.c.demo_session_id
        )
        rows = tuple(
            self._connection.scalars(
                select(ai_chat_turns.c.safe_summary)
                .where(
                    ai_chat_turns.c.actor_kind == actor_kind,
                    session_column == session_id,
                    ai_chat_turns.c.dataset_version_id == dataset_version_id,
                    ai_chat_turns.c.scope["store_ids"] == list(store_ids),
                    ai_chat_turns.c.safe_summary.is_not(None),
                    ai_chat_turns.c.status.in_(
                        (
                            "answered",
                            "clarification_required",
                            "unsupported",
                            "failed",
                            "outcome_unknown",
                        )
                    ),
                )
                .order_by(ai_chat_turns.c.turn_sequence.desc())
                .limit(limit)
            )
        )
        return tuple(reversed(rows))

    def save_answer(
        self,
        *,
        turn_id: UUID,
        operator_id: UUID,
        answer_hash: str,
        now: datetime,
    ) -> bool:
        self._connection.execute(
            pg_insert(ai_chat_saved_records)
            .values(
                id=uuid4(),
                turn_id=turn_id,
                operator_id=operator_id,
                answer_hash=answer_hash,
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=[ai_chat_saved_records.c.turn_id])
        )
        row = self._connection.execute(
            select(
                ai_chat_saved_records.c.operator_id,
                ai_chat_saved_records.c.answer_hash,
            ).where(ai_chat_saved_records.c.turn_id == turn_id)
        ).one_or_none()
        return row == (operator_id, answer_hash)

    def saved_ids(self, turn_ids: tuple[UUID, ...]) -> frozenset[UUID]:
        if not turn_ids:
            return frozenset()
        return frozenset(
            self._connection.scalars(
                select(ai_chat_saved_records.c.turn_id).where(
                    ai_chat_saved_records.c.turn_id.in_(turn_ids)
                )
            )
        )

    def list_saved_for_operator(
        self,
        operator_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[tuple[ChatTurn, str], ...]:
        rows = self._connection.execute(
            select(
                *ai_chat_turns.c,
                ai_chat_saved_records.c.answer_hash.label("saved_answer_hash"),
            )
            .join(
                ai_chat_saved_records,
                ai_chat_saved_records.c.turn_id == ai_chat_turns.c.id,
            )
            .where(ai_chat_saved_records.c.operator_id == operator_id)
            .order_by(ai_chat_saved_records.c.created_at.desc())
            .limit(limit)
        ).mappings()
        return tuple((_turn(row), str(row["saved_answer_hash"])) for row in rows)

    def recover_stale(self, now: datetime) -> int:
        stale_turn = exists(
            select(ai_chat_turns.c.id).where(
                ai_chat_turns.c.id == ai_chat_attempts.c.turn_id,
                ai_chat_turns.c.status.in_(("planning", "querying", "answering")),
                ai_chat_turns.c.lease_expires_at <= now,
            )
        )
        self._connection.execute(
            update(ai_chat_attempts)
            .where(
                ai_chat_attempts.c.status == "started",
                stale_turn,
            )
            .values(
                status="outcome_unknown",
                error_code="provider_outcome_unknown",
                completed_at=now,
            )
        )
        provider_outcome_unknown = exists(
            select(ai_chat_attempts.c.id).where(
                ai_chat_attempts.c.turn_id == ai_chat_turns.c.id,
                ai_chat_attempts.c.status == "outcome_unknown",
            )
        )
        result = self._connection.execute(
            update(ai_chat_turns)
            .where(
                ai_chat_turns.c.status.in_(("planning", "querying", "answering")),
                ai_chat_turns.c.lease_expires_at <= now,
            )
            .values(
                status=case(
                    (provider_outcome_unknown, "outcome_unknown"),
                    else_="failed",
                ),
                safe_summary=case(
                    (
                        provider_outcome_unknown,
                        "The interrupted provider outcome is unknown; deterministic "
                        "pages remain available.",
                    ),
                    else_=(
                        "The interrupted AI request expired; deterministic pages "
                        "remain available."
                    ),
                ),
                error_code=case(
                    (provider_outcome_unknown, "provider_outcome_unknown"),
                    else_="turn_lease_expired",
                ),
                updated_at=now,
                lease_expires_at=None,
                completed_at=now,
            )
        )
        return int(result.rowcount)

    def attempt_usage(self, *, since: datetime) -> tuple[int, int]:
        charged_tokens = case(
            (
                ai_budget_ledger.c.status == "succeeded",
                ai_budget_ledger.c.input_tokens + ai_budget_ledger.c.output_tokens,
            ),
            else_=ai_budget_ledger.c.reserved_tokens,
        )
        row = self._connection.execute(
            select(
                func.count(ai_budget_ledger.c.attempt_id),
                func.coalesce(func.sum(charged_tokens), 0),
            ).where(ai_budget_ledger.c.created_at >= since)
        ).one()
        return int(row[0]), int(row[1])

    def turn_token_usage(self, turn_id: UUID) -> tuple[int, int]:
        row = self._connection.execute(
            select(
                func.coalesce(func.sum(ai_chat_attempts.c.input_tokens), 0),
                func.coalesce(func.sum(ai_chat_attempts.c.output_tokens), 0),
            ).where(ai_chat_attempts.c.turn_id == turn_id)
        ).one()
        return int(row[0]), int(row[1])

    def turn_attempt_audit(
        self,
        turn_id: UUID,
    ) -> tuple[tuple[AttemptProjection, ...], int, int]:
        """Return value-free attempt and synchronized ledger evidence for one turn."""

        attempts = tuple(
            AttemptProjection(**row)
            for row in self._connection.execute(
                select(*ai_chat_attempts.c)
                .where(ai_chat_attempts.c.turn_id == turn_id)
                .order_by(ai_chat_attempts.c.created_at, ai_chat_attempts.c.id)
            )
            .mappings()
        )
        ledger = self._connection.execute(
            select(
                func.count(ai_budget_ledger.c.attempt_id),
                func.coalesce(func.sum(ai_budget_ledger.c.reserved_tokens), 0),
            )
            .select_from(
                ai_budget_ledger.join(
                    ai_chat_attempts,
                    ai_budget_ledger.c.attempt_id == ai_chat_attempts.c.id,
                )
            )
            .where(ai_chat_attempts.c.turn_id == turn_id)
        ).one()
        return attempts, int(ledger[0]), int(ledger[1])

    def session_attempt_count(self, turn_id: UUID, *, since: datetime) -> int:
        target = ai_chat_turns.alias("target_chat_turn")
        candidate = ai_chat_turns.alias("candidate_chat_turn")
        value = self._connection.scalar(
            select(func.count(ai_chat_attempts.c.id))
            .select_from(
                ai_chat_attempts.join(
                    candidate,
                    ai_chat_attempts.c.turn_id == candidate.c.id,
                ).join(target, target.c.id == turn_id)
            )
            .where(
                ai_chat_attempts.c.created_at >= since,
                candidate.c.actor_kind == target.c.actor_kind,
                func.coalesce(
                    candidate.c.operator_session_id,
                    candidate.c.demo_session_id,
                )
                == func.coalesce(
                    target.c.operator_session_id,
                    target.c.demo_session_id,
                ),
            )
        )
        return int(value or 0)

    def find_by_key(
        self,
        actor_kind: str,
        session_id: UUID,
        key_hash: bytes,
    ) -> ChatTurn | None:
        session_column = (
            ai_chat_turns.c.operator_session_id
            if actor_kind == "operator"
            else ai_chat_turns.c.demo_session_id
        )
        row = (
            self._connection.execute(
                select(*ai_chat_turns.c).where(
                    ai_chat_turns.c.actor_kind == actor_kind,
                    session_column == session_id,
                    ai_chat_turns.c.idempotency_key_hash == key_hash,
                )
            )
            .mappings()
            .one_or_none()
        )
        return _turn(row) if row is not None else None

    def request_hash(self, turn_id: UUID) -> bytes | None:
        value = self._connection.scalar(
            select(ai_chat_turns.c.request_hash).where(ai_chat_turns.c.id == turn_id)
        )
        return bytes(value) if value is not None else None

    def get_for_session(
        self,
        actor_kind: str,
        session_id: UUID,
        turn_id: UUID,
    ) -> ChatTurn | None:
        session_column = (
            ai_chat_turns.c.operator_session_id
            if actor_kind == "operator"
            else ai_chat_turns.c.demo_session_id
        )
        row = (
            self._connection.execute(
                select(*ai_chat_turns.c).where(
                    ai_chat_turns.c.id == turn_id,
                    ai_chat_turns.c.actor_kind == actor_kind,
                    session_column == session_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        return _turn(row) if row is not None else None

    def get(self, turn_id: UUID) -> ChatTurn | None:
        row = (
            self._connection.execute(
                select(*ai_chat_turns.c).where(ai_chat_turns.c.id == turn_id)
            )
            .mappings()
            .one_or_none()
        )
        return _turn(row) if row is not None else None

    def list_for_session(
        self,
        actor_kind: str,
        session_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[ChatTurn, ...]:
        session_column = (
            ai_chat_turns.c.operator_session_id
            if actor_kind == "operator"
            else ai_chat_turns.c.demo_session_id
        )
        rows = self._connection.execute(
            select(*ai_chat_turns.c)
            .where(
                ai_chat_turns.c.actor_kind == actor_kind,
                session_column == session_id,
            )
            .order_by(ai_chat_turns.c.turn_sequence)
            .limit(limit)
        ).mappings()
        return tuple(_turn(row) for row in rows)

    def insert_turn(
        self,
        *,
        turn_id: UUID,
        workspace_id: str,
        dataset_version_id: UUID,
        actor_kind: str,
        session_id: UUID,
        question: str | None,
        recommended_question_id: str | None,
        prompt_locale: str | None,
        prompt_template_version: str | None,
        prompt_template_sha256: str | None,
        prompt_audit_state: str,
        question_digest: str,
        scope: dict[str, object],
        plan_schema_version: str,
        output_schema_version: str,
        key_hash: bytes,
        request_hash: bytes,
        now: datetime,
        lease_expires_at: datetime,
        credential_binding_id: str | None = None,
        credential_control_revision: int | None = None,
        credential_request_id: str | None = None,
    ) -> ChatTurn:
        session_column = (
            ai_chat_turns.c.operator_session_id
            if actor_kind == "operator"
            else ai_chat_turns.c.demo_session_id
        )
        turn_sequence = int(
            self._connection.scalar(
                select(
                    func.coalesce(func.max(ai_chat_turns.c.turn_sequence), 0) + 1
                ).where(
                    ai_chat_turns.c.actor_kind == actor_kind,
                    session_column == session_id,
                )
            )
            or 1
        )
        row = (
            self._connection.execute(
                insert(ai_chat_turns)
                .values(
                    id=turn_id,
                    turn_sequence=turn_sequence,
                    workspace_id=workspace_id,
                    dataset_version_id=dataset_version_id,
                    actor_kind=actor_kind,
                    operator_session_id=session_id
                    if actor_kind == "operator"
                    else None,
                    demo_session_id=session_id if actor_kind == "demo" else None,
                    question=question,
                    recommended_question_id=recommended_question_id,
                    prompt_locale=prompt_locale,
                    prompt_template_version=prompt_template_version,
                    prompt_template_sha256=prompt_template_sha256,
                    prompt_audit_state=prompt_audit_state,
                    question_digest=question_digest,
                    status="planning",
                    scope=scope,
                    plan_schema_version=plan_schema_version,
                    output_schema_version=output_schema_version,
                    idempotency_key_hash=key_hash,
                    request_hash=request_hash,
                    credential_binding_id=credential_binding_id,
                    credential_control_revision=credential_control_revision,
                    credential_request_id=credential_request_id,
                    tool_name=None,
                    result_hash=None,
                    answer_projection=None,
                    safe_summary=None,
                    error_code=None,
                    action_draft_id=None,
                    action_draft_projection=None,
                    action_draft_key_hash=None,
                    action_draft_request_hash=None,
                    action_draft_created_at=None,
                    created_at=now,
                    updated_at=now,
                    lease_expires_at=lease_expires_at,
                    completed_at=None,
                )
                .returning(*ai_chat_turns.c)
            )
            .mappings()
            .one()
        )
        return _turn(row)

    def credential_binding_audit(
        self,
        workspace_id: str,
        turn_ids: tuple[UUID, ...],
    ) -> tuple[CredentialBindingAuditProjection, ...]:
        """Return only non-secret immutable binding evidence for exact turns."""

        if not turn_ids:
            return ()
        rows = self._connection.execute(
            select(
                ai_chat_turns.c.id.label("turn_id"),
                ai_chat_turns.c.actor_kind,
                ai_chat_turns.c.credential_request_id.label("request_id"),
                ai_chat_turns.c.credential_binding_id,
                ai_chat_turns.c.credential_control_revision,
                ai_chat_turns.c.status,
            ).where(
                ai_chat_turns.c.workspace_id == workspace_id,
                ai_chat_turns.c.id.in_(turn_ids),
                ai_chat_turns.c.credential_binding_id.is_not(None),
                ai_chat_turns.c.credential_control_revision.is_not(None),
                ai_chat_turns.c.credential_request_id.is_not(None),
            )
        ).mappings()
        by_id = {
            row["turn_id"]: CredentialBindingAuditProjection(**row) for row in rows
        }
        return tuple(by_id[turn_id] for turn_id in turn_ids if turn_id in by_id)

    def transition(
        self,
        turn_id: UUID,
        *,
        expected_status: str,
        status: str,
        now: datetime,
        tool_name: str | None = None,
        result_hash: str | None = None,
        answer: ChatAnswer | None = None,
        safe_summary: str | None = None,
        error_code: str | None = None,
        lease_expires_at: datetime | None = None,
    ) -> ChatTurn | None:
        terminal = status in {
            "answered",
            "clarification_required",
            "unsupported",
            "failed",
            "outcome_unknown",
        }
        values: dict[str, object] = {
            "status": status,
            "updated_at": now,
            "lease_expires_at": None if terminal else lease_expires_at,
            "completed_at": now if terminal else None,
        }
        if tool_name is not None:
            values["tool_name"] = tool_name
        if result_hash is not None:
            values["result_hash"] = result_hash
        if answer is not None:
            values["answer_projection"] = answer.model_dump(mode="json")
        if safe_summary is not None:
            values["safe_summary"] = safe_summary
        if error_code is not None:
            values["error_code"] = error_code
        row = (
            self._connection.execute(
                update(ai_chat_turns)
                .where(
                    ai_chat_turns.c.id == turn_id,
                    ai_chat_turns.c.status == expected_status,
                )
                .values(**values)
                .returning(*ai_chat_turns.c)
            )
            .mappings()
            .one_or_none()
        )
        return _turn(row) if row is not None else None

    def add_attempt(
        self,
        turn_id: UUID,
        stage: str,
        now: datetime,
        reserved_tokens: int,
    ) -> UUID:
        attempt_id = uuid4()
        self._connection.execute(
            insert(ai_chat_attempts).values(
                id=attempt_id,
                turn_id=turn_id,
                stage=stage,
                model=APPROVED_OPENAI_MODEL,
                reasoning_effort=APPROVED_REASONING_EFFORT,
                input_tokens=0,
                output_tokens=0,
                reserved_tokens=reserved_tokens,
                status="started",
                error_code=None,
                created_at=now,
                completed_at=None,
            )
        )
        return attempt_id

    def finish_attempt(
        self,
        attempt_id: UUID,
        *,
        status: str,
        input_tokens: int,
        output_tokens: int,
        error_code: str | None,
        now: datetime,
    ) -> None:
        self._connection.execute(
            update(ai_chat_attempts)
            .where(
                ai_chat_attempts.c.id == attempt_id,
                ai_chat_attempts.c.status == "started",
            )
            .values(
                status=status,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                error_code=error_code,
                completed_at=now,
            )
        )

    def attempt(self, turn_id: UUID, stage: str) -> AttemptProjection | None:
        row = (
            self._connection.execute(
                select(*ai_chat_attempts.c).where(
                    ai_chat_attempts.c.turn_id == turn_id,
                    ai_chat_attempts.c.stage == stage,
                )
            )
            .mappings()
            .one_or_none()
        )
        return AttemptProjection(**row) if row is not None else None

    def attempt_by_id(self, attempt_id: UUID) -> AttemptProjection | None:
        row = (
            self._connection.execute(
                select(*ai_chat_attempts.c).where(ai_chat_attempts.c.id == attempt_id)
            )
            .mappings()
            .one_or_none()
        )
        return AttemptProjection(**row) if row is not None else None

    def add_tool_result(
        self,
        turn_id: UUID,
        plan: QueryPlan,
        result: ToolResult | None,
        *,
        status: str,
        error_code: str | None,
        now: datetime,
    ) -> None:
        self._connection.execute(
            insert(ai_chat_tool_runs).values(
                id=uuid4(),
                turn_id=turn_id,
                tool_name=plan.tool,
                arguments=plan.arguments.model_dump(mode="json"),
                result_summary=(
                    result.model_dump(mode="json") if result is not None else None
                ),
                result_hash=result.result_hash if result is not None else None,
                status=status,
                error_code=error_code,
                created_at=now,
                completed_at=now,
            )
        )

    def add_evidence(self, turn_id: UUID, result: ToolResult, now: datetime) -> None:
        for fact in result.facts:
            source_ref = fact.evidence_refs[0] if fact.evidence_refs else "unavailable"
            parts = source_ref.split(":", 2)
            analysis_run_id = None
            alias = source_ref
            if len(parts) == 3 and parts[0] == "analysis":
                try:
                    analysis_run_id = UUID(parts[1])
                    alias = parts[2]
                except ValueError:
                    analysis_run_id = None
            self._connection.execute(
                insert(ai_chat_evidence).values(
                    id=uuid4(),
                    turn_id=turn_id,
                    fact_ref=fact.fact_ref,
                    analysis_run_id=analysis_run_id,
                    evidence_alias=alias[:500],
                    evidence_state=fact.evidence_state,
                    source_ref=source_ref[:1000],
                    created_at=now,
                )
            )

    def tool_run(self, turn_id: UUID) -> ToolRunProjection | None:
        row = (
            self._connection.execute(
                select(*ai_chat_tool_runs.c).where(
                    ai_chat_tool_runs.c.turn_id == turn_id
                )
            )
            .mappings()
            .one_or_none()
        )
        return ToolRunProjection(**row) if row is not None else None

    def record_action_draft(
        self,
        *,
        turn_id: UUID,
        action_draft_id: UUID,
        projection: dict[str, object],
        key_hash: bytes,
        request_hash: bytes,
        now: datetime,
    ) -> ChatTurn | None:
        row = (
            self._connection.execute(
                update(ai_chat_turns)
                .where(
                    ai_chat_turns.c.id == turn_id,
                    ai_chat_turns.c.status == "answered",
                    ai_chat_turns.c.action_draft_id.is_(None),
                )
                .values(
                    action_draft_id=action_draft_id,
                    action_draft_projection=projection,
                    action_draft_key_hash=key_hash,
                    action_draft_request_hash=request_hash,
                    action_draft_created_at=now,
                    updated_at=now,
                )
                .returning(*ai_chat_turns.c)
            )
            .mappings()
            .one_or_none()
        )
        return _turn(row) if row is not None else None

    def get_action_draft_authority(
        self,
        turn_id: UUID,
    ) -> tuple[bytes, bytes] | None:
        row = self._connection.execute(
            select(
                ai_chat_turns.c.action_draft_key_hash,
                ai_chat_turns.c.action_draft_request_hash,
            ).where(ai_chat_turns.c.id == turn_id)
        ).one_or_none()
        if row is None or row[0] is None or row[1] is None:
            return None
        return bytes(row[0]), bytes(row[1])

    def evidence(self, turn_id: UUID) -> tuple[ChatEvidenceProjection, ...]:
        rows = self._connection.execute(
            select(*ai_chat_evidence.c)
            .where(ai_chat_evidence.c.turn_id == turn_id)
            .order_by(ai_chat_evidence.c.fact_ref)
        ).mappings()
        return tuple(ChatEvidenceProjection(**row) for row in rows)

    def delete_for_session(self, actor_kind: str, session_id: UUID) -> int:
        session_column = (
            ai_chat_turns.c.operator_session_id
            if actor_kind == "operator"
            else ai_chat_turns.c.demo_session_id
        )
        return int(
            self._connection.execute(
                delete(ai_chat_turns).where(
                    ai_chat_turns.c.actor_kind == actor_kind,
                    session_column == session_id,
                )
            ).rowcount
        )


def _turn(row) -> ChatTurn:
    scope = dict(row["scope"])
    scope.setdefault("workspace_id", row["workspace_id"])
    scope.setdefault("actor_kind", row["actor_kind"])
    scope.setdefault(
        "session_id",
        str(row["operator_session_id"] or row["demo_session_id"]),
    )
    answer = None
    if row["answer_projection"] is not None:
        payload = dict(row["answer_projection"])
        answer_scope = dict(payload.get("scope", {}))
        answer_scope.update(scope)
        payload["scope"] = answer_scope
        answer = ChatAnswer.model_validate(payload)
    return ChatTurn(
        id=row["id"],
        turn_sequence=int(row["turn_sequence"]),
        actor_kind=row["actor_kind"],
        session_id=row["operator_session_id"] or row["demo_session_id"],
        dataset_version_id=row["dataset_version_id"],
        question=row["question"],
        recommended_question_id=row["recommended_question_id"],
        prompt_locale=row.get("prompt_locale"),
        prompt_template_version=row.get("prompt_template_version"),
        prompt_template_sha256=row.get("prompt_template_sha256"),
        prompt_audit_state=row.get("prompt_audit_state", "legacy_unrecorded"),
        credential_binding_id=row.get("credential_binding_id"),
        credential_control_revision=row.get("credential_control_revision"),
        credential_request_id=row.get("credential_request_id"),
        status=row["status"],
        plan_schema_version=row["plan_schema_version"],
        output_schema_version=row["output_schema_version"],
        tool=row["tool_name"],
        result_hash=row["result_hash"],
        answer=answer,
        safe_summary=row["safe_summary"],
        error_code=row["error_code"],
        action_draft_id=row["action_draft_id"],
        action_draft=(
            dict(row["action_draft_projection"])
            if row["action_draft_projection"] is not None
            else None
        ),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
        saved=bool(row.get("saved", False)),
    )
