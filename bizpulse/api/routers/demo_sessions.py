"""Anonymous viewer-session routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from api.dependencies.csrf import require_allowed_origin, require_demo_csrf
from api.dependencies.session import DEMO_COOKIE, resolve_demo_session
from api.errors import AuthenticationRequiredError
from api.request_context import set_safe_error_code
from src.services.demo_session_service import (
    DemoPrincipal,
    DemoSessionRateLimited,
    PublicReleaseUnavailable,
)

router = APIRouter(prefix="/api/demo/sessions", tags=["demo-sessions"])
PRIVATE_NO_STORE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


def isoformat_utc(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


def principal_payload(principal: DemoPrincipal) -> dict[str, object]:
    return {
        "session_id": str(principal.session_id),
        "workspace_id": principal.workspace_id,
        "dataset_version_id": (
            str(principal.dataset_version_id)
            if principal.dataset_version_id is not None
            else None
        ),
        "status": principal.status,
        "demo_data_imported": principal.demo_data_imported_at is not None,
        "demo_data_imported_at": (
            isoformat_utc(principal.demo_data_imported_at)
            if principal.demo_data_imported_at is not None
            else None
        ),
        "idle_expires_at": isoformat_utc(principal.idle_expires_at),
        "absolute_expires_at": isoformat_utc(principal.absolute_expires_at),
    }


@router.post("", status_code=201)
def create_demo_session(request: Request, response: Response):
    require_allowed_origin(request)
    service = request.app.state.container.demo_session_service
    if service is None:
        set_safe_error_code(request.scope, "SERVICE_UNAVAILABLE")
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    source = request.client.host if request.client is not None else "unknown"
    try:
        issued = service.create(
            service.source_address_fingerprint(source),
            service.current_time(),
        )
    except PublicReleaseUnavailable as error:
        set_safe_error_code(request.scope, error.code)
        return JSONResponse(status_code=503, content={"code": error.code})
    except DemoSessionRateLimited as error:
        set_safe_error_code(request.scope, error.code)
        return JSONResponse(status_code=429, content={"code": error.code})
    response.set_cookie(
        key=DEMO_COOKIE,
        value=issued.session_token,
        max_age=7_200,
        httponly=True,
        secure=request.app.state.container.settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.headers.update(PRIVATE_NO_STORE)
    return {
        "csrf_token": issued.csrf_token,
        "session": principal_payload(issued.principal),
    }


@router.get("/current")
def current_demo_session(
    response: Response,
    principal: DemoPrincipal = Depends(resolve_demo_session),
) -> dict[str, object]:
    response.headers.update(PRIVATE_NO_STORE)
    return {"session": principal_payload(principal)}


@router.post("/current/import-demo-data")
def import_demo_data(
    request: Request,
    response: Response,
    principal: DemoPrincipal = Depends(require_demo_csrf),
) -> dict[str, object]:
    service = request.app.state.container.demo_session_service
    imported = service.import_demo_data(principal.session_id, service.current_time())
    if imported is None:
        raise AuthenticationRequiredError
    response.headers.update(PRIVATE_NO_STORE)
    return {"session": principal_payload(imported)}


@router.delete("", status_code=204)
def end_demo_session(
    request: Request,
    response: Response,
    principal: DemoPrincipal = Depends(require_demo_csrf),
) -> None:
    service = request.app.state.container.demo_session_service
    service.end(principal.session_id, service.current_time())
    response.set_cookie(
        key=DEMO_COOKIE,
        value="",
        max_age=0,
        expires=0,
        httponly=True,
        secure=request.app.state.container.settings.cookie_secure,
        samesite="lax",
        path="/",
    )
