"""Stable HTTP error responses exposed by the application."""

from __future__ import annotations

from fastapi.responses import JSONResponse

AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"


class AuthenticationRequiredError(Exception):
    """Raised when a protected surface has no valid session."""


class CsrfValidationError(Exception):
    """Raised when Origin or CSRF validation fails closed."""


class DemoDataNotImportedError(Exception):
    """Raised when a Viewer has not activated the shared prepared data."""


def authentication_required() -> JSONResponse:
    """Return the stable unauthenticated response for protected surfaces."""

    return JSONResponse(
        status_code=401,
        content={"code": AUTHENTICATION_REQUIRED},
    )
