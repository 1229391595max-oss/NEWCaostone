"""Pure state and evidence contract for package-gated AI enablement."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re
from typing import Mapping
from uuid import UUID

from src.ai.release_constants import (
    ANSWERING_TOKEN_RESERVATION,
    APPROVED_AI_DAILY_ATTEMPT_LIMIT,
    APPROVED_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE,
    APPROVED_AI_MAX_CONCURRENT_TURNS,
    APPROVED_AI_MONTHLY_TOKEN_LIMIT,
    APPROVED_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE,
    APPROVED_CHAT_OUTPUT_TOKEN_LIMIT,
    APPROVED_OPENAI_MODEL,
    PLANNING_TOKEN_RESERVATION,
)


STATE_ORDER = (
    "readonly_revalidation",
    "publish_candidate_image",
    "activate_ai_disabled_candidate",
    "verify_ai_disabled_candidate",
    "reconcile_ai_vault_identity_role_diagnostics",
    "budget_failure_rehearsal",
    "provider_failure_placeholder_write",
    "provider_failure_rehearsal",
    "paid_model_qualification",
    "real_secret_write",
    "activate_ai_enabled_revision",
    "verify_ai_enabled_revision",
    "paid_hosted_manual_send_smoke",
    "sanitize_receipt",
)

_ANCHOR_KEYS = frozenset(
    {
        "package_sha256",
        "candidate_image_digest",
        "revision",
        "subscription_id",
        "tenant_id",
        "resource_group",
        "app_name",
        "vault_name",
        "identity_name",
        "model",
        "expires_at",
    }
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]{1,62}[a-z0-9]")
_REVISION_PATTERN = re.compile(r"[a-z][a-z0-9-]{2,126}")
_KEY_PATTERN = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b")
_FAILURE_CODE_PATTERN = re.compile(r"ai_enablement_[a-z0-9_]{3,96}")
_PROHIBITED_EVIDENCE_PATTERN = re.compile(
    r"(?i)(?:\bbearer\b|\bdatabase\b|connection[_ -]?string|\bprompt\b|"
    r"user[_ -]?data|raw[_ -]?stdout|\btraceback\b|\bexception\b|"
    r"api[_ -]?key|secret[_ -]?value)"
)

RECONCILIATION_KEYS = frozenset(
    {
        "role",
        "acknowledgement",
        "predecessor_revision",
        "target_revision",
        "target_image_digest",
        "final_state",
        "application_read_count",
        "revision_read_count",
        "elapsed_milliseconds",
    }
)
RECONCILIATION_ROLES = (
    "ai_disabled_candidate",
    "budget_enabled",
    "budget_recovery",
    "provider_enabled",
    "provider_recovery",
    "ai_enabled",
)
_ALLOWED_RECONCILIATION_ROLES = frozenset(
    {*RECONCILIATION_ROLES, "emergency_disabled"}
)
_ALLOWED_RECONCILIATION_FINAL_STATES = frozenset(
    {"healthy_target", "drift", "failed", "read_failed", "timeout"}
)

_STATE_SPECS: dict[str, dict[str, object]] = {
    "readonly_revalidation": {
        "operations": {"azure.read.sanitized": 12},
        "expected_evidence": {
            "authority_matches": True,
            "secret_values_read": 0,
        },
    },
    "publish_candidate_image": {
        "operations": {"acr.publish.immutable": 1},
        "expected_evidence": {"image_digest_verified": True},
    },
    "activate_ai_disabled_candidate": {
        "operations": {"containerapp.patch.nonsecret": 1},
        "expected_evidence": {
            "ai_enabled": False,
            "configuration_secrets_changed": False,
        },
    },
    "verify_ai_disabled_candidate": {
        "operations": {
            "azure.read.containerapp.max": 25,
            "azure.read.revisions.max": 25,
            "browser.ai_disabled": 1,
        },
        "expected_evidence": {
            "ready_revision_matches": True,
            "ai_enabled": False,
            "preset_requests": 0,
        },
    },
    "reconcile_ai_vault_identity_role_diagnostics": {
        "operations": {
            "azure.resource.reconcile.identity": 1,
            "azure.resource.reconcile.keyvault": 1,
            "azure.resource.reconcile.role_assignment": 1,
            "azure.resource.reconcile.diagnostic_setting": 1,
        },
        "expected_evidence": {
            "resource_mode": "existing_exact_reconcile",
            "public_network_access": "Enabled",
            "rbac_authorization": True,
            "purge_protection": True,
            "secret_count": 0,
        },
    },
    "budget_failure_rehearsal": {
        "operations": {
            "containerapp.patch.nonsecret": 2,
            "browser.manual_send": 1,
            "azure.read.containerapp.max": 50,
            "azure.read.revisions.max": 50,
        },
        "expected_evidence": {
            "provider_calls": 0,
            "ledger_attempt_delta": 0,
            "ledger_token_delta": 0,
            "failure_code": "ai_budget_unavailable",
            "recovery_revision_ready": True,
        },
    },
    "provider_failure_placeholder_write": {
        "operations": {"keyvault.secret.placeholder_write": 1},
        "expected_evidence": {
            "secret_name": "openai-api-key",
            "secret_kind": "generated_placeholder",
        },
    },
    "provider_failure_rehearsal": {
        "operations": {
            "containerapp.patch.nonsecret": 2,
            "browser.manual_send": 1,
            "azure.read.containerapp.max": 50,
            "azure.read.revisions.max": 50,
        },
        "expected_evidence": {
            "provider_calls": 1,
            "ledger_attempt_delta": 1,
            "minimum_reserved_tokens": PLANNING_TOKEN_RESERVATION,
            "provider_error_code": "provider_auth_rejected",
            "key_vault_read_succeeded": True,
            "failure_code": "ai_provider_unavailable",
            "recovery_ai_enabled": False,
            "recovery_revision_ready": True,
            "placeholder_inert": True,
        },
    },
    "paid_model_qualification": {
        "operations": {"openai.paid.synthetic_qualification": 12},
        "expected_evidence": {
            "case_count": 12,
            "passed_case_count": 12,
            "retries": 0,
        },
    },
    "real_secret_write": {
        "operations": {"keyvault.secret.real_write": 1},
        "expected_evidence": {
            "secret_name": "openai-api-key",
            "secret_value_recorded": False,
        },
    },
    "activate_ai_enabled_revision": {
        "operations": {"containerapp.patch.nonsecret": 1},
        "expected_evidence": {
            "ai_enabled": True,
            "configuration_secrets_changed": False,
        },
    },
    "verify_ai_enabled_revision": {
        "operations": {
            "azure.read.containerapp.max": 25,
            "azure.read.revisions.max": 25,
        },
        "expected_evidence": {
            "ready_revision_matches": True,
            "ai_enabled": True,
            "key_vault_binding_matches": True,
        },
    },
    "paid_hosted_manual_send_smoke": {
        "operations": {"browser.manual_send": 1},
        "expected_evidence": {
            "manual_send_count": 1,
            "provider_calls": 1,
            "preset_auto_submit_count": 0,
            "public_demo_viewer": True,
            "csrf_session_scoped": True,
            "store_workspace_scope_enforced": True,
        },
    },
    "sanitize_receipt": {
        "operations": {"local.receipt.sanitize": 1},
        "expected_evidence": {
            "prohibited_content_matches": 0,
            "receipt_mode": "0600",
        },
    },
}


class AIEnablementContractInvalid(ValueError):
    """The authority, state transition, or receipt violated the fixed contract."""


def _invalid(code: str = "ai_enablement_contract_invalid") -> AIEnablementContractInvalid:
    return AIEnablementContractInvalid(code)


def _canonical_uuid4(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
    except ValueError:
        return False
    return str(parsed) == value and parsed.version == 4


def _validate_anchors(raw: Mapping[str, object]) -> dict[str, str]:
    if set(raw) != _ANCHOR_KEYS:
        raise _invalid()
    anchors = {key: raw[key] for key in sorted(_ANCHOR_KEYS)}
    if (
        not isinstance(anchors["package_sha256"], str)
        or _SHA256_PATTERN.fullmatch(anchors["package_sha256"]) is None
        or not isinstance(anchors["candidate_image_digest"], str)
        or _DIGEST_PATTERN.fullmatch(anchors["candidate_image_digest"]) is None
        or not _canonical_uuid4(anchors["subscription_id"])
        or not _canonical_uuid4(anchors["tenant_id"])
        or anchors["model"] != APPROVED_OPENAI_MODEL
    ):
        raise _invalid()
    for name in ("resource_group", "app_name", "vault_name", "identity_name"):
        value = anchors[name]
        if not isinstance(value, str) or _NAME_PATTERN.fullmatch(value) is None:
            raise _invalid()
    revision = anchors["revision"]
    if not isinstance(revision, str) or _REVISION_PATTERN.fullmatch(revision) is None:
        raise _invalid()
    expires_at = anchors["expires_at"]
    if not isinstance(expires_at, str) or not expires_at.endswith("Z"):
        raise _invalid()
    try:
        datetime.fromisoformat(expires_at.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise _invalid() from error
    return {key: str(value) for key, value in anchors.items()}


def _resume_token(anchors: Mapping[str, str], next_index: int) -> str:
    encoded = json.dumps(
        {"anchors": anchors, "next_state_index": next_index},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_ai_enablement_contract(anchors: Mapping[str, object]) -> dict[str, object]:
    """Create the immutable, sanitized operation contract for one package."""

    validated = _validate_anchors(anchors)
    return {
        "schema_version": "newcaostone.ai-enablement-contract.v2",
        "anchors": validated,
        **contract_template(),
    }


def contract_template() -> dict[str, object]:
    """Return the anchor-free limits and states safe to embed before approval."""

    return {
        "state_order": list(STATE_ORDER),
        "runtime_limits": {
            "daily_attempt_limit": APPROVED_AI_DAILY_ATTEMPT_LIMIT,
            "monthly_token_limit": APPROVED_AI_MONTHLY_TOKEN_LIMIT,
            "max_concurrent_turns": APPROVED_AI_MAX_CONCURRENT_TURNS,
            "session_attempt_limit_per_minute": (
                APPROVED_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE
            ),
            "global_attempt_limit_per_minute": (
                APPROVED_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE
            ),
            "chat_output_token_limit": APPROVED_CHAT_OUTPUT_TOKEN_LIMIT,
            "planning_token_reservation": PLANNING_TOKEN_RESERVATION,
            "answering_token_reservation": ANSWERING_TOKEN_RESERVATION,
            "provider_timeout_seconds": 30,
            "provider_retries": 0,
            "provider_tools": 0,
            "reconciliation_timeout_seconds": 120,
            "reconciliation_poll_interval_seconds": 5,
            "reconciliation_application_read_max": 25,
            "reconciliation_revision_read_max": 25,
            "containerapp_patch_retries": 0,
        },
        "paid_calls": {
            "model_qualification_cases": 12,
            "hosted_manual_send_smoke": 1,
            "total_maximum": 13,
            "retries_per_call": 0,
        },
        "states": deepcopy(_STATE_SPECS),
    }


def initial_progress(contract: Mapping[str, object]) -> dict[str, object]:
    anchors = _contract_anchors(contract)
    return {
        "completed_states": [],
        "next_state": STATE_ORDER[0],
        "resume_token": _resume_token(anchors, 0),
    }


def _contract_anchors(contract: Mapping[str, object]) -> dict[str, str]:
    if (
        contract.get("schema_version")
        != "newcaostone.ai-enablement-contract.v2"
        or contract.get("state_order") != list(STATE_ORDER)
        or contract.get("states") != _STATE_SPECS
        or not isinstance(contract.get("anchors"), Mapping)
    ):
        raise _invalid()
    return _validate_anchors(contract["anchors"])


def advance_contract(
    contract: Mapping[str, object],
    progress: Mapping[str, object],
    *,
    state: str,
    operations: Mapping[str, int],
    evidence: Mapping[str, object],
) -> dict[str, object]:
    """Advance exactly one state; fail without mutating either input."""

    anchors = _contract_anchors(contract)
    completed = progress.get("completed_states")
    if (
        set(progress) != {"completed_states", "next_state", "resume_token"}
        or not isinstance(completed, list)
        or completed != list(STATE_ORDER[: len(completed)])
        or len(completed) >= len(STATE_ORDER)
        or progress.get("next_state") != STATE_ORDER[len(completed)]
        or progress.get("resume_token") != _resume_token(anchors, len(completed))
        or state != STATE_ORDER[len(completed)]
    ):
        raise _invalid("ai_enablement_transition_invalid")
    specification = _STATE_SPECS[state]
    if dict(operations) != specification["operations"] or dict(evidence) != (
        specification["expected_evidence"]
    ):
        raise _invalid("ai_enablement_transition_invalid")
    next_index = len(completed) + 1
    return {
        "completed_states": [*completed, state],
        "next_state": STATE_ORDER[next_index] if next_index < len(STATE_ORDER) else None,
        "resume_token": _resume_token(anchors, next_index),
    }


def validate_reconciliation_evidence(raw: object) -> dict[str, object]:
    """Validate one closed, bounded, non-secret transition observation."""

    if not isinstance(raw, Mapping) or set(raw) != RECONCILIATION_KEYS:
        raise _invalid("ai_enablement_reconciliation_invalid")
    serialized = json.dumps(raw, sort_keys=True, ensure_ascii=False)
    if _KEY_PATTERN.search(serialized) or _PROHIBITED_EVIDENCE_PATTERN.search(
        serialized
    ):
        raise _invalid("ai_enablement_reconciliation_invalid")
    for counter in ("application_read_count", "revision_read_count"):
        value = raw[counter]
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= 25
        ):
            raise _invalid("ai_enablement_reconciliation_invalid")
    elapsed = raw["elapsed_milliseconds"]
    if (
        not isinstance(elapsed, int)
        or isinstance(elapsed, bool)
        or not 0 <= elapsed <= 120000
        or raw["role"] not in _ALLOWED_RECONCILIATION_ROLES
        or raw["acknowledgement"] != "accepted"
        or raw["final_state"] not in _ALLOWED_RECONCILIATION_FINAL_STATES
        or not isinstance(raw["predecessor_revision"], str)
        or _REVISION_PATTERN.fullmatch(raw["predecessor_revision"]) is None
        or not isinstance(raw["target_revision"], str)
        or _REVISION_PATTERN.fullmatch(raw["target_revision"]) is None
        or raw["predecessor_revision"] == raw["target_revision"]
        or not isinstance(raw["target_image_digest"], str)
        or _DIGEST_PATTERN.fullmatch(raw["target_image_digest"]) is None
    ):
        raise _invalid("ai_enablement_reconciliation_invalid")
    return {key: deepcopy(raw[key]) for key in sorted(RECONCILIATION_KEYS)}


def _reconciliations(
    raw: object,
    *,
    require_complete: bool,
) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        raise _invalid("ai_enablement_reconciliation_invalid")
    validated = [validate_reconciliation_evidence(item) for item in raw]
    roles = [str(item["role"]) for item in validated]
    expected = list(RECONCILIATION_ROLES)
    if roles != (expected if require_complete else expected[: len(roles)]):
        raise _invalid("ai_enablement_reconciliation_invalid")
    if any(item["final_state"] != "healthy_target" for item in validated):
        raise _invalid("ai_enablement_reconciliation_invalid")
    return validated


def sanitize_ai_enablement_observation(
    raw: Mapping[str, object],
) -> dict[str, object]:
    """Return the provisional, non-secret hosted acceptance observation."""

    required = {
        "package_sha256",
        "candidate_image_digest",
        "final_revision",
        "ai_enabled",
        "paid_call_count",
        "reconciliations",
        "acceptance_requires_completed_receipt",
    }
    if set(raw) != required:
        raise _invalid("ai_enablement_observation_invalid")
    reconciliations = _reconciliations(
        raw["reconciliations"],
        require_complete=True,
    )
    if (
        not isinstance(raw["package_sha256"], str)
        or _SHA256_PATTERN.fullmatch(raw["package_sha256"]) is None
        or not isinstance(raw["candidate_image_digest"], str)
        or _DIGEST_PATTERN.fullmatch(raw["candidate_image_digest"]) is None
        or not isinstance(raw["final_revision"], str)
        or _REVISION_PATTERN.fullmatch(raw["final_revision"]) is None
        or raw["ai_enabled"] is not True
        or raw["paid_call_count"] != 13
        or raw["acceptance_requires_completed_receipt"] is not True
    ):
        raise _invalid("ai_enablement_observation_invalid")
    return {
        "schema_version": "newcaostone.ai-enablement-observation.v1",
        **{
            key: deepcopy(raw[key])
            for key in sorted(required - {"reconciliations"})
        },
        "reconciliations": reconciliations,
    }


def sanitize_terminal_receipt(raw: Mapping[str, object]) -> dict[str, object]:
    """Return only terminal proof fields and reject secret/user/prompt material."""

    required = {
        "package_sha256",
        "completed_states",
        "candidate_image_digest",
        "final_revision",
        "vault_name",
        "identity_name",
        "paid_call_count",
        "result",
        "reconciliations",
        "observation_sha256",
    }
    allowed = required | {"schema_version"}
    if set(raw) - allowed or not required.issubset(raw):
        raise _invalid("ai_enablement_receipt_invalid")
    serialized = json.dumps(raw, sort_keys=True, ensure_ascii=False)
    if _KEY_PATTERN.search(serialized):
        raise _invalid("ai_enablement_receipt_invalid")
    if (
        not isinstance(raw["package_sha256"], str)
        or _SHA256_PATTERN.fullmatch(raw["package_sha256"]) is None
        or raw["completed_states"] != list(STATE_ORDER)
        or not isinstance(raw["candidate_image_digest"], str)
        or _DIGEST_PATTERN.fullmatch(raw["candidate_image_digest"]) is None
        or not isinstance(raw["final_revision"], str)
        or _REVISION_PATTERN.fullmatch(raw["final_revision"]) is None
        or not isinstance(raw["vault_name"], str)
        or _NAME_PATTERN.fullmatch(raw["vault_name"]) is None
        or not isinstance(raw["identity_name"], str)
        or _NAME_PATTERN.fullmatch(raw["identity_name"]) is None
        or raw["paid_call_count"] != 13
        or raw["result"] != "completed"
        or not isinstance(raw["observation_sha256"], str)
        or _SHA256_PATTERN.fullmatch(raw["observation_sha256"]) is None
    ):
        raise _invalid("ai_enablement_receipt_invalid")
    reconciliations = _reconciliations(
        raw["reconciliations"],
        require_complete=True,
    )
    return {
        "schema_version": "newcaostone.ai-enablement-receipt.v2",
        **{
            key: deepcopy(raw[key])
            for key in sorted(required - {"reconciliations"})
        },
        "reconciliations": reconciliations,
    }


def sanitize_failed_receipt(raw: Mapping[str, object]) -> dict[str, object]:
    """Return a closed failed-attempt receipt without exception material."""

    required = {
        "package_sha256",
        "state",
        "failure_code",
        "completed_states",
        "reconciliations",
        "recovery",
    }
    if set(raw) != required:
        raise _invalid("ai_enablement_receipt_invalid")
    completed = raw["completed_states"]
    if (
        not isinstance(raw["package_sha256"], str)
        or _SHA256_PATTERN.fullmatch(raw["package_sha256"]) is None
        or raw["state"] != "failed"
        or not isinstance(raw["failure_code"], str)
        or _FAILURE_CODE_PATTERN.fullmatch(raw["failure_code"]) is None
        or not isinstance(completed, list)
        or completed != list(STATE_ORDER[: len(completed)])
    ):
        raise _invalid("ai_enablement_receipt_invalid")
    reconciliations = _reconciliations(
        raw["reconciliations"],
        require_complete=False,
    )
    recovery = raw["recovery"]
    validated_recovery: dict[str, object] | None
    if recovery is None:
        validated_recovery = None
    elif isinstance(recovery, Mapping) and set(recovery) == {
        "ai_disabled_confirmed",
        "placeholder_overwrite_succeeded",
        "reconciliation",
    }:
        reconciliation = validate_reconciliation_evidence(
            recovery["reconciliation"]
        )
        if (
            recovery["ai_disabled_confirmed"] is not True
            or recovery["placeholder_overwrite_succeeded"] is not True
            or reconciliation["role"] != "emergency_disabled"
            or reconciliation["final_state"] != "healthy_target"
        ):
            raise _invalid("ai_enablement_receipt_invalid")
        validated_recovery = {
            "ai_disabled_confirmed": True,
            "placeholder_overwrite_succeeded": True,
            "reconciliation": reconciliation,
        }
    else:
        raise _invalid("ai_enablement_receipt_invalid")
    return {
        "schema_version": "newcaostone.ai-enablement-attempt.v2",
        "package_sha256": raw["package_sha256"],
        "state": "failed",
        "failure_code": raw["failure_code"],
        "completed_states": deepcopy(completed),
        "reconciliations": reconciliations,
        "recovery": validated_recovery,
    }
