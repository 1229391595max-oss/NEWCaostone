"""Fail-closed HTTP security and cache policy."""

from __future__ import annotations

from dataclasses import dataclass

CSP = (
    "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; "
    "object-src 'none'; form-action 'self'; script-src 'self'; "
    "style-src 'self'; img-src 'self' data:; connect-src 'self'"
)
HSTS = "max-age=31536000; includeSubDomains"


@dataclass(frozen=True, slots=True)
class SecurityPolicy:
    """Runtime-specific, value-free response and request limits."""

    cloud: bool
    request_body_limit_bytes: int

    def response_headers(
        self,
        *,
        path: str,
        status: int,
        existing: dict[str, str],
    ) -> dict[str, str]:
        headers = {
            "Content-Security-Policy": CSP,
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        }
        if self.cloud:
            headers["Strict-Transport-Security"] = HSTS
        lower_existing = {name.lower(): value for name, value in existing.items()}
        if (
            path == "/admin"
            or path.startswith("/admin/")
            or path.startswith("/api/v1/admin")
        ):
            headers["Cache-Control"] = "private, no-store"
            headers["Vary"] = "Cookie"
            return headers
        requires_no_store = path.startswith(("/api/", "/health/")) or status >= 400
        existing_cache = lower_existing.get("cache-control", "").lower()
        if requires_no_store and "no-store" not in existing_cache:
            headers["Cache-Control"] = "no-store"
        elif not requires_no_store and "cache-control" not in lower_existing:
            headers["Cache-Control"] = "no-cache"
        return headers
