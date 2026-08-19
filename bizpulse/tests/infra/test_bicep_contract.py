from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAIN_BICEP = PROJECT_ROOT / "infra/main.bicep"
APP_BICEP = PROJECT_ROOT / "infra/modules/app.bicep"
OPERATOR_ROTATION_JOB_BICEP = PROJECT_ROOT / "infra/operator_rotation_job.bicep"


def _compiled_bicep(path: Path) -> dict[str, Any]:
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


def _compiled_template() -> dict[str, Any]:
    return _compiled_bicep(MAIN_BICEP)


def _compiled_app_template() -> dict[str, Any]:
    return _compiled_bicep(APP_BICEP)


def _compiled_app_resource(template: dict[str, Any]) -> dict[str, Any]:
    resources = [
        resource
        for resource in template["resources"]
        if resource.get("type") == "Microsoft.App/containerApps"
    ]
    assert len(resources) == 1
    return resources[0]


def _resource_types(template: dict[str, Any]) -> tuple[str, ...]:
    found: list[str] = []

    def visit(payload: object) -> None:
        if isinstance(payload, dict):
            resource_type = payload.get("type")
            if isinstance(resource_type, str):
                found.append(resource_type)
            for value in payload.values():
                visit(value)
        elif isinstance(payload, list):
            for value in payload:
                visit(value)

    visit(template.get("resources", []))
    return tuple(found)


def test_bicep_compiles_to_exact_demo_authorities_without_sqlite() -> None:
    template = _compiled_template()
    serialized = json.dumps(template, sort_keys=True).lower()
    types = _resource_types(template)

    assert types.count("Microsoft.DBforPostgreSQL/flexibleServers") == 1
    assert types.count("Microsoft.Storage/storageAccounts") == 1
    assert types.count("Microsoft.Storage/storageAccounts/blobServices/containers") == 1
    assert types.count("Microsoft.App/containerApps") == 1
    assert types.count("Microsoft.App/jobs") == 5
    assert types.count("Microsoft.OperationalInsights/workspaces") == 1
    assert "microsoft.insights/components" in {value.lower() for value in types}
    assert "sqlite" not in serialized
    assert "allowblobpublicaccess" in serialized
    assert '"publicaccess": "none"' in serialized
    assert '"allowinsecure": false' in serialized
    app_source = (PROJECT_ROOT / "infra/modules/app.bicep").read_text()
    assert "external: applicationEnabled" in app_source
    assert "minReplicas: applicationEnabled ? 1 : 0" in app_source
    assert "revisionSuffix: revisionSuffix" in app_source
    assert '"revisionsuffix"' in serialized


def test_application_module_compiles_mutually_exclusive_phase_authority() -> None:
    template = _compiled_app_template()
    app = _compiled_app_resource(template)
    serialized = json.dumps(template, sort_keys=True)
    app_source = APP_BICEP.read_text()
    app_secrets = app["properties"]["configuration"]["secrets"]

    assert "var phase1AppEnvironment = [" in app_source
    assert "value: 'phase1-fenced'" in app_source
    assert "var phase2AppEnvironment = [" in app_source
    assert "var appSecrets = applicationEnabled ? jobSecrets : []" in app_source
    assert "var appContainer = union(" in app_source
    assert "containers: [\n        appContainer\n      ]" in app_source
    assert app_source.count("secrets: jobSecrets") == 4
    assert app_source.count("secrets: operatorRotationJobSecrets") == 1
    assert app_source.count("env: jobEnvironment") == 4
    assert "phase1-fenced" in serialized
    assert "scripts/phase1_fence_server.py" in serialized
    assert "union(" in serialized
    assert "if(parameters('applicationEnabled')" in app_secrets
    assert "openai-api-key" not in app_secrets
    assert "OPENAI_API_KEY" not in serialized


def test_bicep_is_fail_closed_until_value_complete_authorization() -> None:
    template = _compiled_template()
    parameters = template["parameters"]
    serialized = json.dumps(template, sort_keys=True)
    main_source = MAIN_BICEP.read_text()
    param_file = (PROJECT_ROOT / "infra/environments/demo.bicepparam").read_text()

    assert parameters["deploymentEnabled"]["defaultValue"] is False
    assert parameters["applicationEnabled"]["defaultValue"] is False
    assert "var containerImageIsImmutable" in main_source
    assert "fail('containerImage_must_be_immutable_digest')" in main_source
    assert "fail('openaiKeyVaultUrl_required_when_ai_enabled')" in main_source
    assert "fail('openaiManagedIdentityClientId_required_when_ai_enabled')" in main_source
    assert "fail('openaiManagedIdentityResourceId_required_when_ai_enabled')" in main_source
    assert "param openaiApiKey" not in main_source
    app_source = (PROJECT_ROOT / "infra/modules/app.bicep").read_text()
    assert "param openaiApiKey" not in app_source
    for name in (
        "openaiKeyVaultUrl",
        "openaiManagedIdentityClientId",
        "openaiManagedIdentityResourceId",
    ):
        assert parameters[name]["type"] == "string"
        assert parameters[name]["defaultValue"] == ""
    assert "@sha256:" in main_source
    assert "param applicationRevisionSuffix string = ''" in main_source
    assert "var selectedRevisionSuffix" in main_source
    assert "revisionSuffix: selectedRevisionSuffix" in main_source
    assert "BIZPULSE_RUNTIME_ENVIRONMENT" in serialized
    assert "BIZPULSE_BLOB_CONNECTION_STRING" in serialized
    assert "BIZPULSE_OPENAI_MODEL" in serialized
    assert "BIZPULSE_OPENAI_KEY_VAULT_URL" in serialized
    assert "BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME" in serialized
    assert "BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID" in serialized
    assert "gpt-5.4-nano-2026-03-17" in serialized
    assert parameters["aiDailyAttemptLimit"]["defaultValue"] == 120
    assert parameters["aiMonthlyTokenLimit"]["defaultValue"] == 150_000
    assert parameters["aiMaxConcurrentTurns"]["defaultValue"] == 15
    assert parameters["aiSessionAttemptLimitPerMinute"]["defaultValue"] == 3
    assert parameters["aiGlobalAttemptLimitPerMinute"]["defaultValue"] == 20
    assert parameters["aiBudgetFailureRehearsal"]["defaultValue"] is False
    assert "readEnvironmentVariable" in param_file
    assert "deploymentEnabled = false" in param_file
    assert "applicationEnabled = false" in param_file
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f-]{27,}", param_file, re.I)
    assert "AccountKey=" not in param_file
    assert "BIZPULSE_DEPLOY_OPENAI_API_KEY" not in param_file
    assert not re.search(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b", param_file)


def test_admin_ai_capability_uses_fixed_server_bindings_without_channel_flags() -> None:
    app_template = _compiled_app_template()
    app = _compiled_app_resource(app_template)
    serialized = json.dumps(app_template, sort_keys=True)
    app_source = APP_BICEP.read_text()
    main_source = MAIN_BICEP.read_text()
    param_file = (PROJECT_ROOT / "infra/environments/demo.bicepparam").read_text()

    assert "param openaiKeyVaultSecretName" not in app_source
    assert "param openaiKeyVaultSecretName" not in main_source
    assert "param openaiKeyVaultSecretName" not in param_file
    assert "name: 'BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME'" in app_source
    assert "value: 'openai-api-key'" in app_source
    assert "openai-api-key" in serialized
    assert "OPENAI_API_KEY" not in serialized
    assert "secretRef: 'openai-api-key'" not in app_source
    assert "BIZPULSE_OPERATOR_AI_ENABLED" not in app_source
    assert "BIZPULSE_DEMO_AI_ENABLED" not in app_source
    assert "BIZPULSE_AI_OPERATOR_ENABLED" not in app_source
    assert "BIZPULSE_AI_DEMO_ENABLED" not in app_source

    for setting in (
        "BIZPULSE_OPENAI_KEY_VAULT_URL",
        "BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID",
        "BIZPULSE_OPENAI_MODEL",
        "BIZPULSE_OPENAI_REASONING_EFFORT",
        "BIZPULSE_AI_DAILY_ATTEMPT_LIMIT",
        "BIZPULSE_AI_MONTHLY_TOKEN_LIMIT",
        "BIZPULSE_AI_MAX_CONCURRENT_TURNS",
        "BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE",
        "BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE",
    ):
        assert setting in serialized

    assert "gpt-5.4-nano-2026-03-17" in serialized
    assert "low" in serialized
    assert app["identity"]["userAssignedIdentities"] == (
        "[variables('appUserAssignedIdentities')]"
    )
    identity_expression = app_template["variables"]["appUserAssignedIdentities"]
    assert "if(parameters('aiChatEnabled')" in identity_expression
    assert "parameters('openaiManagedIdentityResourceId')" in identity_expression


def test_admin_ai_capability_preserves_fail_closed_startup_and_readiness() -> None:
    main_source = MAIN_BICEP.read_text()
    app_source = APP_BICEP.read_text()

    assert "aiChatEnabled_requires_enabled_application" in main_source
    assert "openaiKeyVaultUrl_required_when_ai_enabled" in main_source
    assert "openaiManagedIdentityClientId_required_when_ai_enabled" in main_source
    assert "openaiManagedIdentityResourceId_required_when_ai_enabled" in main_source
    assert "BIZPULSE_AI_CHAT_ENABLED" in app_source
    assert "value: aiChatEnabled ? 'true' : 'false'" in app_source
    assert "path: '/health/live'" in app_source
    assert "path: '/health/ready'" in app_source
    assert "external: applicationEnabled" in app_source
    assert "minReplicas: applicationEnabled ? 1 : 0" in app_source


def test_ai_enabled_environment_value_is_canonical_lowercase_boolean() -> None:
    template = _compiled_template()
    serialized = json.dumps(template, sort_keys=True)
    app_source = (PROJECT_ROOT / "infra/modules/app.bicep").read_text()

    assert "value: aiChatEnabled ? 'true' : 'false'" in app_source
    assert "value: string(aiChatEnabled)" not in app_source
    assert "if(parameters('aiChatEnabled'), 'true', 'false')" in serialized
    assert "string(parameters('aiChatEnabled'))" not in serialized


def test_budget_failure_rehearsal_preserves_limits_and_is_transient_only() -> None:
    template = _compiled_template()
    app_template = _compiled_app_template()
    serialized = json.dumps(app_template, sort_keys=True)
    main_source = MAIN_BICEP.read_text()
    app_source = APP_BICEP.read_text()

    assert template["parameters"]["aiMonthlyTokenLimit"]["defaultValue"] == 150_000
    assert template["parameters"]["aiBudgetFailureRehearsal"]["defaultValue"] is False
    assert "fail('aiBudgetFailureRehearsal_requires_enabled_application')" in main_source
    assert "BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL" in app_source
    assert "BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL" in serialized
    assert "@minValue(150000)\n@maxValue(150000)\nparam aiMonthlyTokenLimit" in main_source


def test_deployment_cannot_override_the_official_openai_endpoint() -> None:
    template = _compiled_template()
    app_template = _compiled_app_template()
    serialized = json.dumps(
        {"main": template, "app": app_template},
        sort_keys=True,
    )
    main_source = MAIN_BICEP.read_text()
    app_source = APP_BICEP.read_text()

    assert "openAiBaseUrl" not in main_source
    assert "openAiBaseUrl" not in app_source
    assert "OPENAI_BASE_URL" not in serialized
    assert "OPENAI_BASE_URL" not in main_source
    assert "OPENAI_BASE_URL" not in app_source


def test_private_acr_pull_uses_a_dedicated_managed_identity_without_admin_secret() -> None:
    template = _compiled_template()
    serialized = json.dumps(template, sort_keys=True)
    types = _resource_types(template)
    main_source = MAIN_BICEP.read_text()
    app_source = (PROJECT_ROOT / "infra/modules/app.bicep").read_text()

    assert types.count("Microsoft.ManagedIdentity/userAssignedIdentities") == 1
    assert types.count("Microsoft.Authorization/roleAssignments") == 1
    assert "7f951dda-4ed3-4680-a7ca-43fe172d538d" in main_source
    assert "registryIdentityResourceId" in main_source
    assert "registryIdentityResourceId" in app_source
    assert "identity: registryIdentityResourceId" in app_source
    assert "passwordSecretRef: 'registry-password'" not in app_source
    assert "param registryPassword" not in main_source
    assert "param registryPassword" not in app_source
    assert "registry-password" not in serialized
    assert "output principalId string = app.identity.principalId" not in app_source
    assert "var appUserAssignedIdentities = union(" in app_source
    assert "openaiManagedIdentityResourceId" in app_source
    assert "userAssignedIdentities: appUserAssignedIdentities" in app_source


def test_application_database_url_is_derived_from_the_declared_postgres() -> None:
    template = _compiled_template()
    serialized = json.dumps(template, sort_keys=True)
    param_file = (PROJECT_ROOT / "infra/environments/demo.bicepparam").read_text()

    assert "databaseUrl" not in template["parameters"]
    assert "BIZPULSE_DEPLOY_DATABASE_URL" not in param_file
    assert "serverFqdn" in serialized
    assert "databaseName" in serialized
    assert "sslmode=require" in serialized


def test_resource_keys_are_read_inside_the_dependent_application_module() -> None:
    main_source = MAIN_BICEP.read_text()
    app_source = (PROJECT_ROOT / "infra/modules/app.bicep").read_text()

    assert "listKeys(resourceId('Microsoft.Storage/storageAccounts'" not in main_source
    assert (
        "listKeys(resourceId('Microsoft.OperationalInsights/workspaces'"
        not in main_source
    )
    assert "resource storageAccount 'Microsoft.Storage/storageAccounts@" in app_source
    assert "resource logWorkspace 'Microsoft.OperationalInsights/workspaces@" in app_source
    assert "existing = {" in app_source
    assert "storageAccount.listKeys()" in app_source
    assert "logWorkspace.listKeys()" in app_source


def test_private_postgres_has_pretraffic_prepare_seed_and_maintenance_jobs() -> None:
    template = _compiled_template()
    serialized = json.dumps(template, sort_keys=True)

    assert "scripts/prepare_cloud.py" in serialized
    assert "scripts/seed_demo.py" in serialized
    assert "tests/fixtures/synthetic/v1" in serialized
    assert "tests/fixtures/synthetic/v1/manifest.json" not in serialized
    assert "scripts/maintain_sessions.py" in serialized
    assert "scripts/maintain_storage.py" in serialized
    assert "--expire-temporary" in serialized
    assert "applicationEnabled" in template["parameters"]
    app_source = (PROJECT_ROOT / "infra/modules/app.bicep").read_text()
    assert "resource app 'Microsoft.App/containerApps@2024-03-01' = {" in app_source
    assert "resource sessionMaintenanceJob 'Microsoft.App/jobs@2024-03-01' = {" in app_source
    assert "resource storageMaintenanceJob 'Microsoft.App/jobs@2024-03-01' = {" in app_source
    assert "triggerType: 'Manual'" in app_source
    assert "triggerType: 'Schedule'" in app_source


def test_operator_rotation_job_is_manual_and_scopes_expected_state_to_that_job() -> None:
    template = _compiled_template()
    serialized = json.dumps(template, sort_keys=True)
    app_source = APP_BICEP.read_text()
    main_source = MAIN_BICEP.read_text()
    param_file = (PROJECT_ROOT / "infra/environments/demo.bicepparam").read_text()

    assert "scripts/rotate_operator_password.py" in serialized
    assert "resource operatorRotationJob 'Microsoft.App/jobs@2024-03-01' = {" in app_source
    assert "triggerType: 'Manual'" in app_source
    assert "var operatorRotationJobSecrets = [" in app_source
    assert "var operatorRotationJobEnvironment = [" in app_source
    assert "BIZPULSE_EXPECTED_OPERATOR_PASSWORD_HASH_SHA256" in app_source
    assert "BIZPULSE_OPERATOR_ROTATION_ID" in app_source
    phase2_source = app_source.split("var phase2AppEnvironment = [", 1)[1].split(
        "var appSecrets", 1
    )[0]
    assert "BIZPULSE_EXPECTED_OPERATOR_PASSWORD_HASH_SHA256" not in phase2_source
    assert "BIZPULSE_OPERATOR_ROTATION_ID" not in phase2_source
    assert "param operatorRotationEnabled bool = false" in main_source
    assert "param operatorRotationPasswordHash string = ''" in main_source
    assert "param operatorRotationExpectedHashFingerprint string = ''" in main_source
    assert "param operatorRotationId string = ''" in main_source
    assert "operatorRotationEnabled: operatorRotationEnabled" in main_source
    assert "operatorRotationPasswordHash: validatedOperatorRotationPasswordHash" in main_source
    assert "operatorRotationExpectedHashFingerprint" in param_file
    assert "operatorRotationId" in param_file
    assert "BIZPULSE_DEPLOY_OPERATOR_ROTATION_PASSWORD_HASH" in param_file

    rotation_job_source = app_source.split(
        "resource operatorRotationJob 'Microsoft.App/jobs@2024-03-01' = {", 1
    )[1]
    assert "secrets: operatorRotationJobSecrets" in rotation_job_source
    assert "value: operatorRotationEnabled ? operatorRotationPasswordHash : operatorPasswordHash" in app_source
    assert "operatorRotationPasswordHash" not in phase2_source


def test_rotation_stage_template_declares_only_the_manual_job() -> None:
    template = _compiled_bicep(OPERATOR_ROTATION_JOB_BICEP)
    source = OPERATOR_ROTATION_JOB_BICEP.read_text()
    types = _resource_types(template)

    assert types.count("Microsoft.App/jobs") == 1
    assert "Microsoft.App/containerApps" not in types
    assert "resource operatorRotationJob 'Microsoft.App/jobs@2024-03-01' = {" in source
    assert "resource app 'Microsoft.App/containerApps@" not in source
    assert "replicaRetryLimit: 0" in source
    assert "BIZPULSE_EXPECTED_OPERATOR_PASSWORD_HASH_SHA256" in source
    assert "BIZPULSE_OPERATOR_ROTATION_ID" in source


def test_checked_in_inert_parameters_compile_without_external_state() -> None:
    az = shutil.which("az")
    assert az is not None, "azure_cli_missing_for_local_bicep_compile"
    environment = dict(os.environ)
    for name in (
        "BIZPULSE_DEPLOY_POSTGRES_PASSWORD",
        "BIZPULSE_DEPLOY_OPERATOR_PASSWORD_HASH",
        "BIZPULSE_DEPLOY_SESSION_PEPPER",
    ):
        environment[name] = "local-inert-placeholder"
    environment.pop("BIZPULSE_DEPLOY_OPENAI_API_KEY", None)
    completed = subprocess.run(
        [
            az,
            "bicep",
            "build-params",
            "--file",
            str(PROJECT_ROOT / "infra/environments/demo.bicepparam"),
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
    assert parameters["applicationEnabled"]["value"] is False
    assert "openaiApiKey" not in parameters
    for name in (
        "openaiKeyVaultUrl",
        "openaiManagedIdentityClientId",
        "openaiManagedIdentityResourceId",
    ):
        assert parameters[name]["value"] == ""
