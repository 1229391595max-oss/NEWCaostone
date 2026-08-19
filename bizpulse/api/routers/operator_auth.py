"""Single-operator login and logout routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, SecretStr, StringConstraints
from typing_extensions import Annotated

from api.dependencies.csrf import require_allowed_origin, require_operator_csrf
from api.dependencies.operator import OPERATOR_COOKIE
from src.services.operator_auth_service import (
    AuthenticationFailed,
    AuthenticationRateLimited,
    OperatorPrincipal,
    RequestMeta,
)

router = APIRouter(prefix="/api/operator", tags=["operator-auth"])


class LoginRequest(BaseModel):
    login_name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    password: SecretStr


def isoformat_utc(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


@router.post("/login", status_code=201)
def login(payload: LoginRequest, request: Request, response: Response):
    require_allowed_origin(request)
    service = request.app.state.container.operator_auth_service
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    source = request.client.host if request.client is not None else "unknown"
    try:
        issued = service.login(
            payload.login_name,
            payload.password,
            RequestMeta(
                source_address_hash=service.source_address_fingerprint(source),
                now=service.current_time(),
            ),
        )
    except AuthenticationRateLimited:
        return JSONResponse(status_code=429, content={"code": "RATE_LIMITED"})
    except AuthenticationFailed:
        return JSONResponse(
            status_code=401,
            content={"code": "AUTHENTICATION_FAILED"},
        )

    response.set_cookie(
        key=OPERATOR_COOKIE,
        value=issued.session_token,
        max_age=7_200,
        httponly=True,
        secure=request.app.state.container.settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return {
        "csrf_token": issued.csrf_token,
        "operator": {
            "operator_id": str(issued.principal.operator_id),
            "workspace_id": issued.principal.workspace_id,
            "login_name": issued.principal.login_name,
            "idle_expires_at": isoformat_utc(issued.principal.idle_expires_at),
            "absolute_expires_at": isoformat_utc(
                issued.principal.absolute_expires_at
            ),
        },
    }


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    principal: OperatorPrincipal = Depends(require_operator_csrf),
) -> None:
    service = request.app.state.container.operator_auth_service
    service.logout(principal.session_id, service.current_time())
    response.set_cookie(
        key=OPERATOR_COOKIE,
        value="",
        max_age=0,
        expires=0,
        httponly=True,
        secure=request.app.state.container.settings.cookie_secure,
        samesite="lax",
        path="/",
    )
