from __future__ import annotations

import json
from email.message import Message
from urllib.request import Request

import pytest

from scripts import verify_hosted_health as hosted_health
from scripts.verify_hosted_health import HostedHealthInvalid, verify_hosted_health
from src.db.readiness import EXPECTED_SCHEMA_REVISION


class Response:
    def __init__(
        self, url: str, payload: object, *, content_type: str = "application/json"
    ):
        self.status = 200
        self._url = url
        self._payload = json.dumps(payload).encode()
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, _size: int) -> bytes:
        return self._payload


def test_default_opener_uses_explicit_system_trust_https_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers: list[object] = []
    opened: list[tuple[Request, int]] = []

    class Opener:
        def open(self, request: Request, *, timeout: int):
            opened.append((request, timeout))
            return object()

    def fake_build_opener(*items: object) -> Opener:
        handlers.extend(items)
        return Opener()

    monkeypatch.setattr(hosted_health, "build_opener", fake_build_opener)
    request = Request("https://bp-approved-app.example.azurecontainerapps.io")

    hosted_health._default_opener(request, timeout=5)

    assert len(handlers) == 2
    assert type(handlers[0]).__name__ == "_NoRedirect"
    assert type(handlers[1]).__name__ == "HTTPSHandler"
    assert opened == [(request, 5)]


def test_hosted_health_requires_exact_json_authorities_without_redirect() -> None:
    base = "https://bp-approved-app.example.azurecontainerapps.io"
    payloads = {
        f"{base}/health/live": {"status": "ok"},
        f"{base}/health/ready": {
            "status": "ready",
            "checks": {
                "blob": "ok",
                "configuration": "ok",
                "database": "ok",
                "foundation": "ok",
                "migration": EXPECTED_SCHEMA_REVISION,
            },
        },
    }

    verify_hosted_health(
        base,
        opener=lambda request, **_kwargs: Response(
            request.full_url,
            payloads[request.full_url],
        ),
    )


def test_hosted_health_binds_the_repository_readiness_revision() -> None:
    assert hosted_health.EXPECTED_READY["checks"] == {
        "blob": "ok",
        "configuration": "ok",
        "database": "ok",
        "foundation": "ok",
        "migration": EXPECTED_SCHEMA_REVISION,
    }


def test_hosted_health_rejects_redirect_or_html_success() -> None:
    base = "https://bp-approved-app.example.azurecontainerapps.io"
    with pytest.raises(HostedHealthInvalid, match="hosted_health_url_mismatch"):
        verify_hosted_health(
            base,
            opener=lambda _request, **_kwargs: Response(
                "https://elsewhere.example/health/live",
                {"status": "ok"},
            ),
        )
    with pytest.raises(HostedHealthInvalid, match="hosted_health_content_type_invalid"):
        verify_hosted_health(
            base,
            opener=lambda request, **_kwargs: Response(
                request.full_url,
                {"status": "ok"},
                content_type="text/html",
            ),
        )
