"""Read-only, recovery-first validation for one exact Azure Demo target."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_SCRIPT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_PROJECT_ROOT))

from scripts.verify_hosted_health import (  # noqa: E402
    HostedHealthInvalid,
    verify_hosted_health,
)

UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]{1,62}[a-z0-9]")
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
ACR_PULL_ROLE_ID = "7f951dda-4ed3-4680-a7ca-43fe172d538d"


class AzurePreflightFailed(RuntimeError):
    """The exact read-only recovery/configuration authority was not proved."""


def _same_resource_id(actual: object, expected: str) -> bool:
    return isinstance(actual, str) and actual.casefold() == expected.casefold()


def _same_region(actual: object, expected: str) -> bool:
    return (
        isinstance(actual, str)
        and re.sub(r"[^a-z0-9]", "", actual.casefold())
        == re.sub(r"[^a-z0-9]", "", expected.casefold())
    )


def _az_json(
    arguments: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> Any:
    try:
        completed = runner(
            ["az", *arguments, "--only-show-errors", "--output", "json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise AzurePreflightFailed("azure_preflight_read_failed") from error
    if len(completed.stdout) > 1_000_000:
        raise AzurePreflightFailed("azure_preflight_response_invalid")
    try:
        return json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise AzurePreflightFailed("azure_preflight_response_invalid") from error


def _resource_list(
    *,
    subscription_id: str,
    resource_group: str,
    name: str,
    resource_type: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> list[dict[str, Any]]:
    payload = _az_json(
        (
            "resource",
            "list",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--name",
            name,
            "--resource-type",
            resource_type,
        ),
        runner=runner,
    )
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise AzurePreflightFailed("azure_preflight_response_invalid")
    return payload


def _strict_alias_value(
    payload: dict[str, Any],
    nested: dict[str, Any] | None,
    names: tuple[str, ...],
    *,
    error: str,
) -> Any:
    values = [
        source[name]
        for source in (payload, nested or {})
        for name in names
        if name in source
    ]
    if not values or any(value != values[0] for value in values[1:]):
        raise AzurePreflightFailed(error)
    return values[0]


def _require_acr_managed_identity_tokens(
    *,
    subscription_id: str,
    registry_name: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    authority = _az_json(
        (
            "acr",
            "config",
            "authentication-as-arm",
            "show",
            "--subscription",
            subscription_id,
            "--registry",
            registry_name,
        ),
        runner=runner,
    )
    if not isinstance(authority, dict) or authority.get("status") != "enabled":
        raise AzurePreflightFailed("azure_preflight_registry_identity_invalid")


def _require_registry_identity_authority(
    *,
    subscription_id: str,
    resource_group: str,
    region: str,
    registry_name: str,
    registry_identity: str,
    expected_client_id: str,
    expected_principal_id: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    identity_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
        f"{registry_identity}"
    )
    registry_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.ContainerRegistry/registries/{registry_name}"
    )
    identity = _az_json(
        (
            "identity",
            "show",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--name",
            registry_identity,
        ),
        runner=runner,
    )
    principal_id = identity.get("principalId") if isinstance(identity, dict) else None
    if (
        not isinstance(identity, dict)
        or not _same_resource_id(identity.get("id"), identity_id)
        or identity.get("name") != registry_identity
        or not _same_region(identity.get("location"), region)
        or identity.get("clientId") != expected_client_id
        or principal_id != expected_principal_id
    ):
        raise AzurePreflightFailed("azure_preflight_registry_identity_invalid")
    assignments = _az_json(
        (
            "role",
            "assignment",
            "list",
            "--subscription",
            subscription_id,
            "--scope",
            registry_id,
            "--assignee-object-id",
            str(principal_id),
            "--role",
            "AcrPull",
        ),
        runner=runner,
    )
    if (
        not isinstance(assignments, list)
        or len(assignments) != 1
        or not isinstance(assignments[0], dict)
        or assignments[0].get("principalId") != principal_id
        or not _same_resource_id(assignments[0].get("scope"), registry_id)
        or not _same_resource_id(
            assignments[0].get("roleDefinitionId"),
            (
                f"/subscriptions/{subscription_id}/providers/"
                f"Microsoft.Authorization/roleDefinitions/{ACR_PULL_ROLE_ID}"
            ),
        )
    ):
        raise AzurePreflightFailed("azure_preflight_registry_identity_invalid")


def _app_registry_identity_authority(
    *,
    current_app: dict[str, Any],
    configuration: dict[str, Any],
    registry_identity_id: str,
    registry_name: str,
) -> tuple[str, str]:
    identity = current_app.get("identity")
    if (
        not isinstance(identity, dict)
        or set(identity)
        - {"principalId", "tenantId", "type", "userAssignedIdentities"}
        or identity.get("type") != "UserAssigned"
        or identity.get("principalId") is not None
        or identity.get("tenantId") is not None
    ):
        raise AzurePreflightFailed("azure_preflight_registry_identity_invalid")
    assigned = identity.get("userAssignedIdentities")
    if not isinstance(assigned, dict) or len(assigned) != 1:
        raise AzurePreflightFailed("azure_preflight_registry_identity_invalid")
    assigned_identity_id, metadata = next(iter(assigned.items()))
    if (
        not _same_resource_id(assigned_identity_id, registry_identity_id)
        or not isinstance(metadata, dict)
        or set(metadata) != {"clientId", "principalId"}
        or UUID_PATTERN.fullmatch(str(metadata.get("clientId"))) is None
        or UUID_PATTERN.fullmatch(str(metadata.get("principalId"))) is None
    ):
        raise AzurePreflightFailed("azure_preflight_registry_identity_invalid")
    registries = configuration.get("registries")
    if not isinstance(registries, list) or len(registries) != 1:
        raise AzurePreflightFailed("azure_preflight_registry_identity_invalid")
    registry = registries[0]
    if (
        not isinstance(registry, dict)
        or set(registry)
        - {"identity", "passwordSecretRef", "server", "username"}
        or not _same_resource_id(registry.get("identity"), registry_identity_id)
        or registry.get("server") != f"{registry_name}.azurecr.io"
        or registry.get("passwordSecretRef") not in {None, ""}
        or registry.get("username") not in {None, ""}
    ):
        raise AzurePreflightFailed("azure_preflight_registry_identity_invalid")
    return str(metadata["clientId"]), str(metadata["principalId"])


def _validate_arguments(**values: object) -> None:
    if (
        UUID_PATTERN.fullmatch(str(values["subscription_id"])) is None
        or any(
            NAME_PATTERN.fullmatch(str(values[name])) is None
            for name in (
                "resource_group",
                "app_name",
                "application_insights",
                "container_environment",
                "log_workspace",
                "postgres_server",
                "registry_name",
                "registry_identity",
                "storage_account",
                "virtual_network",
            )
        )
        or len(set(values["job_names"])) != 4
        or any(
            NAME_PATTERN.fullmatch(str(name)) is None
            for name in values["job_names"]
        )
        or values["postgres_dns_zone"] != "private.postgres.database.azure.com"
        or not re.fullmatch(r"[a-z][a-z0-9]{2,31}", str(values["region"]))
        or not re.fullmatch(
            r"[a-z0-9][a-z0-9._/-]{1,127}",
            str(values["image_repository"]),
        )
        or values["target_mode"] not in {"fresh", "prepared", "update"}
        or values["current_image_state"] not in {"pending-publication", "present"}
        or DIGEST_PATTERN.fullmatch(str(values["image_digest"])) is None
        or DIGEST_PATTERN.fullmatch(str(values["rollback_image_digest"])) is None
        or (
            values["target_mode"] == "update"
            and DIGEST_PATTERN.fullmatch(
                str(values["observed_current_image_digest"])
            )
            is None
        )
        or (
            values["target_mode"] != "update"
            and values["observed_current_image_digest"] is not None
        )
        or type(values["postgres_backup_days"]) is not int
        or not 7 <= int(values["postgres_backup_days"]) <= 35
        or values["blob_retention_days"] != 7
        or values["application_sku"] != "Consumption"
        or values["application_cpu"] != "0.5"
        or values["application_memory"] != "1Gi"
        or values["application_min_replicas"] != 1
        or values["application_max_replicas"] != 1
        or not isinstance(values["log_retention_days"], int)
        or not 30 <= values["log_retention_days"] <= 730
        or not isinstance(values["postgres_storage_gb"], int)
        or not 32 <= values["postgres_storage_gb"] <= 16_384
        or not re.fullmatch(r"[A-Za-z0-9_]{3,64}", str(values["postgres_sku"]))
        or values["postgres_tier"]
        not in {"Burstable", "GeneralPurpose", "MemoryOptimized"}
        or not re.fullmatch(r"1[4-9]", str(values["postgres_version"]))
        or not re.fullmatch(r"[A-Za-z0-9_]{3,64}", str(values["storage_sku"]))
        or (
            values["target_mode"] == "fresh"
            and values["public_url"] is not None
        )
        or (
            values["target_mode"] == "update"
            and not str(values["public_url"]).startswith(
                f"https://{values['app_name']}."
            )
        )
        or (
            values["target_mode"] == "prepared"
            and values["public_url"] is not None
            and not str(values["public_url"]).startswith(
                f"https://{values['app_name']}."
            )
        )
    ):
        raise AzurePreflightFailed("azure_preflight_authority_invalid")


def run_recovery_preflight(
    *,
    subscription_id: str,
    resource_group: str,
    region: str,
    target_mode: str,
    app_name: str,
    container_environment: str,
    application_insights: str,
    log_workspace: str,
    job_names: tuple[str, str, str, str],
    virtual_network: str,
    postgres_dns_zone: str,
    postgres_server: str,
    postgres_backup_days: int,
    postgres_sku: str,
    postgres_tier: str,
    postgres_storage_gb: int,
    postgres_version: str,
    storage_account: str,
    storage_sku: str,
    blob_retention_days: int,
    application_sku: str,
    application_cpu: str = "0.5",
    application_memory: str = "1Gi",
    application_min_replicas: int = 1,
    application_max_replicas: int = 1,
    log_retention_days: int,
    registry_name: str,
    registry_identity: str,
    image_repository: str,
    image_digest: str,
    rollback_image_digest: str,
    public_url: str | None,
    observed_current_image_digest: str | None = None,
    current_image_state: str = "present",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    health_verifier: Callable[[str], None] = verify_hosted_health,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Use only bounded read commands and reject every authority mismatch."""

    _validate_arguments(**locals())
    account = _az_json(
        ("account", "show", "--subscription", subscription_id),
        runner=runner,
    )
    group = _az_json(
        (
            "group",
            "show",
            "--subscription",
            subscription_id,
            "--name",
            resource_group,
        ),
        runner=runner,
    )
    if account.get("id") != subscription_id or not _same_region(
        group.get("location"), region
    ):
        raise AzurePreflightFailed("azure_preflight_target_invalid")

    declared_resources = (
        (app_name, "Microsoft.App/containerApps"),
        (container_environment, "Microsoft.App/managedEnvironments"),
        *((name, "Microsoft.App/jobs") for name in job_names),
        (log_workspace, "Microsoft.OperationalInsights/workspaces"),
        (application_insights, "Microsoft.Insights/components"),
        (postgres_server, "Microsoft.DBforPostgreSQL/flexibleServers"),
        (storage_account, "Microsoft.Storage/storageAccounts"),
        (virtual_network, "Microsoft.Network/virtualNetworks"),
        (postgres_dns_zone, "Microsoft.Network/privateDnsZones"),
    )
    existing = [
        _resource_list(
            subscription_id=subscription_id,
            resource_group=resource_group,
            name=name,
            resource_type=resource_type,
            runner=runner,
        )
        for name, resource_type in declared_resources
    ]
    if target_mode == "fresh" and any(existing):
        raise AzurePreflightFailed("azure_preflight_target_not_fresh")
    if target_mode in {"prepared", "update"} and any(
        len(rows) != 1 or rows[0].get("name") != name
        for rows, (name, _resource_type) in zip(existing, declared_resources, strict=True)
    ):
        raise AzurePreflightFailed("azure_preflight_target_missing")

    digests = (
        ()
        if current_image_state == "pending-publication"
        else (image_digest, rollback_image_digest)
    )
    for digest in digests:
        metadata = _az_json(
            (
                "acr",
                "manifest",
                "show-metadata",
                "--subscription",
                subscription_id,
                "--registry",
                registry_name,
                "--name",
                f"{image_repository}@{digest}",
            ),
            runner=runner,
        )
        if metadata.get("digest") != digest:
            raise AzurePreflightFailed("azure_preflight_digest_unavailable")

    if target_mode == "fresh":
        _require_acr_managed_identity_tokens(
            subscription_id=subscription_id,
            registry_name=registry_name,
            runner=runner,
        )
        if _resource_list(
            subscription_id=subscription_id,
            resource_group=resource_group,
            name=registry_identity,
            resource_type="Microsoft.ManagedIdentity/userAssignedIdentities",
            runner=runner,
        ):
            raise AzurePreflightFailed("azure_preflight_target_not_fresh")
        return

    current_app = _az_json(
        (
            "containerapp",
            "show",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--name",
            app_name,
        ),
        runner=runner,
    )
    containers = current_app.get("properties", {}).get("template", {}).get("containers", [])
    app_properties = current_app.get("properties", {})
    configuration = app_properties.get("configuration", {})
    ingress = configuration.get("ingress", {})
    traffic = ingress.get("traffic", [])
    public_hostname = (
        urlsplit(public_url).hostname if isinstance(public_url, str) else None
    )
    actual_fqdn = ingress.get("fqdn")
    expected_current_digest = (
        image_digest if target_mode == "prepared" else observed_current_image_digest
    )
    expected_prior_image = (
        f"{registry_name}.azurecr.io/{image_repository}@{expected_current_digest}"
    )
    environment_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.App/managedEnvironments/{container_environment}"
    )
    registry_identity_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
        f"{registry_identity}"
    )
    vnet_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Network/virtualNetworks/{virtual_network}"
    )
    postgres_subnet_id = f"{vnet_id}/subnets/postgres"
    app_subnet_id = f"{vnet_id}/subnets/container-apps"
    private_dns_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Network/privateDnsZones/{postgres_dns_zone}"
    )
    template = app_properties.get("template", {})
    scale = template.get("scale", {})
    expected_min_replicas = (
        0 if target_mode == "prepared" else application_min_replicas
    )
    container_resources = containers[0].get("resources", {}) if len(containers) == 1 else {}
    registry_client_id, registry_principal_id = _app_registry_identity_authority(
        current_app=current_app,
        configuration=configuration,
        registry_identity_id=registry_identity_id,
        registry_name=registry_name,
    )
    if (
        current_app.get("name") != app_name
        or not _same_resource_id(
            current_app.get("id"),
            (
                f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
                f"/providers/Microsoft.App/containerApps/{app_name}"
            ),
        )
        or not _same_region(current_app.get("location"), region)
        or app_properties.get("provisioningState") != "Succeeded"
        or not _same_resource_id(app_properties.get("environmentId"), environment_id)
        or app_properties.get("workloadProfileName") not in {None, application_sku}
        or configuration.get("activeRevisionsMode") != "Single"
        or app_properties.get("latestRevisionName")
        != app_properties.get("latestReadyRevisionName")
        or not isinstance(traffic, list)
        or len(traffic) != 1
        or not isinstance(traffic[0], dict)
        or traffic[0].get("latestRevision") is not True
        or traffic[0].get("weight") != 100
        or len(containers) != 1
        or containers[0].get("image") != expected_prior_image
        or str(container_resources.get("cpu")) != application_cpu
        or container_resources.get("memory") != application_memory
        or scale.get("minReplicas") != expected_min_replicas
        or scale.get("maxReplicas") != application_max_replicas
        or (
            public_hostname is not None
            and actual_fqdn != public_hostname
        )
        or (
            public_hostname is None
            and (
                not isinstance(actual_fqdn, str)
                or not actual_fqdn.startswith(f"{app_name}.")
                or not actual_fqdn.endswith(".azurecontainerapps.io")
            )
        )
        or ingress.get("external") is not (target_mode == "update")
    ):
        raise AzurePreflightFailed("azure_preflight_current_release_invalid")

    postgres = _az_json(
        (
            "postgres",
            "flexible-server",
            "show",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--name",
            postgres_server,
        ),
        runner=runner,
    )
    nested_postgres = postgres.get("properties")
    if nested_postgres is not None and not isinstance(nested_postgres, dict):
        raise AzurePreflightFailed("azure_preflight_postgres_invalid")
    properties = nested_postgres or postgres
    if nested_postgres is not None and any(
        name in postgres and postgres[name] != nested_postgres.get(name)
        for name in ("backup", "network", "state", "storage", "version")
    ):
        raise AzurePreflightFailed("azure_preflight_postgres_invalid")
    postgres_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.DBforPostgreSQL/flexibleServers/{postgres_server}"
    )
    postgres_storage = properties.get("storage")
    if not isinstance(postgres_storage, dict):
        raise AzurePreflightFailed("azure_preflight_postgres_invalid")
    storage_size_gb = _strict_alias_value(
        postgres_storage,
        None,
        ("storageSizeGB", "storageSizeGb"),
        error="azure_preflight_postgres_invalid",
    )
    if (
        postgres.get("name") != postgres_server
        or not _same_resource_id(postgres.get("id"), postgres_id)
        or not _same_region(postgres.get("location"), region)
        or postgres.get("sku")
        != {"name": postgres_sku, "tier": postgres_tier}
        or properties.get("state") != "Ready"
        or properties.get("version") != postgres_version
        or storage_size_gb != postgres_storage_gb
        or properties.get("network", {}).get("publicNetworkAccess") != "Disabled"
        or not _same_resource_id(
            properties.get("network", {}).get("delegatedSubnetResourceId"),
            postgres_subnet_id,
        )
        or not _same_resource_id(
            properties.get("network", {}).get("privateDnsZoneArmResourceId"),
            private_dns_id,
        )
        or properties.get("backup", {}).get("backupRetentionDays")
        != postgres_backup_days
    ):
        raise AzurePreflightFailed("azure_preflight_postgres_invalid")
    backups = _az_json(
        (
            "postgres",
            "flexible-server",
            "backup",
            "list",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--server-name",
            postgres_server,
        ),
        runner=runner,
    )
    now = clock()
    if now.tzinfo is None:
        raise AzurePreflightFailed("azure_preflight_backup_invalid")
    try:
        earliest = datetime.fromisoformat(
            str(properties["backup"]["earliestRestoreDate"]).replace("Z", "+00:00")
        )
    except (KeyError, TypeError, ValueError) as error:
        raise AzurePreflightFailed("azure_preflight_backup_invalid") from error
    backup_prefix = f"{postgres_id}/backups/"
    completed: list[datetime] = []
    if not isinstance(backups, list) or not backups:
        raise AzurePreflightFailed("azure_preflight_backup_invalid")
    for backup in backups:
        if not isinstance(backup, dict):
            raise AzurePreflightFailed("azure_preflight_backup_invalid")
        backup_properties = backup.get("properties", backup)
        try:
            completed_at = datetime.fromisoformat(
                str(backup_properties["completedTime"]).replace("Z", "+00:00")
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AzurePreflightFailed("azure_preflight_backup_invalid") from error
        if (
            not str(backup.get("id", "")).casefold().startswith(
                backup_prefix.casefold()
            )
            or backup_properties.get("backupType")
            not in {"Full", "Customer On-Demand"}
            or backup_properties.get("source")
            not in {"Automatic", "Customer Initiated"}
            or completed_at.tzinfo is None
            or completed_at < earliest
            or completed_at > now
        ):
            raise AzurePreflightFailed("azure_preflight_backup_invalid")
        completed.append(completed_at)
    if (
        earliest > now
        or earliest < now - timedelta(days=postgres_backup_days, hours=24)
        or max(completed) < now - timedelta(hours=48)
    ):
        raise AzurePreflightFailed("azure_preflight_backup_invalid")

    storage = _az_json(
        (
            "storage",
            "account",
            "show",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--name",
            storage_account,
        ),
        runner=runner,
    )
    storage_properties = storage.get("properties", storage)
    if not isinstance(storage_properties, dict):
        raise AzurePreflightFailed("azure_preflight_storage_invalid")
    https_only = _strict_alias_value(
        storage_properties,
        None,
        ("supportsHttpsTrafficOnly", "enableHttpsTrafficOnly"),
        error="azure_preflight_storage_invalid",
    )
    storage_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Storage/storageAccounts/{storage_account}"
    )
    if (
        storage.get("name") != storage_account
        or not _same_resource_id(storage.get("id"), storage_id)
        or not _same_region(storage.get("location"), region)
        or storage.get("sku", {}).get("name") != storage_sku
        or storage_properties.get("allowBlobPublicAccess") is not False
        or https_only is not True
        or storage_properties.get("minimumTlsVersion") != "TLS1_2"
    ):
        raise AzurePreflightFailed("azure_preflight_storage_invalid")
    blob = _az_json(
        (
            "storage",
            "account",
            "blob-service-properties",
            "show",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--account-name",
            storage_account,
        ),
        runner=runner,
    )
    deletion = blob.get("deleteRetentionPolicy", {})
    container_deletion = blob.get("containerDeleteRetentionPolicy", {})
    if any(
        policy.get("enabled") is not True
        or policy.get("days") != blob_retention_days
        for policy in (deletion, container_deletion)
    ):
        raise AzurePreflightFailed("azure_preflight_blob_recovery_invalid")
    monitoring = _az_json(
        (
            "monitor",
            "log-analytics",
            "workspace",
            "show",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--workspace-name",
            log_workspace,
        ),
        runner=runner,
    )
    if (
        not _same_resource_id(
            monitoring.get("id"),
            (
                f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
                f"/providers/Microsoft.OperationalInsights/workspaces/{log_workspace}"
            ),
        )
        or monitoring.get("name") != log_workspace
        or not _same_region(monitoring.get("location"), region)
        or monitoring.get("retentionInDays") != log_retention_days
        or monitoring.get("sku", {}).get("name") != "PerGB2018"
    ):
        raise AzurePreflightFailed("azure_preflight_monitoring_invalid")
    environment = _az_json(
        (
            "containerapp",
            "env",
            "show",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--name",
            container_environment,
        ),
        runner=runner,
    )
    environment_properties = environment.get("properties", {})
    if (
        not _same_resource_id(environment.get("id"), environment_id)
        or environment.get("name") != container_environment
        or not _same_region(environment.get("location"), region)
        or environment_properties.get("provisioningState") != "Succeeded"
        or not _same_resource_id(
            environment_properties.get("vnetConfiguration", {}).get(
                "infrastructureSubnetId"
            ),
            app_subnet_id,
        )
        or environment_properties.get("appLogsConfiguration", {}).get(
            "destination"
        )
        != "log-analytics"
    ):
        raise AzurePreflightFailed("azure_preflight_environment_invalid")
    insights = _az_json(
        (
            "resource",
            "show",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--resource-type",
            "Microsoft.Insights/components",
            "--name",
            application_insights,
            "--api-version",
            "2020-02-02",
        ),
        runner=runner,
    )
    monitoring_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.OperationalInsights/workspaces/{log_workspace}"
    )
    insights_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Insights/components/{application_insights}"
    )
    nested_insights = insights.get("properties")
    if nested_insights is not None and not isinstance(nested_insights, dict):
        raise AzurePreflightFailed("azure_preflight_application_insights_invalid")
    insights_error = "azure_preflight_application_insights_invalid"
    try:
        application_type = _strict_alias_value(
            insights,
            nested_insights,
            ("Application_Type", "applicationType"),
            error=insights_error,
        )
        disable_local_auth = _strict_alias_value(
            insights,
            nested_insights,
            ("DisableLocalAuth", "disableLocalAuth"),
            error=insights_error,
        )
        workspace_resource_id = _strict_alias_value(
            insights,
            nested_insights,
            ("WorkspaceResourceId", "workspaceResourceId"),
            error=insights_error,
        )
    except AzurePreflightFailed:
        raise
    if (
        not _same_resource_id(insights.get("id"), insights_id)
        or insights.get("name") != application_insights
        or not _same_region(insights.get("location"), region)
        or insights.get("kind") != "web"
        or application_type != "web"
        or disable_local_auth is not True
        or not _same_resource_id(workspace_resource_id, monitoring_id)
    ):
        raise AzurePreflightFailed("azure_preflight_application_insights_invalid")
    _require_acr_managed_identity_tokens(
        subscription_id=subscription_id,
        registry_name=registry_name,
        runner=runner,
    )
    _require_registry_identity_authority(
        subscription_id=subscription_id,
        resource_group=resource_group,
        region=region,
        registry_name=registry_name,
        registry_identity=registry_identity,
        expected_client_id=registry_client_id,
        expected_principal_id=registry_principal_id,
        runner=runner,
    )
    if target_mode == "update":
        try:
            health_verifier(str(public_url))
        except HostedHealthInvalid as error:
            raise AzurePreflightFailed("azure_preflight_health_invalid") from error


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument(
        "--target-mode",
        choices=("fresh", "prepared", "update"),
        required=True,
    )
    parser.add_argument("--app", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--application-insights", required=True)
    parser.add_argument("--log-workspace", required=True)
    parser.add_argument("--prepare-job", required=True)
    parser.add_argument("--seed-job", required=True)
    parser.add_argument("--session-job", required=True)
    parser.add_argument("--storage-job", required=True)
    parser.add_argument("--virtual-network", required=True)
    parser.add_argument("--postgres-dns-zone", required=True)
    parser.add_argument("--postgres-server", required=True)
    parser.add_argument("--postgres-backup-days", required=True, type=int)
    parser.add_argument("--postgres-sku", required=True)
    parser.add_argument("--postgres-tier", required=True)
    parser.add_argument("--postgres-storage-gb", required=True, type=int)
    parser.add_argument("--postgres-version", required=True)
    parser.add_argument("--storage-account", required=True)
    parser.add_argument("--storage-sku", required=True)
    parser.add_argument("--blob-retention-days", required=True, type=int)
    parser.add_argument("--application-sku", required=True)
    parser.add_argument("--application-cpu", required=True)
    parser.add_argument("--application-memory", required=True)
    parser.add_argument("--application-min-replicas", required=True, type=int)
    parser.add_argument("--application-max-replicas", required=True, type=int)
    parser.add_argument("--log-retention-days", required=True, type=int)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--registry-identity", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--rollback-image-digest", required=True)
    parser.add_argument("--observed-current-image-digest")
    parser.add_argument(
        "--current-image-state",
        choices=("pending-publication", "present"),
        required=True,
    )
    parser.add_argument("--public-url")
    options = parser.parse_args(arguments)
    try:
        run_recovery_preflight(
            subscription_id=options.subscription,
            resource_group=options.resource_group,
            region=options.region,
            target_mode=options.target_mode,
            app_name=options.app,
            container_environment=options.environment,
            application_insights=options.application_insights,
            log_workspace=options.log_workspace,
            job_names=(
                options.prepare_job,
                options.seed_job,
                options.session_job,
                options.storage_job,
            ),
            virtual_network=options.virtual_network,
            postgres_dns_zone=options.postgres_dns_zone,
            postgres_server=options.postgres_server,
            postgres_backup_days=options.postgres_backup_days,
            postgres_sku=options.postgres_sku,
            postgres_tier=options.postgres_tier,
            postgres_storage_gb=options.postgres_storage_gb,
            postgres_version=options.postgres_version,
            storage_account=options.storage_account,
            storage_sku=options.storage_sku,
            blob_retention_days=options.blob_retention_days,
            application_sku=options.application_sku,
            application_cpu=options.application_cpu,
            application_memory=options.application_memory,
            application_min_replicas=options.application_min_replicas,
            application_max_replicas=options.application_max_replicas,
            log_retention_days=options.log_retention_days,
            registry_name=options.registry,
            registry_identity=options.registry_identity,
            image_repository=options.repository,
            image_digest=options.image_digest,
            rollback_image_digest=options.rollback_image_digest,
            public_url=options.public_url,
            observed_current_image_digest=options.observed_current_image_digest,
            current_image_state=options.current_image_state,
        )
    except AzurePreflightFailed:
        print("azure_preflight=failed")
        return 1
    print("azure_preflight=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
