"""Prove the hosted 30-minute viewer TTL with a real clock and cleanup Job."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

import httpx

_SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_SCRIPT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_PROJECT_ROOT))

from scripts.run_azure_job import run_job_to_completion  # noqa: E402
from scripts.run_hosted_check import resolve_hosted_url  # noqa: E402

MINIMUM_IDLE_SECONDS = 1_500
MAXIMUM_IDLE_SECONDS = 2_100
EXPIRY_BUFFER_SECONDS = 60


class HostedExpiryInvalid(RuntimeError):
    """The hosted natural-expiry authority was not proved."""


class _Response(Protocol):
    status_code: int

    def json(self) -> Any: ...


class _Client(Protocol):
    def __enter__(self) -> _Client: ...

    def __exit__(self, *args: object) -> object: ...

    def post(self, url: str, *, headers: dict[str, str]) -> _Response: ...

    def get(self, url: str) -> _Response: ...

    def delete(self, url: str, *, headers: dict[str, str]) -> _Response: ...


def _session_authority(response: _Response) -> tuple[UUID, str, datetime]:
    if response.status_code != 201:
        raise HostedExpiryInvalid("hosted_expiry_admission_failed")
    try:
        payload = response.json()
        session = payload["session"]
        session_id = UUID(session["session_id"])
        csrf = payload["csrf_token"]
        expires_at = datetime.fromisoformat(
            session["idle_expires_at"].replace("Z", "+00:00")
        )
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise HostedExpiryInvalid("hosted_expiry_admission_invalid") from error
    if (
        not isinstance(csrf, str)
        or not 16 <= len(csrf) <= 512
        or expires_at.tzinfo is None
    ):
        raise HostedExpiryInvalid("hosted_expiry_admission_invalid")
    return session_id, csrf, expires_at.astimezone(UTC)


def verify_hosted_expiry(
    base_url: str,
    *,
    subscription_id: str,
    resource_group: str,
    session_job: str,
    client_factory: Callable[..., _Client] = httpx.Client,
    wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleeper: Callable[[float], None] = time.sleep,
    job_runner: Callable[..., str] = run_job_to_completion,
) -> None:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
    ):
        raise HostedExpiryInvalid("hosted_expiry_url_invalid")
    try:
        UUID(subscription_id)
    except (TypeError, ValueError) as error:
        raise HostedExpiryInvalid("hosted_expiry_authority_invalid") from error

    origin = base_url.rstrip("/")
    try:
        with client_factory(
            timeout=30,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            old_id, _old_csrf, expires_at = _session_authority(
                client.post(
                    f"{origin}/api/demo/sessions",
                    headers={"Origin": origin},
                )
            )
            now = wall_clock().astimezone(UTC)
            idle_seconds = (expires_at - now).total_seconds()
            if not MINIMUM_IDLE_SECONDS <= idle_seconds <= MAXIMUM_IDLE_SECONDS:
                raise HostedExpiryInvalid("hosted_expiry_ttl_invalid")
            sleeper(idle_seconds + EXPIRY_BUFFER_SECONDS)
            job_runner(
                subscription_id=subscription_id,
                resource_group=resource_group,
                job_name=session_job,
                timeout_seconds=600,
            )
            expired = client.get(f"{origin}/api/demo/sessions/current")
            if expired.status_code != 401:
                raise HostedExpiryInvalid("hosted_expiry_not_enforced")
            new_id, new_csrf, _new_expiry = _session_authority(
                client.post(
                    f"{origin}/api/demo/sessions",
                    headers={"Origin": origin},
                )
            )
            if new_id == old_id:
                raise HostedExpiryInvalid("hosted_expiry_session_reused")
            ended = client.delete(
                f"{origin}/api/demo/sessions",
                headers={"Origin": origin, "X-CSRF-Token": new_csrf},
            )
            if ended.status_code != 204:
                raise HostedExpiryInvalid("hosted_expiry_cleanup_failed")
    except HostedExpiryInvalid:
        raise
    except (httpx.HTTPError, OSError, TypeError, ValueError) as error:
        raise HostedExpiryInvalid("hosted_expiry_failed") from error


def run_hosted_expiry(
    *,
    subscription_id: str,
    resource_group: str,
    app_name: str,
    image: str,
    session_job: str,
    expected_url: str | None = None,
) -> None:
    try:
        url = resolve_hosted_url(
            subscription_id=subscription_id,
            resource_group=resource_group,
            app_name=app_name,
            image=image,
            expected_url=expected_url,
        )
        verify_hosted_expiry(
            url,
            subscription_id=subscription_id,
            resource_group=resource_group,
            session_job=session_job,
        )
    except HostedExpiryInvalid:
        raise
    except Exception as error:
        raise HostedExpiryInvalid("hosted_expiry_authority_invalid") from error


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--session-job", required=True)
    parser.add_argument("--expected-url")
    options = parser.parse_args(arguments)
    try:
        run_hosted_expiry(
            subscription_id=options.subscription,
            resource_group=options.resource_group,
            app_name=options.app,
            image=options.image,
            session_job=options.session_job,
            expected_url=options.expected_url,
        )
    except HostedExpiryInvalid:
        print("hosted_expiry=failed")
        return 1
    print("hosted_expiry=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
