"""Orchestrate bounded Ask BizPulse turns with exact replay and no retries."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import re
from uuid import UUID, uuid5

from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from src.actions.contracts import ActionSource, FactRef
from src.ai.answer_merge import AnswerMergeRejected, merge_answer
from src.ai.contracts import (
    ChatAnswer,
    ChatPrincipal,
    ChatTurn,
    ModelExplanation,
    PlanningDecision,
    ProviderResult,
    QueryPlan,
    QueryScope,
    ToolResult,
)
from src.ai.openai_gateway import ProviderOutcomeUnknown, ProviderUnavailable
from src.ai.prompt_catalog import (
    PromptPresetContractInvalid,
    ResolvedPrompt,
)
from src.ai.query_catalog import QueryCatalog
from src.ai.query_executor import QueryExecutionFailed, QueryExecutor
from src.ai.release_constants import (
    ANSWERING_TOKEN_RESERVATION,
    PLANNING_TOKEN_RESERVATION,
)
from src.analysis.evidence import canonical_json_bytes
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.ai_chat import AIChatRepository
from src.repositories.datasets import DatasetRepository
from src.repositories.sessions import SessionRepository
from src.services.ai_control_service import (
    AICredentialBinding,
    AIChannelDisabled,
    AIControlUnavailable,
)
from src.synthetic.boundary import (
    SyntheticSourceBoundaryError,
    validate_synthetic_records,
)

CHAT_NAMESPACE = UUID("42b93e98-1e91-46b2-8b14-c601511b1c18")
PLAN_SCHEMA_VERSION = "query-plan.v1"
OUTPUT_SCHEMA_VERSION = "chat-answer.v1"
ANSWER_VERSION = "chat-answer.v1"
MAX_QUESTION_CHARS = 2_000
CHAT_LEASE = timedelta(minutes=15)
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,127}")
UNSUPPORTED_PATTERN = re.compile(
    r"(?:\b(?:select|insert|update|delete|drop|alter|create)\b.*\b(?:from|into|table)\b|"
    r"\b(?:schema|ddl|dml|database credential|connection string)\b|"
    r"\bignore (?:all|previous|system)\b|"
    r"\bexport (?:all|every|raw) row)",
    re.IGNORECASE | re.DOTALL,
)
CHAT_SECRET_PATTERN = re.compile(
    r"(?:\bAKIA[0-9A-Z]{16}\b|"
    r"\bAuthorization\s*:\s*Bearer\s+[A-Za-z0-9._~+/=-]{12,}\b|"
    r"\bBearer\s+eyJ[A-Za-z0-9._-]{12,}\b|"
    r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|"
    r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b|"
    r"(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,3}\)|\d{2,3})"
    r"[\s.-]?\d{3,5}[\s.-]\d{4}\b|"
    r"\b(?:password|passwd|client_secret|api_key|access_token)\s*[:=]\s*"
    r"[^\s,;]{8,})",
    re.IGNORECASE,
)
CHAT_CONTEXT_TO_REFERENCE = {
    "inventory_analysis": "inventory_analysis:pinned",
    "profit_bridge": "profit_bridge:pinned",
    "forecast": "forecast:pinned",
    "action_cards": "action_cards:pinned",
}
CHAT_CONTEXT_TO_TOOL = {
    "inventory_analysis": "inventory_risk_lookup",
    "profit_bridge": "profit_bridge_explain",
    "forecast": "forecast_lookup",
    "action_cards": "action_card_lookup",
}


class AIChatError(RuntimeError):
    code = "AI_CHAT_ERROR"


class AIChatInvalid(AIChatError):
    code = "AI_CHAT_INVALID"


class AIChatPromptPresetInvalid(AIChatInvalid):
    code = "prompt_preset_contract_invalid"


class AIChatNotFound(AIChatError):
    code = "AI_CHAT_NOT_FOUND"


class AIChatConflict(AIChatError):
    code = "IDEMPOTENCY_CONFLICT"


class AIChatBusy(AIChatError):
    code = "AI_CHAT_BUSY"


class AIChatBudgetExceeded(AIChatError):
    code = "AI_CHAT_BUDGET_EXHAUSTED"


class AIChatRateLimited(AIChatError):
    code = "AI_CHAT_RATE_LIMITED"


class AIChatInputRejected(AIChatError):
    code = "AI_CHAT_INPUT_REJECTED"


class AIChatUnavailable(AIChatError):
    code = "AI_CHAT_UNAVAILABLE"


class AIChatChannelDisabled(AIChatUnavailable):
    code = "AI_CHAT_CHANNEL_DISABLED"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class AIBudgetLimits:
    daily_attempt_limit: int
    monthly_token_limit: int
    max_concurrent_turns: int
    session_attempt_limit_per_minute: int = 3
    global_attempt_limit_per_minute: int = 20
    failure_rehearsal: bool = False

    def __post_init__(self) -> None:
        if (
            min(
                self.daily_attempt_limit,
                self.monthly_token_limit,
                self.max_concurrent_turns,
                self.session_attempt_limit_per_minute,
                self.global_attempt_limit_per_minute,
            )
            <= 0
        ):
            raise ValueError("ai_budget_limits_invalid")
        if not isinstance(self.failure_rehearsal, bool):
            raise ValueError("ai_budget_limits_invalid")


@dataclass(frozen=True, slots=True)
class AIProviderAttemptTelemetry:
    error_code: str | None
    reserved_tokens: int
    stage: str
    status: str


@dataclass(frozen=True, slots=True)
class AITurnTelemetry:
    dataset_version_hash_prefix: str
    error_code: str | None
    input_tokens: int
    output_tokens: int
    provider_attempt_count: int
    provider_attempts: tuple[AIProviderAttemptTelemetry, ...]
    provider_ledger_count: int
    provider_ledger_reserved_tokens: int
    provider_reserved_tokens: int
    replayed: bool
    status: str
    tool_name: str | None


class AIChatService:
    def __init__(
        self,
        *,
        engine: Engine,
        workspace_id: str,
        catalog: QueryCatalog,
        executor: QueryExecutor,
        gateway,
        ai_control,
        budget_limits: AIBudgetLimits,
        action_service=None,
        clock=None,
        uow_factory=PostgresUnitOfWork,
    ) -> None:
        self._engine = engine
        self._workspace_id = workspace_id
        self._catalog = catalog
        self._executor = executor
        self._gateway = gateway
        self._ai_control = ai_control
        self._budget = budget_limits
        self._actions = action_service
        self._clock = clock or (lambda: datetime.now(UTC))
        self._uow_factory = uow_factory

    def submit(
        self,
        principal: ChatPrincipal,
        *,
        question: str | None = None,
        recommended_question_id: str | None = None,
        prompt_locale: str | None = None,
        prompt_template_version: str | None = None,
        prompt_template_sha256: str | None = None,
        context_kind: str | None = None,
        context_reference: str | None = None,
        idempotency_key: str,
        request_id: str | None = None,
    ) -> ChatTurn:
        scope = self._validate_principal(
            principal,
            context_kind=context_kind,
            context_reference=context_reference,
        )
        normalized_question = _validate_question(question)
        resolution = self.resolve_prompt(
            question=normalized_question,
            recommended_question_id=recommended_question_id,
            prompt_locale=prompt_locale,
            prompt_template_version=prompt_template_version,
            prompt_template_sha256=prompt_template_sha256,
            context_kind=context_kind,
        )
        normalized_recommended = resolution.recommended_question_id
        key_hash = _key_hash(principal, idempotency_key)
        payload = {
            "actor_kind": principal.actor_kind,
            "session_id": str(principal.session_id),
            "chat_epoch": (
                principal.chat_epoch if principal.actor_kind == "demo" else None
            ),
            "dataset_version_id": str(principal.dataset_version_id),
            "store_ids": list(scope.store_ids),
            "period_start": scope.period_start.isoformat(),
            "period_end": scope.period_end.isoformat(),
            "currency": scope.currency,
            "question": normalized_question,
            "recommended_question_id": normalized_recommended,
            "prompt_locale": resolution.prompt_locale,
            "prompt_template_version": resolution.prompt_template_version,
            "prompt_template_sha256": resolution.prompt_template_sha256,
            "context": (
                {"kind": context_kind, "reference": context_reference}
                if context_kind is not None
                else None
            ),
        }
        request_hash = sha256(canonical_json_bytes(payload)).digest()
        question_digest = sha256(normalized_question.encode()).hexdigest()
        turn_id = uuid5(
            CHAT_NAMESPACE,
            f"{principal.actor_kind}:{principal.session_id}:"
            f"{key_hash.hex()}:{request_hash.hex()}",
        )
        now = self._clock()
        history: tuple[str, ...] = ()
        try:
            replay = self._recover_and_find_replay(
                principal,
                key_hash,
                request_hash,
                now,
            )
        except Exception:
            replay = self._find_replay(principal, key_hash, request_hash)
            if replay is None:
                replay = self._recover_and_find_replay(
                    principal,
                    key_hash,
                    request_hash,
                    now,
                )
        if replay is not None:
            return replace(replay, replayed=True)
        try:
            selector = getattr(self._ai_control, "select_binding", None)
            if callable(selector):
                selected = selector(principal.actor_kind)
            else:
                selected = self._ai_control.require_enabled(principal.actor_kind)
        except AIChannelDisabled:
            replay = self._find_replay(principal, key_hash, request_hash)
            if replay is not None:
                return replace(replay, replayed=True)
            raise AIChatChannelDisabled from None
        except AIControlUnavailable as error:
            replay = self._find_replay(principal, key_hash, request_hash)
            if replay is not None:
                return replace(replay, replayed=True)
            raise AIChatUnavailable(error.code) from None
        except Exception:
            replay = self._find_replay(principal, key_hash, request_hash)
            if replay is not None:
                return replace(replay, replayed=True)
            raise AIChatUnavailable("AI_CHAT_UNAVAILABLE") from None
        if isinstance(selected, AICredentialBinding):
            binding = selected
        elif isinstance(selected, str) and selected.strip():
            binding = AICredentialBinding(
                version=selected,
                binding_id=sha256(
                    b"bizpulse-test-credential-binding-v1\x00" + selected.encode()
                ).hexdigest(),
                control_revision=0,
            )
        else:
            raise AIChatUnavailable("AI_CHAT_UNAVAILABLE")
        credential_version = binding.version
        credential_request_owned = request_id is not None
        credential_request_id = request_id or f"turn-{turn_id.hex}"
        if REQUEST_ID_PATTERN.fullmatch(credential_request_id) is None:
            raise AIChatInvalid("request_id_invalid")
        try:
            with self._uow_factory(self._engine) as uow:
                repository = AIChatRepository(uow.connection)
                repository.lock_session(principal.actor_kind, principal.session_id)
                if principal.actor_kind == "demo" and not SessionRepository(
                    uow.connection
                ).lock_demo_chat_epoch(
                    principal.session_id,
                    principal.workspace_id,
                    principal.dataset_version_id,
                    principal.chat_epoch,
                    now,
                ):
                    raise AIChatNotFound("chat_session_epoch_changed")
                repository.lock_budget()
                repository.recover_stale(now)
                history = repository.safe_history(
                    principal.actor_kind,
                    principal.session_id,
                    scope.dataset_version_id,
                    scope.store_ids,
                )
                replay = repository.find_by_key(
                    principal.actor_kind,
                    principal.session_id,
                    key_hash,
                )
                if replay is not None:
                    stored_hash = repository.request_hash(replay.id)
                    if stored_hash != request_hash:
                        raise AIChatConflict
                    return replace(replay, replayed=True)
                if repository.active_turn_count() >= self._budget.max_concurrent_turns:
                    raise AIChatBusy
                turn = repository.insert_turn(
                    turn_id=turn_id,
                    workspace_id=self._workspace_id,
                    dataset_version_id=scope.dataset_version_id,
                    actor_kind=principal.actor_kind,
                    session_id=principal.session_id,
                    question=normalized_question,
                    recommended_question_id=normalized_recommended,
                    prompt_locale=resolution.prompt_locale,
                    prompt_template_version=resolution.prompt_template_version,
                    prompt_template_sha256=resolution.prompt_template_sha256,
                    prompt_audit_state="recorded",
                    question_digest=question_digest,
                    scope=_scope_payload(scope),
                    plan_schema_version=PLAN_SCHEMA_VERSION,
                    output_schema_version=OUTPUT_SCHEMA_VERSION,
                    key_hash=key_hash,
                    request_hash=request_hash,
                    credential_binding_id=binding.binding_id,
                    credential_control_revision=binding.control_revision,
                    credential_request_id=credential_request_id,
                    now=now,
                    lease_expires_at=now + CHAT_LEASE,
                )
        except IntegrityError as error:
            replay = self._find_replay(principal, key_hash, request_hash)
            if replay is not None:
                return replace(replay, replayed=True)
            raise AIChatBusy from error
        except Exception:
            replay = self._find_replay(principal, key_hash, request_hash)
            if replay is None:
                raise
            if (
                not credential_request_owned
                or replay.credential_binding_id != binding.binding_id
                or replay.credential_control_revision != binding.control_revision
                or replay.credential_request_id != credential_request_id
            ):
                return replace(replay, replayed=True)
            turn = replay

        if turn.status != "planning":
            return turn
        if UNSUPPORTED_PATTERN.search(normalized_question):
            return self._terminal(
                turn.id,
                "planning",
                "unsupported",
                "unsupported_question",
                "This request is outside the Ask BizPulse whitelist.",
            )
        if len(normalized_question) < 5:
            return self._terminal(
                turn.id,
                "planning",
                "clarification_required",
                "question_ambiguous",
                "Please ask a specific metric, period, SKU, or evidence question.",
            )

        if resolution.fixed_intent is not None:
            plan = self._catalog.plan_for_intent(resolution.fixed_intent, scope)
        else:
            try:
                decision = self._provider_plan(
                    turn.id,
                    normalized_question,
                    history,
                    credential_version,
                )
            except AIChatError as error:
                return self._provider_terminal(turn.id, "planning", error)
            if decision.status != "planned":
                status = decision.status
                return self._terminal(
                    turn.id,
                    "planning",
                    status,
                    (
                        "question_ambiguous"
                        if status == "clarification_required"
                        else "unsupported_question"
                    ),
                    (
                        "Please ask a specific supported synthetic business question."
                        if status == "clarification_required"
                        else "This request is outside the Ask BizPulse whitelist."
                    ),
                )
            assert decision.plan is not None
            plan = decision.plan

        if (
            scope.context_kind is not None
            and plan.tool != CHAT_CONTEXT_TO_TOOL[scope.context_kind]
        ):
            return self._terminal(
                turn.id,
                "planning",
                "unsupported",
                "context_tool_mismatch",
                "This question does not match the selected pinned context.",
            )

        try:
            querying = self._transition(
                turn.id,
                expected="planning",
                status="querying",
                tool_name=plan.tool,
            )
            result = self._executor.execute(plan, scope)
            try:
                with self._uow_factory(self._engine) as uow:
                    repository = AIChatRepository(uow.connection)
                    repository.add_tool_result(
                        turn.id,
                        plan,
                        result,
                        status="succeeded",
                        error_code=None,
                        now=self._clock(),
                    )
                    no_facts = not result.facts
                    insufficient_answer = (
                        ChatAnswer(
                            turn_id=turn.id,
                            status="clarification_required",
                            answer=(
                                "The current synthetic data is insufficient to "
                                "support this conclusion."
                            ),
                            scope=scope,
                            facts=(),
                            limitations=result.limitations,
                            suggested_questions=(
                                "Adjust the available filters or ask about another "
                                "supported synthetic metric.",
                            ),
                            action_card_draft_eligible=False,
                        )
                        if no_facts
                        else None
                    )
                    answering = repository.transition(
                        turn.id,
                        expected_status="querying",
                        status=("clarification_required" if no_facts else "answering"),
                        now=self._clock(),
                        tool_name=plan.tool,
                        result_hash=result.result_hash,
                        answer=insufficient_answer,
                        error_code="insufficient_evidence" if no_facts else None,
                        safe_summary=(
                            "The current synthetic data is insufficient to support "
                            "this conclusion."
                            if no_facts
                            else None
                        ),
                        lease_expires_at=(
                            None if no_facts else self._clock() + CHAT_LEASE
                        ),
                    )
                    if answering is None:
                        raise AIChatUnavailable("turn_transition_failed")
            except Exception:
                with self._engine.connect() as connection:
                    repository = AIChatRepository(connection)
                    answering = repository.get(turn.id)
                    durable_run = repository.tool_run(turn.id)
                if (
                    answering is None
                    or answering.status
                    != ("clarification_required" if not result.facts else "answering")
                    or answering.tool != plan.tool
                    or answering.result_hash != result.result_hash
                    or durable_run is None
                    or durable_run.status != "succeeded"
                    or durable_run.tool_name != plan.tool
                    or durable_run.result_hash != result.result_hash
                ):
                    raise
            if not result.facts:
                return answering
        except Exception as error:
            if isinstance(error, QueryExecutionFailed):
                try:
                    with self._uow_factory(self._engine) as uow:
                        AIChatRepository(uow.connection).add_tool_result(
                            turn.id,
                            plan,
                            None,
                            status="failed",
                            error_code="query_failed",
                            now=self._clock(),
                        )
                except Exception:
                    pass
            return self._terminal(
                turn.id,
                querying.status if "querying" in locals() else "planning",
                "failed",
                "query_failed",
                "The authoritative query is currently unavailable.",
            )

        try:
            explanation = self._provider_explanation(
                turn.id,
                normalized_question,
                result,
                history,
                credential_version,
            )
            answer = merge_answer(turn.id, result, explanation)
        except (AIChatError, AnswerMergeRejected, ValidationError) as error:
            if isinstance(error, AIChatError):
                return self._provider_terminal(turn.id, "answering", error)
            return self._terminal(
                turn.id,
                "answering",
                "failed",
                "answer_merge_rejected",
                "The explanation could not be safely bound to authoritative facts.",
            )

        try:
            with self._uow_factory(self._engine) as uow:
                repository = AIChatRepository(uow.connection)
                repository.add_evidence(turn.id, result, self._clock())
                completed = repository.transition(
                    turn.id,
                    expected_status="answering",
                    status="answered",
                    now=self._clock(),
                    tool_name=plan.tool,
                    result_hash=result.result_hash,
                    answer=answer,
                    safe_summary=_safe_summary(answer),
                    lease_expires_at=None,
                )
                if completed is None:
                    raise AIChatUnavailable("turn_completion_failed")
                return completed
        except Exception as error:
            current = self._get_optional(principal, turn.id)
            if current is not None and current.status == "answered":
                return current
            raise AIChatUnavailable("turn_completion_unknown") from error

    def list(self, principal: ChatPrincipal) -> tuple[ChatTurn, ...]:
        self._validate_principal(principal)
        with self._engine.connect() as connection:
            repository = AIChatRepository(connection)
            turns = repository.list_for_session(
                principal.actor_kind,
                principal.session_id,
            )
            if principal.actor_kind != "operator":
                return turns
            saved = repository.saved_ids(tuple(turn.id for turn in turns))
            return tuple(replace(turn, saved=turn.id in saved) for turn in turns)

    def credential_binding_audit(
        self,
        turn_ids: tuple[UUID, ...],
    ):
        with self._engine.connect() as connection:
            return AIChatRepository(connection).credential_binding_audit(
                self._workspace_id,
                turn_ids,
            )

    def get(self, principal: ChatPrincipal, turn_id: UUID) -> ChatTurn:
        self._validate_principal(principal)
        current = self._get_optional(principal, turn_id)
        if (
            current is None
            or current.dataset_version_id != principal.dataset_version_id
        ):
            raise AIChatNotFound
        if principal.actor_kind == "operator":
            with self._engine.connect() as connection:
                saved = AIChatRepository(connection).saved_ids((current.id,))
            current = replace(current, saved=current.id in saved)
        return current

    def telemetry(
        self,
        principal: ChatPrincipal,
        turn_id: UUID,
        *,
        replayed: bool = False,
    ) -> AITurnTelemetry:
        """Project only value-free usage metadata for a session-owned turn."""

        turn = self.get(principal, turn_id)
        with self._engine.connect() as connection:
            dataset = DatasetRepository(connection).get_version(turn.dataset_version_id)
            if dataset is None or dataset.workspace_id != self._workspace_id:
                raise AIChatInvalid("dataset_version_authority_missing")
            repository = AIChatRepository(connection)
            input_tokens, output_tokens = repository.turn_token_usage(turn.id)
            attempts, ledger_count, ledger_reserved_tokens = (
                repository.turn_attempt_audit(turn.id)
            )
        return AITurnTelemetry(
            dataset_version_hash_prefix=dataset.content_sha256[:12],
            error_code=turn.error_code,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider_attempt_count=len(attempts),
            provider_attempts=tuple(
                AIProviderAttemptTelemetry(
                    error_code=attempt.error_code,
                    reserved_tokens=attempt.reserved_tokens,
                    stage=attempt.stage,
                    status=attempt.status,
                )
                for attempt in attempts
            ),
            provider_ledger_count=ledger_count,
            provider_ledger_reserved_tokens=ledger_reserved_tokens,
            provider_reserved_tokens=sum(
                attempt.reserved_tokens for attempt in attempts
            ),
            replayed=replayed,
            status=turn.status,
            tool_name=turn.tool,
        )

    def dataset_hash_prefix(self, principal: ChatPrincipal) -> str:
        """Resolve the immutable dataset content hash for safe rejected telemetry."""

        self._validate_principal(principal)
        with self._engine.connect() as connection:
            dataset = DatasetRepository(connection).get_version(
                principal.dataset_version_id
            )
        if dataset is None or dataset.workspace_id != self._workspace_id:
            raise AIChatInvalid("dataset_version_authority_missing")
        return dataset.content_sha256[:12]

    def recommended_questions(self) -> tuple[dict[str, object], ...]:
        return self._catalog.recommended_questions()

    def resolve_prompt(
        self,
        *,
        question: str,
        recommended_question_id: str | None,
        prompt_locale: str | None,
        prompt_template_version: str | None,
        prompt_template_sha256: str | None,
        context_kind: str | None,
    ) -> ResolvedPrompt:
        try:
            return self._catalog.prompt_catalog.resolve(
                question=question,
                recommended_question_id=recommended_question_id,
                prompt_locale=prompt_locale,
                prompt_template_version=prompt_template_version,
                prompt_template_sha256=prompt_template_sha256,
                context_kind=context_kind,
            )
        except PromptPresetContractInvalid as error:
            raise AIChatPromptPresetInvalid("prompt_preset_contract_invalid") from error

    def list_saved(self, principal: ChatPrincipal) -> tuple[ChatTurn, ...]:
        self._validate_principal(principal)
        if principal.actor_kind != "operator" or principal.operator_id is None:
            return ()
        with self._engine.connect() as connection:
            rows = AIChatRepository(connection).list_saved_for_operator(
                principal.operator_id
            )
        saved = []
        for turn, stored_hash in rows:
            if turn.answer is None or _answer_hash(turn) != stored_hash:
                raise AIChatConflict("saved_chat_authority_conflict")
            saved.append(replace(turn, saved=True))
        return tuple(saved)

    def save_answer(self, principal: ChatPrincipal, turn_id: UUID) -> ChatTurn:
        self._validate_principal(principal)
        if principal.actor_kind != "operator" or principal.operator_id is None:
            raise AIChatInvalid("only_operator_can_save_chat")
        turn = self.get(principal, turn_id)
        if turn.status != "answered" or turn.answer is None:
            raise AIChatInvalid("only_answered_chat_can_be_saved")
        answer_hash = _answer_hash(turn)
        with self._uow_factory(self._engine) as uow:
            if not AIChatRepository(uow.connection).save_answer(
                turn_id=turn.id,
                operator_id=principal.operator_id,
                answer_hash=answer_hash,
                now=self._clock(),
            ):
                raise AIChatConflict("saved_chat_authority_conflict")
        return replace(turn, saved=True)

    def delete_demo_session(self, principal: ChatPrincipal) -> int:
        self._validate_principal(principal)
        if principal.actor_kind != "demo":
            raise AIChatInvalid("only_demo_chat_session_can_be_deleted")
        with self._uow_factory(self._engine) as uow:
            sessions = SessionRepository(uow.connection)
            if (
                sessions.advance_demo_chat_epoch(
                    principal.session_id,
                    principal.workspace_id,
                    principal.dataset_version_id,
                    principal.chat_epoch,
                    self._clock(),
                )
                is None
            ):
                raise AIChatNotFound
            sessions.clear_demo_action_overlays(principal.session_id)
            return AIChatRepository(uow.connection).delete_for_session(
                principal.actor_kind,
                principal.session_id,
            )

    def create_action_draft(
        self,
        principal: ChatPrincipal,
        turn_id: UUID,
        *,
        idempotency_key: str,
    ) -> ChatTurn:
        self._validate_principal(principal)
        turn = self.get(principal, turn_id)
        if (
            turn.status != "answered"
            or turn.answer is None
            or not turn.answer.action_card_draft_eligible
            or turn.tool is None
            or turn.result_hash is None
        ):
            raise AIChatInvalid("action_draft_not_eligible")
        scope = turn.answer.scope
        if (
            scope.dataset_version_id != principal.dataset_version_id
            or scope.workspace_id != principal.workspace_id
            or scope.actor_kind != principal.actor_kind
            or scope.session_id != principal.session_id
        ):
            raise AIChatInvalid("action_draft_scope_invalid")
        key_hash = _key_hash(principal, idempotency_key)
        request_hash = sha256(
            canonical_json_bytes(
                {
                    "turn_id": str(turn_id),
                    "dataset_version_id": str(scope.dataset_version_id),
                    "store_ids": list(scope.store_ids),
                    "result_hash": turn.result_hash,
                }
            )
        ).digest()
        with self._engine.connect() as connection:
            repository = AIChatRepository(connection)
            authority = repository.get_action_draft_authority(turn_id)
            run = repository.tool_run(turn_id)
        if authority is not None:
            if authority != (key_hash, request_hash):
                raise AIChatConflict
            return self.get(principal, turn_id)
        if run is None or run.status != "succeeded" or run.result_summary is None:
            raise AIChatInvalid("tool_result_missing")
        stored_result = _tool_result(run.result_summary, scope)
        plan = QueryPlan.model_validate(
            {"tool": run.tool_name, "arguments": run.arguments}
        )
        current_result = self._executor.execute(plan, scope)
        if (
            current_result.result_hash != turn.result_hash
            or current_result.result_hash != stored_result.result_hash
            or current_result.action_card_draft is None
        ):
            raise AIChatConflict("chat_evidence_changed")
        spec = current_result.action_card_draft
        draft_id = uuid5(CHAT_NAMESPACE, f"draft:{turn.id}")
        projection: dict[str, object]
        if principal.actor_kind == "operator":
            if self._actions is None:
                raise AIChatUnavailable("action_service_unavailable")
            fact_map = {item.fact_ref: item for item in current_result.facts}
            selected = tuple(fact_map[ref] for ref in spec.fact_refs)
            source = ActionSource(
                source_type="chat_box_draft",
                dataset_version_id=scope.dataset_version_id,
                suggestion=spec.suggestion,
                target=spec.target,
                period_start=scope.period_start,
                period_end=scope.period_end,
                scope={
                    "period_start": scope.period_start.isoformat(),
                    "period_end": scope.period_end.isoformat(),
                    "currency": scope.currency,
                    **(
                        {"store_id": scope.store_ids[0]}
                        if len(scope.store_ids) == 1
                        else {}
                    ),
                },
                quantity=spec.quantity,
                budget_brl=spec.budget_brl,
                action_date=None,
                threshold=None,
                expected_impact=spec.expected_impact,
                confidence=spec.confidence,
                limitations=spec.limitations,
                analysis_run_id=None,
                forecast_id=None,
                bridge_id=None,
                chat_turn_id=turn.id,
                chat_tool=turn.tool,
                answer_version=ANSWER_VERSION,
            )
            card = self._actions.create_draft(
                source,
                tuple(
                    FactRef(
                        alias=item.fact_ref,
                        evidence_state=item.evidence_state,
                        source_ref=item.evidence_refs[0],
                        value=item.value,
                    )
                    for item in selected
                ),
                f"chat-turn-{turn.id}",
            )
            draft_id = card.id
            projection = {
                "kind": "operator_action_card",
                "action_id": str(card.id),
                "status": card.status,
                "revision": card.current_revision,
            }
        else:
            projection = {
                "kind": "demo_session_draft",
                "draft_id": str(draft_id),
                "status": "new",
                "source_turn_id": str(turn.id),
                "spec": spec.model_dump(mode="json"),
            }
        try:
            with self._uow_factory(self._engine) as uow:
                stored = AIChatRepository(uow.connection).record_action_draft(
                    turn_id=turn.id,
                    action_draft_id=draft_id,
                    projection=projection,
                    key_hash=key_hash,
                    request_hash=request_hash,
                    now=self._clock(),
                )
                if stored is None:
                    raise AIChatConflict
                return stored
        except Exception:
            current = self.get(principal, turn_id)
            if current.action_draft_id == draft_id:
                with self._engine.connect() as connection:
                    exact = AIChatRepository(connection).get_action_draft_authority(
                        turn_id
                    )
                if exact == (key_hash, request_hash):
                    return current
            raise

    def _validate_principal(
        self,
        principal: ChatPrincipal,
        *,
        context_kind: str | None = None,
        context_reference: str | None = None,
    ) -> QueryScope:
        if (
            not isinstance(principal, ChatPrincipal)
            or principal.workspace_id != self._workspace_id
            or principal.actor_kind not in {"operator", "demo"}
        ):
            raise AIChatInvalid("chat_principal_invalid")
        if (context_kind is None) != (context_reference is None):
            raise AIChatInvalid("chat_context_invalid")
        if (
            context_kind is not None
            and CHAT_CONTEXT_TO_REFERENCE.get(context_kind) != context_reference
        ):
            raise AIChatInvalid("chat_context_invalid")
        return principal.scope(
            context_kind=context_kind,
            context_reference=context_reference,
        )

    def _provider_plan(
        self,
        turn_id: UUID,
        question: str,
        history: tuple[str, ...],
        credential_version: str,
    ) -> PlanningDecision:
        attempt_id = self._begin_attempt(turn_id, "planning")
        try:
            response = self._gateway.plan(
                question,
                self._catalog.capability_catalog(),
                history,
                credential_version=credential_version,
            )
            value, input_tokens, output_tokens = _provider_value(response)
            decision = PlanningDecision.model_validate(value)
        except ProviderOutcomeUnknown as error:
            self._finish_attempt(
                attempt_id, "outcome_unknown", 0, 0, "provider_outcome_unknown"
            )
            raise AIChatUnavailable("provider_outcome_unknown") from error
        except ProviderUnavailable as error:
            code = _provider_failure_code(error)
            self._finish_attempt(attempt_id, "failed", 0, 0, code)
            raise AIChatUnavailable("provider_unavailable") from error
        except Exception as error:
            self._finish_attempt(attempt_id, "failed", 0, 0, "provider_unavailable")
            raise AIChatUnavailable("provider_unavailable") from error
        self._finish_attempt(
            attempt_id,
            "succeeded",
            input_tokens,
            output_tokens,
            None,
        )
        return decision

    def _provider_explanation(
        self,
        turn_id: UUID,
        question: str,
        result: ToolResult,
        history: tuple[str, ...],
        credential_version: str,
    ) -> ModelExplanation:
        attempt_id = self._begin_attempt(turn_id, "answering")
        try:
            response = self._gateway.explain(
                question,
                result,
                history,
                credential_version=credential_version,
            )
            value, input_tokens, output_tokens = _provider_value(response)
            explanation = ModelExplanation.model_validate(value)
        except ProviderOutcomeUnknown as error:
            self._finish_attempt(
                attempt_id, "outcome_unknown", 0, 0, "provider_outcome_unknown"
            )
            raise AIChatUnavailable("provider_outcome_unknown") from error
        except ProviderUnavailable as error:
            code = _provider_failure_code(error)
            self._finish_attempt(attempt_id, "failed", 0, 0, code)
            raise AIChatUnavailable("provider_unavailable") from error
        except Exception as error:
            self._finish_attempt(attempt_id, "failed", 0, 0, "provider_unavailable")
            raise AIChatUnavailable("provider_unavailable") from error
        self._finish_attempt(
            attempt_id,
            "succeeded",
            input_tokens,
            output_tokens,
            None,
        )
        return explanation

    def _begin_attempt(self, turn_id: UUID, stage: str) -> UUID:
        if self._budget.failure_rehearsal:
            raise AIChatBudgetExceeded
        now = self._clock()
        day_start = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)
        month_start = datetime(now.year, now.month, 1, tzinfo=now.tzinfo)
        minute_start = now - timedelta(minutes=1)
        reserved_tokens = (
            PLANNING_TOKEN_RESERVATION
            if stage == "planning"
            else ANSWERING_TOKEN_RESERVATION
        )
        try:
            with self._uow_factory(self._engine) as uow:
                repository = AIChatRepository(uow.connection)
                repository.lock_budget()
                global_minute_attempts, _ = repository.attempt_usage(since=minute_start)
                session_minute_attempts = repository.session_attempt_count(
                    turn_id,
                    since=minute_start,
                )
                daily_attempts, _ = repository.attempt_usage(since=day_start)
                _, monthly_tokens = repository.attempt_usage(since=month_start)
                if (
                    global_minute_attempts
                    >= self._budget.global_attempt_limit_per_minute
                    or session_minute_attempts
                    >= self._budget.session_attempt_limit_per_minute
                ):
                    raise AIChatRateLimited
                if daily_attempts >= self._budget.daily_attempt_limit:
                    raise AIChatBudgetExceeded
                if monthly_tokens + reserved_tokens > self._budget.monthly_token_limit:
                    raise AIChatBudgetExceeded
                return repository.add_attempt(
                    turn_id,
                    stage,
                    now,
                    reserved_tokens,
                )
        except (AIChatBudgetExceeded, AIChatRateLimited):
            raise
        except IntegrityError as error:
            raise AIChatUnavailable("provider_attempt_already_recorded") from error
        except Exception:
            with self._engine.connect() as connection:
                attempt = AIChatRepository(connection).attempt(turn_id, stage)
            if (
                attempt is not None
                and attempt.status == "started"
                and attempt.reserved_tokens == reserved_tokens
            ):
                return attempt.id
            raise

    def _finish_attempt(
        self,
        attempt_id: UUID,
        status: str,
        input_tokens: int,
        output_tokens: int,
        error_code: str | None,
    ) -> None:
        try:
            with self._uow_factory(self._engine) as uow:
                repository = AIChatRepository(uow.connection)
                current = repository.attempt_by_id(attempt_id)
                if current is None:
                    raise AIChatUnavailable("provider_attempt_missing")
                if input_tokens + output_tokens > current.reserved_tokens:
                    raise AIChatUnavailable("provider_usage_exceeds_reservation")
                repository.finish_attempt(
                    attempt_id,
                    status=status,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    error_code=error_code,
                    now=self._clock(),
                )
        except Exception:
            with self._engine.connect() as connection:
                current = AIChatRepository(connection).attempt_by_id(attempt_id)
            if (
                current is not None
                and current.status == status
                and current.input_tokens == input_tokens
                and current.output_tokens == output_tokens
                and current.error_code == error_code
                and current.completed_at is not None
            ):
                return
            raise

    def _provider_terminal(
        self,
        turn_id: UUID,
        expected: str,
        error: AIChatError,
    ) -> ChatTurn:
        code = str(error) or error.code
        status = "outcome_unknown" if "outcome_unknown" in code else "failed"
        return self._terminal(
            turn_id,
            expected,
            status,
            "provider_outcome_unknown" if status == "outcome_unknown" else error.code,
            "The AI explanation layer is unavailable; deterministic pages remain available.",
        )

    def _terminal(
        self,
        turn_id: UUID,
        expected: str,
        status: str,
        error_code: str,
        summary: str,
    ) -> ChatTurn:
        return self._transition(
            turn_id,
            expected=expected,
            status=status,
            error_code=error_code,
            safe_summary=summary,
        )

    def _transition(
        self,
        turn_id: UUID,
        *,
        expected: str,
        status: str,
        tool_name: str | None = None,
        result_hash: str | None = None,
        error_code: str | None = None,
        safe_summary: str | None = None,
    ) -> ChatTurn:
        try:
            with self._uow_factory(self._engine) as uow:
                now = self._clock()
                current = AIChatRepository(uow.connection).transition(
                    turn_id,
                    expected_status=expected,
                    status=status,
                    now=now,
                    tool_name=tool_name,
                    result_hash=result_hash,
                    error_code=error_code,
                    safe_summary=safe_summary,
                    lease_expires_at=(
                        None
                        if status
                        in {
                            "answered",
                            "clarification_required",
                            "unsupported",
                            "failed",
                            "outcome_unknown",
                        }
                        else now + CHAT_LEASE
                    ),
                )
                if current is None:
                    raise AIChatUnavailable("turn_transition_failed")
                return current
        except Exception:
            with self._engine.connect() as connection:
                current = AIChatRepository(connection).get(turn_id)
            if (
                current is not None
                and current.status == status
                and (tool_name is None or current.tool == tool_name)
                and (result_hash is None or current.result_hash == result_hash)
                and (error_code is None or current.error_code == error_code)
                and (safe_summary is None or current.safe_summary == safe_summary)
            ):
                return current
            raise

    def _find_replay(
        self,
        principal: ChatPrincipal,
        key_hash: bytes,
        request_hash: bytes,
    ) -> ChatTurn | None:
        try:
            with self._engine.connect() as connection:
                repository = AIChatRepository(connection)
                replay = repository.find_by_key(
                    principal.actor_kind,
                    principal.session_id,
                    key_hash,
                )
                if replay is None:
                    return None
                stored = repository.request_hash(replay.id)
            if stored != request_hash:
                raise AIChatConflict
            return replay
        except AIChatConflict:
            raise
        except Exception:
            return None

    def _recover_and_find_replay(
        self,
        principal: ChatPrincipal,
        key_hash: bytes,
        request_hash: bytes,
        now: datetime,
    ) -> ChatTurn | None:
        with self._uow_factory(self._engine) as uow:
            repository = AIChatRepository(uow.connection)
            repository.lock_session(principal.actor_kind, principal.session_id)
            if principal.actor_kind == "demo" and not SessionRepository(
                uow.connection
            ).lock_demo_chat_epoch(
                principal.session_id,
                principal.workspace_id,
                principal.dataset_version_id,
                principal.chat_epoch,
                now,
            ):
                raise AIChatNotFound("chat_session_epoch_changed")
            repository.lock_budget()
            repository.recover_stale(now)
            replay = repository.find_by_key(
                principal.actor_kind,
                principal.session_id,
                key_hash,
            )
            if replay is None:
                return None
            stored_hash = repository.request_hash(replay.id)
        if stored_hash != request_hash:
            raise AIChatConflict
        return replay

    def _get_optional(
        self,
        principal: ChatPrincipal,
        turn_id: UUID,
    ) -> ChatTurn | None:
        with self._engine.connect() as connection:
            return AIChatRepository(connection).get_for_session(
                principal.actor_kind,
                principal.session_id,
                turn_id,
            )


def _validate_question(question: str | None) -> str:
    if question is None:
        raise AIChatInvalid("question_required")
    normalized = question.strip()
    if not 1 <= len(normalized) <= MAX_QUESTION_CHARS:
        raise AIChatInputRejected("question_length_invalid")
    if CHAT_SECRET_PATTERN.search(normalized):
        raise AIChatInputRejected("question_sensitive_pattern")
    try:
        validate_synthetic_records(({"question": normalized},))
    except SyntheticSourceBoundaryError as error:
        raise AIChatInputRejected("question_sensitive_pattern") from error
    return normalized


def _key_hash(principal: ChatPrincipal, key: str) -> bytes:
    if (
        not isinstance(key, str)
        or not 1 <= len(key) <= 128
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in key)
    ):
        raise AIChatInvalid("idempotency_key_invalid")
    return sha256(
        f"{principal.actor_kind}:{principal.session_id}:{key}".encode()
    ).digest()


def _scope_payload(scope: QueryScope) -> dict[str, object]:
    return {
        "workspace_id": scope.workspace_id,
        "actor_kind": scope.actor_kind,
        "session_id": str(scope.session_id) if scope.session_id else None,
        "session_created_at": (
            scope.session_created_at.isoformat() if scope.session_created_at else None
        ),
        "forecast_id": str(scope.forecast_id) if scope.forecast_id else None,
        "profit_bridge_id": (
            str(scope.profit_bridge_id) if scope.profit_bridge_id else None
        ),
        "context_kind": scope.context_kind,
        "context_reference": scope.context_reference,
        "dataset_version_id": str(scope.dataset_version_id),
        "store_ids": list(scope.store_ids),
        "period_start": scope.period_start.isoformat(),
        "period_end": scope.period_end.isoformat(),
        "currency": scope.currency,
    }


def _provider_value(value):
    if not isinstance(value, ProviderResult):
        raise ValueError("provider_result_envelope_required")
    return value.value, value.input_tokens, value.output_tokens


def _provider_failure_code(error: ProviderUnavailable) -> str:
    code = str(error)
    if code in {"key_vault_secret_unavailable", "provider_auth_rejected"}:
        return code
    return "provider_unavailable"


def _safe_summary(answer) -> str:
    return f"{answer.status}; tool facts={len(answer.facts)}; limitations={len(answer.limitations)}"


def _answer_hash(turn: ChatTurn) -> str:
    if turn.answer is None:
        raise AIChatInvalid("saved_chat_answer_missing")
    return sha256(canonical_json_bytes(turn.answer.model_dump(mode="json"))).hexdigest()


def _tool_result(payload: dict[str, object], scope: QueryScope) -> ToolResult:
    value = dict(payload)
    value["scope"] = _scope_payload(scope)
    return ToolResult.model_validate(value)
