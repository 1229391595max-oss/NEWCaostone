"""Verify exact hosted liveness/readiness JSON without following redirects."""

from __future__ import annotations

import argparse
import json
import ssl
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import truststore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.readiness import EXPECTED_SCHEMA_REVISION  # noqa: E402

EXPECTED_READY = {
    "status": "ready",
    "checks": {
        "blob": "ok",
        "configuration": "ok",
        "database": "ok",
        "foundation": "ok",
        "migration": EXPECTED_SCHEMA_REVISION,
    },
}


class HostedHealthInvalid(RuntimeError):
    """The hosted endpoint did not prove the exact health authority."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


def _default_opener(request: Request, *, timeout: int):
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return build_opener(
        _NoRedirect(),
        HTTPSHandler(context=context),
    ).open(request, timeout=timeout)


def _read_exact(
    url: str,
    expected: dict[str, object],
    *,
    opener: Callable[..., object],
) -> None:
    request = Request(url, method="GET", headers={"Cache-Control": "no-cache"})
    try:
        with opener(request, timeout=5) as response:
            if response.geturl() != url:
                raise HostedHealthInvalid("hosted_health_url_mismatch")
            if response.status != 200:
                raise HostedHealthInvalid("hosted_health_status_invalid")
            if response.headers.get_content_type() != "application/json":
                raise HostedHealthInvalid("hosted_health_content_type_invalid")
            body = response.read(4_097)
    except HostedHealthInvalid:
        raise
    except Exception as error:
        raise HostedHealthInvalid("hosted_health_unavailable") from error
    if len(body) > 4_096:
        raise HostedHealthInvalid("hosted_health_body_too_large")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HostedHealthInvalid("hosted_health_json_invalid") from error
    if payload != expected:
        raise HostedHealthInvalid("hosted_health_authority_invalid")


def verify_hosted_health(
    base_url: str,
    *,
    opener: Callable[..., object] = _default_opener,
) -> None:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise HostedHealthInvalid("hosted_health_base_url_invalid")
    normalized = base_url.rstrip("/")
    _read_exact(
        f"{normalized}/health/live",
        {"status": "ok"},
        opener=opener,
    )
    _read_exact(
        f"{normalized}/health/ready",
        EXPECTED_READY,
        opener=opener,
    )


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    options = parser.parse_args(arguments)
    try:
        verify_hosted_health(options.url)
    except HostedHealthInvalid:
        print("hosted_health=failed")
        return 1
    print("hosted_health=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
