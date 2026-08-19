#!/usr/bin/env python3
"""Create a fresh, owner-only admin-AI hosted release authorization package."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from typing import Any
from urllib.parse import urlsplit

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

from scripts.admin_ai_oci_artifact import (  # noqa: E402
    AdminAIOCIArtifactInvalid,
    inspect_oci_archive,
)
from scripts.admin_ai_current_successor import (  # noqa: E402
    CURRENT_ADMIN_AI_SUCCESSOR_TARGET,
    R19_REGISTRY_TAG,
)
from scripts.create_ai_enablement_package import (  # noqa: E402
    ARTIFACTS as HISTORICAL_TASK10_ARTIFACTS,
    AUTHORIZED_BRANCH,
    AIEnablementPackageInvalid,
    D3_BRANCH,
    D3_PACKAGE_SHA256,
    D3_SELECTED_BASE_SHA,
    build_ai_enablement_package,
    validate_ai_enablement_package,
    write_ai_enablement_package,
)


PACKAGE_SCHEMA = "newcaostone.admin-ai-release.v1"
PACKAGE_LIFETIME = timedelta(hours=24)
MAX_BASELINE_AGE = timedelta(minutes=15)
REQUIRED_AZURE_READS = 12
ALLOWED_RBAC_PHASES = frozenset({"legacy_only", "officer_only"})
PRE_MIGRATION_DATABASE_REVISIONS = frozenset(
    {
        "0014_import_base_lineage",
        "0015_admin_ai_control",
        "0016_admin_ai_control_integrity",
    }
)
MIGRATION_JOB_NAME = "newcaostone-demo-prepare"
MIGRATION_JOB_SCHEMA = "newcaostone.admin-ai-migration-job.v1"
MIGRATION_JOB_QUERY = (
    "{id:id,name:name,identityIds:keys(identity.userAssignedIdentities),"
    "triggerType:properties.configuration.triggerType,"
    "replicaTimeout:properties.configuration.replicaTimeout,"
    "replicaRetryLimit:properties.configuration.replicaRetryLimit,"
    "manualTriggerConfig:properties.configuration.manualTriggerConfig,"
    "registries:properties.configuration.registries[].{server:server,identity:identity},"
    "secretNames:properties.configuration.secrets[].name,"
    "containers:properties.template.containers[].{name:name,image:image,command:command,"
    "args:args,resources:resources,env:env[].{name:name,secretRef:secretRef},"
    "safeEnv:env[?name=='BIZPULSE_RUNTIME_ENVIRONMENT' || "
    "name=='BIZPULSE_BLOB_ENDPOINT' || name=='BIZPULSE_BLOB_CONTAINER' || "
    "name=='BIZPULSE_ALLOWED_ORIGIN'].{name:name,value:value}}}"
)
_PROCESS_ENVIRONMENT_NAMES = (
    "AZURE_CONFIG_DIR",
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_FILE",
    "TMPDIR",
)

_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_REVISION = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?")
BUILD_CONTEXT_PATHS = (
    ".dockerignore",
    "Dockerfile",
    "requirements.txt",
    "alembic.ini",
    "alembic",
    "api",
    "frontend",
    "src",
    "scripts/seed_demo.py",
    "scripts/prepare_cloud.py",
    "scripts/maintain_sessions.py",
    "scripts/maintain_storage.py",
    "scripts/phase1_fence_server.py",
    "scripts/rotate_operator_password.py",
    "tests/fixtures/synthetic/v1",
)
BUILD_CONTEXT_SCHEMA = "newcaostone.docker-build-context.v1"
RUNTIME_TOOL_SCHEMA = "newcaostone.admin-ai-runtime-toolchain.v1"
RUNTIME_TOOL_PATHS = (
    "infra/ai_enablement.bicep",
    "infra/ai_secret_write.bicep",
    "infra/modules/app.bicep",
    "scripts/admin_ai_runtime_dependencies.json",
    "scripts/admin_ai_current_successor.py",
    "requirements.txt",
    "requirements-dev.txt",
    "scripts/admin_ai_exact_runtime.py",
    "scripts/admin_ai_oci_artifact.py",
    "scripts/admin_ai_release_operations.py",
    "scripts/ai_enablement_contract.py",
    "scripts/azure_ai_enablement_actions.py",
    "scripts/azure_ai_reconciliation.py",
    "scripts/azure_ai_revision.py",
    "scripts/azure_arm_lro.py",
    "scripts/build_admin_ai_candidate.py",
    "scripts/create_ai_enablement_package.py",
    "scripts/create_admin_ai_release_package.py",
    "scripts/create_release_manifest.py",
    "scripts/publish_registry_image.py",
    "scripts/refresh_admin_ai_current_authority.py",
    "scripts/refresh_current_authority.py",
    "scripts/release_authority.py",
    "scripts/run_admin_ai_release.py",
    "scripts/run_azure_job.py",
    "scripts/verify_admin_ai_control.py",
    "scripts/verify_release.py",
    "src/ai/release_constants.py",
)


class AdminAIReleasePackageInvalid(ValueError):
    """A fresh admin-AI release package failed closed validation."""


def _invalid(code: str) -> AdminAIReleasePackageInvalid:
    return AdminAIReleasePackageInvalid(code)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise _invalid("timestamp_invalid")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_utc(value: object, *, code: str = "timestamp_invalid") -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise _invalid(code)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise _invalid(code) from error
    if parsed.tzinfo is None:
        raise _invalid(code)
    return parsed.astimezone(UTC)


def build_fresh_task10_authority_request(
    *,
    repository: Mapping[str, object],
    candidate_artifact: Mapping[str, object],
    generated_at: datetime,
    role_assignment_state: str,
    artifact_id: str,
    project_root: Path,
    control_sha256: Mapping[str, object],
    prior_attempts: Mapping[str, object],
) -> dict[str, object]:
    """Build one fresh strict Task 10 successor request for Task 12."""

    try:
        source_sha = repository["source_sha"]
        source_tree = repository["source_tree"]
        clean = repository["tracked_tree_clean"]
        image_input = candidate_artifact["image_input_sha256"]
        dockerfile_sha = hashlib.sha256(
            (project_root / "Dockerfile").read_bytes()
        ).hexdigest()
        runtime_lock_sha = hashlib.sha256(
            (project_root / "requirements.txt").read_bytes()
        ).hexdigest()
    except (KeyError, OSError, TypeError) as error:
        raise _invalid("operations_authority_invalid") from error
    artifacts = {
        "package_path": (
            f".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_TASK12_{artifact_id}.json"
        ),
        "receipt_path": f".tmp/AI_ENABLEMENT_RECEIPT_TASK12_{artifact_id}.json",
        "observation_path": (
            f".tmp/AI_ENABLEMENT_OBSERVATION_TASK12_{artifact_id}.json"
        ),
    }
    try:
        request = build_ai_enablement_package(
            generated_at=generated_at,
            role_assignment_state=role_assignment_state,
            repository={
                "branch": AUTHORIZED_BRANCH,
                "head_sha": source_sha,
                "tree_sha": source_tree,
                "clean": clean,
            },
            azure_target=CURRENT_ADMIN_AI_SUCCESSOR_TARGET,
            candidate={
                "image_repository": "bizpulse",
                "source_tree_sha": source_tree,
                "dockerfile_sha256": dockerfile_sha,
                "runtime_lock_sha256": runtime_lock_sha,
                "image_input_sha256": image_input,
                "candidate_image_digest": None,
            },
            control_sha256=control_sha256,
            d3={
                "branch": D3_BRANCH,
                "selected_base_sha": D3_SELECTED_BASE_SHA,
                "package_sha256": D3_PACKAGE_SHA256,
                "package_mode": "0600",
                "receipt_present": False,
                "observation_present": False,
            },
            artifacts=artifacts,
            prior_attempts=prior_attempts,
            rollback_registry_tag=R19_REGISTRY_TAG,
        )
        return validate_ai_enablement_package(request, now=generated_at)
    except AIEnablementPackageInvalid as error:
        raise _invalid("operations_authority_invalid") from error


def write_fresh_task10_authority_request(
    output: Path,
    *,
    repository: Mapping[str, object],
    candidate_artifact: Mapping[str, object],
    generated_at: datetime,
    role_assignment_state: str,
    artifact_id: str,
    project_root: Path,
    output_root: Path,
    control_sha256: Mapping[str, object],
    prior_attempts: Mapping[str, object],
) -> dict[str, object]:
    """Exclusively persist one fresh owner-only strict Task 10 request."""

    request = build_fresh_task10_authority_request(
        repository=repository,
        candidate_artifact=candidate_artifact,
        generated_at=generated_at,
        role_assignment_state=role_assignment_state,
        artifact_id=artifact_id,
        project_root=project_root,
        control_sha256=control_sha256,
        prior_attempts=prior_attempts,
    )
    expected = output_root / str(request["artifacts"]["package_path"])
    try:
        if output.resolve() != expected.resolve():
            raise _invalid("operations_authority_invalid")
        write_ai_enablement_package(output, request)
    except AIEnablementPackageInvalid as error:
        raise _invalid("operations_authority_invalid") from error
    return request


def _exact_mapping(value: object, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _invalid("package_shape_invalid")
    return value


def _validate_baseline(
    baseline: object,
    *,
    issued_at: datetime,
) -> dict[str, object]:
    raw = _exact_mapping(
        baseline,
        {
            "observed_at",
            "observation_sha256",
            "required_azure_reads",
            "health_state",
            "ready",
            "revision",
            "image_digest",
            "traffic_weight",
            "operator_ai_enabled",
            "demo_ai_enabled",
            "role_assignment_phase",
            "database_revision",
        },
    )
    observed_at = _parse_utc(raw["observed_at"], code="azure_baseline_stale")
    age = issued_at.astimezone(UTC) - observed_at
    if age < timedelta(0) or age > MAX_BASELINE_AGE:
        raise _invalid("azure_baseline_stale")
    if (
        not isinstance(raw["observation_sha256"], str)
        or _SHA256.fullmatch(raw["observation_sha256"]) is None
    ):
        raise _invalid("azure_baseline_digest_invalid")
    if raw["required_azure_reads"] != REQUIRED_AZURE_READS:
        raise _invalid("azure_read_contract_invalid")
    if raw["health_state"] != "Healthy" or raw["ready"] is not True:
        raise _invalid("azure_baseline_not_healthy")
    if (
        not isinstance(raw["revision"], str)
        or _REVISION.fullmatch(raw["revision"]) is None
        or not isinstance(raw["image_digest"], str)
        or _IMAGE_DIGEST.fullmatch(raw["image_digest"]) is None
        or raw["traffic_weight"] != 100
    ):
        raise _invalid("azure_baseline_not_current")
    if (
        raw["operator_ai_enabled"] is not False
        or raw["demo_ai_enabled"] is not False
    ):
        raise _invalid("azure_baseline_ai_not_disabled")
    if raw["role_assignment_phase"] not in ALLOWED_RBAC_PHASES:
        raise _invalid("rbac_phase_invalid")
    if raw["database_revision"] not in PRE_MIGRATION_DATABASE_REVISIONS:
        raise _invalid("azure_baseline_database_revision_invalid")
    return dict(raw)


def _validate_authority(
    authority: object,
    *,
    issued_at: datetime,
) -> dict[str, object]:
    raw = _exact_mapping(
        authority,
        {"path", "sha256", "evidence_sha256", "observed_at", "expires_at"},
    )
    if raw["path"] != "release/current_authority.json":
        raise _invalid("authority_path_invalid")
    if not isinstance(raw["sha256"], str) or _SHA256.fullmatch(raw["sha256"]) is None:
        raise _invalid("authority_digest_invalid")
    if (
        not isinstance(raw["evidence_sha256"], str)
        or _SHA256.fullmatch(raw["evidence_sha256"]) is None
    ):
        raise _invalid("authority_evidence_drift")
    observed = _parse_utc(raw["observed_at"], code="authority_stale")
    expires = _parse_utc(raw["expires_at"], code="authority_stale")
    if (
        observed > issued_at.astimezone(UTC)
        or expires <= issued_at.astimezone(UTC)
    ):
        raise _invalid("authority_stale")
    return dict(raw)


def _validate_operations_factory(value: object) -> dict[str, str]:
    raw = _exact_mapping(value, {"factory", "source_path", "source_sha256"})
    factory = raw["factory"]
    source_path = raw["source_path"]
    source_sha256 = raw["source_sha256"]
    if (
        not isinstance(factory, str)
        or re.fullmatch(
            r"scripts\.[a-z0-9_]+:[a-zA-Z_][a-zA-Z0-9_]*",
            factory,
        )
        is None
        or not isinstance(source_path, str)
        or not isinstance(source_sha256, str)
        or _SHA256.fullmatch(source_sha256) is None
    ):
        raise _invalid("operations_factory_invalid")
    module_name = factory.split(":", 1)[0]
    expected_path = module_name.replace(".", "/") + ".py"
    if source_path != expected_path:
        raise _invalid("operations_factory_invalid")
    return {
        "factory": factory,
        "source_path": source_path,
        "source_sha256": source_sha256,
    }


def validate_migration_job_safe_projection(
    payload: object,
    *,
    task10_request: Mapping[str, object],
    expected_image: str,
) -> dict[str, object]:
    """Validate the complete non-secret migration Job mutation authority."""

    try:
        target = task10_request["azure_target"]
        if not isinstance(target, Mapping) or not isinstance(payload, Mapping):
            raise TypeError
        subscription = target["subscription_id"]
        resource_group = target["resource_group"]
        registry_name = target["registry_name"]
        registry_identity_name = target["existing_registry_identity_name"]
        app_name = target["app_name"]
        registry_identity = (
            f"/subscriptions/{subscription}/resourceGroups/{resource_group}/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/"
            f"{registry_identity_name}"
        )
        job_id = (
            f"/subscriptions/{subscription}/resourceGroups/{resource_group}/providers/"
            f"Microsoft.App/jobs/{MIGRATION_JOB_NAME}"
        )
        containers = payload["containers"]
        container = containers[0]
        environment = container["env"]
        safe_environment = container["safeEnv"]
    except (KeyError, IndexError, TypeError) as error:
        raise _invalid("operations_authority_invalid") from error
    if not isinstance(environment, list):
        raise _invalid("operations_authority_invalid")
    bindings: dict[str, object] = {}
    for entry in environment:
        if (
            not isinstance(entry, Mapping)
            or set(entry) != {"name", "secretRef"}
            or not isinstance(entry["name"], str)
            or entry["name"] in bindings
        ):
            raise _invalid("operations_authority_invalid")
        bindings[entry["name"]] = entry["secretRef"]
    if not isinstance(safe_environment, list):
        raise _invalid("operations_authority_invalid")
    safe_values: dict[str, object] = {}
    for entry in safe_environment:
        if (
            not isinstance(entry, Mapping)
            or set(entry) != {"name", "value"}
            or not isinstance(entry["name"], str)
            or entry["name"] in safe_values
        ):
            raise _invalid("operations_authority_invalid")
        safe_values[entry["name"]] = entry["value"]
    blob_endpoint = safe_values.get("BIZPULSE_BLOB_ENDPOINT")
    allowed_origin = safe_values.get("BIZPULSE_ALLOWED_ORIGIN")
    expected_bindings: dict[str, object] = {
        "BIZPULSE_RUNTIME_ENVIRONMENT": None,
        "BIZPULSE_DATABASE_URL": "database-url",
        "BIZPULSE_BLOB_ENDPOINT": None,
        "BIZPULSE_BLOB_CONTAINER": None,
        "BIZPULSE_BLOB_CONNECTION_STRING": "blob-connection-string",
        "BIZPULSE_ALLOWED_ORIGIN": None,
        "BIZPULSE_OPERATOR_PASSWORD_HASH": "operator-password-hash",
        "BIZPULSE_SESSION_PEPPER": "session-pepper",
    }
    expected_safe_values = {
        "BIZPULSE_RUNTIME_ENVIRONMENT": "cloud",
        "BIZPULSE_BLOB_ENDPOINT": blob_endpoint,
        "BIZPULSE_BLOB_CONTAINER": "synthetic-demo",
        "BIZPULSE_ALLOWED_ORIGIN": allowed_origin,
    }
    expected_keys = {
        "id",
        "name",
        "identityIds",
        "triggerType",
        "replicaTimeout",
        "replicaRetryLimit",
        "manualTriggerConfig",
        "registries",
        "secretNames",
        "containers",
    }
    if (
        set(payload) != expected_keys
        or payload["id"] != job_id
        or payload["name"] != MIGRATION_JOB_NAME
        or payload["identityIds"] != [registry_identity]
        or payload["triggerType"] != "Manual"
        or payload["replicaTimeout"] != 900
        or payload["replicaRetryLimit"] != 0
        or payload["manualTriggerConfig"]
        != {"parallelism": 1, "replicaCompletionCount": 1}
        or payload["registries"]
        != [
            {
                "server": f"{registry_name}.azurecr.io",
                "identity": registry_identity,
            }
        ]
        or set(payload["secretNames"])
        != {
            "blob-connection-string",
            "database-url",
            "operator-password-hash",
            "session-pepper",
        }
        or not isinstance(container, Mapping)
        or set(container)
        != {"name", "image", "command", "args", "resources", "env", "safeEnv"}
        or container["name"] != "prepare"
        or container["image"] != expected_image
        or container["command"] != ["python"]
        or container["args"] != ["scripts/prepare_cloud.py"]
        or container["resources"] != {"cpu": 0.5, "memory": "1Gi"}
        or bindings != expected_bindings
        or safe_values != expected_safe_values
        or not isinstance(blob_endpoint, str)
        or re.fullmatch(
            r"https://[a-z0-9]{3,24}\.blob\.core\.windows\.net/",
            blob_endpoint,
        )
        is None
        or not isinstance(allowed_origin, str)
        or re.fullmatch(
            rf"https://{re.escape(str(app_name))}\.[a-z0-9.-]+",
            allowed_origin,
        )
        is None
    ):
        raise _invalid("operations_authority_invalid")
    normalized = deepcopy(dict(payload))
    normalized["identityIds"] = sorted(normalized["identityIds"])
    normalized["secretNames"] = sorted(normalized["secretNames"])
    normalized["containers"][0]["env"] = sorted(
        normalized["containers"][0]["env"],
        key=lambda item: item["name"],
    )
    normalized["containers"][0]["safeEnv"] = sorted(
        normalized["containers"][0]["safeEnv"],
        key=lambda item: item["name"],
    )
    return normalized


def collect_migration_job_authority(
    task10_request: Mapping[str, object],
    *,
    candidate_image: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    environment: Mapping[str, str] = os.environ,
) -> dict[str, object]:
    """Read one exact sanitized migration Job projection for package approval."""

    target = task10_request["azure_target"]
    try:
        completed = runner(
            [
                "az",
                "containerapp",
                "job",
                "show",
                "--subscription",
                str(target["subscription_id"]),
                "--resource-group",
                str(target["resource_group"]),
                "--name",
                MIGRATION_JOB_NAME,
                "--query",
                MIGRATION_JOB_QUERY,
                "--only-show-errors",
                "--output",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
            shell=False,
            env={
                name: value
                for name in _PROCESS_ENVIRONMENT_NAMES
                if isinstance((value := environment.get(name)), str)
            },
        )
        if len(completed.stdout) > 1_000_000:
            raise _invalid("operations_authority_invalid")
        projection = json.loads(completed.stdout)
    except (
        AdminAIReleasePackageInvalid,
        KeyError,
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        TypeError,
    ) as error:
        if isinstance(error, AdminAIReleasePackageInvalid):
            raise
        raise _invalid("operations_authority_invalid") from error
    rollback_image = str(target["rollback_image"])
    return {
        "schema_version": MIGRATION_JOB_SCHEMA,
        "safe_projection": validate_migration_job_safe_projection(
            projection,
            task10_request=task10_request,
            expected_image=rollback_image,
        ),
        "approved_execution_image": candidate_image,
    }


def _validate_operations_authority(
    value: object,
    *,
    issued_at: datetime,
    candidate_image: str,
) -> dict[str, object]:
    raw = _exact_mapping(value, {"migration_job", "task10_request"})
    migration_job = raw["migration_job"]
    request = raw["task10_request"]
    if not isinstance(request, Mapping):
        raise _invalid("operations_authority_invalid")
    try:
        copied = deepcopy(
            validate_ai_enablement_package(
                request,
                now=issued_at,
            )
        )
        if (
            copied["artifacts"] == HISTORICAL_TASK10_ARTIFACTS
            or copied["azure_target"] != CURRENT_ADMIN_AI_SUCCESSOR_TARGET
            or copied["prepackage_gate"].get("rollback_registry_tag")
            != R19_REGISTRY_TAG
            or copied["prepackage_gate"].get("rollback_identity_state")
            != "registry_only"
        ):
            raise TypeError
        expected_evidence = copied["execution_contract"]["states"][
            "reconcile_ai_vault_identity_role_diagnostics"
        ]["expected_evidence"]
        if expected_evidence.get("rbac_authorization") is not True:
            raise TypeError
    except (AIEnablementPackageInvalid, KeyError, TypeError) as error:
        raise _invalid("operations_authority_invalid") from error
    migration = _exact_mapping(
        migration_job,
        {"schema_version", "safe_projection", "approved_execution_image"},
    )
    rollback_image = str(copied["azure_target"]["rollback_image"])
    if (
        migration["schema_version"] != MIGRATION_JOB_SCHEMA
        or migration["approved_execution_image"] != candidate_image
    ):
        raise _invalid("operations_authority_invalid")
    safe_projection = validate_migration_job_safe_projection(
        migration["safe_projection"],
        task10_request=copied,
        expected_image=rollback_image,
    )
    validated_migration = {
        "schema_version": MIGRATION_JOB_SCHEMA,
        "safe_projection": safe_projection,
        "approved_execution_image": candidate_image,
    }
    prohibited_fields = {
        "api_key",
        "authorization",
        "candidate_key",
        "current_password",
        "database_url",
        "openai_api_key",
        "password",
    }
    prohibited_value = re.compile(
        r"(?i)(\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b|"
        r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}|postgres(?:ql)?://|AccountKey=)"
    )

    def unsafe(item: object) -> bool:
        if isinstance(item, Mapping):
            return any(
                not isinstance(key, str)
                or key.casefold() in prohibited_fields
                or unsafe(child)
                for key, child in item.items()
            )
        if isinstance(item, list):
            return any(unsafe(child) for child in item)
        return isinstance(item, str) and prohibited_value.search(item) is not None

    if unsafe(copied) or unsafe(validated_migration):
        raise _invalid("operations_authority_invalid")
    return {"migration_job": validated_migration, "task10_request": copied}


def _validate_file_manifest(
    value: object, *, schema: str, invalid_code: str
) -> dict[str, object]:
    raw = _exact_mapping(value, {"schema_version", "entries", "sha256"})
    entries = raw["entries"]
    if raw["schema_version"] != schema or not isinstance(entries, list):
        raise _invalid(invalid_code)
    validated: list[dict[str, object]] = []
    prior_path = ""
    for entry in entries:
        item = _exact_mapping(entry, {"path", "mode", "size", "sha256"})
        path = item["path"]
        if (
            not isinstance(path, str)
            or not path
            or path.startswith("/")
            or ".." in Path(path).parts
            or path <= prior_path
            or item["mode"] not in {"100644", "100755"}
            or type(item["size"]) is not int
            or item["size"] < 0
            or not isinstance(item["sha256"], str)
            or _SHA256.fullmatch(item["sha256"]) is None
        ):
            raise _invalid(invalid_code)
        validated.append(dict(item))
        prior_path = path
    if not validated:
        raise _invalid(invalid_code)
    canonical = json.dumps(
        {"schema_version": schema, "entries": validated},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    if raw["sha256"] != digest:
        raise _invalid(invalid_code)
    return {
        "schema_version": schema,
        "entries": validated,
        "sha256": digest,
    }


def _validate_build_context_manifest(value: object) -> dict[str, object]:
    return _validate_file_manifest(
        value,
        schema=BUILD_CONTEXT_SCHEMA,
        invalid_code="build_context_manifest_invalid",
    )


def _validate_runtime_tool_manifest(value: object) -> dict[str, object]:
    manifest = _validate_file_manifest(
        value,
        schema=RUNTIME_TOOL_SCHEMA,
        invalid_code="runtime_tool_manifest_invalid",
    )
    if [entry["path"] for entry in manifest["entries"]] != sorted(
        RUNTIME_TOOL_PATHS
    ):
        raise _invalid("runtime_tool_manifest_invalid")
    return manifest


def _validate_runtime_dependencies(value: object) -> dict[str, object]:
    try:
        from scripts.admin_ai_exact_runtime import (  # noqa: PLC0415
            AdminAIExactRuntimeInvalid,
            _validate_runtime_dependency_manifest,
        )

        return _validate_runtime_dependency_manifest(value)
    except AdminAIExactRuntimeInvalid as error:
        raise _invalid("runtime_dependency_manifest_invalid") from error


def _validate_retired_hashes(values: Sequence[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise _invalid("retired_package_hash_invalid")
        if value in result:
            raise _invalid("retired_package_hash_invalid")
        result.append(value)
    return result


def _validate_candidate_artifact(value: object) -> dict[str, object]:
    raw = _exact_mapping(
        value,
        {
            "artifact_format",
            "artifact_path",
            "artifact_sha256",
            "image_digest",
            "platform",
            "source_sha",
            "source_tree",
            "image_input_sha256",
            "build_context_sha256",
            "oci_reference",
            "runtime_user",
        },
    )
    artifact_path = raw["artifact_path"]
    if not isinstance(artifact_path, str):
        raise _invalid("candidate_artifact_invalid")
    parsed_path = PurePosixPath(artifact_path)
    if (
        raw["artifact_format"] != "oci-archive"
        or parsed_path.is_absolute()
        or ".." in parsed_path.parts
        or parsed_path.parts[:1] != (".tmp",)
        or not artifact_path.endswith(".oci.tar")
        or not isinstance(raw["artifact_sha256"], str)
        or _SHA256.fullmatch(raw["artifact_sha256"]) is None
        or not isinstance(raw["image_digest"], str)
        or _IMAGE_DIGEST.fullmatch(raw["image_digest"]) is None
        or raw["platform"] != "linux/amd64"
        or not isinstance(raw["source_sha"], str)
        or _GIT_SHA.fullmatch(raw["source_sha"]) is None
        or not isinstance(raw["source_tree"], str)
        or _GIT_SHA.fullmatch(raw["source_tree"]) is None
        or not isinstance(raw["image_input_sha256"], str)
        or _SHA256.fullmatch(raw["image_input_sha256"]) is None
        or not isinstance(raw["build_context_sha256"], str)
        or _SHA256.fullmatch(raw["build_context_sha256"]) is None
        or raw["oci_reference"] != f"candidate-{raw['source_sha'][:12]}"
        or raw["runtime_user"] != "bizpulse"
    ):
        raise _invalid("candidate_artifact_invalid")
    return dict(raw)


def build_package(
    *,
    source_sha: str,
    source_tree: str,
    image_digest: str,
    image_platform: str,
    image_input_sha256: str,
    candidate_artifact: Mapping[str, object],
    baseline: Mapping[str, object],
    authority: Mapping[str, object],
    issued_at: datetime,
    expires_at: datetime,
    receipt_path: str,
    retired_package_sha256: Sequence[str],
    operations_factory: Mapping[str, object],
    build_context_manifest: Mapping[str, object],
    runtime_tool_manifest: Mapping[str, object],
    runtime_dependency_manifest: Mapping[str, object],
    operations_authority: Mapping[str, object],
) -> dict[str, object]:
    """Build a deterministic, secret-free package from one fresh observation."""

    if _GIT_SHA.fullmatch(source_sha) is None:
        raise _invalid("source_sha_invalid")
    if _GIT_SHA.fullmatch(source_tree) is None:
        raise _invalid("source_tree_invalid")
    if _IMAGE_DIGEST.fullmatch(image_digest) is None:
        raise _invalid("image_digest_invalid")
    if image_platform != "linux/amd64":
        raise _invalid("image_platform_invalid")
    if _SHA256.fullmatch(image_input_sha256) is None:
        raise _invalid("image_input_sha256_invalid")
    if issued_at.tzinfo is None or expires_at.tzinfo is None:
        raise _invalid("package_expiry_invalid")
    issued = issued_at.astimezone(UTC)
    expires = expires_at.astimezone(UTC)
    if expires - issued != PACKAGE_LIFETIME:
        raise _invalid("package_expiry_invalid")
    if (
        not isinstance(receipt_path, str)
        or not receipt_path
        or not receipt_path.endswith(".json")
        or "\x00" in receipt_path
    ):
        raise _invalid("receipt_path_invalid")
    validated_baseline = _validate_baseline(baseline, issued_at=issued)
    validated_authority = _validate_authority(
        authority,
        issued_at=issued,
    )
    retired = _validate_retired_hashes(retired_package_sha256)
    validated_factory = _validate_operations_factory(operations_factory)
    validated_build_context = _validate_build_context_manifest(
        build_context_manifest
    )
    validated_runtime_tools = _validate_runtime_tool_manifest(
        runtime_tool_manifest
    )
    validated_runtime_dependencies = _validate_runtime_dependencies(
        runtime_dependency_manifest
    )
    validated_artifact = _validate_candidate_artifact(candidate_artifact)
    task10_request = operations_authority.get("task10_request")
    try:
        target = task10_request["azure_target"]
        request_candidate = task10_request["candidate"]
        candidate_reference = (
            f"{target['registry_name']}.azurecr.io/"
            f"{request_candidate['image_repository']}@{image_digest}"
        )
    except (KeyError, TypeError) as error:
        raise _invalid("operations_authority_invalid") from error
    validated_operations_authority = _validate_operations_authority(
        operations_authority,
        issued_at=issued,
        candidate_image=candidate_reference,
    )
    task10_repository = validated_operations_authority["task10_request"][
        "repository"
    ]
    task10_candidate = validated_operations_authority["task10_request"][
        "candidate"
    ]
    task10_target = validated_operations_authority["task10_request"][
        "azure_target"
    ]
    task10_gate = validated_operations_authority["task10_request"][
        "prepackage_gate"
    ]
    if (
        task10_repository.get("head_sha") != source_sha
        or task10_repository.get("tree_sha") != source_tree
        or task10_candidate.get("source_tree_sha") != source_tree
        or task10_candidate.get("image_input_sha256") != image_input_sha256
        or task10_gate.get("role_assignment_state")
        != validated_baseline["role_assignment_phase"]
        or task10_target.get("rollback_revision")
        != validated_baseline["revision"]
        or task10_target.get("rollback_image", "").rsplit("@", maxsplit=1)[-1]
        != validated_baseline["image_digest"]
        or validated_artifact["image_digest"] != image_digest
        or validated_artifact["platform"] != image_platform
        or validated_artifact["source_sha"] != source_sha
        or validated_artifact["source_tree"] != source_tree
        or validated_artifact["image_input_sha256"] != image_input_sha256
        or validated_artifact["build_context_sha256"]
        != validated_build_context["sha256"]
    ):
        raise _invalid("operations_authority_drift")
    package = {
        "schema_version": PACKAGE_SCHEMA,
        "issued_at": _utc_text(issued),
        "expires_at": _utc_text(expires),
        "repository": {
            "source_sha": source_sha,
            "source_tree": source_tree,
            "tracked_tree_clean": True,
            "build_context_manifest": validated_build_context,
            "runtime_tool_manifest": validated_runtime_tools,
            "runtime_dependency_manifest": validated_runtime_dependencies,
        },
        "candidate": {
            "image_digest": image_digest,
            "platform": image_platform,
            "source_sha": source_sha,
            "source_tree": source_tree,
            "image_input_sha256": image_input_sha256,
            "build_context_sha256": validated_build_context["sha256"],
            "artifact_format": validated_artifact["artifact_format"],
            "artifact_path": validated_artifact["artifact_path"],
            "artifact_sha256": validated_artifact["artifact_sha256"],
            "oci_reference": validated_artifact["oci_reference"],
            "runtime_user": validated_artifact["runtime_user"],
        },
        "azure_baseline": validated_baseline,
        "authority_binding": validated_authority,
        "operations_factory": validated_factory,
        "operations_authority": validated_operations_authority,
        "execution_contract": {
            "attempts": 1,
            "automatic_retries": 0,
            "required_azure_reads": REQUIRED_AZURE_READS,
            "rbac_migration_action": "reconcile_admin_ai_secret_access",
            "receipt_path": receipt_path,
        },
        "replay_fence": {"retired_package_sha256": retired},
    }
    serialized = json.dumps(package, sort_keys=True, separators=(",", ":"))
    prohibited = (
        "OPENAI_API_KEY",
        "candidate_key",
        "current_password",
        "api_key",
    )
    if any(value.casefold() in serialized.casefold() for value in prohibited):
        raise _invalid("package_prohibited_content")
    return package


def _encoded(package: Mapping[str, object]) -> bytes:
    return (
        json.dumps(package, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def package_sha256(package: Mapping[str, object]) -> str:
    """Return the approval hash for the exact deterministic package bytes."""

    return hashlib.sha256(_encoded(package)).hexdigest()


def _validate_package(package: object, *, now: datetime) -> dict[str, object]:
    raw = _exact_mapping(
        package,
        {
            "schema_version",
            "issued_at",
            "expires_at",
            "repository",
            "candidate",
            "azure_baseline",
            "authority_binding",
            "operations_factory",
            "operations_authority",
            "execution_contract",
            "replay_fence",
        },
    )
    if raw["schema_version"] != PACKAGE_SCHEMA or now.tzinfo is None:
        raise _invalid("package_invalid")
    issued = _parse_utc(raw["issued_at"], code="package_invalid")
    expires = _parse_utc(raw["expires_at"], code="package_invalid")
    if expires - issued != PACKAGE_LIFETIME:
        raise _invalid("package_expiry_invalid")
    current = now.astimezone(UTC)
    if current < issued or current >= expires:
        raise _invalid("package_expired")
    repository = _exact_mapping(
        raw["repository"],
        {
            "source_sha",
            "source_tree",
            "tracked_tree_clean",
            "build_context_manifest",
            "runtime_tool_manifest",
            "runtime_dependency_manifest",
        },
    )
    candidate = _exact_mapping(
        raw["candidate"],
        {
            "image_digest",
            "platform",
            "source_sha",
            "source_tree",
            "image_input_sha256",
            "build_context_sha256",
            "artifact_format",
            "artifact_path",
            "artifact_sha256",
            "oci_reference",
            "runtime_user",
        },
    )
    execution = _exact_mapping(
        raw["execution_contract"],
        {
            "attempts",
            "automatic_retries",
            "required_azure_reads",
            "rbac_migration_action",
            "receipt_path",
        },
    )
    replay = _exact_mapping(raw["replay_fence"], {"retired_package_sha256"})
    manifest = _validate_build_context_manifest(
        repository["build_context_manifest"]
    )
    runtime_manifest = _validate_runtime_tool_manifest(
        repository["runtime_tool_manifest"]
    )
    runtime_dependencies = _validate_runtime_dependencies(
        repository["runtime_dependency_manifest"]
    )
    if candidate["build_context_sha256"] != manifest["sha256"]:
        raise _invalid("build_context_binding_mismatch")
    rebuilt = build_package(
        source_sha=repository["source_sha"],
        source_tree=repository["source_tree"],
        image_digest=candidate["image_digest"],
        image_platform=candidate["platform"],
        image_input_sha256=candidate["image_input_sha256"],
        candidate_artifact={
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
        },
        baseline=raw["azure_baseline"],
        authority=raw["authority_binding"],
        issued_at=issued,
        expires_at=expires,
        receipt_path=execution["receipt_path"],
        retired_package_sha256=replay["retired_package_sha256"],
        operations_factory=raw["operations_factory"],
        build_context_manifest=manifest,
        runtime_tool_manifest=runtime_manifest,
        runtime_dependency_manifest=runtime_dependencies,
        operations_authority=raw["operations_authority"],
    )
    if raw != rebuilt:
        raise _invalid("package_invalid")
    return dict(raw)


def validate_package(package: object, *, now: datetime) -> dict[str, object]:
    """Validate an in-memory package using the same strict loader contract."""

    return _validate_package(package, now=now)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _invalid("package_duplicate_key")
        result[key] = value
    return result


def write_package(path: Path, package: Mapping[str, object]) -> str:
    """Exclusively write one regular package at mode 0600."""

    issued = _parse_utc(package.get("issued_at"), code="package_invalid")
    _validate_package(package, now=issued)
    encoded = _encoded(package)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        raise _invalid("package_write_refused") from error
    return hashlib.sha256(encoded).hexdigest()


def load_package(path: Path, *, now: datetime) -> dict[str, object]:
    """Load one unexpired, owner-only regular package without following links."""

    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or not 0 < metadata.st_size <= 1_000_000
        ):
            raise _invalid("package_file_invalid")
        package = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _invalid("package_file_invalid") from error
    return _validate_package(package, now=now)


def _capture_source_file_manifest(
    source_sha: str,
    project_root: Path,
    *,
    paths: Sequence[str],
    schema: str,
    read_failed_code: str,
    dirty_code: str,
) -> dict[str, object]:
    if _GIT_SHA.fullmatch(source_sha) is None:
        raise _invalid(read_failed_code)
    try:
        listed = subprocess.run(
            [
                "git",
                "ls-tree",
                "-r",
                "-z",
                source_sha,
                "--",
                *paths,
            ],
            cwd=project_root,
            check=True,
            capture_output=True,
            timeout=30,
            shell=False,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise _invalid(read_failed_code) from error
    entries: list[dict[str, object]] = []
    for raw in listed.split(b"\0"):
        if not raw:
            continue
        try:
            metadata, encoded_path = raw.split(b"\t", 1)
            mode, object_type, blob_sha = metadata.decode("ascii").split(" ", 2)
            path = encoded_path.decode("utf-8")
            candidate = project_root / path
            file_metadata = candidate.lstat()
            local_bytes = candidate.read_bytes()
            committed = subprocess.run(
                ["git", "cat-file", "blob", blob_sha],
                cwd=project_root,
                check=True,
                capture_output=True,
                timeout=30,
                shell=False,
            ).stdout
        except (OSError, UnicodeError, ValueError, subprocess.SubprocessError) as error:
            raise _invalid(read_failed_code) from error
        if (
            object_type != "blob"
            or mode not in {"100644", "100755"}
            or not stat.S_ISREG(file_metadata.st_mode)
            or candidate.is_symlink()
            or committed != local_bytes
            or stat.S_IMODE(file_metadata.st_mode) != int(mode[-3:], 8)
        ):
            raise _invalid(dirty_code)
        entries.append(
            {
                "mode": mode,
                "path": path,
                "sha256": hashlib.sha256(local_bytes).hexdigest(),
                "size": len(local_bytes),
            }
        )
    entries.sort(key=lambda entry: str(entry["path"]))
    canonical = json.dumps(
        {"schema_version": schema, "entries": entries},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    value = {
        "schema_version": schema,
        "entries": entries,
        "sha256": hashlib.sha256(canonical).hexdigest(),
    }
    return _validate_file_manifest(
        value,
        schema=schema,
        invalid_code=read_failed_code,
    )


def _capture_materialized_file_manifest(
    project_root: Path,
    *,
    paths: Sequence[str],
    schema: str,
    read_failed_code: str,
) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    try:
        candidates: list[Path] = []
        for relative in paths:
            root = project_root / relative
            if root.is_dir():
                candidates.extend(path for path in root.rglob("*") if path.is_file())
            else:
                candidates.append(root)
        for candidate in candidates:
            metadata = candidate.lstat()
            relative = candidate.relative_to(project_root).as_posix()
            payload = candidate.read_bytes()
            if (
                relative in seen
                or candidate.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) not in {0o400, 0o500}
            ):
                raise _invalid(read_failed_code)
            seen.add(relative)
            entries.append(
                {
                    "mode": "100755" if metadata.st_mode & stat.S_IXUSR else "100644",
                    "path": relative,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size": len(payload),
                }
            )
    except (OSError, ValueError) as error:
        raise _invalid(read_failed_code) from error
    entries.sort(key=lambda entry: str(entry["path"]))
    canonical = json.dumps(
        {"schema_version": schema, "entries": entries},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return _validate_file_manifest(
        {
            "schema_version": schema,
            "entries": entries,
            "sha256": hashlib.sha256(canonical).hexdigest(),
        },
        schema=schema,
        invalid_code=read_failed_code,
    )


def capture_build_context_manifest(
    source_sha: str,
    project_root: Path,
) -> dict[str, object]:
    """Hash the exact committed bytes and modes accepted by the Docker context."""

    return _capture_source_file_manifest(
        source_sha,
        project_root,
        paths=BUILD_CONTEXT_PATHS,
        schema=BUILD_CONTEXT_SCHEMA,
        read_failed_code="build_context_read_failed",
        dirty_code="build_context_dirty",
    )


def capture_runtime_tool_manifest(
    source_sha: str,
    project_root: Path,
) -> dict[str, object]:
    """Hash every transitive Python source and lockfile executed by the release."""

    manifest = _capture_source_file_manifest(
        source_sha,
        project_root,
        paths=RUNTIME_TOOL_PATHS,
        schema=RUNTIME_TOOL_SCHEMA,
        read_failed_code="runtime_tool_manifest_read_failed",
        dirty_code="runtime_tool_manifest_dirty",
    )
    return _validate_runtime_tool_manifest(manifest)


def capture_repository(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    project_root: Path | None = None,
    manifest_reader: Callable[[str, Path], Mapping[str, object]] = (
        capture_build_context_manifest
    ),
    runtime_manifest_reader: Callable[[str, Path], Mapping[str, object]] = (
        capture_runtime_tool_manifest
    ),
) -> dict[str, object]:
    """Capture exact HEAD/tree and refuse mutable build or release inputs."""

    root = PROJECT_ROOT if project_root is None else project_root

    try:
        from scripts.admin_ai_exact_runtime import (  # noqa: PLC0415
            AdminAIExactRuntimeInvalid,
            load_exact_runtime_marker,
            load_runtime_dependency_manifest,
        )

        marker = load_exact_runtime_marker(root)
        runtime_dependencies = load_runtime_dependency_manifest(root)
    except AdminAIExactRuntimeInvalid as error:
        raise _invalid("repository_read_failed") from error
    if marker is not None:
        manifest = _capture_materialized_file_manifest(
            root,
            paths=BUILD_CONTEXT_PATHS,
            schema=BUILD_CONTEXT_SCHEMA,
            read_failed_code="build_context_read_failed",
        )
        runtime_manifest = _validate_runtime_tool_manifest(
            _capture_materialized_file_manifest(
                root,
                paths=RUNTIME_TOOL_PATHS,
                schema=RUNTIME_TOOL_SCHEMA,
                read_failed_code="runtime_tool_manifest_read_failed",
            )
        )
        result = {
            "source_sha": marker["source_sha"],
            "source_tree": marker["source_tree"],
            "tracked_tree_clean": True,
            "build_context_manifest": manifest,
            "runtime_tool_manifest": runtime_manifest,
        }
        if runtime_dependencies is not None:
            result["runtime_dependency_manifest"] = runtime_dependencies
        return result

    def git(*arguments: str) -> str:
        try:
            result = runner(
                ["git", *arguments],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise _invalid("repository_read_failed") from error
        if result.returncode != 0 or not isinstance(result.stdout, str):
            raise _invalid("repository_read_failed")
        return result.stdout.strip()

    source_sha = git("rev-parse", "HEAD")
    source_tree = git("rev-parse", "HEAD^{tree}")
    repository_status = git(
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if repository_status:
        raise _invalid("repository_dirty")
    try:
        scripts_directory = root / "scripts"
        shadow_candidates = (
            *scripts_directory.glob("*.so"),
            *scripts_directory.glob("*.pyd"),
            *scripts_directory.glob("*.pyc"),
            *scripts_directory.glob("*.pth"),
            root / "sitecustomize.py",
            root / "usercustomize.py",
            scripts_directory / "sitecustomize.py",
            scripts_directory / "usercustomize.py",
        )
        if any(
            candidate.exists() or candidate.is_symlink()
            for candidate in shadow_candidates
        ):
            raise _invalid("repository_import_shadow")
    except OSError as error:
        raise _invalid("repository_read_failed") from error
    if _GIT_SHA.fullmatch(source_sha) is None or _GIT_SHA.fullmatch(source_tree) is None:
        raise _invalid("repository_read_failed")
    manifest = _validate_build_context_manifest(
        manifest_reader(source_sha, root)
    )
    runtime_manifest = _validate_runtime_tool_manifest(
        runtime_manifest_reader(source_sha, root)
    )
    return {
        "source_sha": source_sha,
        "source_tree": source_tree,
        "tracked_tree_clean": True,
        "build_context_manifest": manifest,
        "runtime_tool_manifest": runtime_manifest,
    }


def capture_operations_factory(
    specification: str,
    *,
    source_sha: str,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    project_root: Path | None = None,
) -> dict[str, str]:
    """Bind a factory to the exact regular file committed at the source SHA."""

    root = PROJECT_ROOT if project_root is None else project_root
    if (
        not isinstance(specification, str)
        or re.fullmatch(
            r"scripts\.[a-z0-9_]+:[a-zA-Z_][a-zA-Z0-9_]*",
            specification,
        )
        is None
        or _GIT_SHA.fullmatch(source_sha) is None
    ):
        raise _invalid("operations_factory_invalid")
    module_name = specification.split(":", 1)[0]
    source_path = module_name.replace(".", "/") + ".py"
    candidate = root / source_path
    try:
        from scripts.admin_ai_exact_runtime import (  # noqa: PLC0415
            AdminAIExactRuntimeInvalid,
            load_exact_runtime_marker,
        )

        marker = load_exact_runtime_marker(root)
        metadata = candidate.lstat()
        if not stat.S_ISREG(metadata.st_mode) or candidate.is_symlink():
            raise _invalid("operations_factory_invalid")
        local_bytes = candidate.read_bytes()
        if marker is not None:
            if marker["source_sha"] != source_sha:
                raise _invalid("operations_factory_invalid")
            committed = local_bytes
        else:
            completed = runner(
                ["git", "show", f"{source_sha}:./{source_path}"],
                cwd=root,
                check=False,
                capture_output=True,
                timeout=30,
                shell=False,
            )
            if completed.returncode != 0:
                raise _invalid("operations_factory_invalid")
            committed = completed.stdout
    except AdminAIReleasePackageInvalid:
        raise
    except (AdminAIExactRuntimeInvalid, OSError, subprocess.SubprocessError) as error:
        raise _invalid("operations_factory_invalid") from error
    if committed != local_bytes:
        raise _invalid("operations_factory_invalid")
    return _validate_operations_factory(
        {
            "factory": specification,
            "source_path": source_path,
            "source_sha256": hashlib.sha256(local_bytes).hexdigest(),
        }
    )


def capture_candidate_image(
    *,
    source_sha: str,
    source_tree: str,
    image_reference: str,
    image_input_sha256: str,
    build_context_sha256: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    """Inspect one exact OCI image and bind its platform and source labels."""

    if (
        _GIT_SHA.fullmatch(source_sha) is None
        or _GIT_SHA.fullmatch(source_tree) is None
        or not isinstance(image_reference, str)
        or "@" not in image_reference
        or _IMAGE_DIGEST.fullmatch(image_reference.rsplit("@", 1)[-1]) is None
        or _SHA256.fullmatch(image_input_sha256) is None
        or _SHA256.fullmatch(build_context_sha256) is None
    ):
        raise _invalid("candidate_image_invalid")
    try:
        completed = runner(
            ["docker", "image", "inspect", image_reference],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
        if completed.returncode != 0 or len(completed.stdout) > 1_000_000:
            raise _invalid("candidate_image_unavailable")
        payload = json.loads(completed.stdout)
        image = payload[0]
        labels = image["Config"]["Labels"]
    except AdminAIReleasePackageInvalid:
        raise
    except (OSError, subprocess.SubprocessError) as error:
        raise _invalid("candidate_image_unavailable") from error
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise _invalid("candidate_image_invalid") from error
    digest = image_reference.rsplit("@", 1)[-1]
    if (
        not isinstance(payload, list)
        or len(payload) != 1
        or not isinstance(image, Mapping)
        or image.get("Os") != "linux"
        or image.get("Architecture") != "amd64"
        or image_reference not in image.get("RepoDigests", [])
        or labels.get("org.opencontainers.image.revision") != source_sha
        or labels.get("org.opencontainers.image.bizpulse.image-input-sha256")
        != image_input_sha256
        or labels.get("org.opencontainers.image.bizpulse.build-context-sha256")
        != build_context_sha256
    ):
        raise _invalid("candidate_image_invalid")
    return {
        "image_digest": digest,
        "platform": "linux/amd64",
        "source_sha": source_sha,
        "source_tree": source_tree,
        "image_input_sha256": image_input_sha256,
        "build_context_sha256": build_context_sha256,
    }


def capture_candidate_artifact(
    path: Path,
    *,
    source_sha: str,
    source_tree: str,
    image_input_sha256: str,
    build_context_sha256: str,
    project_root: Path | None = None,
) -> dict[str, object]:
    """Bind one exact owner-only OCI archive under the project private area."""

    root = PROJECT_ROOT if project_root is None else project_root
    try:
        resolved_root = root.resolve(strict=True)
        candidate = path if path.is_absolute() else root / path
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(resolved_root).as_posix()
        inspected = inspect_oci_archive(
            resolved,
            source_sha=source_sha,
            source_tree=source_tree,
            image_input_sha256=image_input_sha256,
            build_context_sha256=build_context_sha256,
        )
    except (OSError, ValueError, AdminAIOCIArtifactInvalid) as error:
        raise _invalid("candidate_artifact_invalid") from error
    inspected["artifact_path"] = relative
    return _validate_candidate_artifact(inspected)


def validate_task10_request_for_observation(
    authority_request: object,
    *,
    observed_at: datetime,
    source_sha: str,
    source_tree: str,
    image_input_sha256: str,
    verified_prior_attempts: Mapping[str, object],
) -> dict[str, object]:
    """Validate the complete Task 10 authority before its first Azure read."""

    try:
        validated = validate_ai_enablement_package(
            authority_request,
            now=observed_at,
        )
        repository = validated["repository"]
        candidate = validated["candidate"]
        artifacts = validated["artifacts"]
        azure_target = validated["azure_target"]
        prepackage_gate = validated["prepackage_gate"]
        prior_attempts = validated["prior_attempts"]
        expected_evidence = validated["execution_contract"]["states"][
            "reconcile_ai_vault_identity_role_diagnostics"
        ]["expected_evidence"]
    except (AIEnablementPackageInvalid, KeyError, TypeError) as error:
        raise _invalid("operations_authority_invalid") from error
    if (
        artifacts == HISTORICAL_TASK10_ARTIFACTS
        or azure_target != CURRENT_ADMIN_AI_SUCCESSOR_TARGET
        or prepackage_gate.get("rollback_registry_tag") != R19_REGISTRY_TAG
        or prepackage_gate.get("rollback_identity_state") != "registry_only"
        or prior_attempts != verified_prior_attempts
        or repository.get("head_sha") != source_sha
        or repository.get("tree_sha") != source_tree
        or candidate.get("source_tree_sha") != source_tree
        or candidate.get("image_input_sha256") != image_input_sha256
        or expected_evidence.get("rbac_authorization") is not True
    ):
        raise _invalid("operations_authority_drift")
    return validated


def collect_current_azure_baseline(
    authority_request: Mapping[str, object],
    *,
    observed_at: datetime,
    source_sha: str,
    source_tree: str,
    image_input_sha256: str,
    verified_prior_attempts: Mapping[str, object],
    reader: Callable[..., object] | None = None,
    readiness_reader: Callable[[str], str] | None = None,
) -> dict[str, object]:
    """Derive the baseline only from Task 10's exact twelve-read verifier."""

    validated_request = validate_task10_request_for_observation(
        authority_request,
        observed_at=observed_at,
        source_sha=source_sha,
        source_tree=source_tree,
        image_input_sha256=image_input_sha256,
        verified_prior_attempts=verified_prior_attempts,
    )
    if reader is None:
        from scripts.azure_ai_enablement_actions import (  # noqa: PLC0415
            read_sanitized_azure_authority,
        )

        reader = read_sanitized_azure_authority
    observed: dict[str, object] = {}

    def observe(values: Mapping[str, object]) -> None:
        observed.update(deepcopy(dict(values)))

    try:
        task10_result, projection = reader(
            validated_request,
            safe_observer=observe,
        )
        target = validated_request["azure_target"]
        expected_phase = validated_request["prepackage_gate"][
            "role_assignment_state"
        ]
        outputs = task10_result["outputs"]
        hosted_url = observed["hosted_url"]
        if not isinstance(hosted_url, str):
            raise TypeError
        database_revision = (
            read_hosted_database_revision(hosted_url)
            if readiness_reader is None
            else readiness_reader(hosted_url)
        )
    except (KeyError, TypeError, ValueError) as error:
        raise _invalid("azure_baseline_invalid") from error
    if (
        task10_result.get("operations") != {"azure.read.sanitized": 12}
        or outputs.get("rollback_revision") != target.get("rollback_revision")
        or outputs.get("ai_enabled") is not False
        or outputs.get("role_assignment_state") != expected_phase
        or outputs.get("secret_values_read") != 0
        or expected_phase not in ALLOWED_RBAC_PHASES
        or database_revision not in PRE_MIGRATION_DATABASE_REVISIONS
    ):
        raise _invalid("azure_read_contract_invalid")
    rollback_image = target.get("rollback_image")
    if (
        not isinstance(rollback_image, str)
        or "@" not in rollback_image
        or _IMAGE_DIGEST.fullmatch(rollback_image.rsplit("@", 1)[-1]) is None
    ):
        raise _invalid("azure_baseline_invalid")
    canonical = json.dumps(
        {
            "result": task10_result,
            "projection": projection,
            "readiness": {
                "database_revision": database_revision,
                "status": "ready",
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        "observed_at": _utc_text(observed_at),
        "observation_sha256": hashlib.sha256(canonical).hexdigest(),
        "required_azure_reads": 12,
        "health_state": "Healthy",
        "ready": True,
        "revision": target["rollback_revision"],
        "image_digest": rollback_image.rsplit("@", 1)[-1],
        "traffic_weight": 100,
        "operator_ai_enabled": False,
        "demo_ai_enabled": False,
        "role_assignment_phase": expected_phase,
        "database_revision": database_revision,
    }


def read_hosted_database_revision(
    hosted_origin: str,
    *,
    client_factory: Callable[..., object] | None = None,
) -> str:
    """Read one bounded public readiness projection without ambient credentials."""

    parsed = urlsplit(hosted_origin)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise _invalid("azure_baseline_readiness_invalid")
    if client_factory is None:
        import httpx  # noqa: PLC0415

        client_factory = httpx.Client
    client = client_factory(
        base_url=hosted_origin.rstrip("/"),
        timeout=15,
        follow_redirects=False,
        trust_env=False,
    )
    try:
        response = client.get(
            "/health/ready",
            headers={"Accept": "application/json"},
        )
        if response.status_code != 200 or len(response.content) > 65_536:
            raise _invalid("azure_baseline_readiness_invalid")
        payload = response.json()
    except AdminAIReleasePackageInvalid:
        raise
    except Exception as error:
        raise _invalid("azure_baseline_readiness_invalid") from error
    finally:
        client.close()
    if not isinstance(payload, Mapping) or set(payload) != {"status", "checks"}:
        raise _invalid("azure_baseline_readiness_invalid")
    checks = payload["checks"]
    expected_checks = {"blob", "configuration", "database", "foundation", "migration"}
    if (
        payload["status"] != "ready"
        or not isinstance(checks, Mapping)
        or set(checks) != expected_checks
        or any(checks[name] != "ok" for name in expected_checks - {"migration"})
        or checks["migration"] not in PRE_MIGRATION_DATABASE_REVISIONS
    ):
        raise _invalid("azure_baseline_readiness_invalid")
    return str(checks["migration"])


def capture_authority_binding(
    path: Path,
    *,
    now: datetime,
    project_root: Path | None = None,
) -> dict[str, object]:
    """Hash the current authority file and reject an expired Azure snapshot."""

    root = PROJECT_ROOT if project_root is None else project_root
    try:
        resolved_root = root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        metadata = resolved.lstat()
        if (
            not resolved.is_relative_to(resolved_root)
            or not stat.S_ISREG(metadata.st_mode)
            or resolved.is_symlink()
            or not 0 < metadata.st_size <= 1_000_000
        ):
            raise _invalid("authority_file_invalid")
        encoded = resolved.read_bytes()
        document = json.loads(encoded)
        freshness = document["freshness"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise _invalid("authority_file_invalid") from error
    if (
        not isinstance(freshness, Mapping)
        or set(freshness)
        != {"evidence_kind", "evidence_sha256", "observed_at", "expires_at"}
        or freshness["evidence_kind"] != "sanitized_azure_readback"
        or not isinstance(freshness["evidence_sha256"], str)
        or _SHA256.fullmatch(freshness["evidence_sha256"]) is None
    ):
        raise _invalid("authority_file_invalid")
    observed = _parse_utc(freshness["observed_at"], code="authority_stale")
    expires = _parse_utc(freshness["expires_at"], code="authority_stale")
    current = now.astimezone(UTC)
    if observed > current or expires <= current:
        raise _invalid("authority_stale")
    return {
        "path": resolved.relative_to(resolved_root).as_posix(),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "evidence_sha256": freshness["evidence_sha256"],
        "observed_at": freshness["observed_at"],
        "expires_at": freshness["expires_at"],
    }


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-artifact", type=Path, required=True)
    authority_group = parser.add_mutually_exclusive_group(required=True)
    authority_group.add_argument("--azure-authority-request", type=Path)
    authority_group.add_argument("--create-azure-authority-request", type=Path)
    parser.add_argument(
        "--task10-role-assignment-state",
        choices=tuple(sorted(ALLOWED_RBAC_PHASES)),
    )
    parser.add_argument(
        "--authority",
        type=Path,
        default=Path("release/current_authority.json"),
    )
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--operations-factory",
        required=True,
        help="Committed adapter factory as scripts.module:function",
    )
    parser.add_argument("--retired-package-sha256", action="append", default=[])
    options = parser.parse_args(arguments)
    try:
        repository = capture_repository()
        now = datetime.now(UTC).replace(microsecond=0)
        from scripts.create_release_manifest import (  # noqa: PLC0415
            DEPENDENCY_FILES,
            image_input_sha256 as build_image_input_sha256,
        )

        dependency_hashes = {
            path: hashlib.sha256((PROJECT_ROOT / path).read_bytes()).hexdigest()
            for path in DEPENDENCY_FILES
        }
        image_input_sha256 = build_image_input_sha256(
            git_tree=str(repository["source_tree"]),
            dependency_hashes=dependency_hashes,
        )
        image = capture_candidate_artifact(
            options.candidate_artifact,
            source_sha=str(repository["source_sha"]),
            source_tree=str(repository["source_tree"]),
            image_input_sha256=image_input_sha256,
            build_context_sha256=str(
                repository["build_context_manifest"]["sha256"]
            ),
        )
        from scripts.create_ai_enablement_package import (  # noqa: PLC0415
            capture_prior_ai_attempts,
            collect_control_sha256,
        )

        verified_prior_attempts = capture_prior_ai_attempts(
            project_root=Path.cwd()
        )
        if options.create_azure_authority_request is not None:
            if options.task10_role_assignment_state is None:
                raise _invalid("operations_authority_invalid")
            match = re.fullmatch(
                r"LAUNCH_AUTHORIZATION_AI_ENABLEMENT_TASK12_"
                r"([0-9a-f-]{36})\.json",
                options.create_azure_authority_request.name,
            )
            if match is None:
                raise _invalid("operations_authority_invalid")
            authority_request = write_fresh_task10_authority_request(
                options.create_azure_authority_request,
                repository=repository,
                candidate_artifact=image,
                generated_at=now,
                role_assignment_state=options.task10_role_assignment_state,
                artifact_id=match.group(1),
                project_root=PROJECT_ROOT,
                output_root=Path.cwd(),
                control_sha256=collect_control_sha256(project_root=PROJECT_ROOT),
                prior_attempts=verified_prior_attempts,
            )
        else:
            if options.task10_role_assignment_state is not None:
                raise _invalid("operations_authority_invalid")
            authority_request = json.loads(
                options.azure_authority_request.read_text(encoding="utf-8")
            )
        authority_request = validate_task10_request_for_observation(
            authority_request,
            observed_at=now,
            source_sha=str(repository["source_sha"]),
            source_tree=str(repository["source_tree"]),
            image_input_sha256=image_input_sha256,
            verified_prior_attempts=verified_prior_attempts,
        )
        baseline = collect_current_azure_baseline(
            authority_request,
            observed_at=now,
            source_sha=str(repository["source_sha"]),
            source_tree=str(repository["source_tree"]),
            image_input_sha256=image_input_sha256,
            verified_prior_attempts=verified_prior_attempts,
        )
        authority_path = (
            options.authority
            if options.authority.is_absolute()
            else PROJECT_ROOT / options.authority
        )
        authority = capture_authority_binding(authority_path, now=now)
        operations_factory = capture_operations_factory(
            options.operations_factory,
            source_sha=str(repository["source_sha"]),
        )
        candidate_reference = (
            f"{authority_request['azure_target']['registry_name']}.azurecr.io/"
            f"{authority_request['candidate']['image_repository']}@"
            f"{image['image_digest']}"
        )
        migration_job_authority = collect_migration_job_authority(
            authority_request,
            candidate_image=candidate_reference,
        )
        package = build_package(
            source_sha=str(repository["source_sha"]),
            source_tree=str(repository["source_tree"]),
            image_digest=str(image["image_digest"]),
            image_platform=str(image["platform"]),
            image_input_sha256=str(image["image_input_sha256"]),
            candidate_artifact=image,
            baseline=baseline,
            authority=authority,
            issued_at=now,
            expires_at=now + PACKAGE_LIFETIME,
            receipt_path=options.receipt,
            retired_package_sha256=options.retired_package_sha256,
            operations_factory=operations_factory,
            build_context_manifest=repository["build_context_manifest"],
            runtime_tool_manifest=repository["runtime_tool_manifest"],
            runtime_dependency_manifest=repository[
                "runtime_dependency_manifest"
            ],
            operations_authority={
                "migration_job": migration_job_authority,
                "task10_request": authority_request,
            },
        )
        digest = write_package(options.output, package)
    except (AdminAIReleasePackageInvalid, OSError, json.JSONDecodeError) as error:
        code = str(error)
        if not re.fullmatch(r"[a-z0-9_]{3,96}", code):
            code = "package_generation_failed"
        print("admin_ai_release_package=failed")
        print(f"reason={code}")
        return 1
    print("admin_ai_release_package=created")
    print(f"package_sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
