"""Opaque request correlation, bounded bodies, safe errors, and telemetry."""

from __future__ import annotations

import re
from time import perf_counter
from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.security_policy import SecurityPolicy
from src.observability import log_http_request


class RequestBodyTooLarge(RuntimeError):
    """Raised before an oversized body reaches a route."""


class RequestContextMiddleware:
    """Apply the complete HTTP boundary without inspecting request payloads."""

    def __init__(self, app: ASGIApp, *, policy: SecurityPolicy) -> None:
        self._app = app
        self._policy = policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = uuid4().hex
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        path = str(scope.get("path", ""))
        method = str(scope.get("method", "UNKNOWN"))
        started_at = perf_counter()
        status = 500
        error_code: str | None = None
        response_started = False
        received_bytes = 0

        async def bounded_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self._policy.request_body_limit_bytes:
                    raise RequestBodyTooLarge
            return message

        async def secure_send(message: Message) -> None:
            nonlocal error_code, response_started, status
            if message["type"] == "http.response.start":
                response_started = True
                status = int(message["status"])
                safe_code = state.get("safe_error_code")
                if safe_code is not None:
                    error_code = str(safe_code)
                if status >= 400 and error_code is None:
                    error_code = f"HTTP_{status}"
                existing = {
                    name.decode("latin-1"): value.decode("latin-1")
                    for name, value in message.get("headers", [])
                }
                additions = self._policy.response_headers(
                    path=path,
                    status=status,
                    existing=existing,
                )
                additions["X-Request-ID"] = request_id
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower()
                    not in {header.lower().encode("latin-1") for header in additions}
                ]
                headers.extend(
                    (name.encode("latin-1"), value.encode("latin-1"))
                    for name, value in additions.items()
                )
                message = {**message, "headers": headers}
            await send(message)

        try:
            content_length = _content_length(scope)
            if content_length is not None and (
                content_length > self._policy.request_body_limit_bytes
            ):
                raise RequestBodyTooLarge
            await self._app(scope, bounded_receive, secure_send)
        except RequestBodyTooLarge:
            error_code = "REQUEST_TOO_LARGE"
            if response_started:
                raise
            await _safe_error(
                scope,
                bounded_receive,
                secure_send,
                status_code=413,
                code="REQUEST_TOO_LARGE",
                request_id=request_id,
            )
        except Exception:
            error_code = "INTERNAL_ERROR"
            if response_started:
                raise
            await _safe_error(
                scope,
                bounded_receive,
                secure_send,
                status_code=500,
                code="INTERNAL_ERROR",
                request_id=request_id,
            )
        finally:
            route = scope.get("route")
            route_template = getattr(route, "path", "<unmatched>")
            log_http_request(
                {
                    "duration_ms": max(0, int((perf_counter() - started_at) * 1000)),
                    "error_code": error_code,
                    "event": "http_request",
                    "method": method,
                    "request_id": request_id,
                    "route": route_template,
                    "status": status,
                }
            )


def request_id(scope: Scope) -> str:
    """Read the current opaque request ID without accepting a client value."""

    return str(scope.get("state", {}).get("request_id", ""))


def set_safe_error_code(scope: Scope, code: str) -> None:
    """Attach only a stable value-free code for the outer request log."""

    if re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", code) is None:
        raise ValueError("safe_error_code_invalid")
    scope.setdefault("state", {})["safe_error_code"] = code


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name.lower() != b"content-length":
            continue
        try:
            parsed = int(value)
        except ValueError as error:
            raise RequestBodyTooLarge from error
        if parsed < 0:
            raise RequestBodyTooLarge
        return parsed
    return None


async def _safe_error(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    status_code: int,
    code: str,
    request_id: str,
) -> None:
    response = JSONResponse(
        status_code=status_code,
        content={"code": code, "request_id": request_id},
    )
    await response(scope, receive, send)
