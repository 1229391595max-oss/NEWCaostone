"""Secret-free idempotency material for administrator AI mutations."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import hmac
import json

from src.repositories.admin_ai import AIControlProjection

ADMIN_IDEMPOTENCY_TTL = timedelta(days=30)


def idempotency_key_hash(pepper: bytes, idempotency_key: str) -> bytes:
    """Validate and irreversibly bind a caller key to this application."""

    normalized = idempotency_key.strip()
    if not 1 <= len(normalized) <= 128 or any(
        ord(character) < 0x21 or ord(character) > 0x7E
        for character in normalized
    ):
        raise ValueError("admin_idempotency_key_invalid")
    return hmac.new(
        pepper,
        b"admin-ai-idempotency\x00" + normalized.encode(),
        hashlib.sha256,
    ).digest()


def request_hash(payload: dict[str, object]) -> bytes:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).digest()


def control_projection(
    state: AIControlProjection,
    *,
    result: str = "succeeded",
    error_code: str | None = None,
) -> dict[str, object]:
    """Store only values that the Admin API is permitted to return."""

    configured = (
        isinstance(state.key_name, str)
        and bool(state.key_name)
        and isinstance(state.key_version, str)
        and bool(state.key_version)
        and state.key_reference == f"{state.key_name}/{state.key_version}"
        and isinstance(state.key_fingerprint, str)
        and len(state.key_fingerprint) == 64
        and state.verified_at is not None
        and state.key_validation_state == "verified"
    )
    return {
        "result": result,
        "error_code": error_code,
        "revision": state.revision,
        "operator_enabled": state.operator_enabled,
        "demo_enabled": state.demo_enabled,
        "credential_configured": configured,
        "key_fingerprint": state.key_fingerprint if configured else None,
        "verified_at": state.verified_at.isoformat() if configured else None,
    }


def replay_control_projection(
    current: AIControlProjection,
    projection: dict[str, object],
) -> AIControlProjection | None:
    """Rebuild a service result without persisting a secret locator."""

    revision = projection.get("revision")
    operator_enabled = projection.get("operator_enabled")
    demo_enabled = projection.get("demo_enabled")
    configured = projection.get("credential_configured")
    fingerprint = projection.get("key_fingerprint")
    verified_text = projection.get("verified_at")
    if (
        not isinstance(revision, int)
        or isinstance(revision, bool)
        or not isinstance(operator_enabled, bool)
        or not isinstance(demo_enabled, bool)
        or not isinstance(configured, bool)
    ):
        return None
    if not configured:
        return replace(
            current,
            revision=revision,
            operator_enabled=operator_enabled,
            demo_enabled=demo_enabled,
            key_name=None,
            key_version=None,
            key_reference=None,
            key_fingerprint=None,
            verified_at=None,
            key_validation_state="unconfigured",
        )
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or not isinstance(verified_text, str)
        or not current.key_name
        or not current.key_version
        or current.key_reference != f"{current.key_name}/{current.key_version}"
    ):
        return None
    try:
        verified_at = datetime.fromisoformat(verified_text)
    except ValueError:
        return None
    return replace(
        current,
        revision=revision,
        operator_enabled=operator_enabled,
        demo_enabled=demo_enabled,
        key_fingerprint=fingerprint,
        verified_at=verified_at,
        key_validation_state="verified",
    )
