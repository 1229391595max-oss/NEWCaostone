from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from uuid import UUID, uuid5

import pytest

import scripts.azure_ai_enablement_actions as azure_actions
from scripts.ai_enablement_contract import contract_template
from scripts.azure_arm_lro import ARMResponse
from scripts.azure_ai_reconciliation import PendingAITransition
from scripts.azure_ai_enablement_actions import (
    AzureAIEnablementActionInvalid,
    AzureAIEnablementActions,
    provider_price_preflight,
    read_sanitized_azure_authority,
)
from scripts.azure_ai_revision import build_ai_revision_patch


SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"
APP_RESOURCE_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-bizpulse-centralus/"
    "providers/Microsoft.App/containerApps/newcaostone-demo-app"
)
APP_URL = (
    f"https://management.azure.com{APP_RESOURCE_ID}?api-version=2025-01-01"
)
TENANT = "22222222-2222-4222-8222-222222222222"
PACKAGE_SHA256 = "3" * 64
HEAD = "4" * 40
TREE = "5" * 40
ROLLBACK_DIGEST = "7" * 64
ROLLBACK_IMAGE = (
    f"sellernorthbpacr.azurecr.io/bizpulse@sha256:{ROLLBACK_DIGEST}"
)
ROLLBACK_REVISION = "newcaostone-demo-app--713a6984d4a0"
REGISTRY_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-bizpulse-centralus/"
    "providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
    "newcaostone-demo-registry"
)
AI_IDENTITY = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-bizpulse-centralus/"
    "providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
    "newcaostone-ai-identity"
)
AI_CLIENT_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
AI_PRINCIPAL_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
VAULT_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-bizpulse-centralus/"
    "providers/Microsoft.KeyVault/vaults/newcaostone-ai-kv"
)
SECRET_ID = f"{VAULT_ID}/secrets/openai-api-key"
SECRETS_USER_ROLE_ID = (
    f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.Authorization/"
    "roleDefinitions/4633458b-17de-408a-b874-0445c86b69e6"
)
SECRETS_OFFICER_ROLE_ID = (
    f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.Authorization/"
    "roleDefinitions/b86a8fe4-44ce-4948-aee5-eccb2c155cd7"
)
_BICEP_GUID_NAMESPACE = UUID("11fb06fb-712d-4ddd-98c7-e71bbd588830")


def _bicep_guid(*values: str) -> str:
    return str(uuid5(_BICEP_GUID_NAMESPACE, "-".join(values)))


LEGACY_ASSIGNMENT_ID = (
    f"{VAULT_ID}/providers/Microsoft.Authorization/roleAssignments/"
    f"{_bicep_guid(VAULT_ID, AI_IDENTITY, SECRETS_USER_ROLE_ID)}"
)
OFFICER_ASSIGNMENT_ID = (
    f"{SECRET_ID}/providers/Microsoft.Authorization/roleAssignments/"
    f"{_bicep_guid(SECRET_ID, AI_IDENTITY, 'admin-ai-secret-officer')}"
)
WORKSPACE_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-bizpulse-centralus/"
    "providers/Microsoft.OperationalInsights/workspaces/newcaostone-demo-logs"
)
AI_RESOURCE_TAGS = {
    "application": "newcaostone",
    "component": "ai-enablement",
    "data_classification": "credential",
    "environment": "demo",
    "production_ready": "false",
}


def test_apply_patch_waits_for_arm_operation_before_acknowledgement() -> None:
    app_resource_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-bizpulse-centralus/"
        "providers/Microsoft.App/containerApps/newcaostone-demo-app"
    )
    operation_url = (
        f"https://management.azure.com/subscriptions/{SUBSCRIPTION}/providers/"
        "Microsoft.App/locations/centralus/operations/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        "?api-version=2025-01-01"
    )
    calls: list[tuple[str, str]] = []
    responses = iter(
        (
            ARMResponse(
                status_code=202,
                headers={"Azure-AsyncOperation": operation_url},
                payload={},
            ),
            ARMResponse(
                status_code=200,
                headers={},
                payload={
                    "id": APP_RESOURCE_ID,
                    "provisioningState": "Succeeded",
                },
            ),
        )
    )
    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        monotonic=lambda: 0.0,
        sleeper=lambda _seconds: None,
        arm_requester=lambda method, url, _body: calls.append((method, url))
        or next(responses),
    )

    assert actions._apply_patch_azure(
        {"location": "Central US"},
        revision_suffix="ai-off-33333333-ccccccc",
    ) == "accepted"
    assert calls == [
        (
            "PATCH",
            f"https://management.azure.com{app_resource_id}?api-version=2025-01-01",
        ),
        ("GET", APP_URL),
    ]


def test_arm_requester_disables_ambient_proxy_and_redirect_handling(monkeypatch) -> None:
    events: list[object] = []

    class FakeCredential:
        def __init__(self, *, process_timeout: int) -> None:
            assert process_timeout == 30

        def get_token(self, scope: str):
            assert scope == "https://management.azure.com/.default"
            return type("Token", (), {"token": "test-access-token"})()

    class FakeResponse:
        status_code = 202
        headers = {"Retry-After": "5", "Untrusted": "discard"}
        content = b""

    class FakeSession:
        def __init__(self) -> None:
            self.trust_env = True
            events.append("session")

        def request(self, method, url, **kwargs):
            events.append((method, url, kwargs))
            assert self.trust_env is False
            assert kwargs["allow_redirects"] is False
            return FakeResponse()

        def close(self) -> None:
            events.append("closed")

    monkeypatch.setattr(azure_actions, "AzureCliCredential", FakeCredential)
    monkeypatch.setattr(azure_actions.requests, "Session", FakeSession)
    monkeypatch.setattr(
        azure_actions.requests,
        "request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError),
    )
    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        monotonic=lambda: 5.0,
    )
    actions._arm_operation_deadline = 35.0

    response = actions._request_arm(
        "PATCH",
        "https://management.azure.com/subscriptions/example",
        {"location": "Central US"},
    )

    assert response == ARMResponse(
        status_code=202,
        headers={"Retry-After": "5"},
        payload={},
    )
    request = next(event for event in events if isinstance(event, tuple))
    assert request[2]["timeout"] == 30.0
    assert events[-1] == "closed"


def test_arm_requester_projects_only_resource_id_and_provisioning_state(
    monkeypatch,
) -> None:
    class FakeCredential:
        def __init__(self, *, process_timeout: int) -> None:
            assert process_timeout == 30

        def get_token(self, scope: str):
            assert scope == "https://management.azure.com/.default"
            return type("Token", (), {"token": "test-access-token"})()

    class FakeResponse:
        status_code = 200
        headers = {"Untrusted": "discard"}
        content = b"present"

        @staticmethod
        def json():
            return {
                "id": APP_RESOURCE_ID,
                "properties": {
                    "provisioningState": "Succeeded",
                    "configuration": {"secrets": [{"value": "discard"}]},
                },
                "tags": {"discard": "discard"},
            }

    class FakeSession:
        trust_env = True

        def request(self, _method, _url, **_kwargs):
            assert self.trust_env is False
            return FakeResponse()

        def close(self) -> None:
            return None

    monkeypatch.setattr(azure_actions, "AzureCliCredential", FakeCredential)
    monkeypatch.setattr(azure_actions.requests, "Session", FakeSession)
    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        monotonic=lambda: 5.0,
    )
    actions._arm_operation_deadline = 35.0

    response = actions._request_arm("GET", APP_URL, None)

    assert response == ARMResponse(
        status_code=200,
        headers={},
        payload={
            "id": APP_RESOURCE_ID,
            "provisioningState": "Succeeded",
        },
    )


def test_reconciliation_budget_starts_after_arm_patch_acknowledgement() -> None:
    ticks = iter((0.0, 125.0))
    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        monotonic=lambda: next(ticks),
        patch_applier=lambda _patch, **_kwargs: next(ticks) == 0.0 and "accepted",
    )
    actions.current_projection = {
        "location": "Central US",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {REGISTRY_ID: {}},
        },
        "properties": {"template": deepcopy(_app()["properties"]["template"])},
    }
    actions._immutable_configuration = deepcopy(_app()["properties"]["configuration"])

    revision = actions._apply_revision(
        enabled=False,
        label="r9-disable",
        role="emergency_disabled",
        context={"candidate_image_digest": "sha256:" + ("c" * 64)},
    )

    assert actions._pending_transitions[revision].started_at == 125.0


def test_r9_style_disabled_transition_uses_real_lro_patch_and_browser_gate() -> None:
    source_template = deepcopy(_app()["properties"]["template"])
    environment = source_template["containers"][0]["env"]
    for row in environment:
        if row["name"] == "BIZPULSE_AI_CHAT_ENABLED":
            row["value"] = "true"
    environment.extend(
        [
            {"name": "BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL", "value": "true"},
            {
                "name": "BIZPULSE_OPENAI_KEY_VAULT_URL",
                "value": "https://newcaostone-ai-kv.vault.azure.net",
            },
            {
                "name": "BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME",
                "value": "openai-api-key",
            },
            {
                "name": "BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID",
                "value": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            },
        ]
    )
    operation_url = (
        f"https://management.azure.com/subscriptions/{SUBSCRIPTION}/providers/"
        "Microsoft.App/locations/centralus/operations/dddddddd-dddd-4ddd-8ddd-dddddddddddd"
        "?api-version=2025-01-01"
    )
    arm_calls: list[str] = []
    browser_calls: list[tuple[str, ...]] = []
    responses = iter(
        (
            ARMResponse(
                status_code=202,
                headers={"Azure-AsyncOperation": operation_url},
                payload={},
            ),
            ARMResponse(
                status_code=200,
                headers={},
                payload={
                    "id": APP_RESOURCE_ID,
                    "provisioningState": "Succeeded",
                },
            ),
        )
    )

    def runner(command, **kwargs):
        browser_calls.append(tuple(command))
        assert command[:2] == ["node", "scripts/browser_release_gate.mjs"]
        assert kwargs["env"]["BIZPULSE_BROWSER_OPERATOR_PASSWORD"] == "operator-only"
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "scenario": "ai-disabled",
                    "externalRequests": 0,
                    "consoleErrors": 0,
                    "providerTurns": 0,
                }
            ),
            stderr="",
        )

    reconciliations: list[dict[str, object]] = []

    def revision_verifier(**kwargs):
        reconciliations.append(kwargs)
        revision = kwargs["revision"]
        return {
            "role": "emergency_disabled",
            "acknowledgement": "accepted",
            "predecessor_revision": ROLLBACK_REVISION,
            "target_revision": revision,
            "target_image_digest": f"sha256:{ROLLBACK_DIGEST}",
            "final_state": "healthy_target",
            "application_read_count": 1,
            "revision_read_count": 1,
            "elapsed_milliseconds": 0,
        }

    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        runner=runner,
        monotonic=lambda: 0.0,
        sleeper=lambda _seconds: None,
        browser_credential_provider=lambda: "operator-only",
        arm_requester=lambda method, _url, _body: arm_calls.append(method)
        or next(responses),
        revision_verifier=revision_verifier,
    )
    actions.current_projection = {
        "location": "Central US",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {REGISTRY_ID: {}, AI_IDENTITY: {}},
        },
        "properties": {"template": source_template},
    }
    actions._immutable_configuration = deepcopy(_app()["properties"]["configuration"])
    actions._hosted_url = "https://newcaostone-demo-app.example.azurecontainerapps.io"
    context = {"candidate_image_digest": f"sha256:{ROLLBACK_DIGEST}"}

    try:
        revision = actions._apply_revision(
            enabled=False,
            label="r9-disable",
            role="emergency_disabled",
            context=context,
        )
        reconciliation = actions._reconcile_revision(
            enabled=False,
            image=ROLLBACK_IMAGE,
            revision=revision,
            context=context,
            role="emergency_disabled",
        )
        actions._prepare_browser_credential()
        actions._run_browser_gate("ai-disabled")
    finally:
        actions.clear_browser_credential()

    current = actions.current_projection
    assert arm_calls == ["PATCH", "GET"]
    assert reconciliation is not None
    assert reconciliations[0]["enabled"] is False
    assert current is not None
    assert current["identity"]["userAssignedIdentities"] == {REGISTRY_ID: {}}
    names = {
        row["name"]
        for row in current["properties"]["template"]["containers"][0]["env"]
    }
    assert "BIZPULSE_OPENAI_KEY_VAULT_URL" not in names
    assert "BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME" not in names
    assert "BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID" not in names
    assert "BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL" not in names
    assert browser_calls == [("node", "scripts/browser_release_gate.mjs", actions._hosted_url, "ai-disabled")]


def test_disabled_transition_sends_identity_null_and_tracks_canonical_target() -> None:
    patches: list[dict[str, object]] = []
    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        patch_applier=lambda patch, **_kwargs: patches.append(deepcopy(patch))
        or "accepted",
        monotonic=lambda: 0.0,
    )
    actions.current_projection = {
        "location": "Central US",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {REGISTRY_ID: {}, AI_IDENTITY: {}},
        },
        "properties": {"template": deepcopy(_app()["properties"]["template"])},
    }
    actions._immutable_configuration = deepcopy(
        _app()["properties"]["configuration"]
    )

    revision = actions._apply_revision(
        enabled=False,
        label="recover-b",
        role="budget_recovery",
        context={"candidate_image_digest": "sha256:" + ("c" * 64)},
    )

    assert patches[0]["identity"]["userAssignedIdentities"] == {
        REGISTRY_ID: {},
        AI_IDENTITY: None,
    }
    expected_target = {REGISTRY_ID: {}}
    assert actions.current_projection is not None
    assert actions.current_projection["identity"]["userAssignedIdentities"] == (
        expected_target
    )
    assert actions._pending_transitions[revision].target_projection["identity"][
        "userAssignedIdentities"
    ] == expected_target


def _package(
    *, role_assignment_state: str = "legacy_only"
) -> dict[str, object]:
    return {
        "schema_version": "newcaostone.ai-enablement-package.v1",
        "issued_at": "2026-08-17T12:00:00Z",
        "expires_at": "2026-08-18T12:00:00Z",
        "approval": {"approved_sha256": None, "approved_at": None},
        "repository": {
            "branch": "codex/ai-enable-preset-buttons",
            "head_sha": HEAD,
            "tree_sha": TREE,
            "clean": True,
        },
        "azure_target": {
            "subscription_id": SUBSCRIPTION,
            "tenant_id": TENANT,
            "resource_group": "rg-bizpulse-centralus",
            "location": "centralus",
            "app_name": "newcaostone-demo-app",
            "registry_name": "sellernorthbpacr",
            "log_analytics_workspace_name": "newcaostone-demo-logs",
            "existing_registry_identity_name": "newcaostone-demo-registry",
            "rollback_revision": ROLLBACK_REVISION,
            "rollback_image": ROLLBACK_IMAGE,
            "vault_name": "newcaostone-ai-kv",
            "identity_name": "newcaostone-ai-identity",
        },
        "candidate": {
            "image_repository": "bizpulse",
            "source_tree_sha": TREE,
            "dockerfile_sha256": "8" * 64,
            "runtime_lock_sha256": "9" * 64,
            "image_input_sha256": "a" * 64,
            "candidate_image_digest": None,
        },
        "control_sha256": {"scripts/run_ai_enablement.py": "b" * 64},
        "d3": {},
        "resource_allowlist": {},
        "execution_contract": contract_template(),
        "cost_cap": {
            "currency": "USD",
            "maximum_paid_execution": "1.00",
            "maximum_paid_calls": 13,
            "stop_if_price_evidence_missing": True,
        },
        "provider_pricing": {
            "model": "gpt-5.4-nano-2026-03-17",
            "official_source": (
                "https://developers.openai.com/api/docs/models/gpt-5.4-nano"
            ),
            "checked_at": "2026-08-17T12:00:00Z",
            "input_usd_per_million_tokens": "0.20",
            "output_usd_per_million_tokens": "1.25",
            "regional_processing_uplift_percent": "10",
            "execution_uses_regional_processing": False,
        },
        "expected_safe_observations": {},
        "prepackage_gate": {
            "required_azure_reads": 12,
            "rollback_revision": ROLLBACK_REVISION,
            "rollback_image": ROLLBACK_IMAGE,
            "rollback_registry_tag": "ai-5a6c199eacae-ba92c00d",
            "rollback_identity_state": "registry_plus_ai",
            "replica_count": 1,
            "ai_enabled": False,
            "vault_state": "existing_exact",
            "identity_state": "existing_exact",
            "role_assignment_state": role_assignment_state,
            "diagnostic_setting_state": "existing_exact",
            "secret_values_read": 0,
        },
        "stop_conditions": [],
    }


def _environment() -> list[dict[str, str]]:
    values = {
        "APPLICATIONINSIGHTS_CONNECTION_STRING": "InstrumentationKey=redacted",
        "BIZPULSE_ALLOWED_ORIGIN": "https://example.invalid",
        "BIZPULSE_AI_CHAT_ENABLED": "false",
        "BIZPULSE_AI_DAILY_ATTEMPT_LIMIT": "120",
        "BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE": "20",
        "BIZPULSE_AI_MAX_CONCURRENT_TURNS": "15",
        "BIZPULSE_AI_MONTHLY_TOKEN_LIMIT": "150000",
        "BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE": "3",
        "BIZPULSE_BLOB_CONTAINER": "bizpulse",
        "BIZPULSE_BLOB_ENDPOINT": "https://storage.blob.core.windows.net",
        "BIZPULSE_DEMO_SESSION_RATE_LIMIT_PER_HOUR": "20",
        "BIZPULSE_OPENAI_MODEL": "gpt-5.4-nano-2026-03-17",
        "BIZPULSE_OPENAI_REASONING_EFFORT": "low",
        "BIZPULSE_RUNTIME_ENVIRONMENT": "cloud",
    }
    rows = [{"name": name, "value": value} for name, value in values.items()]
    rows.extend(
        [
            {"name": "BIZPULSE_DATABASE_URL", "secretRef": "database-url"},
            {
                "name": "BIZPULSE_BLOB_CONNECTION_STRING",
                "secretRef": "blob-connection-string",
            },
            {
                "name": "BIZPULSE_OPERATOR_PASSWORD_HASH",
                "secretRef": "operator-password-hash",
            },
            {
                "name": "BIZPULSE_SESSION_PEPPER",
                "secretRef": "session-pepper",
            },
        ]
    )
    return rows


def _app() -> dict[str, object]:
    return {
        "id": (
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/"
            "rg-bizpulse-centralus/providers/Microsoft.App/containerApps/"
            "newcaostone-demo-app"
        ),
        "name": "newcaostone-demo-app",
        "location": "Central US",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {
                REGISTRY_ID: {
                    "clientId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    "principalId": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                }
            },
        },
        "properties": {
            "latestRevisionName": ROLLBACK_REVISION,
            "latestReadyRevisionName": ROLLBACK_REVISION,
            "provisioningState": "Succeeded",
            "configuration": {
                "activeRevisionsMode": "Single",
                "ingress": {
                    "external": True,
                    "fqdn": "newcaostone-demo-app.example.azurecontainerapps.io",
                    "traffic": [{"latestRevision": True, "weight": 100}],
                },
                "registries": [
                    {
                        "server": "sellernorthbpacr.azurecr.io",
                        "identity": REGISTRY_ID.replace(
                            "/resourceGroups/", "/resourcegroups/"
                        ),
                    }
                ],
            },
            "template": {
                "revisionSuffix": "713a6984d4a0",
                "containers": [
                    {
                        "name": "bizpulse",
                        "image": ROLLBACK_IMAGE,
                        "env": _environment(),
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
            },
        },
    }


def _azure_runner(
    calls: list[tuple[tuple[str, ...], dict[str, object]]],
    *,
    role_assignment_state: str = "legacy_only",
):
    def runner(command, **kwargs):
        calls.append((tuple(command), kwargs))
        joined = " ".join(command)
        if command[:3] == ["az", "account", "show"]:
            payload = {"id": SUBSCRIPTION, "tenantId": TENANT}
            returncode = 0
            stderr = ""
        elif command[:3] == ["az", "containerapp", "show"]:
            payload = _app()
            assigned = payload["identity"]["userAssignedIdentities"]
            registry_value = assigned.pop(REGISTRY_ID)
            assigned[
                REGISTRY_ID.replace("/resourceGroups/", "/resourcegroups/")
            ] = registry_value
            assigned[
                AI_IDENTITY.replace("/resourceGroups/", "/resourcegroups/")
            ] = {
                "clientId": AI_CLIENT_ID,
                "principalId": AI_PRINCIPAL_ID,
            }
            returncode = 0
            stderr = ""
        elif command[:4] == ["az", "containerapp", "revision", "show"]:
            payload = {
                "name": ROLLBACK_REVISION,
                "properties": {
                    "active": True,
                    "healthState": "Healthy",
                    "provisioningState": "Provisioned",
                    "template": {"containers": [{"image": ROLLBACK_IMAGE}]},
                },
            }
            returncode = 0
            stderr = ""
        elif command[:4] == ["az", "containerapp", "replica", "list"]:
            payload = [
                {
                    "name": f"{ROLLBACK_REVISION}-replica",
                    "runningState": "Running",
                }
            ]
            returncode = 0
            stderr = ""
        elif command[:4] == ["az", "acr", "manifest", "show-metadata"]:
            payload = {
                "digest": f"sha256:{ROLLBACK_DIGEST}",
                "tags": ["ai-5a6c199eacae-ba92c00d"],
            }
            returncode = 0
            stderr = ""
        elif command[:3] == ["az", "acr", "show"]:
            payload = {
                "id": (
                    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/"
                    "rg-bizpulse-centralus/providers/Microsoft.ContainerRegistry/"
                    "registries/sellernorthbpacr"
                ),
                "name": "sellernorthbpacr",
                "location": "centralus",
                "loginServer": "sellernorthbpacr.azurecr.io",
                "adminUserEnabled": False,
                "publicNetworkAccess": "Enabled",
            }
            returncode = 0
            stderr = ""
        elif "log-analytics workspace show" in joined:
            payload = {
                "id": (
                    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/"
                    "rg-bizpulse-centralus/providers/Microsoft.OperationalInsights/"
                    "workspaces/newcaostone-demo-logs"
                ),
                "name": "newcaostone-demo-logs",
                "location": "centralus",
                "provisioningState": "Succeeded",
            }
            returncode = 0
            stderr = ""
        elif command[:3] == ["az", "keyvault", "show"]:
            payload = {
                "id": VAULT_ID,
                "name": "newcaostone-ai-kv",
                "location": "centralus",
                "tenantId": TENANT,
                "enableRbacAuthorization": True,
                "enablePurgeProtection": True,
                "softDeleteRetentionInDays": 90,
                "publicNetworkAccess": "Enabled",
                "provisioningState": "Succeeded",
                "tags": AI_RESOURCE_TAGS,
            }
            returncode = 0
            stderr = ""
        elif command[:3] == ["az", "identity", "show"]:
            payload = {
                "id": AI_IDENTITY,
                "name": "newcaostone-ai-identity",
                "location": "centralus",
                "clientId": AI_CLIENT_ID,
                "principalId": AI_PRINCIPAL_ID,
                "tenantId": TENANT,
                "tags": AI_RESOURCE_TAGS,
            }
            returncode = 0
            stderr = ""
        elif command[:4] == ["az", "role", "assignment", "list"]:
            assignments = {
                "legacy_only": {
                    "id": LEGACY_ASSIGNMENT_ID,
                    "principalId": AI_PRINCIPAL_ID,
                    "principalType": "ServicePrincipal",
                    "roleDefinitionId": SECRETS_USER_ROLE_ID,
                    "scope": VAULT_ID,
                },
                "officer_only": {
                    "id": OFFICER_ASSIGNMENT_ID,
                    "principalId": AI_PRINCIPAL_ID,
                    "principalType": "ServicePrincipal",
                    "roleDefinitionId": SECRETS_OFFICER_ROLE_ID,
                    "scope": SECRET_ID,
                },
            }
            payload = (
                []
                if "--scope" in command
                else [assignments[role_assignment_state]]
            )
            returncode = 0
            stderr = ""
        elif command[:4] == ["az", "monitor", "diagnostic-settings", "list"]:
            payload = [
                {
                    "name": "ai-vault-audit",
                    "workspaceId": WORKSPACE_ID,
                    "logs": [
                        {"category": "AuditEvent", "enabled": True},
                        {
                            "category": "AzurePolicyEvaluationDetails",
                            "enabled": True,
                        },
                    ],
                    "metrics": [{"category": "AllMetrics", "enabled": True}],
                }
            ]
            returncode = 0
            stderr = ""
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(
            command,
            returncode,
            stdout="" if payload is None else json.dumps(payload),
            stderr=stderr,
        )

    return runner


def test_readonly_revalidation_adopts_exact_resources_in_twelve_reads() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    result, projection = read_sanitized_azure_authority(
        _package(),
        runner=_azure_runner(calls),
    )

    specification = contract_template()["states"]["readonly_revalidation"]
    assert result == {
        "operations": {"azure.read.sanitized": 12},
        "evidence": specification["expected_evidence"],
        "outputs": {
            "rollback_revision": ROLLBACK_REVISION,
            "ai_enabled": False,
            "vault_state": "existing_exact",
            "identity_state": "existing_exact",
            "role_assignment_state": "legacy_only",
            "diagnostic_setting_state": "existing_exact",
            "secret_values_read": 0,
        },
    }
    assert len(calls) == 12
    serialized_commands = "\n".join(" ".join(command) for command, _ in calls)
    assert "configuration.secrets" not in serialized_commands.casefold()
    assert "keyvault secret" not in serialized_commands.casefold()
    assert "list-secrets" not in serialized_commands.casefold()
    assert "keyvault show" in serialized_commands
    assert "role assignment list" in serialized_commands
    assert "monitor diagnostic-settings list" in serialized_commands
    role_commands = [
        command
        for command, _ in calls
        if command[:4] == ("az", "role", "assignment", "list")
    ]
    assert len(role_commands) == 2
    assert "--all" in role_commands[0]
    assert "--include-inherited" not in role_commands[0]
    assert "--scope" not in role_commands[0]
    assert "--all" not in role_commands[1]
    assert "--include-inherited" in role_commands[1]
    assert role_commands[1][role_commands[1].index("--scope") + 1] == (
        f"/subscriptions/{SUBSCRIPTION}"
    )
    diagnostic_command = next(
        command
        for command, _ in calls
        if command[:4] == ("az", "monitor", "diagnostic-settings", "list")
    )
    diagnostic_query = diagnostic_command[diagnostic_command.index("--query") + 1]
    assert diagnostic_query.startswith("[].{")
    assert "value[]" not in diagnostic_query
    assert all(item[1].get("check") is False for item in calls)
    app_command = next(
        command
        for command, _ in calls
        if command[:3] == ("az", "containerapp", "show")
    )
    app_query = app_command[app_command.index("--query") + 1]
    assert "template:properties.template" not in app_query
    assert "resources:{cpu:resources.cpu,memory:resources.memory}" in app_query
    assert "scale:{minReplicas:properties.template.scale.minReplicas" in app_query
    revision_command = next(
        command
        for command, _ in calls
        if command[:4] == ("az", "containerapp", "revision", "show")
    )
    assert revision_command.count("newcaostone-demo-app") == 1
    assert revision_command[revision_command.index("--name") + 1] == (
        "newcaostone-demo-app"
    )
    assert revision_command[revision_command.index("--revision") + 1] == (
        ROLLBACK_REVISION
    )
    revision_query = revision_command[revision_command.index("--query") + 1]
    assert (
        "template:{containers:properties.template.containers[].{image:image}}"
        in revision_query
    )
    assert "template:properties.template" not in revision_query
    replica_command = next(
        command
        for command, _ in calls
        if command[:4] == ("az", "containerapp", "replica", "list")
    )
    assert replica_command[replica_command.index("--revision") + 1] == (
        ROLLBACK_REVISION
    )
    manifest_command = next(
        command
        for command, _ in calls
        if command[:4] == ("az", "acr", "manifest", "show-metadata")
    )
    assert manifest_command[manifest_command.index("--name") + 1] == (
        f"bizpulse@sha256:{ROLLBACK_DIGEST}"
    )
    assert projection == {
        "location": "Central US",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {
                REGISTRY_ID.replace("/resourceGroups/", "/resourcegroups/"): {},
                AI_IDENTITY.replace("/resourceGroups/", "/resourcegroups/"): {},
            },
        },
        "properties": {"template": _app()["properties"]["template"]},
    }


def _registry_only_successor_package() -> dict[str, object]:
    package = deepcopy(_package(role_assignment_state="officer_only"))
    recovery_revision = "newcaostone-demo-app--recover-b-9c35ae6a-2bf7086"
    package["azure_target"]["rollback_revision"] = recovery_revision
    package["prepackage_gate"]["rollback_revision"] = recovery_revision
    package["prepackage_gate"]["rollback_identity_state"] = "registry_only"
    return package


def _registry_only_successor_runner(
    calls: list[tuple[tuple[str, ...], dict[str, object]]],
):
    base = _azure_runner(calls, role_assignment_state="officer_only")
    recovery_revision = "newcaostone-demo-app--recover-b-9c35ae6a-2bf7086"

    def runner(command, **kwargs):
        completed = base(command, **kwargs)
        payload = json.loads(completed.stdout)
        if command[:3] == ["az", "containerapp", "show"]:
            payload["properties"]["latestRevisionName"] = recovery_revision
            payload["properties"]["latestReadyRevisionName"] = recovery_revision
            assigned = payload["identity"]["userAssignedIdentities"]
            assigned.pop(
                AI_IDENTITY.replace("/resourceGroups/", "/resourcegroups/"),
                None,
            )
        elif command[:4] == ["az", "containerapp", "revision", "show"]:
            payload["name"] = recovery_revision
        elif command[:4] == ["az", "containerapp", "replica", "list"]:
            payload[0]["name"] = f"{recovery_revision}-replica"
        return subprocess.CompletedProcess(
            command,
            completed.returncode,
            stdout=json.dumps(payload),
            stderr=completed.stderr,
        )

    return runner


def test_readonly_successor_accepts_exact_registry_only_recovery() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    result, projection = read_sanitized_azure_authority(
        _registry_only_successor_package(),
        runner=_registry_only_successor_runner(calls),
    )

    assert result["operations"] == {"azure.read.sanitized": 12}
    assert result["outputs"]["rollback_revision"] == (
        "newcaostone-demo-app--recover-b-9c35ae6a-2bf7086"
    )
    assert len(calls) == 12
    assert projection["identity"]["userAssignedIdentities"] == {
        REGISTRY_ID.replace("/resourceGroups/", "/resourcegroups/"): {}
    }


def test_readonly_successor_rejects_registry_plus_ai_identity() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    with pytest.raises(
        AzureAIEnablementActionInvalid,
        match="ai_enablement_azure_authority_drift",
    ):
        read_sanitized_azure_authority(
            _registry_only_successor_package(),
            runner=_azure_runner(calls, role_assignment_state="officer_only"),
        )


def test_readonly_revalidation_rejects_management_group_assignment_returned_only_by_inherited_query() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    base = _azure_runner(calls)
    management_group_assignment = {
        "id": (
            "/providers/Microsoft.Management/managementGroups/course-demo/"
            "providers/Microsoft.Authorization/roleAssignments/"
            "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
        ),
        "principalId": AI_PRINCIPAL_ID,
        "principalType": "ServicePrincipal",
        "roleDefinitionId": (
            f"/subscriptions/{SUBSCRIPTION}/providers/"
            "Microsoft.Authorization/roleDefinitions/"
            "acdd72a7-3385-48ef-bd42-f606fba81ae7"
        ),
        "scope": "/providers/Microsoft.Management/managementGroups/course-demo",
    }

    def runner(command, **kwargs):
        if (
            command[:4] == ["az", "role", "assignment", "list"]
            and "--scope" in command
        ):
            calls.append((tuple(command), kwargs))
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps([management_group_assignment]),
                stderr="",
            )
        return base(command, **kwargs)

    with pytest.raises(
        AzureAIEnablementActionInvalid,
        match="ai_enablement_azure_authority_drift",
    ):
        read_sanitized_azure_authority(_package(), runner=runner)

    role_commands = [
        command
        for command, _kwargs in calls
        if command[:4] == ("az", "role", "assignment", "list")
    ]
    assert len(role_commands) == 2
    assert "--all" in role_commands[0]
    assert "--scope" not in role_commands[0]
    assert "--include-inherited" in role_commands[1]
    assert "--scope" in role_commands[1]


def test_readonly_revalidation_deduplicates_assignment_returned_by_both_queries() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    base = _azure_runner(calls)
    legacy = {
        "id": LEGACY_ASSIGNMENT_ID,
        "principalId": AI_PRINCIPAL_ID,
        "principalType": "ServicePrincipal",
        "roleDefinitionId": SECRETS_USER_ROLE_ID,
        "scope": VAULT_ID,
    }

    def runner(command, **kwargs):
        if command[:4] == ["az", "role", "assignment", "list"]:
            calls.append((tuple(command), kwargs))
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps([legacy]), stderr=""
            )
        return base(command, **kwargs)

    result, _projection = read_sanitized_azure_authority(
        _package(), runner=runner
    )

    assert result["operations"] == {"azure.read.sanitized": 12}
    assert len(
        [
            command
            for command, _kwargs in calls
            if command[:4] == ("az", "role", "assignment", "list")
        ]
    ) == 2


@pytest.mark.parametrize(
    ("package_phase", "observed_phase"),
    [
        ("legacy_only", "officer_only"),
        ("officer_only", "legacy_only"),
    ],
)
def test_readonly_revalidation_rejects_cross_phase_role_state(
    package_phase: str,
    observed_phase: str,
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    with pytest.raises(
        AzureAIEnablementActionInvalid,
        match="ai_enablement_azure_authority_drift",
    ):
        read_sanitized_azure_authority(
            _package(role_assignment_state=package_phase),
            runner=_azure_runner(
                calls,
                role_assignment_state=observed_phase,
            ),
        )


def test_readonly_revalidation_accepts_exact_officer_only_successor() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    result, _projection = read_sanitized_azure_authority(
        _package(role_assignment_state="officer_only"),
        runner=_azure_runner(calls, role_assignment_state="officer_only"),
    )

    assert result["outputs"]["role_assignment_state"] == "officer_only"


def test_readonly_revalidation_uses_a_credential_free_child_environment() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    read_sanitized_azure_authority(
        _package(),
        runner=_azure_runner(calls),
        environment={
            "HOME": "/safe-home",
            "PATH": "/safe-bin",
            "BIZPULSE_BROWSER_OPERATOR_PASSWORD": "operator-secret",
            "UNRELATED_SECRET": "must-not-inherit",
        },
    )

    assert len(calls) == 12
    assert all(
        kwargs["env"] == {"HOME": "/safe-home", "PATH": "/safe-bin"}
        for _command, kwargs in calls
    )


def test_readonly_revalidation_rejects_ready_revision_or_image_drift() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    base = _azure_runner(calls)

    def runner(command, **kwargs):
        completed = base(command, **kwargs)
        if command[:3] == ["az", "containerapp", "show"]:
            payload = json.loads(completed.stdout)
            payload["properties"]["latestReadyRevisionName"] = "drifted"
            completed = subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(payload), stderr=""
            )
        return completed

    with pytest.raises(
        AzureAIEnablementActionInvalid,
        match="ai_enablement_azure_authority_drift",
    ):
        read_sanitized_azure_authority(_package(), runner=runner)


@pytest.mark.parametrize("mutation", ["replica", "manifest"])
def test_readonly_revalidation_rejects_replica_or_manifest_drift(
    mutation: str,
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    base = _azure_runner(calls)

    def runner(command, **kwargs):
        completed = base(command, **kwargs)
        if (
            mutation == "replica"
            and command[:4] == ["az", "containerapp", "replica", "list"]
        ):
            completed = subprocess.CompletedProcess(
                command,
                0,
                stdout="[]",
                stderr="",
            )
        if (
            mutation == "manifest"
            and command[:4] == ["az", "acr", "manifest", "show-metadata"]
        ):
            payload = json.loads(completed.stdout)
            payload["tags"] = ["unrelated-tag"]
            completed = subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(payload),
                stderr="",
            )
        return completed

    with pytest.raises(
        AzureAIEnablementActionInvalid,
        match="ai_enablement_azure_authority_drift",
    ):
        read_sanitized_azure_authority(_package(), runner=runner)


def test_paid_preflight_uses_bound_official_price_and_conservative_cost() -> None:
    assert provider_price_preflight(_package()) == {
        "price_evidence_present": True,
        "maximum_estimated_cost": "0.19",
    }

    package = _package()
    package["provider_pricing"]["model"] = "floating-model"
    with pytest.raises(
        AzureAIEnablementActionInvalid,
        match="ai_enablement_paid_preflight_failed",
    ):
        provider_price_preflight(package)


class _SecretWriter:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str]] = []

    def __call__(self, value: str, *, write_kind: str) -> None:
        self.writes.append((write_kind, value))


def test_placeholder_is_overwritten_not_read_deleted_or_serialized() -> None:
    writer = _SecretWriter()
    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        secret_writer=writer,
        now=lambda: datetime(2026, 8, 17, 12, 30, tzinfo=UTC),
    )
    placeholder = actions.operation_executor(
        "provider_failure_placeholder_write",
        environment={},
        secret_value=None,
        context={},
    )
    real = actions.operation_executor(
        "real_secret_write",
        environment={},
        secret_value="sentinel-real-key",
        context={},
    )

    assert placeholder["outputs"] == {}
    assert real["outputs"] == {}
    assert [kind for kind, _ in writer.writes] == [
        "placeholder",
        "real",
    ]
    assert writer.writes[0][1] != "sentinel-real-key"
    assert len(writer.writes[0][1]) >= 32
    assert writer.writes[1][1] == "sentinel-real-key"
    assert "sentinel-real-key" not in repr(placeholder)
    assert "sentinel-real-key" not in repr(real)


def test_default_actions_orchestrate_exact_patches_browser_and_paid_counts() -> None:
    patch_calls: list[dict[str, object]] = []
    browser_calls: list[str] = []
    qualification_environments: list[dict[str, str]] = []
    writer = _SecretWriter()
    digest = "sha256:" + ("c" * 64)

    def patch_applier(patch, *, revision_suffix):
        patch_calls.append(deepcopy(patch))
        return "accepted"

    def browser_checker(scenario: str) -> None:
        browser_calls.append(scenario)

    def qualification_executor(environment):
        qualification_environments.append(dict(environment))
        return 12

    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        secret_writer=writer,
        publisher=lambda: digest,
        patch_applier=patch_applier,
        browser_checker=browser_checker,
        resource_deployer=lambda: {
                "vault_url": "https://newcaostone-ai-kv.vault.azure.net",
            "identity_resource_id": (
                f"/subscriptions/{SUBSCRIPTION}/resourceGroups/"
                "rg-bizpulse-centralus/providers/Microsoft.ManagedIdentity/"
                "userAssignedIdentities/newcaostone-ai-identity"
            ),
            "managed_identity_client_id": (
                "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
            ),
        },
        revision_verifier=lambda **_kwargs: None,
        qualification_executor=qualification_executor,
    )
    actions.current_projection = {
        "location": "Central US",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {REGISTRY_ID: {}},
        },
        "properties": {"template": _app()["properties"]["template"]},
    }
    actions._immutable_configuration = deepcopy(
        _app()["properties"]["configuration"]
    )
    context: dict[str, object] = {"package_sha256": PACKAGE_SHA256}

    published = actions.operation_executor(
        "publish_candidate_image",
        environment={},
        secret_value=None,
        context=context,
    )
    context.update(published["outputs"])
    disabled = actions.operation_executor(
        "activate_ai_disabled_candidate",
        environment={},
        secret_value=None,
        context=context,
    )
    context.update({"ai_disabled_revision": disabled["outputs"]["revision"]})
    actions.operation_executor(
        "verify_ai_disabled_candidate",
        environment={},
        secret_value=None,
        context=context,
    )
    resources = actions.operation_executor(
        "reconcile_ai_vault_identity_role_diagnostics",
        environment={},
        secret_value=None,
        context=context,
    )
    context.update(resources["outputs"])
    actions.operation_executor(
        "budget_failure_rehearsal",
        environment={},
        secret_value=None,
        context=context,
    )
    actions.operation_executor(
        "provider_failure_placeholder_write",
        environment={},
        secret_value=None,
        context=context,
    )
    actions.operation_executor(
        "provider_failure_rehearsal",
        environment={},
        secret_value=None,
        context=context,
    )
    qualification = actions.operation_executor(
        "paid_model_qualification",
        environment={"BIZPULSE_DEPLOY_OPENAI_API_KEY": "sentinel-real-key"},
        secret_value=None,
        context=context,
    )
    actions.operation_executor(
        "real_secret_write",
        environment={},
        secret_value="sentinel-real-key",
        context=context,
    )
    enabled = actions.operation_executor(
        "activate_ai_enabled_revision",
        environment={},
        secret_value=None,
        context=context,
    )
    context.update({"final_revision": enabled["outputs"]["final_revision"]})
    actions.operation_executor(
        "verify_ai_enabled_revision",
        environment={},
        secret_value=None,
        context=context,
    )
    smoke = actions.operation_executor(
        "paid_hosted_manual_send_smoke",
        environment={},
        secret_value=None,
        context=context,
    )
    actions.operation_executor(
        "sanitize_receipt",
        environment={},
        secret_value=None,
        context=context,
    )

    assert published["outputs"] == {"candidate_image_digest": digest}
    assert disabled["outputs"]["candidate_image_digest"] == digest
    assert qualification["outputs"] == {"paid_call_count": 12}
    assert enabled["outputs"]["candidate_image_digest"] == digest
    assert smoke["outputs"] == {"paid_call_count": 1}
    assert len(patch_calls) == 6
    patch_environments = [
        {
            row["name"]: row.get("value", row.get("secretRef"))
            for row in patch["properties"]["template"]["containers"][0]["env"]
        }
        for patch in patch_calls
    ]
    assert [rows["BIZPULSE_AI_CHAT_ENABLED"] for rows in patch_environments] == [
        "false",
        "true",
        "false",
        "true",
        "false",
        "true",
    ]
    assert patch_environments[1]["BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL"] == (
        "true"
    )
    assert all(
        "BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL" not in rows
        for index, rows in enumerate(patch_environments)
        if index != 1
    )
    assert browser_calls == [
        "ai-disabled",
        "budget",
        "provider-unavailable",
        "paid-ai",
    ]
    assert qualification_environments == [
        {"BIZPULSE_DEPLOY_OPENAI_API_KEY": "sentinel-real-key"}
    ]


def test_default_secret_writer_sends_secure_parameter_only_on_child_stdin() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def runner(command, **kwargs):
        calls.append((tuple(command), kwargs))
        payload = {
            "deploymentEnabled": {"value": True},
            "keyVaultSecretName": {"value": "openai-api-key"},
            "keyVaultSecretResourceId": {
                "value": (
                    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/"
                    "rg-bizpulse-centralus/providers/Microsoft.KeyVault/"
                    "vaults/newcaostone-ai-kv/secrets/openai-api-key"
                )
            },
        }
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payload), stderr=""
        )

    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        runner=runner,
    )
    result = actions.operation_executor(
        "real_secret_write",
        environment={},
        secret_value="sentinel-real-key",
        context={},
    )

    assert result["outputs"] == {}
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:4] == ("az", "deployment", "group", "create")
    assert command[command.index("--parameters") + 1] == "@/dev/stdin"
    assert "sentinel-real-key" not in " ".join(command)
    parameters = json.loads(kwargs["input"])
    assert parameters["parameters"]["openAiApiKey"]["value"] == (
        "sentinel-real-key"
    )
    assert "sentinel-real-key" not in repr(result)


def test_default_resource_reconciliation_has_no_secret_parameter() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    identity_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-bizpulse-centralus/"
        "providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
        "newcaostone-ai-identity"
    )

    before = [
        {
            "id": LEGACY_ASSIGNMENT_ID,
            "principalId": AI_PRINCIPAL_ID,
            "principalType": "ServicePrincipal",
            "roleDefinitionId": SECRETS_USER_ROLE_ID,
            "scope": VAULT_ID,
        },
        {
            "id": OFFICER_ASSIGNMENT_ID,
            "principalId": AI_PRINCIPAL_ID,
            "principalType": "ServicePrincipal",
            "roleDefinitionId": SECRETS_OFFICER_ROLE_ID,
            "scope": SECRET_ID,
        },
    ]
    reads = iter((before, before, [before[1]], [before[1]]))

    def runner(command, **kwargs):
        calls.append((tuple(command), kwargs))
        if command[:4] == ["az", "role", "assignment", "list"]:
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(next(reads)), stderr=""
            )
        if command[:4] == ["az", "role", "assignment", "delete"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        payload = {
            "deploymentEnabled": {"value": True},
            "identityName": {"value": "newcaostone-ai-identity"},
            "identityResourceId": {"value": identity_id},
            "managedIdentityClientId": {
                "value": "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
            },
            "keyVaultName": {"value": "newcaostone-ai-kv"},
            "keyVaultResourceId": {"value": VAULT_ID},
            "keyVaultUrl": {
                "value": "https://newcaostone-ai-kv.vault.azure.net/"
            },
            "canonicalSecretResourceId": {"value": SECRET_ID},
            "managedIdentityPrincipalId": {"value": AI_PRINCIPAL_ID},
            "adminAiSecretOfficerRoleAssignmentResourceId": {
                "value": OFFICER_ASSIGNMENT_ID
            },
            "legacyVaultSecretsUserRoleAssignmentResourceId": {
                "value": LEGACY_ASSIGNMENT_ID
            },
        }
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payload), stderr=""
        )

    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        runner=runner,
    )
    result = actions.operation_executor(
        "reconcile_ai_vault_identity_role_diagnostics",
        environment={},
        secret_value=None,
        context={"package_sha256": PACKAGE_SHA256, "source_git_sha": HEAD},
    )

    assert result["outputs"] == {
        "vault_url": "https://newcaostone-ai-kv.vault.azure.net",
        "identity_resource_id": identity_id,
        "managed_identity_client_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "assignment_set_sha256": hashlib.sha256(
            json.dumps(
                [
                    {
                        "id": OFFICER_ASSIGNMENT_ID.casefold(),
                        "principalId": AI_PRINCIPAL_ID.casefold(),
                        "principalType": "ServicePrincipal",
                        "roleDefinitionId": SECRETS_OFFICER_ROLE_ID.casefold(),
                        "scope": SECRET_ID.casefold(),
                    }
                ],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
    }
    assert len(calls) == 6
    command = calls[0][0]
    assert command[:4] == ("az", "deployment", "group", "create")
    serialized = " ".join(command)
    assert "ai_enablement.bicep" in serialized
    assert "secretDeploymentEnabled" not in serialized
    assert "openAiApiKey" not in serialized
    assert "sellernorthbp-kv" not in serialized
    assert command[command.index("--mode") + 1] == "Incremental"
    assert "Complete" not in command
    list_commands = [
        candidate
        for candidate, _kwargs in calls
        if candidate[:4] == ("az", "role", "assignment", "list")
    ]
    assert len(list_commands) == 4
    assert all(
        candidate[candidate.index("--assignee-object-id") + 1]
        == AI_PRINCIPAL_ID
        for candidate in list_commands
    )
    for descendants, ancestors in zip(
        list_commands[::2], list_commands[1::2], strict=True
    ):
        assert "--all" in descendants
        assert "--include-inherited" not in descendants
        assert "--scope" not in descendants
        assert "--all" not in ancestors
        assert "--include-inherited" in ancestors
        assert ancestors[ancestors.index("--scope") + 1] == (
            f"/subscriptions/{SUBSCRIPTION}"
        )
    assert calls[3][0] == (
        "az",
        "role",
        "assignment",
        "delete",
        "--subscription",
        SUBSCRIPTION,
        "--ids",
        LEGACY_ASSIGNMENT_ID,
        "--only-show-errors",
        "--output",
        "none",
    )


@pytest.mark.parametrize(
    "unexpected",
    [
        {
            "id": f"{VAULT_ID}/providers/Microsoft.Authorization/roleAssignments/"
            "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
            "principalId": AI_PRINCIPAL_ID,
            "principalType": "ServicePrincipal",
            "roleDefinitionId": SECRETS_USER_ROLE_ID,
            "scope": VAULT_ID,
        },
        {
            "id": LEGACY_ASSIGNMENT_ID,
            "principalId": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
            "principalType": "ServicePrincipal",
            "roleDefinitionId": SECRETS_USER_ROLE_ID,
            "scope": VAULT_ID,
        },
        {
            "id": (
                f"/subscriptions/{SUBSCRIPTION}/resourceGroups/"
                "rg-bizpulse-centralus/providers/Microsoft.Authorization/"
                "roleAssignments/eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
            ),
            "principalId": AI_PRINCIPAL_ID,
            "principalType": "ServicePrincipal",
            "roleDefinitionId": (
                f"/subscriptions/{SUBSCRIPTION}/providers/"
                "Microsoft.Authorization/roleDefinitions/"
                "b24988ac-6180-42a0-ab88-20f7382dd24c"
            ),
            "scope": (
                f"/subscriptions/{SUBSCRIPTION}/resourceGroups/"
                "rg-bizpulse-centralus"
            ),
        },
        {
            "id": (
                f"/subscriptions/{SUBSCRIPTION}/providers/"
                "Microsoft.Authorization/roleAssignments/"
                "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
            ),
            "principalId": AI_PRINCIPAL_ID,
            "principalType": "ServicePrincipal",
            "roleDefinitionId": (
                f"/subscriptions/{SUBSCRIPTION}/providers/"
                "Microsoft.Authorization/roleDefinitions/"
                "acdd72a7-3385-48ef-bd42-f606fba81ae7"
            ),
            "scope": f"/subscriptions/{SUBSCRIPTION}",
        },
        {
            "id": (
                "/providers/Microsoft.Management/managementGroups/course-demo/"
                "providers/Microsoft.Authorization/roleAssignments/"
                "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
            ),
            "principalId": AI_PRINCIPAL_ID,
            "principalType": "ServicePrincipal",
            "roleDefinitionId": (
                f"/subscriptions/{SUBSCRIPTION}/providers/"
                "Microsoft.Authorization/roleDefinitions/"
                "acdd72a7-3385-48ef-bd42-f606fba81ae7"
            ),
            "scope": "/providers/Microsoft.Management/managementGroups/course-demo",
        },
    ],
)
def test_secret_access_migration_refuses_unexpected_or_mismatched_assignment(
    unexpected: dict[str, str],
) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(command, **_kwargs):
        calls.append(tuple(command))
        if command[:4] == ["az", "deployment", "group", "create"]:
            outputs = {
                "deploymentEnabled": {"value": True},
                "identityName": {"value": "newcaostone-ai-identity"},
                "identityResourceId": {"value": AI_IDENTITY},
                "managedIdentityClientId": {"value": AI_CLIENT_ID},
                "managedIdentityPrincipalId": {"value": AI_PRINCIPAL_ID},
                "keyVaultName": {"value": "newcaostone-ai-kv"},
                "keyVaultResourceId": {"value": VAULT_ID},
                "keyVaultUrl": {
                    "value": "https://newcaostone-ai-kv.vault.azure.net/"
                },
                "canonicalSecretResourceId": {"value": SECRET_ID},
                "adminAiSecretOfficerRoleAssignmentResourceId": {
                    "value": OFFICER_ASSIGNMENT_ID
                },
                "legacyVaultSecretsUserRoleAssignmentResourceId": {
                    "value": LEGACY_ASSIGNMENT_ID
                },
            }
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(outputs), stderr=""
            )
        assignments = [
            {
                "id": OFFICER_ASSIGNMENT_ID,
                "principalId": AI_PRINCIPAL_ID,
                "principalType": "ServicePrincipal",
                "roleDefinitionId": SECRETS_OFFICER_ROLE_ID,
                "scope": SECRET_ID,
            },
            unexpected,
        ]
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(assignments), stderr=""
        )

    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        runner=runner,
    )
    with pytest.raises(
        AzureAIEnablementActionInvalid,
        match="ai_enablement_role_assignment_drift",
    ):
        actions.reconcile_admin_ai_secret_access(
            context={"package_sha256": PACKAGE_SHA256, "source_git_sha": HEAD}
        )

    assert not any(
        command[:4] == ("az", "role", "assignment", "delete")
        for command in calls
    )
    list_commands = [
        command
        for command in calls
        if command[:4] == ("az", "role", "assignment", "list")
    ]
    assert len(list_commands) == 2
    assert "--all" in list_commands[0]
    assert "--include-inherited" not in list_commands[0]
    assert "--scope" not in list_commands[0]
    assert "--all" not in list_commands[1]
    assert "--include-inherited" in list_commands[1]
    assert list_commands[1][list_commands[1].index("--scope") + 1] == (
        f"/subscriptions/{SUBSCRIPTION}"
    )


def test_secret_access_migration_rejects_management_group_assignment_returned_only_by_inherited_query() -> None:
    calls: list[tuple[str, ...]] = []
    officer = {
        "id": OFFICER_ASSIGNMENT_ID,
        "principalId": AI_PRINCIPAL_ID,
        "principalType": "ServicePrincipal",
        "roleDefinitionId": SECRETS_OFFICER_ROLE_ID,
        "scope": SECRET_ID,
    }
    legacy = {
        "id": LEGACY_ASSIGNMENT_ID,
        "principalId": AI_PRINCIPAL_ID,
        "principalType": "ServicePrincipal",
        "roleDefinitionId": SECRETS_USER_ROLE_ID,
        "scope": VAULT_ID,
    }
    management_group_assignment = {
        "id": (
            "/providers/Microsoft.Management/managementGroups/course-demo/"
            "providers/Microsoft.Authorization/roleAssignments/"
            "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
        ),
        "principalId": AI_PRINCIPAL_ID,
        "principalType": "ServicePrincipal",
        "roleDefinitionId": (
            f"/subscriptions/{SUBSCRIPTION}/providers/"
            "Microsoft.Authorization/roleDefinitions/"
            "acdd72a7-3385-48ef-bd42-f606fba81ae7"
        ),
        "scope": "/providers/Microsoft.Management/managementGroups/course-demo",
    }

    def runner(command, **_kwargs):
        calls.append(tuple(command))
        if command[:4] == ["az", "deployment", "group", "create"]:
            outputs = {
                "deploymentEnabled": {"value": True},
                "identityName": {"value": "newcaostone-ai-identity"},
                "identityResourceId": {"value": AI_IDENTITY},
                "managedIdentityClientId": {"value": AI_CLIENT_ID},
                "managedIdentityPrincipalId": {"value": AI_PRINCIPAL_ID},
                "keyVaultName": {"value": "newcaostone-ai-kv"},
                "keyVaultResourceId": {"value": VAULT_ID},
                "keyVaultUrl": {
                    "value": "https://newcaostone-ai-kv.vault.azure.net/"
                },
                "canonicalSecretResourceId": {"value": SECRET_ID},
                "adminAiSecretOfficerRoleAssignmentResourceId": {
                    "value": OFFICER_ASSIGNMENT_ID
                },
                "legacyVaultSecretsUserRoleAssignmentResourceId": {
                    "value": LEGACY_ASSIGNMENT_ID
                },
            }
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(outputs), stderr=""
            )
        if command[:4] == ["az", "role", "assignment", "list"]:
            assignments = (
                [management_group_assignment]
                if "--scope" in command
                else [officer, legacy]
            )
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(assignments), stderr=""
            )
        raise AssertionError(command)

    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        runner=runner,
    )
    with pytest.raises(
        AzureAIEnablementActionInvalid,
        match="ai_enablement_role_assignment_drift",
    ):
        actions.reconcile_admin_ai_secret_access(
            context={"package_sha256": PACKAGE_SHA256, "source_git_sha": HEAD}
        )

    assert not any(
        command[:4] == ("az", "role", "assignment", "delete")
        for command in calls
    )
    role_commands = [
        command
        for command in calls
        if command[:4] == ("az", "role", "assignment", "list")
    ]
    assert len(role_commands) == 2
    assert "--all" in role_commands[0]
    assert "--scope" not in role_commands[0]
    assert "--include-inherited" in role_commands[1]
    assert "--scope" in role_commands[1]


def test_secret_access_migration_requires_exact_package_and_source_binding() -> None:
    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError),
    )

    for context in (
        {"package_sha256": "f" * 64, "source_git_sha": HEAD},
        {"package_sha256": PACKAGE_SHA256, "source_git_sha": "e" * 40},
        {"package_sha256": PACKAGE_SHA256},
    ):
        with pytest.raises(
            AzureAIEnablementActionInvalid,
            match="ai_enablement_resource_authority_drift",
        ):
            actions.reconcile_admin_ai_secret_access(context=context)


def test_officer_only_successor_reconciles_without_legacy_delete() -> None:
    calls: list[tuple[str, ...]] = []
    officer = {
        "id": OFFICER_ASSIGNMENT_ID,
        "principalId": AI_PRINCIPAL_ID,
        "principalType": "ServicePrincipal",
        "roleDefinitionId": SECRETS_OFFICER_ROLE_ID,
        "scope": SECRET_ID,
    }

    def runner(command, **_kwargs):
        calls.append(tuple(command))
        if command[:4] == ["az", "deployment", "group", "create"]:
            outputs = {
                "deploymentEnabled": {"value": True},
                "identityName": {"value": "newcaostone-ai-identity"},
                "identityResourceId": {"value": AI_IDENTITY},
                "managedIdentityClientId": {"value": AI_CLIENT_ID},
                "managedIdentityPrincipalId": {"value": AI_PRINCIPAL_ID},
                "keyVaultName": {"value": "newcaostone-ai-kv"},
                "keyVaultResourceId": {"value": VAULT_ID},
                "keyVaultUrl": {
                    "value": "https://newcaostone-ai-kv.vault.azure.net/"
                },
                "canonicalSecretResourceId": {"value": SECRET_ID},
                "adminAiSecretOfficerRoleAssignmentResourceId": {
                    "value": OFFICER_ASSIGNMENT_ID
                },
                "legacyVaultSecretsUserRoleAssignmentResourceId": {
                    "value": LEGACY_ASSIGNMENT_ID
                },
            }
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(outputs), stderr=""
            )
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps([officer]), stderr=""
        )

    actions = AzureAIEnablementActions(
        package=_package(role_assignment_state="officer_only"),
        package_sha256=PACKAGE_SHA256,
        runner=runner,
    )

    result = actions.reconcile_admin_ai_secret_access(
        context={"package_sha256": PACKAGE_SHA256, "source_git_sha": HEAD}
    )

    assert result["vault_url"] == "https://newcaostone-ai-kv.vault.azure.net"
    expected_assignment_set = [
        {
            "id": OFFICER_ASSIGNMENT_ID.casefold(),
            "principalId": AI_PRINCIPAL_ID.casefold(),
            "principalType": "ServicePrincipal",
            "roleDefinitionId": SECRETS_OFFICER_ROLE_ID.casefold(),
            "scope": SECRET_ID.casefold(),
        }
    ]
    assert result["assignment_set_sha256"] == hashlib.sha256(
        json.dumps(
            expected_assignment_set,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert not any(
        command[:4] == ("az", "role", "assignment", "delete")
        for command in calls
    )


def test_default_qualification_scopes_key_to_child_environment_and_safe_receipt() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def runner(command, **kwargs):
        captured_kwargs = dict(kwargs)
        captured_kwargs["env"] = dict(kwargs["env"])
        calls.append((tuple(command), captured_kwargs))
        receipt = Path(command[command.index("--receipt") + 1])
        receipt.write_text(
            json.dumps(
                {
                    "passed": True,
                    "model_snapshot": {
                        "model": "gpt-5.4-nano-2026-03-17"
                    },
                    "cases": [
                        {"case_id": f"case-{index}", "passed": True}
                        for index in range(12)
                    ],
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="safe", stderr="")

    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        runner=runner,
        environment={"PATH": "/usr/bin"},
    )
    result = actions.operation_executor(
        "paid_model_qualification",
        environment={"BIZPULSE_DEPLOY_OPENAI_API_KEY": "sentinel-real-key"},
        secret_value=None,
        context={},
    )

    assert result["outputs"] == {"paid_call_count": 12}
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert "sentinel-real-key" not in " ".join(command)
    assert kwargs["env"] == {
        "PATH": "/usr/bin",
        "BIZPULSE_DEPLOY_OPENAI_API_KEY": "sentinel-real-key",
    }
    assert "sentinel-real-key" not in repr(result)


def test_provider_rehearsal_recovers_to_ai_disabled_before_propagating_failure() -> None:
    patches: list[dict[str, object]] = []
    verified: list[dict[str, object]] = []

    def patch_applier(patch, *, revision_suffix):
        patches.append(deepcopy(patch))
        return "accepted"

    def browser_checker(_scenario: str) -> None:
        raise RuntimeError("synthetic-browser-failure")

    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        patch_applier=patch_applier,
        browser_checker=browser_checker,
        revision_verifier=lambda **kwargs: verified.append(deepcopy(kwargs)),
    )
    actions.current_projection = {
        "location": "Central US",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {REGISTRY_ID: {}},
        },
        "properties": {"template": _app()["properties"]["template"]},
    }
    actions._immutable_configuration = deepcopy(
        _app()["properties"]["configuration"]
    )
    context = {
        "candidate_image_digest": "sha256:" + ("c" * 64),
        "vault_url": "https://newcaostone-ai-kv.vault.azure.net",
        "managed_identity_client_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    }

    with pytest.raises(
        AzureAIEnablementActionInvalid,
        match="ai_enablement_browser_failed",
    ):
        actions.operation_executor(
            "provider_failure_rehearsal",
            environment={},
            secret_value=None,
            context=context,
        )

    assert len(patches) == 2
    assert [
        next(
            row["value"]
            for row in patch["properties"]["template"]["containers"][0]["env"]
            if row["name"] == "BIZPULSE_AI_CHAT_ENABLED"
        )
        for patch in patches
    ] == ["true", "false"]
    assert [entry["enabled"] for entry in verified] == [True, False]
    assert [entry["role"] for entry in verified] == [
        "provider_enabled",
        "provider_recovery",
    ]


def test_first_enabled_rehearsal_patch_ambiguity_still_recovers_and_verifies_disabled() -> None:
    patches: list[dict[str, object]] = []
    verified: list[dict[str, object]] = []

    def patch_applier(patch, *, revision_suffix):
        patches.append(deepcopy(patch))
        if len(patches) == 1:
            raise TimeoutError("response-lost-after-commit")
        return "accepted"

    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        patch_applier=patch_applier,
        browser_checker=lambda _scenario: (_ for _ in ()).throw(
            AssertionError("browser-must-not-run")
        ),
        revision_verifier=lambda **kwargs: verified.append(deepcopy(kwargs)),
    )
    actions.current_projection = {
        "location": "Central US",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {REGISTRY_ID: {}},
        },
        "properties": {"template": _app()["properties"]["template"]},
    }
    actions._immutable_configuration = deepcopy(
        _app()["properties"]["configuration"]
    )
    context = {
        "candidate_image_digest": "sha256:" + ("c" * 64),
        "vault_url": "https://newcaostone-ai-kv.vault.azure.net",
        "managed_identity_client_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    }

    with pytest.raises(
        AzureAIEnablementActionInvalid,
        match="ai_enablement_patch_unconfirmed",
    ):
        actions.operation_executor(
            "provider_failure_rehearsal",
            environment={},
            secret_value=None,
            context=context,
        )

    assert len(patches) == 2
    assert len(verified) == 1
    assert verified[0]["enabled"] is False
    assert verified[0]["revision"].startswith(
        "newcaostone-demo-app--recover-p-"
    )


def test_emergency_recovery_verifies_disabled_and_overwrites_real_secret_once() -> None:
    patches: list[dict[str, object]] = []
    verified: list[dict[str, object]] = []
    writer = _SecretWriter()

    def patch_applier(patch, *, revision_suffix):
        patches.append(deepcopy(patch))
        return "accepted"

    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        patch_applier=patch_applier,
        revision_verifier=lambda **kwargs: verified.append(deepcopy(kwargs)),
        secret_writer=writer,
    )
    actions.current_projection = {
        "location": "Central US",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {REGISTRY_ID: {}},
        },
        "properties": {"template": _app()["properties"]["template"]},
    }
    actions._immutable_configuration = deepcopy(
        _app()["properties"]["configuration"]
    )
    context = {
        "candidate_image_digest": "sha256:" + ("c" * 64),
        "vault_url": "https://newcaostone-ai-kv.vault.azure.net",
        "managed_identity_client_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    }

    actions.emergency_recovery(
        context=context,
        real_secret_write_attempted=True,
    )

    assert len(patches) == 1
    assert len(verified) == 1
    assert verified[0]["enabled"] is False
    assert [kind for kind, _value in writer.writes] == ["emergency"]


def test_patch_success_is_acknowledgement_only_after_arm_completion() -> None:
    app_resource_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-bizpulse-centralus/"
        "providers/Microsoft.App/containerApps/newcaostone-demo-app"
    )
    operation_url = (
        f"https://management.azure.com/subscriptions/{SUBSCRIPTION}/providers/"
        "Microsoft.App/locations/centralus/operations/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        "?api-version=2025-01-01"
    )
    calls: list[str] = []
    responses = iter(
        (
            ARMResponse(
                status_code=202,
                headers={"Azure-AsyncOperation": operation_url},
                payload={},
            ),
            ARMResponse(
                status_code=200,
                headers={},
                payload={
                    "id": APP_RESOURCE_ID,
                    "provisioningState": "Succeeded",
                },
            ),
        )
    )
    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        monotonic=lambda: 0.0,
        sleeper=lambda _seconds: None,
        arm_requester=lambda method, _url, _body: calls.append(method)
        or next(responses),
    )

    acknowledgement = actions._apply_patch_azure(
        {"location": "Central US", "identity": {}, "properties": {"template": {}}},
        revision_suffix="ai-off-33333333-ccccccc",
    )

    assert acknowledgement == "accepted"
    assert calls == ["PATCH", "GET"]
    assert app_resource_id.endswith("containerApps/newcaostone-demo-app")


def test_browser_operator_credential_is_scoped_to_browser_child_only() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    arm_calls: list[str] = []

    def runner(command, **kwargs):
        captured_kwargs = dict(kwargs)
        captured_kwargs["env"] = dict(kwargs["env"])
        calls.append((tuple(command), captured_kwargs))
        if command[0] == "node":
            stdout = json.dumps(
                {
                    "scenario": "ai-disabled",
                    "externalRequests": 0,
                    "consoleErrors": 0,
                    "providerTurns": 0,
                }
            )
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        runner=runner,
        environment={
            "HOME": "/safe-home",
            "PATH": "/safe-bin",
            "BIZPULSE_BROWSER_OPERATOR_PASSWORD": "ambient-must-not-inherit",
        },
        browser_credential_provider=lambda: "operator-secret",
        arm_requester=lambda method, _url, _body: arm_calls.append(method)
        or ARMResponse(
            status_code=200,
            headers={},
            payload={
                "id": (
                    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/"
                    "rg-bizpulse-centralus/providers/Microsoft.App/"
                    "containerApps/newcaostone-demo-app"
                )
            },
        ),
    )
    actions._prepare_browser_credential()
    actions._hosted_url = "https://newcaostone-demo-app.example.azurecontainerapps.io"

    assert actions._apply_patch_azure(
        {"location": "Central US", "identity": {}, "properties": {"template": {}}},
        revision_suffix="ai-off-33333333-ccccccc",
    ) == "accepted"
    actions._run_browser_gate("ai-disabled")

    browser_command, browser_kwargs = calls[0]
    assert arm_calls == ["PATCH"]
    assert browser_command[0] == "node"
    assert browser_kwargs["env"] == {
        "HOME": "/safe-home",
        "PATH": "/safe-bin",
        "BIZPULSE_BROWSER_OPERATOR_PASSWORD": "operator-secret",
    }


@pytest.mark.parametrize(
    "response",
    [
        ARMResponse(status_code=200, headers={}, payload={"id": "/subscriptions/wrong"}),
        ARMResponse(status_code=409, headers={}, payload={}),
    ],
)
def test_patch_wrong_resource_or_failed_response_stops_without_retry(
    response: ARMResponse,
) -> None:
    calls = 0

    def arm_requester(_method, _url, _body):
        nonlocal calls
        calls += 1
        return response

    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        arm_requester=arm_requester,
    )
    with pytest.raises(
        AzureAIEnablementActionInvalid,
        match="ai_enablement_patch_unconfirmed",
    ):
        actions._apply_patch_azure(
            {"location": "Central US"},
            revision_suffix="ai-off-33333333-ccccccc",
        )
    assert calls == 1


@pytest.mark.parametrize(
    ("state", "enabled_role", "recovery_role", "browser_scenario"),
    [
        (
            "budget_failure_rehearsal",
            "budget_enabled",
            "budget_recovery",
            "budget",
        ),
        (
            "provider_failure_rehearsal",
            "provider_enabled",
            "provider_recovery",
            "provider-unavailable",
        ),
    ],
)
def test_rehearsal_reconciles_enabled_before_browser_and_disabled_after(
    state: str,
    enabled_role: str,
    recovery_role: str,
    browser_scenario: str,
) -> None:
    events: list[str] = []

    def patch_applier(_patch, *, revision_suffix):
        label = revision_suffix.split("-", 1)[0]
        if revision_suffix.startswith("recover-"):
            label = "recover-" + revision_suffix.split("-", 2)[1]
        events.append(f"patch:{label}")
        return "accepted"

    def revision_verifier(**kwargs):
        role = str(kwargs.get("role", "missing"))
        events.append(f"reconcile:{role}")
        return {"role": role}

    def browser_checker(scenario: str) -> None:
        events.append(f"browser:{scenario}")

    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        patch_applier=patch_applier,
        revision_verifier=revision_verifier,
        browser_checker=browser_checker,
    )
    actions.current_projection = {
        "location": "Central US",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {REGISTRY_ID: {}},
        },
        "properties": {"template": _app()["properties"]["template"]},
    }
    actions._immutable_configuration = deepcopy(
        _app()["properties"]["configuration"]
    )
    actions._current_revision = ROLLBACK_REVISION
    context = {
        "candidate_image_digest": "sha256:" + ("c" * 64),
        "vault_url": "https://newcaostone-ai-kv.vault.azure.net",
        "managed_identity_client_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    }

    actions.operation_executor(
        state,
        environment={},
        secret_value=None,
        context=context,
    )

    enabled_label = "budget" if state.startswith("budget") else "provider"
    recovery_label = "recover-b" if state.startswith("budget") else "recover-p"
    assert events == [
        f"patch:{enabled_label}",
        f"reconcile:{enabled_role}",
        f"browser:{browser_scenario}",
        f"patch:{recovery_label}",
        f"reconcile:{recovery_role}",
    ]


def test_emergency_placeholder_runs_after_failed_disabled_reconciliation() -> None:
    events: list[str] = []

    def patch_applier(_patch, *, revision_suffix):
        events.append(f"patch:{revision_suffix.split('-', 1)[0]}")
        return "accepted"

    def revision_verifier(**kwargs):
        events.append(f"reconcile:{kwargs.get('role', 'missing')}")
        raise RuntimeError("synthetic-disabled-timeout")

    def secret_writer(_value: str, *, write_kind: str) -> None:
        events.append(f"secret:{write_kind}")

    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        patch_applier=patch_applier,
        revision_verifier=revision_verifier,
        secret_writer=secret_writer,
    )
    actions.current_projection = {
        "location": "Central US",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {REGISTRY_ID: {}, AI_IDENTITY: {}},
        },
        "properties": {"template": _app()["properties"]["template"]},
    }
    actions._immutable_configuration = deepcopy(
        _app()["properties"]["configuration"]
    )
    actions._current_revision = "newcaostone-demo-app--ai-on-current"
    context = {
        "candidate_image_digest": "sha256:" + ("c" * 64),
        "vault_url": "https://newcaostone-ai-kv.vault.azure.net",
        "managed_identity_client_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    }

    with pytest.raises(
        AzureAIEnablementActionInvalid,
        match="ai_enablement_emergency_disable_failed",
    ):
        actions.emergency_recovery(
            context=context,
            real_secret_write_attempted=True,
        )

    assert events == [
        "patch:abort",
        "reconcile:emergency_disabled",
        "secret:emergency",
    ]


class _ReconciliationClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def _azure_defaulted_template(template: object) -> dict[str, object]:
    assert isinstance(template, dict)
    raw = deepcopy(template)
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


def test_default_revision_verifier_canonicalizes_application_template_with_narrow_revision_state() -> None:
    suffix = "ai-off-33333333-ccccccc"
    target_revision = f"newcaostone-demo-app--{suffix}"
    target_image = "sellernorthbpacr.azurecr.io/bizpulse@sha256:" + ("c" * 64)
    predecessor_projection = {
        "location": "Central US",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {REGISTRY_ID: {}},
        },
        "properties": {"template": _app()["properties"]["template"]},
    }
    target_projection = build_ai_revision_patch(
        predecessor_projection,
        enabled=False,
        candidate_image=target_image,
        revision_suffix=suffix,
        ai_identity_resource_id=AI_IDENTITY,
    )
    clock = _ReconciliationClock()
    app_reads = 0
    revision_reads = 0

    def runner(command, **_kwargs):
        nonlocal app_reads, revision_reads
        if command[:3] == ["az", "containerapp", "show"]:
            app_reads += 1
            ready = ROLLBACK_REVISION if app_reads == 1 else target_revision
            payload = deepcopy(target_projection)
            payload["properties"] = {
                "configuration": deepcopy(
                    _app()["properties"]["configuration"]
                ),
                "latestRevisionName": target_revision,
                "latestReadyRevisionName": ready,
                "provisioningState": "Succeeded",
                "template": _azure_defaulted_template(
                    target_projection["properties"]["template"]
                ),
            }
        elif command[:4] == ["az", "containerapp", "revision", "list"]:
            revision_reads += 1
            revision_query = command[command.index("--query") + 1]
            assert "template:properties.template" not in revision_query
            payload = [
                {
                    "name": target_revision,
                    "properties": {
                        "active": True,
                        "healthState": None if revision_reads == 1 else "Healthy",
                        "provisioningState": (
                            "Provisioning" if revision_reads == 1 else "Provisioned"
                        ),
                    },
                }
            ]
        else:  # pragma: no cover - unexpected command is the failure
            raise AssertionError(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload),
            stderr="",
        )

    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        runner=runner,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )
    actions._pending_transitions = {
        target_revision: PendingAITransition(
            role="ai_disabled_candidate",
            acknowledgement="accepted",
            started_at=0.0,
            predecessor_revision=ROLLBACK_REVISION,
            target_revision=target_revision,
            predecessor_projection=predecessor_projection,
            target_projection=target_projection,
            target_image=target_image,
            immutable_configuration=deepcopy(
                _app()["properties"]["configuration"]
            ),
        )
    }

    evidence = actions._verify_revision(
        enabled=False,
        image=target_image,
        revision=target_revision,
        context={},
        role="ai_disabled_candidate",
    )

    assert evidence["final_state"] == "healthy_target"
    assert evidence["application_read_count"] == 2
    assert evidence["revision_read_count"] == 2
    assert evidence["elapsed_milliseconds"] == 5000
    assert app_reads == 2
    assert revision_reads == 2
