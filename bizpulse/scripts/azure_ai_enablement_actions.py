"""Package-bound Azure and provider actions for BizPulse AI enablement."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal, ROUND_UP
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from azure.identity import AzureCliCredential
import requests

from scripts.azure_arm_lro import (
    ARMOperationInvalid,
    ARMRequester,
    ARMResponse,
    MAX_ARM_OPERATION_SECONDS,
    wait_for_arm_patch,
)
from scripts.azure_ai_reconciliation import (
    AzureAIReconciliationInvalid,
    PendingAITransition,
    reconcile_ai_transition,
)
from scripts.azure_ai_revision import (
    AzureAIRevisionInvalid,
    build_ai_revision_patch,
    canonicalize_ai_revision_patch_target,
    canonicalize_azure_template_readback,
)
from scripts.publish_registry_image import publish_registry_image_discover_digest


_OFFICIAL_PRICING = {
    "model": "gpt-5.4-nano-2026-03-17",
    "official_source": "https://developers.openai.com/api/docs/models/gpt-5.4-nano",
    "input_usd_per_million_tokens": "0.20",
    "output_usd_per_million_tokens": "1.25",
    "regional_processing_uplift_percent": "10",
    "execution_uses_regional_processing": False,
}
_AI_BINDING_NAMES = frozenset(
    {
        "BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL",
        "BIZPULSE_OPENAI_KEY_VAULT_URL",
        "BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME",
        "BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
    }
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
_BROWSER_OPERATOR_PASSWORD_ENVIRONMENT = "BIZPULSE_BROWSER_OPERATOR_PASSWORD"
_KEY_VAULT_SECRETS_USER_ROLE_DEFINITION_ID = (
    "4633458b-17de-408a-b874-0445c86b69e6"
)
_KEY_VAULT_SECRETS_OFFICER_ROLE_DEFINITION_ID = (
    "b86a8fe4-44ce-4948-aee5-eccb2c155cd7"
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_BICEP_GUID_NAMESPACE = UUID("11fb06fb-712d-4ddd-98c7-e71bbd588830")
_AI_RESOURCE_TAGS = {
    "application": "newcaostone",
    "component": "ai-enablement",
    "data_classification": "credential",
    "environment": "demo",
    "production_ready": "false",
}


class AzureAIEnablementActionInvalid(RuntimeError):
    """A package-bound Azure/provider action was unsafe or unconfirmed."""

    def __init__(
        self,
        code: str,
        *,
        reconciliation_evidence: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(code)
        self.reconciliation_evidence = deepcopy(
            dict(reconciliation_evidence or {})
        )


def _invalid(
    code: str,
    *,
    reconciliation_evidence: Mapping[str, object] | None = None,
) -> AzureAIEnablementActionInvalid:
    return AzureAIEnablementActionInvalid(
        code,
        reconciliation_evidence=reconciliation_evidence,
    )


def _safe_process_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Return the only ambient settings child processes may inherit."""

    return {
        name: value
        for name in _PROCESS_ENVIRONMENT_NAMES
        if isinstance((value := source.get(name)), str)
    }


def _wipe(buffer: bytearray | None) -> None:
    if buffer is not None:
        for index in range(len(buffer)):
            buffer[index] = 0


def _run_json(
    command: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    environment: Mapping[str, str],
    timeout: int = 30,
) -> object:
    try:
        completed = runner(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            env=_safe_process_environment(environment),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise _invalid("ai_enablement_azure_read_failed") from error
    if (
        completed.returncode != 0
        or not isinstance(completed.stdout, str)
        or len(completed.stdout) > 1_000_000
    ):
        raise _invalid("ai_enablement_azure_read_failed")
    try:
        return json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise _invalid("ai_enablement_azure_read_failed") from error


def _resource_absent(
    command: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    environment: Mapping[str, str],
) -> bool:
    try:
        completed = runner(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
            env=_safe_process_environment(environment),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise _invalid("ai_enablement_azure_read_failed") from error
    if completed.returncode == 0:
        return False
    stderr = completed.stderr if isinstance(completed.stderr, str) else ""
    if (
        completed.returncode != 3
        or completed.stdout not in {"", None}
        or "resourcenotfound" not in stderr.casefold()
        or "not found" not in stderr.casefold()
    ):
        raise _invalid("ai_enablement_azure_read_failed")
    return True


def _resource_id(
    target: Mapping[str, object],
    provider: str,
    resource_type: str,
    name: str,
) -> str:
    return (
        f"/subscriptions/{target['subscription_id']}/resourceGroups/"
        f"{target['resource_group']}/providers/{provider}/{resource_type}/{name}"
    )


def _bicep_guid(*values: str) -> str:
    return str(uuid5(_BICEP_GUID_NAMESPACE, "-".join(values)))


def _normalized_role_assignment(
    *,
    assignment_id: str,
    principal_id: str,
    role_definition_id: str,
    scope: str,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            {
                "id": assignment_id.casefold(),
                "principalId": principal_id.casefold(),
                "principalType": "ServicePrincipal",
                "roleDefinitionId": role_definition_id.casefold(),
                "scope": scope.casefold(),
            }.items()
        )
    )


def _complete_role_assignment_set(
    *assignment_batches: object,
) -> frozenset[tuple[tuple[str, str], ...]]:
    expected_keys = {
        "id",
        "principalId",
        "principalType",
        "roleDefinitionId",
        "scope",
    }
    normalized_by_id: dict[str, tuple[tuple[str, str], ...]] = {}
    for assignments in assignment_batches:
        if not isinstance(assignments, list):
            raise _invalid("ai_enablement_role_assignment_drift")
        for assignment in assignments:
            if (
                not isinstance(assignment, Mapping)
                or set(assignment) != expected_keys
                or not all(
                    isinstance(assignment[key], str) for key in expected_keys
                )
            ):
                raise _invalid("ai_enablement_role_assignment_drift")
            normalized = _normalized_role_assignment(
                assignment_id=str(assignment["id"]),
                principal_id=str(assignment["principalId"]),
                role_definition_id=str(assignment["roleDefinitionId"]),
                scope=str(assignment["scope"]),
            )
            assignment_id = str(assignment["id"]).casefold()
            previous = normalized_by_id.get(assignment_id)
            if previous is not None and previous != normalized:
                raise _invalid("ai_enablement_role_assignment_drift")
            normalized_by_id[assignment_id] = normalized
    return frozenset(normalized_by_id.values())


def _read_complete_role_assignment_set(
    target: Mapping[str, object],
    *,
    principal_id: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    environment: Mapping[str, str],
) -> frozenset[tuple[tuple[str, str], ...]]:
    subscription = str(target["subscription_id"])
    projection = (
        "[].{id:id,principalId:principalId,principalType:principalType,"
        "roleDefinitionId:roleDefinitionId,scope:scope}"
    )
    descendants = _run_json(
        (
            "az",
            "role",
            "assignment",
            "list",
            "--subscription",
            subscription,
            "--assignee-object-id",
            principal_id,
            "--all",
            "--query",
            projection,
            "--only-show-errors",
            "--output",
            "json",
        ),
        runner=runner,
        environment=environment,
    )
    ancestors = _run_json(
        (
            "az",
            "role",
            "assignment",
            "list",
            "--subscription",
            subscription,
            "--scope",
            f"/subscriptions/{subscription}",
            "--include-inherited",
            "--assignee-object-id",
            principal_id,
            "--query",
            projection,
            "--only-show-errors",
            "--output",
            "json",
        ),
        runner=runner,
        environment=environment,
    )
    return _complete_role_assignment_set(descendants, ancestors)


def _expected_role_assignment(
    target: Mapping[str, object],
    *,
    principal_id: str,
    phase: str,
) -> tuple[tuple[str, str], ...]:
    subscription = str(target["subscription_id"])
    vault_id = _resource_id(
        target,
        "Microsoft.KeyVault",
        "vaults",
        str(target["vault_name"]),
    )
    identity_id = _resource_id(
        target,
        "Microsoft.ManagedIdentity",
        "userAssignedIdentities",
        str(target["identity_name"]),
    )
    if phase == "legacy_only":
        scope = vault_id
        role_definition_id = (
            f"/subscriptions/{subscription}/providers/"
            "Microsoft.Authorization/roleDefinitions/"
            f"{_KEY_VAULT_SECRETS_USER_ROLE_DEFINITION_ID}"
        )
        assignment_name = _bicep_guid(
            vault_id,
            identity_id,
            role_definition_id,
        )
    elif phase == "officer_only":
        scope = f"{vault_id}/secrets/openai-api-key"
        role_definition_id = (
            f"/subscriptions/{subscription}/providers/"
            "Microsoft.Authorization/roleDefinitions/"
            f"{_KEY_VAULT_SECRETS_OFFICER_ROLE_DEFINITION_ID}"
        )
        assignment_name = _bicep_guid(
            scope,
            identity_id,
            "admin-ai-secret-officer",
        )
    else:
        raise _invalid("ai_enablement_role_assignment_phase_invalid")
    assignment_id = (
        f"{scope}/providers/Microsoft.Authorization/roleAssignments/"
        f"{assignment_name}"
    )
    return _normalized_role_assignment(
        assignment_id=assignment_id,
        principal_id=principal_id,
        role_definition_id=role_definition_id,
        scope=scope,
    )


def _location(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(character for character in value.casefold() if character.isalnum())


def _safe_projection(
    app: object,
    *,
    target: Mapping[str, object],
    rollback_identity_state: str,
) -> dict[str, object]:
    try:
        identity = app["identity"]
        assigned = identity["userAssignedIdentities"]
        template = app["properties"]["template"]
    except (KeyError, TypeError) as error:
        raise _invalid("ai_enablement_azure_authority_drift") from error
    registry_identity_id = _resource_id(
        target,
        "Microsoft.ManagedIdentity",
        "userAssignedIdentities",
        str(target["existing_registry_identity_name"]),
    )
    ai_identity_id = _resource_id(
        target,
        "Microsoft.ManagedIdentity",
        "userAssignedIdentities",
        str(target["identity_name"]),
    )
    if rollback_identity_state == "registry_plus_ai":
        expected_identity_ids = {
            registry_identity_id.casefold(),
            ai_identity_id.casefold(),
        }
    elif rollback_identity_state == "registry_only":
        expected_identity_ids = {registry_identity_id.casefold()}
    else:
        raise _invalid("ai_enablement_azure_authority_drift")
    if (
        not isinstance(identity, Mapping)
        or identity.get("type") != "UserAssigned"
        or not isinstance(assigned, Mapping)
        or {str(item).casefold() for item in assigned}
        != expected_identity_ids
        or not isinstance(template, Mapping)
    ):
        raise _invalid("ai_enablement_azure_authority_drift")
    projection = {
        "location": app.get("location"),
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {
                str(identity_id): {} for identity_id in assigned
            },
        },
        "properties": {"template": deepcopy(template)},
    }
    try:
        build_ai_revision_patch(
            projection,
            enabled=False,
            candidate_image=str(target["rollback_image"]),
            revision_suffix=str(template["revisionSuffix"]),
            ai_identity_resource_id=ai_identity_id,
        )
    except (AzureAIRevisionInvalid, KeyError, TypeError) as error:
        raise _invalid("ai_enablement_azure_authority_drift") from error
    return projection


def read_sanitized_azure_authority(
    package: Mapping[str, object],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    safe_observer: Callable[[Mapping[str, object]], None] | None = None,
    environment: Mapping[str, str] = os.environ,
) -> tuple[dict[str, object], dict[str, object]]:
    """Perform twelve non-secret reads and verify the rollback authority."""

    try:
        target = package["azure_target"]
        if not isinstance(target, Mapping):
            raise TypeError
        subscription = str(target["subscription_id"])
        resource_group = str(target["resource_group"])
        app_name = str(target["app_name"])
        rollback_revision = str(target["rollback_revision"])
        rollback_image = str(target["rollback_image"])
        registry_name = str(target["registry_name"])
        workspace_name = str(target["log_analytics_workspace_name"])
        vault_name = str(target["vault_name"])
        identity_name = str(target["identity_name"])
        gate = package["prepackage_gate"]
        if not isinstance(gate, Mapping):
            raise TypeError
        rollback_registry_tag = str(gate["rollback_registry_tag"])
        rollback_identity_state = str(gate["rollback_identity_state"])
        role_assignment_state = str(gate["role_assignment_state"])
        image_repository = str(package["candidate"]["image_repository"])
    except (KeyError, TypeError) as error:
        raise _invalid("ai_enablement_azure_authority_drift") from error
    child_environment = _safe_process_environment(environment)
    expected_vault_id = _resource_id(
        target,
        "Microsoft.KeyVault",
        "vaults",
        vault_name,
    )
    expected_identity_id = _resource_id(
        target,
        "Microsoft.ManagedIdentity",
        "userAssignedIdentities",
        identity_name,
    )

    account = _run_json(
        (
            "az",
            "account",
            "show",
            "--query",
            "{id:id,tenantId:tenantId}",
            "--only-show-errors",
            "--output",
            "json",
        ),
        runner=runner,
        environment=child_environment,
    )
    app = _run_json(
        (
            "az",
            "containerapp",
            "show",
            "--subscription",
            subscription,
            "--resource-group",
            resource_group,
            "--name",
            app_name,
            "--query",
            (
                "{id:id,name:name,location:location,identity:identity,properties:{"
                "latestRevisionName:properties.latestRevisionName,"
                "latestReadyRevisionName:properties.latestReadyRevisionName,"
                "provisioningState:properties.provisioningState,"
                "template:{revisionSuffix:properties.template.revisionSuffix,"
                "containers:properties.template.containers[].{name:name,"
                "image:image,env:env,probes:probes,resources:{cpu:resources.cpu,"
                "memory:resources.memory}},scale:{minReplicas:properties.template."
                "scale.minReplicas,maxReplicas:properties.template.scale."
                "maxReplicas}},configuration:{"
                "activeRevisionsMode:properties.configuration.activeRevisionsMode,"
                "ingress:properties.configuration.ingress,"
                "registries:properties.configuration.registries}}}"
            ),
            "--only-show-errors",
            "--output",
            "json",
        ),
        runner=runner,
        environment=child_environment,
    )
    revision = _run_json(
        (
            "az",
            "containerapp",
            "revision",
            "show",
            "--subscription",
            subscription,
            "--resource-group",
            resource_group,
            "--name",
            app_name,
            "--revision",
            rollback_revision,
            "--query",
            (
                "{name:name,properties:{active:properties.active,"
                "healthState:properties.healthState,"
                "provisioningState:properties.provisioningState,"
                "template:{containers:properties.template.containers[]."
                "{image:image}}}}"
            ),
            "--only-show-errors",
            "--output",
            "json",
        ),
        runner=runner,
        environment=child_environment,
    )
    replicas = _run_json(
        (
            "az",
            "containerapp",
            "replica",
            "list",
            "--subscription",
            subscription,
            "--resource-group",
            resource_group,
            "--name",
            app_name,
            "--revision",
            rollback_revision,
            "--query",
            "[].{name:name,runningState:properties.runningState}",
            "--only-show-errors",
            "--output",
            "json",
        ),
        runner=runner,
        environment=child_environment,
    )
    rollback_digest = rollback_image.rsplit("@", 1)[-1]
    manifest = _run_json(
        (
            "az",
            "acr",
            "manifest",
            "show-metadata",
            "--registry",
            registry_name,
            "--name",
            f"{image_repository}@{rollback_digest}",
            "--query",
            "{digest:digest,tags:tags}",
            "--only-show-errors",
            "--output",
            "json",
        ),
        runner=runner,
        environment=child_environment,
    )
    registry = _run_json(
        (
            "az",
            "acr",
            "show",
            "--subscription",
            subscription,
            "--resource-group",
            resource_group,
            "--name",
            registry_name,
            "--query",
            (
                "{id:id,name:name,location:location,loginServer:loginServer,"
                "adminUserEnabled:adminUserEnabled,"
                "publicNetworkAccess:publicNetworkAccess}"
            ),
            "--only-show-errors",
            "--output",
            "json",
        ),
        runner=runner,
        environment=child_environment,
    )
    workspace = _run_json(
        (
            "az",
            "monitor",
            "log-analytics",
            "workspace",
            "show",
            "--subscription",
            subscription,
            "--resource-group",
            resource_group,
            "--workspace-name",
            workspace_name,
            "--query",
            "{id:id,name:name,location:location,provisioningState:provisioningState}",
            "--only-show-errors",
            "--output",
            "json",
        ),
        runner=runner,
        environment=child_environment,
    )
    vault = _run_json(
        (
            "az",
            "keyvault",
            "show",
            "--subscription",
            subscription,
            "--resource-group",
            resource_group,
            "--name",
            vault_name,
            "--query",
            (
                "{id:id,name:name,location:location,tenantId:properties.tenantId,"
                "enableRbacAuthorization:properties.enableRbacAuthorization,"
                "enablePurgeProtection:properties.enablePurgeProtection,"
                "softDeleteRetentionInDays:properties.softDeleteRetentionInDays,"
                "publicNetworkAccess:properties.publicNetworkAccess,"
                "provisioningState:properties.provisioningState,tags:tags}"
            ),
            "--only-show-errors",
            "--output",
            "json",
        ),
        runner=runner,
        environment=child_environment,
    )
    identity = _run_json(
        (
            "az",
            "identity",
            "show",
            "--subscription",
            subscription,
            "--resource-group",
            resource_group,
            "--name",
            identity_name,
            "--query",
            (
                "{id:id,name:name,location:location,clientId:clientId,"
                "principalId:principalId,tenantId:tenantId,tags:tags}"
            ),
            "--only-show-errors",
            "--output",
            "json",
        ),
        runner=runner,
        environment=child_environment,
    )
    if (
        not isinstance(identity, Mapping)
        or not _canonical_uuid4(identity.get("principalId"))
    ):
        raise _invalid("ai_enablement_azure_authority_drift")
    principal_id = str(identity["principalId"])
    role_assignments = _read_complete_role_assignment_set(
        target,
        principal_id=principal_id,
        runner=runner,
        environment=child_environment,
    )
    diagnostics = _run_json(
        (
            "az",
            "monitor",
            "diagnostic-settings",
            "list",
            "--resource",
            expected_vault_id,
            "--query",
            (
                "[].{name:name,workspaceId:workspaceId,"
                "logs:logs[].{category:category,enabled:enabled},"
                "metrics:metrics[].{category:category,enabled:enabled}}"
            ),
            "--only-show-errors",
            "--output",
            "json",
        ),
        runner=runner,
        environment=child_environment,
    )

    expected_app_id = _resource_id(
        target,
        "Microsoft.App",
        "containerApps",
        app_name,
    )
    expected_registry_id = _resource_id(
        target,
        "Microsoft.ContainerRegistry",
        "registries",
        registry_name,
    )
    expected_workspace_id = _resource_id(
        target,
        "Microsoft.OperationalInsights",
        "workspaces",
        workspace_name,
    )
    try:
        role_assignment_matches = role_assignments == frozenset(
            {
                _expected_role_assignment(
                    target,
                    principal_id=principal_id,
                    phase=role_assignment_state,
                )
            }
        )
    except AzureAIEnablementActionInvalid:
        role_assignment_matches = False
    diagnostic_matches = False
    if (
        isinstance(diagnostics, list)
        and len(diagnostics) == 1
        and isinstance(diagnostics[0], Mapping)
    ):
        diagnostic = diagnostics[0]
        logs = diagnostic.get("logs")
        metrics = diagnostic.get("metrics")
        if isinstance(logs, list) and isinstance(metrics, list):
            log_projection = {
                (row.get("category"), row.get("enabled"))
                for row in logs
                if isinstance(row, Mapping)
            }
            metric_projection = {
                (row.get("category"), row.get("enabled"))
                for row in metrics
                if isinstance(row, Mapping)
            }
            diagnostic_matches = (
                len(log_projection) == len(logs)
                and len(metric_projection) == len(metrics)
                and diagnostic.get("name") == "ai-vault-audit"
                and str(diagnostic.get("workspaceId", "")).casefold()
                == expected_workspace_id.casefold()
                and log_projection
                == {
                    ("AuditEvent", True),
                    ("AzurePolicyEvaluationDetails", True),
                }
                and metric_projection == {("AllMetrics", True)}
            )
    try:
        properties = app["properties"]
        configuration = properties["configuration"]
        ingress = configuration["ingress"]
        traffic = ingress["traffic"]
        containers = properties["template"]["containers"]
        registries = configuration["registries"]
        revision_properties = revision["properties"]
        revision_containers = revision_properties["template"]["containers"]
    except (KeyError, TypeError) as error:
        raise _invalid("ai_enablement_azure_authority_drift") from error
    if (
        account != {"id": subscription, "tenantId": target["tenant_id"]}
        or not isinstance(app, Mapping)
        or str(app.get("id", "")).casefold() != expected_app_id.casefold()
        or app.get("name") != app_name
        or _location(app.get("location")) != _location(target["location"])
        or properties.get("latestRevisionName") != rollback_revision
        or properties.get("latestReadyRevisionName") != rollback_revision
        or properties.get("provisioningState") != "Succeeded"
        or configuration.get("activeRevisionsMode") != "Single"
        or ingress.get("external") is not True
        or not isinstance(ingress.get("fqdn"), str)
        or not ingress["fqdn"].startswith(f"{app_name}.")
        or not ingress["fqdn"].endswith(".azurecontainerapps.io")
        or traffic != [{"latestRevision": True, "weight": 100}]
        or not isinstance(containers, list)
        or len(containers) != 1
        or containers[0].get("image") != rollback_image
        or not isinstance(registries, list)
        or len(registries) != 1
        or not isinstance(registries[0], Mapping)
        or registries[0].get("server") != f"{registry_name}.azurecr.io"
        or str(registries[0].get("identity", "")).casefold()
        != _resource_id(
            target,
            "Microsoft.ManagedIdentity",
            "userAssignedIdentities",
            str(target["existing_registry_identity_name"]),
        ).casefold()
        or revision.get("name") != rollback_revision
        or revision_properties.get("active") is not True
        or revision_properties.get("healthState") != "Healthy"
        or revision_properties.get("provisioningState") != "Provisioned"
        or revision_containers != [{"image": rollback_image}]
        or not isinstance(replicas, list)
        or len(replicas) != 1
        or not isinstance(replicas[0], Mapping)
        or not isinstance(replicas[0].get("name"), str)
        or not replicas[0]["name"].startswith(f"{rollback_revision}-")
        or replicas[0].get("runningState") != "Running"
        or not isinstance(manifest, Mapping)
        or manifest.get("digest") != rollback_digest
        or not isinstance(manifest.get("tags"), list)
        or rollback_registry_tag not in manifest["tags"]
        or not isinstance(registry, Mapping)
        or str(registry.get("id", "")).casefold()
        != expected_registry_id.casefold()
        or registry.get("name") != registry_name
        or _location(registry.get("location"))
        != _location(app.get("location"))
        or registry.get("loginServer") != f"{registry_name}.azurecr.io"
        or registry.get("adminUserEnabled") is not False
        or registry.get("publicNetworkAccess") != "Enabled"
        or not isinstance(workspace, Mapping)
        or str(workspace.get("id", "")).casefold()
        != expected_workspace_id.casefold()
        or workspace.get("name") != workspace_name
        or _location(workspace.get("location"))
        != _location(app.get("location"))
        or workspace.get("provisioningState") != "Succeeded"
        or not isinstance(vault, Mapping)
        or str(vault.get("id", "")).casefold() != expected_vault_id.casefold()
        or vault.get("name") != vault_name
        or _location(vault.get("location")) != _location(target["location"])
        or vault.get("tenantId") != target["tenant_id"]
        or vault.get("enableRbacAuthorization") is not True
        or vault.get("enablePurgeProtection") is not True
        or vault.get("softDeleteRetentionInDays") != 90
        or vault.get("publicNetworkAccess") != "Enabled"
        or vault.get("provisioningState") != "Succeeded"
        or vault.get("tags") != _AI_RESOURCE_TAGS
        or str(identity.get("id", "")).casefold()
        != expected_identity_id.casefold()
        or identity.get("name") != identity_name
        or _location(identity.get("location")) != _location(target["location"])
        or not _canonical_uuid4(identity.get("clientId"))
        or identity.get("tenantId") != target["tenant_id"]
        or identity.get("tags") != _AI_RESOURCE_TAGS
        or not role_assignment_matches
        or not diagnostic_matches
    ):
        raise _invalid("ai_enablement_azure_authority_drift")
    environment = containers[0].get("env")
    if not isinstance(environment, list):
        raise _invalid("ai_enablement_azure_authority_drift")
    by_name = {
        row.get("name"): row
        for row in environment
        if isinstance(row, Mapping) and isinstance(row.get("name"), str)
    }
    limits = package["execution_contract"]["runtime_limits"]
    expected_values = {
        "BIZPULSE_AI_CHAT_ENABLED": "false",
        "BIZPULSE_AI_DAILY_ATTEMPT_LIMIT": str(limits["daily_attempt_limit"]),
        "BIZPULSE_AI_MONTHLY_TOKEN_LIMIT": str(limits["monthly_token_limit"]),
        "BIZPULSE_AI_MAX_CONCURRENT_TURNS": str(limits["max_concurrent_turns"]),
        "BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE": str(
            limits["session_attempt_limit_per_minute"]
        ),
        "BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE": str(
            limits["global_attempt_limit_per_minute"]
        ),
        "BIZPULSE_OPENAI_MODEL": str(package["provider_pricing"]["model"]),
        "BIZPULSE_OPENAI_REASONING_EFFORT": "low",
        "BIZPULSE_RUNTIME_ENVIRONMENT": "cloud",
    }
    if any(by_name.get(name) != {"name": name, "value": value} for name, value in expected_values.items()):
        raise _invalid("ai_enablement_azure_authority_drift")
    if set(by_name).intersection(_AI_BINDING_NAMES):
        raise _invalid("ai_enablement_azure_authority_drift")
    projection = _safe_projection(
        app,
        target=target,
        rollback_identity_state=rollback_identity_state,
    )
    hosted_url = f"https://{ingress['fqdn']}"
    parsed_url = urlsplit(hosted_url)
    if parsed_url.scheme != "https" or parsed_url.hostname != ingress["fqdn"]:
        raise _invalid("ai_enablement_azure_authority_drift")
    if safe_observer is not None:
        safe_observer(
            {
                "hosted_url": hosted_url,
                "immutable_configuration": {
                    "activeRevisionsMode": configuration["activeRevisionsMode"],
                    "ingress": {
                        "external": ingress["external"],
                        "fqdn": ingress["fqdn"],
                        "traffic": deepcopy(traffic),
                    },
                    "registries": [
                        {
                            "server": registries[0]["server"],
                            "identity": registries[0]["identity"],
                        }
                    ],
                },
            }
        )
    specification = package["execution_contract"]["states"][
        "readonly_revalidation"
    ]
    return (
        {
            "operations": deepcopy(specification["operations"]),
            "evidence": deepcopy(specification["expected_evidence"]),
            "outputs": {
                "rollback_revision": rollback_revision,
                "ai_enabled": False,
                "vault_state": "existing_exact",
                "identity_state": "existing_exact",
                "role_assignment_state": role_assignment_state,
                "diagnostic_setting_state": "existing_exact",
                "secret_values_read": 0,
            },
        },
        projection,
    )


def provider_price_preflight(package: Mapping[str, object]) -> dict[str, object]:
    """Validate bound official price evidence and compute the worst token cost."""

    try:
        pricing = package["provider_pricing"]
        expected = {**_OFFICIAL_PRICING, "checked_at": package["issued_at"]}
        limits = package["execution_contract"]["runtime_limits"]
        cap = package["cost_cap"]
        if pricing != expected or cap != {
            "currency": "USD",
            "maximum_paid_execution": "1.00",
            "maximum_paid_calls": 13,
            "stop_if_price_evidence_missing": True,
        }:
            raise TypeError
        token_limit = Decimal(str(limits["monthly_token_limit"]))
        output_rate = Decimal(str(pricing["output_usd_per_million_tokens"]))
        worst = token_limit * output_rate / Decimal("1000000")
        if pricing["execution_uses_regional_processing"]:
            uplift = Decimal(str(pricing["regional_processing_uplift_percent"]))
            worst *= Decimal("1") + (uplift / Decimal("100"))
        rounded = worst.quantize(Decimal("0.01"), rounding=ROUND_UP)
        if rounded > Decimal(str(cap["maximum_paid_execution"])):
            raise TypeError
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        raise _invalid("ai_enablement_paid_preflight_failed") from error
    return {
        "price_evidence_present": True,
        "maximum_estimated_cost": format(rounded, ".2f"),
    }


class AzureAIEnablementActions:
    """Default package-bound action adapter used only after exact approval."""

    def __init__(
        self,
        *,
        package: Mapping[str, object],
        package_sha256: str,
        secret_writer: Callable[..., None] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        environment: Mapping[str, str] = os.environ,
        browser_credential_provider: Callable[[], object] | None = None,
        publisher: Callable[[], str] | None = None,
        patch_applier: Callable[..., str] | None = None,
        arm_requester: ARMRequester | None = None,
        browser_checker: Callable[[str], None] | None = None,
        resource_deployer: Callable[[], Mapping[str, object]] | None = None,
        revision_verifier: Callable[..., object] | None = None,
        qualification_executor: Callable[[Mapping[str, str]], int] | None = None,
    ) -> None:
        self.package = package
        self.package_sha256 = package_sha256
        self._now = now
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._runner = runner
        self._base_environment = _safe_process_environment(environment)
        self._browser_credential_provider = browser_credential_provider
        self._browser_credential: bytearray | None = None
        self.current_projection: dict[str, object] | None = None
        self._immutable_configuration: dict[str, object] | None = None
        self._current_revision = str(package["azure_target"]["rollback_revision"])
        self._pending_transitions: dict[str, PendingAITransition] = {}
        self._hosted_url: str | None = None
        self._publisher = publisher or self._publish_candidate
        self._patch_applier = patch_applier or self._apply_patch_azure
        self._arm_requester = arm_requester or self._request_arm
        self._arm_credential: AzureCliCredential | None = None
        self._arm_operation_deadline: float | None = None
        self._browser_checker = browser_checker or self._run_browser_gate
        self._resource_deployer = resource_deployer
        self._revision_verifier = revision_verifier or self._verify_revision
        self._qualification_executor = (
            qualification_executor or self._run_paid_qualification
        )
        self._secret_writer = secret_writer or self._write_secret_azure

    def _prepare_browser_credential(self) -> None:
        """Read the operator password only after the nine Azure reads succeed."""

        if self._browser_credential is not None:
            return
        if self._browser_credential_provider is None:
            raise _invalid("ai_enablement_browser_credential_unavailable")
        provided: object = None
        try:
            provided = self._browser_credential_provider()
            if (
                not isinstance(provided, str)
                or not provided
                or len(provided) > 4_096
                or any(character in provided for character in ("\0", "\r", "\n"))
            ):
                raise _invalid("ai_enablement_browser_credential_unavailable")
            self._browser_credential = bytearray(provided.encode())
        except AzureAIEnablementActionInvalid:
            raise
        except Exception as error:
            raise _invalid("ai_enablement_browser_credential_unavailable") from error
        finally:
            provided = None

    def clear_browser_credential(self) -> None:
        """Wipe the in-memory browser-only credential at process completion."""

        _wipe(self._browser_credential)
        self._browser_credential = None

    def azure_revalidator(self, package: Mapping[str, object]) -> dict[str, object]:
        def observe(values: Mapping[str, object]) -> None:
            hosted_url = values.get("hosted_url")
            configuration = values.get("immutable_configuration")
            if not isinstance(hosted_url, str) or not isinstance(
                configuration,
                Mapping,
            ):
                raise _invalid("ai_enablement_azure_authority_drift")
            self._hosted_url = hosted_url
            self._immutable_configuration = deepcopy(dict(configuration))

        result, projection = read_sanitized_azure_authority(
            package,
            runner=self._runner,
            safe_observer=observe,
            environment=self._base_environment,
        )
        self.current_projection = projection
        self._current_revision = str(package["azure_target"]["rollback_revision"])
        if self._browser_credential_provider is not None:
            self._prepare_browser_credential()
        return result

    def paid_preflight(self, package: Mapping[str, object]) -> dict[str, object]:
        return provider_price_preflight(package)

    def _result(self, state: str) -> dict[str, object]:
        try:
            specification = self.package["execution_contract"]["states"][state]
        except (KeyError, TypeError) as error:
            raise _invalid("ai_enablement_state_mismatch") from error
        return {
            "operations": deepcopy(specification["operations"]),
            "evidence": deepcopy(specification["expected_evidence"]),
            "outputs": {},
        }

    def _write_secret(self, value: str, *, write_kind: str) -> None:
        try:
            self._secret_writer(value, write_kind=write_kind)
        except Exception as error:
            raise _invalid("ai_enablement_secret_write_failed") from error

    def _write_secret_azure(self, value: str, *, write_kind: str) -> None:
        if write_kind not in {"placeholder", "real", "emergency"}:
            raise _invalid("ai_enablement_secret_boundary_invalid")
        target = self.package["azure_target"]
        parameters = {
            "$schema": (
                "https://schema.management.azure.com/schemas/2019-04-01/"
                "deploymentParameters.json#"
            ),
            "contentVersion": "1.0.0.0",
            "parameters": {
                "deploymentEnabled": {"value": True},
                "vaultName": {"value": target["vault_name"]},
                "openAiApiKey": {"value": value},
            },
        }
        command = [
            "az",
            "deployment",
            "group",
            "create",
            "--subscription",
            str(target["subscription_id"]),
            "--resource-group",
            str(target["resource_group"]),
            "--name",
            f"ai-{write_kind}-{self.package_sha256[:8]}",
            "--template-file",
            str(Path(__file__).resolve().parents[1] / "infra/ai_secret_write.bicep"),
            "--parameters",
            "@/dev/stdin",
            "--query",
            "properties.outputs",
            "--only-show-errors",
            "--output",
            "json",
        ]
        encoded = json.dumps(
            parameters,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        try:
            completed = self._runner(
                command,
                input=encoded,
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
                shell=False,
                env=self._base_environment,
            )
            outputs = json.loads(completed.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            raise _invalid("ai_enablement_secret_write_failed") from error
        finally:
            encoded = ""
        expected_id = (
            _resource_id(
                target,
                "Microsoft.KeyVault",
                "vaults",
                str(target["vault_name"]),
            )
            + "/secrets/openai-api-key"
        )
        try:
            values = {key: item["value"] for key, item in outputs.items()}
        except (AttributeError, TypeError, KeyError) as error:
            raise _invalid("ai_enablement_secret_write_failed") from error
        if (
            completed.returncode != 0
            or values
            != {
                "deploymentEnabled": True,
                "keyVaultSecretName": "openai-api-key",
                "keyVaultSecretResourceId": expected_id,
            }
        ):
            raise _invalid("ai_enablement_secret_write_failed")

    def _candidate_image(self, context: Mapping[str, object]) -> str:
        digest = context.get("candidate_image_digest")
        if (
            not isinstance(digest, str)
            or len(digest) != 71
            or not digest.startswith("sha256:")
        ):
            raise _invalid("ai_enablement_image_digest_invalid")
        target = self.package["azure_target"]
        repository = self.package["candidate"]["image_repository"]
        return f"{target['registry_name']}.azurecr.io/{repository}@{digest}"

    def _suffix(self, label: str, context: Mapping[str, object]) -> str:
        image = self._candidate_image(context)
        digest_prefix = image.rsplit("@sha256:", 1)[1][:7]
        return f"{label}-{self.package_sha256[:8]}-{digest_prefix}"

    def _apply_revision(
        self,
        *,
        enabled: bool,
        label: str,
        role: str,
        context: Mapping[str, object],
        budget_failure_rehearsal: bool = False,
    ) -> str:
        if (
            self.current_projection is None
            or self._immutable_configuration is None
        ):
            raise _invalid("ai_enablement_azure_authority_drift")
        target = self.package["azure_target"]
        suffix = self._suffix(label, context)
        identity_resource_id = _resource_id(
            target,
            "Microsoft.ManagedIdentity",
            "userAssignedIdentities",
            str(target["identity_name"]),
        )
        enabled_values: dict[str, object] = {}
        if enabled:
            try:
                enabled_values = {
                    "vault_url": context["vault_url"],
                    "secret_name": "openai-api-key",
                    "managed_identity_client_id": context[
                        "managed_identity_client_id"
                    ],
                }
            except KeyError as error:
                raise _invalid("ai_enablement_resource_output_drift") from error
        predecessor_projection = deepcopy(self.current_projection)
        predecessor_revision = self._current_revision
        try:
            patch = build_ai_revision_patch(
                self.current_projection,
                enabled=enabled,
                candidate_image=self._candidate_image(context),
                revision_suffix=suffix,
                ai_identity_resource_id=identity_resource_id,
                budget_failure_rehearsal=budget_failure_rehearsal,
                **enabled_values,
            )
            target_projection = canonicalize_ai_revision_patch_target(patch)
            acknowledgement = self._patch_applier(
                patch,
                revision_suffix=suffix,
            )
        except AzureAIEnablementActionInvalid:
            raise
        except Exception as error:
            raise _invalid("ai_enablement_patch_unconfirmed") from error
        expected_revision = f"{target['app_name']}--{suffix}"
        if acknowledgement != "accepted":
            raise _invalid("ai_enablement_patch_unconfirmed")
        started_at = self._monotonic()
        self._pending_transitions[expected_revision] = PendingAITransition(
            role=role,
            acknowledgement=acknowledgement,
            started_at=started_at,
            predecessor_revision=predecessor_revision,
            target_revision=expected_revision,
            predecessor_projection=predecessor_projection,
            target_projection=deepcopy(target_projection),
            target_image=self._candidate_image(context),
            immutable_configuration=deepcopy(self._immutable_configuration),
        )
        self.current_projection = deepcopy(target_projection)
        self._current_revision = expected_revision
        return expected_revision

    def _reconcile_revision(
        self,
        *,
        enabled: bool,
        image: str,
        revision: str,
        context: Mapping[str, object],
        role: str,
    ) -> dict[str, object] | None:
        try:
            result = self._revision_verifier(
                enabled=enabled,
                image=image,
                revision=revision,
                context=context,
                role=role,
            )
        finally:
            self._pending_transitions.pop(revision, None)
        if result is not None and not isinstance(result, Mapping):
            raise _invalid("ai_enablement_revision_unverified")
        return deepcopy(dict(result)) if isinstance(result, Mapping) else None

    def _recover_disabled(
        self,
        *,
        label: str,
        role: str,
        context: Mapping[str, object],
        overwrite_placeholder: bool,
    ) -> dict[str, object]:
        if self.current_projection is None:
            raise _invalid("ai_enablement_azure_authority_drift")
        target = self.package["azure_target"]
        suffix = self._suffix(label, context)
        identity_resource_id = _resource_id(
            target,
            "Microsoft.ManagedIdentity",
            "userAssignedIdentities",
            str(target["identity_name"]),
        )
        try:
            recovered_projection = canonicalize_ai_revision_patch_target(
                build_ai_revision_patch(
                    self.current_projection,
                    enabled=False,
                    candidate_image=self._candidate_image(context),
                    revision_suffix=suffix,
                    ai_identity_resource_id=identity_resource_id,
                )
            )
        except Exception as error:
            raise _invalid("ai_enablement_emergency_disable_failed") from error
        expected_revision = f"{target['app_name']}--{suffix}"
        patch_error: BaseException | None = None
        reconciliation_error: BaseException | None = None
        placeholder_error: Exception | None = None
        reconciliation: dict[str, object] | None = None
        try:
            self._apply_revision(
                enabled=False,
                label=label,
                role=role,
                context=context,
            )
        except (Exception, KeyboardInterrupt) as error:
            patch_error = error
        if patch_error is None:
            try:
                reconciliation = self._reconcile_revision(
                    enabled=False,
                    image=self._candidate_image(context),
                    revision=expected_revision,
                    context=context,
                    role=role,
                )
            except (Exception, KeyboardInterrupt) as error:
                reconciliation_error = error
        if overwrite_placeholder:
            placeholder = secrets.token_urlsafe(48)
            try:
                self._write_secret(placeholder, write_kind="emergency")
            except Exception as error:
                placeholder_error = error
            finally:
                placeholder = ""
        if (
            patch_error is not None
            or reconciliation_error is not None
            or placeholder_error is not None
        ):
            source = patch_error or reconciliation_error or placeholder_error
            raise _invalid(
                "ai_enablement_emergency_disable_failed",
                reconciliation_evidence=(
                    reconciliation
                    if isinstance(reconciliation, Mapping)
                    else getattr(source, "reconciliation_evidence", None)
                ),
            ) from source
        self.current_projection = recovered_projection
        return {
            "ai_disabled_confirmed": True,
            "placeholder_overwrite_succeeded": True,
            "reconciliation": deepcopy(reconciliation),
        }

    def emergency_recovery(
        self,
        *,
        context: Mapping[str, object],
        real_secret_write_attempted: bool,
    ) -> dict[str, object]:
        """Make a post-secret-write failure inert exactly once."""

        if real_secret_write_attempted is not True:
            raise _invalid("ai_enablement_emergency_boundary_invalid")
        return self._recover_disabled(
            label="abort",
            role="emergency_disabled",
            context=context,
            overwrite_placeholder=True,
        )

    def _publish_candidate(self) -> str:
        target = self.package["azure_target"]
        repository = self.package["repository"]
        candidate = self.package["candidate"]
        return publish_registry_image_discover_digest(
            subscription_id=str(target["subscription_id"]),
            registry_name=str(target["registry_name"]),
            repository=str(candidate["image_repository"]),
            candidate_git_sha=str(repository["head_sha"]),
            package_sha256=self.package_sha256,
            image_input_sha256=str(candidate["image_input_sha256"]),
            environment=self._base_environment,
            runner=self._runner,
        )

    def _apply_patch_azure(
        self,
        patch: Mapping[str, object],
        *,
        revision_suffix: str,
    ) -> str:
        target = self.package["azure_target"]
        app_id = _resource_id(
            target,
            "Microsoft.App",
            "containerApps",
            str(target["app_name"]),
        )
        try:
            deadline_started_at = self._monotonic()
            self._arm_operation_deadline = (
                float(deadline_started_at) + MAX_ARM_OPERATION_SECONDS
            )
            wait_for_arm_patch(
                app_resource_id=app_id,
                patch_body=patch,
                request=self._arm_requester,
                monotonic=self._monotonic,
                sleeper=self._sleeper,
            )
        except ARMOperationInvalid as error:
            raise _invalid(str(error)) from None
        except Exception:
            raise _invalid("ai_enablement_patch_unconfirmed") from None
        finally:
            self._arm_operation_deadline = None
        return "accepted"

    def _request_arm(
        self,
        method: str,
        url: str,
        body: Mapping[str, object] | None,
    ) -> ARMResponse:
        token = ""
        session: requests.Session | None = None
        try:
            if self._arm_credential is None:
                self._arm_credential = AzureCliCredential(process_timeout=30)
            token = self._arm_credential.get_token(
                "https://management.azure.com/.default"
            ).token
            if not isinstance(token, str) or not token:
                raise TypeError
            timeout = 300.0
            if self._arm_operation_deadline is not None:
                remaining = self._arm_operation_deadline - self._monotonic()
                if (
                    not isinstance(remaining, (int, float))
                    or isinstance(remaining, bool)
                    or not math.isfinite(float(remaining))
                    or remaining <= 0
                ):
                    raise TypeError
                timeout = min(timeout, float(remaining))
            session = requests.Session()
            session.trust_env = False
            response = session.request(
                method,
                url,
                json=deepcopy(dict(body)) if body is not None else None,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=timeout,
                allow_redirects=False,
            )
            headers = {
                name: value
                for name, value in response.headers.items()
                if name.casefold()
                in {"azure-asyncoperation", "location", "retry-after"}
            }
            payload: dict[str, object] = {}
            if response.status_code in {200, 201} and response.content:
                raw_payload = response.json()
                if not isinstance(raw_payload, Mapping):
                    raise TypeError
                if method == "PATCH" and "id" in raw_payload:
                    payload["id"] = raw_payload["id"]
                elif method == "GET":
                    properties = raw_payload.get("properties")
                    if "id" in raw_payload:
                        payload["id"] = raw_payload["id"]
                    if (
                        isinstance(properties, Mapping)
                        and "provisioningState" in properties
                    ):
                        payload["provisioningState"] = properties[
                            "provisioningState"
                        ]
            return ARMResponse(
                status_code=response.status_code,
                headers=headers,
                payload=payload,
            )
        except Exception:
            raise _invalid("ai_enablement_patch_unconfirmed") from None
        finally:
            token = ""
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    def _run_browser_gate(self, scenario: str) -> None:
        if (
            self._hosted_url is None
            or scenario
            not in {"ai-disabled", "budget", "provider-unavailable", "paid-ai"}
        ):
            raise _invalid("ai_enablement_browser_authority_invalid")
        if self._browser_credential is None:
            raise _invalid("ai_enablement_browser_credential_unavailable")
        child_environment = dict(self._base_environment)
        credential = ""
        try:
            credential = self._browser_credential.decode()
            child_environment[_BROWSER_OPERATOR_PASSWORD_ENVIRONMENT] = credential
            completed = self._runner(
                [
                    "node",
                    "scripts/browser_release_gate.mjs",
                    self._hosted_url,
                    scenario,
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=child_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
                shell=False,
            )
            payload = json.loads(completed.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            raise _invalid("ai_enablement_browser_failed") from error
        finally:
            child_environment.clear()
            credential = ""
        if (
            completed.returncode != 0
            or not isinstance(payload, Mapping)
            or payload.get("scenario") != scenario
            or payload.get("externalRequests") != 0
            or payload.get("consoleErrors") != 0
        ):
            raise _invalid("ai_enablement_browser_failed")
        if scenario == "ai-disabled" and payload.get("providerTurns") != 0:
            raise _invalid("ai_enablement_browser_failed")
        if scenario == "budget" and any(
            payload.get(name) != 0
            for name in (
                "providerAttemptCount",
                "ledgerAttemptCount",
                "providerReservedTokens",
                "ledgerReservedTokens",
            )
        ):
            raise _invalid("ai_enablement_browser_failed")
        if scenario == "provider-unavailable" and (
            payload.get("providerAttemptCount") != 1
            or payload.get("ledgerAttemptCount") != 1
            or not isinstance(payload.get("providerReservedTokens"), int)
            or payload["providerReservedTokens"] < 16_000
            or payload.get("ledgerReservedTokens")
            != payload["providerReservedTokens"]
            or payload.get("providerStatus") != "failed"
            or payload.get("providerErrorCode") != "provider_auth_rejected"
        ):
            raise _invalid("ai_enablement_browser_failed")
        if scenario == "paid-ai" and (
            payload.get("providerTurns") != 1
            or payload.get("publicDemoViewer") is not True
            or payload.get("csrfSessionScoped") is not True
            or payload.get("presetAuditComplete") is not True
            or not isinstance(payload.get("storeScopeCount"), int)
            or payload["storeScopeCount"] < 1
        ):
            raise _invalid("ai_enablement_browser_failed")

    def _deploy_resources(self) -> Mapping[str, object]:
        target = self.package["azure_target"]
        vault_name = str(target["vault_name"])
        if not vault_name.endswith("-ai-kv"):
            raise _invalid("ai_enablement_resource_output_drift")
        prefix = vault_name.removesuffix("-ai-kv")
        if str(target["identity_name"]) != f"{prefix}-ai-identity":
            raise _invalid("ai_enablement_resource_output_drift")
        command = [
            "az",
            "deployment",
            "group",
            "create",
            "--subscription",
            str(target["subscription_id"]),
            "--resource-group",
            str(target["resource_group"]),
            "--name",
            f"ai-enable-{self.package_sha256[:8]}",
            "--template-file",
            str(Path(__file__).resolve().parents[1] / "infra/ai_enablement.bicep"),
            "--parameters",
            "deploymentEnabled=true",
            f"namePrefix={prefix}",
            f"location={target['location']}",
            (
                "logAnalyticsWorkspaceName="
                f"{target['log_analytics_workspace_name']}"
            ),
            "--mode",
            "Incremental",
            "--query",
            "properties.outputs",
            "--only-show-errors",
            "--output",
            "json",
        ]
        try:
            completed = self._runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
                shell=False,
                env=self._base_environment,
            )
            outputs = json.loads(completed.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            raise _invalid("ai_enablement_resource_create_failed") from error
        if completed.returncode != 0 or not isinstance(outputs, Mapping):
            raise _invalid("ai_enablement_resource_create_failed")
        try:
            values = {key: value["value"] for key, value in outputs.items()}
            raw_vault_url = values["keyVaultUrl"]
            result = {
                "vault_url": (
                    raw_vault_url.removesuffix("/")
                    if isinstance(raw_vault_url, str)
                    else raw_vault_url
                ),
                "identity_resource_id": values["identityResourceId"],
                "managed_identity_client_id": values["managedIdentityClientId"],
                "managed_identity_principal_id": values[
                    "managedIdentityPrincipalId"
                ],
                "vault_resource_id": values["keyVaultResourceId"],
                "canonical_secret_resource_id": values[
                    "canonicalSecretResourceId"
                ],
                "secret_officer_assignment_resource_id": values[
                    "adminAiSecretOfficerRoleAssignmentResourceId"
                ],
                "legacy_secrets_user_assignment_resource_id": values[
                    "legacyVaultSecretsUserRoleAssignmentResourceId"
                ],
            }
        except (KeyError, TypeError) as error:
            raise _invalid("ai_enablement_resource_output_drift") from error
        expected = {
            "vault_url": f"https://{vault_name}.vault.azure.net",
            "identity_resource_id": _resource_id(
                target,
                "Microsoft.ManagedIdentity",
                "userAssignedIdentities",
                str(target["identity_name"]),
            ),
            "vault_resource_id": _resource_id(
                target,
                "Microsoft.KeyVault",
                "vaults",
                vault_name,
            ),
        }
        expected["canonical_secret_resource_id"] = (
            f"{expected['vault_resource_id']}/secrets/openai-api-key"
        )
        if (
            raw_vault_url != f"{expected['vault_url']}/"
            or result["vault_url"] != expected["vault_url"]
            or result["identity_resource_id"].casefold()
            != expected["identity_resource_id"].casefold()
            or not _canonical_uuid4(result["managed_identity_client_id"])
            or not _canonical_uuid4(result["managed_identity_principal_id"])
            or not isinstance(result["vault_resource_id"], str)
            or result["vault_resource_id"].casefold()
            != expected["vault_resource_id"].casefold()
            or not isinstance(result["canonical_secret_resource_id"], str)
            or result["canonical_secret_resource_id"].casefold()
            != expected["canonical_secret_resource_id"].casefold()
            or not self._assignment_id_at_scope(
                result["secret_officer_assignment_resource_id"],
                str(expected["canonical_secret_resource_id"]),
            )
            or not self._assignment_id_at_scope(
                result["legacy_secrets_user_assignment_resource_id"],
                str(expected["vault_resource_id"]),
            )
            or values.get("deploymentEnabled") is not True
            or values.get("keyVaultName") != vault_name
            or values.get("identityName") != target["identity_name"]
        ):
            raise _invalid("ai_enablement_resource_output_drift")
        return result

    @staticmethod
    def _assignment_id_at_scope(value: object, scope: str) -> bool:
        if not isinstance(value, str):
            return False
        prefix = f"{scope}/providers/Microsoft.Authorization/roleAssignments/"
        if not value.casefold().startswith(prefix.casefold()):
            return False
        candidate = value[len(prefix) :]
        try:
            parsed = UUID(candidate)
        except ValueError:
            return False
        return str(parsed) == candidate

    def _role_assignments_for_principal(
        self, principal_id: str
    ) -> frozenset[tuple[tuple[str, str], ...]]:
        return _read_complete_role_assignment_set(
            self.package["azure_target"],
            principal_id=principal_id,
            runner=self._runner,
            environment=self._base_environment,
        )

    def reconcile_admin_ai_secret_access(
        self,
        *,
        context: Mapping[str, object],
    ) -> dict[str, object]:
        """Apply one package/source-bound, exact-ID access migration."""

        repository = self.package.get("repository")
        package_sha256 = context.get("package_sha256")
        source_git_sha = context.get("source_git_sha")
        if (
            not isinstance(repository, Mapping)
            or not isinstance(package_sha256, str)
            or _SHA256.fullmatch(package_sha256) is None
            or not secrets.compare_digest(package_sha256, self.package_sha256)
            or not isinstance(source_git_sha, str)
            or _GIT_SHA.fullmatch(source_git_sha) is None
            or not isinstance(repository.get("head_sha"), str)
            or not secrets.compare_digest(source_git_sha, str(repository["head_sha"]))
        ):
            raise _invalid("ai_enablement_resource_authority_drift")

        resources = dict(self._deploy_resources())
        target = self.package["azure_target"]
        subscription = str(target["subscription_id"])
        principal_id = str(resources["managed_identity_principal_id"])
        vault_scope = str(resources["vault_resource_id"])
        secret_scope = str(resources["canonical_secret_resource_id"])
        officer_id = str(resources["secret_officer_assignment_resource_id"])
        legacy_id = str(resources["legacy_secrets_user_assignment_resource_id"])
        officer = _normalized_role_assignment(
            assignment_id=officer_id,
            principal_id=principal_id,
            role_definition_id=(
                f"/subscriptions/{subscription}/providers/"
                "Microsoft.Authorization/roleDefinitions/"
                f"{_KEY_VAULT_SECRETS_OFFICER_ROLE_DEFINITION_ID}"
            ),
            scope=secret_scope,
        )
        legacy = _normalized_role_assignment(
            assignment_id=legacy_id,
            principal_id=principal_id,
            role_definition_id=(
                f"/subscriptions/{subscription}/providers/"
                "Microsoft.Authorization/roleDefinitions/"
                f"{_KEY_VAULT_SECRETS_USER_ROLE_DEFINITION_ID}"
            ),
            scope=vault_scope,
        )
        try:
            role_assignment_state = str(
                self.package["prepackage_gate"]["role_assignment_state"]
            )
        except (KeyError, TypeError) as error:
            raise _invalid("ai_enablement_role_assignment_phase_invalid") from error
        expected_before = {
            "legacy_only": frozenset({officer, legacy}),
            "officer_only": frozenset({officer}),
        }.get(role_assignment_state)
        if expected_before is None:
            raise _invalid("ai_enablement_role_assignment_phase_invalid")
        before = self._role_assignments_for_principal(principal_id)
        if before != expected_before:
            raise _invalid("ai_enablement_role_assignment_drift")
        if legacy in before:
            command = [
                "az",
                "role",
                "assignment",
                "delete",
                "--subscription",
                subscription,
                "--ids",
                legacy_id,
                "--only-show-errors",
                "--output",
                "none",
            ]
            try:
                completed = self._runner(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    shell=False,
                    env=self._base_environment,
                )
            except (OSError, subprocess.SubprocessError) as error:
                raise _invalid("ai_enablement_role_assignment_delete_failed") from error
            if completed.returncode != 0 or completed.stdout not in {"", None}:
                raise _invalid("ai_enablement_role_assignment_delete_failed")
        after = self._role_assignments_for_principal(principal_id)
        if after != frozenset({officer}):
            raise _invalid("ai_enablement_role_assignment_drift")
        assignment_set_sha256 = hashlib.sha256(
            json.dumps(
                [dict(assignment) for assignment in sorted(after)],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return {
            "vault_url": resources["vault_url"],
            "identity_resource_id": resources["identity_resource_id"],
            "managed_identity_client_id": resources[
                "managed_identity_client_id"
            ],
            "assignment_set_sha256": assignment_set_sha256,
        }

    def _verify_revision(
        self,
        *,
        enabled: bool,
        image: str,
        revision: str,
        context: Mapping[str, object],
        role: str,
    ) -> dict[str, object]:
        target = self.package["azure_target"]
        subscription = str(target["subscription_id"])
        resource_group = str(target["resource_group"])
        app_name = str(target["app_name"])
        pending = self._pending_transitions.get(revision)
        if (
            pending is None
            or pending.role != role
            or pending.target_image != image
            or not isinstance(enabled, bool)
        ):
            raise _invalid("ai_enablement_revision_unverified")

        def application_reader() -> Mapping[str, object]:
            app = _run_json(
                (
                    "az",
                    "containerapp",
                    "show",
                    "--subscription",
                    subscription,
                    "--resource-group",
                    resource_group,
                    "--name",
                    app_name,
                    "--query",
                    (
                        "{location:location,identity:identity,properties:{"
                        "latestRevisionName:properties.latestRevisionName,"
                        "latestReadyRevisionName:properties.latestReadyRevisionName,"
                        "provisioningState:properties.provisioningState,"
                        "configuration:{activeRevisionsMode:properties.configuration."
                        "activeRevisionsMode,ingress:{external:properties.configuration."
                        "ingress.external,fqdn:properties.configuration.ingress.fqdn,"
                        "traffic:properties.configuration.ingress.traffic},registries:"
                        "properties.configuration.registries[].{server:server,identity:"
                        "identity}},template:properties.template}}"
                    ),
                    "--only-show-errors",
                    "--output",
                    "json",
                ),
                runner=self._runner,
                environment=self._base_environment,
            )
            try:
                identity = app["identity"]
                assigned = identity["userAssignedIdentities"]
                properties = app["properties"]
                template = canonicalize_azure_template_readback(
                    properties.get("template")
                )
            except (KeyError, TypeError, AzureAIRevisionInvalid) as error:
                raise _invalid("ai_enablement_revision_unverified") from error
            if not isinstance(assigned, Mapping):
                raise _invalid("ai_enablement_revision_unverified")
            return {
                "location": app.get("location"),
                "identity": {
                    "type": identity.get("type"),
                    "userAssignedIdentities": {
                        str(identity_id): {} for identity_id in assigned
                    },
                },
                "properties": {
                    "latestRevisionName": properties.get("latestRevisionName"),
                    "latestReadyRevisionName": properties.get(
                        "latestReadyRevisionName"
                    ),
                    "provisioningState": properties.get("provisioningState"),
                    "configuration": deepcopy(properties.get("configuration")),
                    "template": template,
                },
            }

        def revisions_reader() -> Sequence[Mapping[str, object]]:
            rows = _run_json(
                (
                    "az",
                    "containerapp",
                    "revision",
                    "list",
                    "--subscription",
                    subscription,
                    "--resource-group",
                    resource_group,
                    "--name",
                    app_name,
                    "--query",
                    (
                        "[].{name:name,properties:{active:properties.active,"
                        "healthState:properties.healthState,provisioningState:"
                        "properties.provisioningState}}"
                    ),
                    "--only-show-errors",
                    "--output",
                    "json",
                ),
                runner=self._runner,
                environment=self._base_environment,
            )
            if not isinstance(rows, list):
                raise _invalid("ai_enablement_revision_unverified")
            canonical_rows: list[dict[str, object]] = []
            try:
                for row in rows:
                    if not isinstance(row, Mapping) or set(row) != {
                        "name",
                        "properties",
                    }:
                        raise TypeError
                    properties = row["properties"]
                    if not isinstance(properties, Mapping) or set(properties) != {
                        "active",
                        "healthState",
                        "provisioningState",
                    }:
                        raise TypeError
                    canonical_rows.append(
                        {
                            "name": row["name"],
                            "properties": {
                                "active": properties["active"],
                                "healthState": properties["healthState"],
                                "provisioningState": properties[
                                    "provisioningState"
                                ],
                            },
                        }
                    )
            except (KeyError, TypeError, AzureAIRevisionInvalid) as error:
                raise _invalid("ai_enablement_revision_unverified") from error
            return canonical_rows

        try:
            return reconcile_ai_transition(
                pending,
                application_reader=application_reader,
                revisions_reader=revisions_reader,
                monotonic=self._monotonic,
                sleeper=self._sleeper,
            )
        except AzureAIReconciliationInvalid as error:
            raise _invalid(
                str(error),
                reconciliation_evidence=error.evidence,
            ) from error

    def _run_paid_qualification(self, environment: Mapping[str, str]) -> int:
        if set(environment) != {"BIZPULSE_DEPLOY_OPENAI_API_KEY"}:
            raise _invalid("ai_enablement_secret_boundary_invalid")
        child_environment = dict(self._base_environment)
        child_environment.update(environment)
        try:
            with tempfile.TemporaryDirectory(
                prefix="newcaostone-ai-qualification-"
            ) as directory:
                receipt = Path(directory) / "qualification.json"
                completed = self._runner(
                    [
                        sys.executable,
                        "scripts/qualify_openai_model.py",
                        "--execute-paid-qualification",
                        "--receipt",
                        str(receipt),
                    ],
                    cwd=Path(__file__).resolve().parents[1],
                    env=child_environment,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=420,
                    shell=False,
                )
                if (
                    completed.returncode != 0
                    or not receipt.is_file()
                    or receipt.stat().st_size > 1_000_000
                ):
                    raise _invalid("ai_enablement_paid_qualification_failed")
                payload = json.loads(receipt.read_text(encoding="utf-8"))
        except AzureAIEnablementActionInvalid:
            raise
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            raise _invalid("ai_enablement_paid_qualification_failed") from error
        finally:
            child_environment.clear()
        cases = payload.get("cases") if isinstance(payload, Mapping) else None
        if (
            payload.get("passed") is not True
            or payload.get("model_snapshot", {}).get("model")
            != self.package["provider_pricing"]["model"]
            or not isinstance(cases, list)
            or len(cases) != 12
            or any(not isinstance(item, Mapping) or item.get("passed") is not True for item in cases)
        ):
            raise _invalid("ai_enablement_paid_qualification_failed")
        return 12

    def operation_executor(
        self,
        state: str,
        *,
        environment: Mapping[str, str],
        secret_value: str | None,
        context: Mapping[str, object],
    ) -> dict[str, object]:
        if state != "paid_model_qualification" and environment:
            raise _invalid("ai_enablement_secret_boundary_invalid")
        if state != "real_secret_write" and secret_value is not None:
            raise _invalid("ai_enablement_secret_boundary_invalid")
        if state == "publish_candidate_image":
            try:
                digest = self._publisher()
            except Exception as error:
                raise _invalid("ai_enablement_image_publish_failed") from error
            if (
                not isinstance(digest, str)
                or len(digest) != 71
                or not digest.startswith("sha256:")
            ):
                raise _invalid("ai_enablement_image_digest_invalid")
            result = self._result(state)
            result["outputs"] = {"candidate_image_digest": digest}
            return result
        if state == "activate_ai_disabled_candidate":
            revision = self._apply_revision(
                enabled=False,
                label="ai-off",
                role="ai_disabled_candidate",
                context=context,
            )
            result = self._result(state)
            result["outputs"] = {
                "candidate_image_digest": context["candidate_image_digest"],
                "revision": revision,
            }
            return result
        if state == "verify_ai_disabled_candidate":
            image = self._candidate_image(context)
            try:
                reconciliation = self._reconcile_revision(
                    enabled=False,
                    image=image,
                    revision=context["ai_disabled_revision"],
                    context=context,
                    role="ai_disabled_candidate",
                )
                self._browser_checker("ai-disabled")
            except Exception as error:
                raise _invalid("ai_enablement_revision_unverified") from error
            result = self._result(state)
            result["outputs"] = {
                "candidate_image_digest": context["candidate_image_digest"],
                "ai_enabled": False,
                "reconciliation": reconciliation,
            }
            return result
        if state == "reconcile_ai_vault_identity_role_diagnostics":
            try:
                outputs = (
                    dict(self._resource_deployer())
                    if self._resource_deployer is not None
                    else self.reconcile_admin_ai_secret_access(context=context)
                )
            except AzureAIEnablementActionInvalid:
                raise
            except Exception as error:
                raise _invalid("ai_enablement_resource_create_failed") from error
            result = self._result(state)
            result["outputs"] = outputs
            return result
        if state == "budget_failure_rehearsal":
            primary_error: Exception | None = None
            enabled_reconciliation: dict[str, object] | None = None
            try:
                revision = self._apply_revision(
                    enabled=True,
                    label="budget",
                    role="budget_enabled",
                    context=context,
                    budget_failure_rehearsal=True,
                )
                enabled_reconciliation = self._reconcile_revision(
                    enabled=True,
                    image=self._candidate_image(context),
                    revision=revision,
                    context=context,
                    role="budget_enabled",
                )
                self._browser_checker("budget")
            except Exception as error:
                primary_error = error
            recovery = self._recover_disabled(
                label="recover-b",
                role="budget_recovery",
                context=context,
                overwrite_placeholder=False,
            )
            if primary_error is not None:
                if isinstance(primary_error, AzureAIEnablementActionInvalid):
                    raise primary_error
                raise _invalid("ai_enablement_browser_failed") from primary_error
            result = self._result(state)
            result["outputs"] = {
                "reconciliations": [
                    enabled_reconciliation,
                    recovery["reconciliation"],
                ]
            }
            return result
        if state == "provider_failure_placeholder_write":
            if environment or secret_value is not None:
                raise _invalid("ai_enablement_secret_boundary_invalid")
            placeholder = secrets.token_urlsafe(48)
            try:
                self._write_secret(placeholder, write_kind="placeholder")
            finally:
                placeholder = ""
            return self._result(state)
        if state == "provider_failure_rehearsal":
            primary_error: Exception | None = None
            enabled_reconciliation = None
            try:
                revision = self._apply_revision(
                    enabled=True,
                    label="provider",
                    role="provider_enabled",
                    context=context,
                )
                enabled_reconciliation = self._reconcile_revision(
                    enabled=True,
                    image=self._candidate_image(context),
                    revision=revision,
                    context=context,
                    role="provider_enabled",
                )
                self._browser_checker("provider-unavailable")
            except Exception as error:
                primary_error = error
            recovery = self._recover_disabled(
                label="recover-p",
                role="provider_recovery",
                context=context,
                overwrite_placeholder=False,
            )
            if primary_error is not None:
                if isinstance(primary_error, AzureAIEnablementActionInvalid):
                    raise primary_error
                raise _invalid("ai_enablement_browser_failed") from primary_error
            result = self._result(state)
            result["outputs"] = {
                "reconciliations": [
                    enabled_reconciliation,
                    recovery["reconciliation"],
                ]
            }
            return result
        if state == "paid_model_qualification":
            if (
                set(environment) != {"BIZPULSE_DEPLOY_OPENAI_API_KEY"}
                or not environment["BIZPULSE_DEPLOY_OPENAI_API_KEY"]
            ):
                raise _invalid("ai_enablement_secret_boundary_invalid")
            try:
                count = self._qualification_executor(environment)
            except Exception as error:
                raise _invalid("ai_enablement_paid_qualification_failed") from error
            if count != 12:
                raise _invalid("ai_enablement_paid_qualification_failed")
            result = self._result(state)
            result["outputs"] = {"paid_call_count": 12}
            return result
        if state == "real_secret_write":
            if environment or not isinstance(secret_value, str) or not secret_value:
                raise _invalid("ai_enablement_secret_boundary_invalid")
            self._write_secret(secret_value, write_kind="real")
            return self._result(state)
        if state == "activate_ai_enabled_revision":
            revision = self._apply_revision(
                enabled=True,
                label="ai-on",
                role="ai_enabled",
                context=context,
            )
            result = self._result(state)
            result["outputs"] = {
                "candidate_image_digest": context["candidate_image_digest"],
                "final_revision": revision,
            }
            return result
        if state == "verify_ai_enabled_revision":
            try:
                reconciliation = self._reconcile_revision(
                    enabled=True,
                    image=self._candidate_image(context),
                    revision=context["final_revision"],
                    context=context,
                    role="ai_enabled",
                )
            except Exception as error:
                raise _invalid("ai_enablement_revision_unverified") from error
            result = self._result(state)
            result["outputs"] = {
                "candidate_image_digest": context["candidate_image_digest"],
                "ai_enabled": True,
                "reconciliation": reconciliation,
            }
            return result
        if state == "paid_hosted_manual_send_smoke":
            try:
                self._browser_checker("paid-ai")
            except Exception as error:
                raise _invalid("ai_enablement_browser_failed") from error
            result = self._result(state)
            result["outputs"] = {"paid_call_count": 1}
            return result
        if state == "sanitize_receipt":
            return self._result(state)
        raise _invalid("ai_enablement_state_not_implemented")


def _canonical_uuid4(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
    except ValueError:
        return False
    return str(parsed) == value and parsed.version == 4
