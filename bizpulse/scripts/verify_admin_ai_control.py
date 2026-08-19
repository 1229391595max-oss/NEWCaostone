"""Validate secret-free hosted admin-AI acceptance evidence."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
import re


_FINGERPRINT = re.compile(r"[0-9a-f]{8}")
_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,127}")
_REVISION = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?")
_BINDING_ID = re.compile(r"[0-9a-f]{64}")


class HostedAdminAIVerificationInvalid(ValueError):
    """Hosted evidence did not prove the complete shared-binding contract."""


def _invalid() -> HostedAdminAIVerificationInvalid:
    return HostedAdminAIVerificationInvalid("hosted_admin_ai_acceptance_invalid")


def _mapping(value: object, keys: set[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _invalid()
    return value


def _turn(value: object, *, demo: bool) -> Mapping[str, object]:
    keys = {
        "status",
        "request_id",
        "credential_fingerprint",
        "credential_binding_id",
        "credential_control_revision",
    }
    if demo:
        keys |= {"admin_denied", "admin_cache_control", "admin_vary"}
    turn = _mapping(value, keys)
    if (
        turn["status"] != "completed"
        or not isinstance(turn["request_id"], str)
        or _REQUEST_ID.fullmatch(turn["request_id"]) is None
        or not isinstance(turn["credential_fingerprint"], str)
        or _FINGERPRINT.fullmatch(turn["credential_fingerprint"]) is None
        or not isinstance(turn["credential_binding_id"], str)
        or _BINDING_ID.fullmatch(turn["credential_binding_id"]) is None
        or type(turn["credential_control_revision"]) is not int
        or turn["credential_control_revision"] < 0
        or (
            demo
            and (
                turn["admin_denied"] is not True
                or turn["admin_cache_control"] != "private, no-store"
                or turn["admin_vary"] != "Cookie"
            )
        )
    ):
        raise _invalid()
    return turn


def verify_hosted_admin_ai_control(result: object) -> dict[str, object]:
    """Return sanitized evidence only after every hosted acceptance gate passes."""

    raw = _mapping(
        result,
        {
            "revision",
            "admin_entry",
            "operator_turn",
            "demo_turn",
            "channel_switches",
            "invalid_candidate_rollback",
            "secret_scan_matches",
            "audit_evidence",
        },
    )
    if (
        not isinstance(raw["revision"], str)
        or _REVISION.fullmatch(raw["revision"]) is None
    ):
        raise _invalid()
    admin_entry = _mapping(
        raw["admin_entry"],
        {"status", "summary_status", "request_id"},
    )
    if (
        admin_entry["status"] != "protected"
        or admin_entry["summary_status"] != "ready"
        or not isinstance(admin_entry["request_id"], str)
        or _REQUEST_ID.fullmatch(admin_entry["request_id"]) is None
    ):
        raise _invalid()
    operator = _turn(raw["operator_turn"], demo=False)
    demo = _turn(raw["demo_turn"], demo=True)
    if operator["credential_fingerprint"] != demo["credential_fingerprint"]:
        raise _invalid()
    if operator["credential_binding_id"] != demo["credential_binding_id"]:
        raise _invalid()
    switches = _mapping(
        raw["channel_switches"],
        {
            "status",
            "operator_independent",
            "demo_independent",
            "final_operator_enabled",
            "final_demo_enabled",
        },
    )
    if switches != {
        "status": "completed",
        "operator_independent": True,
        "demo_independent": True,
        "final_operator_enabled": True,
        "final_demo_enabled": True,
    }:
        raise _invalid()
    rollback = _mapping(
        raw["invalid_candidate_rollback"],
        {
            "status",
            "safe_code",
            "prior_fingerprint",
            "resulting_fingerprint",
            "prior_operator_enabled",
            "resulting_operator_enabled",
            "prior_demo_enabled",
            "resulting_demo_enabled",
        },
    )
    audit = _mapping(
        raw["audit_evidence"],
        {"event_count", "secret_scan_matches", "evidence_sha256"},
    )
    if (
        rollback["status"] != "rejected"
        or rollback["safe_code"] != "ADMIN_AI_KEY_REJECTED"
        or rollback["prior_fingerprint"] != operator["credential_fingerprint"]
        or rollback["resulting_fingerprint"] != operator["credential_fingerprint"]
        or rollback["prior_operator_enabled"] is not True
        or rollback["resulting_operator_enabled"] is not True
        or rollback["prior_demo_enabled"] is not True
        or rollback["resulting_demo_enabled"] is not True
        or raw["secret_scan_matches"] != 0
        or audit["event_count"] != 8
        or audit["secret_scan_matches"] != 0
        or not isinstance(audit["evidence_sha256"], str)
        or _BINDING_ID.fullmatch(audit["evidence_sha256"]) is None
    ):
        raise _invalid()
    serialized = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    if any(
        prohibited in serialized.casefold()
        for prohibited in (
            "api_key",
            "candidate_key",
            "current_password",
            "authorization",
            "provider_response",
        )
    ):
        raise _invalid()
    return deepcopy(dict(raw))
