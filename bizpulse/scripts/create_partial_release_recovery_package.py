#!/usr/bin/env python3
"""Create an exact AI-disabled package for a recorded partial release failure."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.create_two_stage_release_package import (  # noqa: E402
    TwoStagePackageInvalid,
    build_data_stage_authority,
)
from scripts.verify_partial_release_state import (  # noqa: E402
    PartialReleaseStateInvalid,
    load_partial_release_incident,
    validate_partial_release_incident,
)
from tests.hosted.verify_azure_demo import (  # noqa: E402
    AuthorizationInvalid,
    SECRET_PATTERN,
    _load_authorization_bytes,
    data_authority_sha256,
)


HEADER = "# NEWCaostone Partial Release Recovery Authorization"
SCHEMA = "newcaostone.partial-release-recovery.v1"
STAGES = (
    "incident_preflight",
    "registry_verify",
    "bind_seed",
    "rebound_preflight",
    "seed",
    "deploy",
    "health",
    "browser_acceptance",
    "capacity",
    "expiry",
    "restart_readback",
    "rollback",
)
ALLOWED_OPERATIONS = (
    "azure_read_partial_state",
    "registry_digest_readback",
    "azure_job_update",
    "synthetic_seed",
    "deploy_digest",
    "hosted_verify",
    "rollback_rehearsal",
)
STOP_CONDITIONS = (
    "incident_or_authority_changed",
    "partial_state_changed",
    "registry_digest_changed",
    "job_rebind_failed",
    "seed_failed",
    "deployment_or_hosted_verification_failed",
    "secret_boundary_failed",
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9._/-]{1,255}")
CONTROL_HASH_PATHS = (
    "scripts/create_partial_release_recovery_package.py",
    "scripts/update_azure_job_binding.py",
    "scripts/verify_partial_release_state.py",
)


class PartialReleaseRecoveryInvalid(ValueError):
    """The partial recovery authority is incomplete, drifted or unsafe."""


def _timestamp(value: object, code: str) -> datetime:
    if not isinstance(value, str):
        raise PartialReleaseRecoveryInvalid(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PartialReleaseRecoveryInvalid(code) from error
    if parsed.tzinfo is None:
        raise PartialReleaseRecoveryInvalid(code)
    return parsed.astimezone(UTC)


def _reference(value: object) -> str:
    if not isinstance(value, str) or REFERENCE_PATTERN.fullmatch(value) is None:
        raise PartialReleaseRecoveryInvalid("partial_recovery_reference_invalid")
    logical = PurePosixPath(value)
    if logical.is_absolute() or ".." in logical.parts or "." in logical.parts:
        raise PartialReleaseRecoveryInvalid("partial_recovery_reference_invalid")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("partial_recovery_json_duplicate_key")
        result[key] = value
    return result


def _release_matches_incident(
    authority: dict[str, Any], incident: dict[str, Any]
) -> bool:
    release = authority.get("release")
    target = incident["target"]
    generated = authority.get("generated_names")
    recorded = incident["release"]
    if not isinstance(release, dict) or not isinstance(generated, dict):
        return False
    expected_release = {
        "candidate_git_sha": release.get("git_sha"),
        "attestation_git_sha": release.get("attestation_git_sha"),
        "candidate_image_digest": release.get("image_digest"),
        "candidate_image_input_sha256": release.get("image_input_sha256"),
        "migration_head": release.get("migration_head"),
        "synthetic_manifest_sha256": release.get("synthetic_manifest_sha256"),
        "synthetic_dataset_version_id": release.get(
            "synthetic_dataset_version_id"
        ),
        "rollback_git_sha": release.get("rollback_git_sha"),
        "rollback_image_digest": release.get("rollback_image_digest"),
        "rollback_image_input_sha256": release.get(
            "rollback_image_input_sha256"
        ),
    }
    expected_target = {
        "subscription_id": authority.get("subscription_id"),
        "region": authority.get("region"),
        "resource_group": authority.get("resource_group"),
        "public_url": authority.get("public_url"),
        "name_prefix": generated.get("name_prefix"),
        "registry_name": generated.get("registry_name"),
        "image_repository": generated.get("image_repository"),
        "storage_account": generated.get("storage_account"),
        "postgres_server": generated.get("postgres_server"),
        "postgres_administrator_login": generated.get(
            "postgres_administrator_login"
        ),
        "application": generated.get("container_app"),
        "prepare_job": generated.get("migration_job"),
        "seed_job": generated.get("seed_job"),
    }
    return all(recorded.get(key) == value for key, value in expected_release.items()) and all(
        target.get(key) == value for key, value in expected_target.items()
    )


def _partial_state_command(
    *,
    incident_reference: str,
    incident_sha256: str,
    mode: str,
) -> str:
    return (
        ".venv/bin/python scripts/verify_partial_release_state.py "
        f"--incident {incident_reference} "
        f"--incident-sha256 {incident_sha256} --mode {mode}"
    )


def _control_sha256() -> dict[str, str]:
    try:
        return {
            path: hashlib.sha256((PROJECT_ROOT / path).read_bytes()).hexdigest()
            for path in CONTROL_HASH_PATHS
        }
    except OSError as error:
        raise PartialReleaseRecoveryInvalid(
            "partial_recovery_control_invalid"
        ) from error


def _expected_recovery_commands(
    authority: dict[str, Any],
    *,
    incident_reference: str,
    incident_sha256: str,
) -> dict[str, list[str]]:
    source = authority.get("commands")
    if not isinstance(source, dict):
        raise PartialReleaseRecoveryInvalid("partial_recovery_authority_invalid")
    expected_lengths = {
        "registry_verify": 2,
        "provision": 2,
        "seed": 1,
        "deploy": 4,
        "health": 1,
        "browser_acceptance": 1,
        "capacity": 1,
        "expiry": 1,
        "restart_readback": 1,
        "rollback": 1,
    }
    if any(
        not isinstance(source.get(stage), list)
        or len(source[stage]) != count
        for stage, count in expected_lengths.items()
    ):
        raise PartialReleaseRecoveryInvalid("partial_recovery_authority_invalid")
    return {
        "incident_preflight": [
            _partial_state_command(
                incident_reference=incident_reference,
                incident_sha256=incident_sha256,
                mode="failed",
            )
        ],
        "registry_verify": list(source["registry_verify"]),
        "bind_seed": [source["provision"][1]],
        "rebound_preflight": [
            _partial_state_command(
                incident_reference=incident_reference,
                incident_sha256=incident_sha256,
                mode="rebound",
            )
        ],
        "seed": list(source["seed"]),
        "deploy": list(source["deploy"]),
        "health": list(source["health"]),
        "browser_acceptance": list(source["browser_acceptance"]),
        "capacity": list(source["capacity"]),
        "expiry": list(source["expiry"]),
        "restart_readback": list(source["restart_readback"]),
        "rollback": list(source["rollback"]),
    }


def build_partial_release_recovery_package(
    *,
    authority: dict[str, Any],
    incident: dict[str, Any],
    incident_reference: str,
    incident_sha256: str,
    authorization_id: str,
    issued_at: str,
    expires_at: str,
) -> dict[str, Any]:
    incident = validate_partial_release_incident(incident)
    reference = _reference(incident_reference)
    if SHA256_PATTERN.fullmatch(incident_sha256) is None:
        raise PartialReleaseRecoveryInvalid("partial_recovery_incident_invalid")
    issued = _timestamp(issued_at, "partial_recovery_time_invalid")
    expires = _timestamp(expires_at, "partial_recovery_time_invalid")
    if (
        UUID_PATTERN.fullmatch(authorization_id) is None
        or expires <= issued
        or expires - issued > timedelta(hours=48)
    ):
        raise PartialReleaseRecoveryInvalid("partial_recovery_identity_invalid")
    try:
        validated_authority = _load_authorization_bytes(
            (
                "# NEWCaostone Launch Authorization\n\n```json\n"
                + json.dumps(authority, indent=2, sort_keys=True)
                + "\n```\n"
            ).encode(),
            now=issued,
        )
    except AuthorizationInvalid as error:
        raise PartialReleaseRecoveryInvalid(
            "partial_recovery_authority_invalid"
        ) from error
    publication = validated_authority["external_publication"]
    ai_limits = validated_authority["ai_limits"]
    secrets = validated_authority["secret_presence"]
    if (
        publication["registry_publish"] is not False
        or publication["paid_ai_smoke"] is not False
        or ai_limits["enabled"] is not False
        or secrets["openai_api_key"] is not False
        or validated_authority["commands"]["registry_publish"] != []
        or validated_authority["commands"]["migrate"] == []
    ):
        raise PartialReleaseRecoveryInvalid("partial_recovery_authority_invalid")
    if not _release_matches_incident(validated_authority, incident):
        raise PartialReleaseRecoveryInvalid("partial_recovery_release_mismatch")
    commands = _expected_recovery_commands(
        validated_authority,
        incident_reference=reference,
        incident_sha256=incident_sha256,
    )
    package: dict[str, Any] = {
        "schema_version": SCHEMA,
        "authorization_id": authorization_id,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "incident_reference": reference,
        "incident_sha256": incident_sha256,
        "source_package_sha256": incident["source_package"]["sha256"],
        "data_authority_sha256": data_authority_sha256(validated_authority),
        "control_sha256": _control_sha256(),
        "authority": validated_authority,
        "no_ai": True,
        "completed_operations": ["registry_publish", "postgres_migrate"],
        "commands": commands,
        "execution_order": list(STAGES),
        "retry_limits": {"read": 1, "deploy": 0, "paid_provider": 0},
        "allowed_operations": list(ALLOWED_OPERATIONS),
        "stop_conditions": list(STOP_CONDITIONS),
    }
    if SECRET_PATTERN.search(json.dumps(package, sort_keys=True)):
        raise PartialReleaseRecoveryInvalid("partial_recovery_secret_forbidden")
    return package


def write_partial_release_recovery_package(
    path: Path, package: dict[str, Any]
) -> str:
    payload = (
        HEADER
        + "\n\n```json\n"
        + json.dumps(package, indent=2, sort_keys=True)
        + "\n```\n"
    ).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise PartialReleaseRecoveryInvalid("partial_recovery_mode_invalid")
    return hashlib.sha256(payload).hexdigest()


def load_partial_release_recovery_package(
    path: Path,
    *,
    incident_path: Path,
    now: str | datetime | None = None,
) -> dict[str, Any]:
    try:
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise PartialReleaseRecoveryInvalid("partial_recovery_mode_invalid")
        source = path.read_text()
    except OSError as error:
        raise PartialReleaseRecoveryInvalid("partial_recovery_document_invalid") from error
    match = re.fullmatch(
        re.escape(HEADER) + r"\n\n```json\n(?P<payload>.*)\n```\n?",
        source,
        flags=re.DOTALL,
    )
    if match is None:
        raise PartialReleaseRecoveryInvalid("partial_recovery_document_invalid")
    try:
        package = json.loads(
            match.group("payload"), object_pairs_hook=_unique_object
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise PartialReleaseRecoveryInvalid("partial_recovery_document_invalid") from error
    expected_fields = {
        "schema_version",
        "authorization_id",
        "issued_at",
        "expires_at",
        "incident_reference",
        "incident_sha256",
        "source_package_sha256",
        "data_authority_sha256",
        "control_sha256",
        "authority",
        "no_ai",
        "completed_operations",
        "commands",
        "execution_order",
        "retry_limits",
        "allowed_operations",
        "stop_conditions",
    }
    if not isinstance(package, dict) or set(package) != expected_fields:
        raise PartialReleaseRecoveryInvalid("partial_recovery_fields_invalid")
    checked_at = (
        _timestamp(now, "partial_recovery_time_invalid")
        if isinstance(now, str)
        else (now.astimezone(UTC) if isinstance(now, datetime) else datetime.now(UTC))
    )
    issued = _timestamp(package["issued_at"], "partial_recovery_time_invalid")
    expires = _timestamp(package["expires_at"], "partial_recovery_time_invalid")
    if checked_at < issued or checked_at >= expires:
        raise PartialReleaseRecoveryInvalid("partial_recovery_expired")
    reference = _reference(package["incident_reference"])
    if not incident_path.as_posix().endswith(reference):
        raise PartialReleaseRecoveryInvalid("partial_recovery_reference_invalid")
    try:
        incident = load_partial_release_incident(
            incident_path,
            expected_sha256=package["incident_sha256"],
        )
    except PartialReleaseStateInvalid as error:
        raise PartialReleaseRecoveryInvalid("partial_recovery_incident_invalid") from error
    expected = build_partial_release_recovery_package(
        authority=package["authority"],
        incident=incident,
        incident_reference=reference,
        incident_sha256=package["incident_sha256"],
        authorization_id=package["authorization_id"],
        issued_at=package["issued_at"],
        expires_at=package["expires_at"],
    )
    if package != expected:
        raise PartialReleaseRecoveryInvalid("partial_recovery_drift")
    return package


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incident", required=True, type=Path)
    parser.add_argument("--incident-reference", required=True)
    parser.add_argument("--release-attestation", required=True, type=Path)
    parser.add_argument("--attestation-git-sha", required=True)
    parser.add_argument("--authorization-id")
    parser.add_argument("--expires-hours", type=int, default=24)
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args(arguments)
    try:
        incident_bytes = options.incident.read_bytes()
        incident = load_partial_release_incident(options.incident)
        if not 1 <= options.expires_hours <= 48:
            raise PartialReleaseRecoveryInvalid("partial_recovery_expiry_invalid")
        issued = datetime.now(UTC).replace(microsecond=0)
        expires = issued + timedelta(hours=options.expires_hours)
        target = incident["target"]
        authority = build_data_stage_authority(
            attestation_path=options.release_attestation,
            attestation_git_sha=options.attestation_git_sha,
            authorization_id=options.authorization_id or str(uuid4()),
            issued_at=issued.isoformat().replace("+00:00", "Z"),
            expires_at=expires.isoformat().replace("+00:00", "Z"),
            subscription_id=target["subscription_id"],
            region=target["region"],
            resource_group=target["resource_group"],
            public_url=target["public_url"],
            name_prefix=target["name_prefix"],
            registry_name=target["registry_name"],
            image_repository=target["image_repository"],
            storage_account=target["storage_account"],
            postgres_server=target["postgres_server"],
            postgres_administrator_login=target[
                "postgres_administrator_login"
            ],
            observed_current_image_digest=incident["release"][
                "rollback_image_digest"
            ],
            hard_cap_usd="100.00",
            one_time_estimate_usd="0.00",
            monthly_estimate_usd="80.00",
            registry_publish=False,
        )
        package = build_partial_release_recovery_package(
            authority=authority,
            incident=incident,
            incident_reference=options.incident_reference,
            incident_sha256=hashlib.sha256(incident_bytes).hexdigest(),
            authorization_id=authority["authorization_id"],
            issued_at=authority["issued_at"],
            expires_at=authority["expires_at"],
        )
        digest = write_partial_release_recovery_package(options.output, package)
        load_partial_release_recovery_package(
            options.output,
            incident_path=options.incident,
            now=issued,
        )
    except (
        OSError,
        PartialReleaseRecoveryInvalid,
        PartialReleaseStateInvalid,
        TwoStagePackageInvalid,
    ) as error:
        options.output.unlink(missing_ok=True)
        print(str(error))
        print("partial_recovery_package=failed")
        return 1
    print("partial_recovery_package=ok")
    print(f"output={options.output}")
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
