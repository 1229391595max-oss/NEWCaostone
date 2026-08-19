#!/usr/bin/env python3
"""Validate the exact deployed V4 continuation before hosted acceptance."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import hashlib
import hmac
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
    _read_json,
    _timestamp,
)
from scripts.verify_phase1_fence import (  # noqa: E402
    EXPECTED_APP_PROBES,
    PHASE2_SECRET_NAMES,
    PHASE2_SECRET_REFS,
)
from scripts.secret_boundary import SECRET_PATTERN  # noqa: E402


CONTINUATION_SCHEMA = "newcaostone.deployed-release-continuation.v1"
COMPLETED_OPERATIONS = (
    "registry_publish",
    "postgres_migrate",
    "seed_job_bind",
    "prepare",
    "synthetic_seed",
    "application_deploy",
    "session_maintenance",
    "storage_maintenance",
)
EXECUTION_ROLES = (
    "prepare",
    "seed",
    "session_maintenance",
    "storage_maintenance",
)
BOUNDARY_KEYS = {
    "application_deployed",
    "traffic_switched",
    "ai_enabled",
    "hosted_health_verified",
    "browser_verified",
    "capacity_verified",
    "expiry_verified",
    "restart_verified",
    "rollback_verified",
    "openai_key_accessed",
    "paid_ai_called",
}
MAX_CONTINUATION_BYTES = 1024 * 1024
ALLOWED_ADDITIONAL_EXECUTION_STATES = frozenset(
    {
        "Succeeded",
        "Pending",
        "Processing",
        "Queued",
        "Running",
        "Starting",
        "Deactivating",
    }
)
REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9._/-]{1,255}")
EXPECTED_SOURCE_RECOVERY = {
    "authorization_id": "993b492e-aba0-40e8-87e5-65019caaa291",
    "package_sha256": (
        "978110287eb3335bcf5537ee59e9bd887a41eee9753861148680f1a5475beae8"
    ),
    "receipt_reference": ".tmp/RECOVERY_V4_EXECUTION_RECEIPT.json",
    "receipt_schema_version": "newcaostone.seeded-release-execution-receipt.v1",
    "receipt_status": "failed",
    "completed_stages": ["seeded_preflight", "registry_verify"],
    "failed_stage": "deploy",
}
EXPECTED_SEEDED_SOURCE = {
    "reference": (
        "release/incidents/2026-08-16-recovery-v2-seeded-continuation.json"
    ),
    "sha256": (
        "dd5b39ee23d7e053f5454a4c8500cc748c74a3d6cec7717b9ae3a19e96e40cdc"
    ),
}
EXPECTED_EXECUTIONS = {
    "prepare": {
        "job": "newcaostone-demo-prepare",
        "name": "newcaostone-demo-prepare-pc747ae",
        "status": "Succeeded",
    },
    "seed": {
        "job": "newcaostone-demo-seed",
        "name": "newcaostone-demo-seed-vhamoeo",
        "status": "Succeeded",
    },
    "session_maintenance": {
        "job": "newcaostone-demo-sessions",
        "name": "newcaostone-demo-sessions-8yiqp1m",
        "status": "Succeeded",
    },
    "storage_maintenance": {
        "job": "newcaostone-demo-storage",
        "name": "newcaostone-demo-storage-bch1i2u",
        "status": "Succeeded",
    },
}


class DeployedReleaseStateInvalid(ValueError):
    """The deployed continuation or observed state is invalid."""


def _mapping(value: object, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise DeployedReleaseStateInvalid(
            "deployed_release_continuation_invalid"
        )
    return dict(value)


def _match(value: object, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise DeployedReleaseStateInvalid(
            "deployed_release_continuation_invalid"
        )
    return value


def _reference(value: object) -> str:
    reference = _match(value, REFERENCE_PATTERN)
    logical = PurePosixPath(reference)
    if logical.is_absolute() or "." in logical.parts or ".." in logical.parts:
        raise DeployedReleaseStateInvalid(
            "deployed_release_continuation_invalid"
        )
    return reference


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("deployed_release_json_duplicate_key")
        result[key] = value
    return result


def validate_deployed_release_continuation(
    value: object,
) -> dict[str, Any]:
    try:
        serialized = json.dumps(value, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise DeployedReleaseStateInvalid(
            "deployed_release_continuation_invalid"
        ) from error
    if SECRET_PATTERN.search(serialized):
        raise DeployedReleaseStateInvalid("deployed_release_secret_forbidden")

    continuation = _mapping(
        value,
        {
            "schema_version",
            "recorded_at",
            "source_recovery",
            "source_seeded_continuation",
            "target",
            "release",
            "executions",
            "completed_operations",
            "boundaries",
        },
    )
    if continuation["schema_version"] != CONTINUATION_SCHEMA:
        raise DeployedReleaseStateInvalid(
            "deployed_release_continuation_invalid"
        )
    try:
        _timestamp(
            continuation["recorded_at"],
            "deployed_release_continuation_invalid",
        )
    except Exception as error:
        raise DeployedReleaseStateInvalid(
            "deployed_release_continuation_invalid"
        ) from error
    if continuation["recorded_at"] != "2026-08-16T22:18:28Z":
        raise DeployedReleaseStateInvalid(
            "deployed_release_continuation_invalid"
        )

    recovery = _mapping(
        continuation["source_recovery"], set(EXPECTED_SOURCE_RECOVERY)
    )
    _match(recovery["authorization_id"], UUID_PATTERN)
    _match(recovery["package_sha256"], SHA256_PATTERN)
    _reference(recovery["receipt_reference"])
    if recovery != EXPECTED_SOURCE_RECOVERY:
        raise DeployedReleaseStateInvalid(
            "deployed_release_continuation_invalid"
        )

    seeded = _mapping(
        continuation["source_seeded_continuation"],
        set(EXPECTED_SEEDED_SOURCE),
    )
    _reference(seeded["reference"])
    _match(seeded["sha256"], SHA256_PATTERN)
    if seeded != EXPECTED_SEEDED_SOURCE:
        raise DeployedReleaseStateInvalid(
            "deployed_release_continuation_invalid"
        )

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
            "environment",
            "prepare_job",
            "seed_job",
            "session_maintenance_job",
            "storage_maintenance_job",
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
        "environment",
        "prepare_job",
        "seed_job",
        "session_maintenance_job",
        "storage_maintenance_job",
        "postgres_server",
    ):
        _match(target[field], NAME_PATTERN)
    if (
        not isinstance(target["application_revision"], str)
        or not target["application_revision"].startswith(
            f"{target['application']}--"
        )
        or re.fullmatch(r"[a-z0-9]{5,50}", str(target["registry_name"]))
        is None
        or re.fullmatch(r"[a-z][a-z0-9]{2,31}", str(target["region"]))
        is None
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
            r"[a-z0-9][a-z0-9._/-]{1,127}",
            str(target["image_repository"]),
        )
        is None
    ):
        raise DeployedReleaseStateInvalid(
            "deployed_release_continuation_invalid"
        )

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
        or release["candidate_image_digest"]
        == release["rollback_image_digest"]
        or re.fullmatch(
            r"[0-9]{4}_[a-z0-9_]+", str(release["migration_head"])
        )
        is None
    ):
        raise DeployedReleaseStateInvalid(
            "deployed_release_continuation_invalid"
        )

    executions = _mapping(continuation["executions"], set(EXECUTION_ROLES))
    for role in EXECUTION_ROLES:
        execution = _mapping(executions[role], {"job", "name", "status"})
        _match(execution["job"], NAME_PATTERN)
        _match(execution["name"], NAME_PATTERN)
    if executions != EXPECTED_EXECUTIONS:
        raise DeployedReleaseStateInvalid(
            "deployed_release_continuation_invalid"
        )

    if continuation["completed_operations"] != list(COMPLETED_OPERATIONS):
        raise DeployedReleaseStateInvalid(
            "deployed_release_continuation_invalid"
        )

    boundaries = _mapping(continuation["boundaries"], BOUNDARY_KEYS)
    expected_boundaries = {key: False for key in BOUNDARY_KEYS}
    expected_boundaries["application_deployed"] = True
    expected_boundaries["traffic_switched"] = True
    if boundaries != expected_boundaries:
        raise DeployedReleaseStateInvalid(
            "deployed_release_continuation_invalid"
        )
    return json.loads(json.dumps(continuation, sort_keys=True))


def load_deployed_release_continuation(
    path: Path, *, expected_sha256: str | None = None
) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            source = stream.read(MAX_CONTINUATION_BYTES + 1)
    except OSError as error:
        raise DeployedReleaseStateInvalid(
            "deployed_release_continuation_invalid"
        ) from error
    if len(source) > MAX_CONTINUATION_BYTES:
        raise DeployedReleaseStateInvalid(
            "deployed_release_continuation_invalid"
        )
    if expected_sha256 is not None:
        if SHA256_PATTERN.fullmatch(expected_sha256) is None or not hmac.compare_digest(
            hashlib.sha256(source).hexdigest(), expected_sha256
        ):
            raise DeployedReleaseStateInvalid(
                "deployed_release_continuation_hash_mismatch"
            )
    try:
        payload = json.loads(source, object_pairs_hook=_unique_object)
    except ValueError as error:
        code = str(error)
        if code != "deployed_release_json_duplicate_key":
            code = "deployed_release_continuation_invalid"
        raise DeployedReleaseStateInvalid(code) from error
    return validate_deployed_release_continuation(payload)


def _one_container(payload: object, code: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise DeployedReleaseStateInvalid(code)
    try:
        containers = payload["properties"]["template"]["containers"]
    except (KeyError, TypeError) as error:
        raise DeployedReleaseStateInvalid(code) from error
    if (
        not isinstance(containers, list)
        or len(containers) != 1
        or not isinstance(containers[0], Mapping)
    ):
        raise DeployedReleaseStateInvalid(code)
    return dict(containers[0])


def _env_authority(
    container: Mapping[str, Any], code: str
) -> tuple[dict[str, str], dict[str, str]]:
    rows = container.get("env")
    if not isinstance(rows, list):
        raise DeployedReleaseStateInvalid(code)
    values: dict[str, str] = {}
    secret_refs: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping) or set(row) not in (
            {"name", "value"},
            {"name", "secretRef"},
        ):
            raise DeployedReleaseStateInvalid(code)
        name = row.get("name")
        if not isinstance(name, str) or name in values or name in secret_refs:
            raise DeployedReleaseStateInvalid(code)
        if "value" in row:
            value = row["value"]
            if not isinstance(value, str):
                raise DeployedReleaseStateInvalid(code)
            values[name] = value
        else:
            secret_ref = row["secretRef"]
            if not isinstance(secret_ref, str):
                raise DeployedReleaseStateInvalid(code)
            secret_refs[name] = secret_ref
    return values, secret_refs


def _secret_names(configuration: Mapping[str, Any], code: str) -> frozenset[str]:
    rows = configuration.get("secrets")
    if not isinstance(rows, list):
        raise DeployedReleaseStateInvalid(code)
    names: list[str] = []
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or set(row) - {"name", "value"}
            or not isinstance(row.get("name"), str)
            or ("value" in row and row["value"] not in (None, ""))
        ):
            raise DeployedReleaseStateInvalid(code)
        names.append(row["name"])
    if len(names) != len(set(names)):
        raise DeployedReleaseStateInvalid(code)
    return frozenset(names)


def _candidate_image(continuation: dict[str, Any]) -> str:
    target = continuation["target"]
    return (
        f"{target['registry_name']}.azurecr.io/"
        f"{target['image_repository']}@"
        f"{continuation['release']['candidate_image_digest']}"
    )


def _environment_id(continuation: dict[str, Any]) -> str:
    target = continuation["target"]
    return (
        f"/subscriptions/{target['subscription_id']}/resourceGroups/"
        f"{target['resource_group']}/providers/Microsoft.App/"
        f"managedEnvironments/{target['environment']}"
    )


def _expected_job_env(continuation: dict[str, Any]) -> dict[str, str]:
    target = continuation["target"]
    return {
        "BIZPULSE_RUNTIME_ENVIRONMENT": "cloud",
        "BIZPULSE_BLOB_ENDPOINT": (
            f"https://{target['storage_account']}.blob.core.windows.net/"
        ),
        "BIZPULSE_BLOB_CONTAINER": "synthetic-demo",
    }


def _verify_candidate_app(
    payload: object, continuation: dict[str, Any]
) -> None:
    code = "deployed_release_application_invalid"
    if not isinstance(payload, Mapping):
        raise DeployedReleaseStateInvalid(code)
    target = continuation["target"]
    try:
        properties = payload["properties"]
        configuration = properties["configuration"]
        ingress = configuration["ingress"]
        template = properties["template"]
    except (KeyError, TypeError) as error:
        raise DeployedReleaseStateInvalid(code) from error
    if not all(
        isinstance(item, Mapping)
        for item in (properties, configuration, ingress, template)
    ):
        raise DeployedReleaseStateInvalid(code)
    scale = template.get("scale")
    if not isinstance(scale, Mapping):
        raise DeployedReleaseStateInvalid(code)
    container = _one_container(payload, code)
    value_env, secret_env = _env_authority(container, code)
    insights = value_env.pop("APPLICATIONINSIGHTS_CONNECTION_STRING", None)
    expected_values = {
        **_expected_job_env(continuation),
        "BIZPULSE_ALLOWED_ORIGIN": target["public_url"],
        "BIZPULSE_AI_CHAT_ENABLED": "false",
        "BIZPULSE_AI_DAILY_ATTEMPT_LIMIT": "120",
        "BIZPULSE_AI_MONTHLY_TOKEN_LIMIT": "150000",
        "BIZPULSE_AI_MAX_CONCURRENT_TURNS": "15",
        "BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE": "3",
        "BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE": "20",
        "BIZPULSE_DEMO_SESSION_RATE_LIMIT_PER_HOUR": "50",
        "BIZPULSE_OPENAI_MODEL": "gpt-5.4-nano-2026-03-17",
        "BIZPULSE_OPENAI_REASONING_EFFORT": "low",
    }
    expected_fqdn = target["public_url"].removeprefix("https://")
    if (
        payload.get("name") != target["application"]
        or properties.get("provisioningState") != "Succeeded"
        or properties.get("latestRevisionName")
        != target["application_revision"]
        or properties.get("latestReadyRevisionName")
        != target["application_revision"]
        or properties.get("environmentId") != _environment_id(continuation)
        or configuration.get("activeRevisionsMode") != "Single"
        or ingress.get("external") is not True
        or ingress.get("fqdn") != expected_fqdn
        or ingress.get("traffic") != [{"latestRevision": True, "weight": 100}]
        or type(scale.get("minReplicas")) is not int
        or scale.get("minReplicas") != 1
        or type(scale.get("maxReplicas")) is not int
        or scale.get("maxReplicas") != 1
        or container.get("name") != "bizpulse"
        or container.get("image") != _candidate_image(continuation)
        or container.get("command") not in (None, [])
        or container.get("args") not in (None, [])
        or container.get("probes") != EXPECTED_APP_PROBES
        or value_env != expected_values
        or secret_env != PHASE2_SECRET_REFS
        or _secret_names(configuration, code) != PHASE2_SECRET_NAMES
        or not isinstance(insights, str)
        or not insights.startswith("InstrumentationKey=")
        or "IngestionEndpoint=https://" not in insights
        or "\n" in insights
        or len(insights) > 4096
    ):
        raise DeployedReleaseStateInvalid(code)


def _verify_candidate_revision(
    payload: object, continuation: dict[str, Any]
) -> None:
    code = "deployed_release_revision_invalid"
    if not isinstance(payload, list) or not payload:
        raise DeployedReleaseStateInvalid(code)
    expected_name = continuation["target"]["application_revision"]
    candidates = [
        item
        for item in payload
        if isinstance(item, Mapping) and item.get("name") == expected_name
    ]
    if len(candidates) != 1:
        raise DeployedReleaseStateInvalid(code)
    properties = candidates[0].get("properties")
    if (
        not isinstance(properties, Mapping)
        or properties.get("active") is not True
        or type(properties.get("replicas")) is not int
        or properties["replicas"] < 1
    ):
        raise DeployedReleaseStateInvalid(code)


def _job_spec(
    role: str, continuation: dict[str, Any]
) -> tuple[str, list[str], str, int, dict[str, Any] | None]:
    release = continuation["release"]
    if role == "prepare":
        return "prepare", ["scripts/prepare_cloud.py"], "Manual", 900, None
    if role == "seed":
        return (
            "seed",
            [
                "scripts/seed_demo.py",
                "tests/fixtures/synthetic/v1",
                "--expected-manifest-sha256",
                release["synthetic_manifest_sha256"],
                "--expected-dataset-version-id",
                release["synthetic_dataset_version_id"],
            ],
            "Manual",
            1800,
            None,
        )
    if role == "session_maintenance":
        return (
            "maintain-sessions",
            ["scripts/maintain_sessions.py"],
            "Schedule",
            300,
            {
                "cronExpression": "*/15 * * * *",
                "parallelism": 1,
                "replicaCompletionCount": 1,
            },
        )
    return (
        "maintain-storage",
        ["scripts/maintain_storage.py", "--expire-temporary"],
        "Schedule",
        600,
        {
            "cronExpression": "0 * * * *",
            "parallelism": 1,
            "replicaCompletionCount": 1,
        },
    )


def _verify_job_and_bound_execution(
    role: str,
    job_payload: object,
    execution_payload: object,
    continuation: dict[str, Any],
) -> None:
    code = "deployed_release_job_invalid"
    if role not in EXECUTION_ROLES or not isinstance(job_payload, Mapping):
        raise DeployedReleaseStateInvalid(code)
    execution_authority = continuation["executions"][role]
    try:
        properties = job_payload["properties"]
        configuration = properties["configuration"]
    except (KeyError, TypeError) as error:
        raise DeployedReleaseStateInvalid(code) from error
    if not isinstance(properties, Mapping) or not isinstance(
        configuration, Mapping
    ):
        raise DeployedReleaseStateInvalid(code)
    container = _one_container(job_payload, code)
    values, secret_refs = _env_authority(container, code)
    container_name, arguments, trigger, timeout, schedule = _job_spec(
        role, continuation
    )
    manual = {
        "parallelism": 1,
        "replicaCompletionCount": 1,
    }
    if (
        job_payload.get("name") != execution_authority["job"]
        or properties.get("environmentId") != _environment_id(continuation)
        or configuration.get("triggerType") != trigger
        or configuration.get("replicaTimeout") != timeout
        or configuration.get("replicaRetryLimit") != 0
        or (
            trigger == "Manual"
            and (
                configuration.get("manualTriggerConfig") != manual
                or configuration.get("scheduleTriggerConfig") is not None
            )
        )
        or (
            trigger == "Schedule"
            and (
                configuration.get("scheduleTriggerConfig") != schedule
                or configuration.get("manualTriggerConfig") is not None
            )
        )
        or _secret_names(configuration, code) != PHASE2_SECRET_NAMES
        or container.get("name") != container_name
        or container.get("image") != _candidate_image(continuation)
        or container.get("command") != ["python"]
        or container.get("args") != arguments
        or values != _expected_job_env(continuation)
        or secret_refs
        != {
            name: reference
            for name, reference in PHASE2_SECRET_REFS.items()
            if name != "BIZPULSE_OPERATOR_PASSWORD_HASH"
        }
    ):
        raise DeployedReleaseStateInvalid(code)

    if not isinstance(execution_payload, list) or any(
        not isinstance(item, Mapping) for item in execution_payload
    ):
        raise DeployedReleaseStateInvalid(
            "deployed_release_bound_execution_invalid"
        )
    bound = [
        item
        for item in execution_payload
        if item.get("name") == execution_authority["name"]
    ]
    if (
        len(bound) != 1
        or not isinstance(bound[0].get("properties"), Mapping)
        or bound[0]["properties"].get("status") != "Succeeded"
    ):
        raise DeployedReleaseStateInvalid(
            "deployed_release_bound_execution_invalid"
        )
    additional = [item for item in execution_payload if item not in bound]
    if role not in {"session_maintenance", "storage_maintenance"} and additional:
        raise DeployedReleaseStateInvalid(
            "deployed_release_additional_execution_invalid"
        )
    seen_names = {execution_authority["name"]}
    for execution in additional:
        name = execution.get("name")
        properties = execution.get("properties")
        if (
            not isinstance(name, str)
            or name in seen_names
            or not isinstance(properties, Mapping)
            or properties.get("status")
            not in ALLOWED_ADDITIONAL_EXECUTION_STATES
        ):
            raise DeployedReleaseStateInvalid(
                "deployed_release_additional_execution_invalid"
            )
        seen_names.add(name)


def verify_deployed_release_state(
    continuation: dict[str, Any],
    *,
    reader: Callable[[tuple[str, ...]], object] = _read_json,
) -> dict[str, str]:
    continuation = validate_deployed_release_continuation(continuation)
    target = continuation["target"]
    try:
        app = reader(
            _command(
                continuation,
                "containerapp",
                "show",
                name=target["application"],
            )
        )
        _verify_candidate_app(app, continuation)
        revisions = reader(
            _command(
                continuation,
                "containerapp",
                "revision",
                "list",
                name=target["application"],
            )
        )
        _verify_candidate_revision(revisions, continuation)
        for role in EXECUTION_ROLES:
            job_name = continuation["executions"][role]["job"]
            job = reader(
                _command(
                    continuation,
                    "containerapp",
                    "job",
                    "show",
                    name=job_name,
                )
            )
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
            _verify_job_and_bound_execution(
                role, job, executions, continuation
            )
    except DeployedReleaseStateInvalid:
        raise
    except Exception as error:
        raise DeployedReleaseStateInvalid(
            "deployed_release_azure_read_failed"
        ) from error
    return {"state": "deployed_awaiting_hosted_acceptance"}


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--continuation", type=Path, required=True)
    parser.add_argument("--continuation-sha256", required=True)
    options = parser.parse_args(arguments)
    try:
        continuation = load_deployed_release_continuation(
            options.continuation,
            expected_sha256=options.continuation_sha256,
        )
        verify_deployed_release_state(continuation)
    except DeployedReleaseStateInvalid as error:
        print(str(error), file=sys.stderr)
        return 1
    print("deployed_release_state=verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
