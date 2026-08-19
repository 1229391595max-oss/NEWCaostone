"""Compile Bicep and derive a value-safe deployed release projection."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from scripts.deployed_release_diagnostic_contract import (
    DeployedReleaseDiagnosticInvalid,
    unique_object,
)


PROJECTION_SCHEMA = "newcaostone.deployed-release-desired-projection.v1"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
ROLE_BY_CONTAINER = {
    "prepare": "prepare",
    "seed": "seed",
    "maintain-sessions": "session_maintenance",
    "maintain-storage": "storage_maintenance",
}
SCOPED_OPERATOR_ROTATION_JOB_NAME = (
    "[take(format('{0}-rotate-operator', parameters('namePrefix')), 32)]"
)
SCOPED_OPERATOR_ROTATION_CONTAINER = "operator-rotation"
SCOPED_OPERATOR_ROTATION_ENVIRONMENT_ID = (
    "[resourceId('Microsoft.App/managedEnvironments', "
    "take(format('{0}-env', parameters('namePrefix')), 60))]"
)
SCOPED_OPERATOR_ROTATION_ENVIRONMENT = (
    "[flatten(createArray(createArray("
    "createObject('name', 'BIZPULSE_RUNTIME_ENVIRONMENT', 'value', 'cloud'), "
    "createObject('name', 'BIZPULSE_DATABASE_URL', 'secretRef', 'database-url'), "
    "createObject('name', 'BIZPULSE_BLOB_ENDPOINT', 'value', "
    "parameters('blobEndpoint')), "
    "createObject('name', 'BIZPULSE_BLOB_CONTAINER', 'value', "
    "parameters('blobContainer')), "
    "createObject('name', 'BIZPULSE_BLOB_CONNECTION_STRING', 'secretRef', "
    "'blob-connection-string'), "
    "createObject('name', 'BIZPULSE_ALLOWED_ORIGIN', 'value', "
    "format('https://{0}.{1}', variables('appName'), "
    "reference(resourceId('Microsoft.App/managedEnvironments', "
    "take(format('{0}-env', parameters('namePrefix')), 60)), "
    "'2024-03-01').defaultDomain)), "
    "createObject('name', 'BIZPULSE_OPERATOR_PASSWORD_HASH', 'secretRef', "
    "'operator-password-hash'), "
    "createObject('name', 'BIZPULSE_SESSION_PEPPER', 'secretRef', "
    "'session-pepper')), createArray("
    "createObject('name', 'BIZPULSE_EXPECTED_OPERATOR_PASSWORD_HASH_SHA256', "
    "'value', if(parameters('operatorRotationEnabled'), "
    "parameters('operatorRotationExpectedHashFingerprint'), '')), "
    "createObject('name', 'BIZPULSE_OPERATOR_ROTATION_ID', 'value', "
    "if(parameters('operatorRotationEnabled'), parameters('operatorRotationId'), ''))"
    ")))]"
)
JOB_SPEC = {
    "prepare": {
        "trigger_type": "Manual",
        "replica_timeout": 900,
        "replica_retry_limit": 0,
        "manual": {"parallelism": 1, "replicaCompletionCount": 1},
        "schedule": None,
    },
    "seed": {
        "trigger_type": "Manual",
        "replica_timeout": 1800,
        "replica_retry_limit": 0,
        "manual": {"parallelism": 1, "replicaCompletionCount": 1},
        "schedule": None,
    },
    "session_maintenance": {
        "trigger_type": "Schedule",
        "replica_timeout": 300,
        "replica_retry_limit": 0,
        "manual": None,
        "schedule": {
            "cronExpression": "*/15 * * * *",
            "parallelism": 1,
            "replicaCompletionCount": 1,
        },
    },
    "storage_maintenance": {
        "trigger_type": "Schedule",
        "replica_timeout": 600,
        "replica_retry_limit": 0,
        "manual": None,
        "schedule": {
            "cronExpression": "0 * * * *",
            "parallelism": 1,
            "replicaCompletionCount": 1,
        },
    },
}
JOB_ENV_BINDINGS = {
    "BIZPULSE_ALLOWED_ORIGIN": "value",
    "BIZPULSE_BLOB_CONNECTION_STRING": "secretRef:blob-connection-string",
    "BIZPULSE_BLOB_CONTAINER": "value",
    "BIZPULSE_BLOB_ENDPOINT": "value",
    "BIZPULSE_DATABASE_URL": "secretRef:database-url",
    "BIZPULSE_OPERATOR_PASSWORD_HASH": "secretRef:operator-password-hash",
    "BIZPULSE_RUNTIME_ENVIRONMENT": "value",
    "BIZPULSE_SESSION_PEPPER": "secretRef:session-pepper",
}
SECRET_NAMES = {
    "blob-connection-string",
    "database-url",
    "operator-password-hash",
    "session-pepper",
}
SECRET_COMPILED_VALUES = {
    "database-url": "[parameters('databaseUrl')]",
    "blob-connection-string": (
        "[format('DefaultEndpointsProtocol=https;AccountName={0};AccountKey={1};"
        "EndpointSuffix={2}', parameters('storageAccountName'), "
        "listKeys(resourceId('Microsoft.Storage/storageAccounts', "
        "parameters('storageAccountName')), '2023-05-01').keys[0].value, "
        "environment().suffixes.storage)]"
    ),
    "operator-password-hash": "[parameters('operatorPasswordHash')]",
    "session-pepper": "[parameters('sessionPepper')]",
}
SCOPED_OPERATOR_ROTATION_SECRET_VALUES = {
    "blob-connection-string": SECRET_COMPILED_VALUES["blob-connection-string"],
    "database-url": SECRET_COMPILED_VALUES["database-url"],
    "operator-password-hash": (
        "[if(parameters('operatorRotationEnabled'), "
        "parameters('operatorRotationPasswordHash'), "
        "parameters('operatorPasswordHash'))]"
    ),
    "session-pepper": SECRET_COMPILED_VALUES["session-pepper"],
}
CONTAINER_RESOURCES = {"cpu": 0.5, "memory": "1Gi"}
COMPILED_CONTAINER_RESOURCES = {"cpu": "[json('0.5')]", "memory": "1Gi"}
APP_PROBES = [
    {
        "failureThreshold": 3,
        "httpGet": {"path": "/health/live", "port": 8000, "scheme": "HTTP"},
        "initialDelaySeconds": 15,
        "periodSeconds": 30,
        "timeoutSeconds": 5,
        "type": "Liveness",
    },
    {
        "failureThreshold": 3,
        "httpGet": {"path": "/health/ready", "port": 8000, "scheme": "HTTP"},
        "initialDelaySeconds": 10,
        "periodSeconds": 10,
        "timeoutSeconds": 5,
        "type": "Readiness",
    },
]
APP_VALUE_ENV_NAMES = {
    "APPLICATIONINSIGHTS_CONNECTION_STRING",
    "BIZPULSE_AI_CHAT_ENABLED",
    "BIZPULSE_AI_DAILY_ATTEMPT_LIMIT",
    "BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE",
    "BIZPULSE_AI_MAX_CONCURRENT_TURNS",
    "BIZPULSE_AI_MONTHLY_TOKEN_LIMIT",
    "BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE",
    "BIZPULSE_ALLOWED_ORIGIN",
    "BIZPULSE_BLOB_CONTAINER",
    "BIZPULSE_BLOB_ENDPOINT",
    "BIZPULSE_DEMO_SESSION_RATE_LIMIT_PER_HOUR",
    "BIZPULSE_OPENAI_MODEL",
    "BIZPULSE_OPENAI_REASONING_EFFORT",
    "BIZPULSE_RUNTIME_ENVIRONMENT",
}
APP_ENV_BINDINGS = {
    **{name: "value" for name in APP_VALUE_ENV_NAMES},
    **{
        name: binding
        for name, binding in JOB_ENV_BINDINGS.items()
        if binding.startswith("secretRef:")
    },
}


def _invalid() -> DeployedReleaseDiagnosticInvalid:
    return DeployedReleaseDiagnosticInvalid(
        "diagnostic_bicep_projection_invalid", "local", "local"
    )


def _one_container(resource: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        containers = resource["properties"]["template"]["containers"]
    except (KeyError, TypeError) as error:
        raise _invalid() from error
    if (
        not isinstance(containers, list)
        or len(containers) != 1
        or not isinstance(containers[0], Mapping)
    ):
        raise _invalid()
    return containers[0]


def _environment_bindings(container: Mapping[str, Any]) -> dict[str, str]:
    rows = container.get("env")
    if not isinstance(rows, list):
        raise _invalid()
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping) or set(row) not in (
            {"name", "value"},
            {"name", "secretRef"},
        ):
            raise _invalid()
        name = row.get("name")
        if not isinstance(name, str) or not name or name in result:
            raise _invalid()
        if "secretRef" in row:
            reference = row["secretRef"]
            if not isinstance(reference, str) or not reference:
                raise _invalid()
            result[name] = f"secretRef:{reference}"
        else:
            result[name] = "value"
    return result


def _resolve_job_arguments(
    arguments: object, continuation: Mapping[str, Any]
) -> list[str]:
    if not isinstance(arguments, list) or not all(
        isinstance(item, str) for item in arguments
    ):
        raise _invalid()
    release = continuation["release"]
    replacements = {
        "[parameters('syntheticManifestSha256')]": release["synthetic_manifest_sha256"],
        "[parameters('syntheticDatasetVersionId')]": release[
            "synthetic_dataset_version_id"
        ],
    }
    return [str(replacements.get(item, item)) for item in arguments]


def _compiled_secret_names(configuration: object) -> list[str]:
    if isinstance(configuration, Mapping):
        secrets = configuration.get("secrets")
        if not isinstance(secrets, list):
            raise _invalid()
        names: set[str] = set()
        for secret in secrets:
            if not isinstance(secret, Mapping) or set(secret) != {"name", "value"}:
                raise _invalid()
            name = secret.get("name")
            value = secret.get("value")
            if (
                not isinstance(name, str)
                or name in names
                or not isinstance(value, str)
                or value != SECRET_COMPILED_VALUES.get(name)
            ):
                raise _invalid()
            names.add(name)
        if names != SECRET_NAMES:
            raise _invalid()
        return sorted(names)

    if isinstance(configuration, str):
        names = {
            name
            for name in SECRET_NAMES
            if (f"'name', '{name}', 'value', {SECRET_COMPILED_VALUES[name][1:-1]}")
            in configuration
        }
        if names != SECRET_NAMES:
            raise _invalid()
        return sorted(names)

    raise _invalid()


def _container_resources(
    container: Mapping[str, Any], variables: Mapping[str, Any]
) -> dict[str, Any]:
    if (
        container.get("resources") != "[variables('jobResources')]"
        or variables.get("jobResources") != COMPILED_CONTAINER_RESOURCES
    ):
        raise _invalid()
    return dict(CONTAINER_RESOURCES)


def _validate_job_configuration(configuration: object, role: str) -> list[str]:
    spec = JOB_SPEC[role]
    secret_names = _compiled_secret_names(configuration)
    if isinstance(configuration, Mapping):
        expected_keys = {
            "manualTriggerConfig",
            "registries",
            "replicaRetryLimit",
            "replicaTimeout",
            "secrets",
            "triggerType",
        }
        if (
            set(configuration) != expected_keys
            or configuration.get("triggerType") != spec["trigger_type"]
            or configuration.get("replicaTimeout") != spec["replica_timeout"]
            or configuration.get("replicaRetryLimit") != spec["replica_retry_limit"]
            or configuration.get("manualTriggerConfig") != spec["manual"]
            or configuration.get("registries") != "[variables('registryConfiguration')]"
        ):
            raise _invalid()
        return secret_names

    assert isinstance(configuration, str)
    fragments = {
        f"'replicaTimeout', {spec['replica_timeout']}",
        f"'replicaRetryLimit', {spec['replica_retry_limit']}",
        "'triggerType', 'Schedule'",
        f"'cronExpression', '{spec['schedule']['cronExpression']}'",
        "'parallelism', 1",
        "'replicaCompletionCount', 1",
        "if(parameters('applicationEnabled')",
    }
    if not all(fragment in configuration for fragment in fragments):
        raise _invalid()
    return secret_names


def _job_projection(
    resource: Mapping[str, Any],
    continuation: Mapping[str, Any],
    variables: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    container = _one_container(resource)
    container_name = container.get("name")
    if not isinstance(container_name, str) or container_name not in ROLE_BY_CONTAINER:
        raise _invalid()
    role = ROLE_BY_CONTAINER[container_name]
    target = continuation["target"]
    release = continuation["release"]
    expected_job_names = {
        "prepare": target["prepare_job"],
        "seed": target["seed_job"],
        "session_maintenance": target["session_maintenance_job"],
        "storage_maintenance": target["storage_maintenance_job"],
    }
    candidate_image = (
        f"{target['registry_name']}.azurecr.io/{target['image_repository']}@"
        f"{release['candidate_image_digest']}"
    )
    expected_values = {
        "BIZPULSE_RUNTIME_ENVIRONMENT": "cloud",
        "BIZPULSE_BLOB_ENDPOINT": (
            f"https://{target['storage_account']}.blob.core.windows.net/"
        ),
        "BIZPULSE_BLOB_CONTAINER": "synthetic-demo",
        "BIZPULSE_ALLOWED_ORIGIN": target["public_url"],
    }
    environment_bindings = _environment_bindings(container)
    if environment_bindings != JOB_ENV_BINDINGS:
        raise _invalid()
    try:
        configuration = resource["properties"]["configuration"]
    except (KeyError, TypeError) as error:
        raise _invalid() from error
    spec = JOB_SPEC[role]
    expected_arguments = _resolve_job_arguments(container.get("args"), continuation)
    if (
        resource.get("name")
        != {
            "prepare": "[take(format('{0}-prepare', parameters('namePrefix')), 32)]",
            "seed": "[take(format('{0}-seed', parameters('namePrefix')), 32)]",
            "session_maintenance": "[take(format('{0}-sessions', parameters('namePrefix')), 32)]",
            "storage_maintenance": "[take(format('{0}-storage', parameters('namePrefix')), 32)]",
        }[role]
        or container.get("image") != "[parameters('containerImage')]"
        or container.get("command") != ["python"]
    ):
        raise _invalid()
    return role, {
        "arguments": expected_arguments,
        "command": ["python"],
        "container_name": container_name,
        "environment_bindings": environment_bindings,
        "expected_value_env": expected_values,
        "image": candidate_image,
        "job_name": expected_job_names[role],
        "manual_trigger_config": spec["manual"],
        "replica_retry_limit": spec["replica_retry_limit"],
        "replica_timeout": spec["replica_timeout"],
        "resources": _container_resources(container, variables),
        "schedule_trigger_config": spec["schedule"],
        "secret_names": _validate_job_configuration(configuration, role),
        "trigger_type": spec["trigger_type"],
    }


def _scoped_operator_rotation_environment_is_expected(environment: object) -> bool:
    return environment == SCOPED_OPERATOR_ROTATION_ENVIRONMENT


def _scoped_operator_rotation_configuration_is_expected(
    configuration: object,
) -> bool:
    if not isinstance(configuration, Mapping) or set(configuration) != {
        "manualTriggerConfig",
        "registries",
        "replicaRetryLimit",
        "replicaTimeout",
        "secrets",
        "triggerType",
    }:
        return False
    secrets = configuration.get("secrets")
    if not isinstance(secrets, list):
        return False
    secret_values: dict[str, str] = {}
    for secret in secrets:
        if not isinstance(secret, Mapping) or set(secret) != {"name", "value"}:
            return False
        name = secret.get("name")
        value = secret.get("value")
        if not isinstance(name, str) or not isinstance(value, str) or name in secret_values:
            return False
        secret_values[name] = value
    return (
        configuration.get("triggerType") == "Manual"
        and configuration.get("replicaTimeout") == 900
        and configuration.get("replicaRetryLimit") == 0
        and configuration.get("manualTriggerConfig")
        == {"parallelism": 1, "replicaCompletionCount": 1}
        and configuration.get("registries") == "[variables('registryConfiguration')]"
        and secret_values == SCOPED_OPERATOR_ROTATION_SECRET_VALUES
    )


def _is_scoped_operator_rotation_job(resource: Mapping[str, Any]) -> bool:
    container = _one_container(resource)
    try:
        properties = resource["properties"]
        identity = resource["identity"]
        configuration = properties["configuration"]
        template = properties["template"]
    except (KeyError, TypeError):
        return False
    if not all(isinstance(item, Mapping) for item in (properties, identity, template)):
        return False
    return (
        resource.get("apiVersion") == "2024-03-01"
        and resource.get("name") == SCOPED_OPERATOR_ROTATION_JOB_NAME
        and set(properties) == {"configuration", "environmentId", "template"}
        and properties.get("environmentId") == SCOPED_OPERATOR_ROTATION_ENVIRONMENT_ID
        and identity
        == {
            "type": "UserAssigned",
            "userAssignedIdentities": {
                "[format('{0}', parameters('registryIdentityResourceId'))]": {}
            },
        }
        and set(template) == {"containers"}
        and set(container) == {"args", "command", "env", "image", "name", "resources"}
        and container.get("name") == SCOPED_OPERATOR_ROTATION_CONTAINER
        and container.get("image") == "[parameters('containerImage')]"
        and container.get("command") == ["python"]
        and container.get("args") == ["scripts/rotate_operator_password.py"]
        and container.get("resources") == "[variables('jobResources')]"
        and _scoped_operator_rotation_environment_is_expected(container.get("env"))
        and _scoped_operator_rotation_configuration_is_expected(configuration)
    )


def _application_projection(
    resource: Mapping[str, Any],
    continuation: Mapping[str, Any],
    variables: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        properties = resource["properties"]
        configuration = properties["configuration"]
        ingress = configuration["ingress"]
        template = properties["template"]
        containers = template["containers"]
        scale = template["scale"]
        boundaries = continuation["boundaries"]
    except (KeyError, TypeError) as error:
        raise _invalid() from error
    if not all(
        isinstance(item, Mapping)
        for item in (properties, configuration, ingress, template, scale, boundaries)
    ):
        raise _invalid()
    if (
        resource.get("name") != "[variables('appName')]"
        or boundaries.get("ai_enabled") is not False
        or configuration.get("activeRevisionsMode") != "Single"
        or ingress
        != {
            "allowInsecure": False,
            "external": "[parameters('applicationEnabled')]",
            "targetPort": 8000,
            "traffic": [{"latestRevision": True, "weight": 100}],
            "transport": "auto",
        }
        or not isinstance(containers, list)
        or len(containers) != 1
        or not isinstance(containers[0], str)
        or scale
        != {
            "minReplicas": "[if(parameters('applicationEnabled'), 1, 0)]",
            "maxReplicas": 1,
        }
        or variables.get("jobResources") != COMPILED_CONTAINER_RESOURCES
        or variables.get("appProbes") != APP_PROBES
    ):
        raise _invalid()
    container_expression = containers[0]
    required_container_fragments = {
        "createObject('name', 'bizpulse', 'image', parameters('containerImage')",
        "'probes', variables('appProbes')",
        "'resources', variables('jobResources')",
        "if(parameters('applicationEnabled')",
    }
    for name, binding in APP_ENV_BINDINGS.items():
        if binding == "value":
            required_container_fragments.add(f"'name', '{name}', 'value',")
        else:
            required_container_fragments.add(
                f"'name', '{name}', 'secretRef', '{binding.removeprefix('secretRef:')}'"
            )
    if not all(
        fragment in container_expression for fragment in required_container_fragments
    ):
        raise _invalid()
    secret_expression = configuration.get("secrets")
    if not isinstance(secret_expression, str):
        raise _invalid()
    for name in SECRET_NAMES:
        expected_binding = (
            f"'name', '{name}', 'value', {SECRET_COMPILED_VALUES[name][1:-1]}"
        )
        if expected_binding not in secret_expression:
            raise _invalid()
    target = continuation["target"]
    candidate_image = (
        f"{target['registry_name']}.azurecr.io/{target['image_repository']}@"
        f"{continuation['release']['candidate_image_digest']}"
    )
    expected_values = {
        "BIZPULSE_RUNTIME_ENVIRONMENT": "cloud",
        "BIZPULSE_BLOB_ENDPOINT": (
            f"https://{target['storage_account']}.blob.core.windows.net/"
        ),
        "BIZPULSE_BLOB_CONTAINER": "synthetic-demo",
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
    return {
        "arguments": [],
        "command": [],
        "container_name": "bizpulse",
        "environment_bindings": dict(sorted(APP_ENV_BINDINGS.items())),
        "environment_id": (
            f"/subscriptions/{target['subscription_id']}/resourceGroups/"
            f"{target['resource_group']}/providers/Microsoft.App/"
            f"managedEnvironments/{target['environment']}"
        ),
        "expected_value_env": expected_values,
        "image": candidate_image,
        "ingress": {
            "allowInsecure": False,
            "external": True,
            "targetPort": 8000,
            "traffic": [{"latestRevision": True, "weight": 100}],
            "transport": "auto",
        },
        "probes": APP_PROBES,
        "resource_name": target["application"],
        "resources": dict(CONTAINER_RESOURCES),
        "revision_name": target["application_revision"],
        "scale": {"maxReplicas": 1, "minReplicas": 1},
        "secret_names": sorted(SECRET_NAMES),
    }


def compile_desired_projection(
    bicep_path: Path,
    continuation: Mapping[str, Any],
    *,
    continuation_sha256: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    if (
        not bicep_path.is_file()
        or SHA256_PATTERN.fullmatch(continuation_sha256) is None
    ):
        raise _invalid()
    try:
        completed = runner(
            [
                "az",
                "bicep",
                "build",
                "--file",
                str(bicep_path),
                "--stdout",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise _invalid() from error
    if completed.returncode != 0 or len(completed.stdout) > 2_000_000:
        raise _invalid()
    try:
        compiled = json.loads(completed.stdout, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, ValueError) as error:
        raise _invalid() from error
    resources = compiled.get("resources") if isinstance(compiled, dict) else None
    variables = compiled.get("variables") if isinstance(compiled, dict) else None
    if not isinstance(resources, list) or not isinstance(variables, Mapping):
        raise _invalid()
    jobs: dict[str, Any] = {}
    application: dict[str, Any] | None = None
    scoped_operator_rotation_job_found = False
    for resource in resources:
        if not isinstance(resource, Mapping):
            raise _invalid()
        if resource.get("type") == "Microsoft.App/jobs":
            if _is_scoped_operator_rotation_job(resource):
                if scoped_operator_rotation_job_found:
                    raise _invalid()
                scoped_operator_rotation_job_found = True
                continue
            role, projection = _job_projection(resource, continuation, variables)
            if role in jobs:
                raise _invalid()
            jobs[role] = projection
        elif resource.get("type") == "Microsoft.App/containerApps":
            if application is not None:
                raise _invalid()
            application = _application_projection(resource, continuation, variables)
    if set(jobs) != set(JOB_SPEC) or application is None:
        raise _invalid()
    return {
        "application": application,
        "continuation_sha256": continuation_sha256,
        "jobs": jobs,
        "schema_version": PROJECTION_SCHEMA,
    }
