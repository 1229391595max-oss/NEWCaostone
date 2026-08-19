from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scripts.verify_hosted_expiry import (
    HostedExpiryInvalid,
    verify_hosted_expiry,
)


class _Response:
    def __init__(self, status_code: int, payload: dict[str, object] | None = None):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        if self._payload is None:
            raise ValueError("no_json")
        return self._payload


class _Client:
    def __init__(self, responses: list[_Response]):
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, str] | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, url: str, *, headers: dict[str, str]):
        self.calls.append(("POST", url, headers))
        return self.responses.pop(0)

    def get(self, url: str):
        self.calls.append(("GET", url, None))
        return self.responses.pop(0)

    def delete(self, url: str, *, headers: dict[str, str]):
        self.calls.append(("DELETE", url, headers))
        return self.responses.pop(0)


def _session(session_id: str, csrf: str, expires_at: str) -> _Response:
    return _Response(
        201,
        {
            "csrf_token": csrf,
            "session": {
                "session_id": session_id,
                "idle_expires_at": expires_at,
            },
        },
    )


def test_hosted_expiry_waits_for_product_ttl_and_proves_cleanup() -> None:
    client = _Client(
        [
            _session(
                "11111111-1111-4111-8111-111111111111",
                "csrf-old-token-1234567890",
                "2026-08-14T12:30:00Z",
            ),
            _Response(401, {"code": "DEMO_SESSION_INVALID"}),
            _session(
                "22222222-2222-4222-8222-222222222222",
                "csrf-new-token-1234567890",
                "2026-08-14T13:01:00Z",
            ),
            _Response(204),
        ]
    )
    sleeps: list[float] = []
    jobs: list[dict[str, object]] = []

    verify_hosted_expiry(
        "https://bp.example.test",
        subscription_id="33333333-3333-4333-8333-333333333333",
        resource_group="rg-approved",
        session_job="bp-approved-sessions",
        client_factory=lambda **_kwargs: client,
        wall_clock=lambda: datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
        sleeper=sleeps.append,
        job_runner=lambda **kwargs: jobs.append(kwargs) or "execution-1",
    )

    assert sleeps == [1860.0]
    assert jobs == [
        {
            "subscription_id": "33333333-3333-4333-8333-333333333333",
            "resource_group": "rg-approved",
            "job_name": "bp-approved-sessions",
            "timeout_seconds": 600,
        }
    ]
    assert [call[0] for call in client.calls] == ["POST", "GET", "POST", "DELETE"]
    assert client.calls[-1][2] == {
        "Origin": "https://bp.example.test",
        "X-CSRF-Token": "csrf-new-token-1234567890",
    }


@pytest.mark.parametrize(
    ("url", "expires_at"),
    [
        ("http://bp.example.test", "2026-08-14T12:30:00Z"),
        ("https://bp.example.test", "2026-08-14T11:59:00Z"),
        ("https://bp.example.test", "2026-08-14T13:00:01Z"),
    ],
)
def test_hosted_expiry_rejects_invalid_authority_or_ttl(
    url: str,
    expires_at: str,
) -> None:
    client = _Client(
        [
            _session(
                "11111111-1111-4111-8111-111111111111",
                "csrf-old-token-1234567890",
                expires_at,
            )
        ]
    )
    with pytest.raises(HostedExpiryInvalid):
        verify_hosted_expiry(
            url,
            subscription_id="33333333-3333-4333-8333-333333333333",
            resource_group="rg-approved",
            session_job="bp-approved-sessions",
            client_factory=lambda **_kwargs: client,
            wall_clock=lambda: datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
            sleeper=lambda _seconds: None,
            job_runner=lambda **_kwargs: "execution-1",
        )


def test_hosted_expiry_requires_expired_cookie_and_fresh_session() -> None:
    client = _Client(
        [
            _session(
                "11111111-1111-4111-8111-111111111111",
                "csrf-old-token-1234567890",
                "2026-08-14T12:30:00Z",
            ),
            _Response(200, {"session": {}}),
        ]
    )
    with pytest.raises(HostedExpiryInvalid, match="hosted_expiry_not_enforced"):
        verify_hosted_expiry(
            "https://bp.example.test",
            subscription_id="33333333-3333-4333-8333-333333333333",
            resource_group="rg-approved",
            session_job="bp-approved-sessions",
            client_factory=lambda **_kwargs: client,
            wall_clock=lambda: datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
            sleeper=lambda _seconds: None,
            job_runner=lambda **_kwargs: "execution-1",
        )
