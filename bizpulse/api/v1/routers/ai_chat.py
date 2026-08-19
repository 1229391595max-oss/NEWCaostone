"""Same-origin Ask BizPulse routes with server-owned scope."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse

from api.dependencies.csrf import require_allowed_origin
from api.dependencies.operator import OPERATOR_COOKIE, resolve_operator
from api.dependencies.session import DEMO_COOKIE, resolve_demo_session
from api.errors import (
    AuthenticationRequiredError,
    CsrfValidationError,
    DemoDataNotImportedError,
)
from api.request_context import request_id, set_safe_error_code
from api.v1.schemas.ai_chat import (
    ChatSessionDeleteResponse,
    ProviderAuditResponse,
    ChatTurnListResponse,
    ChatTurnRequest,
    ChatTurnResponse,
)
from src.ai.contracts import ChatPrincipal
from src.observability import log_ai_turn
from src.services.ai_chat_service import (
    AIChatBudgetExceeded,
    AIChatBusy,
    AIChatConflict,
    AIChatInputRejected,
    AIChatInvalid,
    AIChatNotFound,
    AIChatRateLimited,
    AIChatUnavailable,
)
from src.services.store_scope import StoreScopeError, StoreScopeResolver

router = APIRouter(prefix="/ai-chat", tags=["ai-chat"])
PRIVATE_NO_STORE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


def _service(request: Request):
    return request.app.state.container.ai_chat_service


def _error(error: Exception, request: Request) -> JSONResponse:
    if isinstance(error, AIChatNotFound):
        status = 404
    elif isinstance(error, AIChatConflict):
        status = 409
    elif isinstance(error, AIChatBusy):
        status = 409
    elif isinstance(error, (AIChatBudgetExceeded, AIChatRateLimited)):
        status = 429
    elif isinstance(error, (AIChatInvalid, AIChatInputRejected)):
        status = 422
    elif isinstance(error, AIChatUnavailable):
        status = 503
    else:
        status = 503
    code = getattr(error, "code", "AI_CHAT_UNAVAILABLE")
    set_safe_error_code(request.scope, str(code))
    return JSONResponse(
        status_code=status,
        content={"code": code},
        headers=PRIVATE_NO_STORE,
    )


def _log_rejected_turn(
    request: Request,
    error: Exception,
    principal: ChatPrincipal | None,
    service=None,
) -> None:
    try:
        dataset_prefix = (
            service.dataset_hash_prefix(principal)
            if principal is not None and service is not None
            else None
        )
        log_ai_turn(
            {
                "dataset_version_hash_prefix": dataset_prefix,
                "error_code": getattr(error, "code", "AI_CHAT_UNAVAILABLE"),
                "event": "ai_turn",
                "input_tokens": 0,
                "output_tokens": 0,
                "replayed": False,
                "request_id": request_id(request.scope),
                "status": "rejected",
                "tool_name": None,
            }
        )
    except Exception:
        pass


def _principal(
    request: Request,
    *,
    mutate: bool,
    requested_store_ids: tuple[str, ...] | None = None,
) -> ChatPrincipal:
    operator_cookie = request.cookies.get(OPERATOR_COOKIE)
    demo_cookie = request.cookies.get(DEMO_COOKIE)
    if bool(operator_cookie) == bool(demo_cookie):
        raise AuthenticationRequiredError
    container = request.app.state.container
    if operator_cookie:
        actor = resolve_operator(request)
        if mutate:
            _validate_csrf(request, actor.session_id, "operator")
        release_service = container.public_release_service
        current = release_service.current() if release_service is not None else None
        if current is None:
            raise AIChatUnavailable("public_release_unavailable")
        dataset_version_id = current.dataset_version_id
        release = release_service.for_operator(dataset_version_id)
        actor_kind = "operator"
        session_created_at = None
        operator_id = actor.operator_id
        chat_epoch = 0
    else:
        actor = resolve_demo_session(request)
        if actor.demo_data_imported_at is None:
            raise DemoDataNotImportedError
        if mutate:
            _validate_csrf(request, actor.session_id, "demo")
        if actor.dataset_version_id is None:
            raise AIChatUnavailable("pinned_release_unavailable")
        dataset_version_id = actor.dataset_version_id
        release_service = container.public_release_service
        if release_service is None:
            raise AIChatUnavailable("public_release_unavailable")
        release = release_service.for_operator(dataset_version_id)
        actor_kind = "demo"
        session_created_at = actor.created_at
        operator_id = None
        chat_epoch = actor.chat_epoch
    if container.engine is None or container.workflow_storage is None:
        raise AIChatUnavailable("store_scope_authority_unavailable")
    try:
        resolved = StoreScopeResolver(
            container.engine,
            container.workflow_storage,
            actor.workspace_id,
        ).resolve(dataset_version_id, requested_store_ids)
    except StoreScopeError as error:
        raise AIChatInvalid("store_scope_invalid") from error
    identity_scope = {
        "currency": "BRL",
        **(
            {"store_id": resolved.store_ids[0]}
            if resolved.kind == "single"
            else {}
        ),
    }
    forecast_id = (
        container.forecast_service.completed_id_for_session(
            dataset_version_id,
            identity_scope,
        )
        if container.forecast_service is not None
        else None
    )
    profit_bridge_id = (
        container.profit_bridge_service.completed_id_for_session(
            dataset_version_id,
            identity_scope,
        )
        if container.profit_bridge_service is not None
        else None
    )
    return ChatPrincipal(
        actor_kind=actor_kind,
        session_id=actor.session_id,
        workspace_id=actor.workspace_id,
        dataset_version_id=dataset_version_id,
        store_ids=resolved.store_ids,
        period_start=date.fromisoformat(release.current_period[0]),
        period_end=date.fromisoformat(release.current_period[1]),
        currency="BRL",
        session_created_at=session_created_at,
        forecast_id=forecast_id,
        profit_bridge_id=profit_bridge_id,
        operator_id=operator_id,
        chat_epoch=chat_epoch,
    )


def _validate_csrf(request: Request, session_id: UUID, actor_kind: str) -> None:
    require_allowed_origin(request)
    token = request.headers.get("X-CSRF-Token")
    container = request.app.state.container
    authority = (
        container.operator_auth_service
        if actor_kind == "operator"
        else container.demo_session_service
    )
    if token is None or authority is None or not authority.csrf_matches(session_id, token):
        raise CsrfValidationError


@router.post("/turns", status_code=201)
def submit_turn(
    payload: ChatTurnRequest,
    request: Request,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    service = _service(request)
    if service is None:
        _log_rejected_turn(request, AIChatUnavailable(), None)
        return _error(AIChatUnavailable(), request)
    principal = None
    try:
        principal = _principal(
            request,
            mutate=True,
            requested_store_ids=payload.store_ids,
        )
        turn = service.submit(
            principal,
            question=payload.question,
            recommended_question_id=payload.recommended_question_id,
            prompt_locale=payload.prompt_locale,
            prompt_template_version=payload.prompt_template_version,
            prompt_template_sha256=payload.prompt_template_sha256,
            context_kind=payload.context.kind if payload.context else None,
            context_reference=payload.context.reference if payload.context else None,
            idempotency_key=idempotency_key,
            request_id=request_id(request.scope),
        )
    except (AuthenticationRequiredError, CsrfValidationError, DemoDataNotImportedError):
        raise
    except Exception as error:
        _log_rejected_turn(request, error, principal, service)
        return _error(error, request)
    telemetry = None
    try:
        telemetry = service.telemetry(
            principal,
            turn.id,
            replayed=turn.replayed,
        )
        log_ai_turn(
            {
                "dataset_version_hash_prefix": telemetry.dataset_version_hash_prefix,
                "error_code": telemetry.error_code,
                "event": "ai_turn",
                "input_tokens": telemetry.input_tokens,
                "output_tokens": telemetry.output_tokens,
                "replayed": telemetry.replayed,
                "request_id": request_id(request.scope),
                "status": telemetry.status,
                "tool_name": telemetry.tool_name,
            }
        )
    except Exception:
        pass
    response.headers.update(PRIVATE_NO_STORE)
    projected = ChatTurnResponse.model_validate(turn, from_attributes=True)
    if telemetry is None:
        return projected
    return projected.model_copy(
        update={
            "provider_audit": ProviderAuditResponse(
                attempt_count=telemetry.provider_attempt_count,
                ledger_attempt_count=telemetry.provider_ledger_count,
                reserved_tokens=telemetry.provider_reserved_tokens,
                ledger_reserved_tokens=(
                    telemetry.provider_ledger_reserved_tokens
                ),
                attempts=telemetry.provider_attempts,
            )
        }
    )


@router.get("/turns")
def list_turns(request: Request, response: Response):
    service = _service(request)
    try:
        principal = _principal(request, mutate=False)
    except (AuthenticationRequiredError, DemoDataNotImportedError):
        raise
    except Exception as error:
        return _error(error, request)
    response.headers.update(PRIVATE_NO_STORE)
    if service is None:
        return ChatTurnListResponse(
            items=(),
            saved_items=(),
            recommended_questions=(
                request.app.state.container.query_catalog.recommended_questions()
            ),
            availability="unavailable",
            unavailable_code="AI_CHAT_UNAVAILABLE",
        )
    try:
        turns = service.list(principal)
        saved_turns = service.list_saved(principal)
    except Exception as error:
        return _error(error, request)
    return ChatTurnListResponse(
        items=tuple(
            ChatTurnResponse.model_validate(turn, from_attributes=True)
            for turn in turns
        ),
        saved_items=tuple(
            ChatTurnResponse.model_validate(turn, from_attributes=True)
            for turn in saved_turns
        ),
        recommended_questions=service.recommended_questions(),
        availability="available",
        unavailable_code=None,
    )


@router.get("/turns/{turn_id}")
def get_turn(turn_id: UUID, request: Request, response: Response):
    service = _service(request)
    if service is None:
        return _error(AIChatUnavailable(), request)
    try:
        principal = _principal(request, mutate=False)
        turn = service.get(principal, turn_id)
    except (AuthenticationRequiredError, DemoDataNotImportedError):
        raise
    except Exception as error:
        return _error(error, request)
    response.headers.update(PRIVATE_NO_STORE)
    return ChatTurnResponse.model_validate(turn, from_attributes=True)


@router.post("/turns/{turn_id}/action-card-drafts")
def create_action_draft(
    turn_id: UUID,
    request: Request,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    service = _service(request)
    if service is None:
        return _error(AIChatUnavailable(), request)
    try:
        principal = _principal(request, mutate=True)
        turn = service.create_action_draft(
            principal,
            turn_id,
            idempotency_key=idempotency_key,
        )
    except (AuthenticationRequiredError, CsrfValidationError, DemoDataNotImportedError):
        raise
    except Exception as error:
        return _error(error, request)
    response.headers.update(PRIVATE_NO_STORE)
    return ChatTurnResponse.model_validate(turn, from_attributes=True)


@router.post("/turns/{turn_id}/save")
def save_turn(turn_id: UUID, request: Request, response: Response):
    service = _service(request)
    if service is None:
        return _error(AIChatUnavailable(), request)
    try:
        principal = _principal(request, mutate=True)
        turn = service.save_answer(principal, turn_id)
    except (AuthenticationRequiredError, CsrfValidationError, DemoDataNotImportedError):
        raise
    except Exception as error:
        return _error(error, request)
    response.headers.update(PRIVATE_NO_STORE)
    return ChatTurnResponse.model_validate(turn, from_attributes=True)


@router.delete("/session")
def delete_chat_session(request: Request, response: Response):
    service = _service(request)
    if service is None:
        return _error(AIChatUnavailable(), request)
    try:
        principal = _principal(request, mutate=True)
        deleted = service.delete_demo_session(principal)
    except (AuthenticationRequiredError, CsrfValidationError, DemoDataNotImportedError):
        raise
    except Exception as error:
        return _error(error, request)
    response.headers.update(PRIVATE_NO_STORE)
    return ChatSessionDeleteResponse(deleted_turns=deleted)
