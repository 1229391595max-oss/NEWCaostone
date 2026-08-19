"""Authenticated Operator Settings endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from api.dependencies.csrf import require_operator_csrf
from api.dependencies.operator import resolve_operator
from api.v1.schemas.preferences import (
    AiConnectionStatus,
    PreferencePermissions,
    PreferenceUpdate,
    SavedViewCreate,
    SavedViewResponse,
    SavedViewUpdate,
    SettingsResponse,
    TargetCreate,
    TargetResponse,
    TargetStatusUpdate,
)
from src.services.operator_auth_service import OperatorPrincipal
from src.services.preferences_service import PreferenceRevisionConflict

router = APIRouter(prefix="/preferences", tags=["preferences"])
PRIVATE_NO_STORE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


def _service(request: Request):
    return request.app.state.container.preferences_service


def _ai_status(request: Request) -> AiConnectionStatus:
    container = request.app.state.container
    if container.ai_chat_service is not None:
        return AiConnectionStatus(status="available")
    if not container.settings.ai_chat_enabled:
        return AiConnectionStatus(status="disabled", limitation_code="ai_not_configured")
    return AiConnectionStatus(status="unavailable", limitation_code="ai_temporarily_unavailable")


def _settings_response(request: Request, principal: OperatorPrincipal) -> SettingsResponse:
    service = _service(request)
    return SettingsResponse(
        preferences=service.get_preferences(principal.operator_id),
        saved_views=service.list_saved_views(principal.operator_id),
        targets=service.list_targets(principal.operator_id),
        ai=_ai_status(request),
        permissions=PreferencePermissions(
            reporting_defaults="editable", targets="editable", persistence="server",
        ),
    )


@router.get("")
def get_settings(
    request: Request,
    response: Response,
    principal: OperatorPrincipal = Depends(resolve_operator),
):
    if _service(request) is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    response.headers.update(PRIVATE_NO_STORE)
    return _settings_response(request, principal)


@router.put("")
def put_settings(
    payload: PreferenceUpdate,
    request: Request,
    response: Response,
    principal: OperatorPrincipal = Depends(require_operator_csrf),
):
    if _service(request) is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    try:
        saved = _service(request).save_preferences(
            principal.operator_id,
            expected_revision=payload.expected_revision,
            document=payload.preferences.model_dump(),
        )
    except PreferenceRevisionConflict as error:
        return JSONResponse(status_code=409, content={"code": error.code})
    response.headers.update(PRIVATE_NO_STORE)
    return {"preferences": saved}


@router.post("/saved-views", status_code=201)
def create_saved_view(
    payload: SavedViewCreate,
    request: Request,
    principal: OperatorPrincipal = Depends(require_operator_csrf),
):
    result = _service(request).create_saved_view(
        principal.operator_id,
        name=payload.name.strip(),
        kind=payload.kind,
        config=payload.config.model_dump(exclude_none=True),
    )
    return SavedViewResponse.model_validate(result)


@router.put("/saved-views/{view_id}")
def update_saved_view(
    view_id: UUID,
    payload: SavedViewUpdate,
    request: Request,
    principal: OperatorPrincipal = Depends(require_operator_csrf),
):
    try:
        result = _service(request).update_saved_view(
            principal.operator_id,
            view_id,
            expected_revision=payload.expected_revision,
            name=payload.name.strip(),
            config=payload.config.model_dump(exclude_none=True),
        )
    except PreferenceRevisionConflict as error:
        return JSONResponse(status_code=409, content={"code": error.code})
    return SavedViewResponse.model_validate(result)


@router.delete("/saved-views/{view_id}", status_code=204)
def delete_saved_view(
    view_id: UUID,
    request: Request,
    expected_revision: int = Query(ge=1),
    principal: OperatorPrincipal = Depends(require_operator_csrf),
):
    try:
        _service(request).delete_saved_view(
            principal.operator_id, view_id, expected_revision=expected_revision,
        )
    except PreferenceRevisionConflict as error:
        return JSONResponse(status_code=409, content={"code": error.code})


@router.post("/targets", status_code=201)
def create_target(
    payload: TargetCreate,
    request: Request,
    principal: OperatorPrincipal = Depends(require_operator_csrf),
):
    result = _service(request).create_target(
        principal.operator_id, **payload.model_dump(),
    )
    return TargetResponse.model_validate(result)


@router.patch("/targets/{target_id}")
def update_target_status(
    target_id: UUID,
    payload: TargetStatusUpdate,
    request: Request,
    principal: OperatorPrincipal = Depends(require_operator_csrf),
):
    try:
        result = _service(request).set_target_status(
            principal.operator_id,
            target_id,
            expected_revision=payload.expected_revision,
            status=payload.status,
        )
    except PreferenceRevisionConflict as error:
        return JSONResponse(status_code=409, content={"code": error.code})
    return TargetResponse.model_validate(result)
