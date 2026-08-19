#!/usr/bin/env python3
"""Run one exact-hash admin-AI hosted release attempt without automatic retry."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime
import getpass
import importlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _require_exact_runtime_for_script() -> None:
    marker = PROJECT_ROOT / ".admin-ai-exact-runtime.json"
    try:
        metadata = marker.lstat()
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = None
        metadata = None
    if (
        os.environ.get("BIZPULSE_ADMIN_AI_EXACT_RUNTIME_ROOT")
        != str(PROJECT_ROOT)
        or not sys.flags.isolated
        or not sys.dont_write_bytecode
        or not sys.flags.no_site
        or metadata is None
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o400
        or not isinstance(payload, Mapping)
        or payload.get("schema_version")
        != "newcaostone.admin-ai-exact-runtime.v1"
    ):
        print("admin_ai_exact_runtime=failed")
        print("reason=runtime_snapshot_required")
        raise SystemExit(1)


if __name__ == "__main__":
    _require_exact_runtime_for_script()

from scripts.create_admin_ai_release_package import (  # noqa: E402
    AdminAIReleasePackageInvalid,
    capture_authority_binding,
    capture_candidate_artifact,
    capture_operations_factory,
    capture_repository,
    load_package,
    package_sha256,
    validate_package,
)
from scripts.verify_admin_ai_control import (  # noqa: E402
    verify_hosted_admin_ai_control,
)


ADMIN_AI_RELEASE_STATES = (
    "readonly_revalidation",
    "publish_candidate_image",
    "deploy_admin_ai_capability",
    "verify_ai_disabled_candidate",
    "rotate_key_through_admin",
    "verify_operator_ai",
    "verify_demo_ai",
    "verify_independent_channel_switches",
    "verify_invalid_candidate_rollback",
)
KNOWN_INVALID_SENTINEL = "bizpulse-known-invalid-admin-ai-candidate"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SAFE_CODE = re.compile(r"admin_ai_release_[a-z0-9_]{3,80}")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,127}")
_REVISION = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?")
_CREDENTIAL_SHAPED = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b")


class AdminAIReleaseInvalid(RuntimeError):
    """The one-shot release controller stopped at a closed gate."""


def _invalid(code: str) -> AdminAIReleaseInvalid:
    return AdminAIReleaseInvalid(code)


class AdminAIReleaseOperations(Protocol):
    """Separately authorized live adapter used by the pure one-shot controller."""

    def run(
        self,
        state: str,
        *,
        secret_value: str | None,
        context: dict[str, object],
    ) -> Mapping[str, object]: ...

    def reconcile_admin_ai_secret_access(
        self,
        *,
        context: dict[str, object],
    ) -> Mapping[str, object]: ...


def read_candidate_key(
    *,
    stdin_is_tty: Callable[[], bool] = sys.stdin.isatty,
    hidden_prompt: Callable[[str], str] = getpass.getpass,
) -> str:
    """Read one candidate locally from a TTY without echo or environment fallback."""

    if stdin_is_tty() is not True:
        raise _invalid("admin_ai_release_tty_required")
    value = hidden_prompt("OpenAI candidate key (input hidden): ")
    if not value:
        raise _invalid("admin_ai_release_key_missing")
    return value


def _safe_code(error: BaseException) -> str:
    if isinstance(error, AdminAIReleaseInvalid) and _SAFE_CODE.fullmatch(str(error)):
        return str(error)
    return "admin_ai_release_operation_failed"


def _validate_preexecution(package: Mapping[str, object], *, now: datetime) -> str:
    if now.tzinfo is None:
        raise _invalid("admin_ai_release_package_invalid")
    try:
        validate_package(package, now=now)
    except AdminAIReleasePackageInvalid as error:
        raise _invalid("admin_ai_release_package_invalid") from error
    try:
        expires = datetime.fromisoformat(
            str(package["expires_at"]).replace("Z", "+00:00")
        ).astimezone(UTC)
        issued = datetime.fromisoformat(
            str(package["issued_at"]).replace("Z", "+00:00")
        ).astimezone(UTC)
        execution = package["execution_contract"]
        baseline = package["azure_baseline"]
        repository = package["repository"]
        candidate = package["candidate"]
        retired = package["replay_fence"]["retired_package_sha256"]
    except (KeyError, TypeError, ValueError) as error:
        raise _invalid("admin_ai_release_package_invalid") from error
    if (
        now.astimezone(UTC) < issued
        or now.astimezone(UTC) >= expires
        or execution.get("attempts") != 1
        or execution.get("automatic_retries") != 0
        or execution.get("required_azure_reads") != 12
        or execution.get("rbac_migration_action")
        != "reconcile_admin_ai_secret_access"
        or baseline.get("required_azure_reads") != 12
        or baseline.get("role_assignment_phase")
        not in {"legacy_only", "officer_only"}
        or repository.get("tracked_tree_clean") is not True
        or candidate.get("platform") != "linux/amd64"
        or not isinstance(retired, list)
    ):
        raise _invalid("admin_ai_release_package_invalid")
    return package_sha256(package)


def _write_reserved_receipt(descriptor: int, receipt: Mapping[str, object]) -> None:
    encoded = (
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("short receipt write")
            remaining = remaining[written:]
        os.fsync(descriptor)
    except OSError as error:
        raise _invalid("admin_ai_release_receipt_write_failed") from error


def _reserve_receipt(path: Path, started_receipt: Mapping[str, object]) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        _write_reserved_receipt(descriptor, started_receipt)
        return descriptor
    except AdminAIReleaseInvalid:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except FileExistsError as error:
        raise _invalid("admin_ai_release_receipt_exists") from error
    except OSError as error:
        if descriptor is not None:
            os.close(descriptor)
        raise _invalid("admin_ai_release_receipt_reservation_failed") from error


def _exact_result(state: str, value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise _invalid("admin_ai_release_evidence_invalid")
    result = dict(value)
    keys = {
        "readonly_revalidation": {
            "required_azure_reads",
            "observation_sha256",
            "role_assignment_phase",
            "database_revision",
        },
        "publish_candidate_image": {"image_digest"},
        "deploy_admin_ai_capability": {
            "revision",
            "migration",
            "migration_job_reads",
            "migration_job_projection_sha256",
            "migration_execution_template_sha256",
            "operator_ai_enabled",
            "demo_ai_enabled",
        },
        "verify_ai_disabled_candidate": {
            "ready",
            "admin_protected",
            "summary_status",
            "operator_ai_enabled",
            "demo_ai_enabled",
            "request_id",
        },
        "rotate_key_through_admin": {
            "credential_fingerprint",
            "request_id",
            "revision",
        },
        "verify_operator_ai": {
            "status",
            "request_id",
            "credential_fingerprint",
            "credential_binding_id",
            "credential_control_revision",
        },
        "verify_demo_ai": {
            "status",
            "request_id",
            "credential_fingerprint",
            "credential_binding_id",
            "credential_control_revision",
            "admin_denied",
            "admin_cache_control",
            "admin_vary",
        },
        "verify_independent_channel_switches": {
            "status",
            "operator_independent",
            "demo_independent",
            "final_operator_enabled",
            "final_demo_enabled",
        },
        "verify_invalid_candidate_rollback": {
            "status",
            "safe_code",
            "prior_fingerprint",
            "resulting_fingerprint",
            "prior_operator_enabled",
            "resulting_operator_enabled",
            "prior_demo_enabled",
            "resulting_demo_enabled",
            "secret_scan_matches",
            "audit_event_count",
            "audit_secret_scan_matches",
            "audit_evidence_sha256",
        },
    }[state]
    if set(result) != keys:
        raise _invalid("admin_ai_release_evidence_invalid")
    serialized = json.dumps(result, sort_keys=True, separators=(",", ":"))
    if _CREDENTIAL_SHAPED.search(serialized) is not None or any(
        name in serialized.casefold()
        for name in (
            "api_key",
            "candidate_key",
            "current_password",
            "authorization",
            "provider_response",
        )
    ):
        raise _invalid("admin_ai_release_evidence_invalid")
    return result


def _validate_state_result(
    state: str,
    result: Mapping[str, object],
    *,
    package: Mapping[str, object],
    context: Mapping[str, object],
) -> None:
    baseline = package["azure_baseline"]
    request_id = result.get("request_id")
    if request_id is not None and (
        not isinstance(request_id, str) or _SAFE_ID.fullmatch(request_id) is None
    ):
        raise _invalid("admin_ai_release_evidence_invalid")
    if state == "readonly_revalidation" and result != {
        "required_azure_reads": 12,
        "observation_sha256": baseline["observation_sha256"],
        "role_assignment_phase": baseline["role_assignment_phase"],
        "database_revision": baseline["database_revision"],
    }:
        raise _invalid("admin_ai_release_baseline_drift")
    if state == "publish_candidate_image" and result != {
        "image_digest": package["candidate"]["image_digest"]
    }:
        raise _invalid("admin_ai_release_image_drift")
    if state == "deploy_admin_ai_capability" and (
        not isinstance(result["revision"], str)
        or _REVISION.fullmatch(result["revision"]) is None
        or result["migration"] != "0017_ai_turn_credential_binding"
        or result["migration_job_reads"] != 1
        or not isinstance(result["migration_job_projection_sha256"], str)
        or _SHA256.fullmatch(result["migration_job_projection_sha256"]) is None
        or not isinstance(result["migration_execution_template_sha256"], str)
        or _SHA256.fullmatch(result["migration_execution_template_sha256"])
        is None
        or result["operator_ai_enabled"] is not False
        or result["demo_ai_enabled"] is not False
    ):
        raise _invalid("admin_ai_release_deploy_drift")
    if state == "verify_ai_disabled_candidate" and (
        result["ready"] is not True
        or result["admin_protected"] is not True
        or result["summary_status"] != "ready"
        or result["operator_ai_enabled"] is not False
        or result["demo_ai_enabled"] is not False
    ):
        raise _invalid("admin_ai_release_disabled_gate_failed")
    if state == "rotate_key_through_admin" and not re.fullmatch(
        r"[0-9a-f]{8}", str(result["credential_fingerprint"])
    ):
        raise _invalid("admin_ai_release_fingerprint_invalid")
    if state in {"verify_operator_ai", "verify_demo_ai"} and (
        result["status"] != "completed"
        or result["credential_fingerprint"] != context.get("fingerprint")
        or not isinstance(result["credential_binding_id"], str)
        or _SHA256.fullmatch(result["credential_binding_id"]) is None
        or type(result["credential_control_revision"]) is not int
        or result["credential_control_revision"] < 0
    ):
        raise _invalid("admin_ai_release_shared_binding_failed")
    if state == "verify_demo_ai" and result["credential_binding_id"] != context.get(
        "credential_binding_id"
    ):
        raise _invalid("admin_ai_release_shared_binding_failed")
    if state == "verify_demo_ai" and (
        result["admin_denied"] is not True
        or result["admin_cache_control"] != "private, no-store"
        or result["admin_vary"] != "Cookie"
    ):
        raise _invalid("admin_ai_release_demo_admin_boundary_failed")
    if state == "verify_independent_channel_switches" and result != {
        "status": "completed",
        "operator_independent": True,
        "demo_independent": True,
        "final_operator_enabled": True,
        "final_demo_enabled": True,
    }:
        raise _invalid("admin_ai_release_channel_switch_failed")
    if state == "verify_invalid_candidate_rollback" and (
        result["status"] != "rejected"
        or result["safe_code"] != "ADMIN_AI_KEY_REJECTED"
        or result["prior_fingerprint"] != context.get("fingerprint")
        or result["resulting_fingerprint"] != context.get("fingerprint")
        or result["prior_operator_enabled"] is not True
        or result["resulting_operator_enabled"] is not True
        or result["prior_demo_enabled"] is not True
        or result["resulting_demo_enabled"] is not True
    ):
        raise _invalid("admin_ai_release_invalid_candidate_rollback_failed")
    if (
        state == "verify_invalid_candidate_rollback"
        and (
            result["secret_scan_matches"] != 0
            or result["audit_event_count"] != 8
            or result["audit_secret_scan_matches"] != 0
            or not isinstance(result["audit_evidence_sha256"], str)
            or _SHA256.fullmatch(result["audit_evidence_sha256"]) is None
        )
    ):
        raise _invalid("admin_ai_release_secret_scan_failed")


def _validate_task10_rbac_result(value: object) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "initial_phase",
        "final_phase",
        "assignment_set_sha256",
        "preflight_required_azure_reads",
        "vault_url",
        "identity_resource_id",
        "managed_identity_client_id",
    }:
        raise _invalid("admin_ai_release_rbac_drift")
    if (
        value["initial_phase"] not in {"legacy_only", "officer_only"}
        or value["final_phase"] != "officer_only"
        or not isinstance(value["assignment_set_sha256"], str)
        or _SHA256.fullmatch(value["assignment_set_sha256"]) is None
        or value["preflight_required_azure_reads"] != 12
    ):
        raise _invalid("admin_ai_release_rbac_drift")
    vault_url = value["vault_url"]
    identity_resource_id = value["identity_resource_id"]
    client_id = value["managed_identity_client_id"]
    if not isinstance(vault_url, str):
        raise _invalid("admin_ai_release_rbac_drift")
    parsed = urlsplit(vault_url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.hostname is None
        or not parsed.hostname.endswith(".vault.azure.net")
    ):
        raise _invalid("admin_ai_release_rbac_drift")
    if (
        not isinstance(identity_resource_id, str)
        or not identity_resource_id.casefold().startswith("/subscriptions/")
        or "/providers/microsoft.managedidentity/userassignedidentities/"
        not in identity_resource_id.casefold()
    ):
        raise _invalid("admin_ai_release_rbac_drift")
    try:
        parsed_client_id = UUID(str(client_id))
    except ValueError as error:
        raise _invalid("admin_ai_release_rbac_drift") from error
    if str(parsed_client_id) != client_id:
        raise _invalid("admin_ai_release_rbac_drift")


def _terminal_receipt(
    *,
    package: Mapping[str, object],
    package_digest: str,
    status: str,
    completed_states: list[str],
    failed_state: str | None,
    safe_error_code: str | None,
    context: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": "newcaostone.admin-ai-release-attempt.v1",
        "package_sha256": package_digest,
        "source_sha": package["repository"]["source_sha"],
        "source_tree": package["repository"]["source_tree"],
        "image_digest": package["candidate"]["image_digest"],
        "build_context_sha256": package["candidate"]["build_context_sha256"],
        "artifact_sha256": package["candidate"]["artifact_sha256"],
        "status": status,
        "completed_states": completed_states,
        "failed_state": failed_state,
        "safe_error_code": safe_error_code,
        "revision_names": list(context.get("revision_names", [])),
        "request_ids": list(context.get("request_ids", [])),
        "fingerprint_prefixes": list(context.get("fingerprint_prefixes", [])),
        "credential_binding_ids": list(
            context.get("credential_binding_ids", [])
        ),
        "rbac": {
            "initial_phase": package["azure_baseline"]["role_assignment_phase"],
            "final_phase": context.get("rbac_final_phase"),
            "required_azure_reads": context.get("rbac_read_count"),
            "assignment_set_sha256": context.get("rbac_assignment_set_sha256"),
        },
        "schema_recovery_boundary": {
            "pre_migration_head": package["azure_baseline"]["database_revision"],
            "post_migration_head": "0017_ai_turn_credential_binding",
            "safe_stop": "candidate_revision_only",
            "old_revision_routing": "prohibited_after_migration",
        },
        "audit_evidence": dict(context.get("audit_evidence", {})),
    }


def _validate_runtime_bindings(
    package: Mapping[str, object],
    *,
    approved_sha256: str,
    observed_now: datetime,
    repository_reader: Callable[[], object],
    authority_reader: Callable[[datetime], object] | None,
    artifact_reader: Callable[[], object] | None,
) -> str:
    current_digest = _validate_preexecution(package, now=observed_now)
    retired = package["replay_fence"]["retired_package_sha256"]
    if approved_sha256 in retired:
        raise _invalid("admin_ai_release_retired_package_hash")
    if (
        _SHA256.fullmatch(approved_sha256) is None
        or approved_sha256 != current_digest
    ):
        raise _invalid("admin_ai_release_approval_hash_mismatch")
    try:
        repository = repository_reader()
    except Exception as error:
        raise _invalid("admin_ai_release_repository_drift") from error
    if repository != package["repository"]:
        raise _invalid("admin_ai_release_repository_drift")
    try:
        current_authority = (
            capture_authority_binding(
                PROJECT_ROOT / "release/current_authority.json",
                now=observed_now,
            )
            if authority_reader is None
            else authority_reader(observed_now)
        )
    except Exception as error:
        raise _invalid("admin_ai_release_authority_drift") from error
    if current_authority != package["authority_binding"]:
        raise _invalid("admin_ai_release_authority_drift")
    candidate = package["candidate"]
    expected_artifact = {
        "artifact_format": candidate["artifact_format"],
        "artifact_path": candidate["artifact_path"],
        "artifact_sha256": candidate["artifact_sha256"],
        "image_digest": candidate["image_digest"],
        "platform": candidate["platform"],
        "source_sha": candidate["source_sha"],
        "source_tree": candidate["source_tree"],
        "image_input_sha256": candidate["image_input_sha256"],
        "build_context_sha256": candidate["build_context_sha256"],
        "oci_reference": candidate["oci_reference"],
        "runtime_user": candidate["runtime_user"],
    }
    try:
        current_artifact = (
            capture_candidate_artifact(
                PROJECT_ROOT / str(candidate["artifact_path"]),
                source_sha=str(candidate["source_sha"]),
                source_tree=str(candidate["source_tree"]),
                image_input_sha256=str(candidate["image_input_sha256"]),
                build_context_sha256=str(candidate["build_context_sha256"]),
            )
            if artifact_reader is None
            else artifact_reader()
        )
    except Exception as error:
        raise _invalid("admin_ai_release_candidate_artifact_drift") from error
    if current_artifact != expected_artifact:
        raise _invalid("admin_ai_release_candidate_artifact_drift")
    return current_digest


def run_once(
    package: Mapping[str, object],
    operations: AdminAIReleaseOperations,
    *,
    approved_sha256: str,
    key_reader: Callable[[], str] = read_candidate_key,
    now: datetime | None = None,
    repository_reader: Callable[[], object] = capture_repository,
    authority_reader: Callable[[datetime], object] | None = None,
    artifact_reader: Callable[[], object] | None = None,
    reserved_descriptor: int | None = None,
) -> dict[str, object]:
    """Run the fixed release sequence once and create exactly one terminal receipt."""

    observed_now = datetime.now(UTC) if now is None else now
    current_digest = _validate_runtime_bindings(
        package,
        approved_sha256=approved_sha256,
        observed_now=observed_now,
        repository_reader=repository_reader,
        authority_reader=authority_reader,
        artifact_reader=artifact_reader,
    )
    completed: list[str] = []
    failed_state: str | None = None
    failure_code: str | None = None
    context: dict[str, object] = {
        "package_sha256": current_digest,
        "source_git_sha": package["repository"]["source_sha"],
        "known_invalid_sentinel": KNOWN_INVALID_SENTINEL,
        "revision_names": [],
        "request_ids": [],
        "fingerprint_prefixes": [],
        "credential_binding_ids": [],
    }
    owns_descriptor = reserved_descriptor is None
    descriptor = reserved_descriptor
    if descriptor is None:
        started = _terminal_receipt(
            package=package,
            package_digest=current_digest,
            status="started",
            completed_states=[],
            failed_state=None,
            safe_error_code=None,
            context=context,
        )
        receipt_path = Path(str(package["execution_contract"]["receipt_path"]))
        descriptor = _reserve_receipt(receipt_path, started)
    candidate_buffer: bytearray | None = None
    try:
        for state in ADMIN_AI_RELEASE_STATES:
            failed_state = state
            secret_value: str | None = None
            if state == "deploy_admin_ai_capability":
                migration = operations.reconcile_admin_ai_secret_access(
                    context={
                        "package_sha256": current_digest,
                        "source_git_sha": package["repository"]["source_sha"],
                        "role_assignment_phase": package["azure_baseline"][
                            "role_assignment_phase"
                        ],
                    }
                )
                _validate_task10_rbac_result(migration)
                if migration["initial_phase"] != package["azure_baseline"][
                    "role_assignment_phase"
                ]:
                    raise _invalid("admin_ai_release_rbac_drift")
                context["rbac_final_phase"] = "officer_only"
                context["rbac_read_count"] = migration[
                    "preflight_required_azure_reads"
                ]
                context["rbac_assignment_set_sha256"] = migration[
                    "assignment_set_sha256"
                ]
                context["vault_url"] = migration["vault_url"]
                context["identity_resource_id"] = migration[
                    "identity_resource_id"
                ]
                context["managed_identity_client_id"] = migration[
                    "managed_identity_client_id"
                ]
            if state == "rotate_key_through_admin":
                try:
                    candidate = key_reader()
                except Exception as error:
                    raise _invalid("admin_ai_release_key_input_failed") from error
                if not isinstance(candidate, str) or not candidate:
                    raise _invalid("admin_ai_release_key_missing")
                candidate_buffer = bytearray(candidate.encode("utf-8"))
                candidate = ""
                secret_value = candidate_buffer.decode("utf-8")
            try:
                raw_result = operations.run(
                    state,
                    secret_value=secret_value,
                    context=deepcopy(context),
                )
            finally:
                secret_value = None
                if state == "rotate_key_through_admin" and candidate_buffer is not None:
                    for index in range(len(candidate_buffer)):
                        candidate_buffer[index] = 0
                    candidate_buffer.clear()
                    candidate_buffer = None
            result = _exact_result(state, raw_result)
            _validate_state_result(
                state,
                result,
                package=package,
                context=context,
            )
            if "revision" in result and isinstance(result["revision"], str):
                context["revision_names"].append(result["revision"])
            if "request_id" in result:
                context["request_ids"].append(result["request_id"])
            if state == "rotate_key_through_admin":
                context["fingerprint"] = result["credential_fingerprint"]
                context["fingerprint_prefixes"].append(
                    result["credential_fingerprint"]
                )
            elif state == "verify_operator_ai":
                context["operator_turn"] = deepcopy(result)
                context["credential_binding_id"] = result[
                    "credential_binding_id"
                ]
                context["credential_binding_ids"].append(
                    result["credential_binding_id"]
                )
            elif state == "verify_demo_ai":
                context["demo_turn"] = deepcopy(result)
                context["credential_binding_ids"].append(
                    result["credential_binding_id"]
                )
            elif state == "verify_independent_channel_switches":
                context["channel_switches"] = deepcopy(result)
            elif state == "verify_invalid_candidate_rollback":
                rollback = deepcopy(result)
                context["secret_scan_matches"] = rollback.pop(
                    "secret_scan_matches"
                )
                context["audit_evidence"] = {
                    "event_count": rollback.pop("audit_event_count"),
                    "secret_scan_matches": rollback.pop(
                        "audit_secret_scan_matches"
                    ),
                    "evidence_sha256": rollback.pop(
                        "audit_evidence_sha256"
                    ),
                }
                context["invalid_rollback"] = rollback
            completed.append(state)
        hosted = verify_hosted_admin_ai_control(
            {
                "revision": context["revision_names"][0],
                "admin_entry": {
                    "status": "protected",
                    "summary_status": "ready",
                    "request_id": context["request_ids"][0],
                },
                "operator_turn": context.get("operator_turn", {}),
                "demo_turn": context.get("demo_turn", {}),
                "channel_switches": context.get("channel_switches", {}),
                "invalid_candidate_rollback": context.get("invalid_rollback", {}),
                "secret_scan_matches": context.get("secret_scan_matches"),
                "audit_evidence": context.get("audit_evidence", {}),
            }
        )
        del hosted
        failed_state = None
        status = "completed"
    except (Exception, KeyboardInterrupt) as error:
        status = "failed"
        failure_code = _safe_code(error)
    finally:
        if candidate_buffer is not None:
            for index in range(len(candidate_buffer)):
                candidate_buffer[index] = 0
            candidate_buffer.clear()
        receipt = _terminal_receipt(
            package=package,
            package_digest=current_digest,
            status=status,
            completed_states=completed,
            failed_state=failed_state,
            safe_error_code=failure_code,
            context=context,
        )
        try:
            _write_reserved_receipt(descriptor, receipt)
        finally:
            if owns_descriptor:
                os.close(descriptor)
    return receipt


def _load_operations_factory(
    binding: Mapping[str, object],
    *,
    source_sha: str,
) -> Callable[..., object]:
    try:
        specification = str(binding["factory"])
        observed_binding = capture_operations_factory(
            specification,
            source_sha=source_sha,
        )
    except (KeyError, TypeError, AdminAIReleasePackageInvalid) as error:
        raise _invalid("admin_ai_release_operations_factory_invalid") from error
    if observed_binding != binding:
        raise _invalid("admin_ai_release_operations_factory_drift")
    module_name, attribute = specification.split(":", 1)
    try:
        factory = getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as error:
        raise _invalid("admin_ai_release_operations_factory_invalid") from error
    if not callable(factory):
        raise _invalid("admin_ai_release_operations_factory_invalid")
    return factory


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--approved-sha256", required=True)
    options = parser.parse_args(arguments)
    now = datetime.now(UTC)
    descriptor: int | None = None
    package: Mapping[str, object] | None = None
    digest: str | None = None
    try:
        package = load_package(options.package, now=now)
        digest = _validate_runtime_bindings(
            package,
            approved_sha256=options.approved_sha256,
            observed_now=now,
            repository_reader=capture_repository,
            authority_reader=None,
            artifact_reader=None,
        )
        started_context = {
            "revision_names": [],
            "request_ids": [],
            "fingerprint_prefixes": [],
            "credential_binding_ids": [],
        }
        started = _terminal_receipt(
            package=package,
            package_digest=digest,
            status="started",
            completed_states=[],
            failed_state=None,
            safe_error_code=None,
            context=started_context,
        )
        descriptor = _reserve_receipt(
            Path(str(package["execution_contract"]["receipt_path"])),
            started,
        )
        factory = _load_operations_factory(
            package["operations_factory"],
            source_sha=str(package["repository"]["source_sha"]),
        )
        operations = factory(
            package=deepcopy(package),
            approved_sha256=options.approved_sha256,
        )
        receipt = run_once(
            package,
            operations,
            approved_sha256=options.approved_sha256,
            now=now,
            reserved_descriptor=descriptor,
        )
        os.close(descriptor)
        descriptor = None
    except (Exception, KeyboardInterrupt) as error:
        if descriptor is not None and package is not None and digest is not None:
            failed = _terminal_receipt(
                package=package,
                package_digest=digest,
                status="failed",
                completed_states=[],
                failed_state="operations_factory_initialization",
                safe_error_code=_safe_code(error),
                context={},
            )
            try:
                _write_reserved_receipt(descriptor, failed)
            finally:
                os.close(descriptor)
        print("admin_ai_release=failed")
        print(f"reason={_safe_code(error)}")
        return 1
    print(f"admin_ai_release={receipt['status']}")
    return 0 if receipt["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
