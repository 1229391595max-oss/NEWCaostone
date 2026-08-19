"""Build a fail-closed Container Apps AI revision patch without secret values."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any
from uuid import UUID


_IMAGE_PATTERN = re.compile(
    r"[a-z0-9][a-z0-9-]{2,49}\.azurecr\.io/"
    r"[a-z0-9][a-z0-9._/-]{1,127}@sha256:[0-9a-f]{64}"
)
_REVISION_SUFFIX_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}[a-z0-9]")
_LOCATION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ]{1,62}[A-Za-z0-9]")
_IDENTITY_RESOURCE_ID_PATTERN = re.compile(
    r"/subscriptions/[0-9a-f-]{36}/resourceGroups/[A-Za-z0-9._()-]{1,90}/"
    r"providers/Microsoft\.ManagedIdentity/userAssignedIdentities/"
    r"[A-Za-z0-9._()-]{1,128}",
    re.IGNORECASE,
)
_VAULT_URL_PATTERN = re.compile(
    r"https://[a-z0-9][a-z0-9-]{1,22}[a-z0-9]\.vault\.azure\.net"
)

_SECRET_ENVIRONMENT = {
    "BIZPULSE_DATABASE_URL": "database-url",
    "BIZPULSE_BLOB_CONNECTION_STRING": "blob-connection-string",
    "BIZPULSE_OPERATOR_PASSWORD_HASH": "operator-password-hash",
    "BIZPULSE_SESSION_PEPPER": "session-pepper",
}
_BASE_VALUE_ENVIRONMENT = frozenset(
    {
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "BIZPULSE_ALLOWED_ORIGIN",
        "BIZPULSE_AI_CHAT_ENABLED",
        "BIZPULSE_AI_DAILY_ATTEMPT_LIMIT",
        "BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE",
        "BIZPULSE_AI_MAX_CONCURRENT_TURNS",
        "BIZPULSE_AI_MONTHLY_TOKEN_LIMIT",
        "BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE",
        "BIZPULSE_BLOB_CONTAINER",
        "BIZPULSE_BLOB_ENDPOINT",
        "BIZPULSE_DEMO_SESSION_RATE_LIMIT_PER_HOUR",
        "BIZPULSE_OPENAI_MODEL",
        "BIZPULSE_OPENAI_REASONING_EFFORT",
        "BIZPULSE_RUNTIME_ENVIRONMENT",
    }
)
_AI_BINDING_ENVIRONMENT = (
    "BIZPULSE_OPENAI_KEY_VAULT_URL",
    "BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME",
    "BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID",
)
_OPTIONAL_VALUE_ENVIRONMENT = frozenset(
    {"BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL", *_AI_BINDING_ENVIRONMENT}
)
_ALLOWED_VALUE_ENVIRONMENT = _BASE_VALUE_ENVIRONMENT | _OPTIONAL_VALUE_ENVIRONMENT
_MUTABLE_AI_ENVIRONMENT = frozenset(
    {
        "BIZPULSE_AI_CHAT_ENABLED",
        "BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL",
        *_AI_BINDING_ENVIRONMENT,
    }
)
_EXPECTED_PROBES = [
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
]
_EXPECTED_RESOURCES = {"cpu": 0.5, "memory": "1Gi"}
_EXPECTED_SCALE = {"minReplicas": 1, "maxReplicas": 1}
_AZURE_TEMPLATE_DEFAULTS = {
    "customMetricsSettings": None,
    "initContainers": None,
    "serviceBinds": None,
    "terminationGracePeriodSeconds": None,
    "volumes": None,
}
_AZURE_SCALE_DEFAULTS = {
    "cooldownPeriod": 300,
    "pollingInterval": 30,
    "rules": None,
}
_AZURE_CONTAINER_DEFAULTS = {"imageType": "ContainerImage"}
_AZURE_RESOURCE_DEFAULTS = {"ephemeralStorage": "2Gi"}


class AzureAIRevisionInvalid(ValueError):
    """The source projection or requested AI binding is not allowlisted."""


def _projection_invalid() -> AzureAIRevisionInvalid:
    return AzureAIRevisionInvalid("ai_revision_projection_invalid")


def _binding_invalid() -> AzureAIRevisionInvalid:
    return AzureAIRevisionInvalid("ai_revision_binding_invalid")


def _canonical_uuid4(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
    except ValueError:
        return False
    return str(parsed) == value and parsed.version == 4


def _valid_identity_id(value: object) -> bool:
    if not isinstance(value, str) or _IDENTITY_RESOURCE_ID_PATTERN.fullmatch(value) is None:
        return False
    subscription_id = value.split("/", 3)[2].lower()
    try:
        parsed = UUID(subscription_id)
    except ValueError:
        return False
    return str(parsed) == subscription_id


def _validate_environment(rows: object) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        raise _projection_invalid()
    validated: list[dict[str, str]] = []
    names: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise _projection_invalid()
        name = raw.get("name")
        if not isinstance(name, str) or name in names:
            raise _projection_invalid()
        names.add(name)
        if name in _SECRET_ENVIRONMENT:
            if raw != {"name": name, "secretRef": _SECRET_ENVIRONMENT[name]}:
                raise _projection_invalid()
        elif name in _ALLOWED_VALUE_ENVIRONMENT:
            value = raw.get("value")
            if (
                set(raw) != {"name", "value"}
                or not isinstance(value, str)
                or not 1 <= len(value) <= 4096
            ):
                raise _projection_invalid()
        else:
            raise _projection_invalid()
        validated.append({str(key): str(value) for key, value in raw.items()})

    required = _BASE_VALUE_ENVIRONMENT | set(_SECRET_ENVIRONMENT)
    if not required.issubset(names):
        raise _projection_invalid()
    if names - required - _OPTIONAL_VALUE_ENVIRONMENT:
        raise _projection_invalid()
    by_name = {row["name"]: row for row in validated}
    if by_name["BIZPULSE_RUNTIME_ENVIRONMENT"].get("value") != "cloud":
        raise _projection_invalid()
    if by_name["BIZPULSE_AI_CHAT_ENABLED"].get("value") not in {
        "true",
        "false",
    }:
        raise _projection_invalid()
    if by_name["BIZPULSE_OPENAI_MODEL"].get("value") != (
        "gpt-5.4-nano-2026-03-17"
    ):
        raise _projection_invalid()
    if by_name["BIZPULSE_OPENAI_REASONING_EFFORT"].get("value") != "low":
        raise _projection_invalid()
    return validated


def _validate_template(template: object) -> dict[str, Any]:
    if not isinstance(template, dict) or set(template) != {
        "revisionSuffix",
        "containers",
        "scale",
    }:
        raise _projection_invalid()
    revision_suffix = template.get("revisionSuffix")
    if (
        not isinstance(revision_suffix, str)
        or _REVISION_SUFFIX_PATTERN.fullmatch(revision_suffix) is None
        or template.get("scale") != _EXPECTED_SCALE
    ):
        raise _projection_invalid()
    containers = template.get("containers")
    if not isinstance(containers, list) or len(containers) != 1:
        raise _projection_invalid()
    container = containers[0]
    if not isinstance(container, dict) or set(container) != {
        "name",
        "image",
        "env",
        "probes",
        "resources",
    }:
        raise _projection_invalid()
    if (
        container.get("name") != "bizpulse"
        or not isinstance(container.get("image"), str)
        or _IMAGE_PATTERN.fullmatch(container["image"]) is None
        or container.get("probes") != _EXPECTED_PROBES
        or container.get("resources") != _EXPECTED_RESOURCES
    ):
        raise _projection_invalid()
    validated = deepcopy(template)
    validated["containers"][0]["env"] = _validate_environment(container.get("env"))
    return validated


def canonicalize_azure_template_readback(template: object) -> dict[str, Any]:
    """Project an Azure readback to the exact non-secret patch template shape."""

    canonical_keys = {"revisionSuffix", "containers", "scale"}
    if (
        not isinstance(template, dict)
        or set(template) != canonical_keys | set(_AZURE_TEMPLATE_DEFAULTS)
        or any(
            template.get(name) != value
            for name, value in _AZURE_TEMPLATE_DEFAULTS.items()
        )
    ):
        raise _projection_invalid()
    scale = template.get("scale")
    if (
        not isinstance(scale, dict)
        or set(scale) != set(_EXPECTED_SCALE) | set(_AZURE_SCALE_DEFAULTS)
        or any(
            scale.get(name) != value
            for name, value in _AZURE_SCALE_DEFAULTS.items()
        )
    ):
        raise _projection_invalid()
    containers = template.get("containers")
    if not isinstance(containers, list) or len(containers) != 1:
        raise _projection_invalid()
    container = containers[0]
    canonical_container_keys = {"name", "image", "env", "probes", "resources"}
    if (
        not isinstance(container, dict)
        or set(container)
        != canonical_container_keys | set(_AZURE_CONTAINER_DEFAULTS)
        or any(
            container.get(name) != value
            for name, value in _AZURE_CONTAINER_DEFAULTS.items()
        )
    ):
        raise _projection_invalid()
    resources = container.get("resources")
    expected_resource_keys = set(_EXPECTED_RESOURCES)
    observed_resource_keys = set(resources) if isinstance(resources, dict) else set()
    has_allowed_resource_keys = (
        observed_resource_keys == expected_resource_keys
        or observed_resource_keys
        == expected_resource_keys | set(_AZURE_RESOURCE_DEFAULTS)
    )
    if (
        not isinstance(resources, dict)
        or not has_allowed_resource_keys
        or any(
            name in resources and resources[name] != value
            for name, value in _AZURE_RESOURCE_DEFAULTS.items()
        )
    ):
        raise _projection_invalid()
    canonical_container = {
        name: deepcopy(container[name])
        for name in canonical_container_keys - {"resources"}
    }
    canonical_container["resources"] = {
        name: deepcopy(resources[name]) for name in _EXPECTED_RESOURCES
    }
    canonical = {
        "revisionSuffix": template.get("revisionSuffix"),
        "containers": [canonical_container],
        "scale": {name: deepcopy(scale[name]) for name in _EXPECTED_SCALE},
    }
    return _validate_template(canonical)


def _validate_projection(current: object) -> dict[str, Any]:
    if not isinstance(current, dict) or set(current) != {
        "location",
        "identity",
        "properties",
    }:
        raise _projection_invalid()
    location = current.get("location")
    if not isinstance(location, str) or _LOCATION_PATTERN.fullmatch(location) is None:
        raise _projection_invalid()
    identity = current.get("identity")
    if not isinstance(identity, dict) or set(identity) != {
        "type",
        "userAssignedIdentities",
    }:
        raise _projection_invalid()
    assigned = identity.get("userAssignedIdentities")
    identity_ids = (
        [str(identity_id).casefold() for identity_id in assigned]
        if isinstance(assigned, dict)
        else []
    )
    if (
        identity.get("type") != "UserAssigned"
        or not isinstance(assigned, dict)
        or not assigned
        or len(identity_ids) != len(set(identity_ids))
        or any(not _valid_identity_id(key) or value != {} for key, value in assigned.items())
    ):
        raise _projection_invalid()
    properties = current.get("properties")
    if not isinstance(properties, dict) or set(properties) != {"template"}:
        raise _projection_invalid()
    validated = deepcopy(current)
    validated["properties"]["template"] = _validate_template(
        properties.get("template")
    )
    return validated


def build_ai_revision_patch(
    current: object,
    *,
    enabled: bool,
    candidate_image: str,
    revision_suffix: str,
    ai_identity_resource_id: str,
    vault_url: str | None = None,
    secret_name: str | None = None,
    managed_identity_client_id: str | None = None,
    budget_failure_rehearsal: bool = False,
) -> dict[str, Any]:
    """Return the exact nonsecret identity and template patch for one revision."""

    if (
        not isinstance(enabled, bool)
        or not isinstance(candidate_image, str)
        or _IMAGE_PATTERN.fullmatch(candidate_image) is None
        or not isinstance(revision_suffix, str)
        or _REVISION_SUFFIX_PATTERN.fullmatch(revision_suffix) is None
        or not _valid_identity_id(ai_identity_resource_id)
        or not isinstance(budget_failure_rehearsal, bool)
    ):
        raise _binding_invalid()
    if enabled:
        if (
            not isinstance(vault_url, str)
            or _VAULT_URL_PATTERN.fullmatch(vault_url) is None
            or secret_name != "openai-api-key"
            or not _canonical_uuid4(managed_identity_client_id)
        ):
            raise _binding_invalid()
    elif (
        vault_url is not None
        or secret_name is not None
        or managed_identity_client_id is not None
        or budget_failure_rehearsal
    ):
        raise _binding_invalid()

    validated = _validate_projection(current)
    identity = validated["identity"]
    assigned = identity["userAssignedIdentities"]
    matching_identity_id = next(
        (
            identity_id
            for identity_id in assigned
            if identity_id.casefold() == ai_identity_resource_id.casefold()
        ),
        None,
    )
    if enabled:
        assigned[matching_identity_id or ai_identity_resource_id] = {}
    else:
        if matching_identity_id is not None:
            assigned[matching_identity_id] = None
        if not any(value == {} for value in assigned.values()):
            raise _projection_invalid()

    template = validated["properties"]["template"]
    container = template["containers"][0]
    source_environment = container["env"]
    environment: list[dict[str, str]] = []
    for row in source_environment:
        name = row["name"]
        if name in _MUTABLE_AI_ENVIRONMENT:
            if name == "BIZPULSE_AI_CHAT_ENABLED":
                environment.append(
                    {
                        "name": "BIZPULSE_AI_CHAT_ENABLED",
                        "value": str(enabled).lower(),
                    }
                )
                if enabled and budget_failure_rehearsal:
                    environment.append(
                        {
                            "name": "BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL",
                            "value": "true",
                        }
                    )
                if enabled:
                    environment.extend(
                        [
                            {
                                "name": "BIZPULSE_OPENAI_KEY_VAULT_URL",
                                "value": vault_url,
                            },
                            {
                                "name": "BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME",
                                "value": secret_name,
                            },
                            {
                                "name": (
                                    "BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID"
                                ),
                                "value": managed_identity_client_id,
                            },
                        ]
                    )
            continue
        environment.append(row)

    container["image"] = candidate_image
    container["env"] = environment
    template["revisionSuffix"] = revision_suffix
    return {
        "location": validated["location"],
        "identity": identity,
        "properties": {"template": template},
    }


def canonicalize_ai_revision_patch_target(patch: object) -> dict[str, Any]:
    """Remove explicit identity-deletion markers from a desired readback."""

    if not isinstance(patch, dict):
        raise _projection_invalid()
    target = deepcopy(patch)
    try:
        assigned = target["identity"]["userAssignedIdentities"]
    except (KeyError, TypeError) as error:
        raise _projection_invalid() from error
    if not isinstance(assigned, dict) or not assigned:
        raise _projection_invalid()
    for identity_id, value in list(assigned.items()):
        if not _valid_identity_id(identity_id) or value not in ({}, None):
            raise _projection_invalid()
        if value is None:
            assigned.pop(identity_id)
    return _validate_projection(target)
