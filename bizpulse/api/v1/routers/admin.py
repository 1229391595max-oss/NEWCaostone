"""Operator-only administrator summary and AI control routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import SecretStr

from api.dependencies.admin import require_admin_mutation, require_admin_operator
from api.request_context import request_id, set_safe_error_code
from api.v1.schemas.admin import (
    AIChannelsUpdateRequest,
    AIControlResponse,
    AICredentialProjection,
    AIKeyRotationRequest,
    AIKeyRotationResponse,
    AIMutationAuditListResponse,
    AITurnBindingAuditListResponse,
    AdminSummaryResponse,
)
from src.repositories.admin_ai import AIControlBusy
from src.services.admin_summary_service import project_ai_control
from src.services.ai_control_service import (
    AIControlAvailabilityFailed,
    AIControlUnavailable,
    AIReauthenticationFailed,
    AIStateConflict,
)
from src.services.openai_key_rotation_service import AIKeyRotationFailed
from src.services.operator_auth_service import (
    AuthenticationRateLimited,
    OperatorPrincipal,
    RequestMeta,
)

router = APIRouter(prefix="/admin", tags=["admin"])
PRIVATE_NO_STORE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
_ERROR_STATUS = {
    "ADMIN_AI_STATE_CONFLICT": 409,
    "ADMIN_AI_OPERATION_BUSY": 409,
    "ADMIN_AI_KEY_REJECTED": 422,
    "ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN": 503,
    "ADMIN_AI_SECRET_UNAVAILABLE": 503,
    "ADMIN_AI_RECONCILIATION_REQUIRED": 503,
    "ADMIN_REAUTHENTICATION_FAILED": 401,
    "RATE_LIMITED": 429,
}


def _control_response(state) -> AIControlResponse:
    safe = project_ai_control(state)
    assert safe.revision is not None
    return AIControlResponse(
        revision=safe.revision,
        operator_enabled=safe.operator_enabled,
        demo_enabled=safe.demo_enabled,
        credential=AICredentialProjection.model_validate(
            safe.credential,
            from_attributes=True,
        ),
    )


def _request_meta(request: Request) -> RequestMeta:
    service = request.app.state.container.operator_auth_service
    source = request.client.host if request.client is not None else "unknown"
    return RequestMeta(
        source_address_hash=service.source_address_fingerprint(source),
        now=service.current_time(),
    )


def _error(error: Exception, request: Request, service=None) -> JSONResponse:
    if isinstance(error, AIStateConflict):
        code = "ADMIN_AI_STATE_CONFLICT"
    elif isinstance(error, AIControlBusy):
        code = "ADMIN_AI_OPERATION_BUSY"
    elif isinstance(error, AIReauthenticationFailed):
        code = "ADMIN_REAUTHENTICATION_FAILED"
    elif isinstance(error, AuthenticationRateLimited):
        code = "RATE_LIMITED"
    elif isinstance(error, (AIControlAvailabilityFailed, AIKeyRotationFailed)):
        code = error.code
    elif isinstance(error, AIControlUnavailable):
        code = "ADMIN_AI_SECRET_UNAVAILABLE"
    else:
        code = "ADMIN_AI_SECRET_UNAVAILABLE"
    if code not in _ERROR_STATUS:
        code = "ADMIN_AI_SECRET_UNAVAILABLE"
    set_safe_error_code(request.scope, code)
    content: dict[str, object] = {"code": code}
    if code == "ADMIN_AI_STATE_CONFLICT" and service is not None:
        try:
            content["current"] = jsonable_encoder(_control_response(service.get()))
        except Exception:
            pass
    return JSONResponse(
        status_code=_ERROR_STATUS[code],
        content=content,
        headers=PRIVATE_NO_STORE,
    )


@router.get("/summary", response_model=AdminSummaryResponse)
def summary(
    request: Request,
    response: Response,
    _: OperatorPrincipal = Depends(require_admin_operator),
):
    del _
    response.headers.update(PRIVATE_NO_STORE)
    service = request.app.state.container.admin_summary_service
    if service is None:
        return _error(AIControlUnavailable(), request)
    try:
        return service.get()
    except Exception as error:
        return _error(error, request)


@router.get("/ai", response_model=AIControlResponse)
def ai_control(
    request: Request,
    response: Response,
    _: OperatorPrincipal = Depends(require_admin_operator),
):
    del _
    response.headers.update(PRIVATE_NO_STORE)
    service = request.app.state.container.ai_control_service
    if service is None:
        return _error(AIControlUnavailable(), request)
    try:
        return _control_response(service.get())
    except Exception as error:
        return _error(error, request, service)


@router.get(
    "/ai/turn-bindings",
    response_model=AITurnBindingAuditListResponse,
)
def ai_turn_bindings(
    request: Request,
    response: Response,
    turn_id: list[UUID] = Query(min_length=1, max_length=2),
    _: OperatorPrincipal = Depends(require_admin_operator),
):
    del _
    response.headers.update(PRIVATE_NO_STORE)
    service = request.app.state.container.ai_chat_service
    if service is None:
        return _error(AIControlUnavailable(), request)
    try:
        items = service.credential_binding_audit(tuple(turn_id))
    except Exception as error:
        return _error(error, request)
    if len(items) != len(turn_id):
        return _error(AIControlUnavailable(), request)
    return AITurnBindingAuditListResponse(items=items)


@router.get(
    "/ai/audit-events",
    response_model=AIMutationAuditListResponse,
)
def ai_mutation_audit(
    request: Request,
    response: Response,
    request_id: list[str] = Query(min_length=1, max_length=16),
    _: OperatorPrincipal = Depends(require_admin_operator),
):
    del _
    response.headers.update(PRIVATE_NO_STORE)
    service = request.app.state.container.ai_control_service
    if service is None:
        return _error(AIControlUnavailable(), request)
    try:
        items = service.mutation_audit(tuple(request_id))
    except Exception as error:
        return _error(error, request)
    if len(items) != len(request_id):
        return _error(AIControlUnavailable(), request)
    return AIMutationAuditListResponse(items=items)


@router.patch("/ai/channels", response_model=AIControlResponse)
def update_channels(
    payload: AIChannelsUpdateRequest,
    request: Request,
    response: Response,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
    ),
    principal: OperatorPrincipal = Depends(require_admin_mutation),
):
    response.headers.update(PRIVATE_NO_STORE)
    service = request.app.state.container.ai_control_service
    if service is None:
        return _error(AIControlUnavailable(), request)
    password = payload.current_password
    payload.current_password = SecretStr("")
    try:
        changed = service.set_channels(
            principal=principal,
            current_password=password,
            request_meta=_request_meta(request),
            expected_revision=payload.expected_revision,
            operator_enabled=payload.operator_enabled,
            demo_enabled=payload.demo_enabled,
            request_id=request_id(request.scope),
            idempotency_key=idempotency_key,
        )
        return _control_response(changed)
    except Exception as error:
        return _error(error, request, service)
    finally:
        password = SecretStr("")


@router.post("/ai/key-rotations", response_model=AIKeyRotationResponse)
def rotate_key(
    payload: AIKeyRotationRequest,
    request: Request,
    response: Response,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
    ),
    principal: OperatorPrincipal = Depends(require_admin_mutation),
):
    response.headers.update(PRIVATE_NO_STORE)
    service = request.app.state.container.openai_key_rotation_service
    if service is None:
        return _error(AIControlUnavailable(), request)
    password = payload.current_password
    candidate = payload.candidate_key
    payload.current_password = SecretStr("")
    payload.candidate_key = SecretStr("")
    try:
        changed = service.rotate(
            principal=principal,
            current_password=password,
            request_meta=_request_meta(request),
            candidate=candidate,
            expected_revision=payload.expected_revision,
            request_id=request_id(request.scope),
            idempotency_key=idempotency_key,
        )
        projected = _control_response(changed)
        return AIKeyRotationResponse(
            revision=projected.revision,
            credential=projected.credential,
            result_code="ADMIN_AI_KEY_ROTATED",
        )
    except Exception as error:
        return _error(
            error,
            request,
            request.app.state.container.ai_control_service,
        )
    finally:
        password = SecretStr("")
        candidate = SecretStr("")
