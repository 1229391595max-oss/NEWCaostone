from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

import pytest

from scripts.create_release_manifest import committed_image_input_sha256
from scripts.release_authority import load_current_authority
from tests.hosted.verify_azure_demo import (
    AuthorizationInvalid,
    CANDIDATE_HASH_PATHS,
    REQUIRED_CANDIDATE_PATHS,
    _expected_commands,
    _expected_ai_transition_commands,
    _expected_execution_order as verifier_execution_order,
    data_authority_sha256,
    _validate_candidate_inputs,
    _validate_release_manifest_binding,
    load_authorization,
    load_two_stage_authorization,
    main,
)

NOW = datetime(2026, 8, 15, 14, 0, tzinfo=UTC)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEED_NAMESPACE = UUID("cb794ce7-d3cf-516a-850b-643ab0c2ec91")


@pytest.mark.parametrize(
    "entrypoint",
    (
        "scripts/azure_recovery_preflight.py",
        "scripts/run_hosted_check.py",
        "scripts/run_hosted_failure_check.py",
        "scripts/run_azure_readback.py",
        "scripts/verify_hosted_expiry.py",
        "scripts/verify_registry_image.py",
    ),
)
def test_hash_bound_hosted_entrypoints_start_from_exact_command_shape(
    entrypoint: str,
) -> None:
    completed = subprocess.run(
        [sys.executable, entrypoint, "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_authorization_verifier_cli_starts_from_project_root() -> None:
    completed = subprocess.run(
        [sys.executable, "tests/hosted/verify_azure_demo.py", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--authorization" in completed.stdout


def test_deploy_runbook_preserves_conditional_ai_failure_authority() -> None:
    runbook = (PROJECT_ROOT / "docs/runbooks/DEPLOY.md").read_text()

    assert (
        "When `ai_limits.enabled=false`, both AI failure command groups are exact "
        "empty arrays and are omitted from `execution_order`."
    ) in runbook
    assert (
        "When `ai_limits.enabled=true`, both AI failure rehearsals and the paid AI "
        "smoke remain mandatory."
    ) in runbook
    assert (
        "Phase 1 runs only `python scripts/phase1_fence_server.py`; the application "
        "container has no PostgreSQL, Blob, operator, session, or OpenAI secret "
        "authority."
    ) in runbook
    assert (
        "Migration and seed may start only after the exact Phase 1 "
        "command/env/secret projection is verified and every application revision "
        "reports zero replicas."
    ) in runbook
    assert (
        "Phase 2 removes the command override, restores the normal Uvicorn "
        "application authority, and must pass the exact phase2 fence before hosted "
        "acceptance begins."
    ) in runbook


def _file_sha256(path: str) -> str:
    return hashlib.sha256((PROJECT_ROOT / path).read_bytes()).hexdigest()


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commands(payload: dict[str, object]) -> dict[str, list[str]]:
    generated = payload["generated_names"]
    release = payload["release"]
    subscription = payload["subscription_id"]
    resource_group = payload["resource_group"]
    public_url = payload["public_url"]
    ai_limits = payload["ai_limits"]
    registry_image = (
        f"{generated['registry_name']}.azurecr.io/"
        f"{generated['image_repository']}@{release['image_digest']}"
    )
    rollback_image = (
        f"{generated['registry_name']}.azurecr.io/"
        f"{generated['image_repository']}@{release['rollback_image_digest']}"
    )
    deployment_parameters = (
        "--parameters infra/environments/demo.bicepparam "
        "deploymentEnabled=true "
        "namePrefix=bp-approved location=brazilsouth "
        f"containerImage={registry_image} "
        f"syntheticManifestSha256={release['synthetic_manifest_sha256']} "
        f"syntheticDatasetVersionId={release['synthetic_dataset_version_id']} "
        "registryName=bpapprovedregistry "
        "postgresAdministratorLogin=bpoperator "
        "postgresServerName=bp-approved-pg "
        "storageAccountName=bpapprovedstorage "
        "storageSku=Standard_LRS "
        "postgresSkuName=Standard_B1ms postgresTier=Burstable "
        "postgresStorageSizeGb=32 postgresBackupRetentionDays=7 "
        "logRetentionDays=30 "
        f"aiDailyAttemptLimit={ai_limits['daily_attempt_limit']} "
        f"aiMaxConcurrentTurns={ai_limits['max_concurrent_turns']} "
        "aiSessionAttemptLimitPerMinute="
        f"{ai_limits['session_attempt_limit_per_minute']} "
        "aiGlobalAttemptLimitPerMinute="
        f"{ai_limits['global_attempt_limit_per_minute']} "
        "demoSessionRateLimitPerHour="
        f"{ai_limits['demo_session_rate_limit_per_hour']}"
    )
    hosted_check = (
        ".venv/bin/python scripts/run_hosted_check.py "
        f"--subscription {subscription} --resource-group {resource_group} "
        f"--app {generated['container_app']} --image {registry_image}"
        + (f" --expected-url {public_url}" if public_url is not None else "")
    )
    health = hosted_check + " --check health"
    browser = hosted_check + " --check browser --scenario core"
    expiry = (
        ".venv/bin/python scripts/verify_hosted_expiry.py "
        f"--subscription {subscription} --resource-group {resource_group} "
        f"--app {generated['container_app']} --image {registry_image} "
        f"--session-job {generated['session_maintenance_job']}"
        + (f" --expected-url {public_url}" if public_url is not None else "")
    )
    preflight = (
        ".venv/bin/python scripts/azure_recovery_preflight.py "
        f"--subscription {subscription} --resource-group {resource_group} "
        f"--region brazilsouth --target-mode {payload['recovery']['target_mode']} "
        "--app bp-approved-app --environment bp-approved-env "
        "--application-insights bp-approved-insights "
        "--log-workspace bp-approved-logs "
        "--prepare-job bp-approved-prepare --seed-job bp-approved-seed "
        "--session-job bp-approved-sessions --storage-job bp-approved-storage "
        "--virtual-network bp-approved-vnet "
        "--postgres-dns-zone private.postgres.database.azure.com "
        "--postgres-server bp-approved-pg --postgres-backup-days 7 "
        "--postgres-sku Standard_B1ms --postgres-tier Burstable "
        "--postgres-storage-gb 32 --postgres-version 16 "
        "--storage-account bpapprovedstorage --storage-sku Standard_LRS "
        "--blob-retention-days 7 --application-sku Consumption "
        "--application-cpu 0.5 --application-memory 1Gi "
        "--application-min-replicas 1 --application-max-replicas 1 "
        "--log-retention-days 30 "
        "--registry bpapprovedregistry --registry-identity bp-approved-registry "
        "--repository bizpulse "
        f"--image-digest {release['image_digest']} "
        f"--rollback-image-digest {release['rollback_image_digest']}"
        " --current-image-state "
        + (
            "pending-publication"
            if payload["external_publication"]["registry_publish"]
            else "present"
        )
        + (f" --public-url {public_url}" if public_url is not None else "")
    )
    if payload["recovery"]["target_mode"] == "update":
        preflight += (
            " --observed-current-image-digest "
            f"{payload['recovery']['observed_current_image_digest']}"
        )
    phase1_fence = (
        ".venv/bin/python scripts/verify_phase1_fence.py "
        f"--subscription {subscription} --resource-group {resource_group} "
        "--app bp-approved-app "
        f"--image {registry_image} "
        "--prepare-job bp-approved-prepare --seed-job bp-approved-seed "
        "--session-job bp-approved-sessions --storage-job bp-approved-storage "
        "--storage-account bpapprovedstorage --blob-container synthetic-demo "
        f"--synthetic-manifest-sha256 {release['synthetic_manifest_sha256']} "
        f"--synthetic-dataset-version-id {release['synthetic_dataset_version_id']} "
        "--environment bp-approved-env "
        f"--ai-enabled {str(payload['ai_limits']['enabled']).lower()} "
        f"--ai-daily-attempt-limit {payload['ai_limits']['daily_attempt_limit']} "
        f"--ai-monthly-token-limit {payload['ai_limits']['monthly_token_limit']} "
        f"--ai-max-concurrent-turns {payload['ai_limits']['max_concurrent_turns']} "
        "--ai-session-attempt-limit-per-minute "
        f"{payload['ai_limits']['session_attempt_limit_per_minute']} "
        "--ai-global-attempt-limit-per-minute "
        f"{payload['ai_limits']['global_attempt_limit_per_minute']} "
        "--demo-session-rate-limit-per-hour "
        f"{payload['ai_limits']['demo_session_rate_limit_per_hour']} "
        "--mode initial"
    )
    phase1_deploy = (
        "az deployment group create "
        f"--subscription {subscription} --resource-group {resource_group} "
        "--name bp-approved-phase1 "
        f"{deployment_parameters} applicationEnabled=false "
        "applicationRevisionSuffix=prep-bbbbbbb "
        f"aiChatEnabled={str(payload['ai_limits']['enabled']).lower()} "
        f"aiMonthlyTokenLimit={payload['ai_limits']['monthly_token_limit']} "
        "--mode Incremental --output json"
    )
    migrate = (
        ".venv/bin/python scripts/run_azure_job.py "
        f"--subscription {subscription} --resource-group {resource_group} "
        "--job bp-approved-prepare --timeout-seconds 900"
    )
    seed = (
        ".venv/bin/python scripts/run_azure_job.py "
        f"--subscription {subscription} --resource-group {resource_group} "
        "--job bp-approved-seed --timeout-seconds 1800"
    )
    activate_preflight = preflight.replace(
        f"--target-mode {payload['recovery']['target_mode']}",
        "--target-mode prepared",
    ).replace("--current-image-state pending-publication", "--current-image-state present")
    if payload["recovery"]["target_mode"] == "update":
        activate_preflight = activate_preflight.replace(
            " --observed-current-image-digest "
            f"{payload['recovery']['observed_current_image_digest']}",
            "",
        )
    activate_fence = phase1_fence.replace("--mode initial", "--mode activate") + (
        f" --not-before {payload['issued_at']}"
    )
    def application_deploy(
        name: str,
        suffix: str,
        ai_enabled: bool,
        monthly_tokens: int,
    ) -> str:
        return (
            "az deployment group create "
            f"--subscription {subscription} --resource-group {resource_group} "
            f"--name {name} {deployment_parameters} applicationEnabled=true "
            f"applicationRevisionSuffix={suffix} "
            f"aiChatEnabled={str(ai_enabled).lower()} "
            f"aiMonthlyTokenLimit={monthly_tokens} "
            "--mode Incremental --output json"
        )

    def failure_check(scenario: str) -> str:
        command = (
            ".venv/bin/python scripts/run_hosted_failure_check.py "
            f"--subscription {subscription} --resource-group {resource_group} "
            "--app bp-approved-app "
            f"--image {registry_image} "
            f"--authorization-id {payload['authorization_id']} "
            f"--scenario {scenario} "
            "--normal-ai-enabled "
            f"{str(payload['ai_limits']['enabled']).lower()} "
            "--normal-monthly-token-limit "
            f"{payload['ai_limits']['monthly_token_limit']}"
        )
        if public_url is not None:
            command += f" --expected-url {public_url}"
        for parameter in deployment_parameters.split()[2:]:
            command += f" --parameter {parameter}"
        return command

    phase2_fence = phase1_fence.replace("--mode initial", "--mode phase2") + (
        f" --not-before {payload['issued_at']}"
    )
    session_maintenance = (
        ".venv/bin/python scripts/run_azure_job.py "
        f"--subscription {subscription} --resource-group {resource_group} "
        "--job bp-approved-sessions --timeout-seconds 600"
    )
    storage_maintenance = (
        ".venv/bin/python scripts/run_azure_job.py "
        f"--subscription {subscription} --resource-group {resource_group} "
        "--job bp-approved-storage --timeout-seconds 600"
    )
    return {
        "activate": [activate_preflight, activate_fence],
        "browser_acceptance": [browser],
        "budget_failure": (
            [failure_check("budget")]
            if payload["ai_limits"]["enabled"]
            else []
        ),
        "capacity": [hosted_check + " --check capacity"],
        "deploy": [
            application_deploy(
                "bp-approved-phase2",
                "bbbbbbbbbbbb",
                payload["ai_limits"]["enabled"],
                payload["ai_limits"]["monthly_token_limit"],
            ),
            session_maintenance,
            storage_maintenance,
            phase2_fence,
        ],
        "expiry": [expiry],
        "health": [health],
        "migrate": [migrate],
        "paid_ai_smoke": (
            [hosted_check + " --check browser --scenario paid-ai"]
            if payload["external_publication"]["paid_ai_smoke"]
            else []
        ),
        "preflight": [preflight],
        "provision": [
            "az provider register "
            f"--subscription {subscription} --namespace Microsoft.App "
            "--wait --only-show-errors --output none",
            phase1_deploy,
            phase1_fence,
        ],
        "provider_failure": (
            [failure_check("provider-unavailable")]
            if payload["ai_limits"]["enabled"]
            else []
        ),
        "registry_publish": (
            [
                ".venv/bin/python scripts/publish_registry_image.py "
                f"--subscription {subscription} "
                f"--registry {generated['registry_name']} "
                f"--repository {generated['image_repository']} "
                f"--candidate-git-sha {release['git_sha']} "
                f"--authorization-id {payload['authorization_id']} "
                f"--expected-digest {release['image_digest']} "
                f"--image-input-sha256 {release['image_input_sha256']}",
                ".venv/bin/python scripts/publish_registry_image.py "
                f"--subscription {subscription} "
                f"--registry {generated['registry_name']} "
                f"--repository {generated['image_repository']} "
                f"--candidate-git-sha {release['rollback_git_sha']} "
                f"--authorization-id {payload['authorization_id']} "
                f"--expected-digest {release['rollback_image_digest']} "
                "--image-input-sha256 "
                f"{release['rollback_image_input_sha256']}"
            ]
            if payload["external_publication"]["registry_publish"]
            else []
        ),
        "registry_verify": [
            ".venv/bin/python scripts/verify_registry_image.py "
            f"--subscription {subscription} "
            f"--registry {generated['registry_name']} "
            f"--repository {generated['image_repository']} "
            f"--source-git-sha {release['git_sha']} "
            f"--expected-digest {release['image_digest']} "
            f"--image-input-sha256 {release['image_input_sha256']}",
            ".venv/bin/python scripts/verify_registry_image.py "
            f"--subscription {subscription} "
            f"--registry {generated['registry_name']} "
            f"--repository {generated['image_repository']} "
            f"--source-git-sha {release['rollback_git_sha']} "
            f"--expected-digest {release['rollback_image_digest']} "
            "--image-input-sha256 "
            f"{release['rollback_image_input_sha256']}",
            *(
                [
                    preflight.replace(
                        "--current-image-state pending-publication",
                        "--current-image-state present",
                    )
                ]
                if payload["external_publication"]["registry_publish"]
                else []
            ),
        ],
        "restart_readback": [
            ".venv/bin/python scripts/run_azure_readback.py "
            f"--subscription {subscription} --resource-group {resource_group} "
            "--app bp-approved-app "
            f"--current-image {registry_image} "
            f"--authorization-id {payload['authorization_id']} --ai-enabled "
            f"{str(payload['ai_limits']['enabled']).lower()} --operation restart "
            "--revision bp-approved-app--bbbbbbbbbbbb"
        ],
        "rollback": [
            ".venv/bin/python scripts/run_azure_readback.py "
            f"--subscription {subscription} --resource-group {resource_group} "
            "--app bp-approved-app "
            f"--current-image {registry_image} "
            f"--authorization-id {payload['authorization_id']} --ai-enabled "
            f"{str(payload['ai_limits']['enabled']).lower()} --operation rollback "
            f"--rollback-image {rollback_image}"
        ],
        "seed": [seed],
    }


def _execution_order(payload: dict[str, object]) -> list[str]:
    return list(verifier_execution_order(payload))


def _authorization() -> dict[str, object]:
    synthetic_manifest_sha256 = _file_sha256(
        "tests/fixtures/synthetic/v1/manifest.json"
    )
    local_manifest = json.loads(
        (PROJECT_ROOT / "release/local-release-manifest.json").read_text()
    )
    current_authority = load_current_authority(
        PROJECT_ROOT / "release/current_authority.json"
    )
    rollback_sha = current_authority.attested_rollback.git_sha
    payload = {
        "schema_version": "newcaostone.launch-authorization.v4",
        "authorization_id": "22222222-2222-4222-8222-222222222222",
        "issued_at": "2026-08-14T14:00:00Z",
        "expires_at": "2026-08-16T14:00:00Z",
        "subscription_id": "11111111-1111-4111-8111-111111111111",
        "region": "brazilsouth",
        "resource_group": "rg-synthetic-demo-approved",
        "public_url": None,
        "public_url_source": "azure_containerapp_fqdn",
        "generated_names": {
            "application_insights": "bp-approved-insights",
            "application_revision": "bp-approved-app--bbbbbbbbbbbb",
            "container_app": "bp-approved-app",
            "container_environment": "bp-approved-env",
            "image_repository": "bizpulse",
            "log_workspace": "bp-approved-logs",
            "migration_job": "bp-approved-prepare",
            "name_prefix": "bp-approved",
            "postgres_administrator_login": "bpoperator",
            "postgres_dns_zone": "private.postgres.database.azure.com",
            "postgres_server": "bp-approved-pg",
            "registry_name": "bpapprovedregistry",
            "registry_identity": "bp-approved-registry",
            "seed_job": "bp-approved-seed",
            "session_maintenance_job": "bp-approved-sessions",
            "storage_account": "bpapprovedstorage",
            "storage_maintenance_job": "bp-approved-storage",
            "virtual_network": "bp-approved-vnet",
        },
        "release": {
            "attestation_git_sha": _git(
                "log",
                "-1",
                "--format=%H",
                "--",
                "release/local-release-manifest.json",
            ),
            "azure_preflight_sha256": _file_sha256(
                "scripts/azure_recovery_preflight.py"
            ),
            "azure_readback_sha256": _file_sha256(
                "scripts/run_azure_readback.py"
            ),
            "azure_job_runner_sha256": _file_sha256("scripts/run_azure_job.py"),
            "browser_gate_sha256": _file_sha256("scripts/browser_release_gate.mjs"),
            "hosted_health_sha256": _file_sha256(
                "scripts/verify_hosted_health.py"
            ),
            "hosted_check_sha256": _file_sha256("scripts/run_hosted_check.py"),
            "hosted_failure_check_sha256": _file_sha256(
                "scripts/run_hosted_failure_check.py"
            ),
            "hosted_capacity_sha256": _file_sha256(
                "scripts/verify_hosted_capacity.py"
            ),
            "hosted_expiry_sha256": _file_sha256(
                "scripts/verify_hosted_expiry.py"
            ),
            "infra_bicep_sha256": _file_sha256("infra/main.bicep"),
            "infra_parameters_sha256": _file_sha256(
                "infra/environments/demo.bicepparam"
            ),
            "launch_verifier_sha256": _file_sha256(
                "tests/hosted/verify_azure_demo.py"
            ),
            "git_sha": local_manifest["candidate_git_sha"],
            "image_digest": "sha256:" + "b" * 64,
            "image_input_sha256": local_manifest["image_input_sha256"],
            "local_manifest_sha256": _file_sha256(
                "release/local-release-manifest.json"
            ),
            "migration_head": (
                current_authority.observed_deployment.database_migration_head
            ),
            "model_qualification_sha256": _file_sha256(
                "scripts/qualify_openai_model.py"
            ),
            "phase1_fence_sha256": _file_sha256(
                "scripts/verify_phase1_fence.py"
            ),
            "registry_publisher_sha256": _file_sha256(
                "scripts/publish_registry_image.py"
            ),
            "registry_verifier_sha256": _file_sha256(
                "scripts/verify_registry_image.py"
            ),
            "stage_receipt_verifier_sha256": _file_sha256(
                "scripts/verify_stage_receipts.py"
            ),
            "rollback_git_sha": rollback_sha,
            "rollback_image_input_sha256": committed_image_input_sha256(
                rollback_sha
            ),
            "synthetic_dataset_version_id": str(
                uuid5(SEED_NAMESPACE, f"version:{synthetic_manifest_sha256}")
            ),
            "synthetic_manifest_sha256": synthetic_manifest_sha256,
            "two_stage_package_generator_sha256": _file_sha256(
                "scripts/create_two_stage_release_package.py"
            ),
            "rollback_image_digest": "sha256:" + "d" * 64,
        },
        "resources": {
            "application": {
                "count": 1,
                "cpu": "0.5",
                "max_replicas": 1,
                "memory": "1Gi",
                "min_replicas": 1,
                "sku": "Consumption",
            },
            "monitoring": {"log_retention_days": 30},
            "postgres": {
                "backup_retention_days": 7,
                "count": 1,
                "public_network": False,
                "sku": "Standard_B1ms",
                "storage_gb": 32,
                "tier": "Burstable",
                "version": "16",
            },
            "storage": {
                "container": "synthetic-demo",
                "count": 1,
                "public_access": False,
                "sku": "Standard_LRS",
            },
        },
        "limits_usd": {
            "one_time_estimate": "10.00",
            "monthly_estimate": "80.00",
            "hard_cap": "100.00",
            "openai_smoke_cap": "0.00",
        },
        "ai_limits": {
            "enabled": False,
            "daily_attempt_limit": 120,
            "monthly_token_limit": 150_000,
            "max_concurrent_turns": 15,
            "session_attempt_limit_per_minute": 3,
            "global_attempt_limit_per_minute": 20,
            "demo_session_rate_limit_per_hour": 50,
        },
        "secret_presence": {
            "blob_credential": True,
            "openai_api_key": False,
            "operator_password_hash": True,
            "postgres_password": True,
            "registry_password": False,
            "session_pepper": True,
        },
        "server_settings": [
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
        ],
        "external_publication": {
            "dns_change": False,
            "github_push": False,
            "paid_ai_smoke": False,
            "registry_publish": False,
        },
        "recovery": {
            "blob_soft_delete_days": 7,
            "observed_current_image_digest": None,
            "postgres_backup_retention_days": 7,
            "restart_readback": True,
            "rollback_digest_preflight": True,
            "rollback_rehearsal": True,
            "target_mode": "fresh",
        },
        "commands": {},
        "execution_order": [],
        "retry_limits": {"read": 1, "deploy": 0, "paid_provider": 0},
        "allowed_operations": [
            "azure_read_preflight",
            "registry_digest_readback",
            "azure_provision",
            "postgres_migrate",
            "synthetic_seed",
            "deploy_digest",
            "hosted_verify",
            "rollback_rehearsal",
        ],
        "stop_conditions": [
            "target_or_cost_changed",
            "digest_or_migration_changed",
            "recovery_preflight_failed",
            "secret_boundary_failed",
        ],
    }
    payload["commands"] = _commands(payload)
    payload["execution_order"] = _execution_order(payload)
    return payload


def test_phase_fence_commands_bind_exact_blob_authority() -> None:
    commands = _expected_commands(_authorization())
    phase_fences = [
        command
        for stage_commands in commands.values()
        for command in stage_commands
        if "scripts/verify_phase1_fence.py" in command
    ]

    assert phase_fences
    assert all(
        "--storage-account" in command
        and "bpapprovedstorage" in command
        and "--blob-container" in command
        and "synthetic-demo" in command
        for command in phase_fences
    )


def _enable_paid_ai(payload: dict[str, object]) -> None:
    payload["ai_limits"].update(
        enabled=True,
        daily_attempt_limit=120,
        monthly_token_limit=150_000,
        session_attempt_limit_per_minute=3,
        global_attempt_limit_per_minute=20,
    )
    payload["secret_presence"]["openai_api_key"] = True
    payload["server_settings"].append("OPENAI_API_KEY")
    payload["external_publication"]["paid_ai_smoke"] = True
    payload["limits_usd"]["openai_smoke_cap"] = "0.25"
    payload["allowed_operations"].append("paid_ai_smoke")


def _write(path: Path, payload: dict[str, object], *, suffix: str = "") -> None:
    path.write_text(
        "# NEWCaostone Launch Authorization\n\n```json\n"
        + json.dumps(payload, indent=2, sort_keys=True)
        + "\n```\n"
        + suffix
    )


def _two_stage_authorization() -> dict[str, object]:
    data = _authorization()
    data["external_publication"]["registry_publish"] = True
    data["allowed_operations"].insert(1, "registry_publish")
    data["commands"] = _commands(data)
    data["execution_order"] = _execution_order(data)
    digest_fragment = data["release"]["image_digest"][7:14]
    data_revision = data["generated_names"]["application_revision"]
    ai_revision = f"{data['generated_names']['container_app']}--ai-{digest_fragment}"
    package = {
        "schema_version": "newcaostone.two-stage-launch.v1",
        "package_id": "33333333-3333-4333-8333-333333333333",
        "issued_at": data["issued_at"],
        "expires_at": data["expires_at"],
        "tenant_id": "44444444-4444-4444-8444-444444444444",
        "stage_order": ["data_scope_revision", "ai_revision"],
        "cost_cap_usd": {
            "hard_cap": "100.00",
            "qualification_cap": "1.00",
            "hosted_smoke_cap": "0.25",
        },
        "data_authority_sha256": data_authority_sha256(data),
        "data_scope_revision": {
            "revision": data_revision,
            "authority": data,
            "receipt_contract": {
                "schema_version": "newcaostone.data-scope-receipt.v1",
                "required_checks": [
                    "health",
                    "browser_core",
                    "capacity_exact_15",
                    "expiry",
                    "restart_readback",
                    "rollback_compatibility",
                ],
            },
        },
        "ai_revision": {
            "revision": ai_revision,
            "candidate_image_digest": data["release"]["image_digest"],
            "data_authority_sha256": data_authority_sha256(data),
            "depends_on": [
                "data_scope_revision_receipt",
                "model_qualification_receipt",
            ],
            "model_snapshot": {
                "model": "gpt-5.4-nano-2026-03-17",
                "reasoning_effort": "low",
                "max_output_tokens": 2800,
            },
            "qualification_contract": {
                "case_count": 12,
                "receipt_schema_version": 1,
                "receipt_path": ".tmp/OPENAI_MODEL_QUALIFICATION_RECEIPT.json",
                "must_pass": True,
            },
            "secret_presence": {
                "blob_credential": True,
                "openai_api_key": True,
                "operator_password_hash": True,
                "postgres_password": True,
                "registry_password": False,
                "session_pepper": True,
            },
            "commands": {},
            "execution_order": [
                "model_qualification",
                "receipt_verification",
                "deploy",
                "paid_ai_smoke",
                "rollback_on_failure",
            ],
            "retry_limits": {"deploy": 0, "paid_provider": 0, "read": 1},
            "stop_conditions": [
                "stage1_receipt_missing_or_invalid",
                "model_qualification_failed",
                "target_digest_or_data_authority_changed",
                "secret_boundary_failed",
                "cost_cap_exceeded",
            ],
            "rollback_revision": data_revision,
        },
    }
    package["ai_revision"]["commands"] = _expected_ai_transition_commands(package)
    return package


def _write_two_stage(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        "# NEWCaostone Two-Stage Launch Authorization\n\n```json\n"
        + json.dumps(payload, indent=2, sort_keys=True)
        + "\n```\n"
    )


def test_two_stage_package_requires_data_then_ai_with_exact_rollback(
    tmp_path: Path,
) -> None:
    path = tmp_path / "TWO_STAGE_AUTHORIZATION.md"
    payload = _two_stage_authorization()
    _write_two_stage(path, payload)

    loaded = load_two_stage_authorization(path, now=NOW)

    assert loaded == payload
    assert loaded["stage_order"] == ["data_scope_revision", "ai_revision"]
    assert loaded["data_scope_revision"]["authority"]["ai_limits"]["enabled"] is False
    assert loaded["data_scope_revision"]["authority"]["secret_presence"]["openai_api_key"] is False
    assert loaded["ai_revision"]["candidate_image_digest"] == loaded[
        "data_scope_revision"
    ]["authority"]["release"]["image_digest"]
    assert loaded["ai_revision"]["rollback_revision"] == loaded[
        "data_scope_revision"
    ]["revision"]


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value["stage_order"].reverse(),
        lambda value: value["data_scope_revision"]["authority"]["secret_presence"].update(openai_api_key=True),
        lambda value: value["ai_revision"].update(candidate_image_digest="sha256:" + "9" * 64),
        lambda value: value["ai_revision"]["depends_on"].remove("model_qualification_receipt"),
        lambda value: value["ai_revision"].update(rollback_revision="bp-approved-app--other"),
        lambda value: value["ai_revision"]["commands"].update(paid_ai_smoke=[]),
    ),
)
def test_two_stage_package_fails_closed_on_stage_drift(
    tmp_path: Path,
    mutation,
) -> None:
    path = tmp_path / "TWO_STAGE_AUTHORIZATION.md"
    payload = _two_stage_authorization()
    mutation(payload)
    _write_two_stage(path, payload)

    with pytest.raises(AuthorizationInvalid):
        load_two_stage_authorization(path, now=NOW)


def test_two_stage_package_contains_no_key_or_secret_value(tmp_path: Path) -> None:
    path = tmp_path / "TWO_STAGE_AUTHORIZATION.md"
    payload = _two_stage_authorization()
    _write_two_stage(path, payload)

    source = path.read_text()
    assert "sk-" not in source
    assert "BIZPULSE_DEPLOY_OPENAI_API_KEY" not in source
    assert "openaiApiKey=" not in source
    assert load_two_stage_authorization(path, now=NOW) == payload


def test_cli_hash_binds_the_complete_two_stage_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "TWO_STAGE_AUTHORIZATION.md"
    payload = _two_stage_authorization()
    _write_two_stage(path, payload)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(
        "tests.hosted.verify_azure_demo._validate_candidate_inputs",
        lambda _release: None,
    )
    monkeypatch.setattr(
        "tests.hosted.verify_azure_demo._validate_release_manifest_binding",
        lambda _release: None,
    )

    assert main(
        ["--authorization", str(path), "--approved-sha256", digest],
        now=NOW,
    ) == 2
    output = capsys.readouterr().out
    assert "stage_order=data_scope_revision,ai_revision" in output
    assert "hosted_verification=not_executed" in output


def test_authorization_parser_accepts_only_exact_value_complete_payload(
    tmp_path: Path,
) -> None:
    path = tmp_path / "LAUNCH_AUTHORIZATION.md"
    payload = _authorization()
    _write(path, payload)

    assert load_authorization(path, now=NOW) == payload
    assert payload["commands"]["budget_failure"] == []
    assert payload["commands"]["provider_failure"] == []
    assert "budget_failure" not in payload["execution_order"]
    assert "provider_failure" not in payload["execution_order"]


def test_ai_disabled_authority_rejects_failure_rehearsal_command(
    tmp_path: Path,
) -> None:
    path = tmp_path / "LAUNCH_AUTHORIZATION.md"
    payload = _authorization()
    enabled = _authorization()
    _enable_paid_ai(enabled)
    enabled["commands"] = _commands(enabled)
    payload["commands"]["budget_failure"] = enabled["commands"]["budget_failure"]
    _write(path, payload)

    with pytest.raises(AuthorizationInvalid, match="authorization_commands_invalid"):
        load_authorization(path, now=NOW)


def test_ai_disabled_authority_rejects_failure_stage_in_execution_order(
    tmp_path: Path,
) -> None:
    path = tmp_path / "LAUNCH_AUTHORIZATION.md"
    payload = _authorization()
    deploy_index = payload["execution_order"].index("deploy")
    payload["execution_order"].insert(deploy_index, "budget_failure")
    _write(path, payload)

    with pytest.raises(
        AuthorizationInvalid,
        match="authorization_execution_order_invalid",
    ):
        load_authorization(path, now=NOW)


def test_fresh_target_uses_one_package_with_server_issued_url_authority(
    tmp_path: Path,
) -> None:
    path = tmp_path / "LAUNCH_AUTHORIZATION.md"
    payload = _authorization()
    _write(path, payload)

    assert load_authorization(path, now=NOW) == payload
    assert payload["commands"]["health"]
    assert payload["commands"]["deploy"]
    assert "None" not in json.dumps(payload["commands"])


def test_update_authorization_binds_observed_current_image_to_preflight() -> None:
    payload = _authorization()
    payload["recovery"].update(
        target_mode="update",
        observed_current_image_digest="sha256:" + "e" * 64,
    )
    payload["public_url"] = "https://bp-approved-app.synthetic.azurecontainerapps.io"
    payload["public_url_source"] = "exact"

    commands = _expected_commands(payload)

    assert "--observed-current-image-digest" in commands["preflight"][0]
    assert ("--observed-current-image-digest", "sha256:" + "e" * 64) in tuple(
        zip(commands["preflight"][0], commands["preflight"][0][1:])
    )
    assert commands["activate"] == ()


def test_update_target_prepares_jobs_without_disabling_the_healthy_app() -> None:
    payload = _authorization()
    payload["recovery"].update(
        target_mode="update",
        observed_current_image_digest=payload["release"]["rollback_image_digest"],
    )
    payload["public_url"] = "https://bp-approved-app.synthetic.azurecontainerapps.io"
    payload["public_url_source"] = "exact"

    commands = _expected_commands(payload)
    order = list(verifier_execution_order(payload))

    assert len(commands["provision"]) == 2
    assert all(
        command[:2]
        == (".venv/bin/python", "scripts/update_azure_job_binding.py")
        for command in commands["provision"]
    )
    assert commands["activate"] == ()
    assert "activate" not in order
    serialized = json.dumps(commands)
    assert "az provider register" not in serialized
    assert "applicationEnabled=false" not in serialized
    assert "--mode initial" not in serialized


def test_nonupdate_authorization_rejects_observed_current_image(
    tmp_path: Path,
) -> None:
    path = tmp_path / "LAUNCH_AUTHORIZATION.md"
    payload = _authorization()
    payload["recovery"]["observed_current_image_digest"] = "sha256:" + "e" * 64
    _write(path, payload)

    with pytest.raises(AuthorizationInvalid, match="authorization_recovery_invalid"):
        load_authorization(path, now=NOW)


def test_live_ai_browser_flow_requires_explicit_paid_authority(tmp_path: Path) -> None:
    path = tmp_path / "LAUNCH_AUTHORIZATION.md"
    payload = _authorization()
    _enable_paid_ai(payload)
    payload["commands"] = _commands(payload)
    payload["execution_order"] = _execution_order(payload)
    _write(path, payload)

    assert load_authorization(path, now=NOW) == payload
    assert payload["commands"]["paid_ai_smoke"][0].endswith(
        "--check browser --scenario paid-ai"
    )
    assert payload["commands"]["budget_failure"]
    assert payload["commands"]["provider_failure"]
    assert payload["execution_order"].index("budget_failure") < payload[
        "execution_order"
    ].index("deploy")
    assert payload["execution_order"].index("provider_failure") < payload[
        "execution_order"
    ].index("deploy")


def test_registry_publish_requires_exact_candidate_command(tmp_path: Path) -> None:
    path = tmp_path / "LAUNCH_AUTHORIZATION.md"
    payload = _authorization()
    payload["external_publication"]["registry_publish"] = True
    payload["allowed_operations"].insert(1, "registry_publish")
    payload["commands"] = _commands(payload)
    payload["execution_order"] = _execution_order(payload)
    _write(path, payload)

    assert load_authorization(path, now=NOW) == payload
    assert payload["commands"]["registry_publish"] == [
        ".venv/bin/python scripts/publish_registry_image.py "
        "--subscription 11111111-1111-4111-8111-111111111111 "
        "--registry bpapprovedregistry --repository bizpulse "
        f"--candidate-git-sha {payload['release']['git_sha']} "
        f"--authorization-id {payload['authorization_id']} "
        f"--expected-digest {payload['release']['image_digest']} "
        f"--image-input-sha256 {payload['release']['image_input_sha256']}",
        ".venv/bin/python scripts/publish_registry_image.py "
        "--subscription 11111111-1111-4111-8111-111111111111 "
        "--registry bpapprovedregistry --repository bizpulse "
        f"--candidate-git-sha {payload['release']['rollback_git_sha']} "
        f"--authorization-id {payload['authorization_id']} "
        f"--expected-digest {payload['release']['rollback_image_digest']} "
        "--image-input-sha256 "
        f"{payload['release']['rollback_image_input_sha256']}",
    ]


def test_provision_registers_container_apps_provider_before_any_resource_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "LAUNCH_AUTHORIZATION.md"
    payload = _authorization()
    _write(path, payload)

    assert load_authorization(path, now=NOW) == payload
    assert payload["commands"]["provision"][0] == (
        "az provider register "
        "--subscription 11111111-1111-4111-8111-111111111111 "
        "--namespace Microsoft.App --wait --only-show-errors --output none"
    )


@pytest.mark.parametrize(
    ("paid", "cap"),
    [(True, "0.00"), (False, "0.25")],
)
def test_ai_smoke_cost_cap_matches_paid_authority(
    tmp_path: Path,
    paid: bool,
    cap: str,
) -> None:
    path = tmp_path / "LAUNCH_AUTHORIZATION.md"
    payload = _authorization()
    if paid:
        _enable_paid_ai(payload)
    payload["limits_usd"]["openai_smoke_cap"] = cap
    payload["commands"] = _commands(payload)
    payload["execution_order"] = _execution_order(payload)
    _write(path, payload)

    with pytest.raises(AuthorizationInvalid, match="authorization_publication_invalid"):
        load_authorization(path, now=NOW)


@pytest.mark.parametrize(
    ("field", "below_minimum"),
    [
        ("daily_attempt_limit", 3),
        ("monthly_token_limit", 255_999),
        ("session_attempt_limit_per_minute", 2),
        ("global_attempt_limit_per_minute", 3),
    ],
)
def test_live_ai_authority_covers_every_prescribed_provider_attempt(
    tmp_path: Path,
    field: str,
    below_minimum: int,
) -> None:
    path = tmp_path / "LAUNCH_AUTHORIZATION.md"
    payload = _authorization()
    _enable_paid_ai(payload)
    payload["ai_limits"][field] = below_minimum
    payload["commands"] = _commands(payload)
    payload["execution_order"] = _execution_order(payload)
    _write(path, payload)

    with pytest.raises(AuthorizationInvalid, match="authorization_ai_limits_invalid"):
        load_authorization(path, now=NOW)


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda value: value.update(extra="forbidden"), "authorization_fields_invalid"),
        (lambda value: value.update(public_url="http://unsafe.test"), "authorization_url_invalid"),
        (lambda value: value["release"].update(image_digest="mutable:latest"), "authorization_digest_invalid"),
        (lambda value: value["secret_presence"].update(openai_api_key="sk-proj-secretvalue12345"), "authorization_secret_presence_invalid"),
        (lambda value: value["secret_presence"].pop("registry_password"), "authorization_secret_presence_invalid"),
        (lambda value: value["limits_usd"].update(hard_cap=float("nan")), "authorization_limits_invalid"),
        (lambda value: value["limits_usd"].update(openai_smoke_cap="101"), "authorization_limits_invalid"),
        (lambda value: value["generated_names"].pop("migration_job"), "authorization_generated_names_invalid"),
        (lambda value: value["generated_names"].pop("seed_job"), "authorization_generated_names_invalid"),
        (lambda value: value["resources"]["postgres"].update(public_network=True), "authorization_resources_invalid"),
        (lambda value: value["resources"]["postgres"].update(sku="B_Standard_B1ms"), "authorization_resources_invalid"),
        (lambda value: value["resources"]["application"].update(sku="Dedicated"), "authorization_resources_invalid"),
        (lambda value: value["recovery"].update(blob_soft_delete_days=30), "authorization_recovery_invalid"),
        (lambda value: value["retry_limits"].update(deploy=1), "authorization_retry_limits_invalid"),
        (lambda value: value["commands"].update(deploy=[]), "authorization_commands_invalid"),
        (
            lambda value: value.update(
                execution_order=list(reversed(value["execution_order"]))
            ),
            "authorization_execution_order_invalid",
        ),
        (
                lambda value: (
                    value["external_publication"].update(paid_ai_smoke=True),
                    value["commands"].update(
                        paid_ai_smoke=[
                            ".venv/bin/python tests/hosted/paid_ai_smoke.py "
                            "--url https://bp-approved-app.example.azurecontainerapps.io"
                        ]
                    ),
            ),
            "authorization_publication_invalid",
        ),
    ],
)
def test_authorization_parser_fails_closed(
    tmp_path: Path,
    mutation,
    error: str,
) -> None:
    path = tmp_path / "LAUNCH_AUTHORIZATION.md"
    payload = _authorization()
    mutation(payload)
    _write(path, payload)

    with pytest.raises(AuthorizationInvalid, match=error):
        load_authorization(path, now=NOW)


def test_authorization_rejects_extra_prose_duplicate_keys_and_secret_text(
    tmp_path: Path,
) -> None:
    path = tmp_path / "LAUNCH_AUTHORIZATION.md"
    payload = _authorization()
    _write(path, payload, suffix="password=must-not-be-here\n")
    with pytest.raises(AuthorizationInvalid, match="authorization_document_invalid"):
        load_authorization(path, now=NOW)

    source = json.dumps(payload, sort_keys=True)
    source = source.replace(
        '"schema_version":',
        '"schema_version": "duplicate", "schema_version":',
        1,
    )
    path.write_text(f"# NEWCaostone Launch Authorization\n\n```json\n{source}\n```\n")
    with pytest.raises(AuthorizationInvalid, match="authorization_json_duplicate_key"):
        load_authorization(path, now=NOW)


def test_cli_requires_external_exact_document_hash_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "LAUNCH_AUTHORIZATION.md"
    _write(path, _authorization())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(
        "tests.hosted.verify_azure_demo._validate_candidate_inputs",
        lambda _release: None,
    )
    monkeypatch.setattr(
        "tests.hosted.verify_azure_demo._validate_release_manifest_binding",
        lambda _release: None,
    )

    assert main(
        ["--authorization", str(path), "--approved-sha256", "0" * 64],
        now=NOW,
    ) == 1
    assert "launch_package=invalid" in capsys.readouterr().out
    assert main(
        ["--authorization", str(path), "--approved-sha256", digest],
        now=NOW,
    ) == 2
    output = capsys.readouterr().out
    assert "launch_package=valid" in output
    assert "approval_binding=matched" in output
    assert "hosted_verification=not_executed" in output


def test_candidate_inputs_must_be_clean_and_come_from_exact_candidate_tree() -> None:
    candidate = "a" * 40
    attestation = "b" * 40
    candidate_payloads = {
        path: f"candidate:{path}".encode() for path in CANDIDATE_HASH_PATHS.values()
    }
    release = {
        "attestation_git_sha": attestation,
        "git_sha": candidate,
        "rollback_git_sha": "c" * 40,
        **{
            field: hashlib.sha256(candidate_payloads[path]).hexdigest()
            for field, path in CANDIDATE_HASH_PATHS.items()
        },
    }
    responses = {
        ("status", "--porcelain=v1", "--untracked-files=all", "--", "bizpulse"): b"",
        ("rev-parse", "HEAD"): attestation.encode(),
        (
            "diff",
            "--name-only",
            candidate,
            attestation,
            "--",
            "bizpulse",
        ): (
            b"bizpulse/release/attestations/"
            + candidate.encode()
            + b".json\n"
        ),
        (
            "ls-tree",
            "-r",
            "--name-only",
            candidate,
            "--",
            "bizpulse",
        ): ("\n".join(sorted(REQUIRED_CANDIDATE_PATHS)) + "\n").encode(),
        ("merge-base", "--is-ancestor", "c" * 40, candidate): b"",
        (
            "show",
            f"{'c' * 40}:bizpulse/src/db/readiness.py",
        ): b'EXPECTED_SCHEMA_REVISION = "0008_ai_budget_ledger"\n',
        (
            "show",
            f"{'c' * 40}:bizpulse/alembic/versions/0008_ai_budget_ledger.py",
        ): b'revision: str = "0008_ai_budget_ledger"\n',
        (
            "show",
            f"{'c' * 40}:bizpulse/Dockerfile",
        ): b'CMD ["python", "--no-access-log"]\n',
        **{
            ("show", f"{candidate}:{path}"): payload
            for path, payload in candidate_payloads.items()
        },
    }

    _validate_candidate_inputs(release, git_reader=lambda *args: responses[args])

    responses[("status", "--porcelain=v1", "--untracked-files=all", "--", "bizpulse")] = (
        b"?? bizpulse/infra/untracked.bicep\n"
    )
    with pytest.raises(AuthorizationInvalid, match="authorization_candidate_dirty"):
        _validate_candidate_inputs(release, git_reader=lambda *args: responses[args])


def test_authorization_rejects_expired_unbound_or_secret_bearing_commands(
    tmp_path: Path,
) -> None:
    path = tmp_path / "LAUNCH_AUTHORIZATION.md"

    expired = _authorization()
    expired["issued_at"] = "2020-01-01T00:00:00Z"
    expired["expires_at"] = "2020-01-02T00:00:00Z"
    _write(path, expired)
    with pytest.raises(AuthorizationInvalid, match="authorization_expired"):
        load_authorization(path, now=NOW)

    destructive = _authorization()
    destructive["commands"]["deploy"] = [
        "az group delete --name unrelated-authority --yes"
    ]
    _write(path, destructive)
    with pytest.raises(AuthorizationInvalid, match="authorization_commands_invalid"):
        load_authorization(path, now=NOW)

    mutable_image = _authorization()
    mutable_image["commands"]["deploy"] = [
        "az deployment group create "
        "--subscription 11111111-1111-4111-8111-111111111111 "
        "--resource-group rg-synthetic-demo-approved "
        "--parameters deploymentEnabled=true applicationEnabled=true "
        f"containerImage=bpapprovedregistry.azurecr.io/bizpulse:latest note=sha256:{'b' * 64}"
    ]
    _write(path, mutable_image)
    with pytest.raises(AuthorizationInvalid, match="authorization_commands_invalid"):
        load_authorization(path, now=NOW)

    secret_flag = _authorization()
    secret_flag["commands"]["deploy"][0] += (
        " --registry-password SuperSecretValue123"
    )
    _write(path, secret_flag)
    with pytest.raises(AuthorizationInvalid, match="authorization_commands_invalid"):
        load_authorization(path, now=NOW)

    wrong_registry = _authorization()
    wrong_registry["external_publication"]["registry_publish"] = True
    wrong_registry["allowed_operations"].insert(1, "registry_publish")
    wrong_registry["execution_order"] = _execution_order(wrong_registry)
    wrong_registry["commands"]["registry_publish"] = [
        "az acr build --subscription 11111111-1111-4111-8111-111111111111 "
        "--resource-group rg-synthetic-demo-approved --registry unrelated "
        f"--image bizpulse@sha256:{'b' * 64}"
    ]
    _write(path, wrong_registry)
    with pytest.raises(AuthorizationInvalid, match="authorization_commands_invalid"):
        load_authorization(path, now=NOW)

    destructive_deployment_mode = _authorization()
    destructive_deployment_mode["commands"]["deploy"][0] += " --mode Complete"
    _write(path, destructive_deployment_mode)
    with pytest.raises(AuthorizationInvalid, match="authorization_commands_invalid"):
        load_authorization(path, now=NOW)

    method_override = _authorization()
    method_override["commands"]["health"][0] += (
        " --request DELETE https://bp-approved-app.example.azurecontainerapps.io/"
        "api/v1/actions"
    )
    _write(path, method_override)
    with pytest.raises(AuthorizationInvalid, match="authorization_commands_invalid"):
        load_authorization(path, now=NOW)


def test_authorization_binds_candidate_infra_hashes(tmp_path: Path) -> None:
    path = tmp_path / "LAUNCH_AUTHORIZATION.md"
    payload = _authorization()
    payload["release"]["infra_bicep_sha256"] = "0" * 64
    _write(path, payload)

    with pytest.raises(AuthorizationInvalid, match="authorization_infra_hash_invalid"):
        load_authorization(path, now=NOW)

    payload = _authorization()
    payload["release"]["git_sha"] = "a" * 40
    with pytest.raises(AuthorizationInvalid, match="authorization_git_authority_invalid"):
        _validate_release_manifest_binding(payload["release"])


def test_cli_hashes_and_parses_the_same_document_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "LAUNCH_AUTHORIZATION.md"
    _write(path, _authorization())
    valid_source = path.read_text()
    forged_source = valid_source.replace(
        '"resource_group": "rg-synthetic-demo-approved"',
        '"resource_group": "rg-unapproved-target"',
        1,
    )
    monkeypatch.setattr(Path, "read_text", lambda _self: valid_source)
    monkeypatch.setattr(Path, "read_bytes", lambda _self: forged_source.encode())

    digest = hashlib.sha256(forged_source.encode()).hexdigest()
    assert main(
        ["--authorization", str(path), "--approved-sha256", digest],
        now=NOW,
    ) == 1
    assert capsys.readouterr().out == "launch_package=invalid\n"


def test_cli_fails_closed_on_invalid_collection_types(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "LAUNCH_AUTHORIZATION.md"
    payload = _authorization()
    payload["server_settings"] = None
    _write(path, payload)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    assert main(
        ["--authorization", str(path), "--approved-sha256", digest],
        now=NOW,
    ) == 1
    assert capsys.readouterr().out == "launch_package=invalid\n"
