"""Resolve the protected operator from its opaque cookie."""

from __future__ import annotations

from fastapi import Request

from api.errors import AuthenticationRequiredError
from src.services.operator_auth_service import OperatorPrincipal

OPERATOR_COOKIE = "bp_operator_session"


def resolve_operator(request: Request) -> OperatorPrincipal:
    container = request.app.state.container
    service = container.operator_auth_service
    session_token = request.cookies.get(OPERATOR_COOKIE)
    if service is None or not session_token:
        raise AuthenticationRequiredError
    principal = service.resolve(session_token, service.current_time())
    if principal is None:
        raise AuthenticationRequiredError
    return principal
