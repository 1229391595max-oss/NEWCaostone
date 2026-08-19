#!/usr/bin/env python3
"""Verify the exact seeded Azure state before application deployment."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.verify_partial_release_state import (  # noqa: E402
    DIGEST_PATTERN,
    GIT_SHA_PATTERN,
    NAME_PATTERN,
    SHA256_PATTERN,
    UUID_PATTERN,
    _command,
    _one_container,
    _read_json,
    _timestamp,
)


CONTINUATION_SCHEMA = "newcaostone.seeded-release-continuation.v1"
REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9._/-]{1,255}")
COMPLETED_STAGES = (
    "incident_preflight",
    "registry_verify",
    "bind_seed",
    "rebound_preflight",
    "seed",
)


class SeededReleaseStateInvalid(ValueError):
    """The seeded continuation evidence or Azure state is invalid."""


def _mapping(value: object, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise SeededReleaseStateInvalid("seeded_release_continuation_invalid")
    return dict(value)


def _match(value: object, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise SeededReleaseStateInvalid("seeded_release_continuation_invalid")
    return value


def _reference(value: object) -> str:
    reference = _match(value, REFERENCE_PATTERN)
    logical = PurePosixPath(reference)
    if logical.is_absolute() or "." in logical.parts or ".." in logical.parts:
        raise SeededReleaseStateInvalid("seeded_release_continuation_invalid")
    return reference


def validate_seeded_release_continuation(value: object) -> dict[str, Any]:
    continuation = _mapping(
        value,
        {
            "schema_version",
            "recorded_at",
            "source_incident",
            "source_recovery",
            "target",
            "release",
            "prepare_execution",
            "seed_execution",
            "boundaries",
        },
    )
    if continuation["schema_version"] != CONTINUATION_SCHEMA:
        raise SeededReleaseStateInvalid("seeded_release_continuation_invalid")
    try:
        _timestamp(continuation["recorded_at"], "invalid")
    except Exception as error:
        raise SeededReleaseStateInvalid(
            "seeded_release_continuation_invalid"
        ) from error

    incident = _mapping(continuation["source_incident"], {"reference", "sha256"})
    _reference(incident["reference"])
    _match(incident["sha256"], SHA256_PATTERN)

    recovery = _mapping(
        continuation["source_recovery"],
        {
            "authorization_id",
            "package_sha256",
            "completed_stages",
            "failed_stage",
            "failure_code",
            "azure_request_dispatched",
        },
    )
    _match(recovery["authorization_id"], UUID_PATTERN)
    _match(recovery["package_sha256"], SHA256_PATTERN)
    if (
        recovery["completed_stages"] != list(COMPLETED_STAGES)
        or recovery["failed_stage"] != "deploy"
        or recovery["failure_code"] != "deployment_environment_missing"
        or recovery["azure_request_dispatched"] is not False
    ):
        raise SeededReleaseStateInvalid("seeded_release_continuation_invalid")

    target = _mapping(
        continuation["target"],
        {
            "subscription_id",
            "tenant_id",
            "region",
            "resource_group",
            "public_url",
            "name_prefix",
            "application",
            "application_revision",
            "prepare_job",
            "seed_job",
            "registry_name",
            "image_repository",
            "storage_account",
            "postgres_server",
            "postgres_administrator_login",
        },
    )
    _match(target["subscription_id"], UUID_PATTERN)
    _match(target["tenant_id"], UUID_PATTERN)
    for field in (
        "resource_group",
        "name_prefix",
        "application",
        "prepare_job",
        "seed_job",
        "postgres_server",
    ):
        _match(target[field], NAME_PATTERN)
    if (
        not isinstance(target["application_revision"], str)
        or not target["application_revision"].startswith(
            f"{target['application']}--"
        )
        or re.fullmatch(r"[a-z0-9]{5,50}", str(target["registry_name"])) is None
        or re.fullmatch(r"[a-z][a-z0-9]{2,31}", str(target["region"])) is None
        or not isinstance(target["public_url"], str)
        or not target["public_url"].startswith("https://")
        or re.fullmatch(r"[a-z0-9]{3,24}", str(target["storage_account"]))
        is None
        or re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]{2,62}",
            str(target["postgres_administrator_login"]),
        )
        is None
        or re.fullmatch(
            r"[a-z0-9][a-z0-9._/-]{1,127}", str(target["image_repository"])
        )
        is None
    ):
        raise SeededReleaseStateInvalid("seeded_release_continuation_invalid")

    release = _mapping(
        continuation["release"],
        {
            "candidate_git_sha",
            "candidate_image_digest",
            "rollback_git_sha",
            "rollback_image_digest",
            "migration_head",
            "synthetic_manifest_sha256",
            "synthetic_dataset_version_id",
        },
    )
    _match(release["candidate_git_sha"], GIT_SHA_PATTERN)
    _match(release["rollback_git_sha"], GIT_SHA_PATTERN)
    _match(release["candidate_image_digest"], DIGEST_PATTERN)
    _match(release["rollback_image_digest"], DIGEST_PATTERN)
    _match(release["synthetic_manifest_sha256"], SHA256_PATTERN)
    _match(release["synthetic_dataset_version_id"], UUID_PATTERN)
    if (
        release["candidate_git_sha"] == release["rollback_git_sha"]
        or release["candidate_image_digest"] == release["rollback_image_digest"]
        or re.fullmatch(r"[0-9]{4}_[a-z0-9_]+", str(release["migration_head"]))
        is None
    ):
        raise SeededReleaseStateInvalid("seeded_release_continuation_invalid")

    prepare = _mapping(
        continuation["prepare_execution"], {"name", "status", "arguments"}
    )
    seed = _mapping(
        continuation["seed_execution"], {"name", "status", "arguments"}
    )
    expected_seed_arguments = [
        "scripts/seed_demo.py",
        "tests/fixtures/synthetic/v1",
        "--expected-manifest-sha256",
        release["synthetic_manifest_sha256"],
        "--expected-dataset-version-id",
        release["synthetic_dataset_version_id"],
    ]
    if (
        not isinstance(prepare["name"], str)
        or prepare["status"] != "Succeeded"
        or prepare["arguments"] != ["scripts/prepare_cloud.py"]
        or not isinstance(seed["name"], str)
        or seed["status"] != "Succeeded"
        or seed["arguments"] != expected_seed_arguments
    ):
        raise SeededReleaseStateInvalid("seeded_release_continuation_invalid")

    boundaries = _mapping(
        continuation["boundaries"],
        {
            "application_deployed",
            "traffic_switched",
            "ai_enabled",
            "openai_key_accessed",
            "paid_ai_called",
        },
    )
    if any(item is not False for item in boundaries.values()):
        raise SeededReleaseStateInvalid("seeded_release_continuation_invalid")
    return json.loads(json.dumps(continuation, sort_keys=True))


def load_seeded_release_continuation(
    path: Path, *, expected_sha256: str | None = None
) -> dict[str, Any]:
    try:
        source = path.read_bytes()
        payload = json.loads(source)
    except (OSError, json.JSONDecodeError) as error:
        raise SeededReleaseStateInvalid(
            "seeded_release_continuation_invalid"
        ) from error
    if expected_sha256 is not None and (
        SHA256_PATTERN.fullmatch(expected_sha256) is None
        or hashlib.sha256(source).hexdigest() != expected_sha256
    ):
        raise SeededReleaseStateInvalid("seeded_release_continuation_hash_mismatch")
    return validate_seeded_release_continuation(payload)


def verify_seeded_release_state(
    continuation: dict[str, Any],
    *,
    reader: Callable[[tuple[str, ...]], object] = _read_json,
) -> dict[str, str]:
    continuation = validate_seeded_release_continuation(continuation)
    target = continuation["target"]
    release = continuation["release"]
    candidate_image = (
        f"{target['registry_name']}.azurecr.io/{target['image_repository']}@"
        f"{release['candidate_image_digest']}"
    )
    rollback_image = (
        f"{target['registry_name']}.azurecr.io/{target['image_repository']}@"
        f"{release['rollback_image_digest']}"
    )

    app = reader(
        _command(continuation, "containerapp", "show", name=target["application"])
    )
    if not isinstance(app, Mapping):
        raise SeededReleaseStateInvalid("seeded_release_application_invalid")
    try:
        properties = app["properties"]
        traffic = properties["configuration"]["ingress"]["traffic"]
    except (KeyError, TypeError) as error:
        raise SeededReleaseStateInvalid(
            "seeded_release_application_invalid"
        ) from error
    app_container = _one_container(app, "seeded_release_application_invalid")
    if (
        properties.get("provisioningState") != "Succeeded"
        or properties.get("latestRevisionName") != target["application_revision"]
        or properties.get("latestReadyRevisionName") != target["application_revision"]
        or app_container.get("image") != rollback_image
        or traffic != [{"latestRevision": True, "weight": 100}]
    ):
        raise SeededReleaseStateInvalid("seeded_release_application_invalid")

    for role, container_name, execution in (
        ("prepare", "prepare", continuation["prepare_execution"]),
        ("seed", "seed", continuation["seed_execution"]),
    ):
        job_name = target[f"{role}_job"]
        job = reader(
            _command(continuation, "containerapp", "job", "show", name=job_name)
        )
        container = _one_container(job, f"seeded_release_{role}_job_invalid")
        if (
            container.get("name") != container_name
            or container.get("image") != candidate_image
            or container.get("command") != ["python"]
            or container.get("args") != execution["arguments"]
        ):
            raise SeededReleaseStateInvalid(f"seeded_release_{role}_job_invalid")
        executions = reader(
            _command(
                continuation,
                "containerapp",
                "job",
                "execution",
                "list",
                name=job_name,
            )
        )
        if not isinstance(executions, list) or not any(
            isinstance(row, Mapping)
            and row.get("name") == execution["name"]
            and isinstance(row.get("properties"), Mapping)
            and row["properties"].get("status") == "Succeeded"
            for row in executions
        ):
            raise SeededReleaseStateInvalid(
                f"seeded_release_{role}_execution_invalid"
            )
    return {"state": "seeded_awaiting_application_deploy"}


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--continuation", required=True, type=Path)
    parser.add_argument("--continuation-sha256", required=True)
    options = parser.parse_args(arguments)
    try:
        continuation = load_seeded_release_continuation(
            options.continuation,
            expected_sha256=options.continuation_sha256,
        )
        verify_seeded_release_state(continuation)
    except SeededReleaseStateInvalid as error:
        print(str(error))
        return 1
    print("seeded_release_state=verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
