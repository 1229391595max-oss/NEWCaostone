"""Resolve the anonymous viewer from its opaque cookie."""

from __future__ import annotations

from fastapi import Depends, Request

from api.errors import AuthenticationRequiredError, DemoDataNotImportedError
from src.services.demo_session_service import DemoPrincipal

DEMO_COOKIE = "bp_demo_session"


def resolve_demo_session(request: Request) -> DemoPrincipal:
    container = request.app.state.container
    service = container.demo_session_service
    session_token = request.cookies.get(DEMO_COOKIE)
    if service is None or not session_token:
        raise AuthenticationRequiredError
    principal = service.resolve(session_token, service.current_time())
    if principal is None:
        raise AuthenticationRequiredError
    return principal


def require_demo_data_imported(
    principal: DemoPrincipal = Depends(resolve_demo_session),
) -> DemoPrincipal:
    if principal.demo_data_imported_at is None:
        raise DemoDataNotImportedError
    return principal
