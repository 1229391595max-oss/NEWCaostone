#!/usr/bin/env python3
"""Create the owner-only V6 package for pending hosted acceptance only."""

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
from scripts.verify_deployed_release_state import (  # noqa: E402
    COMPLETED_OPERATIONS,
    DeployedReleaseStateInvalid,
    load_deployed_release_continuation,
    validate_deployed_release_continuation,
)
from tests.hosted.verify_azure_demo import (  # noqa: E402
    AuthorizationInvalid,
    SECRET_PATTERN,
    _load_authorization_bytes,
    data_authority_sha256,
)


HEADER = "# NEWCaostone Deployed Release Recovery V6 Authorization"
SCHEMA = "newcaostone.deployed-release-recovery.v1"
STAGES = (
    "deployed_preflight",
    "registry_verify",
    "health",
    "browser_acceptance",
    "capacity",
    "expiry",
    "restart_readback",
    "rollback",
)
KEYCHAIN_SOURCES = (
    {
        "account": "operator",
        "environment": "BIZPULSE_OPERATOR_PASSWORD_HASH_CHECK",
        "scope": "credential_pair_validation",
        "service": "NEWCaostone Azure Demo Operator Password Hash",
    },
    {
        "account": "operator",
        "environment": "BIZPULSE_BROWSER_OPERATOR_PASSWORD",
        "scope": "browser_acceptance",
        "service": "NEWCaostone Azure Demo Operator Password",
    },
)
CONTROL_HASH_PATHS = (
    "scripts/create_deployed_release_recovery_package.py",
    "scripts/run_deployed_release_recovery.py",
    "scripts/verify_deployed_release_state.py",
)
ALLOWED_OPERATIONS = (
    "azure_read_deployed_state",
    "registry_digest_readback",
    "keychain_credential_read",
    "hosted_verify",
    "restart_readback",
    "rollback_rehearsal",
)
STOP_CONDITIONS = (
    "package_or_control_hash_changed",
    "deployed_state_changed",
    "registry_digest_changed",
    "credential_pair_validation_failed",
    "package_already_consumed",
    "hosted_verification_failed",
    "secret_boundary_failed",
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9._/-]{1,255}")


class DeployedReleaseRecoveryInvalid(ValueError):
    """The deployed recovery authority is incomplete, drifted or unsafe."""


def _timestamp(value: object, code: str) -> datetime:
    if not isinstance(value, str):
        raise DeployedReleaseRecoveryInvalid(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DeployedReleaseRecoveryInvalid(code) from error
    if parsed.tzinfo is None:
        raise DeployedReleaseRecoveryInvalid(code)
    return parsed.astimezone(UTC)


def _reference(value: object) -> str:
    if not isinstance(value, str) or REFERENCE_PATTERN.fullmatch(value) is None:
        raise DeployedReleaseRecoveryInvalid(
            "deployed_recovery_reference_invalid"
        )
    logical = PurePosixPath(value)
    if logical.is_absolute() or "." in logical.parts or ".." in logical.parts:
        raise DeployedReleaseRecoveryInvalid(
            "deployed_recovery_reference_invalid"
        )
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("deployed_recovery_json_duplicate_key")
        result[key] = value
    return result


def _control_sha256() -> dict[str, str]:
    try:
        return {
            path: hashlib.sha256((PROJECT_ROOT / path).read_bytes()).hexdigest()
            for path in CONTROL_HASH_PATHS
        }
    except OSError as error:
        raise DeployedReleaseRecoveryInvalid(
            "deployed_recovery_control_invalid"
        ) from error


def _release_matches_continuation(
    authority: dict[str, Any], continuation: dict[str, Any]
) -> bool:
    release = authority.get("release")
    generated = authority.get("generated_names")
    limits = authority.get("limits_usd")
    target = continuation["target"]
    recorded = continuation["release"]
    if not all(isinstance(item, dict) for item in (release, generated, limits)):
        return False
    expected_release = {
        "candidate_git_sha": release.get("git_sha"),
        "candidate_image_digest": release.get("image_digest"),
        "rollback_git_sha": release.get("rollback_git_sha"),
        "rollback_image_digest": release.get("rollback_image_digest"),
        "migration_head": release.get("migration_head"),
        "synthetic_manifest_sha256": release.get("synthetic_manifest_sha256"),
        "synthetic_dataset_version_id": release.get(
            "synthetic_dataset_version_id"
        ),
    }
    expected_target = {
        "subscription_id": authority.get("subscription_id"),
        "region": authority.get("region"),
        "resource_group": authority.get("resource_group"),
        "public_url": authority.get("public_url"),
        "name_prefix": generated.get("name_prefix"),
        "application": generated.get("container_app"),
        "application_revision": generated.get("application_revision"),
        "environment": generated.get("container_environment"),
        "prepare_job": generated.get("migration_job"),
        "seed_job": generated.get("seed_job"),
        "session_maintenance_job": generated.get(
            "session_maintenance_job"
        ),
        "storage_maintenance_job": generated.get(
            "storage_maintenance_job"
        ),
        "registry_name": generated.get("registry_name"),
        "image_repository": generated.get("image_repository"),
        "storage_account": generated.get("storage_account"),
        "postgres_server": generated.get("postgres_server"),
        "postgres_administrator_login": generated.get(
            "postgres_administrator_login"
        ),
    }
    expected_limits = {
        "hard_cap": "100.00",
        "one_time_estimate": "0.00",
        "monthly_estimate": "80.00",
        "openai_smoke_cap": "0.00",
    }
    return (
        all(recorded.get(key) == value for key, value in expected_release.items())
        and all(target.get(key) == value for key, value in expected_target.items())
        and limits == expected_limits
    )


def _build_authority_from_continuation(
    *,
    continuation: dict[str, Any],
    attestation_path: Path,
    attestation_git_sha: str,
    authorization_id: str,
    issued_at: str,
    expires_at: str,
) -> dict[str, Any]:
    continuation = validate_deployed_release_continuation(continuation)
    target = continuation["target"]
    release = continuation["release"]
    authority = build_data_stage_authority(
        attestation_path=attestation_path,
        attestation_git_sha=attestation_git_sha,
        authorization_id=authorization_id,
        issued_at=issued_at,
        expires_at=expires_at,
        subscription_id=target["subscription_id"],
        region=target["region"],
        resource_group=target["resource_group"],
        public_url=target["public_url"],
        name_prefix=target["name_prefix"],
        registry_name=target["registry_name"],
        image_repository=target["image_repository"],
        storage_account=target["storage_account"],
        postgres_server=target["postgres_server"],
        postgres_administrator_login=target["postgres_administrator_login"],
        observed_current_image_digest=release["candidate_image_digest"],
        hard_cap_usd="100.00",
        one_time_estimate_usd="0.00",
        monthly_estimate_usd="80.00",
        registry_publish=False,
    )
    if not _release_matches_continuation(authority, continuation):
        raise DeployedReleaseRecoveryInvalid(
            "deployed_recovery_release_mismatch"
        )
    return authority


def _deployed_state_command(*, reference: str, sha256: str) -> str:
    return (
        ".venv/bin/python scripts/verify_deployed_release_state.py "
        f"--continuation {reference} --continuation-sha256 {sha256}"
    )


def _expected_commands(
    authority: dict[str, Any], *, reference: str, sha256: str
) -> dict[str, list[str]]:
    source = authority.get("commands")
    expected_lengths = {
        "registry_verify": 2,
        "health": 1,
        "browser_acceptance": 1,
        "capacity": 1,
        "expiry": 1,
        "restart_readback": 1,
        "rollback": 1,
    }
    if not isinstance(source, dict) or any(
        not isinstance(source.get(stage), list)
        or len(source[stage]) != count
        for stage, count in expected_lengths.items()
    ):
        raise DeployedReleaseRecoveryInvalid(
            "deployed_recovery_authority_invalid"
        )
    return {
        "deployed_preflight": [
            _deployed_state_command(reference=reference, sha256=sha256)
        ],
        **{stage: list(source[stage]) for stage in STAGES[1:]},
    }


def build_deployed_release_recovery_package(
    *,
    authority: dict[str, Any],
    continuation: dict[str, Any],
    continuation_reference: str,
    continuation_sha256: str,
    authorization_id: str,
    issued_at: str,
    expires_at: str,
) -> dict[str, Any]:
    continuation = validate_deployed_release_continuation(continuation)
    reference = _reference(continuation_reference)
    if SHA256_PATTERN.fullmatch(continuation_sha256) is None:
        raise DeployedReleaseRecoveryInvalid(
            "deployed_recovery_continuation_invalid"
        )
    issued = _timestamp(issued_at, "deployed_recovery_time_invalid")
    expires = _timestamp(expires_at, "deployed_recovery_time_invalid")
    if (
        UUID_PATTERN.fullmatch(authorization_id) is None
        or expires <= issued
        or expires - issued > timedelta(hours=48)
    ):
        raise DeployedReleaseRecoveryInvalid(
            "deployed_recovery_identity_invalid"
        )
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
        raise DeployedReleaseRecoveryInvalid(
            "deployed_recovery_authority_invalid"
        ) from error
    publication = validated_authority["external_publication"]
    ai_limits = validated_authority["ai_limits"]
    secrets = validated_authority["secret_presence"]
    commands = validated_authority["commands"]
    if (
        validated_authority["authorization_id"] != authorization_id
        or validated_authority["issued_at"] != issued_at
        or validated_authority["expires_at"] != expires_at
        or publication["registry_publish"] is not False
        or publication["paid_ai_smoke"] is not False
        or ai_limits["enabled"] is not False
        or secrets["openai_api_key"] is not False
        or commands["registry_publish"] != []
        or commands["paid_ai_smoke"] != []
    ):
        raise DeployedReleaseRecoveryInvalid(
            "deployed_recovery_authority_invalid"
        )
    if not _release_matches_continuation(validated_authority, continuation):
        raise DeployedReleaseRecoveryInvalid(
            "deployed_recovery_release_mismatch"
        )
    package: dict[str, Any] = {
        "schema_version": SCHEMA,
        "authorization_id": authorization_id,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "continuation_reference": reference,
        "continuation_sha256": continuation_sha256,
        "source_recovery_sha256": continuation["source_recovery"][
            "package_sha256"
        ],
        "data_authority_sha256": data_authority_sha256(validated_authority),
        "control_sha256": _control_sha256(),
        "authority": validated_authority,
        "no_ai": True,
        "completed_operations": list(COMPLETED_OPERATIONS),
        "keychain_sources": [dict(item) for item in KEYCHAIN_SOURCES],
        "commands": _expected_commands(
            validated_authority,
            reference=reference,
            sha256=continuation_sha256,
        ),
        "execution_order": list(STAGES),
        "retry_limits": {"read": 1, "deploy": 0, "paid_provider": 0},
        "allowed_operations": list(ALLOWED_OPERATIONS),
        "stop_conditions": list(STOP_CONDITIONS),
    }
    if SECRET_PATTERN.search(json.dumps(package, sort_keys=True)):
        raise DeployedReleaseRecoveryInvalid(
            "deployed_recovery_secret_forbidden"
        )
    return package


def write_deployed_release_recovery_package(
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
        raise DeployedReleaseRecoveryInvalid("deployed_recovery_mode_invalid")
    return hashlib.sha256(payload).hexdigest()


def load_deployed_release_recovery_package(
    path: Path,
    *,
    continuation_path: Path,
    now: str | datetime | None = None,
) -> dict[str, Any]:
    try:
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise DeployedReleaseRecoveryInvalid(
                "deployed_recovery_mode_invalid"
            )
        source = path.read_text()
    except OSError as error:
        raise DeployedReleaseRecoveryInvalid(
            "deployed_recovery_document_invalid"
        ) from error
    match = re.fullmatch(
        re.escape(HEADER) + r"\n\n```json\n(?P<payload>.*)\n```\n?",
        source,
        flags=re.DOTALL,
    )
    if match is None:
        raise DeployedReleaseRecoveryInvalid(
            "deployed_recovery_document_invalid"
        )
    try:
        package = json.loads(
            match.group("payload"), object_pairs_hook=_unique_object
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise DeployedReleaseRecoveryInvalid(
            "deployed_recovery_document_invalid"
        ) from error
    expected_fields = {
        "schema_version",
        "authorization_id",
        "issued_at",
        "expires_at",
        "continuation_reference",
        "continuation_sha256",
        "source_recovery_sha256",
        "data_authority_sha256",
        "control_sha256",
        "authority",
        "no_ai",
        "completed_operations",
        "keychain_sources",
        "commands",
        "execution_order",
        "retry_limits",
        "allowed_operations",
        "stop_conditions",
    }
    if (
        not isinstance(package, dict)
        or set(package) != expected_fields
        or package.get("schema_version") != SCHEMA
    ):
        raise DeployedReleaseRecoveryInvalid(
            "deployed_recovery_fields_invalid"
        )
    checked_at = (
        _timestamp(now, "deployed_recovery_time_invalid")
        if isinstance(now, str)
        else (
            now.astimezone(UTC)
            if isinstance(now, datetime)
            else datetime.now(UTC)
        )
    )
    issued = _timestamp(package["issued_at"], "deployed_recovery_time_invalid")
    expires = _timestamp(
        package["expires_at"], "deployed_recovery_time_invalid"
    )
    if checked_at < issued or checked_at >= expires:
        raise DeployedReleaseRecoveryInvalid("deployed_recovery_expired")
    reference = _reference(package["continuation_reference"])
    if not continuation_path.as_posix().endswith(reference):
        raise DeployedReleaseRecoveryInvalid(
            "deployed_recovery_reference_invalid"
        )
    try:
        continuation = load_deployed_release_continuation(
            continuation_path,
            expected_sha256=package["continuation_sha256"],
        )
    except DeployedReleaseStateInvalid as error:
        raise DeployedReleaseRecoveryInvalid(
            "deployed_recovery_continuation_invalid"
        ) from error
    expected = build_deployed_release_recovery_package(
        authority=package["authority"],
        continuation=continuation,
        continuation_reference=reference,
        continuation_sha256=package["continuation_sha256"],
        authorization_id=package["authorization_id"],
        issued_at=package["issued_at"],
        expires_at=package["expires_at"],
    )
    if package != expected:
        raise DeployedReleaseRecoveryInvalid("deployed_recovery_drift")
    return package


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--continuation", required=True, type=Path)
    parser.add_argument("--continuation-reference", required=True)
    parser.add_argument("--release-attestation", required=True, type=Path)
    parser.add_argument("--attestation-git-sha", required=True)
    parser.add_argument("--authorization-id")
    parser.add_argument("--expires-hours", type=int, default=24)
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args(arguments)
    try:
        continuation_bytes = options.continuation.read_bytes()
        continuation = load_deployed_release_continuation(
            options.continuation
        )
        if not 1 <= options.expires_hours <= 48:
            raise DeployedReleaseRecoveryInvalid(
                "deployed_recovery_expiry_invalid"
            )
        issued = datetime.now(UTC).replace(microsecond=0)
        expires = issued + timedelta(hours=options.expires_hours)
        authorization_id = options.authorization_id or str(uuid4())
        issued_at = issued.isoformat().replace("+00:00", "Z")
        expires_at = expires.isoformat().replace("+00:00", "Z")
        authority = _build_authority_from_continuation(
            continuation=continuation,
            attestation_path=options.release_attestation,
            attestation_git_sha=options.attestation_git_sha,
            authorization_id=authorization_id,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        package = build_deployed_release_recovery_package(
            authority=authority,
            continuation=continuation,
            continuation_reference=options.continuation_reference,
            continuation_sha256=hashlib.sha256(continuation_bytes).hexdigest(),
            authorization_id=authorization_id,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        digest = write_deployed_release_recovery_package(
            options.output, package
        )
        load_deployed_release_recovery_package(
            options.output,
            continuation_path=options.continuation,
            now=issued,
        )
    except (
        OSError,
        DeployedReleaseRecoveryInvalid,
        DeployedReleaseStateInvalid,
        TwoStagePackageInvalid,
    ) as error:
        options.output.unlink(missing_ok=True)
        print(str(error))
        print("deployed_recovery_package=failed")
        return 1
    print("deployed_recovery_package=ok")
    print(f"output={options.output}")
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
