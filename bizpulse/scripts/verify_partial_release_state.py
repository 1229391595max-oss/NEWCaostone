#!/usr/bin/env python3
"""Verify the exact read-only Azure state around a partial release failure."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any


INCIDENT_SCHEMA = "newcaostone.partial-release-incident.v2"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]{1,62}[a-z0-9]")


class PartialReleaseStateInvalid(ValueError):
    """The incident or observed Azure state does not match exactly."""


def _mapping(value: object, keys: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise PartialReleaseStateInvalid(code)
    return dict(value)


def _string(value: object, pattern: re.Pattern[str], code: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PartialReleaseStateInvalid(code)
    return value


def _timestamp(value: object, code: str) -> str:
    if not isinstance(value, str):
        raise PartialReleaseStateInvalid(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PartialReleaseStateInvalid(code) from error
    if parsed.tzinfo is None:
        raise PartialReleaseStateInvalid(code)
    return value


def validate_partial_release_incident(value: object) -> dict[str, Any]:
    incident = _mapping(
        value,
        {
            "schema_version",
            "observed_at",
            "source_package",
            "target",
            "release",
            "prepare",
            "seed",
            "boundaries",
            "recovery_attempts",
        },
        "partial_release_incident_invalid",
    )
    if incident["schema_version"] != INCIDENT_SCHEMA:
        raise PartialReleaseStateInvalid("partial_release_incident_invalid")
    _timestamp(incident["observed_at"], "partial_release_incident_invalid")

    source = _mapping(
        incident["source_package"],
        {"authorization_id", "sha256"},
        "partial_release_incident_invalid",
    )
    _string(source["authorization_id"], UUID_PATTERN, "partial_release_incident_invalid")
    _string(source["sha256"], SHA256_PATTERN, "partial_release_incident_invalid")

    target = _mapping(
        incident["target"],
        {
            "subscription_id",
            "tenant_id",
            "region",
            "resource_group",
            "public_url",
            "name_prefix",
            "registry_name",
            "image_repository",
            "storage_account",
            "postgres_server",
            "postgres_administrator_login",
            "application",
            "application_revision",
            "prepare_job",
            "seed_job",
        },
        "partial_release_incident_invalid",
    )
    for field in ("subscription_id", "tenant_id"):
        _string(target[field], UUID_PATTERN, "partial_release_incident_invalid")
    for field in (
        "resource_group",
        "application",
        "prepare_job",
        "seed_job",
        "postgres_server",
    ):
        _string(target[field], NAME_PATTERN, "partial_release_incident_invalid")
    if (
        not isinstance(target["public_url"], str)
        or not target["public_url"].startswith("https://")
        or not re.fullmatch(r"[a-z][a-z0-9]{2,31}", str(target["region"]))
        or not re.fullmatch(r"[a-z0-9]{5,50}", str(target["registry_name"]))
        or not re.fullmatch(r"[a-z0-9]{3,24}", str(target["storage_account"]))
        or not re.fullmatch(
            r"[a-z0-9][a-z0-9._/-]{1,127}", str(target["image_repository"])
        )
        or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]{2,62}",
            str(target["postgres_administrator_login"]),
        )
        or not isinstance(target["application_revision"], str)
        or not target["application_revision"].startswith(
            f"{target['application']}--"
        )
    ):
        raise PartialReleaseStateInvalid("partial_release_incident_invalid")

    release = _mapping(
        incident["release"],
        {
            "candidate_git_sha",
            "attestation_git_sha",
            "attestation_path",
            "candidate_image_digest",
            "candidate_image_input_sha256",
            "migration_head",
            "synthetic_manifest_sha256",
            "synthetic_dataset_version_id",
            "rollback_git_sha",
            "rollback_image_digest",
            "rollback_image_input_sha256",
        },
        "partial_release_incident_invalid",
    )
    for field in ("candidate_git_sha", "attestation_git_sha", "rollback_git_sha"):
        _string(release[field], GIT_SHA_PATTERN, "partial_release_incident_invalid")
    for field in ("candidate_image_digest", "rollback_image_digest"):
        _string(release[field], DIGEST_PATTERN, "partial_release_incident_invalid")
    for field in (
        "candidate_image_input_sha256",
        "synthetic_manifest_sha256",
        "rollback_image_input_sha256",
    ):
        _string(release[field], SHA256_PATTERN, "partial_release_incident_invalid")
    _string(
        release["synthetic_dataset_version_id"],
        UUID_PATTERN,
        "partial_release_incident_invalid",
    )
    if (
        release["candidate_git_sha"] == release["rollback_git_sha"]
        or release["candidate_image_digest"] == release["rollback_image_digest"]
        or release["attestation_path"]
        != f"release/attestations/{release['candidate_git_sha']}.json"
        or re.fullmatch(
            r"[0-9]{4}_[a-z0-9_]+", str(release["migration_head"])
        )
        is None
    ):
        raise PartialReleaseStateInvalid("partial_release_incident_invalid")

    prepare = _mapping(
        incident["prepare"],
        {"execution", "started_at", "ended_at", "status", "arguments"},
        "partial_release_incident_invalid",
    )
    if (
        prepare["status"] != "Succeeded"
        or prepare["arguments"] != ["scripts/prepare_cloud.py"]
        or not isinstance(prepare["execution"], str)
    ):
        raise PartialReleaseStateInvalid("partial_release_incident_invalid")
    _timestamp(prepare["started_at"], "partial_release_incident_invalid")
    _timestamp(prepare["ended_at"], "partial_release_incident_invalid")

    seed = _mapping(
        incident["seed"],
        {
            "execution",
            "started_at",
            "status",
            "error",
            "previous_manifest_sha256",
            "previous_dataset_version_id",
        },
        "partial_release_incident_invalid",
    )
    if (
        seed["status"] != "Failed"
        or seed["error"] != "seed_authority_mismatch"
        or not isinstance(seed["execution"], str)
    ):
        raise PartialReleaseStateInvalid("partial_release_incident_invalid")
    _timestamp(seed["started_at"], "partial_release_incident_invalid")
    _string(
        seed["previous_manifest_sha256"],
        SHA256_PATTERN,
        "partial_release_incident_invalid",
    )
    _string(
        seed["previous_dataset_version_id"],
        UUID_PATTERN,
        "partial_release_incident_invalid",
    )

    boundaries = _mapping(
        incident["boundaries"],
        {
            "application_deployed",
            "traffic_switched",
            "ai_enabled",
            "openai_key_accessed",
            "paid_ai_called",
            "candidate_seed_writes",
        },
        "partial_release_incident_invalid",
    )
    if any(value is not False for value in boundaries.values()):
        raise PartialReleaseStateInvalid("partial_release_incident_invalid")

    attempts = incident["recovery_attempts"]
    if not isinstance(attempts, list) or len(attempts) > 10:
        raise PartialReleaseStateInvalid("partial_release_incident_invalid")
    seen_authorizations: set[str] = set()
    for attempt_value in attempts:
        attempt = _mapping(
            attempt_value,
            {
                "authorization_id",
                "package_sha256",
                "recorded_at",
                "completed_stages",
                "failed_stage",
                "failure_code",
                "cli_exit_code",
                "azure_request_dispatched",
                "azure_state_changed",
            },
            "partial_release_incident_invalid",
        )
        authorization_id = _string(
            attempt["authorization_id"],
            UUID_PATTERN,
            "partial_release_incident_invalid",
        )
        _string(
            attempt["package_sha256"],
            SHA256_PATTERN,
            "partial_release_incident_invalid",
        )
        _timestamp(attempt["recorded_at"], "partial_release_incident_invalid")
        if (
            authorization_id in seen_authorizations
            or attempt["package_sha256"] == source["sha256"]
            or attempt["completed_stages"]
            != ["incident_preflight", "registry_verify"]
            or attempt["failed_stage"] != "bind_seed"
            or attempt["failure_code"] != "azure_cli_arguments_invalid"
            or attempt["cli_exit_code"] != 2
            or attempt["azure_request_dispatched"] is not False
            or attempt["azure_state_changed"] is not False
        ):
            raise PartialReleaseStateInvalid("partial_release_incident_invalid")
        seen_authorizations.add(authorization_id)
    return json.loads(json.dumps(incident, sort_keys=True))


def load_partial_release_incident(
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    try:
        source = path.read_bytes()
        payload = json.loads(source)
    except (OSError, json.JSONDecodeError) as error:
        raise PartialReleaseStateInvalid("partial_release_incident_invalid") from error
    if expected_sha256 is not None and (
        SHA256_PATTERN.fullmatch(expected_sha256) is None
        or hashlib.sha256(source).hexdigest() != expected_sha256
    ):
        raise PartialReleaseStateInvalid("partial_release_incident_hash_mismatch")
    return validate_partial_release_incident(payload)


def _read_json(command: tuple[str, ...]) -> object:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise PartialReleaseStateInvalid("partial_release_azure_read_failed")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise PartialReleaseStateInvalid("partial_release_azure_read_failed") from error


def _command(
    incident: dict[str, Any],
    *parts: str,
    name: str,
) -> tuple[str, ...]:
    target = incident["target"]
    return (
        "az",
        *parts,
        "--subscription",
        target["subscription_id"],
        "--resource-group",
        target["resource_group"],
        "--name",
        name,
        "--only-show-errors",
        "--output",
        "json",
    )


def _one_container(payload: object, code: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise PartialReleaseStateInvalid(code)
    try:
        containers = payload["properties"]["template"]["containers"]
    except (KeyError, TypeError) as error:
        raise PartialReleaseStateInvalid(code) from error
    if not isinstance(containers, list) or len(containers) != 1:
        raise PartialReleaseStateInvalid(code)
    return _mapping(
        containers[0],
        set(containers[0]) if isinstance(containers[0], Mapping) else set(),
        code,
    )


def verify_partial_release_state(
    incident: dict[str, Any],
    *,
    mode: str,
    reader: Callable[[tuple[str, ...]], object] = _read_json,
) -> dict[str, str]:
    incident = validate_partial_release_incident(incident)
    if mode not in {"failed", "rebound"}:
        raise PartialReleaseStateInvalid("partial_release_mode_invalid")
    target = incident["target"]
    release = incident["release"]
    candidate_image = (
        f"{target['registry_name']}.azurecr.io/{target['image_repository']}@"
        f"{release['candidate_image_digest']}"
    )
    rollback_image = (
        f"{target['registry_name']}.azurecr.io/{target['image_repository']}@"
        f"{release['rollback_image_digest']}"
    )

    app = reader(
        _command(
            incident,
            "containerapp",
            "show",
            name=target["application"],
        )
    )
    if not isinstance(app, Mapping):
        raise PartialReleaseStateInvalid("partial_release_application_invalid")
    try:
        properties = app["properties"]
        traffic = properties["configuration"]["ingress"]["traffic"]
    except (KeyError, TypeError) as error:
        raise PartialReleaseStateInvalid("partial_release_application_invalid") from error
    app_container = _one_container(app, "partial_release_application_invalid")
    if (
        properties.get("provisioningState") != "Succeeded"
        or properties.get("latestRevisionName") != target["application_revision"]
        or properties.get("latestReadyRevisionName") != target["application_revision"]
        or app_container.get("image") != rollback_image
        or traffic != [{"latestRevision": True, "weight": 100}]
    ):
        raise PartialReleaseStateInvalid("partial_release_application_invalid")

    prepare_job = reader(
        _command(
            incident,
            "containerapp",
            "job",
            "show",
            name=target["prepare_job"],
        )
    )
    prepare_container = _one_container(
        prepare_job, "partial_release_prepare_job_invalid"
    )
    if (
        prepare_container.get("name") != "prepare"
        or prepare_container.get("image") != candidate_image
        or prepare_container.get("command") != ["python"]
        or prepare_container.get("args") != incident["prepare"]["arguments"]
    ):
        raise PartialReleaseStateInvalid("partial_release_prepare_job_invalid")

    seed_job = reader(
        _command(
            incident,
            "containerapp",
            "job",
            "show",
            name=target["seed_job"],
        )
    )
    seed_container = _one_container(seed_job, "partial_release_seed_job_invalid")
    seed_authority = incident["seed"] if mode == "failed" else release
    manifest = (
        seed_authority["previous_manifest_sha256"]
        if mode == "failed"
        else seed_authority["synthetic_manifest_sha256"]
    )
    version = (
        seed_authority["previous_dataset_version_id"]
        if mode == "failed"
        else seed_authority["synthetic_dataset_version_id"]
    )
    expected_seed_args = [
        "scripts/seed_demo.py",
        "tests/fixtures/synthetic/v1",
        "--expected-manifest-sha256",
        manifest,
        "--expected-dataset-version-id",
        version,
    ]
    if (
        seed_container.get("name") != "seed"
        or seed_container.get("image") != candidate_image
        or seed_container.get("command") != ["python"]
        or seed_container.get("args") != expected_seed_args
    ):
        raise PartialReleaseStateInvalid("partial_release_seed_job_invalid")

    for role, expected in (
        ("prepare", incident["prepare"]),
        ("seed", incident["seed"]),
    ):
        job_name = target[f"{role}_job"]
        executions = reader(
            _command(
                incident,
                "containerapp",
                "job",
                "execution",
                "list",
                name=job_name,
            )
        )
        if not isinstance(executions, list) or not any(
            isinstance(row, Mapping)
            and row.get("name") == expected["execution"]
            and isinstance(row.get("properties"), Mapping)
            and row["properties"].get("status") == expected["status"]
            for row in executions
        ):
            raise PartialReleaseStateInvalid(
                f"partial_release_{role}_execution_invalid"
            )
    return {"mode": mode, "state": "verified"}


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incident", required=True, type=Path)
    parser.add_argument("--incident-sha256", required=True)
    parser.add_argument("--mode", required=True, choices=("failed", "rebound"))
    options = parser.parse_args(arguments)
    try:
        incident = load_partial_release_incident(
            options.incident,
            expected_sha256=options.incident_sha256,
        )
        verify_partial_release_state(incident, mode=options.mode)
    except PartialReleaseStateInvalid as error:
        print(str(error))
        return 1
    print(f"partial_release_state={options.mode}_verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
