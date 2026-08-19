"""Operator-only boundaries for administrator routes."""

from __future__ import annotations

from fastapi import Request

from api.dependencies.csrf import require_allowed_origin
from api.dependencies.operator import resolve_operator
from api.errors import CsrfValidationError
from src.services.operator_auth_service import OperatorPrincipal


def require_admin_operator(request: Request) -> OperatorPrincipal:
    """Require the existing Operator session for an administrator read."""

    return resolve_operator(request)


def require_admin_mutation(request: Request) -> OperatorPrincipal:
    """Require Operator authority plus same-origin synchronizer-token CSRF."""

    principal = resolve_operator(request)
    require_allowed_origin(request)
    token = request.headers.get("X-CSRF-Token")
    service = request.app.state.container.operator_auth_service
    if token is None or service is None or not service.csrf_matches(
        principal.session_id,
        token,
    ):
        raise CsrfValidationError
    return principal
