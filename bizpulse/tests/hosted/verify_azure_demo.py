"""Validate an externally hash-bound launch package without contacting Azure."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid5

_SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_SCRIPT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_PROJECT_ROOT))

from scripts.create_release_manifest import (  # noqa: E402
    ReleaseManifestInvalid,
    attestation_path,
)
from scripts.secret_boundary import SECRET_PATTERN  # noqa: E402

PROJECT_ROOT = _SCRIPT_PROJECT_ROOT
INFRA_BICEP = PROJECT_ROOT / "infra" / "main.bicep"
INFRA_PARAMETERS = PROJECT_ROOT / "infra" / "environments" / "demo.bicepparam"
AZURE_JOB_RUNNER = PROJECT_ROOT / "scripts" / "run_azure_job.py"
AZURE_PREFLIGHT = PROJECT_ROOT / "scripts" / "azure_recovery_preflight.py"
AZURE_READBACK = PROJECT_ROOT / "scripts" / "run_azure_readback.py"
BROWSER_GATE = PROJECT_ROOT / "scripts" / "browser_release_gate.mjs"
PHASE1_FENCE = PROJECT_ROOT / "scripts" / "verify_phase1_fence.py"
HOSTED_HEALTH = PROJECT_ROOT / "scripts" / "verify_hosted_health.py"
HOSTED_CHECK = PROJECT_ROOT / "scripts" / "run_hosted_check.py"
HOSTED_FAILURE_CHECK = PROJECT_ROOT / "scripts" / "run_hosted_failure_check.py"
HOSTED_CAPACITY = PROJECT_ROOT / "scripts" / "verify_hosted_capacity.py"
REGISTRY_PUBLISHER = PROJECT_ROOT / "scripts" / "publish_registry_image.py"
REGISTRY_VERIFIER = PROJECT_ROOT / "scripts" / "verify_registry_image.py"
SYNTHETIC_MANIFEST = PROJECT_ROOT / "tests" / "fixtures" / "synthetic" / "v1" / "manifest.json"
SEED_NAMESPACE = UUID("cb794ce7-d3cf-516a-850b-643ab0c2ec91")
REPOSITORY_ROOT = PROJECT_ROOT.parent
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
CANDIDATE_HASH_PATHS = {
    "azure_job_runner_sha256": "bizpulse/scripts/run_azure_job.py",
    "azure_preflight_sha256": "bizpulse/scripts/azure_recovery_preflight.py",
    "azure_readback_sha256": "bizpulse/scripts/run_azure_readback.py",
    "browser_gate_sha256": "bizpulse/scripts/browser_release_gate.mjs",
    "hosted_health_sha256": "bizpulse/scripts/verify_hosted_health.py",
    "hosted_check_sha256": "bizpulse/scripts/run_hosted_check.py",
    "hosted_failure_check_sha256": (
        "bizpulse/scripts/run_hosted_failure_check.py"
    ),
    "hosted_capacity_sha256": "bizpulse/scripts/verify_hosted_capacity.py",
    "hosted_expiry_sha256": "bizpulse/scripts/verify_hosted_expiry.py",
    "infra_bicep_sha256": "bizpulse/infra/main.bicep",
    "infra_parameters_sha256": "bizpulse/infra/environments/demo.bicepparam",
    "launch_verifier_sha256": "bizpulse/tests/hosted/verify_azure_demo.py",
    "model_qualification_sha256": "bizpulse/scripts/qualify_openai_model.py",
    "phase1_fence_sha256": "bizpulse/scripts/verify_phase1_fence.py",
    "registry_publisher_sha256": "bizpulse/scripts/publish_registry_image.py",
    "registry_verifier_sha256": "bizpulse/scripts/verify_registry_image.py",
    "stage_receipt_verifier_sha256": "bizpulse/scripts/verify_stage_receipts.py",
    "synthetic_manifest_sha256": (
        "bizpulse/tests/fixtures/synthetic/v1/manifest.json"
    ),
    "two_stage_package_generator_sha256": (
        "bizpulse/scripts/create_two_stage_release_package.py"
    ),
}
REQUIRED_CANDIDATE_PATHS = frozenset(
    {
        "bizpulse/.dockerignore",
        "bizpulse/Dockerfile",
        "bizpulse/alembic.ini",
        "bizpulse/alembic/versions/0007_chat_session_fences.py",
        "bizpulse/alembic/versions/0008_ai_budget_ledger.py",
        "bizpulse/package-lock.json",
        "bizpulse/package.json",
        "bizpulse/requirements-dev.txt",
        "bizpulse/requirements.txt",
        "bizpulse/scripts/prepare_cloud.py",
        "bizpulse/scripts/seed_demo.py",
        "bizpulse/scripts/verify_phase1_fence.py",
        "bizpulse/tests/hosted/verify_azure_demo.py",
        *CANDIDATE_HASH_PATHS.values(),
    }
)

EXPECTED_FIELDS = frozenset(
    {
        "allowed_operations",
        "ai_limits",
        "authorization_id",
        "commands",
        "execution_order",
        "expires_at",
        "external_publication",
        "generated_names",
        "issued_at",
        "limits_usd",
        "public_url",
        "public_url_source",
        "recovery",
        "region",
        "release",
        "resource_group",
        "resources",
        "retry_limits",
        "schema_version",
        "secret_presence",
        "server_settings",
        "stop_conditions",
        "subscription_id",
    }
)
EXPECTED_RELEASE_FIELDS = frozenset(
    {
        "attestation_git_sha",
        "azure_preflight_sha256",
        "azure_readback_sha256",
        "azure_job_runner_sha256",
        "browser_gate_sha256",
        "git_sha",
        "hosted_health_sha256",
        "hosted_check_sha256",
        "hosted_failure_check_sha256",
        "hosted_capacity_sha256",
        "hosted_expiry_sha256",
        "image_digest",
        "image_input_sha256",
        "infra_bicep_sha256",
        "infra_parameters_sha256",
        "launch_verifier_sha256",
        "local_manifest_sha256",
        "migration_head",
        "model_qualification_sha256",
        "phase1_fence_sha256",
        "registry_publisher_sha256",
        "registry_verifier_sha256",
        "rollback_git_sha",
        "rollback_image_digest",
        "rollback_image_input_sha256",
        "synthetic_dataset_version_id",
        "synthetic_manifest_sha256",
        "stage_receipt_verifier_sha256",
        "two_stage_package_generator_sha256",
    }
)
EXPECTED_GENERATED_NAMES = frozenset(
    {
        "application_insights",
        "container_app",
        "container_environment",
        "application_revision",
        "image_repository",
        "log_workspace",
        "migration_job",
        "name_prefix",
        "postgres_administrator_login",
        "postgres_dns_zone",
        "postgres_server",
        "registry_name",
        "registry_identity",
        "seed_job",
        "session_maintenance_job",
        "storage_account",
        "storage_maintenance_job",
        "virtual_network",
    }
)
EXPECTED_RESOURCE_FIELDS = frozenset(
    {"application", "monitoring", "postgres", "storage"}
)
EXPECTED_SECRET_FIELDS = frozenset(
    {
        "blob_credential",
        "openai_api_key",
        "operator_password_hash",
        "postgres_password",
        "registry_password",
        "session_pepper",
    }
)
EXPECTED_LIMIT_FIELDS = frozenset(
    {"hard_cap", "monthly_estimate", "one_time_estimate", "openai_smoke_cap"}
)
EXPECTED_AI_LIMIT_FIELDS = frozenset(
    {
        "daily_attempt_limit",
        "demo_session_rate_limit_per_hour",
        "enabled",
        "global_attempt_limit_per_minute",
        "max_concurrent_turns",
        "monthly_token_limit",
        "session_attempt_limit_per_minute",
    }
)
EXPECTED_RETRY_FIELDS = frozenset({"deploy", "paid_provider", "read"})
EXPECTED_PUBLICATION_FIELDS = frozenset(
    {"dns_change", "github_push", "paid_ai_smoke", "registry_publish"}
)
EXPECTED_RECOVERY_FIELDS = frozenset(
    {
        "blob_soft_delete_days",
        "observed_current_image_digest",
        "postgres_backup_retention_days",
        "restart_readback",
        "rollback_digest_preflight",
        "rollback_rehearsal",
        "target_mode",
    }
)
EXPECTED_COMMAND_FIELDS = frozenset(
    {
        "activate",
        "browser_acceptance",
        "budget_failure",
        "capacity",
        "deploy",
        "expiry",
        "health",
        "migrate",
        "paid_ai_smoke",
        "preflight",
        "provision",
        "provider_failure",
        "registry_publish",
        "registry_verify",
        "restart_readback",
        "rollback",
        "seed",
    }
)
EXPECTED_SERVER_SETTINGS = (
    "APPLICATIONINSIGHTS_CONNECTION_STRING",
    "BIZPULSE_ALLOWED_ORIGIN",
    "BIZPULSE_AI_CHAT_ENABLED",
    "BIZPULSE_AI_DAILY_ATTEMPT_LIMIT",
    "BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE",
    "BIZPULSE_AI_MAX_CONCURRENT_TURNS",
    "BIZPULSE_AI_MONTHLY_TOKEN_LIMIT",
    "BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE",
    "BIZPULSE_BLOB_CONNECTION_STRING",
    "BIZPULSE_BLOB_CONTAINER",
    "BIZPULSE_BLOB_ENDPOINT",
    "BIZPULSE_DATABASE_URL",
    "BIZPULSE_DEMO_SESSION_RATE_LIMIT_PER_HOUR",
    "BIZPULSE_OPERATOR_PASSWORD_HASH",
    "BIZPULSE_RUNTIME_ENVIRONMENT",
    "BIZPULSE_SESSION_PEPPER",
)
BASE_OPERATIONS = (
    "azure_read_preflight",
    "registry_digest_readback",
    "azure_provision",
    "postgres_migrate",
    "synthetic_seed",
    "deploy_digest",
    "hosted_verify",
    "rollback_rehearsal",
)
EXPECTED_STOP_CONDITIONS = (
    "target_or_cost_changed",
    "digest_or_migration_changed",
    "recovery_preflight_failed",
    "secret_boundary_failed",
)
TWO_STAGE_HEADER = "# NEWCaostone Two-Stage Launch Authorization"
TWO_STAGE_FIELDS = frozenset(
    {
        "ai_revision",
        "cost_cap_usd",
        "data_authority_sha256",
        "data_scope_revision",
        "expires_at",
        "issued_at",
        "package_id",
        "schema_version",
        "stage_order",
        "tenant_id",
    }
)
DATA_STAGE_FIELDS = frozenset({"authority", "receipt_contract", "revision"})
AI_STAGE_FIELDS = frozenset(
    {
        "candidate_image_digest",
        "commands",
        "data_authority_sha256",
        "depends_on",
        "execution_order",
        "model_snapshot",
        "qualification_contract",
        "retry_limits",
        "revision",
        "rollback_revision",
        "secret_presence",
        "stop_conditions",
    }
)
TWO_STAGE_PATH = ".tmp/LAUNCH_AUTHORIZATION_TWO_STAGE_V1.md"
DATA_RECEIPT_PATH = ".tmp/DATA_SCOPE_REVISION_RECEIPT.json"
QUALIFICATION_RECEIPT_PATH = ".tmp/OPENAI_MODEL_QUALIFICATION_RECEIPT.json"
APPROVED_AI_LIMITS = {
    "daily_attempt_limit": 120,
    "monthly_token_limit": 150_000,
    "max_concurrent_turns": 15,
    "session_attempt_limit_per_minute": 3,
    "global_attempt_limit_per_minute": 20,
    "demo_session_rate_limit_per_hour": 50,
}
UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
FORBIDDEN_COMMAND_FLAGS = frozenset(
    {
        "--account-key",
        "--api-key",
        "--client-secret",
        "--connection-string",
        "--key",
        "--password",
        "--postgres-password",
        "--registry-password",
        "--sas-token",
    }
)
class AuthorizationInvalid(RuntimeError):
    """The launch package is incomplete, unsafe, or not externally bound."""


def _exact_dict(
    value: object,
    fields: frozenset[str],
    error: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise AuthorizationInvalid(error)
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise AuthorizationInvalid("authorization_json_duplicate_key")
        result[name] = value
    return result


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
        value,
    ):
        raise AuthorizationInvalid("authorization_identity_invalid")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AuthorizationInvalid("authorization_identity_invalid") from error


def _bounded_name(value: object, *, maximum: int = 90) -> bool:
    return isinstance(value, str) and bool(
        re.fullmatch(rf"[A-Za-z0-9][A-Za-z0-9._()-]{{1,{maximum - 1}}}", value)
    )


def _finite_decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise AuthorizationInvalid("authorization_limits_invalid")
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise AuthorizationInvalid("authorization_limits_invalid") from error
    if not normalized.is_finite() or normalized < 0:
        raise AuthorizationInvalid("authorization_limits_invalid")
    return normalized


def _validate_resources(value: object) -> None:
    resources = _exact_dict(
        value,
        EXPECTED_RESOURCE_FIELDS,
        "authorization_resources_invalid",
    )
    application = _exact_dict(
        resources["application"],
        frozenset(
            {"count", "cpu", "max_replicas", "memory", "min_replicas", "sku"}
        ),
        "authorization_resources_invalid",
    )
    monitoring = _exact_dict(
        resources["monitoring"],
        frozenset({"log_retention_days"}),
        "authorization_resources_invalid",
    )
    postgres = _exact_dict(
        resources["postgres"],
        frozenset(
            {
                "backup_retention_days",
                "count",
                "public_network",
                "sku",
                "storage_gb",
                "tier",
                "version",
            }
        ),
        "authorization_resources_invalid",
    )
    storage = _exact_dict(
        resources["storage"],
        frozenset({"container", "count", "public_access", "sku"}),
        "authorization_resources_invalid",
    )
    if (
        application["count"] != 1
        or application["sku"] != "Consumption"
        or application["cpu"] != "0.5"
        or application["memory"] != "1Gi"
        or application["min_replicas"] != 1
        or application["max_replicas"] != 1
        or type(monitoring["log_retention_days"]) is not int
        or not 30 <= monitoring["log_retention_days"] <= 730
        or postgres["count"] != 1
        or postgres["public_network"] is not False
        or postgres["sku"] != "Standard_B1ms"
        or postgres["tier"] not in {"Burstable", "GeneralPurpose", "MemoryOptimized"}
        or postgres["version"] != "16"
        or type(postgres["storage_gb"]) is not int
        or not 32 <= postgres["storage_gb"] <= 16_384
        or type(postgres["backup_retention_days"]) is not int
        or not 7 <= postgres["backup_retention_days"] <= 35
        or storage["count"] != 1
        or storage["public_access"] is not False
        or storage["container"] != "synthetic-demo"
        or not _bounded_name(storage["sku"], maximum=64)
    ):
        raise AuthorizationInvalid("authorization_resources_invalid")


def _command_tokens(command: object) -> tuple[str, ...]:
    if (
        not isinstance(command, str)
        or not 1 <= len(command) <= 2_000
        or "\n" in command
        or "\r" in command
        or re.search(r"[;&|`$<>\\]", command)
        or SECRET_PATTERN.search(command)
    ):
        raise AuthorizationInvalid("authorization_commands_invalid")
    try:
        tokens = tuple(shlex.split(command, posix=True))
    except ValueError as error:
        raise AuthorizationInvalid("authorization_commands_invalid") from error
    if not tokens or any(not token or len(token) > 300 for token in tokens):
        raise AuthorizationInvalid("authorization_commands_invalid")
    if any(token.lower().split("=", 1)[0] in FORBIDDEN_COMMAND_FLAGS for token in tokens):
        raise AuthorizationInvalid("authorization_commands_invalid")
    return tokens


def _expected_commands(
    authority: dict[str, Any],
    *,
    legacy_update: bool = False,
) -> dict[str, tuple[tuple[str, ...], ...]]:
    subscription_id = authority["subscription_id"]
    resource_group = authority["resource_group"]
    generated = authority["generated_names"]
    release = authority["release"]
    resources = authority["resources"]
    ai_limits = authority["ai_limits"]
    public_url = (
        authority["public_url"].rstrip("/")
        if isinstance(authority["public_url"], str)
        else None
    )
    registry_image = (
        f"{generated['registry_name']}.azurecr.io/"
        f"{generated['image_repository']}@{release['image_digest']}"
    )
    rollback_image = (
        f"{generated['registry_name']}.azurecr.io/"
        f"{generated['image_repository']}@{release['rollback_image_digest']}"
    )
    deployment_parameters = (
        "--parameters",
        "infra/environments/demo.bicepparam",
        "deploymentEnabled=true",
        f"namePrefix={generated['name_prefix']}",
        f"location={authority['region']}",
        f"containerImage={registry_image}",
        f"syntheticManifestSha256={release['synthetic_manifest_sha256']}",
        f"syntheticDatasetVersionId={release['synthetic_dataset_version_id']}",
        f"registryName={generated['registry_name']}",
        f"postgresAdministratorLogin={generated['postgres_administrator_login']}",
        f"postgresServerName={generated['postgres_server']}",
        f"storageAccountName={generated['storage_account']}",
        f"storageSku={resources['storage']['sku']}",
        f"postgresSkuName={resources['postgres']['sku']}",
        f"postgresTier={resources['postgres']['tier']}",
        f"postgresStorageSizeGb={resources['postgres']['storage_gb']}",
        "postgresBackupRetentionDays="
        f"{resources['postgres']['backup_retention_days']}",
        f"logRetentionDays={resources['monitoring']['log_retention_days']}",
        f"aiDailyAttemptLimit={ai_limits['daily_attempt_limit']}",
        f"aiMaxConcurrentTurns={ai_limits['max_concurrent_turns']}",
        "aiSessionAttemptLimitPerMinute="
        f"{ai_limits['session_attempt_limit_per_minute']}",
        "aiGlobalAttemptLimitPerMinute="
        f"{ai_limits['global_attempt_limit_per_minute']}",
        "demoSessionRateLimitPerHour="
        f"{ai_limits['demo_session_rate_limit_per_hour']}",
    )
    deployment_prefix = (
        "az",
        "deployment",
        "group",
        "create",
        "--subscription",
        subscription_id,
        "--resource-group",
        resource_group,
    )
    deployment_suffix = ("--mode", "Incremental", "--output", "json")
    hosted_check = (
        ".venv/bin/python",
        "scripts/run_hosted_check.py",
        "--subscription",
        subscription_id,
        "--resource-group",
        resource_group,
        "--app",
        generated["container_app"],
        "--image",
        registry_image,
    )
    if public_url is not None:
        hosted_check += ("--expected-url", public_url)
    health = hosted_check + ("--check", "health")
    browser_core = hosted_check + ("--check", "browser", "--scenario", "core")
    browser_paid = hosted_check + ("--check", "browser", "--scenario", "paid-ai")
    capacity = hosted_check + ("--check", "capacity")
    expiry = (
        ".venv/bin/python",
        "scripts/verify_hosted_expiry.py",
        "--subscription",
        subscription_id,
        "--resource-group",
        resource_group,
        "--app",
        generated["container_app"],
        "--image",
        registry_image,
        "--session-job",
        generated["session_maintenance_job"],
    )
    if public_url is not None:
        expiry += ("--expected-url", public_url)
    preflight = (
        ".venv/bin/python",
        "scripts/azure_recovery_preflight.py",
        "--subscription",
        subscription_id,
        "--resource-group",
        resource_group,
        "--region",
        authority["region"],
        "--target-mode",
        authority["recovery"]["target_mode"],
        "--app",
        generated["container_app"],
        "--environment",
        generated["container_environment"],
        "--application-insights",
        generated["application_insights"],
        "--log-workspace",
        generated["log_workspace"],
        "--prepare-job",
        generated["migration_job"],
        "--seed-job",
        generated["seed_job"],
        "--session-job",
        generated["session_maintenance_job"],
        "--storage-job",
        generated["storage_maintenance_job"],
        "--virtual-network",
        generated["virtual_network"],
        "--postgres-dns-zone",
        generated["postgres_dns_zone"],
        "--postgres-server",
        generated["postgres_server"],
        "--postgres-backup-days",
        str(resources["postgres"]["backup_retention_days"]),
        "--postgres-sku",
        resources["postgres"]["sku"],
        "--postgres-tier",
        resources["postgres"]["tier"],
        "--postgres-storage-gb",
        str(resources["postgres"]["storage_gb"]),
        "--postgres-version",
        resources["postgres"]["version"],
        "--storage-account",
        generated["storage_account"],
        "--storage-sku",
        resources["storage"]["sku"],
        "--blob-retention-days",
        str(authority["recovery"]["blob_soft_delete_days"]),
        "--application-sku",
        resources["application"]["sku"],
        "--application-cpu",
        resources["application"]["cpu"],
        "--application-memory",
        resources["application"]["memory"],
        "--application-min-replicas",
        str(resources["application"]["min_replicas"]),
        "--application-max-replicas",
        str(resources["application"]["max_replicas"]),
        "--log-retention-days",
        str(resources["monitoring"]["log_retention_days"]),
        "--registry",
        generated["registry_name"],
        "--registry-identity",
        generated["registry_identity"],
        "--repository",
        generated["image_repository"],
        "--image-digest",
        release["image_digest"],
        "--rollback-image-digest",
        release["rollback_image_digest"],
        "--current-image-state",
        (
            "pending-publication"
            if authority["external_publication"]["registry_publish"]
            else "present"
        ),
    )
    if public_url is not None:
        preflight += ("--public-url", public_url)
    if authority["recovery"]["target_mode"] == "update":
        preflight += (
            "--observed-current-image-digest",
            authority["recovery"]["observed_current_image_digest"],
        )
    phase1_fence = (
        ".venv/bin/python",
        "scripts/verify_phase1_fence.py",
        "--subscription",
        subscription_id,
        "--resource-group",
        resource_group,
        "--app",
        generated["container_app"],
        "--image",
        registry_image,
        "--prepare-job",
        generated["migration_job"],
        "--seed-job",
        generated["seed_job"],
        "--session-job",
        generated["session_maintenance_job"],
        "--storage-job",
        generated["storage_maintenance_job"],
        "--storage-account",
        generated["storage_account"],
        "--blob-container",
        "synthetic-demo",
        "--synthetic-manifest-sha256",
        release["synthetic_manifest_sha256"],
        "--synthetic-dataset-version-id",
        release["synthetic_dataset_version_id"],
        "--environment",
        generated["container_environment"],
        "--ai-enabled",
        str(ai_limits["enabled"]).lower(),
        "--ai-daily-attempt-limit",
        str(ai_limits["daily_attempt_limit"]),
        "--ai-monthly-token-limit",
        str(ai_limits["monthly_token_limit"]),
        "--ai-max-concurrent-turns",
        str(ai_limits["max_concurrent_turns"]),
        "--ai-session-attempt-limit-per-minute",
        str(ai_limits["session_attempt_limit_per_minute"]),
        "--ai-global-attempt-limit-per-minute",
        str(ai_limits["global_attempt_limit_per_minute"]),
        "--demo-session-rate-limit-per-hour",
        str(ai_limits["demo_session_rate_limit_per_hour"]),
        "--mode",
        "initial",
    )

    def job_command(name: str, timeout_seconds: int) -> tuple[tuple[str, ...], ...]:
        return (
            (
                ".venv/bin/python",
                "scripts/run_azure_job.py",
                "--subscription",
                subscription_id,
                "--resource-group",
                resource_group,
                "--job",
                name,
                "--timeout-seconds",
                str(timeout_seconds),
            ),
        )

    def update_job_command(
        name: str,
        *,
        container_name: str,
        arguments: tuple[str, ...],
    ) -> tuple[str, ...]:
        return (
            ".venv/bin/python",
            "scripts/update_azure_job_binding.py",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--job",
            name,
            "--image",
            registry_image,
            "--container-name",
            container_name,
            "--command-json",
            json.dumps(["python"], separators=(",", ":")),
            "--arguments-json",
            json.dumps(list(arguments), separators=(",", ":")),
        )

    phase1_deploy = (
        deployment_prefix
        + ("--name", f"{generated['name_prefix']}-phase1")
        + deployment_parameters
        + (
            "applicationEnabled=false",
            f"applicationRevisionSuffix=prep-{release['image_digest'][7:14]}",
            f"aiChatEnabled={str(ai_limits['enabled']).lower()}",
            f"aiMonthlyTokenLimit={ai_limits['monthly_token_limit']}",
        )
        + deployment_suffix
    )
    activate_preflight = list(preflight)
    mode_index = activate_preflight.index(authority["recovery"]["target_mode"])
    activate_preflight[mode_index] = "prepared"
    if "--public-url" in activate_preflight:
        url_index = activate_preflight.index("--public-url")
        del activate_preflight[url_index : url_index + 2]
    if "--observed-current-image-digest" in activate_preflight:
        observed_index = activate_preflight.index("--observed-current-image-digest")
        del activate_preflight[observed_index : observed_index + 2]
    state_index = activate_preflight.index("--current-image-state") + 1
    activate_preflight[state_index] = "present"
    activate_fence = phase1_fence[:-1] + (
        "activate",
        "--not-before",
        authority["issued_at"],
    )
    final_suffix = release["image_digest"][7:19]

    def application_deploy(
        *,
        name: str,
        revision_suffix: str,
        ai_enabled: bool,
        monthly_token_limit: int,
    ) -> tuple[str, ...]:
        return (
            deployment_prefix
            + ("--name", name)
            + deployment_parameters
            + (
                "applicationEnabled=true",
                f"applicationRevisionSuffix={revision_suffix}",
                f"aiChatEnabled={str(ai_enabled).lower()}",
                f"aiMonthlyTokenLimit={monthly_token_limit}",
            )
            + deployment_suffix
        )

    def failure_check(scenario: str) -> tuple[str, ...]:
        command = (
            ".venv/bin/python",
            "scripts/run_hosted_failure_check.py",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--app",
            generated["container_app"],
            "--image",
            registry_image,
            "--authorization-id",
            authority["authorization_id"],
            "--scenario",
            scenario,
            "--normal-ai-enabled",
            str(ai_limits["enabled"]).lower(),
            "--normal-monthly-token-limit",
            str(ai_limits["monthly_token_limit"]),
        )
        if public_url is not None:
            command += ("--expected-url", public_url)
        for parameter in deployment_parameters[2:]:
            command += ("--parameter", parameter)
        return command

    phase2_fence = phase1_fence[:-1] + (
        "phase2",
        "--not-before",
        authority["issued_at"],
    )
    readback = (
        ".venv/bin/python",
        "scripts/run_azure_readback.py",
        "--subscription",
        subscription_id,
        "--resource-group",
        resource_group,
        "--app",
        generated["container_app"],
        "--current-image",
        registry_image,
        "--authorization-id",
        authority["authorization_id"],
        "--ai-enabled",
        str(ai_limits["enabled"]).lower(),
    )
    candidate_publish = (
        (
            ".venv/bin/python",
            "scripts/publish_registry_image.py",
            "--subscription",
            subscription_id,
            "--registry",
            generated["registry_name"],
            "--repository",
            generated["image_repository"],
            "--candidate-git-sha",
            release["git_sha"],
            "--authorization-id",
            authority["authorization_id"],
            "--expected-digest",
            release["image_digest"],
            "--image-input-sha256",
            release["image_input_sha256"],
        ),
    )
    rollback_publish = (
        (
            ".venv/bin/python",
            "scripts/publish_registry_image.py",
            "--subscription",
            subscription_id,
            "--registry",
            generated["registry_name"],
            "--repository",
            generated["image_repository"],
            "--candidate-git-sha",
            release["rollback_git_sha"],
            "--authorization-id",
            authority["authorization_id"],
            "--expected-digest",
            release["rollback_image_digest"],
            "--image-input-sha256",
            release["rollback_image_input_sha256"],
        ),
    )
    rollback_already_present = (
        not legacy_update
        and authority["recovery"]["target_mode"] == "update"
        and authority["recovery"]["observed_current_image_digest"]
        == release["rollback_image_digest"]
    )
    registry_publish = (
        candidate_publish
        + (() if rollback_already_present else rollback_publish)
        if authority["external_publication"]["registry_publish"]
        else ()
    )
    registry_verify: tuple[tuple[str, ...], ...] = (
        (
            ".venv/bin/python",
            "scripts/verify_registry_image.py",
            "--subscription",
            subscription_id,
            "--registry",
            generated["registry_name"],
            "--repository",
            generated["image_repository"],
            "--source-git-sha",
            release["git_sha"],
            "--expected-digest",
            release["image_digest"],
            "--image-input-sha256",
            release["image_input_sha256"],
        ),
        (
            ".venv/bin/python",
            "scripts/verify_registry_image.py",
            "--subscription",
            subscription_id,
            "--registry",
            generated["registry_name"],
            "--repository",
            generated["image_repository"],
            "--source-git-sha",
            release["rollback_git_sha"],
            "--expected-digest",
            release["rollback_image_digest"],
            "--image-input-sha256",
            release["rollback_image_input_sha256"],
        ),
    )
    if authority["external_publication"]["registry_publish"]:
        verified_preflight = list(preflight)
        verified_state_index = verified_preflight.index("--current-image-state") + 1
        verified_preflight[verified_state_index] = "present"
        registry_verify += (tuple(verified_preflight),)
    update_target = (
        authority["recovery"]["target_mode"] == "update" and not legacy_update
    )
    return {
        "activate": () if update_target else (tuple(activate_preflight), activate_fence),
        "browser_acceptance": (browser_core,),
        "budget_failure": (
            (failure_check("budget"),) if ai_limits["enabled"] else ()
        ),
        "capacity": (capacity,),
        "deploy": (
            application_deploy(
                name=f"{generated['name_prefix']}-phase2",
                revision_suffix=final_suffix,
                ai_enabled=ai_limits["enabled"],
                monthly_token_limit=ai_limits["monthly_token_limit"],
            ),
            job_command(generated["session_maintenance_job"], 600)[0],
            job_command(generated["storage_maintenance_job"], 600)[0],
            phase2_fence,
        ),
        "expiry": (expiry,),
        "health": (health,),
        "migrate": job_command(generated["migration_job"], 900),
        "paid_ai_smoke": (
            (browser_paid,)
            if authority["external_publication"]["paid_ai_smoke"]
            else ()
        ),
        "preflight": (preflight,),
        "provision": (
            (
                update_job_command(
                    generated["migration_job"],
                    container_name="prepare",
                    arguments=("scripts/prepare_cloud.py",),
                ),
                update_job_command(
                    generated["seed_job"],
                    container_name="seed",
                    arguments=(
                        "scripts/seed_demo.py",
                        "tests/fixtures/synthetic/v1",
                        "--expected-manifest-sha256",
                        release["synthetic_manifest_sha256"],
                        "--expected-dataset-version-id",
                        release["synthetic_dataset_version_id"],
                    ),
                ),
            )
            if update_target
            else (
                (
                    "az",
                    "provider",
                    "register",
                    "--subscription",
                    subscription_id,
                    "--namespace",
                    "Microsoft.App",
                    "--wait",
                    "--only-show-errors",
                    "--output",
                    "none",
                ),
                phase1_deploy,
                phase1_fence,
            )
        ),
        "provider_failure": (
            (failure_check("provider-unavailable"),)
            if ai_limits["enabled"]
            else ()
        ),
        "registry_publish": registry_publish,
        "registry_verify": registry_verify,
        "restart_readback": (
            readback
            + (
                "--operation",
                "restart",
                "--revision",
                generated["application_revision"],
            ),
        ),
        "rollback": (
            readback
            + (
                "--operation",
                "rollback",
                "--rollback-image",
                rollback_image,
            ),
        ),
        "seed": job_command(generated["seed_job"], 1_800),
    }


def data_authority_sha256(authority: dict[str, Any]) -> str:
    """Hash the complete AI-disabled data-stage authority canonically."""

    return hashlib.sha256(
        json.dumps(
            authority,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _expected_ai_transition_commands(
    package: dict[str, Any],
) -> dict[str, list[str]]:
    data_stage = package["data_scope_revision"]
    authority = data_stage["authority"]
    ai_stage = package["ai_revision"]
    generated = authority["generated_names"]
    release = authority["release"]
    image = (
        f"{generated['registry_name']}.azurecr.io/"
        f"{generated['image_repository']}@{release['image_digest']}"
    )
    deploy = list(_expected_commands(authority)["deploy"][0])
    name_index = deploy.index("--name") + 1
    deploy[name_index] = f"{generated['name_prefix']}-ai"
    for index, token in enumerate(deploy):
        if token.startswith("applicationRevisionSuffix="):
            deploy[index] = f"applicationRevisionSuffix={ai_stage['revision'].split('--', 1)[1]}"
        elif token == "aiChatEnabled=false":
            deploy[index] = "aiChatEnabled=true"
    phase2_fence = list(_expected_commands(authority)["deploy"][-1])
    enabled_index = phase2_fence.index("--ai-enabled") + 1
    phase2_fence[enabled_index] = "true"
    phase2_fence.extend(("--expected-revision", ai_stage["revision"]))
    hosted = (
        ".venv/bin/python",
        "scripts/run_hosted_check.py",
        "--subscription",
        authority["subscription_id"],
        "--resource-group",
        authority["resource_group"],
        "--app",
        generated["container_app"],
        "--image",
        image,
    )
    if authority["public_url"] is not None:
        hosted += ("--expected-url", authority["public_url"])
    paid_smoke = hosted + ("--check", "browser", "--scenario", "paid-ai")
    hosted_core = hosted + ("--check", "browser", "--scenario", "core")
    rollback_activate = (
        "az",
        "containerapp",
        "revision",
        "activate",
        "--subscription",
        authority["subscription_id"],
        "--resource-group",
        authority["resource_group"],
        "--name",
        generated["container_app"],
        "--revision",
        data_stage["revision"],
        "--only-show-errors",
        "--output",
        "json",
    )
    rollback_traffic = (
        "az",
        "containerapp",
        "ingress",
        "traffic",
        "set",
        "--subscription",
        authority["subscription_id"],
        "--resource-group",
        authority["resource_group"],
        "--name",
        generated["container_app"],
        "--revision-weight",
        f"{data_stage['revision']}=100",
        "--only-show-errors",
        "--output",
        "json",
    )
    rollback_deactivate = (
        "az",
        "containerapp",
        "revision",
        "deactivate",
        "--subscription",
        authority["subscription_id"],
        "--resource-group",
        authority["resource_group"],
        "--name",
        generated["container_app"],
        "--revision",
        ai_stage["revision"],
        "--only-show-errors",
        "--output",
        "json",
    )
    rollback_secret = (
        "az",
        "containerapp",
        "secret",
        "remove",
        "--subscription",
        authority["subscription_id"],
        "--resource-group",
        authority["resource_group"],
        "--name",
        generated["container_app"],
        "--secret-names",
        "openai-api-key",
        "--only-show-errors",
        "--output",
        "json",
    )
    return {
        "deploy": [shlex.join(deploy), shlex.join(phase2_fence)],
        "model_qualification": [
            ".venv/bin/python scripts/qualify_openai_model.py "
            "--execute-paid-qualification "
            f"--receipt {QUALIFICATION_RECEIPT_PATH}"
        ],
        "paid_ai_smoke": [shlex.join(paid_smoke)],
        "receipt_verification": [
            ".venv/bin/python scripts/verify_stage_receipts.py "
            f"--authorization {TWO_STAGE_PATH} "
            f"--data-receipt {DATA_RECEIPT_PATH} "
            f"--qualification-receipt {QUALIFICATION_RECEIPT_PATH}"
        ],
        "rollback_on_failure": [
            shlex.join(rollback_activate),
            shlex.join(rollback_traffic),
            shlex.join(rollback_deactivate),
            shlex.join(rollback_secret),
            shlex.join(hosted_core),
        ],
    }


def _expected_execution_order(
    authority: dict[str, Any], *, legacy_update: bool = False
) -> tuple[str, ...]:
    order = ["preflight"]
    if authority["external_publication"]["registry_publish"]:
        order.append("registry_publish")
    order.extend(("registry_verify", "provision", "migrate", "seed"))
    if (
        authority["recovery"]["target_mode"] != "update"
        or legacy_update
    ):
        order.append("activate")
    if authority["ai_limits"]["enabled"]:
        order.extend(("budget_failure", "provider_failure"))
    order.extend(("deploy", "health", "browser_acceptance", "capacity", "expiry"))
    if authority["external_publication"]["paid_ai_smoke"]:
        order.append("paid_ai_smoke")
    order.extend(("restart_readback", "rollback"))
    return tuple(order)


def _validate_commands(value: object, authority: dict[str, Any]) -> None:
    commands = _exact_dict(
        value,
        EXPECTED_COMMAND_FIELDS,
        "authorization_commands_invalid",
    )
    legacy_update = (
        authority["recovery"]["target_mode"] == "update"
        and bool(commands["activate"])
    )
    expected = _expected_commands(authority, legacy_update=legacy_update)
    for stage, entries in commands.items():
        if not isinstance(entries, list) or len(entries) > 10:
            raise AuthorizationInvalid("authorization_commands_invalid")
        parsed = tuple(_command_tokens(command) for command in entries)
        if parsed != expected[stage]:
            raise AuthorizationInvalid("authorization_commands_invalid")


def _git_bytes(*arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise AuthorizationInvalid("authorization_git_authority_invalid") from error
    if len(result.stdout) > 1_000_000:
        raise AuthorizationInvalid("authorization_git_authority_invalid")
    return result.stdout


def _release_attestation_path(release: dict[str, Any]) -> str:
    try:
        return attestation_path(str(release["git_sha"]))
    except (KeyError, ReleaseManifestInvalid) as error:
        raise AuthorizationInvalid("authorization_git_authority_invalid") from error


def _validate_attestation_authority(release: dict[str, Any]) -> None:
    attestation_sha = str(release["attestation_git_sha"])
    if not re.fullmatch(r"[0-9a-f]{40}", attestation_sha):
        raise AuthorizationInvalid("authorization_git_sha_invalid")
    parent = _git_bytes("rev-parse", f"{attestation_sha}^").decode().strip()
    paths = _git_bytes(
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        attestation_sha,
    ).decode().splitlines()
    path = _release_attestation_path(release)
    committed_manifest = _git_bytes("show", f"{attestation_sha}:{path}")
    if (
        parent != release["git_sha"]
        or paths != [path]
        or hashlib.sha256(committed_manifest).hexdigest()
        != release["local_manifest_sha256"]
    ):
        raise AuthorizationInvalid("authorization_git_authority_invalid")


def _validate_candidate_inputs(
    release: dict[str, Any],
    *,
    git_reader: Any = _git_bytes,
) -> None:
    """Bind every launch input to the exact clean candidate/attestation pair."""

    candidate = str(release["git_sha"])
    attestation = str(release["attestation_git_sha"])
    rollback = str(release["rollback_git_sha"])
    path = _release_attestation_path(release)
    try:
        status = git_reader(
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            "bizpulse",
        )
        head = git_reader("rev-parse", "HEAD").decode().strip()
        changed = git_reader(
            "diff",
            "--name-only",
            candidate,
            attestation,
            "--",
            "bizpulse",
        ).decode().splitlines()
        candidate_paths = frozenset(
            git_reader(
                "ls-tree",
                "-r",
                "--name-only",
                candidate,
                "--",
                "bizpulse",
            )
            .decode()
            .splitlines()
        )
        git_reader("merge-base", "--is-ancestor", rollback, candidate)
        rollback_readiness = git_reader(
            "show", f"{rollback}:bizpulse/src/db/readiness.py"
        )
        rollback_migration = git_reader(
            "show", f"{rollback}:bizpulse/alembic/versions/0008_ai_budget_ledger.py"
        )
        rollback_dockerfile = git_reader(
            "show", f"{rollback}:bizpulse/Dockerfile"
        )
    except (KeyError, UnicodeDecodeError, OSError, subprocess.SubprocessError) as error:
        raise AuthorizationInvalid("authorization_git_authority_invalid") from error
    if status:
        raise AuthorizationInvalid("authorization_candidate_dirty")
    if (
        head != attestation
        or changed != [path]
        or not REQUIRED_CANDIDATE_PATHS.issubset(candidate_paths)
        or b'EXPECTED_SCHEMA_REVISION = "0008_ai_budget_ledger"'
        not in rollback_readiness
        or b'revision: str = "0008_ai_budget_ledger"' not in rollback_migration
        or b"--no-access-log" not in rollback_dockerfile
    ):
        raise AuthorizationInvalid("authorization_git_authority_invalid")
    for field, path in CANDIDATE_HASH_PATHS.items():
        try:
            payload = git_reader("show", f"{candidate}:{path}")
        except (OSError, subprocess.SubprocessError) as error:
            raise AuthorizationInvalid("authorization_git_authority_invalid") from error
        if hashlib.sha256(payload).hexdigest() != release[field]:
            raise AuthorizationInvalid("authorization_git_authority_invalid")


def _validate_release_manifest_binding(release: dict[str, Any]) -> None:
    try:
        source = (REPOSITORY_ROOT / _release_attestation_path(release)).read_bytes()
        local_attestation = json.loads(
            source,
            object_pairs_hook=_unique_object,
        )
        manifest_fixture = local_attestation["synthetic_fixture"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise AuthorizationInvalid("authorization_git_authority_invalid") from error
    if (
        hashlib.sha256(source).hexdigest() != release["local_manifest_sha256"]
        or local_attestation.get("candidate_git_sha") != release["git_sha"]
        or local_attestation.get("migration_head") != release["migration_head"]
        or not isinstance(manifest_fixture, dict)
        or manifest_fixture.get("manifest_sha256")
        != release["synthetic_manifest_sha256"]
        or local_attestation.get("image_input_sha256")
        != release["image_input_sha256"]
        or local_attestation.get("rollback_compatible_prior_sha")
        != release["rollback_git_sha"]
        or local_attestation.get("rollback_image_input_sha256")
        != release["rollback_image_input_sha256"]
    ):
        raise AuthorizationInvalid("authorization_git_authority_invalid")
    _validate_attestation_authority(release)


def _ordered_strings(value: object, expected: tuple[str, ...], error: str) -> None:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) for item in value)
        or tuple(value) != expected
    ):
        raise AuthorizationInvalid(error)


def _load_authorization_bytes(
    source_bytes: bytes,
    *,
    now: datetime,
) -> dict[str, Any]:
    try:
        source = source_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AuthorizationInvalid("authorization_document_invalid") from error
    document = re.fullmatch(
        r"# NEWCaostone Launch Authorization\n\n```json\n(?P<payload>.*)\n```\n?",
        source,
        flags=re.DOTALL,
    )
    if document is None:
        raise AuthorizationInvalid("authorization_document_invalid")
    try:
        payload = json.loads(
            document.group("payload"),
            object_pairs_hook=_unique_object,
        )
    except json.JSONDecodeError as error:
        raise AuthorizationInvalid("authorization_json_invalid") from error
    authority = _exact_dict(payload, EXPECTED_FIELDS, "authorization_fields_invalid")
    issued_at = _timestamp(authority["issued_at"])
    expires_at = _timestamp(authority["expires_at"])
    if (
        authority["schema_version"] != "newcaostone.launch-authorization.v4"
        or not isinstance(authority["authorization_id"], str)
        or UUID_PATTERN.fullmatch(authority["authorization_id"]) is None
        or not isinstance(authority["subscription_id"], str)
        or UUID_PATTERN.fullmatch(authority["subscription_id"]) is None
        or expires_at <= issued_at
        or expires_at - issued_at > timedelta(days=7)
    ):
        raise AuthorizationInvalid("authorization_identity_invalid")
    if now < issued_at or now >= expires_at:
        raise AuthorizationInvalid("authorization_expired")
    parsed_url = (
        urlsplit(authority["public_url"])
        if isinstance(authority["public_url"], str)
        else None
    )
    if parsed_url is not None and (
        parsed_url.scheme != "https"
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.query
        or parsed_url.fragment
        or parsed_url.path not in {"", "/"}
    ):
        raise AuthorizationInvalid("authorization_url_invalid")
    if authority["public_url_source"] not in {
        "azure_containerapp_fqdn",
        "exact",
    }:
        raise AuthorizationInvalid("authorization_url_invalid")
    if (
        not re.fullmatch(r"[a-z][a-z0-9]{2,31}", str(authority["region"]))
        or not re.fullmatch(
            r"[a-z](?:[a-z0-9-]{1,61}[a-z0-9])?",
            str(authority["resource_group"]),
        )
    ):
        raise AuthorizationInvalid("authorization_target_invalid")

    generated = _exact_dict(
        authority["generated_names"],
        EXPECTED_GENERATED_NAMES,
        "authorization_generated_names_invalid",
    )
    if any(not _bounded_name(value, maximum=63) for value in generated.values()):
        raise AuthorizationInvalid("authorization_generated_names_invalid")
    name_prefix = generated["name_prefix"]
    expected_generated = {
        "application_insights": f"{name_prefix}-insights",
        "container_app": f"{name_prefix}-app",
        "container_environment": f"{name_prefix}-env",
        "log_workspace": f"{name_prefix}-logs",
        "migration_job": f"{name_prefix}-prepare",
        "seed_job": f"{name_prefix}-seed",
        "session_maintenance_job": f"{name_prefix}-sessions",
        "storage_maintenance_job": f"{name_prefix}-storage",
        "virtual_network": f"{name_prefix}-vnet",
        "registry_identity": f"{name_prefix}-registry",
    }
    if (
        not re.fullmatch(r"[a-z](?:[a-z0-9-]{1,16}[a-z0-9])?", name_prefix)
        or "--" in name_prefix
        or any(generated[name] != expected for name, expected in expected_generated.items())
        or not re.fullmatch(r"[a-z0-9]{3,24}", generated["storage_account"])
        or not re.fullmatch(r"[a-z0-9]{5,50}", generated["registry_name"])
        or not re.fullmatch(r"[a-z0-9][a-z0-9._/-]{1,127}", generated["image_repository"])
        or not re.fullmatch(
            r"[a-z](?:[a-z0-9-]{1,61}[a-z0-9])?",
            generated["postgres_server"],
        )
        or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]{2,62}",
            generated["postgres_administrator_login"],
        )
        or (
            parsed_url is not None
            and parsed_url.hostname.split(".", 1)[0] != generated["container_app"]
        )
        or generated["postgres_dns_zone"] != "private.postgres.database.azure.com"
    ):
        raise AuthorizationInvalid("authorization_generated_names_invalid")

    release = _exact_dict(
        authority["release"],
        EXPECTED_RELEASE_FIELDS,
        "authorization_release_fields_invalid",
    )
    if not re.fullmatch(r"[0-9a-f]{40}", str(release["git_sha"])):
        raise AuthorizationInvalid("authorization_git_sha_invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", str(release["rollback_git_sha"])):
        raise AuthorizationInvalid("authorization_git_sha_invalid")
    for field in ("image_digest", "rollback_image_digest"):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(release[field])):
            raise AuthorizationInvalid("authorization_digest_invalid")
    if (
        re.fullmatch(r"[0-9]{4}_[a-z0-9_]+", str(release["migration_head"]))
        is None
        or not re.fullmatch(
            r"[0-9a-f]{64}", str(release["synthetic_manifest_sha256"])
        )
        or not re.fullmatch(
            r"[0-9a-f]{64}", str(release["local_manifest_sha256"])
        )
        or release["image_digest"] == release["rollback_image_digest"]
        or release["git_sha"] == release["rollback_git_sha"]
        or release["synthetic_dataset_version_id"]
        != str(
            uuid5(
                SEED_NAMESPACE,
                f"version:{release['synthetic_manifest_sha256']}",
            )
        )
        or generated["application_revision"]
        != f"{generated['container_app']}--{release['image_digest'][7:19]}"
        or not re.fullmatch(r"[0-9a-f]{64}", str(release["image_input_sha256"]))
        or not re.fullmatch(
            r"[0-9a-f]{64}", str(release["rollback_image_input_sha256"])
        )
    ):
        raise AuthorizationInvalid("authorization_release_authority_invalid")
    try:
        infra_hashes = {
            "azure_job_runner_sha256": hashlib.sha256(
                AZURE_JOB_RUNNER.read_bytes()
            ).hexdigest(),
            "azure_preflight_sha256": hashlib.sha256(
                AZURE_PREFLIGHT.read_bytes()
            ).hexdigest(),
            "azure_readback_sha256": hashlib.sha256(
                AZURE_READBACK.read_bytes()
            ).hexdigest(),
            "browser_gate_sha256": hashlib.sha256(BROWSER_GATE.read_bytes()).hexdigest(),
            "hosted_check_sha256": hashlib.sha256(
                HOSTED_CHECK.read_bytes()
            ).hexdigest(),
            "hosted_capacity_sha256": hashlib.sha256(
                HOSTED_CAPACITY.read_bytes()
            ).hexdigest(),
            "hosted_health_sha256": hashlib.sha256(
                HOSTED_HEALTH.read_bytes()
            ).hexdigest(),
            "infra_bicep_sha256": hashlib.sha256(INFRA_BICEP.read_bytes()).hexdigest(),
            "infra_parameters_sha256": hashlib.sha256(
                INFRA_PARAMETERS.read_bytes()
            ).hexdigest(),
            "phase1_fence_sha256": hashlib.sha256(
                PHASE1_FENCE.read_bytes()
            ).hexdigest(),
            "registry_publisher_sha256": hashlib.sha256(
                REGISTRY_PUBLISHER.read_bytes()
            ).hexdigest(),
            "registry_verifier_sha256": hashlib.sha256(
                REGISTRY_VERIFIER.read_bytes()
            ).hexdigest(),
            "synthetic_manifest_sha256": hashlib.sha256(
                SYNTHETIC_MANIFEST.read_bytes()
            ).hexdigest(),
        }
    except OSError as error:
        raise AuthorizationInvalid("authorization_infra_hash_invalid") from error
    if any(release[name] != expected for name, expected in infra_hashes.items()):
        raise AuthorizationInvalid("authorization_infra_hash_invalid")
    _validate_resources(authority["resources"])
    ai_limits = _exact_dict(
        authority["ai_limits"],
        EXPECTED_AI_LIMIT_FIELDS,
        "authorization_ai_limits_invalid",
    )
    if (
        type(ai_limits["enabled"]) is not bool
        or {name: ai_limits[name] for name in APPROVED_AI_LIMITS}
        != APPROVED_AI_LIMITS
    ):
        raise AuthorizationInvalid("authorization_ai_limits_invalid")
    secrets = _exact_dict(
        authority["secret_presence"],
        EXPECTED_SECRET_FIELDS,
        "authorization_secret_presence_invalid",
    )
    if any(type(value) is not bool for value in secrets.values()) or secrets != {
        "blob_credential": True,
        "openai_api_key": ai_limits["enabled"],
        "operator_password_hash": True,
        "postgres_password": True,
        "registry_password": False,
        "session_pepper": True,
    }:
        raise AuthorizationInvalid("authorization_secret_presence_invalid")
    _ordered_strings(
        authority["server_settings"],
        EXPECTED_SERVER_SETTINGS
        + (("OPENAI_API_KEY",) if ai_limits["enabled"] else ()),
        "authorization_server_settings_invalid",
    )

    limits = _exact_dict(
        authority["limits_usd"],
        EXPECTED_LIMIT_FIELDS,
        "authorization_limits_invalid",
    )
    normalized_limits = {name: _finite_decimal(value) for name, value in limits.items()}
    hard_cap = normalized_limits["hard_cap"]
    if hard_cap <= 0 or any(
        normalized_limits[name] > hard_cap
        for name in ("monthly_estimate", "one_time_estimate", "openai_smoke_cap")
    ):
        raise AuthorizationInvalid("authorization_limits_invalid")

    publication = _exact_dict(
        authority["external_publication"],
        EXPECTED_PUBLICATION_FIELDS,
        "authorization_publication_invalid",
    )
    if any(type(value) is not bool for value in publication.values()):
        raise AuthorizationInvalid("authorization_publication_invalid")
    if (
        publication["dns_change"]
        or publication["github_push"]
        or ai_limits["enabled"] is not publication["paid_ai_smoke"]
        or (
            publication["paid_ai_smoke"]
            and not Decimal("0")
            < normalized_limits["openai_smoke_cap"]
            <= Decimal("5")
        )
        or (
            not publication["paid_ai_smoke"]
            and normalized_limits["openai_smoke_cap"] != 0
        )
    ):
        raise AuthorizationInvalid("authorization_publication_invalid")

    recovery = _exact_dict(
        authority["recovery"],
        EXPECTED_RECOVERY_FIELDS,
        "authorization_recovery_invalid",
    )
    if (
        recovery["blob_soft_delete_days"] != 7
        or (
            recovery["target_mode"] not in {"fresh", "update"}
        )
        or (
            recovery["target_mode"] == "fresh"
            and (
                authority["public_url"] is not None
                or authority["public_url_source"] != "azure_containerapp_fqdn"
            )
        )
        or (
            recovery["target_mode"] == "update"
            and (
                parsed_url is None
                or authority["public_url_source"] != "exact"
                or DIGEST_PATTERN.fullmatch(
                    str(recovery["observed_current_image_digest"])
                )
                is None
            )
        )
        or (
            recovery["target_mode"] == "fresh"
            and recovery["observed_current_image_digest"] is not None
        )
        or recovery["postgres_backup_retention_days"]
        != authority["resources"]["postgres"]["backup_retention_days"]
        or any(
            recovery[name] is not True
            for name in (
                "restart_readback",
                "rollback_digest_preflight",
                "rollback_rehearsal",
            )
        )
    ):
        raise AuthorizationInvalid("authorization_recovery_invalid")

    _validate_commands(authority["commands"], authority)
    _ordered_strings(
        authority["execution_order"],
        _expected_execution_order(
            authority,
            legacy_update=(
                authority["recovery"]["target_mode"] == "update"
                and bool(authority["commands"]["activate"])
            ),
        ),
        "authorization_execution_order_invalid",
    )
    retries = _exact_dict(
        authority["retry_limits"],
        EXPECTED_RETRY_FIELDS,
        "authorization_retry_limits_invalid",
    )
    if retries != {"read": 1, "deploy": 0, "paid_provider": 0}:
        raise AuthorizationInvalid("authorization_retry_limits_invalid")
    expected_operations = list(BASE_OPERATIONS)
    if publication["registry_publish"]:
        expected_operations[1:1] = ["registry_publish"]
    if publication["paid_ai_smoke"]:
        expected_operations.append("paid_ai_smoke")
    _ordered_strings(
        authority["allowed_operations"],
        tuple(expected_operations),
        "authorization_operations_invalid",
    )
    _ordered_strings(
        authority["stop_conditions"],
        EXPECTED_STOP_CONDITIONS,
        "authorization_stop_conditions_invalid",
    )

    serialized_strings = json.dumps(authority, sort_keys=True)
    if SECRET_PATTERN.search(serialized_strings):
        raise AuthorizationInvalid("authorization_secret_value_forbidden")
    return authority


def _load_two_stage_authorization_bytes(
    source_bytes: bytes,
    *,
    now: datetime,
) -> dict[str, Any]:
    try:
        source = source_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AuthorizationInvalid("authorization_document_invalid") from error
    document = re.fullmatch(
        rf"{re.escape(TWO_STAGE_HEADER)}\n\n```json\n(?P<payload>.*)\n```\n?",
        source,
        flags=re.DOTALL,
    )
    if document is None:
        raise AuthorizationInvalid("authorization_document_invalid")
    try:
        package = json.loads(
            document.group("payload"),
            object_pairs_hook=_unique_object,
        )
    except json.JSONDecodeError as error:
        raise AuthorizationInvalid("authorization_json_invalid") from error
    package = _exact_dict(
        package,
        TWO_STAGE_FIELDS,
        "authorization_fields_invalid",
    )
    issued_at = _timestamp(package["issued_at"])
    expires_at = _timestamp(package["expires_at"])
    if (
        package["schema_version"] != "newcaostone.two-stage-launch.v1"
        or UUID_PATTERN.fullmatch(str(package["package_id"])) is None
        or UUID_PATTERN.fullmatch(str(package["tenant_id"])) is None
        or expires_at <= issued_at
        or expires_at - issued_at > timedelta(days=7)
        or now < issued_at
        or now >= expires_at
        or package["stage_order"] != ["data_scope_revision", "ai_revision"]
    ):
        raise AuthorizationInvalid("authorization_identity_invalid")

    data_stage = _exact_dict(
        package["data_scope_revision"],
        DATA_STAGE_FIELDS,
        "authorization_data_stage_invalid",
    )
    authority_bytes = (
        "# NEWCaostone Launch Authorization\n\n```json\n"
        + json.dumps(data_stage["authority"], indent=2, sort_keys=True)
        + "\n```\n"
    ).encode()
    data_authority = _load_authorization_bytes(authority_bytes, now=now)
    generated = data_authority["generated_names"]
    release = data_authority["release"]
    data_hash = data_authority_sha256(data_authority)
    if (
        data_stage["authority"] != data_authority
        or data_stage["revision"] != generated["application_revision"]
        or package["data_authority_sha256"] != data_hash
        or data_authority["issued_at"] != package["issued_at"]
        or data_authority["expires_at"] != package["expires_at"]
        or data_authority["ai_limits"]["enabled"] is not False
        or data_authority["secret_presence"]["openai_api_key"] is not False
        or data_authority["external_publication"] != {
            "dns_change": False,
            "github_push": False,
            "paid_ai_smoke": False,
            "registry_publish": True,
        }
        or data_stage["receipt_contract"]
        != {
            "schema_version": "newcaostone.data-scope-receipt.v1",
            "required_checks": [
                "health",
                "browser_core",
                "capacity_exact_15",
                "expiry",
                "restart_readback",
                "rollback_compatibility",
            ],
        }
    ):
        raise AuthorizationInvalid("authorization_data_stage_invalid")

    ai_stage = _exact_dict(
        package["ai_revision"],
        AI_STAGE_FIELDS,
        "authorization_ai_stage_invalid",
    )
    expected_ai_revision = (
        f"{generated['container_app']}--ai-{release['image_digest'][7:14]}"
    )
    if (
        ai_stage["revision"] != expected_ai_revision
        or ai_stage["candidate_image_digest"] != release["image_digest"]
        or ai_stage["data_authority_sha256"] != data_hash
        or ai_stage["depends_on"]
        != ["data_scope_revision_receipt", "model_qualification_receipt"]
        or ai_stage["model_snapshot"]
        != {
            "model": "gpt-5.4-nano-2026-03-17",
            "reasoning_effort": "low",
            "max_output_tokens": 2800,
        }
        or ai_stage["qualification_contract"]
        != {
            "case_count": 12,
            "receipt_schema_version": 1,
            "receipt_path": QUALIFICATION_RECEIPT_PATH,
            "must_pass": True,
        }
        or ai_stage["secret_presence"]
        != {
            "blob_credential": True,
            "openai_api_key": True,
            "operator_password_hash": True,
            "postgres_password": True,
            "registry_password": False,
            "session_pepper": True,
        }
        or ai_stage["execution_order"]
        != [
            "model_qualification",
            "receipt_verification",
            "deploy",
            "paid_ai_smoke",
            "rollback_on_failure",
        ]
        or ai_stage["retry_limits"]
        != {"deploy": 0, "paid_provider": 0, "read": 1}
        or ai_stage["stop_conditions"]
        != [
            "stage1_receipt_missing_or_invalid",
            "model_qualification_failed",
            "target_digest_or_data_authority_changed",
            "secret_boundary_failed",
            "cost_cap_exceeded",
        ]
        or ai_stage["rollback_revision"] != data_stage["revision"]
    ):
        raise AuthorizationInvalid("authorization_ai_stage_invalid")
    expected_commands = _expected_ai_transition_commands(package)
    if ai_stage["commands"] != expected_commands:
        raise AuthorizationInvalid("authorization_commands_invalid")
    for entries in expected_commands.values():
        for command in entries:
            _command_tokens(command)

    costs = _exact_dict(
        package["cost_cap_usd"],
        frozenset({"hard_cap", "hosted_smoke_cap", "qualification_cap"}),
        "authorization_limits_invalid",
    )
    normalized = {name: _finite_decimal(value) for name, value in costs.items()}
    if (
        normalized["hard_cap"] <= 0
        or not Decimal("0") < normalized["qualification_cap"] <= Decimal("5")
        or not Decimal("0") < normalized["hosted_smoke_cap"] <= Decimal("5")
        or normalized["qualification_cap"] + normalized["hosted_smoke_cap"]
        > normalized["hard_cap"]
    ):
        raise AuthorizationInvalid("authorization_limits_invalid")
    if SECRET_PATTERN.search(json.dumps(package, sort_keys=True)):
        raise AuthorizationInvalid("authorization_secret_value_forbidden")
    return package


def load_two_stage_authorization(
    path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    try:
        source_bytes = path.read_bytes()
    except OSError as error:
        raise AuthorizationInvalid("authorization_file_unavailable") from error
    return _load_two_stage_authorization_bytes(
        source_bytes,
        now=now or datetime.now(UTC),
    )


def load_authorization(
    path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Load one exact JSON document and validate only its safe launch contract."""

    try:
        source_bytes = path.read_bytes()
    except OSError as error:
        raise AuthorizationInvalid("authorization_file_unavailable") from error
    return _load_authorization_bytes(
        source_bytes,
        now=now or datetime.now(UTC),
    )


def main(
    arguments: list[str] | None = None,
    *,
    now: datetime | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", required=True, type=Path)
    parser.add_argument("--approved-sha256", required=True)
    options = parser.parse_args(arguments)
    try:
        source_bytes = options.authorization.read_bytes()
        verification_time = now or datetime.now(UTC)
        if source_bytes.startswith((TWO_STAGE_HEADER + "\n").encode()):
            package = _load_two_stage_authorization_bytes(
                source_bytes,
                now=verification_time,
            )
            authority = package["data_scope_revision"]["authority"]
        else:
            package = None
            authority = _load_authorization_bytes(
                source_bytes,
                now=verification_time,
            )
        document_sha256 = hashlib.sha256(source_bytes).hexdigest()
        if (
            not re.fullmatch(r"[0-9a-f]{64}", options.approved_sha256)
            or document_sha256 != options.approved_sha256
        ):
            raise AuthorizationInvalid("authorization_approval_hash_mismatch")
        _validate_release_manifest_binding(authority["release"])
        _validate_candidate_inputs(authority["release"])
    except Exception:
        print("launch_package=invalid")
        return 1
    print("launch_package=valid")
    print("approval_binding=matched")
    print(f"release_git_sha={authority['release']['git_sha']}")
    if package is not None:
        print("stage_order=data_scope_revision,ai_revision")
    print("hosted_verification=not_executed")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
