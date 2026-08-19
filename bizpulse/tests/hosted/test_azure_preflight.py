from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from scripts.azure_recovery_preflight import (
    AzurePreflightFailed,
    run_recovery_preflight,
)
from scripts.verify_phase1_fence import Phase1FenceFailed, verify_phase1_fence

SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"
IMAGE = "sha256:" + "b" * 64
ROLLBACK = "sha256:" + "d" * 64
CURRENT = "sha256:" + "e" * 64
MANIFEST = "c" * 64
VERSION = "33333333-3333-4333-8333-333333333333"
NOW = datetime(2026, 8, 14, 17, 0, tzinfo=UTC)


def _prepared_outputs() -> list[object]:
    app_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-approved"
        "/providers/Microsoft.App/containerApps/bp-approved-app"
    )
    postgres_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-approved"
        "/providers/Microsoft.DBforPostgreSQL/flexibleServers/bp-approved-pg"
    )
    storage_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-approved"
        "/providers/Microsoft.Storage/storageAccounts/bpapprovedstorage"
    )
    monitoring_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-approved"
        "/providers/Microsoft.OperationalInsights/workspaces/bp-approved-logs"
    )
    environment_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-approved"
        "/providers/Microsoft.App/managedEnvironments/bp-approved-env"
    )
    vnet_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-approved"
        "/providers/Microsoft.Network/virtualNetworks/bp-approved-vnet"
    )
    dns_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-approved"
        "/providers/Microsoft.Network/privateDnsZones/"
        "private.postgres.database.azure.com"
    )
    insights_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-approved"
        "/providers/Microsoft.Insights/components/bp-approved-insights"
    )
    registry_identity_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-approved"
        "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
        "bp-approved-registry"
    )
    return [
        {"id": SUBSCRIPTION},
        {"location": "brazilsouth"},
        *(
            [{"name": name}]
            for name in (
                "bp-approved-app",
                "bp-approved-env",
                "bp-approved-prepare",
                "bp-approved-seed",
                "bp-approved-sessions",
                "bp-approved-storage",
                "bp-approved-logs",
                "bp-approved-insights",
                "bp-approved-pg",
                "bpapprovedstorage",
                "bp-approved-vnet",
                "private.postgres.database.azure.com",
            )
        ),
        {"digest": IMAGE},
        {"digest": ROLLBACK},
        {
            "id": app_id,
            "identity": {
                "principalId": None,
                "tenantId": None,
                "type": "UserAssigned",
                "userAssignedIdentities": {
                    registry_identity_id: {
                        "clientId": "44444444-4444-4444-8444-444444444444",
                        "principalId": "55555555-5555-4555-8555-555555555555",
                    }
                },
            },
            "location": "brazilsouth",
            "name": "bp-approved-app",
            "properties": {
                "environmentId": environment_id,
                "configuration": {
                    "activeRevisionsMode": "Single",
                    "registries": [
                        {
                            "identity": registry_identity_id,
                            "passwordSecretRef": None,
                            "server": "bpapprovedregistry.azurecr.io",
                            "username": None,
                        }
                    ],
                    "ingress": {
                        "external": False,
                        "fqdn": "bp-approved-app.synthetic.azurecontainerapps.io",
                        "traffic": [{"latestRevision": True, "weight": 100}],
                    },
                },
                "latestReadyRevisionName": "bp-approved-app--prep-bbbbbbb",
                "latestRevisionName": "bp-approved-app--prep-bbbbbbb",
                "provisioningState": "Succeeded",
                "template": {
                    "containers": [
                        {
                            "image": (
                                "bpapprovedregistry.azurecr.io/bizpulse@" + IMAGE
                            ),
                            "resources": {"cpu": 0.5, "memory": "1Gi"},
                        }
                    ],
                    "scale": {"maxReplicas": 1, "minReplicas": 0},
                },
            },
        },
        {
            "id": postgres_id,
            "location": "brazilsouth",
            "name": "bp-approved-pg",
            "properties": {
                "backup": {
                    "backupRetentionDays": 7,
                    "earliestRestoreDate": "2026-08-08T12:00:00Z",
                },
                "network": {
                    "delegatedSubnetResourceId": f"{vnet_id}/subnets/postgres",
                    "privateDnsZoneArmResourceId": dns_id,
                    "publicNetworkAccess": "Disabled",
                },
                "state": "Ready",
                "storage": {"storageSizeGB": 32},
                "version": "16",
            },
            "sku": {"name": "Standard_B1ms", "tier": "Burstable"},
        },
        [
            {
                "id": f"{postgres_id}/backups/automatic-1",
                "backupType": "Full",
                "completedTime": "2026-08-14T12:00:00Z",
                "source": "Automatic",
            }
        ],
        {
            "id": storage_id,
            "location": "brazilsouth",
            "name": "bpapprovedstorage",
            "properties": {
                "allowBlobPublicAccess": False,
                "minimumTlsVersion": "TLS1_2",
                "supportsHttpsTrafficOnly": True,
            },
            "sku": {"name": "Standard_LRS"},
        },
        {
            "containerDeleteRetentionPolicy": {"days": 7, "enabled": True},
            "deleteRetentionPolicy": {"days": 7, "enabled": True},
        },
        {
            "id": monitoring_id,
            "location": "brazilsouth",
            "name": "bp-approved-logs",
            "retentionInDays": 30,
            "sku": {"name": "PerGB2018"},
        },
        {
            "id": environment_id,
            "location": "brazilsouth",
            "name": "bp-approved-env",
            "properties": {
                "appLogsConfiguration": {"destination": "log-analytics"},
                "provisioningState": "Succeeded",
                "vnetConfiguration": {
                    "infrastructureSubnetId": f"{vnet_id}/subnets/container-apps"
                },
            },
        },
        {
            "id": insights_id,
            "kind": "web",
            "location": "brazilsouth",
            "name": "bp-approved-insights",
            "properties": {
                "Application_Type": "web",
                "DisableLocalAuth": True,
                "WorkspaceResourceId": monitoring_id,
            },
        },
        {"status": "enabled"},
        {
            "clientId": "44444444-4444-4444-8444-444444444444",
            "id": registry_identity_id,
            "location": "brazilsouth",
            "name": "bp-approved-registry",
            "principalId": "55555555-5555-4555-8555-555555555555",
        },
        [
            {
                "principalId": "55555555-5555-4555-8555-555555555555",
                "roleDefinitionId": (
                    f"/subscriptions/{SUBSCRIPTION}/providers/"
                    "Microsoft.Authorization/roleDefinitions/"
                    "7f951dda-4ed3-4680-a7ca-43fe172d538d"
                ),
                "scope": (
                    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-approved/"
                    "providers/Microsoft.ContainerRegistry/registries/"
                    "bpapprovedregistry"
                ),
            }
        ],
    ]


def _run_prepared(
    outputs: list[object],
    calls: list[tuple[str, ...]] | None = None,
    *,
    observed_current_image_digest: str | None = None,
) -> None:
    run_recovery_preflight(
        subscription_id=SUBSCRIPTION,
        resource_group="rg-approved",
        region="brazilsouth",
        target_mode="prepared",
        app_name="bp-approved-app",
        container_environment="bp-approved-env",
        application_insights="bp-approved-insights",
        log_workspace="bp-approved-logs",
        job_names=(
            "bp-approved-prepare",
            "bp-approved-seed",
            "bp-approved-sessions",
            "bp-approved-storage",
        ),
        virtual_network="bp-approved-vnet",
        postgres_dns_zone="private.postgres.database.azure.com",
        postgres_server="bp-approved-pg",
        postgres_backup_days=7,
        postgres_sku="Standard_B1ms",
        postgres_tier="Burstable",
        postgres_storage_gb=32,
        postgres_version="16",
        storage_account="bpapprovedstorage",
        storage_sku="Standard_LRS",
        blob_retention_days=7,
        application_sku="Consumption",
        application_cpu="0.5",
        application_memory="1Gi",
        application_min_replicas=1,
        application_max_replicas=1,
        log_retention_days=30,
        registry_name="bpapprovedregistry",
        registry_identity="bp-approved-registry",
        image_repository="bizpulse",
        image_digest=IMAGE,
        rollback_image_digest=ROLLBACK,
        public_url=None,
        observed_current_image_digest=observed_current_image_digest,
        runner=_runner(outputs, calls if calls is not None else []),
        clock=lambda: NOW,
    )


def _run_update(
    outputs: list[object],
    *,
    observed_current_image_digest: str | None,
) -> None:
    run_recovery_preflight(
        subscription_id=SUBSCRIPTION,
        resource_group="rg-approved",
        region="brazilsouth",
        target_mode="update",
        app_name="bp-approved-app",
        container_environment="bp-approved-env",
        application_insights="bp-approved-insights",
        log_workspace="bp-approved-logs",
        job_names=(
            "bp-approved-prepare",
            "bp-approved-seed",
            "bp-approved-sessions",
            "bp-approved-storage",
        ),
        virtual_network="bp-approved-vnet",
        postgres_dns_zone="private.postgres.database.azure.com",
        postgres_server="bp-approved-pg",
        postgres_backup_days=7,
        postgres_sku="Standard_B1ms",
        postgres_tier="Burstable",
        postgres_storage_gb=32,
        postgres_version="16",
        storage_account="bpapprovedstorage",
        storage_sku="Standard_LRS",
        blob_retention_days=7,
        application_sku="Consumption",
        application_cpu="0.5",
        application_memory="1Gi",
        application_min_replicas=1,
        application_max_replicas=1,
        log_retention_days=30,
        registry_name="bpapprovedregistry",
        registry_identity="bp-approved-registry",
        image_repository="bizpulse",
        image_digest=IMAGE,
        rollback_image_digest=ROLLBACK,
        observed_current_image_digest=observed_current_image_digest,
        public_url="https://bp-approved-app.synthetic.azurecontainerapps.io",
        runner=_runner(outputs, []),
        health_verifier=lambda _url: None,
        clock=lambda: NOW,
    )


def _update_outputs() -> list[object]:
    outputs = deepcopy(_prepared_outputs())
    app = outputs[16]
    app["properties"]["configuration"]["ingress"]["external"] = True
    app["properties"]["template"]["containers"][0]["image"] = (
        "bpapprovedregistry.azurecr.io/bizpulse@" + CURRENT
    )
    app["properties"]["template"]["scale"]["minReplicas"] = 1
    return outputs


def _runner(outputs: list[object], calls: list[tuple[str, ...]]):
    remaining = iter(outputs)

    def run(command, **kwargs):
        calls.append(tuple(command))
        payload = next(remaining)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload),
            stderr="",
        )

    return run


def _job(name: str, image: str) -> dict[str, object]:
    suffix = name.rsplit("-", 1)[-1]
    specs = {
        "prepare": ("prepare", ["scripts/prepare_cloud.py"]),
        "seed": (
            "seed",
            [
                "scripts/seed_demo.py",
                "tests/fixtures/synthetic/v1",
                "--expected-manifest-sha256",
                MANIFEST,
                "--expected-dataset-version-id",
                VERSION,
            ],
        ),
        "sessions": ("maintain-sessions", ["scripts/maintain_sessions.py"]),
        "storage": (
            "maintain-storage",
            ["scripts/maintain_storage.py", "--expire-temporary"],
        ),
    }
    container_name, arguments = specs[suffix]
    return {
        "name": name,
        "properties": {
            "configuration": {"triggerType": "Manual"},
            "template": {
                "containers": [
                    {
                        "name": container_name,
                        "image": image,
                        "command": ["python"],
                        "args": arguments,
                    }
                ]
            },
        },
    }


def _phase2_job(name: str, image: str) -> dict[str, object]:
    job = _job(name, image)
    suffix = name.rsplit("-", 1)[-1]
    if suffix in {"sessions", "storage"}:
        job["properties"]["configuration"] = {
            "scheduleTriggerConfig": {
                "cronExpression": (
                    "*/15 * * * *" if suffix == "sessions" else "0 * * * *"
                ),
                "parallelism": 1,
                "replicaCompletionCount": 1,
            },
            "triggerType": "Schedule",
        }
    return job


def _phase2_env() -> list[dict[str, str]]:
    return [
        {"name": "BIZPULSE_AI_CHAT_ENABLED", "value": "false"},
        {"name": "BIZPULSE_AI_DAILY_ATTEMPT_LIMIT", "value": "120"},
        {"name": "BIZPULSE_AI_MONTHLY_TOKEN_LIMIT", "value": "150000"},
        {"name": "BIZPULSE_AI_MAX_CONCURRENT_TURNS", "value": "15"},
        {
            "name": "BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE",
            "value": "3",
        },
        {
            "name": "BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE",
            "value": "20",
        },
        {
            "name": "BIZPULSE_DEMO_SESSION_RATE_LIMIT_PER_HOUR",
            "value": "50",
        },
        {"name": "BIZPULSE_OPENAI_MODEL", "value": "gpt-5.4-nano-2026-03-17"},
        {"name": "BIZPULSE_OPENAI_REASONING_EFFORT", "value": "low"},
    ]


def _phase2_authority() -> dict[str, object]:
    return {
        "environment_name": "bp-approved-env",
        "ai_enabled": False,
        "ai_daily_attempt_limit": 120,
        "ai_monthly_token_limit": 150_000,
        "ai_max_concurrent_turns": 15,
        "ai_session_attempt_limit_per_minute": 3,
        "ai_global_attempt_limit_per_minute": 20,
        "demo_session_rate_limit_per_hour": 50,
    }


def _phase_app_authority() -> dict[str, str]:
    return {
        "storage_account_name": "bpapprovedstorage",
        "blob_container_name": "synthetic-demo",
    }


def _expected_app_probes() -> list[dict[str, object]]:
    return [
        {
            "type": "Liveness",
            "httpGet": {"path": "/health/live", "port": 8000, "scheme": "HTTP"},
            "initialDelaySeconds": 15,
            "periodSeconds": 30,
            "timeoutSeconds": 5,
            "failureThreshold": 3,
        },
        {
            "type": "Readiness",
            "httpGet": {"path": "/health/ready", "port": 8000, "scheme": "HTTP"},
            "initialDelaySeconds": 10,
            "periodSeconds": 10,
            "timeoutSeconds": 5,
            "failureThreshold": 3,
        },
    ]


def _phase1_app(image: str) -> dict[str, object]:
    return {
        "name": "bp-approved-app",
        "properties": {
            "latestRevisionName": "bp-approved-app--prep-bbbbbbb",
            "configuration": {
                "activeRevisionsMode": "Single",
                "ingress": {
                    "external": False,
                    "traffic": [{"latestRevision": True, "weight": 100}],
                },
                "secrets": [],
            },
            "template": {
                "containers": [
                    {
                        "name": "bizpulse",
                        "image": image,
                        "command": ["python"],
                        "args": ["scripts/phase1_fence_server.py"],
                        "env": [
                            {
                                "name": "BIZPULSE_RUNTIME_ENVIRONMENT",
                                "value": "phase1-fenced",
                            }
                        ],
                        "probes": _expected_app_probes(),
                    }
                ],
                "scale": {"maxReplicas": 1, "minReplicas": 0},
            },
        },
    }


def _phase1_outputs(image: str) -> list[object]:
    outputs: list[object] = [
        _phase1_app(image),
        [
            {
                "name": "bp-approved-app--prep-bbbbbbb",
                "properties": {"replicas": 0},
            }
        ],
    ]
    for name in (
        "bp-approved-prepare",
        "bp-approved-seed",
        "bp-approved-sessions",
        "bp-approved-storage",
    ):
        outputs.extend([_job(name, image), []])
    return outputs


def _phase2_app(image: str) -> dict[str, object]:
    return {
        "name": "bp-approved-app",
        "properties": {
            "configuration": {
                "activeRevisionsMode": "Single",
                "ingress": {
                    "external": True,
                    "fqdn": "bp-approved-app.synthetic.azurecontainerapps.io",
                    "traffic": [{"latestRevision": True, "weight": 100}],
                },
                "secrets": [
                    {"name": "database-url"},
                    {"name": "blob-connection-string"},
                    {"name": "operator-password-hash"},
                    {"name": "session-pepper"},
                ],
            },
            "environmentId": (
                f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-approved"
                "/providers/Microsoft.App/managedEnvironments/bp-approved-env"
            ),
            "latestReadyRevisionName": "bp-approved-app--bbbbbbbbbbbb",
            "latestRevisionName": "bp-approved-app--bbbbbbbbbbbb",
            "provisioningState": "Succeeded",
            "template": {
                "containers": [
                    {
                        "name": "bizpulse",
                        "env": [
                            {
                                "name": "BIZPULSE_RUNTIME_ENVIRONMENT",
                                "value": "cloud",
                            },
                            {
                                "name": "BIZPULSE_DATABASE_URL",
                                "secretRef": "database-url",
                            },
                            {
                                "name": "BIZPULSE_BLOB_ENDPOINT",
                                "value": (
                                    "https://bpapprovedstorage.blob.core.windows.net/"
                                ),
                            },
                            {
                                "name": "BIZPULSE_BLOB_CONTAINER",
                                "value": "synthetic-demo",
                            },
                            {
                                "name": "BIZPULSE_BLOB_CONNECTION_STRING",
                                "secretRef": "blob-connection-string",
                            },
                            {
                                "name": "BIZPULSE_ALLOWED_ORIGIN",
                                "value": (
                                    "https://bp-approved-app.synthetic."
                                    "azurecontainerapps.io"
                                ),
                            },
                            {
                                "name": "BIZPULSE_OPERATOR_PASSWORD_HASH",
                                "secretRef": "operator-password-hash",
                            },
                            {
                                "name": "BIZPULSE_SESSION_PEPPER",
                                "secretRef": "session-pepper",
                            },
                            *_phase2_env(),
                            {
                                "name": "APPLICATIONINSIGHTS_CONNECTION_STRING",
                                "value": (
                                    "InstrumentationKey=00000000-0000-4000-8000-"
                                    "000000000000;IngestionEndpoint=https://"
                                    "brazilsouth-0.in.applicationinsights.azure.com/"
                                ),
                            },
                        ],
                        "image": image,
                        "probes": _expected_app_probes(),
                    }
                ],
                "scale": {"maxReplicas": 1, "minReplicas": 1},
            },
        },
    }


def _phase2_outputs(image: str) -> list[object]:
    outputs: list[object] = [
        _phase2_app(image),
        [
            {
                "name": "bp-approved-app--bbbbbbbbbbbb",
                "properties": {"replicas": 1},
            }
        ],
    ]
    for name in (
        "bp-approved-prepare",
        "bp-approved-seed",
        "bp-approved-sessions",
        "bp-approved-storage",
    ):
        outputs.extend(
            [
                _phase2_job(name, image),
                [
                    {
                        "properties": {
                            "startTime": "2026-08-14T15:01:00Z",
                            "status": "Succeeded",
                        }
                    }
                ],
            ]
        )
    return outputs


@pytest.mark.parametrize(
    ("image_state", "digest_outputs", "expected_calls"),
    [
        ("present", [{"digest": IMAGE}, {"digest": ROLLBACK}], 18),
        ("pending-publication", [], 16),
    ],
)
def test_fresh_preflight_proves_target_absence_and_registry_authority(
    image_state: str,
    digest_outputs: list[dict[str, str]],
    expected_calls: int,
) -> None:
    calls: list[tuple[str, ...]] = []
    run_recovery_preflight(
        subscription_id=SUBSCRIPTION,
        resource_group="rg-approved",
        region="brazilsouth",
        target_mode="fresh",
        app_name="bp-approved-app",
        container_environment="bp-approved-env",
        application_insights="bp-approved-insights",
        log_workspace="bp-approved-logs",
        job_names=(
            "bp-approved-prepare",
            "bp-approved-seed",
            "bp-approved-sessions",
            "bp-approved-storage",
        ),
        virtual_network="bp-approved-vnet",
        postgres_dns_zone="private.postgres.database.azure.com",
        postgres_server="bp-approved-pg",
        postgres_backup_days=7,
        postgres_sku="Standard_B1ms",
        postgres_tier="Burstable",
        postgres_storage_gb=32,
        postgres_version="16",
        storage_account="bpapprovedstorage",
        storage_sku="Standard_LRS",
        blob_retention_days=7,
        application_sku="Consumption",
        log_retention_days=30,
        registry_name="bpapprovedregistry",
        registry_identity="bp-approved-registry",
        image_repository="bizpulse",
        image_digest=IMAGE,
        rollback_image_digest=ROLLBACK,
        current_image_state=image_state,
        public_url=None,
        runner=_runner(
            [
                {"id": SUBSCRIPTION},
                {"location": "brazilsouth"},
                *[[] for _index in range(12)],
                *digest_outputs,
                {"status": "enabled"},
                [],
            ],
            calls,
        ),
    )

    assert len(calls) == expected_calls
    assert all("delete" not in call and "update" not in call for call in calls)
    assert calls[-2][:5] == (
        "az",
        "acr",
        "config",
        "authentication-as-arm",
        "show",
    )


def test_fresh_preflight_rejects_acr_without_managed_identity_arm_tokens() -> None:
    outputs = [
        {"id": SUBSCRIPTION},
        {"location": "brazilsouth"},
        *[[] for _index in range(12)],
        {"status": "disabled"},
    ]

    with pytest.raises(
        AzurePreflightFailed,
        match="azure_preflight_registry_identity_invalid",
    ):
        run_recovery_preflight(
            subscription_id=SUBSCRIPTION,
            resource_group="rg-approved",
            region="brazilsouth",
            target_mode="fresh",
            app_name="bp-approved-app",
            container_environment="bp-approved-env",
            application_insights="bp-approved-insights",
            log_workspace="bp-approved-logs",
            job_names=(
                "bp-approved-prepare",
                "bp-approved-seed",
                "bp-approved-sessions",
                "bp-approved-storage",
            ),
            virtual_network="bp-approved-vnet",
            postgres_dns_zone="private.postgres.database.azure.com",
            postgres_server="bp-approved-pg",
            postgres_backup_days=7,
            postgres_sku="Standard_B1ms",
            postgres_tier="Burstable",
            postgres_storage_gb=32,
            postgres_version="16",
            storage_account="bpapprovedstorage",
            storage_sku="Standard_LRS",
            blob_retention_days=7,
            application_sku="Consumption",
            log_retention_days=30,
            registry_name="bpapprovedregistry",
            registry_identity="bp-approved-registry",
            image_repository="bizpulse",
            image_digest=IMAGE,
            rollback_image_digest=ROLLBACK,
            current_image_state="pending-publication",
            public_url=None,
            runner=_runner(outputs, []),
        )


def test_prepared_preflight_rejects_registry_identity_or_role_drift() -> None:
    wrong_app_identity = deepcopy(_prepared_outputs())
    wrong_app_identity[16]["identity"]["userAssignedIdentities"] = {
        "/wrong/identity": {}
    }
    with pytest.raises(
        AzurePreflightFailed,
        match="azure_preflight_registry_identity_invalid",
    ):
        _run_prepared(wrong_app_identity)

    wrong_role = deepcopy(_prepared_outputs())
    wrong_role[-1][0]["roleDefinitionId"] = "/wrong/role"
    with pytest.raises(
        AzurePreflightFailed,
        match="azure_preflight_registry_identity_invalid",
    ):
        _run_prepared(wrong_role)


def test_update_preflight_rejects_missing_backup_authority() -> None:
    outputs = _prepared_outputs()
    outputs[18] = []

    with pytest.raises(AzurePreflightFailed, match="azure_preflight_backup_invalid"):
        _run_prepared(outputs)


def test_update_preflight_accepts_observed_current_image_distinct_from_rollback() -> None:
    _run_update(
        _update_outputs(),
        observed_current_image_digest=CURRENT,
    )


def test_preflight_rejects_missing_or_nonupdate_observed_current_image() -> None:
    with pytest.raises(
        AzurePreflightFailed,
        match="azure_preflight_authority_invalid",
    ):
        _run_update(
            _update_outputs(),
            observed_current_image_digest=None,
        )

    with pytest.raises(
        AzurePreflightFailed,
        match="azure_preflight_authority_invalid",
    ):
        _run_prepared(
            _prepared_outputs(),
            observed_current_image_digest=CURRENT,
        )


def test_prepared_preflight_binds_actual_sku_capacity_and_backup_authority() -> None:
    _run_prepared(_prepared_outputs())


def test_prepared_preflight_accepts_azure_resource_id_casing() -> None:
    outputs = _prepared_outputs()
    app = outputs[16]
    app["id"] = app["id"].replace("containerApps", "containerapps")
    app["location"] = "Brazil South"
    assigned = app["identity"]["userAssignedIdentities"]
    identity_id, metadata = assigned.popitem()
    assigned[identity_id.replace("/resourceGroups/", "/resourcegroups/")] = metadata
    outputs[-2]["id"] = outputs[-2]["id"].replace(
        "/resourceGroups/", "/resourcegroups/"
    )
    outputs[-1][0]["scope"] = outputs[-1][0]["scope"].replace(
        "/resourceGroups/", "/resourcegroups/"
    )

    _run_prepared(outputs)


def test_prepared_preflight_rejects_cost_or_backup_drift() -> None:
    wrong_sku = deepcopy(_prepared_outputs())
    wrong_sku[17]["sku"]["name"] = "GP_Standard_D2s_v3"
    with pytest.raises(AzurePreflightFailed, match="azure_preflight_postgres_invalid"):
        _run_prepared(wrong_sku)

    stale_backup = deepcopy(_prepared_outputs())
    stale_backup[18][0]["completedTime"] = "2026-08-10T12:00:00Z"
    with pytest.raises(AzurePreflightFailed, match="azure_preflight_backup_invalid"):
        _run_prepared(stale_backup)

    unready_revision = deepcopy(_prepared_outputs())
    unready_revision[16]["properties"]["latestReadyRevisionName"] = (
        "bp-approved-app--old"
    )
    with pytest.raises(
        AzurePreflightFailed,
        match="azure_preflight_current_release_invalid",
    ):
        _run_prepared(unready_revision)


def test_prepared_preflight_rejects_missing_declared_resource() -> None:
    missing_environment = deepcopy(_prepared_outputs())
    missing_environment[3] = []
    with pytest.raises(AzurePreflightFailed, match="azure_preflight_target_missing"):
        _run_prepared(missing_environment)


def test_prepared_preflight_binds_app_environment_scale_and_resources() -> None:
    wrong_environment = deepcopy(_prepared_outputs())
    wrong_environment[16]["properties"]["environmentId"] = "/wrong/environment"
    with pytest.raises(
        AzurePreflightFailed,
        match="azure_preflight_current_release_invalid",
    ):
        _run_prepared(wrong_environment)

    wrong_scale = deepcopy(_prepared_outputs())
    wrong_scale[16]["properties"]["template"]["scale"]["maxReplicas"] = 10
    with pytest.raises(
        AzurePreflightFailed,
        match="azure_preflight_current_release_invalid",
    ):
        _run_prepared(wrong_scale)


def test_prepared_preflight_binds_private_network_and_monitoring_authority() -> None:
    wrong_dns = deepcopy(_prepared_outputs())
    wrong_dns[17]["properties"]["network"]["privateDnsZoneArmResourceId"] = (
        "/wrong/private-dns"
    )
    with pytest.raises(AzurePreflightFailed, match="azure_preflight_postgres_invalid"):
        _run_prepared(wrong_dns)

    wrong_environment_subnet = deepcopy(_prepared_outputs())
    wrong_environment_subnet[22]["properties"]["vnetConfiguration"][
        "infrastructureSubnetId"
    ] = "/wrong/subnet"
    with pytest.raises(AzurePreflightFailed, match="azure_preflight_environment_invalid"):
        _run_prepared(wrong_environment_subnet)

    wrong_workspace = deepcopy(_prepared_outputs())
    wrong_workspace[23]["properties"]["WorkspaceResourceId"] = "/wrong/workspace"
    with pytest.raises(
        AzurePreflightFailed,
        match="azure_preflight_application_insights_invalid",
    ):
        _run_prepared(wrong_workspace)


def test_prepared_preflight_accepts_strict_azure_cli_flat_shapes() -> None:
    outputs = deepcopy(_prepared_outputs())
    postgres = outputs[17]
    postgres.update(postgres.pop("properties"))
    postgres["storage"]["storageSizeGb"] = postgres["storage"].pop(
        "storageSizeGB"
    )
    storage = outputs[19]
    storage["properties"]["enableHttpsTrafficOnly"] = storage["properties"].pop(
        "supportsHttpsTrafficOnly"
    )
    insights = outputs[23]
    insights.update(
        {
            "applicationType": insights["properties"]["Application_Type"],
            "disableLocalAuth": insights["properties"]["DisableLocalAuth"],
            "workspaceResourceId": insights["properties"]["WorkspaceResourceId"],
        }
    )
    insights.pop("properties")

    _run_prepared(outputs)


def test_prepared_preflight_reads_authoritative_insights_resource_projection() -> None:
    calls: list[tuple[str, ...]] = []

    _run_prepared(_prepared_outputs(), calls)

    assert any(
        call[1:4] == ("resource", "show", "--subscription")
        and "Microsoft.Insights/components" in call
        and "2020-02-02" in call
        for call in calls
    )


def test_prepared_preflight_rejects_conflicting_cli_and_rest_shapes() -> None:
    outputs = deepcopy(_prepared_outputs())
    outputs[23]["workspaceResourceId"] = "/wrong/workspace"

    with pytest.raises(
        AzurePreflightFailed,
        match="azure_preflight_application_insights_invalid",
    ):
        _run_prepared(outputs)


def test_phase1_readback_requires_fenced_app_and_manual_idle_jobs() -> None:
    calls: list[tuple[str, ...]] = []
    image = "bpapprovedregistry.azurecr.io/bizpulse@" + IMAGE
    verify_phase1_fence(
        subscription_id=SUBSCRIPTION,
        resource_group="rg-approved",
        app_name="bp-approved-app",
        image=image,
        job_names=(
            "bp-approved-prepare",
            "bp-approved-seed",
            "bp-approved-sessions",
            "bp-approved-storage",
        ),
        synthetic_manifest_sha256=MANIFEST,
        synthetic_dataset_version_id=VERSION,
        **_phase_app_authority(),
        runner=_runner(
            [
                _phase1_app(image),
                [
                    {
                        "name": "bp-approved-app--prep-bbbbbbb",
                        "properties": {"replicas": 0},
                    }
                ],
                *sum(
                    (
                        [
                            _job(name, image),
                            [],
                        ]
                        for name in (
                            "bp-approved-prepare",
                            "bp-approved-seed",
                            "bp-approved-sessions",
                            "bp-approved-storage",
                        )
                    ),
                    [],
                ),
            ],
            calls,
        ),
    )
    assert len(calls) == 10


def test_phase1_readback_allows_bounded_default_scale_to_zero_cooldown() -> None:
    calls: list[tuple[str, ...]] = []
    image = "bpapprovedregistry.azurecr.io/bizpulse@" + IMAGE
    elapsed = [0.0]
    outputs: list[object] = [
        _phase1_app(image),
        *(
            [[{"properties": {"replicas": 1}}]] * 61
        ),
        [{"properties": {"replicas": 0}}],
    ]
    for name in (
        "bp-approved-prepare",
        "bp-approved-seed",
        "bp-approved-sessions",
        "bp-approved-storage",
    ):
        outputs.extend([_job(name, image), []])

    verify_phase1_fence(
        subscription_id=SUBSCRIPTION,
        resource_group="rg-approved",
        app_name="bp-approved-app",
        image=image,
        job_names=(
            "bp-approved-prepare",
            "bp-approved-seed",
            "bp-approved-sessions",
            "bp-approved-storage",
        ),
        synthetic_manifest_sha256=MANIFEST,
        synthetic_dataset_version_id=VERSION,
        **_phase_app_authority(),
        runner=_runner(outputs, calls),
        monotonic=lambda: elapsed[0],
        sleeper=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds),
    )

    assert elapsed[0] == 305


def test_phase1_readback_rejects_unknown_job_status() -> None:
    calls: list[tuple[str, ...]] = []
    image = "bpapprovedregistry.azurecr.io/bizpulse@" + IMAGE
    with pytest.raises(Phase1FenceFailed, match="phase1_job_execution_active"):
        verify_phase1_fence(
            subscription_id=SUBSCRIPTION,
            resource_group="rg-approved",
            app_name="bp-approved-app",
            image=image,
            job_names=(
                "bp-approved-prepare",
                "bp-approved-seed",
                "bp-approved-sessions",
                "bp-approved-storage",
            ),
            synthetic_manifest_sha256=MANIFEST,
            synthetic_dataset_version_id=VERSION,
            **_phase_app_authority(),
            runner=_runner(
                [
                    _phase1_app(image),
                    [{"properties": {"replicas": 0}}],
                    _job("bp-approved-prepare", image),
                    [{"properties": {"status": "Queued"}}],
                ],
                calls,
            ),
        )


def test_activate_fence_requires_one_current_success_for_prepare_and_seed() -> None:
    calls: list[tuple[str, ...]] = []
    image = "bpapprovedregistry.azurecr.io/bizpulse@" + IMAGE
    outputs: list[object] = [
        _phase1_app(image),
        [{"properties": {"replicas": 0}}],
    ]
    for name in (
        "bp-approved-prepare",
        "bp-approved-seed",
        "bp-approved-sessions",
        "bp-approved-storage",
    ):
        outputs.extend(
            [
                _job(name, image),
                (
                    [
                        {
                            "properties": {
                                "startTime": "2026-08-14T15:01:00Z",
                                "status": "Succeeded",
                            }
                        }
                    ]
                    if name in {"bp-approved-prepare", "bp-approved-seed"}
                    else []
                ),
            ]
        )

    verify_phase1_fence(
        subscription_id=SUBSCRIPTION,
        resource_group="rg-approved",
        app_name="bp-approved-app",
        image=image,
        job_names=(
            "bp-approved-prepare",
            "bp-approved-seed",
            "bp-approved-sessions",
            "bp-approved-storage",
        ),
        mode="activate",
        not_before=datetime(2026, 8, 14, 15, 0, tzinfo=UTC),
        synthetic_manifest_sha256=MANIFEST,
        synthetic_dataset_version_id=VERSION,
        **_phase_app_authority(),
        runner=_runner(outputs, calls),
    )

    assert len(calls) == 10


def test_phase2_fence_requires_active_app_exact_schedules_and_successes() -> None:
    calls: list[tuple[str, ...]] = []
    image = "bpapprovedregistry.azurecr.io/bizpulse@" + IMAGE
    outputs: list[object] = [
        _phase2_app(image),
        [
            {
                "name": "bp-approved-app--bbbbbbbbbbbb",
                "properties": {"replicas": 1},
            }
        ],
    ]
    for name in (
        "bp-approved-prepare",
        "bp-approved-seed",
        "bp-approved-sessions",
        "bp-approved-storage",
    ):
        outputs.extend(
            [
                _phase2_job(name, image),
                [
                    {
                        "properties": {
                            "startTime": "2026-08-14T15:01:00Z",
                            "status": "Succeeded",
                        }
                    }
                ],
            ]
        )

    verify_phase1_fence(
        subscription_id=SUBSCRIPTION,
        resource_group="rg-approved",
        app_name="bp-approved-app",
        image=image,
        job_names=(
            "bp-approved-prepare",
            "bp-approved-seed",
            "bp-approved-sessions",
            "bp-approved-storage",
        ),
        mode="phase2",
        not_before=datetime(2026, 8, 14, 15, 0, tzinfo=UTC),
        synthetic_manifest_sha256=MANIFEST,
        synthetic_dataset_version_id=VERSION,
        **_phase_app_authority(),
        **_phase2_authority(),
        runner=_runner(outputs, calls),
    )

    assert len(calls) == 10


def test_phase2_fence_rejects_wrong_schedule_or_failed_maintenance() -> None:
    image = "bpapprovedregistry.azurecr.io/bizpulse@" + IMAGE
    for mutation in ("cron", "failed"):
        outputs: list[object] = [
            _phase2_app(image),
            [
                {
                    "name": "bp-approved-app--bbbbbbbbbbbb",
                    "properties": {"replicas": 1},
                }
            ],
        ]
        for name in (
            "bp-approved-prepare",
            "bp-approved-seed",
            "bp-approved-sessions",
            "bp-approved-storage",
        ):
            job = _phase2_job(name, image)
            if mutation == "cron" and name.endswith("sessions"):
                job["properties"]["configuration"]["scheduleTriggerConfig"][
                    "cronExpression"
                ] = "* * * * *"
            status = (
                "Failed"
                if mutation == "failed" and name.endswith("storage")
                else "Succeeded"
            )
            outputs.extend(
                [
                    job,
                    [
                        {
                            "properties": {
                                "startTime": "2026-08-14T15:01:00Z",
                                "status": status,
                            }
                        }
                    ],
                ]
            )
        with pytest.raises(Phase1FenceFailed):
            verify_phase1_fence(
                subscription_id=SUBSCRIPTION,
                resource_group="rg-approved",
                app_name="bp-approved-app",
                image=image,
                job_names=(
                    "bp-approved-prepare",
                    "bp-approved-seed",
                    "bp-approved-sessions",
                    "bp-approved-storage",
                ),
                mode="phase2",
                not_before=datetime(2026, 8, 14, 15, 0, tzinfo=UTC),
                synthetic_manifest_sha256=MANIFEST,
                synthetic_dataset_version_id=VERSION,
                **_phase_app_authority(),
                **_phase2_authority(),
                runner=_runner(outputs, []),
            )


@pytest.mark.parametrize(
    "mutation",
    ("normal_command", "secret", "extra_env", "probe"),
)
def test_phase1_fence_rejects_mixed_application_authority(mutation: str) -> None:
    image = "bpapprovedregistry.azurecr.io/bizpulse@" + IMAGE
    outputs = _phase1_outputs(image)
    app = outputs[0]
    configuration = app["properties"]["configuration"]
    container = app["properties"]["template"]["containers"][0]
    if mutation == "normal_command":
        container.pop("command")
        container.pop("args")
    elif mutation == "secret":
        configuration["secrets"] = [{"name": "database-url"}]
    elif mutation == "extra_env":
        container["env"].append(
            {"name": "BIZPULSE_DATABASE_URL", "secretRef": "database-url"}
        )
    else:
        container["probes"][1]["httpGet"]["path"] = "/health"

    with pytest.raises(Phase1FenceFailed, match="phase1_app_not_fenced"):
        verify_phase1_fence(
            subscription_id=SUBSCRIPTION,
            resource_group="rg-approved",
            app_name="bp-approved-app",
            image=image,
            job_names=(
                "bp-approved-prepare",
                "bp-approved-seed",
                "bp-approved-sessions",
                "bp-approved-storage",
            ),
            synthetic_manifest_sha256=MANIFEST,
            synthetic_dataset_version_id=VERSION,
            **_phase_app_authority(),
            runner=_runner(outputs, []),
        )


@pytest.mark.parametrize(
    "mutation",
    ("fence_command", "missing_secret_ref", "openai_secret", "probe"),
)
def test_phase2_fence_rejects_mixed_application_authority(mutation: str) -> None:
    image = "bpapprovedregistry.azurecr.io/bizpulse@" + IMAGE
    outputs = _phase2_outputs(image)
    app = outputs[0]
    configuration = app["properties"]["configuration"]
    container = app["properties"]["template"]["containers"][0]
    if mutation == "fence_command":
        container["command"] = ["python"]
        container["args"] = ["scripts/phase1_fence_server.py"]
    elif mutation == "missing_secret_ref":
        container["env"] = [
            row
            for row in container["env"]
            if row["name"] != "BIZPULSE_SESSION_PEPPER"
        ]
    elif mutation == "openai_secret":
        configuration["secrets"].append({"name": "openai-api-key"})
        container["env"].append(
            {"name": "OPENAI_API_KEY", "secretRef": "openai-api-key"}
        )
    else:
        container["probes"][0]["httpGet"]["path"] = "/health"

    with pytest.raises(Phase1FenceFailed, match="phase1_app_not_fenced"):
        verify_phase1_fence(
            subscription_id=SUBSCRIPTION,
            resource_group="rg-approved",
            app_name="bp-approved-app",
            image=image,
            job_names=(
                "bp-approved-prepare",
                "bp-approved-seed",
                "bp-approved-sessions",
                "bp-approved-storage",
            ),
            mode="phase2",
            not_before=datetime(2026, 8, 14, 15, 0, tzinfo=UTC),
            synthetic_manifest_sha256=MANIFEST,
            synthetic_dataset_version_id=VERSION,
            **_phase_app_authority(),
            **_phase2_authority(),
            runner=_runner(outputs, []),
        )
