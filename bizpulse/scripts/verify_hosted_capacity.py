"""Verify exactly 15 same-origin viewer sessions without invoking AI providers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError
from time import monotonic
from urllib.parse import urlsplit

import httpx


class HostedCapacityInvalid(RuntimeError):
    """The hosted exact-15 session/read authority did not pass."""


def verify_hosted_capacity(base_url: str) -> None:
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
        raise HostedCapacityInvalid("hosted_capacity_url_invalid")
    origin = base_url.rstrip("/")
    started = monotonic()
    admitted_barrier = Barrier(15)
    read_barrier = Barrier(15)

    def synchronize(barrier: Barrier) -> None:
        remaining = 60 - (monotonic() - started)
        if remaining <= 0:
            barrier.abort()
            raise HostedCapacityInvalid("hosted_capacity_deadline_exceeded")
        try:
            barrier.wait(timeout=min(30, remaining))
        except BrokenBarrierError as error:
            raise HostedCapacityInvalid("hosted_capacity_concurrency_failed") from error

    def viewer(_index: int) -> tuple[str, str]:
        client: httpx.Client | None = None
        csrf: object | None = None
        session_id: object | None = None
        result: tuple[str, str] | None = None
        try:
            client = httpx.Client(
                timeout=30,
                follow_redirects=False,
                trust_env=False,
            )
            admitted = client.post(
                f"{origin}/api/demo/sessions",
                headers={"Origin": origin},
            )
            if admitted.status_code != 201:
                raise HostedCapacityInvalid("hosted_capacity_admission_failed")
            payload = admitted.json()
            csrf = payload["csrf_token"]
            session_id = payload["session"]["session_id"]
            synchronize(admitted_barrier)
            release = client.get(f"{origin}/api/demo/release/current")
            analysis = client.get(
                f"{origin}/api/demo/release/analyses/sales_ads"
            )
            if release.status_code != 200 or analysis.status_code != 200:
                raise HostedCapacityInvalid("hosted_capacity_read_failed")
            version_id = release.json()["dataset_version_id"]
            result = str(session_id), str(version_id)
            synchronize(read_barrier)
        except HostedCapacityInvalid:
            admitted_barrier.abort()
            read_barrier.abort()
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            admitted_barrier.abort()
            read_barrier.abort()
            raise HostedCapacityInvalid("hosted_capacity_failed") from error
        finally:
            if client is not None:
                try:
                    if csrf is not None and session_id is not None:
                        ended = client.delete(
                            f"{origin}/api/demo/sessions",
                            headers={
                                "Origin": origin,
                                "X-CSRF-Token": str(csrf),
                            },
                        )
                        if ended.status_code != 204:
                            raise HostedCapacityInvalid(
                                "hosted_capacity_cleanup_failed"
                            )
                finally:
                    client.close()
        if result is None:
            raise HostedCapacityInvalid("hosted_capacity_failed")
        return result

    try:
        with ThreadPoolExecutor(max_workers=15) as executor:
            results = tuple(executor.map(viewer, range(15)))
    except HostedCapacityInvalid:
        raise
    except Exception as error:
        raise HostedCapacityInvalid("hosted_capacity_failed") from error
    if (
        monotonic() - started >= 60
        or len(results) != 15
        or len({row[0] for row in results}) != 15
        or len({row[1] for row in results}) != 1
    ):
        raise HostedCapacityInvalid("hosted_capacity_authority_invalid")
