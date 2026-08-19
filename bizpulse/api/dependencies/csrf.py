"""Strict same-origin and synchronizer-token checks."""

from __future__ import annotations

import hmac

from fastapi import Depends, Request

from api.dependencies.operator import resolve_operator
from api.dependencies.session import resolve_demo_session
from api.errors import CsrfValidationError
from src.services.demo_session_service import DemoPrincipal
from src.services.operator_auth_service import OperatorPrincipal


def require_allowed_origin(request: Request) -> None:
    origin = request.headers.get("Origin")
    allowed_origin = request.app.state.container.settings.allowed_origin
    if origin is None or not hmac.compare_digest(origin, allowed_origin):
        raise CsrfValidationError


def require_operator_csrf(
    request: Request,
    principal: OperatorPrincipal = Depends(resolve_operator),
) -> OperatorPrincipal:
    require_allowed_origin(request)
    token = request.headers.get("X-CSRF-Token")
    service = request.app.state.container.operator_auth_service
    if token is None or service is None or not service.csrf_matches(principal.session_id, token):
        raise CsrfValidationError
    return principal


def require_demo_csrf(
    request: Request,
    principal: DemoPrincipal = Depends(resolve_demo_session),
) -> DemoPrincipal:
    require_allowed_origin(request)
    token = request.headers.get("X-CSRF-Token")
    service = request.app.state.container.demo_session_service
    if token is None or service is None or not service.csrf_matches(principal.session_id, token):
        raise CsrfValidationError
    return principal
