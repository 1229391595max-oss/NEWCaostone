from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.azure_ai_revision import (
    AzureAIRevisionInvalid,
    build_ai_revision_patch,
    canonicalize_ai_revision_patch_target,
    canonicalize_azure_template_readback,
)


REGISTRY_IDENTITY_ID = (
    "/subscriptions/00000000-0000-4000-8000-000000000001/"
    "resourceGroups/rg-demo/providers/Microsoft.ManagedIdentity/"
    "userAssignedIdentities/demo-registry"
)
AI_IDENTITY_ID = (
    "/subscriptions/00000000-0000-4000-8000-000000000001/"
    "resourceGroups/rg-demo/providers/Microsoft.ManagedIdentity/"
    "userAssignedIdentities/demo-ai-identity"
)
IMAGE = "demo.azurecr.io/bizpulse@sha256:" + ("a" * 64)
NEXT_IMAGE = "demo.azurecr.io/bizpulse@sha256:" + ("b" * 64)


def _current_projection() -> dict[str, object]:
    return {
        "location": "Central US",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {REGISTRY_IDENTITY_ID: {}},
        },
        "properties": {
            "template": {
                "revisionSuffix": "previous-a123456",
                "containers": [
                    {
                        "name": "bizpulse",
                        "image": IMAGE,
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
                                "value": "https://storage.blob.core.windows.net",
                            },
                            {
                                "name": "BIZPULSE_BLOB_CONTAINER",
                                "value": "bizpulse",
                            },
                            {
                                "name": "BIZPULSE_BLOB_CONNECTION_STRING",
                                "secretRef": "blob-connection-string",
                            },
                            {
                                "name": "BIZPULSE_ALLOWED_ORIGIN",
                                "value": "https://demo.example.test",
                            },
                            {
                                "name": "BIZPULSE_OPERATOR_PASSWORD_HASH",
                                "secretRef": "operator-password-hash",
                            },
                            {
                                "name": "BIZPULSE_SESSION_PEPPER",
                                "secretRef": "session-pepper",
                            },
                            {
                                "name": "BIZPULSE_AI_CHAT_ENABLED",
                                "value": "false",
                            },
                            {
                                "name": "BIZPULSE_AI_DAILY_ATTEMPT_LIMIT",
                                "value": "40",
                            },
                            {
                                "name": "BIZPULSE_AI_MONTHLY_TOKEN_LIMIT",
                                "value": "50000",
                            },
                            {
                                "name": "BIZPULSE_AI_MAX_CONCURRENT_TURNS",
                                "value": "1",
                            },
                            {
                                "name": (
                                    "BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE"
                                ),
                                "value": "4",
                            },
                            {
                                "name": (
                                    "BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE"
                                ),
                                "value": "10",
                            },
                            {
                                "name": "BIZPULSE_DEMO_SESSION_RATE_LIMIT_PER_HOUR",
                                "value": "20",
                            },
                            {
                                "name": "BIZPULSE_OPENAI_MODEL",
                                "value": "gpt-5.4-nano-2026-03-17",
                            },
                            {
                                "name": "BIZPULSE_OPENAI_REASONING_EFFORT",
                                "value": "low",
                            },
                            {
                                "name": "APPLICATIONINSIGHTS_CONNECTION_STRING",
                                "value": "InstrumentationKey=redacted",
                            },
                        ],
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


def _env(patch: dict[str, object]) -> dict[str, dict[str, object]]:
    properties = patch["properties"]
    assert isinstance(properties, dict)
    template = properties["template"]
    assert isinstance(template, dict)
    containers = template["containers"]
    assert isinstance(containers, list)
    container = containers[0]
    assert isinstance(container, dict)
    rows = container["env"]
    assert isinstance(rows, list)
    return {str(row["name"]): row for row in rows if isinstance(row, dict)}


def _azure_readback_template() -> dict[str, object]:
    properties = _current_projection()["properties"]
    assert isinstance(properties, dict)
    canonical = properties["template"]
    assert isinstance(canonical, dict)
    raw = deepcopy(canonical)
    raw.update(
        {
            "customMetricsSettings": None,
            "initContainers": None,
            "serviceBinds": None,
            "terminationGracePeriodSeconds": None,
            "volumes": None,
        }
    )
    scale = raw["scale"]
    assert isinstance(scale, dict)
    scale.update(
        {"cooldownPeriod": 300, "pollingInterval": 30, "rules": None}
    )
    containers = raw["containers"]
    assert isinstance(containers, list)
    container = containers[0]
    assert isinstance(container, dict)
    container["imageType"] = "ContainerImage"
    return raw


def test_canonical_readback_strips_only_observed_azure_defaults() -> None:
    raw = _azure_readback_template()
    properties = _current_projection()["properties"]
    assert isinstance(properties, dict)

    assert canonicalize_azure_template_readback(raw) == properties["template"]


def test_canonical_readback_strips_exact_azure_ephemeral_storage_default() -> None:
    raw = _azure_readback_template()
    containers = raw["containers"]
    assert isinstance(containers, list)
    container = containers[0]
    assert isinstance(container, dict)
    resources = container["resources"]
    assert isinstance(resources, dict)
    resources["ephemeralStorage"] = "2Gi"
    properties = _current_projection()["properties"]
    assert isinstance(properties, dict)

    assert canonicalize_azure_template_readback(raw) == properties["template"]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload["containers"][0].update({"imageType": "Unknown"}),
        lambda payload: payload["scale"].update({"cooldownPeriod": 301}),
        lambda payload: payload["scale"].update({"pollingInterval": 29}),
        lambda payload: payload["scale"].update({"rules": []}),
        lambda payload: payload.update({"terminationGracePeriodSeconds": 30}),
        lambda payload: payload["containers"][0].pop("image"),
        lambda payload: payload["containers"].append(
            deepcopy(payload["containers"][0])
        ),
        lambda payload: payload.update({"unrecognizedProviderField": None}),
    ],
)
def test_canonical_readback_rejects_nondefault_or_unknown_fields(mutator) -> None:
    raw = _azure_readback_template()
    mutator(raw)

    with pytest.raises(AzureAIRevisionInvalid, match="ai_revision_projection_invalid"):
        canonicalize_azure_template_readback(raw)


def test_enabled_patch_is_narrow_nonsecret_and_preserves_runtime_anchors() -> None:
    current = _current_projection()
    before = deepcopy(current)

    patch = build_ai_revision_patch(
        current,
        enabled=True,
        candidate_image=NEXT_IMAGE,
        revision_suffix="ai-enable-b123456",
        ai_identity_resource_id=AI_IDENTITY_ID,
        vault_url="https://demo-ai-kv.vault.azure.net",
        secret_name="openai-api-key",
        managed_identity_client_id="10000000-0000-4000-8000-000000000002",
    )

    assert current == before
    assert set(patch) == {"location", "identity", "properties"}
    assert set(patch["properties"]) == {"template"}
    assert "configuration" not in patch["properties"]
    identity = patch["identity"]
    assert identity == {
        "type": "UserAssigned",
        "userAssignedIdentities": {
            REGISTRY_IDENTITY_ID: {},
            AI_IDENTITY_ID: {},
        },
    }
    template = patch["properties"]["template"]
    assert template["revisionSuffix"] == "ai-enable-b123456"
    assert template["containers"][0]["image"] == NEXT_IMAGE
    assert template["containers"][0]["probes"] == before["properties"][
        "template"
    ]["containers"][0]["probes"]
    assert template["containers"][0]["resources"] == {
        "cpu": 0.5,
        "memory": "1Gi",
    }
    assert template["scale"] == {"minReplicas": 1, "maxReplicas": 1}

    env = _env(patch)
    assert env["BIZPULSE_AI_CHAT_ENABLED"] == {
        "name": "BIZPULSE_AI_CHAT_ENABLED",
        "value": "true",
    }
    assert env["BIZPULSE_OPENAI_KEY_VAULT_URL"]["value"] == (
        "https://demo-ai-kv.vault.azure.net"
    )
    assert env["BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME"]["value"] == (
        "openai-api-key"
    )
    assert env["BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID"]["value"] == (
        "10000000-0000-4000-8000-000000000002"
    )
    assert env["BIZPULSE_DATABASE_URL"] == {
        "name": "BIZPULSE_DATABASE_URL",
        "secretRef": "database-url",
    }
    serialized = repr(patch)
    assert "OPENAI_API_KEY" not in serialized
    assert "OPENAI_BASE_URL" not in serialized
    assert "openai-api-key':" not in serialized


def test_disabled_patch_removes_only_the_ai_binding_and_sets_false() -> None:
    enabled = build_ai_revision_patch(
        _current_projection(),
        enabled=True,
        candidate_image=NEXT_IMAGE,
        revision_suffix="ai-enable-b123456",
        ai_identity_resource_id=AI_IDENTITY_ID,
        vault_url="https://demo-ai-kv.vault.azure.net",
        secret_name="openai-api-key",
        managed_identity_client_id="10000000-0000-4000-8000-000000000002",
        budget_failure_rehearsal=True,
    )

    recovered = build_ai_revision_patch(
        enabled,
        enabled=False,
        candidate_image=NEXT_IMAGE,
        revision_suffix="ai-disable-b123456",
        ai_identity_resource_id=AI_IDENTITY_ID,
    )

    identities = recovered["identity"]["userAssignedIdentities"]
    assert identities == {
        REGISTRY_IDENTITY_ID: {},
        AI_IDENTITY_ID: None,
    }
    target = canonicalize_ai_revision_patch_target(recovered)
    assert target["identity"]["userAssignedIdentities"] == {
        REGISTRY_IDENTITY_ID: {}
    }
    env = _env(recovered)
    assert env["BIZPULSE_AI_CHAT_ENABLED"]["value"] == "false"
    assert "BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL" not in env
    assert "BIZPULSE_OPENAI_KEY_VAULT_URL" not in env
    assert "BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME" not in env
    assert "BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID" not in env


def test_disabled_patch_matches_azure_normalized_identity_id_case() -> None:
    current = _current_projection()
    assigned = current["identity"]["userAssignedIdentities"]
    normalized_registry = REGISTRY_IDENTITY_ID.replace(
        "/resourceGroups/", "/resourcegroups/"
    )
    normalized_ai = AI_IDENTITY_ID.replace(
        "/resourceGroups/", "/resourcegroups/"
    )
    assigned.clear()
    assigned.update({normalized_registry: {}, normalized_ai: {}})

    patch = build_ai_revision_patch(
        current,
        enabled=False,
        candidate_image=NEXT_IMAGE,
        revision_suffix="ai-disable-b123456",
        ai_identity_resource_id=AI_IDENTITY_ID,
    )

    assert patch["identity"]["userAssignedIdentities"] == {
        normalized_registry: {},
        normalized_ai: None,
    }


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload["properties"].update(
            {"configuration": {"secrets": [{"name": "database-url"}]}}
        ),
        lambda payload: payload["properties"]["template"]["containers"][0][
            "env"
        ].append({"name": "UNREVIEWED_SETTING", "value": "true"}),
        lambda payload: payload["properties"]["template"]["containers"][0][
            "env"
        ].append({"name": "BIZPULSE_AI_CHAT_ENABLED", "value": "true"}),
        lambda payload: payload["properties"]["template"]["containers"][0][
            "env"
        ].append({"name": "OPENAI_API_KEY", "value": "must-not-pass"}),
        lambda payload: payload["properties"]["template"]["containers"][0][
            "env"
        ].append({"name": "OPENAI_BASE_URL", "value": "https://evil.test"}),
        lambda payload: payload["properties"]["template"]["containers"][0][
            "env"
        ].append({"name": "BIZPULSE_DATABASE_URL", "value": "literal"}),
        lambda payload: payload["identity"]["userAssignedIdentities"].update(
            {AI_IDENTITY_ID: {"clientId": "unexpected"}}
        ),
        lambda payload: payload["properties"]["template"].pop("scale"),
    ],
)
def test_current_projection_rejects_expansion_or_secret_material(mutator) -> None:
    payload = _current_projection()
    mutator(payload)

    with pytest.raises(AzureAIRevisionInvalid, match="ai_revision_projection_invalid"):
        build_ai_revision_patch(
            payload,
            enabled=True,
            candidate_image=NEXT_IMAGE,
            revision_suffix="ai-enable-b123456",
            ai_identity_resource_id=AI_IDENTITY_ID,
            vault_url="https://demo-ai-kv.vault.azure.net",
            secret_name="openai-api-key",
            managed_identity_client_id=(
                "10000000-0000-4000-8000-000000000002"
            ),
        )


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("candidate_image", "demo.azurecr.io/bizpulse:latest"),
        ("revision_suffix", "Unsafe_Suffix"),
        ("vault_url", "https://evil.example.test/"),
        ("secret_name", "another-secret"),
        ("managed_identity_client_id", "not-a-uuid"),
    ],
)
def test_enabled_binding_rejects_unpinned_or_noncanonical_values(
    override: str,
    value: str,
) -> None:
    arguments = {
        "enabled": True,
        "candidate_image": NEXT_IMAGE,
        "revision_suffix": "ai-enable-b123456",
        "ai_identity_resource_id": AI_IDENTITY_ID,
        "vault_url": "https://demo-ai-kv.vault.azure.net",
        "secret_name": "openai-api-key",
        "managed_identity_client_id": (
            "10000000-0000-4000-8000-000000000002"
        ),
    }
    arguments[override] = value

    with pytest.raises(AzureAIRevisionInvalid, match="ai_revision_binding_invalid"):
        build_ai_revision_patch(_current_projection(), **arguments)
