from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from api.container import ApiContainer
from api.main import create_app
from api.security_policy import SecurityPolicy
from src.config import BizPulseSettings


def _settings(*, cloud: bool = False, body_limit: int = 9 * 1024 * 1024) -> BizPulseSettings:
    return BizPulseSettings(
        runtime_environment="cloud" if cloud else "local",
        database_url="postgresql+psycopg://localhost/bizpulse",
        blob_endpoint=(
            "https://blob.example.test" if cloud else "http://127.0.0.1:10000"
        ),
        blob_container="synthetic-demo",
        allowed_origin="https://demo.test" if cloud else "http://testserver",
        cookie_secure=cloud,
        request_body_limit_bytes=body_limit,
    )


def _client(settings: BizPulseSettings) -> TestClient:
    return TestClient(create_app(container=ApiContainer(settings=settings)))


def test_security_headers_and_request_id_apply_to_html_and_api() -> None:
    with _client(_settings()) as client:
        html = client.get("/")
        api = client.get("/health/live")

    for response in (html, api):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert response.headers["permissions-policy"] == (
            "camera=(), microphone=(), geolocation=()"
        )
        assert response.headers["content-security-policy"] == (
            "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; "
            "object-src 'none'; form-action 'self'; script-src 'self'; "
            "style-src 'self'; img-src 'self' data:; connect-src 'self'"
        )
        request_id = response.headers["x-request-id"]
        assert len(request_id) == 32
        assert all(character in "0123456789abcdef" for character in request_id)
    assert html.headers["cache-control"] == "no-cache"
    assert api.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in html.headers


def test_cloud_adds_hsts_and_rejects_oversized_request_before_routing() -> None:
    settings = replace(_settings(cloud=True), request_body_limit_bytes=128)
    with _client(settings) as client:
        secure = client.get("/", headers={"X-Forwarded-Proto": "https"})
        oversized = client.post(
            "/api/operator/login",
            headers={"Origin": "https://demo.test", "Content-Type": "text/plain"},
            content=b"x" * 129,
        )

    assert secure.headers["strict-transport-security"] == (
        "max-age=31536000; includeSubDomains"
    )
    assert oversized.status_code == 413
    assert oversized.json()["code"] == "REQUEST_TOO_LARGE"
    assert oversized.json()["request_id"] == oversized.headers["x-request-id"]


def test_api_and_error_cache_policy_overrides_unsafe_route_headers() -> None:
    policy = SecurityPolicy(cloud=False, request_body_limit_bytes=128)

    api_headers = policy.response_headers(
        path="/api/v1/example",
        status=200,
        existing={"Cache-Control": "public, max-age=3600"},
    )
    error_headers = policy.response_headers(
        path="/example",
        status=500,
        existing={"Cache-Control": "public, max-age=3600"},
    )

    assert api_headers["Cache-Control"] == "no-store"
    assert error_headers["Cache-Control"] == "no-store"


def test_diagnostic_schema_and_documentation_are_not_public() -> None:
    with _client(_settings()) as client:
        responses = tuple(
            client.get(path) for path in ("/docs", "/redoc", "/openapi.json")
        )

    assert all(response.status_code == 404 for response in responses)
    assert all("swagger" not in response.text.lower() for response in responses)


def test_admin_api_policy_is_private_and_cookie_variant() -> None:
    policy = SecurityPolicy(cloud=False, request_body_limit_bytes=128)

    headers = policy.response_headers(
        path="/api/v1/admin/summary",
        status=200,
        existing={},
    )

    assert headers["Cache-Control"] == "private, no-store"
    assert headers["Vary"] == "Cookie"


def test_every_admin_document_child_is_private_and_cookie_variant() -> None:
    policy = SecurityPolicy(cloud=False, request_body_limit_bytes=128)

    for path, status in (("/admin", 200), ("/admin/future-child", 404)):
        headers = policy.response_headers(
            path=path,
            status=status,
            existing={"Cache-Control": "public, max-age=3600"},
        )

        assert headers["Cache-Control"] == "private, no-store"
        assert headers["Vary"] == "Cookie"
