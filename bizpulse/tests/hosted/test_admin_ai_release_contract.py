from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from scripts.admin_ai_current_successor import (
    CURRENT_ADMIN_AI_SUCCESSOR_TARGET,
)
from scripts.admin_ai_exact_runtime import RUNTIME_DEPENDENCY_DISTRIBUTIONS
from scripts.create_ai_enablement_package import (
    AZURE_TARGET as TASK10_AZURE_TARGET,
    build_ai_enablement_package,
    validate_ai_enablement_package,
)
from scripts.create_admin_ai_release_package import (
    AdminAIReleasePackageInvalid,
    RUNTIME_TOOL_PATHS,
    build_package,
    build_fresh_task10_authority_request,
    write_fresh_task10_authority_request,
    capture_authority_binding,
    capture_candidate_image,
    collect_migration_job_authority,
    collect_current_azure_baseline,
    capture_operations_factory,
    capture_repository,
    load_package,
    main as create_package_main,
    package_sha256,
    read_hosted_database_revision,
    validate_package,
    validate_task10_request_for_observation,
    write_package,
)
from scripts.run_admin_ai_release import (
    ADMIN_AI_RELEASE_STATES,
    AdminAIReleaseInvalid,
    read_candidate_key,
    run_once,
)
from scripts.verify_admin_ai_control import (
    HostedAdminAIVerificationInvalid,
    verify_hosted_admin_ai_control,
)


NOW = datetime(2026, 8, 18, 16, 0, tzinfo=UTC)
SOURCE_SHA = "1" * 40
SOURCE_TREE = "2" * 40
IMAGE_DIGEST = "sha256:" + ("3" * 64)
AUTHORITY_SHA256 = "4" * 64
BASELINE_SHA256 = "5" * 64
AUTHORITY_EVIDENCE_SHA256 = "7" * 64
IMAGE_INPUT_SHA256 = "8" * 64
ARTIFACT_SHA256 = "a" * 64
FINGERPRINT = "7fa2c91e"
BINDING_ID = "d" * 64
BUILD_CONTEXT_ENTRIES = [
    {
        "mode": "100644",
        "path": "Dockerfile",
        "sha256": "9" * 64,
        "size": 42,
    }
]
BUILD_CONTEXT_MANIFEST = {
    "schema_version": "newcaostone.docker-build-context.v1",
    "entries": BUILD_CONTEXT_ENTRIES,
    "sha256": hashlib.sha256(
        json.dumps(
            {
                "schema_version": "newcaostone.docker-build-context.v1",
                "entries": BUILD_CONTEXT_ENTRIES,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest(),
}
RUNTIME_TOOL_ENTRIES = [
    {
        "mode": "100644",
        "path": path,
        "sha256": hashlib.sha256(path.encode()).hexdigest(),
        "size": len(path),
    }
    for path in sorted(RUNTIME_TOOL_PATHS)
]
RUNTIME_TOOL_MANIFEST = {
    "schema_version": "newcaostone.admin-ai-runtime-toolchain.v1",
    "entries": RUNTIME_TOOL_ENTRIES,
    "sha256": hashlib.sha256(
        json.dumps(
            {
                "schema_version": "newcaostone.admin-ai-runtime-toolchain.v1",
                "entries": RUNTIME_TOOL_ENTRIES,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest(),
}
RUNTIME_DEPENDENCY_BASE = {
    "schema_version": "newcaostone.admin-ai-runtime-dependencies.v1",
    "python_cache_tag": sys.implementation.cache_tag,
    "python_version": (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ),
    "distributions": [
        {"name": name, "version": "1"}
        for name in sorted(RUNTIME_DEPENDENCY_DISTRIBUTIONS)
    ],
    "entries": [],
}
RUNTIME_DEPENDENCY_MANIFEST = {
    **RUNTIME_DEPENDENCY_BASE,
    "sha256": hashlib.sha256(
        json.dumps(
            RUNTIME_DEPENDENCY_BASE,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest(),
}
CANDIDATE_ARTIFACT = {
    "artifact_format": "oci-archive",
    "artifact_path": ".tmp/ADMIN_AI_CANDIDATE_2026-08-18.oci.tar",
    "artifact_sha256": ARTIFACT_SHA256,
    "image_digest": IMAGE_DIGEST,
    "platform": "linux/amd64",
    "source_sha": SOURCE_SHA,
    "source_tree": SOURCE_TREE,
    "image_input_sha256": IMAGE_INPUT_SHA256,
    "build_context_sha256": BUILD_CONTEXT_MANIFEST["sha256"],
    "oci_reference": f"candidate-{SOURCE_SHA[:12]}",
    "runtime_user": "bizpulse",
}


def _task10_request() -> dict[str, object]:
    return build_ai_enablement_package(
        generated_at=NOW,
        role_assignment_state="legacy_only",
        repository={
            "branch": "codex/newcaostone-authoritative-v1",
            "head_sha": SOURCE_SHA,
            "tree_sha": SOURCE_TREE,
            "clean": True,
        },
        azure_target=deepcopy(TASK10_AZURE_TARGET),
        candidate={
            "image_repository": "bizpulse",
            "source_tree_sha": SOURCE_TREE,
            "dockerfile_sha256": "3" * 64,
            "runtime_lock_sha256": "4" * 64,
            "image_input_sha256": IMAGE_INPUT_SHA256,
            "candidate_image_digest": None,
        },
        control_sha256={
            "infra/ai_enablement.bicep": "6" * 64,
            "infra/ai_secret_write.bicep": "a" * 64,
            "scripts/ai_enablement_contract.py": "7" * 64,
            "scripts/azure_ai_enablement_actions.py": "b" * 64,
            "scripts/azure_ai_reconciliation.py": "c" * 64,
            "scripts/azure_ai_revision.py": "8" * 64,
            "scripts/run_ai_enablement.py": "9" * 64,
        },
        d3={
            "branch": "codex/deployed-diagnostic-d3",
            "selected_base_sha": "afd3a2f0a9311aafaca35ad4a412c911aadf1e32",
            "package_sha256": (
                "2ca7c7aa0d133b94607569af437dcf0f6a2b7aa44afc475c332dfe16e0ac8687"
            ),
            "package_mode": "0600",
            "receipt_present": False,
            "observation_present": False,
        },
    )


def _task10_successor_request() -> dict[str, object]:
    request = _task10_request()
    artifact_id = "11111111-1111-4111-8111-111111111111"
    request["artifacts"] = {
        "package_path": (
            ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_TASK12_"
            f"{artifact_id}.json"
        ),
        "receipt_path": f".tmp/AI_ENABLEMENT_RECEIPT_TASK12_{artifact_id}.json",
        "observation_path": (
            f".tmp/AI_ENABLEMENT_OBSERVATION_TASK12_{artifact_id}.json"
        ),
    }
    request["azure_target"] = deepcopy(CURRENT_ADMIN_AI_SUCCESSOR_TARGET)
    request["prepackage_gate"].update(
        {
            "rollback_revision": CURRENT_ADMIN_AI_SUCCESSOR_TARGET[
                "rollback_revision"
            ],
            "rollback_image": CURRENT_ADMIN_AI_SUCCESSOR_TARGET[
                "rollback_image"
            ],
            "rollback_registry_tag": "ai-962a4fa43804-9c35ae6a",
            "rollback_identity_state": "registry_only",
        }
    )
    return validate_ai_enablement_package(request, now=NOW)


def _safe_migration_job_projection(*, image: str) -> dict[str, object]:
    target = TASK10_AZURE_TARGET
    subscription = target["subscription_id"]
    resource_group = target["resource_group"]
    registry_identity = (
        f"/subscriptions/{subscription}/resourceGroups/{resource_group}/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/"
        f"{target['existing_registry_identity_name']}"
    )
    return {
        "id": (
            f"/subscriptions/{subscription}/resourceGroups/{resource_group}/providers/"
            "Microsoft.App/jobs/newcaostone-demo-prepare"
        ),
        "name": "newcaostone-demo-prepare",
        "identityIds": [registry_identity],
        "triggerType": "Manual",
        "replicaTimeout": 900,
        "replicaRetryLimit": 0,
        "manualTriggerConfig": {
            "parallelism": 1,
            "replicaCompletionCount": 1,
        },
        "registries": [
            {
                "server": f"{target['registry_name']}.azurecr.io",
                "identity": registry_identity,
            }
        ],
        "secretNames": [
            "blob-connection-string",
            "database-url",
            "operator-password-hash",
            "session-pepper",
        ],
        "containers": [
            {
                "name": "prepare",
                "image": image,
                "command": ["python"],
                "args": ["scripts/prepare_cloud.py"],
                "resources": {"cpu": 0.5, "memory": "1Gi"},
                "env": sorted(
                    [
                        {
                            "name": "BIZPULSE_RUNTIME_ENVIRONMENT",
                            "secretRef": None,
                        },
                        {
                            "name": "BIZPULSE_DATABASE_URL",
                            "secretRef": "database-url",
                        },
                        {
                            "name": "BIZPULSE_BLOB_ENDPOINT",
                            "secretRef": None,
                        },
                        {
                            "name": "BIZPULSE_BLOB_CONTAINER",
                            "secretRef": None,
                        },
                        {
                            "name": "BIZPULSE_BLOB_CONNECTION_STRING",
                            "secretRef": "blob-connection-string",
                        },
                        {
                            "name": "BIZPULSE_ALLOWED_ORIGIN",
                            "secretRef": None,
                        },
                        {
                            "name": "BIZPULSE_OPERATOR_PASSWORD_HASH",
                            "secretRef": "operator-password-hash",
                        },
                        {
                            "name": "BIZPULSE_SESSION_PEPPER",
                            "secretRef": "session-pepper",
                        },
                    ],
                    key=lambda item: item["name"],
                ),
                "safeEnv": sorted(
                    [
                        {
                            "name": "BIZPULSE_RUNTIME_ENVIRONMENT",
                            "value": "cloud",
                        },
                        {
                            "name": "BIZPULSE_BLOB_ENDPOINT",
                            "value": "https://synthetic.blob.core.windows.net/",
                        },
                        {
                            "name": "BIZPULSE_BLOB_CONTAINER",
                            "value": "synthetic-demo",
                        },
                        {
                            "name": "BIZPULSE_ALLOWED_ORIGIN",
                            "value": (
                                "https://newcaostone-demo-app.synthetic."
                                "azurecontainerapps.io"
                            ),
                        },
                    ],
                    key=lambda item: item["name"],
                ),
            }
        ],
    }


def _live_app_projection() -> tuple[dict[str, object], dict[str, object]]:
    target = TASK10_AZURE_TARGET
    subscription = target["subscription_id"]
    resource_group = target["resource_group"]
    registry_identity = (
        f"/subscriptions/{subscription}/resourceGroups/{resource_group}/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/"
        f"{target['existing_registry_identity_name']}"
    )
    values = {
        "APPLICATIONINSIGHTS_CONNECTION_STRING": "InstrumentationKey=redacted",
        "BIZPULSE_ALLOWED_ORIGIN": (
            "https://newcaostone-demo-app.synthetic.azurecontainerapps.io"
        ),
        "BIZPULSE_AI_CHAT_ENABLED": "false",
        "BIZPULSE_AI_DAILY_ATTEMPT_LIMIT": "120",
        "BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE": "20",
        "BIZPULSE_AI_MAX_CONCURRENT_TURNS": "15",
        "BIZPULSE_AI_MONTHLY_TOKEN_LIMIT": "150000",
        "BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE": "3",
        "BIZPULSE_BLOB_CONTAINER": "synthetic-demo",
        "BIZPULSE_BLOB_ENDPOINT": "https://synthetic.blob.core.windows.net/",
        "BIZPULSE_DEMO_SESSION_RATE_LIMIT_PER_HOUR": "20",
        "BIZPULSE_OPENAI_MODEL": "gpt-5.4-nano-2026-03-17",
        "BIZPULSE_OPENAI_REASONING_EFFORT": "low",
        "BIZPULSE_RUNTIME_ENVIRONMENT": "cloud",
    }
    environment = [
        {"name": name, "value": value} for name, value in values.items()
    ]
    environment.extend(
        {"name": name, "secretRef": secret}
        for name, secret in {
            "BIZPULSE_DATABASE_URL": "database-url",
            "BIZPULSE_BLOB_CONNECTION_STRING": "blob-connection-string",
            "BIZPULSE_OPERATOR_PASSWORD_HASH": "operator-password-hash",
            "BIZPULSE_SESSION_PEPPER": "session-pepper",
        }.items()
    )
    projection = {
        "location": "Central US",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {registry_identity: {}},
        },
        "properties": {
            "template": {
                "revisionSuffix": str(target["rollback_revision"]).rsplit("--", 1)[1],
                "containers": [
                    {
                        "name": "bizpulse",
                        "image": target["rollback_image"],
                        "env": environment,
                        "probes": [
                            {
                                "type": "Liveness",
                                "httpGet": {
                                    "path": "/health/live",
                                    "port": 8000,
                                    "scheme": "HTTP",
                                },
                                "initialDelaySeconds": 15,
                                "periodSeconds": 30,
                                "timeoutSeconds": 5,
                                "failureThreshold": 3,
                            },
                            {
                                "type": "Readiness",
                                "httpGet": {
                                    "path": "/health/ready",
                                    "port": 8000,
                                    "scheme": "HTTP",
                                },
                                "initialDelaySeconds": 10,
                                "periodSeconds": 10,
                                "timeoutSeconds": 5,
                                "failureThreshold": 3,
                            },
                        ],
                        "resources": {"cpu": 0.5, "memory": "1Gi"},
                    }
                ],
                "scale": {"minReplicas": 1, "maxReplicas": 1},
            }
        },
    }
    configuration = {
        "activeRevisionsMode": "Single",
        "ingress": {
            "external": True,
            "fqdn": "newcaostone-demo-app.synthetic.azurecontainerapps.io",
            "traffic": [{"latestRevision": True, "weight": 100}],
        },
        "registries": [
            {
                "server": f"{target['registry_name']}.azurecr.io",
                "identity": registry_identity,
            }
        ],
    }
    return projection, configuration


OPERATIONS_AUTHORITY = {
    "migration_job": {
        "schema_version": "newcaostone.admin-ai-migration-job.v1",
        "safe_projection": _safe_migration_job_projection(
            image=str(TASK10_AZURE_TARGET["rollback_image"])
        ),
        "approved_execution_image": (
            f"{TASK10_AZURE_TARGET['registry_name']}.azurecr.io/"
            f"bizpulse@{IMAGE_DIGEST}"
        ),
    },
    "task10_request": _task10_successor_request(),
}
RECEIPT_PATH = ".tmp/ADMIN_AI_RELEASE_RECEIPT_2026-08-18.json"


def _baseline(*, phase: str = "legacy_only") -> dict[str, object]:
    return {
        "observed_at": "2026-08-18T15:55:00Z",
        "observation_sha256": BASELINE_SHA256,
        "required_azure_reads": 12,
        "health_state": "Healthy",
        "ready": True,
        "revision": str(
            CURRENT_ADMIN_AI_SUCCESSOR_TARGET["rollback_revision"]
        ),
        "image_digest": str(
            CURRENT_ADMIN_AI_SUCCESSOR_TARGET["rollback_image"]
        ).rsplit("@", maxsplit=1)[-1],
        "traffic_weight": 100,
        "operator_ai_enabled": False,
        "demo_ai_enabled": False,
        "role_assignment_phase": phase,
        "database_revision": "0014_import_base_lineage",
    }


def _authority() -> dict[str, object]:
    return {
        "path": "release/current_authority.json",
        "sha256": AUTHORITY_SHA256,
        "evidence_sha256": AUTHORITY_EVIDENCE_SHA256,
        "observed_at": "2026-08-18T15:55:00Z",
        "expires_at": "2026-08-18T17:00:00Z",
    }


def _package(
    *,
    receipt_path: str = RECEIPT_PATH,
    operations_authority: dict[str, object] | None = None,
    baseline: dict[str, object] | None = None,
) -> dict[str, object]:
    return build_package(
        source_sha=SOURCE_SHA,
        source_tree=SOURCE_TREE,
        image_digest=IMAGE_DIGEST,
        image_platform="linux/amd64",
        image_input_sha256=IMAGE_INPUT_SHA256,
        candidate_artifact=CANDIDATE_ARTIFACT,
        baseline=_baseline() if baseline is None else baseline,
        authority=_authority(),
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        receipt_path=receipt_path,
        retired_package_sha256=("a" * 64, "b" * 64),
        operations_factory={
            "factory": "scripts.admin_ai_release_operations:create_operations",
            "source_path": "scripts/admin_ai_release_operations.py",
            "source_sha256": "c" * 64,
        },
        build_context_manifest=BUILD_CONTEXT_MANIFEST,
        runtime_tool_manifest=RUNTIME_TOOL_MANIFEST,
        runtime_dependency_manifest=RUNTIME_DEPENDENCY_MANIFEST,
        operations_authority=(
            OPERATIONS_AUTHORITY
            if operations_authority is None
            else operations_authority
        ),
    )


def _hosted_result() -> dict[str, object]:
    return {
        "revision": "newcaostone-demo-app--admin-ai-1234567",
        "admin_entry": {
            "status": "protected",
            "summary_status": "ready",
            "request_id": "request-admin-entry-1",
        },
        "operator_turn": {
            "status": "completed",
            "request_id": "request-operator-turn-1",
            "credential_fingerprint": FINGERPRINT,
            "credential_binding_id": BINDING_ID,
            "credential_control_revision": 2,
        },
        "demo_turn": {
            "status": "completed",
            "request_id": "request-demo-turn-1",
            "credential_fingerprint": FINGERPRINT,
            "credential_binding_id": BINDING_ID,
            "credential_control_revision": 3,
            "admin_denied": True,
            "admin_cache_control": "private, no-store",
            "admin_vary": "Cookie",
        },
        "channel_switches": {
            "status": "completed",
            "operator_independent": True,
            "demo_independent": True,
            "final_operator_enabled": True,
            "final_demo_enabled": True,
        },
        "invalid_candidate_rollback": {
            "status": "rejected",
            "safe_code": "ADMIN_AI_KEY_REJECTED",
            "prior_fingerprint": FINGERPRINT,
            "resulting_fingerprint": FINGERPRINT,
            "prior_operator_enabled": True,
            "resulting_operator_enabled": True,
            "prior_demo_enabled": True,
            "resulting_demo_enabled": True,
        },
        "secret_scan_matches": 0,
        "audit_evidence": {
            "event_count": 8,
            "secret_scan_matches": 0,
            "evidence_sha256": "6" * 64,
        },
    }


def _run_once(
    package: dict[str, object],
    operations: object,
    *,
    approved_sha256: str,
    key_reader,
    now: datetime = NOW,
):
    return run_once(
        package,
        operations,
        approved_sha256=approved_sha256,
        key_reader=key_reader,
        now=now,
        repository_reader=lambda: deepcopy(package["repository"]),
        authority_reader=lambda _now: deepcopy(package["authority_binding"]),
        artifact_reader=lambda: deepcopy(CANDIDATE_ARTIFACT),
    )


def test_package_binds_exact_source_image_baseline_and_no_secret() -> None:
    package = _package()

    assert package["schema_version"] == "newcaostone.admin-ai-release.v1"
    assert package["repository"] == {
        "source_sha": SOURCE_SHA,
        "source_tree": SOURCE_TREE,
        "tracked_tree_clean": True,
        "build_context_manifest": BUILD_CONTEXT_MANIFEST,
        "runtime_tool_manifest": RUNTIME_TOOL_MANIFEST,
        "runtime_dependency_manifest": RUNTIME_DEPENDENCY_MANIFEST,
    }
    assert package["candidate"] == {
        "image_digest": IMAGE_DIGEST,
        "platform": "linux/amd64",
        "source_sha": SOURCE_SHA,
        "source_tree": SOURCE_TREE,
        "image_input_sha256": IMAGE_INPUT_SHA256,
        "build_context_sha256": BUILD_CONTEXT_MANIFEST["sha256"],
        "artifact_format": "oci-archive",
        "artifact_path": CANDIDATE_ARTIFACT["artifact_path"],
        "artifact_sha256": ARTIFACT_SHA256,
        "oci_reference": f"candidate-{SOURCE_SHA[:12]}",
        "runtime_user": "bizpulse",
    }
    assert package["azure_baseline"]["observed_at"] is not None
    assert package["authority_binding"] == _authority()
    assert package["execution_contract"]["attempts"] == 1
    assert package["execution_contract"]["required_azure_reads"] == 12
    assert package["execution_contract"]["rbac_migration_action"] == (
        "reconcile_admin_ai_secret_access"
    )
    assert package["execution_contract"]["receipt_path"] == RECEIPT_PATH
    assert package["operations_factory"]["source_sha256"] == "c" * 64
    assert package["operations_authority"] == OPERATIONS_AUTHORITY
    assert "api_key" not in json.dumps(package).lower()


def test_package_binds_exact_supported_current_database_revision() -> None:
    baseline = _baseline()
    baseline["database_revision"] = "0014_import_base_lineage"

    package = build_package(
        source_sha=SOURCE_SHA,
        source_tree=SOURCE_TREE,
        image_digest=IMAGE_DIGEST,
        image_platform="linux/amd64",
        image_input_sha256=IMAGE_INPUT_SHA256,
        candidate_artifact=CANDIDATE_ARTIFACT,
        baseline=baseline,
        authority=_authority(),
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        receipt_path=RECEIPT_PATH,
        retired_package_sha256=[],
        operations_factory={
            "factory": "scripts.admin_ai_release_operations:create_operations",
            "source_path": "scripts/admin_ai_release_operations.py",
            "source_sha256": "c" * 64,
        },
        build_context_manifest=BUILD_CONTEXT_MANIFEST,
        runtime_tool_manifest=RUNTIME_TOOL_MANIFEST,
        runtime_dependency_manifest=RUNTIME_DEPENDENCY_MANIFEST,
        operations_authority=OPERATIONS_AUTHORITY,
    )

    assert package["azure_baseline"]["database_revision"] == (
        "0014_import_base_lineage"
    )


@pytest.mark.parametrize(
    "database_revision",
    (
        "0008_ai_budget_ledger",
        "0013_workspace_preferences",
        "0017_ai_turn_credential_binding",
    ),
)
def test_package_rejects_database_head_outside_fresh_pre_migration_set(
    database_revision: str,
) -> None:
    baseline = _baseline()
    baseline["database_revision"] = database_revision

    with pytest.raises(
        AdminAIReleasePackageInvalid,
        match="azure_baseline_database_revision_invalid",
    ):
        build_package(
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            image_digest=IMAGE_DIGEST,
            image_platform="linux/amd64",
            image_input_sha256=IMAGE_INPUT_SHA256,
            candidate_artifact=CANDIDATE_ARTIFACT,
            baseline=baseline,
            authority=_authority(),
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=24),
            receipt_path=RECEIPT_PATH,
            retired_package_sha256=[],
            operations_factory={
                "factory": "scripts.admin_ai_release_operations:create_operations",
                "source_path": "scripts/admin_ai_release_operations.py",
                "source_sha256": "c" * 64,
            },
            build_context_manifest=BUILD_CONTEXT_MANIFEST,
            runtime_tool_manifest=RUNTIME_TOOL_MANIFEST,
            runtime_dependency_manifest=RUNTIME_DEPENDENCY_MANIFEST,
            operations_authority=OPERATIONS_AUTHORITY,
        )


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("source_sha", "short", "source_sha_invalid"),
        ("source_tree", "g" * 40, "source_tree_invalid"),
        ("image_digest", "3" * 64, "image_digest_invalid"),
        ("image_platform", "linux/arm64", "image_platform_invalid"),
    ],
)
def test_package_refuses_non_exact_source_or_linux_amd64_image(
    field: str,
    value: str,
    code: str,
) -> None:
    arguments = {
        "source_sha": SOURCE_SHA,
        "source_tree": SOURCE_TREE,
        "image_digest": IMAGE_DIGEST,
        "image_platform": "linux/amd64",
        "image_input_sha256": IMAGE_INPUT_SHA256,
        "candidate_artifact": CANDIDATE_ARTIFACT,
        "baseline": _baseline(),
        "authority": _authority(),
        "issued_at": NOW,
        "expires_at": NOW + timedelta(hours=24),
        "receipt_path": RECEIPT_PATH,
        "retired_package_sha256": (),
        "operations_factory": {
            "factory": "scripts.admin_ai_release_operations:create_operations",
            "source_path": "scripts/admin_ai_release_operations.py",
            "source_sha256": "c" * 64,
        },
        "build_context_manifest": BUILD_CONTEXT_MANIFEST,
        "runtime_tool_manifest": RUNTIME_TOOL_MANIFEST,
        "runtime_dependency_manifest": RUNTIME_DEPENDENCY_MANIFEST,
        "operations_authority": OPERATIONS_AUTHORITY,
    }
    arguments[field] = value

    with pytest.raises(AdminAIReleasePackageInvalid, match=code):
        build_package(**arguments)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ({"required_azure_reads": 11}, "azure_read_contract_invalid"),
        ({"health_state": "Degraded"}, "azure_baseline_not_healthy"),
        ({"ready": False}, "azure_baseline_not_healthy"),
        ({"traffic_weight": 99}, "azure_baseline_not_current"),
        ({"operator_ai_enabled": True}, "azure_baseline_ai_not_disabled"),
        ({"demo_ai_enabled": True}, "azure_baseline_ai_not_disabled"),
        ({"role_assignment_phase": "legacy_plus_officer"}, "rbac_phase_invalid"),
    ],
)
def test_package_refuses_unsafe_or_old_azure_baseline_contract(
    mutation: dict[str, object],
    code: str,
) -> None:
    baseline = _baseline()
    baseline.update(mutation)

    with pytest.raises(AdminAIReleasePackageInvalid, match=code):
        build_package(
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            image_digest=IMAGE_DIGEST,
            image_platform="linux/amd64",
            image_input_sha256=IMAGE_INPUT_SHA256,
            candidate_artifact=CANDIDATE_ARTIFACT,
            baseline=baseline,
            authority=_authority(),
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=24),
            receipt_path=RECEIPT_PATH,
            retired_package_sha256=(),
            operations_factory={
                "factory": "scripts.admin_ai_release_operations:create_operations",
                "source_path": "scripts/admin_ai_release_operations.py",
                "source_sha256": "c" * 64,
            },
            build_context_manifest=BUILD_CONTEXT_MANIFEST,
            runtime_tool_manifest=RUNTIME_TOOL_MANIFEST,
            runtime_dependency_manifest=RUNTIME_DEPENDENCY_MANIFEST,
            operations_authority=OPERATIONS_AUTHORITY,
        )


def test_package_refuses_stale_observation_authority_and_non_24_hour_expiry() -> None:
    stale_baseline = _baseline()
    stale_baseline["observed_at"] = "2026-08-18T14:00:00Z"
    stale_authority = _authority()
    stale_authority["expires_at"] = "2026-08-18T15:59:59Z"

    for baseline, authority, expires_at, code in (
        (
            stale_baseline,
            _authority(),
            NOW + timedelta(hours=24),
            "azure_baseline_stale",
        ),
        (
            _baseline(),
            stale_authority,
            NOW + timedelta(hours=24),
            "authority_stale",
        ),
        (
            _baseline(),
            _authority(),
            NOW + timedelta(hours=23),
            "package_expiry_invalid",
        ),
    ):
        with pytest.raises(AdminAIReleasePackageInvalid, match=code):
            build_package(
                source_sha=SOURCE_SHA,
                source_tree=SOURCE_TREE,
                image_digest=IMAGE_DIGEST,
                image_platform="linux/amd64",
                image_input_sha256=IMAGE_INPUT_SHA256,
                candidate_artifact=CANDIDATE_ARTIFACT,
                baseline=baseline,
                authority=authority,
                issued_at=NOW,
                expires_at=expires_at,
                receipt_path=RECEIPT_PATH,
                retired_package_sha256=(),
                operations_factory={
                    "factory": "scripts.admin_ai_release_operations:create_operations",
                    "source_path": "scripts/admin_ai_release_operations.py",
                    "source_sha256": "c" * 64,
                },
                build_context_manifest=BUILD_CONTEXT_MANIFEST,
                runtime_tool_manifest=RUNTIME_TOOL_MANIFEST,
                runtime_dependency_manifest=RUNTIME_DEPENDENCY_MANIFEST,
                operations_authority=OPERATIONS_AUTHORITY,
            )


def test_capture_repository_refuses_dirty_tracked_tree() -> None:
    responses = iter(
        (
            subprocess.CompletedProcess([], 0, stdout=f"{SOURCE_SHA}\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout=f"{SOURCE_TREE}\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout=" M src/config.py\n", stderr=""),
        )
    )

    with pytest.raises(AdminAIReleasePackageInvalid, match="repository_dirty"):
        capture_repository(runner=lambda *_args, **_kwargs: next(responses))

    clean_responses = iter(
        (
            subprocess.CompletedProcess([], 0, stdout=f"{SOURCE_SHA}\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout=f"{SOURCE_TREE}\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        )
    )
    assert capture_repository(
        runner=lambda *_args, **_kwargs: next(clean_responses),
        manifest_reader=lambda _sha, _root: BUILD_CONTEXT_MANIFEST,
        runtime_manifest_reader=lambda _sha, _root: RUNTIME_TOOL_MANIFEST,
    ) == {
        "source_sha": SOURCE_SHA,
        "source_tree": SOURCE_TREE,
        "tracked_tree_clean": True,
        "build_context_manifest": BUILD_CONTEXT_MANIFEST,
        "runtime_tool_manifest": RUNTIME_TOOL_MANIFEST,
    }


@pytest.mark.parametrize(
    "untracked_path",
    (
        "api/untracked_release_hook.py",
        "src/untracked_release_hook.py",
        "frontend/untracked_release_hook.mjs",
        "alembic/untracked_release_hook.py",
    ),
)
def test_capture_repository_refuses_every_untracked_docker_context_file(
    untracked_path: str,
) -> None:
    responses = iter(
        (
            subprocess.CompletedProcess([], 0, stdout=f"{SOURCE_SHA}\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout=f"{SOURCE_TREE}\n", stderr=""),
            subprocess.CompletedProcess(
                [],
                0,
                stdout=f"?? {untracked_path}\n",
                stderr="",
            ),
        )
    )
    observed_commands: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object):
        observed_commands.append(command)
        return next(responses)

    with pytest.raises(AdminAIReleasePackageInvalid, match="repository_dirty"):
        capture_repository(runner=runner)

    assert observed_commands[-1][0:3] == ["git", "status", "--porcelain=v1"]
    assert "--untracked-files=all" in observed_commands[-1]
    assert "--" not in observed_commands[-1]


def test_capture_repository_rejects_dirty_release_toolchain_outside_docker_context() -> None:
    observed_commands: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object):
        observed_commands.append(command)
        if command[1:3] == ["rev-parse", "HEAD"]:
            output = SOURCE_SHA
        elif command[1:3] == ["rev-parse", "HEAD^{tree}"]:
            output = SOURCE_TREE
        elif "--" in command:
            output = ""
        else:
            output = " M scripts/run_admin_ai_release.py"
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    with pytest.raises(AdminAIReleasePackageInvalid, match="repository_dirty"):
        capture_repository(
            runner=runner,
            manifest_reader=lambda _sha, _root: BUILD_CONTEXT_MANIFEST,
        )

    status_command = observed_commands[-1]
    assert status_command[:4] == [
        "git",
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    ]
    assert "--" not in status_command


def test_runtime_toolchain_manifest_covers_every_transitive_release_module() -> None:
    assert set(RUNTIME_TOOL_PATHS) == {
        "requirements.txt",
        "requirements-dev.txt",
        "infra/ai_enablement.bicep",
        "infra/ai_secret_write.bicep",
        "infra/modules/app.bicep",
        "scripts/admin_ai_runtime_dependencies.json",
        "scripts/admin_ai_current_successor.py",
        "scripts/admin_ai_oci_artifact.py",
        "scripts/admin_ai_exact_runtime.py",
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
    }


def test_package_and_candidate_bind_one_exact_build_context_manifest() -> None:
    package = _package()

    assert package["repository"]["build_context_manifest"]["sha256"] == (
        package["candidate"]["build_context_sha256"]
    )
    assert len(package["repository"]["build_context_manifest"]["entries"]) > 0
    assert package["candidate"]["artifact_format"] == "oci-archive"
    assert package["candidate"]["artifact_sha256"] == ARTIFACT_SHA256
    assert package["candidate"]["artifact_path"].endswith(".oci.tar")
    assert package["repository"]["runtime_dependency_manifest"]["sha256"] == (
        RUNTIME_DEPENDENCY_MANIFEST["sha256"]
    )


def test_package_rejects_any_runtime_dependency_manifest_drift() -> None:
    package = _package()
    package["repository"]["runtime_dependency_manifest"]["distributions"][0][
        "version"
    ] = "modified"

    with pytest.raises(
        AdminAIReleasePackageInvalid,
        match="runtime_dependency_manifest_invalid",
    ):
        validate_package(package, now=NOW)


def test_package_refuses_task10_operations_authority_from_another_source() -> None:
    authority = deepcopy(OPERATIONS_AUTHORITY)
    authority["task10_request"]["repository"]["head_sha"] = "f" * 40

    with pytest.raises(AdminAIReleasePackageInvalid, match="operations_authority_drift"):
        build_package(
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            image_digest=IMAGE_DIGEST,
            image_platform="linux/amd64",
            image_input_sha256=IMAGE_INPUT_SHA256,
            candidate_artifact=CANDIDATE_ARTIFACT,
            baseline=_baseline(),
            authority=_authority(),
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=24),
            receipt_path=RECEIPT_PATH,
            retired_package_sha256=(),
            operations_factory={
                "factory": "scripts.admin_ai_release_operations:create_operations",
                "source_path": "scripts/admin_ai_release_operations.py",
                "source_sha256": "c" * 64,
            },
            build_context_manifest=BUILD_CONTEXT_MANIFEST,
            runtime_tool_manifest=RUNTIME_TOOL_MANIFEST,
            runtime_dependency_manifest=RUNTIME_DEPENDENCY_MANIFEST,
            operations_authority=authority,
        )


def test_package_refuses_task10_operations_authority_from_another_baseline() -> None:
    authority = deepcopy(OPERATIONS_AUTHORITY)
    authority["task10_request"]["prepackage_gate"][
        "role_assignment_state"
    ] = "officer_only"

    with pytest.raises(AdminAIReleasePackageInvalid, match="operations_authority_drift"):
        build_package(
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            image_digest=IMAGE_DIGEST,
            image_platform="linux/amd64",
            image_input_sha256=IMAGE_INPUT_SHA256,
            candidate_artifact=CANDIDATE_ARTIFACT,
            baseline=_baseline(),
            authority=_authority(),
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=24),
            receipt_path=RECEIPT_PATH,
            retired_package_sha256=(),
            operations_factory={
                "factory": "scripts.admin_ai_release_operations:create_operations",
                "source_path": "scripts/admin_ai_release_operations.py",
                "source_sha256": "c" * 64,
            },
            build_context_manifest=BUILD_CONTEXT_MANIFEST,
            runtime_tool_manifest=RUNTIME_TOOL_MANIFEST,
            runtime_dependency_manifest=RUNTIME_DEPENDENCY_MANIFEST,
            operations_authority=authority,
        )


def test_package_refuses_unallowlisted_migration_job_target() -> None:
    authority = deepcopy(OPERATIONS_AUTHORITY)
    authority["migration_job"]["safe_projection"]["name"] = (
        "newcaostone-demo-seed"
    )

    with pytest.raises(
        AdminAIReleasePackageInvalid,
        match="operations_authority_invalid",
    ):
        _package(operations_authority=authority)


def test_migration_job_authority_read_drops_ambient_credentials() -> None:
    observed_environment: dict[str, str] = {}

    def runner(command, **kwargs):
        observed_environment.update(kwargs["env"])
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                _safe_migration_job_projection(
                    image=str(TASK10_AZURE_TARGET["rollback_image"])
                )
            ),
            stderr="",
        )

    result = collect_migration_job_authority(
        _task10_request(),
        candidate_image=(
            f"{TASK10_AZURE_TARGET['registry_name']}.azurecr.io/"
            f"bizpulse@{IMAGE_DIGEST}"
        ),
        runner=runner,
        environment={
            "PATH": "/safe/bin",
            "LANG": "C.UTF-8",
            "OPENAI_API_KEY": "must-not-cross-process",
            "OPERATOR_PASSWORD": "must-not-cross-process",
        },
    )

    assert observed_environment == {"PATH": "/safe/bin", "LANG": "C.UTF-8"}
    assert result == OPERATIONS_AUTHORITY["migration_job"]


def test_migration_job_authority_binds_execution_image_without_authorizing_update() -> None:
    candidate_image = (
        f"{TASK10_AZURE_TARGET['registry_name']}.azurecr.io/"
        f"bizpulse@{IMAGE_DIGEST}"
    )

    result = collect_migration_job_authority(
        _task10_request(),
        candidate_image=candidate_image,
        runner=lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                _safe_migration_job_projection(
                    image=str(TASK10_AZURE_TARGET["rollback_image"])
                )
            ),
            stderr="",
        ),
    )

    assert result["approved_execution_image"] == candidate_image
    assert "allowed_image_update" not in result


def test_migration_job_authority_never_reads_unknown_plaintext_env_values() -> None:
    sentinel = "ambient-plaintext-must-never-be-projected"
    observed_query = ""

    def runner(command, **_kwargs):
        nonlocal observed_query
        observed_query = command[command.index("--query") + 1]
        projection = _safe_migration_job_projection(
            image=str(TASK10_AZURE_TARGET["rollback_image"])
        )
        projection["containers"][0]["env"].append(
            {"name": "OPENAI_API_KEY", "secretRef": None}
        )
        output = json.dumps(projection)
        assert sentinel not in output
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    with pytest.raises(
        AdminAIReleasePackageInvalid,
        match="operations_authority_invalid",
    ):
        collect_migration_job_authority(
            _task10_request(),
            candidate_image=(
                f"{TASK10_AZURE_TARGET['registry_name']}.azurecr.io/"
                f"bizpulse@{IMAGE_DIGEST}"
            ),
            runner=runner,
        )

    assert "env:env[].{name:name,secretRef:secretRef}" in observed_query
    assert "env[].{name:name,value:value" not in observed_query
    assert sentinel not in observed_query


@pytest.mark.parametrize(
    "mutation",
    [
        "resource_id",
        "command",
        "retry",
        "parallelism",
        "database",
        "registry",
        "resources",
    ],
)
def test_live_backend_rejects_drifted_migration_job_before_start(
    mutation: str,
) -> None:
    from scripts.admin_ai_release_operations import (
        AdminAIReleaseOperationInvalid,
        AzureHostedAdminAIBackend,
    )

    projection = _safe_migration_job_projection(
        image=str(TASK10_AZURE_TARGET["rollback_image"])
    )
    if mutation == "resource_id":
        projection["id"] = str(projection["id"]).replace("prepare", "seed")
    elif mutation == "command":
        projection["containers"][0]["args"] = ["scripts/seed_demo.py"]
    elif mutation == "retry":
        projection["replicaRetryLimit"] = 1
    elif mutation == "parallelism":
        projection["manualTriggerConfig"]["parallelism"] = 2
    elif mutation == "database":
        database_binding = next(
            entry
            for entry in projection["containers"][0]["env"]
            if entry["name"] == "BIZPULSE_DATABASE_URL"
        )
        database_binding["secretRef"] = "other-database"
    elif mutation == "resources":
        projection["containers"][0]["resources"]["cpu"] = 1.0
    else:
        projection["registries"][0]["identity"] = "system"

    backend = AzureHostedAdminAIBackend(
        package=_package(),
        approved_sha256=package_sha256(_package()),
        actions=object(),
    )
    backend._hosted_origin = (
        "https://newcaostone-demo-app.synthetic.azurecontainerapps.io"
    )

    with pytest.raises(
        AdminAIReleaseOperationInvalid,
        match="migration_job_authority_invalid",
    ):
        backend._validate_migration_job_projection(
            projection,
            expected_image=str(TASK10_AZURE_TARGET["rollback_image"]),
        )


def test_package_accepts_exact_strict_task10_operations_authority() -> None:
    package = _package()

    state = package["operations_authority"]["task10_request"][
        "execution_contract"
    ]["states"]["reconcile_ai_vault_identity_role_diagnostics"]
    assert state["expected_evidence"]["rbac_authorization"] is True


def test_admin_package_rejects_historical_r19_operations_authority() -> None:
    authority = deepcopy(OPERATIONS_AUTHORITY)
    authority["task10_request"] = _task10_request()
    historical_baseline = _baseline()
    historical_baseline["revision"] = TASK10_AZURE_TARGET[
        "rollback_revision"
    ]

    with pytest.raises(
        AdminAIReleasePackageInvalid,
        match="operations_authority_invalid",
    ):
        _package(
            operations_authority=authority,
            baseline=historical_baseline,
        )


def test_fresh_task10_successor_request_is_accepted_end_to_end(
    tmp_path: Path,
) -> None:
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    (tmp_path / "requirements.txt").write_text("# exact lock\n")
    request = build_fresh_task10_authority_request(
        repository={
            "source_sha": SOURCE_SHA,
            "source_tree": SOURCE_TREE,
            "tracked_tree_clean": True,
        },
        candidate_artifact=CANDIDATE_ARTIFACT,
        generated_at=NOW,
        role_assignment_state="legacy_only",
        artifact_id="11111111-1111-4111-8111-111111111111",
        project_root=tmp_path,
        control_sha256=_task10_request()["control_sha256"],
        prior_attempts=_task10_request()["prior_attempts"],
    )
    authority = deepcopy(OPERATIONS_AUTHORITY)
    authority["task10_request"] = request

    successor_baseline = _baseline()
    successor_baseline["revision"] = (
        "newcaostone-demo-app--recover-b-9c35ae6a-2bf7086"
    )
    package = _package(
        operations_authority=authority,
        baseline=successor_baseline,
    )

    assert package["operations_authority"]["task10_request"] == request
    assert request["artifacts"]["package_path"].startswith(
        ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_TASK12_"
    )
    assert request["azure_target"]["rollback_revision"] == (
        "newcaostone-demo-app--recover-b-9c35ae6a-2bf7086"
    )
    assert request["azure_target"]["rollback_image"] == (
        "sellernorthbpacr.azurecr.io/bizpulse@sha256:"
        "2bf7086bccec9cdb8fb6a9c2c5383909207b021344d8dfee692437829bd87425"
    )
    assert request["prepackage_gate"]["rollback_registry_tag"] == (
        "ai-962a4fa43804-9c35ae6a"
    )
    assert request["prepackage_gate"]["rollback_identity_state"] == (
        "registry_only"
    )
    assert "r19" in request["prior_attempts"]


def test_fresh_task10_successor_requires_r19_terminal_provenance(
    tmp_path: Path,
) -> None:
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    (tmp_path / "requirements.txt").write_text("# exact lock\n")
    prior_attempts = deepcopy(_task10_request()["prior_attempts"])
    prior_attempts.pop("r19")

    with pytest.raises(
        AdminAIReleasePackageInvalid,
        match="operations_authority_invalid",
    ):
        build_fresh_task10_authority_request(
            repository={
                "source_sha": SOURCE_SHA,
                "source_tree": SOURCE_TREE,
                "tracked_tree_clean": True,
            },
            candidate_artifact=CANDIDATE_ARTIFACT,
            generated_at=NOW,
            role_assignment_state="legacy_only",
            artifact_id="11111111-1111-4111-8111-111111111111",
            project_root=tmp_path,
            control_sha256=_task10_request()["control_sha256"],
            prior_attempts=prior_attempts,
        )


def test_task10_successor_rejects_the_pre_r19_rollback_target() -> None:
    authority = deepcopy(OPERATIONS_AUTHORITY)
    request = authority["task10_request"]
    old_revision = "newcaostone-demo-app--recover-b-22767486-20f39c8"
    old_image = (
        "sellernorthbpacr.azurecr.io/bizpulse@sha256:"
        "20f39c82b499c98ba10c68129531a46b4fb7fe3a6c4e91a87ddcdff99bfc18c1"
    )
    request["azure_target"]["rollback_revision"] = old_revision
    request["azure_target"]["rollback_image"] = old_image
    request["prepackage_gate"]["rollback_revision"] = old_revision
    request["prepackage_gate"]["rollback_image"] = old_image
    request["prepackage_gate"]["rollback_registry_tag"] = (
        "ai-790b71a7b95e-22767486"
    )

    with pytest.raises(
        AdminAIReleasePackageInvalid,
        match="operations_authority_invalid",
    ):
        _package(operations_authority=authority)


def test_fresh_task10_successor_request_is_owner_only_and_exclusive(
    tmp_path: Path,
) -> None:
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    (tmp_path / "requirements.txt").write_text("# exact lock\n")
    artifact_id = "11111111-1111-4111-8111-111111111111"
    output = (
        tmp_path
        / ".tmp"
        / f"LAUNCH_AUTHORIZATION_AI_ENABLEMENT_TASK12_{artifact_id}.json"
    )
    output.parent.mkdir()
    kwargs = {
        "output": output,
        "repository": {
            "source_sha": SOURCE_SHA,
            "source_tree": SOURCE_TREE,
            "tracked_tree_clean": True,
        },
        "candidate_artifact": CANDIDATE_ARTIFACT,
        "generated_at": NOW,
        "role_assignment_state": "legacy_only",
        "artifact_id": artifact_id,
        "project_root": tmp_path,
        "output_root": tmp_path,
        "control_sha256": _task10_request()["control_sha256"],
        "prior_attempts": _task10_request()["prior_attempts"],
    }

    request = write_fresh_task10_authority_request(**kwargs)

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(output.read_text()) == request
    with pytest.raises(
        AdminAIReleasePackageInvalid,
        match="operations_authority_invalid",
    ):
        write_fresh_task10_authority_request(**kwargs)


@pytest.mark.parametrize("mutation", ["absent", "false", "partial", "extra"])
def test_package_rejects_nonexact_task10_execution_contract(mutation: str) -> None:
    authority = deepcopy(OPERATIONS_AUTHORITY)
    contract = authority["task10_request"]["execution_contract"]
    if mutation == "absent":
        del authority["task10_request"]["execution_contract"]
    elif mutation == "false":
        contract["states"]["reconcile_ai_vault_identity_role_diagnostics"][
            "expected_evidence"
        ]["rbac_authorization"] = False
    elif mutation == "partial":
        authority["task10_request"]["execution_contract"] = {"states": {}}
    else:
        contract["unexpected"] = True

    with pytest.raises(
        AdminAIReleasePackageInvalid,
        match="operations_authority_invalid",
    ):
        _package(operations_authority=authority)


def test_committed_admin_ai_operations_adapter_exists() -> None:
    project_root = Path(__file__).resolve().parents[2]

    assert (project_root / "scripts/admin_ai_release_operations.py").is_file()


def test_real_operations_adapter_implements_fixed_protocol_without_secret_retention() -> None:
    from scripts.admin_ai_release_operations import create_operations

    class Backend:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def execute(
            self,
            state: str,
            *,
            secret_value: str | None,
            context: dict[str, object],
        ) -> dict[str, object]:
            del context
            self.calls.append((state, secret_value))
            return _Operations().run(
                state,
                secret_value=secret_value,
                context={},
            )

        def reconcile_admin_ai_secret_access(
            self,
            *,
            context: dict[str, object],
        ) -> dict[str, object]:
            del context
            return _Operations().reconcile_admin_ai_secret_access(context={})

    package = _package()
    backend = Backend()
    operations = create_operations(
        package=package,
        approved_sha256=package_sha256(package),
        backend=backend,
    )
    context: dict[str, object] = {}
    secret = "adapter-secret-sentinel"

    for state in ADMIN_AI_RELEASE_STATES:
        if state == "deploy_admin_ai_capability":
            operations.reconcile_admin_ai_secret_access(context=context)
        result = operations.run(
            state,
            secret_value=secret if state == "rotate_key_through_admin" else None,
            context=context,
        )
        if state == "rotate_key_through_admin":
            context["fingerprint"] = result["credential_fingerprint"]
        elif state == "verify_operator_ai":
            context["credential_binding_id"] = result["credential_binding_id"]

    assert [state for state, _value in backend.calls] == list(
        ADMIN_AI_RELEASE_STATES
    )
    assert [state for state, value in backend.calls if value is not None] == [
        "rotate_key_through_admin"
    ]
    assert secret not in repr(operations)
    assert secret not in json.dumps(vars(operations), default=repr)


def test_controller_and_real_operations_wrapper_share_one_rbac_deploy_order(
    tmp_path: Path,
) -> None:
    from scripts.admin_ai_release_operations import create_operations

    delegate = _Operations()

    class Backend:
        def execute(self, state: str, **kwargs) -> dict[str, object]:
            return delegate.run(state, **kwargs)

        def reconcile_admin_ai_secret_access(
            self, *, context: dict[str, object]
        ) -> dict[str, object]:
            return delegate.reconcile_admin_ai_secret_access(context=context)

    package = _package(receipt_path=str(tmp_path / "receipt.json"))
    operations = create_operations(
        package=package,
        approved_sha256=package_sha256(package),
        backend=Backend(),
    )

    receipt = _run_once(
        package,
        operations,
        approved_sha256=package_sha256(package),
        key_reader=lambda: "candidate-secret-sentinel",
    )

    assert receipt["status"] == "completed"
    assert receipt["completed_states"] == list(ADMIN_AI_RELEASE_STATES)
    assert len(delegate.migration_calls) == 1
    assert delegate.calls[2][0] == "deploy_admin_ai_capability"


def test_real_operations_adapter_rejects_out_of_order_or_misplaced_secret() -> None:
    from scripts.admin_ai_release_operations import (
        AdminAIReleaseOperationInvalid,
        create_operations,
    )

    package = _package()
    operations = create_operations(
        package=package,
        approved_sha256=package_sha256(package),
        backend=object(),
    )

    with pytest.raises(AdminAIReleaseOperationInvalid, match="state_order_invalid"):
        operations.run(
            "publish_candidate_image",
            secret_value=None,
            context={},
        )
    with pytest.raises(AdminAIReleaseOperationInvalid, match="secret_boundary_invalid"):
        operations.run(
            "readonly_revalidation",
            secret_value="must-not-be-retained",
            context={},
        )


def test_live_deploy_uses_real_reconciliation_before_one_migration_start() -> None:
    from scripts.admin_ai_release_operations import AzureHostedAdminAIBackend
    from scripts.azure_ai_enablement_actions import AzureAIEnablementActions
    from scripts.azure_arm_lro import ARMResponse

    package = _package()
    approved_sha256 = package_sha256(package)
    patch_bodies: list[dict[str, object]] = []
    job_calls: list[dict[str, object]] = []

    def arm_requester(method, _url, body):
        assert method == "PATCH"
        assert isinstance(body, dict)
        patch_bodies.append(deepcopy(body))
        target = TASK10_AZURE_TARGET
        return ARMResponse(
            status_code=200,
            headers={},
            payload={
                "id": (
                    f"/subscriptions/{target['subscription_id']}/resourceGroups/"
                    f"{target['resource_group']}/providers/Microsoft.App/"
                    f"containerApps/{target['app_name']}"
                ),
                "provisioningState": "Succeeded",
            },
        )

    def azure_runner(command, **_kwargs):
        target = TASK10_AZURE_TARGET
        if command[:3] == ["az", "containerapp", "show"]:
            assert len(patch_bodies) == 1
            patch = deepcopy(patch_bodies[0])
            template = patch["properties"]["template"]
            suffix = template["revisionSuffix"]
            revision = f"{target['app_name']}--{suffix}"
            raw_template = deepcopy(template)
            raw_template.update(
                {
                    "customMetricsSettings": None,
                    "initContainers": None,
                    "serviceBinds": None,
                    "terminationGracePeriodSeconds": None,
                    "volumes": None,
                }
            )
            raw_template["scale"].update(
                {"cooldownPeriod": 300, "pollingInterval": 30, "rules": None}
            )
            raw_container = raw_template["containers"][0]
            raw_container["imageType"] = "ContainerImage"
            raw_container["resources"]["ephemeralStorage"] = "2Gi"
            payload = {
                "location": patch["location"],
                "identity": patch["identity"],
                "properties": {
                    "latestRevisionName": revision,
                    "latestReadyRevisionName": revision,
                    "provisioningState": "Succeeded",
                    "configuration": actions._immutable_configuration,
                    "template": raw_template,
                },
            }
        elif command[:4] == ["az", "containerapp", "revision", "list"]:
            suffix = patch_bodies[0]["properties"]["template"]["revisionSuffix"]
            payload = [
                {
                    "name": f"{target['app_name']}--{suffix}",
                    "properties": {
                        "active": True,
                        "healthState": "Healthy",
                        "provisioningState": "Provisioned",
                    },
                }
            ]
        elif command[:4] == ["az", "containerapp", "job", "show"]:
            payload = _safe_migration_job_projection(
                image=str(target["rollback_image"])
            )
        else:  # pragma: no cover - exact allowlist assertion
            raise AssertionError(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload),
            stderr="",
        )

    def job_runner(**kwargs):
        job_calls.append(deepcopy(kwargs))
        return "execution-once"

    placeholder = object()
    backend = AzureHostedAdminAIBackend(
        package=package,
        approved_sha256=approved_sha256,
        actions=placeholder,
        runner=azure_runner,
        job_runner=job_runner,
    )
    actions = AzureAIEnablementActions(
        package=backend._authority,
        package_sha256=approved_sha256,
        runner=azure_runner,
        arm_requester=arm_requester,
        monotonic=lambda: 0.0,
        sleeper=lambda _seconds: None,
    )
    projection, configuration = _live_app_projection()
    actions.current_projection = projection
    actions._immutable_configuration = configuration
    backend._actions = actions
    backend._hosted_origin = (
        "https://newcaostone-demo-app.synthetic.azurecontainerapps.io"
    )

    result = backend._deploy_admin_ai_capability(
        secret_value=None,
        context={
            "vault_url": "https://newcaostone-ai-kv.vault.azure.net",
            "managed_identity_client_id": (
                "22222222-2222-4222-8222-222222222222"
            ),
        },
    )

    assert len(patch_bodies) == 1
    assert len(job_calls) == 1
    target = TASK10_AZURE_TARGET
    registry_identity = (
        f"/subscriptions/{target['subscription_id']}/resourceGroups/"
        f"{target['resource_group']}/providers/Microsoft.ManagedIdentity/"
        "userAssignedIdentities/"
        f"{target['existing_registry_identity_name']}"
    )
    ai_identity = (
        f"/subscriptions/{target['subscription_id']}/resourceGroups/"
        f"{target['resource_group']}/providers/Microsoft.ManagedIdentity/"
        f"userAssignedIdentities/{target['identity_name']}"
    )
    assert set(projection["identity"]["userAssignedIdentities"]) == {
        registry_identity
    }
    assert set(patch_bodies[0]["identity"]["userAssignedIdentities"]) == {
        registry_identity,
        ai_identity,
    }
    enabled_environment = {
        item["name"]: item
        for item in patch_bodies[0]["properties"]["template"]["containers"][0][
            "env"
        ]
    }
    assert enabled_environment["BIZPULSE_AI_CHAT_ENABLED"] == {
        "name": "BIZPULSE_AI_CHAT_ENABLED",
        "value": "true",
    }
    assert enabled_environment["BIZPULSE_OPENAI_KEY_VAULT_URL"] == {
        "name": "BIZPULSE_OPENAI_KEY_VAULT_URL",
        "value": "https://newcaostone-ai-kv.vault.azure.net",
    }
    assert enabled_environment["BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME"] == {
        "name": "BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME",
        "value": "openai-api-key",
    }
    assert enabled_environment[
        "BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID"
    ] == {
        "name": "BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID",
        "value": "22222222-2222-4222-8222-222222222222",
    }
    assert result["revision"] == backend._deployed_revision
    assert result["migration"] == "0017_ai_turn_credential_binding"


def test_live_backend_wires_all_azure_and_hosted_boundaries_without_live_calls() -> None:
    import httpx

    from scripts.admin_ai_release_operations import AzureHostedAdminAIBackend

    package = _package()
    task10_result = {
        "operations": {"azure.read.sanitized": 12},
        "evidence": {"secret_values_read": 0},
        "outputs": {
            "role_assignment_state": "legacy_only",
            "secret_values_read": 0,
        },
    }
    projection = {"safe": "projection"}
    package["azure_baseline"]["observation_sha256"] = hashlib.sha256(
        json.dumps(
            {"result": task10_result, "projection": projection},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    calls: list[str] = []

    def authority_reader(_authority, **kwargs):
        calls.append("preflight")
        kwargs["safe_observer"](
            {
                "hosted_url": (
                    "https://newcaostone-demo-app.synthetic.azurecontainerapps.io"
                ),
                "immutable_configuration": {"safe": "configuration"},
            }
        )
        return deepcopy(task10_result), deepcopy(projection)

    class Actions:
        current_projection = None
        _immutable_configuration = None
        _hosted_url = None
        revision_arguments: list[dict[str, object]] = []

        def _apply_revision(self, **kwargs):
            self.revision_arguments.append(deepcopy(kwargs))
            calls.append("deploy-app")
            return f"newcaostone-demo-app--admin-ai-{len(self.revision_arguments)}"

        def _reconcile_revision(self, **_kwargs):
            calls.append("verify-app")
            return {}

        def reconcile_admin_ai_secret_access(self, *, context):
            del context
            calls.append("rbac")
            return {
                "vault_url": "https://newcaostone-ai-kv.vault.azure.net",
                "identity_resource_id": (
                    "/subscriptions/11111111-1111-4111-8111-111111111111/"
                    "resourceGroups/rg-bizpulse-centralus/providers/"
                    "Microsoft.ManagedIdentity/userAssignedIdentities/"
                    "newcaostone-ai-identity"
                ),
                "managed_identity_client_id": (
                    "22222222-2222-4222-8222-222222222222"
                ),
                "assignment_set_sha256": "9" * 64,
            }

    control = {
        "revision": 0,
        "operator_enabled": False,
        "demo_enabled": False,
        "credential": {
            "configured": False,
            "fingerprint": None,
            "verified_at": None,
        },
    }
    operator_turn = "11111111-1111-4111-8111-111111111111"
    demo_turn = "22222222-2222-4222-8222-222222222222"
    binding_id = "d" * 64
    audit_rows: list[dict[str, object]] = []
    response_count = 0

    def response(status: int, payload=None, *, headers=None):
        nonlocal response_count
        response_count += 1
        return httpx.Response(
            status,
            json={} if payload is None else payload,
            headers={
                "X-Request-ID": f"request-{response_count}",
                **({} if headers is None else headers),
            },
        )

    class Client:
        def __init__(self, role: str) -> None:
            self.role = role

        def close(self) -> None:
            calls.append(f"close-{self.role}")

        def get(self, path: str, **kwargs):
            if self.role in {"preflight", "anonymous"}:
                return (
                    response(
                        200,
                        {
                            "status": "ready",
                            "checks": {
                                "migration": (
                                    "0014_import_base_lineage"
                                    if self.role == "preflight"
                                    else "0017_ai_turn_credential_binding"
                                )
                            },
                        },
                    )
                    if path == "/health/ready"
                    else response(303)
                )
            if path == "/admin":
                if self.role == "demo":
                    return response(
                        303,
                        headers={
                            "Cache-Control": "private, no-store",
                            "Vary": "Cookie",
                        },
                    )
                return response(200)
            if path == "/api/v1/admin/summary":
                return response(200, {"ai": {"status": "ready"}})
            if path == "/api/v1/admin/ai":
                return response(200, deepcopy(control))
            if path == "/api/v1/admin/ai/turn-bindings":
                ids = [value for key, value in kwargs.get("params", []) if key == "turn_id"]
                return response(
                    200,
                    {
                        "items": [
                            {
                                "turn_id": turn_id,
                                "actor_kind": (
                                    "operator" if turn_id == operator_turn else "demo"
                                ),
                                "request_id": f"request-{turn_id[:8]}",
                                "credential_binding_id": binding_id,
                                "credential_control_revision": (
                                    2 if turn_id == operator_turn else 3
                                ),
                                "status": "answered",
                            }
                            for turn_id in ids
                        ]
                    },
                )
            if path == "/api/v1/admin/ai/audit-events":
                ids = [
                    value
                    for key, value in kwargs.get("params", [])
                    if key == "request_id"
                ]
                by_request = {item["request_id"]: item for item in audit_rows}
                return response(
                    200,
                    {"items": [deepcopy(by_request[value]) for value in ids]},
                )
            raise AssertionError(path)

        def post(self, path: str, *, json=None, **kwargs):
            del kwargs
            if path == "/api/operator/login":
                return response(201, {"csrf_token": "c" * 32})
            if path == "/api/demo/sessions":
                return response(201, {"csrf_token": "e" * 32, "session": {}})
            if path == "/api/demo/sessions/current/import-demo-data":
                return response(200, {"session": {}})
            if path == "/api/v1/ai-chat/turns":
                return response(
                    201,
                    {
                        "id": operator_turn if self.role == "operator" else demo_turn,
                        "status": "answered",
                    },
                )
            if path == "/api/v1/admin/ai/key-rotations":
                prior_revision = control["revision"]
                if json["candidate_key"] == "known-invalid-sentinel":
                    result = response(422, {"code": "ADMIN_AI_KEY_REJECTED"})
                    audit_rows.append(
                        {
                            "request_id": result.headers["X-Request-ID"],
                            "action": "key.rotate",
                            "result": "failed",
                            "safe_error_code": "ADMIN_AI_KEY_REJECTED",
                            "prior_revision": prior_revision,
                            "resulting_revision": prior_revision,
                            "requested_operator_enabled": None,
                            "requested_demo_enabled": None,
                        }
                    )
                    return result
                control["revision"] += 1
                control["credential"] = {
                    "configured": True,
                    "fingerprint": FINGERPRINT,
                    "verified_at": "2026-08-18T16:00:00Z",
                }
                result = response(
                    200,
                    {
                        "revision": control["revision"],
                        "credential": deepcopy(control["credential"]),
                        "result_code": "ADMIN_AI_KEY_ROTATED",
                    },
                )
                audit_rows.append(
                    {
                        "request_id": result.headers["X-Request-ID"],
                        "action": "key.rotate",
                        "result": "succeeded",
                        "safe_error_code": None,
                        "prior_revision": prior_revision,
                        "resulting_revision": control["revision"],
                        "requested_operator_enabled": None,
                        "requested_demo_enabled": None,
                    }
                )
                return result
            raise AssertionError(path)

        def request(self, method: str, path: str, *, json, **kwargs):
            if method == "POST":
                return self.post(path, json=json, **kwargs)
            del kwargs
            assert method == "PATCH"
            assert path == "/api/v1/admin/ai/channels"
            prior_revision = control["revision"]
            control["revision"] += 1
            control["operator_enabled"] = json["operator_enabled"]
            control["demo_enabled"] = json["demo_enabled"]
            result = response(200, deepcopy(control))
            audit_rows.append(
                {
                    "request_id": result.headers["X-Request-ID"],
                    "action": "channels.update",
                    "result": "succeeded",
                    "safe_error_code": None,
                    "prior_revision": prior_revision,
                    "resulting_revision": control["revision"],
                    "requested_operator_enabled": json["operator_enabled"],
                    "requested_demo_enabled": json["demo_enabled"],
                }
            )
            return result

    clients: list[Client] = []

    def client_factory(**_kwargs):
        role = ("preflight", "anonymous", "operator", "demo")[len(clients)]
        client = Client(role)
        clients.append(client)
        return client

    migration_job_image = str(TASK10_AZURE_TARGET["rollback_image"])

    def runner(command, **_kwargs):
        nonlocal migration_job_image
        if command[:5] == [
            "az",
            "monitor",
            "log-analytics",
            "workspace",
            "show",
        ]:
            output = "33333333-3333-4333-8333-333333333333\n"
        elif command[:5] == ["az", "monitor", "log-analytics", "query", "--workspace"]:
            output = json.dumps(
                [
                    {
                        "Log_s": " ".join(
                            f"request-{index}" for index in range(1, 100)
                        )
                    }
                ]
            )
        elif command[:4] == ["az", "containerapp", "job", "show"]:
            calls.append("migration-job-read")
            output = json.dumps(
                _safe_migration_job_projection(image=migration_job_image)
            )
        elif command[:4] == ["az", "containerapp", "job", "update"]:
            migration_job_image = command[command.index("--image") + 1]
            calls.append("migration-job-update")
            output = ""
        else:
            output = ""
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    actions = Actions()
    publication_arguments: list[dict[str, object]] = []
    job_start_arguments: list[dict[str, object]] = []

    def publisher(**kwargs):
        publication_arguments.append(kwargs)
        return IMAGE_DIGEST

    def job_runner(**kwargs):
        nonlocal migration_job_image
        migration_job_image = "registry.example/attacker@sha256:" + "f" * 64
        job_start_arguments.append(kwargs)
        calls.append("migration-job-start")
        return "migration-execution-one"

    backend = AzureHostedAdminAIBackend(
        package=package,
        approved_sha256=package_sha256(package),
        password_provider=lambda _prompt: "operator-password-sentinel",
        runner=runner,
        client_factory=client_factory,
        actions=actions,
        authority_reader=authority_reader,
        publisher=publisher,
        job_runner=job_runner,
    )
    context = {"known_invalid_sentinel": "known-invalid-sentinel"}
    results = {}
    for state in ADMIN_AI_RELEASE_STATES:
        if state == "deploy_admin_ai_capability":
            migration = backend.reconcile_admin_ai_secret_access(
                context={
                    "package_sha256": package_sha256(package),
                    "source_git_sha": SOURCE_SHA,
                }
            )
            assert migration["assignment_set_sha256"] == "9" * 64
            context.update(
                {
                    "vault_url": migration["vault_url"],
                    "identity_resource_id": migration["identity_resource_id"],
                    "managed_identity_client_id": migration[
                        "managed_identity_client_id"
                    ],
                }
            )
        result = backend.execute(
            state,
            secret_value=(
                "candidate-key-sentinel"
                if state == "rotate_key_through_admin"
                else None
            ),
            context=context,
        )
        results[state] = result
        if state == "rotate_key_through_admin":
            context["fingerprint"] = result["credential_fingerprint"]
        elif state == "verify_operator_ai":
            context["credential_binding_id"] = result["credential_binding_id"]

    assert results["verify_operator_ai"]["credential_binding_id"] == binding_id
    assert results["verify_demo_ai"]["credential_binding_id"] == binding_id
    assert results["verify_invalid_candidate_rollback"]["secret_scan_matches"] == 0
    assert results["verify_invalid_candidate_rollback"]["audit_event_count"] == 8
    assert results["verify_invalid_candidate_rollback"][
        "audit_secret_scan_matches"
    ] == 0
    assert results["verify_invalid_candidate_rollback"][
        "audit_evidence_sha256"
    ] == hashlib.sha256(
        json.dumps(audit_rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert len(publication_arguments) == 1
    assert publication_arguments[0]["artifact_path"] == (
        Path(__file__).resolve().parents[2] / CANDIDATE_ARTIFACT["artifact_path"]
    )
    assert publication_arguments[0]["artifact_sha256"] == ARTIFACT_SHA256
    assert publication_arguments[0]["expected_digest"] == IMAGE_DIGEST
    assert publication_arguments[0]["oci_reference"] == (
        CANDIDATE_ARTIFACT["oci_reference"]
    )
    assert [arguments["enabled"] for arguments in actions.revision_arguments] == [
        True,
    ]
    assert calls[:6] == [
        "preflight",
        "close-preflight",
        "rbac",
        "deploy-app",
        "verify-app",
        "migration-job-read",
    ]
    assert calls[5:7] == [
        "migration-job-read",
        "migration-job-start",
    ]
    assert results["deploy_admin_ai_capability"]["migration_job_reads"] == 1
    execution_template = job_start_arguments[0]["execution_template"]
    assert execution_template["containers"][0]["image"] == (
        backend._candidate_reference()
    )
    assert execution_template["containers"][0]["command"] == ["python"]
    assert execution_template["containers"][0]["args"] == [
        "scripts/prepare_cloud.py"
    ]
    assert execution_template["initContainers"] == []
    assert execution_template["volumes"] == []
    assert results["deploy_admin_ai_capability"][
        "migration_execution_template_sha256"
    ] == hashlib.sha256(
        json.dumps(
            execution_template,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def test_live_preflight_rejects_database_head_drift_before_any_mutation() -> None:
    import httpx

    from scripts.admin_ai_release_operations import (
        AdminAIReleaseOperationInvalid,
        AzureHostedAdminAIBackend,
    )

    package = _package()
    task10_result = {
        "operations": {"azure.read.sanitized": 12},
        "outputs": {"role_assignment_state": "legacy_only"},
    }
    projection = {"safe": "projection"}
    package["azure_baseline"]["observation_sha256"] = hashlib.sha256(
        json.dumps(
            {"result": task10_result, "projection": projection},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    def authority_reader(_authority, **kwargs):
        kwargs["safe_observer"](
            {
                "hosted_url": (
                    "https://newcaostone-demo-app.synthetic.azurecontainerapps.io"
                ),
                "immutable_configuration": {"safe": "configuration"},
            }
        )
        return deepcopy(task10_result), deepcopy(projection)

    class Client:
        def get(self, path: str):
            assert path == "/health/ready"
            return httpx.Response(
                200,
                json={
                    "status": "ready",
                    "checks": {"migration": "0015_admin_ai_control"},
                },
            )

        def close(self) -> None:
            return None

    class Actions:
        current_projection = None
        _immutable_configuration = None
        _hosted_url = None

    backend = AzureHostedAdminAIBackend(
        package=package,
        approved_sha256=package_sha256(package),
        actions=Actions(),
        authority_reader=authority_reader,
        client_factory=lambda **_kwargs: Client(),
    )

    with pytest.raises(
        AdminAIReleaseOperationInvalid,
        match="preflight_database_drift",
    ):
        backend._readonly_revalidation(secret_value=None, context={})

    assert backend._actions.current_projection is None


def test_live_backend_scans_bounded_response_headers_for_exact_credentials() -> None:
    import httpx

    from scripts.admin_ai_release_operations import (
        AdminAIReleaseOperationInvalid,
        AzureHostedAdminAIBackend,
    )

    backend = AzureHostedAdminAIBackend(
        package=_package(),
        approved_sha256=package_sha256(_package()),
        actions=object(),
    )
    candidate = "nonstandard-candidate-value-without-a-known-prefix"
    response = httpx.Response(
        200,
        content=b'{"status":"safe"}',
        headers={"X-Unsafe-Debug": candidate},
    )

    with pytest.raises(AdminAIReleaseOperationInvalid, match="secret_scan_failed"):
        backend._record_body(response, sensitive_values=(candidate,))


def test_live_backend_stops_immediately_on_generic_response_secret() -> None:
    import httpx

    from scripts.admin_ai_release_operations import (
        AdminAIReleaseOperationInvalid,
        AzureHostedAdminAIBackend,
    )

    backend = object.__new__(AzureHostedAdminAIBackend)
    backend._candidate_buffer = None
    backend._password_buffer = None
    backend._safe_scan_matches = 0
    response = httpx.Response(
        200,
        headers={"authorization": "Bearer eyJabcdefghijklmnop"},
        json={"status": "must-not-advance"},
    )

    with pytest.raises(AdminAIReleaseOperationInvalid, match="secret_scan_failed"):
        backend._record_body(response)

    assert backend._safe_scan_matches == 1


@pytest.mark.parametrize("header", (None, "unsafe request id"))
def test_live_backend_requires_real_safe_response_request_id(
    header: str | None,
) -> None:
    import httpx

    from scripts.admin_ai_release_operations import (
        AdminAIReleaseOperationInvalid,
        AzureHostedAdminAIBackend,
    )

    backend = object.__new__(AzureHostedAdminAIBackend)
    response = httpx.Response(
        200,
        content=b"{}",
        headers={} if header is None else {"X-Request-ID": header},
    )

    with pytest.raises(AdminAIReleaseOperationInvalid, match="request_id_invalid"):
        backend._request_id(response, "must-not-fabricate")


@pytest.mark.parametrize("location", ["body", "header"])
def test_live_backend_scans_every_later_response_against_retained_credentials(
    location: str,
) -> None:
    import httpx

    from scripts.admin_ai_release_operations import (
        AdminAIReleaseOperationInvalid,
        AzureHostedAdminAIBackend,
    )

    candidate = "retained-nonstandard-candidate-value"
    password = "retained-nonstandard-password-value"
    backend = AzureHostedAdminAIBackend(
        package=_package(),
        approved_sha256=package_sha256(_package()),
        actions=object(),
    )
    backend._candidate_buffer = bytearray(candidate.encode())
    backend._password_buffer = bytearray(password.encode())
    response = httpx.Response(
        200,
        content=(
            f'{{"unexpected":"{candidate}"}}'.encode()
            if location == "body"
            else b'{"status":"safe"}'
        ),
        headers=(
            {"X-Unsafe-Debug": password}
            if location == "header"
            else {}
        ),
    )

    with pytest.raises(AdminAIReleaseOperationInvalid, match="secret_scan_failed"):
        backend._record_body(response)


def test_live_backend_scans_bounded_log_text_for_exact_in_process_credentials() -> None:
    from scripts.admin_ai_release_operations import AzureHostedAdminAIBackend

    candidate = "nonstandard-candidate-value-without-a-known-prefix"
    password = "nonstandard-password-value-without-a-known-prefix"
    commands: list[tuple[str, ...]] = []

    def runner(command, **_kwargs):
        commands.append(tuple(command))
        if command[:5] == [
            "az",
            "monitor",
            "log-analytics",
            "workspace",
            "show",
        ]:
            output = "33333333-3333-4333-8333-333333333333\n"
        else:
            output = json.dumps(
                [
                    {
                        "Log_s": (
                            f"request-watermark unexpected {candidate} and {password}"
                        )
                    }
                ]
            )
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    backend = AzureHostedAdminAIBackend(
        package=_package(),
        approved_sha256=package_sha256(_package()),
        actions=object(),
        runner=runner,
    )
    backend._candidate_buffer = bytearray(candidate.encode())
    backend._password_buffer = bytearray(password.encode())
    backend._deployed_revision = "newcaostone-demo-app--admin-ai-compatible-1234567"

    assert (
        backend._hosted_log_secret_matches(
            marker_request_id="request-watermark"
        )
        == 2
    )
    assert all(candidate not in " ".join(command) for command in commands)
    assert all(password not in " ".join(command) for command in commands)


def test_live_backend_log_scan_is_exact_revision_bounded_and_rejects_truncation(
) -> None:
    from scripts.admin_ai_release_operations import (
        AdminAIReleaseOperationInvalid,
        AzureHostedAdminAIBackend,
    )

    commands: list[tuple[str, ...]] = []

    def runner(command, **_kwargs):
        commands.append(tuple(command))
        if command[:5] == [
            "az",
            "monitor",
            "log-analytics",
            "workspace",
            "show",
        ]:
            output = "33333333-3333-4333-8333-333333333333\n"
        else:
            output = json.dumps([{"Log_s": "safe"}] * 1_001)
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    backend = AzureHostedAdminAIBackend(
        package=_package(),
        approved_sha256=package_sha256(_package()),
        actions=object(),
        runner=runner,
        now=lambda: datetime(2026, 8, 18, 16, 5, 0, 654321, tzinfo=UTC),
    )
    backend._attempt_started_at = datetime(
        2026, 8, 18, 16, 0, 0, 123456, tzinfo=UTC
    )
    backend._deployed_revision = "newcaostone-demo-app--admin-ai-compatible-1234567"

    with pytest.raises(AdminAIReleaseOperationInvalid, match="secret_scan_unavailable"):
        backend._hosted_log_secret_matches(marker_request_id="request-watermark")

    query_command = next(
        command
        for command in commands
        if command[:5] == ("az", "monitor", "log-analytics", "query", "--workspace")
    )
    query = query_command[query_command.index("--analytics-query") + 1]
    assert 'ContainerAppName_s == "newcaostone-demo-app"' in query
    assert (
        'RevisionName_s == "newcaostone-demo-app--admin-ai-compatible-1234567"'
        in query
    )
    assert "TimeGenerated between (datetime(2026-08-18T16:00:00.123456Z)" in query
    assert "datetime(2026-08-18T16:05:00.654321Z))" in query
    assert query.endswith("| project Log_s | take 1001")


def test_live_backend_waits_for_log_watermark_before_accepting_scan() -> None:
    from scripts.admin_ai_release_operations import AzureHostedAdminAIBackend

    candidate = "late-nonstandard-candidate-leak"
    marker = "request-attempt-end-watermark"
    query_count = 0
    sleeps: list[float] = []

    def runner(command, **_kwargs):
        nonlocal query_count
        if command[:5] == [
            "az",
            "monitor",
            "log-analytics",
            "workspace",
            "show",
        ]:
            output = "33333333-3333-4333-8333-333333333333\n"
        else:
            query_count += 1
            output = json.dumps(
                [
                    {"Log_s": "early partial row"},
                    *(
                        [{"Log_s": f"{marker} late {candidate}"}]
                        if query_count == 2
                        else []
                    ),
                ]
            )
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    backend = AzureHostedAdminAIBackend(
        package=_package(),
        approved_sha256=package_sha256(_package()),
        actions=object(),
        runner=runner,
        sleeper=sleeps.append,
        now=lambda: datetime(2026, 8, 18, 16, 5, 0, 654321, tzinfo=UTC),
    )
    backend._candidate_buffer = bytearray(candidate.encode())
    backend._deployed_revision = "newcaostone-demo-app--admin-ai-compatible-1234567"

    assert backend._hosted_log_secret_matches(marker_request_id=marker) == 1
    assert query_count == 2
    assert sleeps == [5.0]


def test_live_backend_does_not_accept_marker_before_late_log_leak_settles() -> None:
    from scripts.admin_ai_release_operations import AzureHostedAdminAIBackend

    candidate = "late-after-marker-nonstandard-candidate-leak"
    marker = "request-marker-before-late-row"
    query_count = 0
    sleeps: list[float] = []

    def runner(command, **_kwargs):
        nonlocal query_count
        if command[:5] == [
            "az",
            "monitor",
            "log-analytics",
            "workspace",
            "show",
        ]:
            output = "33333333-3333-4333-8333-333333333333\n"
        else:
            query_count += 1
            output = json.dumps(
                [
                    {"Log_s": marker},
                    *(
                        [{"Log_s": candidate}]
                        if query_count >= 2
                        else []
                    ),
                ]
            )
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    backend = AzureHostedAdminAIBackend(
        package=_package(),
        approved_sha256=package_sha256(_package()),
        actions=object(),
        runner=runner,
        sleeper=sleeps.append,
        now=lambda: datetime(2026, 8, 18, 16, 5, 0, 654321, tzinfo=UTC),
    )
    backend._candidate_buffer = bytearray(candidate.encode())
    backend._deployed_revision = "newcaostone-demo-app--admin-ai-compatible-1234567"

    assert backend._hosted_log_secret_matches(marker_request_id=marker) == 1
    assert query_count == 2
    assert sleeps == [5.0]


@pytest.mark.parametrize(
    "mutation",
    ["wrong_actor", "wrong_status", "wrong_order", "duplicate", "unsafe_request", "extra"],
)
def test_live_backend_rejects_nonexact_turn_binding_audit_evidence(
    mutation: str,
) -> None:
    import httpx

    from scripts.admin_ai_release_operations import (
        AdminAIReleaseOperationInvalid,
        AzureHostedAdminAIBackend,
    )

    operator_turn = "11111111-1111-4111-8111-111111111111"
    demo_turn = "22222222-2222-4222-8222-222222222222"
    items = [
        {
            "turn_id": operator_turn,
            "actor_kind": "operator",
            "request_id": "request-operator-1",
            "credential_binding_id": "d" * 64,
            "credential_control_revision": 2,
            "status": "answered",
        },
        {
            "turn_id": demo_turn,
            "actor_kind": "demo",
            "request_id": "request-demo-1",
            "credential_binding_id": "d" * 64,
            "credential_control_revision": 3,
            "status": "answered",
        },
    ]
    if mutation == "wrong_actor":
        items[0]["actor_kind"] = "demo"
    elif mutation == "wrong_status":
        items[1]["status"] = "failed"
    elif mutation == "wrong_order":
        items.reverse()
    elif mutation == "duplicate":
        items[1]["turn_id"] = operator_turn
    elif mutation == "unsafe_request":
        items[0]["request_id"] = "unsafe request id"
    else:
        items[0]["unexpected"] = True

    class Operator:
        def get(self, _path: str, **_kwargs):
            return httpx.Response(200, json={"items": items})

    backend = AzureHostedAdminAIBackend(
        package=_package(),
        approved_sha256=package_sha256(_package()),
        actions=object(),
    )
    backend._operator = Operator()

    with pytest.raises(
        AdminAIReleaseOperationInvalid,
        match="binding_evidence_invalid",
    ):
        backend._audit_binding(
            (operator_turn, demo_turn),
            actor_kinds=("operator", "demo"),
        )


@pytest.mark.parametrize("mutation", ("wrong_action", "wrong_revision", "extra"))
def test_live_backend_rejects_nonexact_mutation_audit_evidence(
    mutation: str,
) -> None:
    import httpx

    from scripts.admin_ai_release_operations import (
        AdminAIReleaseOperationInvalid,
        AzureHostedAdminAIBackend,
    )

    expected = {
        "request_id": "request-mutation-1",
        "action": "key.rotate",
        "result": "succeeded",
        "safe_error_code": None,
        "prior_revision": 0,
        "resulting_revision": 1,
        "requested_operator_enabled": None,
        "requested_demo_enabled": None,
    }
    observed = deepcopy(expected)
    if mutation == "wrong_action":
        observed["action"] = "channels.update"
    elif mutation == "wrong_revision":
        observed["resulting_revision"] = 2
    else:
        observed["unexpected"] = True

    class Operator:
        def get(self, _path: str, **_kwargs):
            return httpx.Response(
                200,
                headers={"X-Request-ID": "request-audit-read-1"},
                json={"items": [observed]},
            )

    backend = AzureHostedAdminAIBackend(
        package=_package(),
        approved_sha256=package_sha256(_package()),
        actions=object(),
    )
    backend._operator = Operator()
    backend._mutation_audit_expectations = [expected]

    with pytest.raises(
        AdminAIReleaseOperationInvalid,
        match="mutation_audit_invalid",
    ):
        backend._mutation_audit_evidence()


def test_operations_factory_is_bound_to_exact_committed_regular_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "scripts/admin_ai_release_operations.py"
    source.parent.mkdir()
    committed = b"def create_operations(**kwargs):\n    return kwargs\n"
    source.write_bytes(committed)

    def git_show(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert args[0] == [
            "git",
            "show",
            f"{SOURCE_SHA}:./scripts/admin_ai_release_operations.py",
        ]
        assert kwargs["shell"] is False
        return subprocess.CompletedProcess(
            [],
            0,
            stdout=committed,
            stderr=b"",
        )

    binding = capture_operations_factory(
        "scripts.admin_ai_release_operations:create_operations",
        source_sha=SOURCE_SHA,
        runner=git_show,
        project_root=tmp_path,
    )

    assert binding == {
        "factory": "scripts.admin_ai_release_operations:create_operations",
        "source_path": "scripts/admin_ai_release_operations.py",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }

    source.write_bytes(b"def create_operations(**kwargs):\n    raise RuntimeError\n")
    with pytest.raises(AdminAIReleasePackageInvalid, match="factory_invalid"):
        capture_operations_factory(
            "scripts.admin_ai_release_operations:create_operations",
            source_sha=SOURCE_SHA,
            runner=git_show,
            project_root=tmp_path,
        )


def test_operations_factory_reads_git_object_relative_to_nested_project(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    project = repository / "bizpulse"
    source = project / "scripts" / "admin_ai_release_operations.py"
    source.parent.mkdir(parents=True)
    source.write_text("def create_operations(**kwargs):\n    return kwargs\n")
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.invalid"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tests"],
        cwd=repository,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repository, check=True)
    source_sha = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    binding = capture_operations_factory(
        "scripts.admin_ai_release_operations:create_operations",
        source_sha=source_sha,
        project_root=project,
    )

    assert binding["source_path"] == "scripts/admin_ai_release_operations.py"
    assert binding["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_current_authority_binding_uses_file_hash_and_refuses_expired_snapshot(
    tmp_path: Path,
) -> None:
    path = tmp_path / "current_authority.json"
    current = {
        "freshness": {
            "evidence_kind": "sanitized_azure_readback",
            "evidence_sha256": BASELINE_SHA256,
            "observed_at": "2026-08-18T15:55:00Z",
            "expires_at": "2026-08-18T17:00:00Z",
        }
    }
    path.write_text(json.dumps(current), encoding="utf-8")

    assert capture_authority_binding(path, now=NOW, project_root=tmp_path) == {
        "path": "current_authority.json",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "evidence_sha256": BASELINE_SHA256,
        "observed_at": "2026-08-18T15:55:00Z",
        "expires_at": "2026-08-18T17:00:00Z",
    }
    current["freshness"]["expires_at"] = "2026-08-18T15:59:59Z"
    path.write_text(json.dumps(current), encoding="utf-8")
    with pytest.raises(AdminAIReleasePackageInvalid, match="authority_stale"):
        capture_authority_binding(path, now=NOW, project_root=tmp_path)


def test_candidate_image_inspection_binds_platform_digest_and_source_labels() -> None:
    image_input_sha256 = "8" * 64
    image_reference = f"registry.example/bizpulse@{IMAGE_DIGEST}"
    payload = [
        {
            "Id": IMAGE_DIGEST,
            "Os": "linux",
            "Architecture": "amd64",
            "RepoDigests": [image_reference],
            "Config": {
                "Labels": {
                    "org.opencontainers.image.revision": SOURCE_SHA,
                    "org.opencontainers.image.bizpulse.image-input-sha256": (
                        image_input_sha256
                    ),
                    "org.opencontainers.image.bizpulse.build-context-sha256": (
                        BUILD_CONTEXT_MANIFEST["sha256"]
                    ),
                }
            },
        }
    ]
    result = capture_candidate_image(
        source_sha=SOURCE_SHA,
        source_tree=SOURCE_TREE,
        image_reference=image_reference,
        image_input_sha256=image_input_sha256,
        build_context_sha256=BUILD_CONTEXT_MANIFEST["sha256"],
        runner=lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(payload), stderr=""
        ),
    )

    assert result == {
        "image_digest": IMAGE_DIGEST,
        "platform": "linux/amd64",
        "source_sha": SOURCE_SHA,
        "source_tree": SOURCE_TREE,
        "image_input_sha256": image_input_sha256,
        "build_context_sha256": BUILD_CONTEXT_MANIFEST["sha256"],
    }


@pytest.mark.parametrize(("os_name", "architecture"), [("linux", "arm64"), ("windows", "amd64")])
def test_candidate_image_inspection_refuses_non_linux_amd64(
    os_name: str,
    architecture: str,
) -> None:
    image_reference = f"registry.example/bizpulse@{IMAGE_DIGEST}"
    payload = [
        {
            "Id": IMAGE_DIGEST,
            "Os": os_name,
            "Architecture": architecture,
            "RepoDigests": [image_reference],
            "Config": {
                "Labels": {
                    "org.opencontainers.image.revision": SOURCE_SHA,
                    "org.opencontainers.image.bizpulse.image-input-sha256": "8" * 64,
                    "org.opencontainers.image.bizpulse.build-context-sha256": (
                        BUILD_CONTEXT_MANIFEST["sha256"]
                    ),
                }
            },
        }
    ]
    with pytest.raises(AdminAIReleasePackageInvalid, match="candidate_image_invalid"):
        capture_candidate_image(
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            image_reference=image_reference,
            image_input_sha256="8" * 64,
            build_context_sha256=BUILD_CONTEXT_MANIFEST["sha256"],
            runner=lambda *_args, **_kwargs: subprocess.CompletedProcess(
                [], 0, stdout=json.dumps(payload), stderr=""
            ),
        )


def test_candidate_image_refuses_mismatched_build_context_label() -> None:
    image_reference = f"registry.example/bizpulse@{IMAGE_DIGEST}"
    payload = [
        {
            "Id": IMAGE_DIGEST,
            "Os": "linux",
            "Architecture": "amd64",
            "RepoDigests": [image_reference],
            "Config": {
                "Labels": {
                    "org.opencontainers.image.revision": SOURCE_SHA,
                    "org.opencontainers.image.bizpulse.image-input-sha256": (
                        IMAGE_INPUT_SHA256
                    ),
                    "org.opencontainers.image.bizpulse.build-context-sha256": "f" * 64,
                }
            },
        }
    ]

    with pytest.raises(AdminAIReleasePackageInvalid, match="candidate_image_invalid"):
        capture_candidate_image(
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            image_reference=image_reference,
            image_input_sha256=IMAGE_INPUT_SHA256,
            build_context_sha256=BUILD_CONTEXT_MANIFEST["sha256"],
            runner=lambda *_args, **_kwargs: subprocess.CompletedProcess(
                [], 0, stdout=json.dumps(payload), stderr=""
            ),
        )


def test_current_baseline_is_derived_from_task10_twelve_read_result() -> None:
    request = _task10_successor_request()
    task10_result = {
        "operations": {"azure.read.sanitized": 12},
        "evidence": {"secret_values_read": 0},
        "outputs": {
            "rollback_revision": request["azure_target"]["rollback_revision"],
            "ai_enabled": False,
            "vault_state": "existing_exact",
            "identity_state": "existing_exact",
            "role_assignment_state": "legacy_only",
            "diagnostic_setting_state": "existing_exact",
            "secret_values_read": 0,
        },
    }
    projection = {"safe": "projection"}

    def authority_reader(_request, **kwargs):
        kwargs["safe_observer"](
            {
                "hosted_url": (
                    "https://newcaostone-demo-app.synthetic.azurecontainerapps.io"
                ),
                "immutable_configuration": {"safe": "configuration"},
            }
        )
        return deepcopy(task10_result), deepcopy(projection)

    baseline = collect_current_azure_baseline(
        request,
        observed_at=NOW,
        source_sha=SOURCE_SHA,
        source_tree=SOURCE_TREE,
        image_input_sha256=IMAGE_INPUT_SHA256,
        verified_prior_attempts=request["prior_attempts"],
        reader=authority_reader,
        readiness_reader=lambda _origin: "0014_import_base_lineage",
    )

    expected_digest = hashlib.sha256(
        json.dumps(
            {
                "result": task10_result,
                "projection": projection,
                "readiness": {
                    "database_revision": "0014_import_base_lineage",
                    "status": "ready",
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert baseline == {
        "observed_at": "2026-08-18T16:00:00Z",
        "observation_sha256": expected_digest,
        "required_azure_reads": 12,
        "health_state": "Healthy",
        "ready": True,
        "revision": CURRENT_ADMIN_AI_SUCCESSOR_TARGET["rollback_revision"],
        "image_digest": CURRENT_ADMIN_AI_SUCCESSOR_TARGET[
            "rollback_image"
        ].rsplit("@", 1)[-1],
        "traffic_weight": 100,
        "operator_ai_enabled": False,
        "demo_ai_enabled": False,
        "role_assignment_phase": "legacy_only",
        "database_revision": "0014_import_base_lineage",
    }


def test_hosted_database_revision_reader_is_bounded_and_credential_free() -> None:
    import httpx

    observed: dict[str, object] = {}

    class Client:
        def get(self, path: str, **kwargs):
            observed["path"] = path
            observed["headers"] = kwargs["headers"]
            return httpx.Response(
                200,
                json={
                    "status": "ready",
                    "checks": {
                        "blob": "ok",
                        "configuration": "ok",
                        "database": "ok",
                        "foundation": "ok",
                        "migration": "0014_import_base_lineage",
                    },
                },
            )

        def close(self) -> None:
            observed["closed"] = True

    def client_factory(**kwargs):
        observed["client"] = kwargs
        return Client()

    assert read_hosted_database_revision(
        "https://newcaostone-demo-app.synthetic.azurecontainerapps.io",
        client_factory=client_factory,
    ) == "0014_import_base_lineage"
    assert observed == {
        "client": {
            "base_url": (
                "https://newcaostone-demo-app.synthetic.azurecontainerapps.io"
            ),
            "timeout": 15,
            "follow_redirects": False,
            "trust_env": False,
        },
        "path": "/health/ready",
        "headers": {"Accept": "application/json"},
        "closed": True,
    }


@pytest.mark.parametrize(
    "revision",
    (
        "0008_ai_budget_ledger",
        "0013_workspace_preferences",
        "0017_ai_turn_credential_binding",
    ),
)
def test_hosted_database_revision_reader_rejects_non_pre_migration_heads(
    revision: str,
) -> None:
    import httpx

    class Client:
        def get(self, _path: str, **_kwargs):
            return httpx.Response(
                200,
                json={
                    "status": "ready",
                    "checks": {
                        "blob": "ok",
                        "configuration": "ok",
                        "database": "ok",
                        "foundation": "ok",
                        "migration": revision,
                    },
                },
            )

        def close(self) -> None:
            return None

    with pytest.raises(
        AdminAIReleasePackageInvalid,
        match="azure_baseline_readiness_invalid",
    ):
        read_hosted_database_revision(
            "https://newcaostone-demo-app.synthetic.azurecontainerapps.io",
            client_factory=lambda **_kwargs: Client(),
        )


@pytest.mark.parametrize("mutation", ("extra", "false_rbac", "other_source"))
def test_task10_request_is_strictly_bound_before_the_first_azure_read(
    mutation: str,
) -> None:
    request = _task10_successor_request()
    if mutation == "extra":
        request["unexpected"] = True
    elif mutation == "false_rbac":
        request["execution_contract"]["states"][
            "reconcile_ai_vault_identity_role_diagnostics"
        ]["expected_evidence"]["rbac_authorization"] = False
    else:
        request["repository"]["head_sha"] = "f" * 40
    calls = 0

    def fail_reader(_request):
        nonlocal calls
        calls += 1
        raise AssertionError("malformed authority must cause zero Azure commands")

    with pytest.raises(
        AdminAIReleasePackageInvalid,
        match="operations_authority_invalid|operations_authority_drift",
    ):
        collect_current_azure_baseline(
            request,
            observed_at=NOW,
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            image_input_sha256=IMAGE_INPUT_SHA256,
            verified_prior_attempts=request["prior_attempts"],
            reader=fail_reader,
        )

    assert calls == 0


def test_admin_observation_rejects_historical_r19_task10_profile() -> None:
    calls = 0

    def fail_reader(_request):
        nonlocal calls
        calls += 1
        raise AssertionError("historical authority must cause zero Azure commands")

    with pytest.raises(
        AdminAIReleasePackageInvalid,
        match="operations_authority_drift",
    ):
        collect_current_azure_baseline(
            _task10_request(),
            observed_at=NOW,
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            image_input_sha256=IMAGE_INPUT_SHA256,
            verified_prior_attempts=_task10_request()["prior_attempts"],
            reader=fail_reader,
        )

    assert calls == 0


def test_admin_observation_requires_revalidated_retired_artifacts() -> None:
    request = _task10_successor_request()
    verified_prior_attempts = deepcopy(request["prior_attempts"])

    assert validate_task10_request_for_observation(
        request,
        observed_at=NOW,
        source_sha=SOURCE_SHA,
        source_tree=SOURCE_TREE,
        image_input_sha256=IMAGE_INPUT_SHA256,
        verified_prior_attempts=verified_prior_attempts,
    ) == request

    verified_prior_attempts.pop("r19")
    with pytest.raises(
        AdminAIReleasePackageInvalid,
        match="operations_authority_drift",
    ):
        validate_task10_request_for_observation(
            request,
            observed_at=NOW,
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            image_input_sha256=IMAGE_INPUT_SHA256,
            verified_prior_attempts=verified_prior_attempts,
        )


def test_package_file_is_owner_only_exclusive_and_expiry_checked(tmp_path: Path) -> None:
    path = tmp_path / "fresh-package.json"
    package = _package(receipt_path=str(tmp_path / "receipt.json"))

    digest = write_package(path, package)

    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_package(path, now=NOW + timedelta(hours=1)) == package
    with pytest.raises(AdminAIReleasePackageInvalid, match="package_write_refused"):
        write_package(path, package)
    with pytest.raises(AdminAIReleasePackageInvalid, match="package_expired"):
        load_package(path, now=NOW + timedelta(days=2))


def test_old_package_hash_is_refused_before_any_operation_or_key_prompt(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "receipt.json"
    package = _package(receipt_path=str(receipt))
    old_hash = package["replay_fence"]["retired_package_sha256"][0]
    operations = _Operations()
    key_calls = 0

    def key_reader() -> str:
        nonlocal key_calls
        key_calls += 1
        return "sentinel-never-persist"

    with pytest.raises(AdminAIReleaseInvalid, match="retired_package_hash"):
        _run_once(
            package,
            operations,
            approved_sha256=old_hash,
            key_reader=key_reader,
            now=NOW,
        )

    assert operations.calls == []
    assert key_calls == 0
    assert not receipt.exists()


def test_controller_revalidates_full_package_shape_before_receipt_or_key(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "receipt.json"
    package = _package(receipt_path=str(receipt))
    package["schema_version"] = "retired.admin-ai-release.v0"
    operations = _Operations()
    key_calls = 0

    def key_reader() -> str:
        nonlocal key_calls
        key_calls += 1
        return "never-read"

    with pytest.raises(AdminAIReleaseInvalid, match="package_invalid"):
        _run_once(
            package,
            operations,
            approved_sha256=package_sha256(package),
            key_reader=key_reader,
            now=NOW,
        )

    assert operations.calls == []
    assert key_calls == 0
    assert not receipt.exists()


def test_release_sources_never_read_an_ambient_openai_key() -> None:
    project_root = Path(__file__).resolve().parents[2]
    sources = "\n".join(
        (project_root / relative).read_text(encoding="utf-8")
        for relative in (
            "scripts/admin_ai_release_operations.py",
            "scripts/build_admin_ai_candidate.py",
            "scripts/create_admin_ai_release_package.py",
            "scripts/publish_registry_image.py",
            "scripts/run_admin_ai_release.py",
            "scripts/verify_admin_ai_control.py",
        )
    )

    assert 'os.environ["OPENAI_API_KEY"]' not in sources
    assert "os.environ.get(\"OPENAI_API_KEY\")" not in sources
    assert "os.getenv(\"OPENAI_API_KEY\")" not in sources


@pytest.mark.parametrize(
    "entrypoint",
    (
        "scripts/build_admin_ai_candidate.py",
        "scripts/create_admin_ai_release_package.py",
        "scripts/run_admin_ai_release.py",
    ),
)
def test_release_entrypoints_require_the_exact_runtime_launcher(
    entrypoint: str,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(project_root / entrypoint),
            "--help",
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 1
    assert completed.stdout.splitlines() == [
        "admin_ai_exact_runtime=failed",
        "reason=runtime_snapshot_required",
    ]
    assert completed.stderr == ""


def test_exact_runtime_launcher_is_the_only_documented_executable_boundary() -> None:
    project_root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(project_root / "scripts/admin_ai_exact_runtime.py"),
            "--help",
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    assert "{authority-refresh,build,package,release}" in completed.stdout
    assert ":./scripts/admin_ai_exact_runtime.py" in completed.stdout
    assert "pipefail" in completed.stdout


def test_package_generator_exposes_fresh_task10_successor_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stopped:
        create_package_main(["--help"])

    output = capsys.readouterr().out
    assert stopped.value.code == 0
    assert "--create-azure-authority-request" in output
    assert "--task10-role-assignment-state" in output


def test_runbook_and_status_distinguish_historical_r19_from_current_recovery() -> None:
    project_root = Path(__file__).resolve().parents[2]
    runbook = (project_root / "docs/operations/AZURE_LAUNCH_RUNBOOK.md").read_text()
    status = (project_root.parent / "CURRENT_STATUS.md").read_text()
    historical = "newcaostone-demo-app--ai-off-9c35ae6a-2bf7086"
    recovery = "newcaostone-demo-app--recover-b-9c35ae6a-2bf7086"

    for document in (runbook, status):
        normalized = " ".join(document.split())
        assert historical in document
        assert recovery in document
        assert "registry_only" in document
        assert "does not prove hosted acceptance" in normalized
        assert "never replay R19" in normalized

    assert "expected current recovery-adoption baseline" in runbook
    assert "Historical accepted R19 target" in status
    assert "Current recovery-adoption target" in status


def test_runbook_requires_exact_runtime_and_prohibits_old_revision_after_0017() -> None:
    project_root = Path(__file__).resolve().parents[2]
    runbook = (project_root / "docs/operations/AZURE_LAUNCH_RUNBOOK.md").read_text()

    assert runbook.count(
        "ADMIN_AI_SOURCE_SHA=\"$(git rev-parse --verify 'HEAD^{commit}')\""
    ) == 4
    assert runbook.count("set -o pipefail") == 4
    assert runbook.count(
        'git show "${ADMIN_AI_SOURCE_SHA}:./scripts/admin_ai_exact_runtime.py" |'
    ) == 4
    assert runbook.count('--source-sha "$ADMIN_AI_SOURCE_SHA"') == 4
    assert '.venv/bin/python -I -B -S - --project-root "$PWD" \\' in runbook
    assert "--create-azure-authority-request" in runbook
    assert "complete package-bound execution-template override" in runbook
    assert "Never route traffic back to the old attested revision after 0017" in runbook


def test_default_key_prompt_requires_tty_and_prompts_exactly_once() -> None:
    prompts: list[str] = []

    with pytest.raises(AdminAIReleaseInvalid, match="tty_required"):
        read_candidate_key(
            stdin_is_tty=lambda: False,
            hidden_prompt=lambda _message: "must-not-run",
        )

    value = read_candidate_key(
        stdin_is_tty=lambda: True,
        hidden_prompt=lambda message: prompts.append(message) or "candidate",
    )
    assert value == "candidate"
    assert prompts == ["OpenAI candidate key (input hidden): "]


class _Operations:
    def __init__(self, *, fail_at: str | None = None) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.fail_at = fail_at
        self.migration_calls: list[dict[str, object]] = []

    def reconcile_admin_ai_secret_access(
        self,
        *,
        context: dict[str, object],
    ) -> dict[str, object]:
        self.migration_calls.append(deepcopy(context))
        return {
            "initial_phase": "legacy_only",
            "final_phase": "officer_only",
            "assignment_set_sha256": "9" * 64,
            "preflight_required_azure_reads": 12,
            "vault_url": "https://newcaostone-ai-kv.vault.azure.net",
            "identity_resource_id": (
                "/subscriptions/11111111-1111-4111-8111-111111111111/"
                "resourceGroups/rg-bizpulse-centralus/providers/"
                "Microsoft.ManagedIdentity/userAssignedIdentities/"
                "newcaostone-ai-identity"
            ),
            "managed_identity_client_id": (
                "22222222-2222-4222-8222-222222222222"
            ),
        }

    def run(
        self,
        state: str,
        *,
        secret_value: str | None,
        context: dict[str, object],
    ) -> dict[str, object]:
        del context
        self.calls.append((state, secret_value))
        if state == self.fail_at:
            raise RuntimeError("provider stack with sensitive detail")
        if state == "readonly_revalidation":
            return {
                "required_azure_reads": 12,
                "observation_sha256": BASELINE_SHA256,
                "role_assignment_phase": "legacy_only",
                "database_revision": "0014_import_base_lineage",
            }
        if state == "publish_candidate_image":
            return {"image_digest": IMAGE_DIGEST}
        if state == "deploy_admin_ai_capability":
            return {
                "revision": "newcaostone-demo-app--admin-ai-1234567",
                "migration": "0017_ai_turn_credential_binding",
                "migration_job_reads": 1,
                "migration_job_projection_sha256": "e" * 64,
                "migration_execution_template_sha256": "f" * 64,
                "operator_ai_enabled": False,
                "demo_ai_enabled": False,
            }
        if state == "verify_ai_disabled_candidate":
            return {
                "ready": True,
                "admin_protected": True,
                "summary_status": "ready",
                "operator_ai_enabled": False,
                "demo_ai_enabled": False,
                "request_id": "request-disabled-1",
            }
        if state == "rotate_key_through_admin":
            return {
                "credential_fingerprint": FINGERPRINT,
                "request_id": "request-rotate-1",
                "revision": 1,
            }
        if state == "verify_operator_ai":
            return deepcopy(_hosted_result()["operator_turn"])
        if state == "verify_demo_ai":
            return deepcopy(_hosted_result()["demo_turn"])
        if state == "verify_independent_channel_switches":
            return deepcopy(_hosted_result()["channel_switches"])
        if state == "verify_invalid_candidate_rollback":
            return {
                **deepcopy(_hosted_result()["invalid_candidate_rollback"]),
                "secret_scan_matches": _hosted_result()["secret_scan_matches"],
                "audit_event_count": _hosted_result()["audit_evidence"][
                    "event_count"
                ],
                "audit_secret_scan_matches": _hosted_result()["audit_evidence"][
                    "secret_scan_matches"
                ],
                "audit_evidence_sha256": _hosted_result()["audit_evidence"][
                    "evidence_sha256"
                ],
            }
        raise AssertionError(state)


def test_one_shot_controller_prompts_once_only_at_rotation_and_writes_safe_receipt(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "attempt.json"
    package = _package(receipt_path=str(receipt_path))
    operations = _Operations()
    candidate = "sentinel-provider-value-never-serialize"
    key_calls = 0

    def key_reader() -> str:
        nonlocal key_calls
        key_calls += 1
        return candidate

    receipt = _run_once(
        package,
        operations,
        approved_sha256=package_sha256(package),
        key_reader=key_reader,
        now=NOW,
    )

    assert [state for state, _secret in operations.calls] == list(
        ADMIN_AI_RELEASE_STATES
    )
    assert key_calls == 1
    assert [
        state for state, secret in operations.calls if secret == candidate
    ] == ["rotate_key_through_admin"]
    assert operations.migration_calls == [
        {
            "package_sha256": package_sha256(package),
            "source_git_sha": SOURCE_SHA,
            "role_assignment_phase": "legacy_only",
        }
    ]
    assert receipt["status"] == "completed"
    assert receipt["completed_states"] == list(ADMIN_AI_RELEASE_STATES)
    assert receipt["rbac"] == {
        "initial_phase": "legacy_only",
        "final_phase": "officer_only",
        "required_azure_reads": 12,
        "assignment_set_sha256": "9" * 64,
    }
    assert receipt["schema_recovery_boundary"] == {
        "pre_migration_head": "0014_import_base_lineage",
        "post_migration_head": "0017_ai_turn_credential_binding",
        "safe_stop": "candidate_revision_only",
        "old_revision_routing": "prohibited_after_migration",
    }
    serialized = receipt_path.read_text(encoding="utf-8")
    assert candidate not in serialized
    assert "provider stack" not in serialized
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600


def test_controller_persists_started_receipt_before_first_operation(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "attempt.json"
    package = _package(receipt_path=str(receipt_path))

    class ReceiptObservingOperations(_Operations):
        def run(self, state: str, **kwargs: object) -> dict[str, object]:
            started = json.loads(receipt_path.read_text(encoding="utf-8"))
            assert started["status"] == "started"
            assert started["completed_states"] == []
            assert started["package_sha256"] == package_sha256(package)
            return super().run(state, **kwargs)

    receipt = _run_once(
        package,
        ReceiptObservingOperations(),
        approved_sha256=package_sha256(package),
        key_reader=lambda: "sentinel-never-persist",
    )

    assert receipt["status"] == "completed"
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["status"] == (
        "completed"
    )


def test_first_failure_stops_without_retry_and_terminal_receipt_fences_replay(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "attempt.json"
    package = _package(receipt_path=str(receipt_path))
    operations = _Operations(fail_at="verify_operator_ai")

    receipt = _run_once(
        package,
        operations,
        approved_sha256=package_sha256(package),
        key_reader=lambda: "sentinel-never-persist",
        now=NOW,
    )

    assert receipt["status"] == "failed"
    assert receipt["failed_state"] == "verify_operator_ai"
    assert receipt["safe_error_code"] == "admin_ai_release_operation_failed"
    assert receipt["schema_recovery_boundary"]["safe_stop"] == (
        "candidate_revision_only"
    )
    assert [state for state, _secret in operations.calls].count(
        "verify_operator_ai"
    ) == 1
    assert "verify_demo_ai" not in [state for state, _secret in operations.calls]
    assert "provider stack" not in receipt_path.read_text(encoding="utf-8")

    with pytest.raises(AdminAIReleaseInvalid, match="receipt_exists"):
        _run_once(
            package,
            _Operations(),
            approved_sha256=package_sha256(package),
            key_reader=lambda: "never-called",
            now=NOW,
        )


def test_controller_rejects_rbac_migration_or_read_count_drift(tmp_path: Path) -> None:
    class DriftedOperations(_Operations):
        def reconcile_admin_ai_secret_access(
            self,
            *,
            context: dict[str, object],
        ) -> dict[str, object]:
            del context
            return {
                "role_assignment_phase": "legacy_only",
                "required_azure_reads": 11,
            }

    receipt_path = tmp_path / "attempt.json"
    package = _package(receipt_path=str(receipt_path))
    receipt = _run_once(
        package,
        DriftedOperations(),
        approved_sha256=package_sha256(package),
        key_reader=lambda: "never-reached",
        now=NOW,
    )

    assert receipt["status"] == "failed"
    assert receipt["failed_state"] == "deploy_admin_ai_capability"
    assert receipt["safe_error_code"] == "admin_ai_release_rbac_drift"


def test_controller_reconciles_secret_access_before_enabled_candidate_deploy(
    tmp_path: Path,
) -> None:
    class OrderedOperations(_Operations):
        def __init__(self) -> None:
            super().__init__()
            self.events: list[str] = []

        def reconcile_admin_ai_secret_access(
            self,
            *,
            context: dict[str, object],
        ) -> dict[str, object]:
            self.events.append("rbac")
            return super().reconcile_admin_ai_secret_access(context=context)

        def run(self, state: str, **kwargs: object) -> dict[str, object]:
            if state == "deploy_admin_ai_capability":
                assert self.events == ["rbac"]
                context = kwargs["context"]
                assert isinstance(context, dict)
                assert context["vault_url"] == (
                    "https://newcaostone-ai-kv.vault.azure.net"
                )
                assert context["managed_identity_client_id"] == (
                    "22222222-2222-4222-8222-222222222222"
                )
                self.events.append("deploy")
            return super().run(state, **kwargs)

    operations = OrderedOperations()
    receipt_path = tmp_path / "attempt.json"
    package = _package(receipt_path=str(receipt_path))

    receipt = _run_once(
        package,
        operations,
        approved_sha256=package_sha256(package),
        key_reader=lambda: "sentinel-never-persist",
        now=NOW,
    )

    assert receipt["status"] == "completed"
    assert operations.events == ["rbac", "deploy"]


def test_controller_requires_observed_zero_secret_scan_matches(tmp_path: Path) -> None:
    class LeakingOperations(_Operations):
        def run(self, state: str, **kwargs: object) -> dict[str, object]:
            result = super().run(state, **kwargs)
            if state == "verify_invalid_candidate_rollback":
                result["secret_scan_matches"] = 1
            return result

    receipt_path = tmp_path / "attempt.json"
    package = _package(receipt_path=str(receipt_path))
    receipt = _run_once(
        package,
        LeakingOperations(),
        approved_sha256=package_sha256(package),
        key_reader=lambda: "sentinel-never-persist",
        now=NOW,
    )

    assert receipt["status"] == "failed"
    assert receipt["failed_state"] == "verify_invalid_candidate_rollback"
    assert receipt["safe_error_code"] == "admin_ai_release_secret_scan_failed"


def test_channel_switch_mismatch_stops_before_invalid_candidate_mutation(
    tmp_path: Path,
) -> None:
    class DriftedSwitches(_Operations):
        def run(self, state: str, **kwargs: object) -> dict[str, object]:
            result = super().run(state, **kwargs)
            if state == "verify_independent_channel_switches":
                result["operator_independent"] = False
            return result

    receipt_path = tmp_path / "attempt.json"
    package = _package(receipt_path=str(receipt_path))
    operations = DriftedSwitches()
    receipt = _run_once(
        package,
        operations,
        approved_sha256=package_sha256(package),
        key_reader=lambda: "sentinel-never-persist",
    )

    assert receipt["status"] == "failed"
    assert receipt["failed_state"] == "verify_independent_channel_switches"
    assert "verify_invalid_candidate_rollback" not in [
        state for state, _secret in operations.calls
    ]


def test_key_shaped_operation_value_is_never_written_to_receipt(tmp_path: Path) -> None:
    marker = "sk-proj-abcdefghijklmnop"

    class LeakingOperation(_Operations):
        def run(self, state: str, **kwargs: object) -> dict[str, object]:
            result = super().run(state, **kwargs)
            if state == "rotate_key_through_admin":
                result["request_id"] = marker
            return result

    receipt_path = tmp_path / "attempt.json"
    package = _package(receipt_path=str(receipt_path))
    receipt = _run_once(
        package,
        LeakingOperation(),
        approved_sha256=package_sha256(package),
        key_reader=lambda: "sentinel-never-persist",
    )

    assert receipt["status"] == "failed"
    assert marker not in receipt_path.read_text(encoding="utf-8")


def test_controller_refuses_repository_or_authority_drift_before_receipt(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "attempt.json"
    package = _package(receipt_path=str(receipt_path))
    operations = _Operations()

    with pytest.raises(AdminAIReleaseInvalid, match="repository_drift"):
        run_once(
            package,
            operations,
            approved_sha256=package_sha256(package),
            key_reader=lambda: "never-read",
            now=NOW,
            repository_reader=lambda: {
                **package["repository"],
                "source_sha": "f" * 40,
            },
            authority_reader=lambda _now: deepcopy(
                package["authority_binding"]
            ),
        )
    assert operations.calls == []
    assert not receipt_path.exists()


def test_controller_refuses_candidate_artifact_drift_before_receipt(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "attempt.json"
    package = _package(receipt_path=str(receipt_path))
    observed = deepcopy(CANDIDATE_ARTIFACT)
    observed["artifact_sha256"] = "f" * 64
    operations = _Operations()

    with pytest.raises(AdminAIReleaseInvalid, match="candidate_artifact_drift"):
        run_once(
            package,
            operations,
            approved_sha256=package_sha256(package),
            key_reader=lambda: "never-read",
            now=NOW,
            repository_reader=lambda: deepcopy(package["repository"]),
            authority_reader=lambda _now: deepcopy(package["authority_binding"]),
            artifact_reader=lambda: observed,
        )
    assert operations.calls == []
    assert not receipt_path.exists()


def test_hosted_verifier_requires_shared_fingerprint_for_both_actor_kinds() -> None:
    result = verify_hosted_admin_ai_control(_hosted_result())

    assert result["operator_turn"]["status"] == "completed"
    assert result["demo_turn"]["status"] == "completed"
    assert (
        result["operator_turn"]["credential_fingerprint"]
        == result["demo_turn"]["credential_fingerprint"]
    )
    assert (
        result["operator_turn"]["credential_binding_id"]
        == result["demo_turn"]["credential_binding_id"]
    )


def test_hosted_verifier_rejects_concurrent_rotation_between_actor_turns() -> None:
    result = _hosted_result()
    result["demo_turn"]["credential_binding_id"] = "e" * 64

    with pytest.raises(HostedAdminAIVerificationInvalid):
        verify_hosted_admin_ai_control(result)


@pytest.mark.parametrize(
    "mutation",
    [
        {"demo_turn": {"credential_fingerprint": "deadbeef"}},
        {"operator_turn": {"status": "failed"}},
        {"secret_scan_matches": 1},
        {
            "invalid_candidate_rollback": {
                "resulting_fingerprint": "deadbeef"
            }
        },
    ],
)
def test_hosted_verifier_fails_closed_on_acceptance_drift(
    mutation: dict[str, object],
) -> None:
    result = _hosted_result()
    for key, value in mutation.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key].update(value)
        else:
            result[key] = value

    with pytest.raises(HostedAdminAIVerificationInvalid):
        verify_hosted_admin_ai_control(result)
