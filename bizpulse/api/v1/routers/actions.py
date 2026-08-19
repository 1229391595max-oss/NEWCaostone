"""Operator action-card commands and isolated viewer simulations."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from api.dependencies.csrf import require_demo_csrf, require_operator_csrf
from api.dependencies.operator import resolve_operator
from api.dependencies.session import require_demo_data_imported
from api.v1.schemas.actions import (
    ActionCardResponse,
    ActionCommandRequest,
    ActionCreateRequest,
    ActionExportRequest,
    ActionExportResponse,
    ActionListResponse,
    ActionOutcomeRequest,
    ActionOutcomeResponse,
    DemoActionCommandRequest,
    DemoActionOverlayListResponse,
    DemoActionOverlayResponse,
    DemoActionSandboxResetResponse,
)
from src.actions.contracts import ActionAdjustment, ActionSource, FactRef
from src.actions.state_machine import ActionTransitionInvalid
from src.services.action_service import (
    ActionIdempotencyConflict,
    ActionInvalid,
    ActionNotFound,
    ActionRevisionConflict,
    ActionScopeConflict,
    ActionUnavailable,
)
from src.services.demo_session_service import DemoPrincipal

router = APIRouter(tags=["actions"])
PRIVATE_NO_STORE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


def _service(request: Request):
    return request.app.state.container.action_service


def _error(error: Exception) -> JSONResponse:
    if isinstance(error, ActionNotFound):
        return JSONResponse(status_code=404, content={"code": error.code})
    if isinstance(
        error,
        (ActionRevisionConflict, ActionIdempotencyConflict, ActionScopeConflict),
    ):
        return JSONResponse(status_code=409, content={"code": error.code})
    if isinstance(error, (ActionInvalid, ActionTransitionInvalid)):
        return JSONResponse(status_code=422, content={"code": error.code})
    if isinstance(error, ActionUnavailable):
        return JSONResponse(status_code=503, content={"code": error.code})
    return JSONResponse(status_code=503, content={"code": "ACTION_UNAVAILABLE"})


@router.post(
    "/api/v1/actions",
    dependencies=[Depends(require_operator_csrf)],
)
def create_action(
    payload: ActionCreateRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    service = _service(request)
    if service is None:
        return _error(ActionUnavailable())
    values = payload.source
    source = ActionSource(
        source_type=values.source_type,
        dataset_version_id=values.dataset_version_id,
        suggestion=values.suggestion,
        target=values.target,
        period_start=values.period_start,
        period_end=values.period_end,
        scope=values.scope,
        quantity=values.quantity,
        budget_brl=values.budget_brl,
        action_date=values.action_date,
        threshold=values.threshold,
        expected_impact=values.expected_impact,
        confidence=values.confidence,
        limitations=values.limitations,
        analysis_run_id=values.analysis_run_id,
        forecast_id=values.forecast_id,
        bridge_id=values.bridge_id,
        chat_turn_id=values.chat_turn_id,
        chat_tool=values.chat_tool,
        answer_version=values.answer_version,
    )
    try:
        card = service.create_draft(
            source,
            tuple(FactRef(**item.model_dump()) for item in payload.facts),
            idempotency_key,
        )
    except Exception as error:
        return _error(error)
    return ActionCardResponse.model_validate(card, from_attributes=True)


@router.get("/api/v1/actions", dependencies=[Depends(resolve_operator)])
def list_actions(
    request: Request,
    response: Response,
    dataset_version_id: UUID = Query(),
    store_id: list[str] | None = Query(default=None),
):
    service = _service(request)
    if service is None:
        return _error(ActionUnavailable())
    try:
        items = service.list(dataset_version_id, _scope(store_id))
    except Exception as error:
        return _error(error)
    response.headers.update(PRIVATE_NO_STORE)
    return ActionListResponse(
        items=tuple(
            ActionCardResponse.model_validate(item, from_attributes=True)
            for item in items
        )
    )


@router.get("/api/v1/actions/{action_id}", dependencies=[Depends(resolve_operator)])
def get_action(action_id: UUID, request: Request, response: Response):
    service = _service(request)
    if service is None:
        return _error(ActionUnavailable())
    try:
        card = service.get(action_id)
    except Exception as error:
        return _error(error)
    response.headers.update(PRIVATE_NO_STORE)
    return ActionCardResponse.model_validate(card, from_attributes=True)


@router.post(
    "/api/v1/actions/{action_id}/commands",
    dependencies=[Depends(require_operator_csrf)],
)
def command_action(
    action_id: UUID,
    payload: ActionCommandRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    service = _service(request)
    if service is None:
        return _error(ActionUnavailable())
    try:
        service.require_scope(
            action_id,
            payload.dataset_version_id,
            _scope(payload.store_ids),
        )
        if payload.command == "adjust":
            assert payload.adjustment is not None
            card = service.adjust(
                action_id,
                payload.revision,
                ActionAdjustment(**payload.adjustment.model_dump()),
                payload.reason,
                idempotency_key,
            )
        else:
            card = getattr(service, payload.command)(
                action_id,
                payload.revision,
                payload.reason,
                idempotency_key,
            )
    except Exception as error:
        return _error(error)
    return ActionCardResponse.model_validate(card, from_attributes=True)


@router.post(
    "/api/v1/actions/{action_id}/exports",
    dependencies=[Depends(require_operator_csrf)],
)
def export_action(
    action_id: UUID,
    payload: ActionExportRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    service = _service(request)
    if service is None:
        return _error(ActionUnavailable())
    try:
        service.require_scope(
            action_id,
            payload.dataset_version_id,
            _scope(payload.store_ids),
        )
        exported = service.export(
            action_id,
            payload.revision,
            idempotency_key,
            payload.format,
        )
    except Exception as error:
        return _error(error)
    return ActionExportResponse.model_validate(exported, from_attributes=True)


@router.get(
    "/api/v1/actions/{action_id}/exports/{export_id}/download",
    dependencies=[Depends(resolve_operator)],
)
def download_action_export(
    action_id: UUID,
    export_id: UUID,
    request: Request,
):
    service = _service(request)
    if service is None:
        return _error(ActionUnavailable())
    try:
        content = service.open_export(action_id, export_id)
    except Exception as error:
        return _error(error)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": (
                f'attachment; filename="SYNTH-ACTION-{action_id}.xlsx"'
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/api/v1/actions/{action_id}/outcomes",
    dependencies=[Depends(require_operator_csrf)],
)
def outcome_action(
    action_id: UUID,
    payload: ActionOutcomeRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    service = _service(request)
    if service is None:
        return _error(ActionUnavailable())
    try:
        service.require_scope(
            action_id,
            payload.dataset_version_id,
            _scope(payload.store_ids),
        )
        outcome = service.record_outcome(
            action_id,
            payload.revision,
            review_date=payload.review_date,
            synthetic_result=payload.synthetic_result,
            evidence=tuple(FactRef(**item.model_dump()) for item in payload.evidence),
            conclusion=payload.conclusion,
            reason=payload.reason,
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        return _error(error)
    return ActionOutcomeResponse.model_validate(outcome, from_attributes=True)


@router.get("/api/demo/release/actions")
def public_actions(
    request: Request,
    response: Response,
    principal: DemoPrincipal = Depends(require_demo_data_imported),
    store_id: list[str] | None = Query(default=None),
):
    service = _service(request)
    if service is None or principal.dataset_version_id is None:
        return _error(ActionUnavailable())
    try:
        items = service.list_public(
            principal.dataset_version_id,
            principal.created_at,
            _scope(store_id),
        )
    except Exception as error:
        return _error(error)
    response.headers.update(PRIVATE_NO_STORE)
    return ActionListResponse(
        items=tuple(
            ActionCardResponse.model_validate(item, from_attributes=True)
            for item in items
        )
    )


def _scope(store_ids: list[str] | None) -> dict[str, object]:
    if store_ids is not None and len(store_ids) > 1:
        raise ActionInvalid("scope_store_invalid")
    return {
        "currency": "BRL",
        **({"store_id": store_ids[0]} if store_ids else {}),
    }


@router.post(
    "/api/demo/actions/{action_id}/commands",
    dependencies=[Depends(require_demo_csrf)],
)
def simulate_action(
    action_id: UUID,
    payload: DemoActionCommandRequest,
    request: Request,
    principal: DemoPrincipal = Depends(require_demo_data_imported),
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    service = _service(request)
    if service is None or principal.dataset_version_id is None:
        return _error(ActionUnavailable())
    try:
        service.require_scope(
            action_id,
            principal.dataset_version_id,
            _scope(payload.store_ids),
        )
        overlay = service.simulate(
            session_id=principal.session_id,
            expected_chat_epoch=principal.chat_epoch,
            dataset_version_id=principal.dataset_version_id,
            action_id=action_id,
            base_revision=payload.base_revision,
            command=payload.command,
            adjustment=(
                payload.adjustment.values_dict()
                if payload.adjustment is not None
                else {}
            ),
            reason=payload.reason,
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        return _error(error)
    return DemoActionOverlayResponse.model_validate(overlay, from_attributes=True)


@router.get("/api/demo/actions/{action_id}/overlays")
def action_overlays(
    action_id: UUID,
    request: Request,
    response: Response,
    principal: DemoPrincipal = Depends(require_demo_data_imported),
    store_id: list[str] | None = Query(default=None),
):
    service = _service(request)
    if service is None:
        return _error(ActionUnavailable())
    try:
        if principal.dataset_version_id is None:
            raise ActionUnavailable()
        service.require_scope(
            action_id,
            principal.dataset_version_id,
            _scope(store_id),
        )
        overlays = service.overlays(principal.session_id, action_id)
    except Exception as error:
        return _error(error)
    response.headers.update(PRIVATE_NO_STORE)
    return DemoActionOverlayListResponse(
        items=tuple(
            DemoActionOverlayResponse.model_validate(item, from_attributes=True)
            for item in overlays
        )
    )


@router.delete(
    "/api/demo/action-sandbox",
    dependencies=[Depends(require_demo_csrf)],
)
def reset_action_sandbox(
    request: Request,
    principal: DemoPrincipal = Depends(require_demo_data_imported),
    store_id: list[str] | None = Query(default=None),
):
    service = _service(request)
    if service is None or principal.dataset_version_id is None:
        return _error(ActionUnavailable())
    try:
        deleted = service.reset_simulation(
            session_id=principal.session_id,
            expected_chat_epoch=principal.chat_epoch,
            dataset_version_id=principal.dataset_version_id,
            scope=_scope(store_id),
        )
    except Exception as error:
        return _error(error)
    return DemoActionSandboxResetResponse(deleted_overlays=deleted)
