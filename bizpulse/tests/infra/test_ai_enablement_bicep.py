from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_BICEP = PROJECT_ROOT / "infra/ai_enablement.bicep"
AI_PARAMS = PROJECT_ROOT / "infra/environments/ai_enablement.bicepparam"
AI_SECRET_BICEP = PROJECT_ROOT / "infra/ai_secret_write.bicep"
AI_SECRET_PARAMS = PROJECT_ROOT / "infra/environments/ai_secret_write.bicepparam"
CANONICAL_SECRET_NAME = "openai-api-key"
KEY_VAULT_SECRETS_OFFICER_ROLE_ID = "b86a8fe4-44ce-4948-aee5-eccb2c155cd7"


def _compile(path: Path) -> dict[str, object]:
    az = shutil.which("az")
    assert az is not None, "azure_cli_missing_for_local_bicep_compile"
    completed = subprocess.run(
        [az, "bicep", "build", "--file", str(path), "--stdout"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "warning" not in completed.stderr.lower(), completed.stderr
    return json.loads(completed.stdout)


def _resource_types(payload: object) -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        resource_type = payload.get("type")
        if isinstance(resource_type, str):
            found.append(resource_type)
        for value in payload.values():
            found.extend(_resource_types(value))
    elif isinstance(payload, list):
        for value in payload:
            found.extend(_resource_types(value))
    return found


def test_ai_enablement_template_has_an_exact_isolated_resource_allowlist() -> None:
    template = _compile(AI_BICEP)
    types = _resource_types(template.get("resources", []))
    lowered = [item.lower() for item in types]

    assert lowered.count("microsoft.managedidentity/userassignedidentities") == 0
    assert lowered.count("microsoft.keyvault/vaults") == 0
    assert lowered.count("microsoft.keyvault/vaults/secrets") == 0
    assert lowered.count("microsoft.authorization/roleassignments") == 1
    assert lowered.count("microsoft.insights/diagnosticsettings") == 1
    assert lowered.count("microsoft.operationalinsights/workspaces") == 0
    assert len(lowered) == 2
    source = AI_BICEP.read_text()
    assert (
        "resource openaiIdentity "
        "'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing"
    ) in source
    assert "resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing" in source
    assert (
        "resource logWorkspace "
        "'Microsoft.OperationalInsights/workspaces@2023-09-01' existing"
    ) in source
    serialized = json.dumps(template, sort_keys=True).lower()
    for prohibited in (
        "microsoft.app/containerapps",
        "microsoft.dbforpostgresql",
        "microsoft.storage/storageaccounts",
        "microsoft.containerregistry",
        "sellernorthbp-kv",
        "newcaostone-demo-registry",
    ):
        assert prohibited not in serialized


def test_admin_ai_identity_is_scoped_to_the_canonical_secret() -> None:
    template = _compile(AI_BICEP)
    assignments = [
        resource
        for resource in template["resources"]
        if resource["type"].lower() == "microsoft.authorization/roleassignments"
    ]

    assert len(assignments) == 1
    assignment = assignments[0]
    assert assignment["scope"] == (
        "[resourceId('Microsoft.KeyVault/vaults/secrets', "
        f"parameters('openaiKeyVaultName'), '{CANONICAL_SECRET_NAME}')]"
    )
    assert assignment["properties"]["principalId"] == (
        "[reference(resourceId('Microsoft.ManagedIdentity/"
        "userAssignedIdentities', parameters('openaiIdentityName')), "
        "'2023-01-31').principalId]"
    )
    assert assignment["properties"]["principalType"] == "ServicePrincipal"
    assert assignment["properties"]["roleDefinitionId"] == (
        "[variables('keyVaultSecretsOfficerRoleDefinitionId')]"
    )
    assert KEY_VAULT_SECRETS_OFFICER_ROLE_ID in json.dumps(template["variables"])


def test_existing_ai_resources_receive_only_auditing_and_secret_scoped_role() -> None:
    template = _compile(AI_BICEP)
    serialized = json.dumps(template, sort_keys=True)
    parameters = template["parameters"]
    source = AI_BICEP.read_text()

    assert parameters["deploymentEnabled"]["defaultValue"] is False
    assert "secretDeploymentEnabled" not in parameters
    assert "openAiApiKey" not in parameters
    assert "resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing" in source
    assert "resource canonicalSecret 'Microsoft.KeyVault/vaults/secrets@" in source
    assert f"name: '{CANONICAL_SECRET_NAME}'" in source
    assert "scope: canonicalSecret" in source
    assert KEY_VAULT_SECRETS_OFFICER_ROLE_ID in source
    assert (
        "guid(vault!.id, openaiIdentity!.id, keyVaultSecretsUserRoleDefinitionId)"
        in source
    )
    assert "output canonicalSecretResourceId string" in source
    assert "output adminAiSecretOfficerRoleAssignmentResourceId string" in source
    assert "output legacyVaultSecretsUserRoleAssignmentResourceId string" in source
    assert "principalType: 'ServicePrincipal'" in source
    assignment_source = source.split(
        "resource adminAiSecretOfficer ", 1
    )[1].split("resource logWorkspace ", 1)[0]
    assert "scope: vault" not in assignment_source
    assert "AuditEvent" in serialized
    assert "AzurePolicyEvaluationDetails" in serialized
    assert "AllMetrics" in serialized
    assert "listSecrets" not in source
    assert "listKeys" not in source
    assert "param openAiApiKey" not in source
    assert "value: validatedOpenAiApiKey" not in source
    for prohibited_role in (
        "8e3af657-a8ff-443c-a75c-2fe8c4bcb635",  # Owner
        "b24988ac-6180-42a0-ab88-20f7382dd24c",  # Contributor
        "00482a5a-887f-4fb3-b363-3b7fe8e74483",  # Key Vault Administrator
    ):
        assert prohibited_role not in source


def test_inert_ai_parameters_compile_without_a_key_or_external_state() -> None:
    az = shutil.which("az")
    assert az is not None, "azure_cli_missing_for_local_bicep_compile"
    environment = dict(os.environ)
    environment.pop("BIZPULSE_DEPLOY_OPENAI_API_KEY", None)
    completed = subprocess.run(
        [
            az,
            "bicep",
            "build-params",
            "--file",
            str(AI_PARAMS),
            "--stdout",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    compiled = json.loads(completed.stdout)
    parameters = json.loads(compiled["parametersJson"])["parameters"]
    assert parameters["deploymentEnabled"]["value"] is False
    assert parameters["location"]["value"] == "requires-authorization"
    assert "secretDeploymentEnabled" not in parameters
    assert "openAiApiKey" not in parameters
    serialized = json.dumps(parameters, sort_keys=True)
    assert "sk-" not in serialized
    assert "sellernorthbp-kv" not in serialized


def test_secret_write_template_is_inert_and_contains_exactly_one_secure_secret() -> None:
    template = _compile(AI_SECRET_BICEP)
    types = [item.lower() for item in _resource_types(template.get("resources", []))]
    parameters = template["parameters"]
    source = AI_SECRET_BICEP.read_text()

    assert types == ["microsoft.keyvault/vaults/secrets"]
    assert parameters["deploymentEnabled"]["defaultValue"] is False
    assert parameters["openAiApiKey"]["type"] == "securestring"
    assert re.search(r"@secure\(\)\s+param openAiApiKey string = ''", source)
    assert "openAiApiKey_required_when_deployment_enabled" in source
    assert "resource vault 'Microsoft.KeyVault/vaults@2025-05-01' existing" in source
    assert "name: 'openai-api-key'" in source
    serialized = json.dumps(template, sort_keys=True).lower()
    for prohibited in (
        "microsoft.app/containerapps",
        "microsoft.managedidentity",
        "microsoft.authorization/roleassignments",
        "microsoft.insights/diagnosticsettings",
        "microsoft.dbforpostgresql",
        "sellernorthbp-kv",
    ):
        assert prohibited not in serialized


def test_inert_secret_parameters_compile_without_key_or_external_state() -> None:
    az = shutil.which("az")
    assert az is not None, "azure_cli_missing_for_local_bicep_compile"
    environment = dict(os.environ)
    environment.pop("BIZPULSE_DEPLOY_OPENAI_API_KEY", None)
    completed = subprocess.run(
        [
            az,
            "bicep",
            "build-params",
            "--file",
            str(AI_SECRET_PARAMS),
            "--stdout",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    compiled = json.loads(completed.stdout)
    parameters = json.loads(compiled["parametersJson"])["parameters"]
    assert parameters["deploymentEnabled"]["value"] is False
    assert parameters["openAiApiKey"]["value"] == ""
    assert "sk-" not in json.dumps(parameters, sort_keys=True)
