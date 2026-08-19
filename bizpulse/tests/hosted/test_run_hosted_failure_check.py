from __future__ import annotations

from copy import deepcopy
import inspect

import pytest

from scripts.run_hosted_failure_check import (
    HostedFailureCheckInvalid,
    main,
    run_failure_check,
)


SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"
AUTHORIZATION = "22222222-2222-4222-8222-222222222222"
REGISTRY_IDENTITY_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-approved/"
    "providers/Microsoft.ManagedIdentity/userAssignedIdentities/bp-registry"
)
AI_IDENTITY_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-approved/"
    "providers/Microsoft.ManagedIdentity/userAssignedIdentities/bp-ai-identity"
)
IMAGE = "bpapprovedregistry.azurecr.io/bizpulse@sha256:" + ("b" * 64)


def _projection() -> dict[str, object]:
    return {
        "location": "Central US",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {REGISTRY_IDENTITY_ID: {}},
        },
        "properties": {
            "template": {
                "revisionSuffix": "ai-disabled-bbbbbbb",
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
                                "value": "synthetic-demo",
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
                                "value": "120",
                            },
                            {
                                "name": "BIZPULSE_AI_MONTHLY_TOKEN_LIMIT",
                                "value": "150000",
                            },
                            {
                                "name": "BIZPULSE_AI_MAX_CONCURRENT_TURNS",
                                "value": "15",
                            },
                            {
                                "name": (
                                    "BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE"
                                ),
                                "value": "3",
                            },
                            {
                                "name": (
                                    "BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE"
                                ),
                                "value": "20",
                            },
                            {
                                "name": "BIZPULSE_DEMO_SESSION_RATE_LIMIT_PER_HOUR",
                                "value": "50",
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


def _run(
    *,
    scenario: str,
    patch_applier,
    browser_checker=lambda **_values: None,
):
    return run_failure_check(
        current_projection=_projection(),
        subscription_id=SUBSCRIPTION,
        resource_group="rg-approved",
        app_name="bp-approved-app",
        image=IMAGE,
        authorization_id=AUTHORIZATION,
        scenario=scenario,
        ai_identity_resource_id=AI_IDENTITY_ID,
        vault_url="https://bp-ai-kv.vault.azure.net",
        secret_name="openai-api-key",
        managed_identity_client_id="33333333-3333-4333-8333-333333333333",
        patch_applier=patch_applier,
        browser_checker=browser_checker,
    )


def _environment(patch: dict[str, object]) -> dict[str, dict[str, object]]:
    rows = patch["properties"]["template"]["containers"][0]["env"]
    return {row["name"]: row for row in rows}


@pytest.mark.parametrize(
    ("scenario", "rehearsal_expected", "suffix"),
    [
        ("budget", True, "budget-22222222-bbbbbbb"),
        ("provider-unavailable", False, "provider-22222222-bbbbbbb"),
    ],
)
def test_failure_rehearsal_uses_two_nonsecret_allowlisted_revision_patches(
    scenario: str,
    rehearsal_expected: bool,
    suffix: str,
) -> None:
    patches: list[dict[str, object]] = []
    browser_calls: list[dict[str, object]] = []

    result = _run(
        scenario=scenario,
        patch_applier=lambda patch: patches.append(deepcopy(patch)),
        browser_checker=lambda **values: browser_calls.append(values),
    )

    assert result == {
        "scenario": scenario,
        "rehearsal_revision_suffix": suffix,
        "recovery_revision_suffix": (
            f"recover-{scenario[0]}-22222222-bbbbbbb"
        ),
        "patch_count": 2,
    }
    assert len(patches) == 2
    enabled, recovered = patches
    for patch in patches:
        assert set(patch) == {"location", "identity", "properties"}
        assert set(patch["properties"]) == {"template"}
        assert "configuration" not in patch["properties"]
        assert "OPENAI_API_KEY" not in repr(patch)
        assert "OPENAI_BASE_URL" not in repr(patch)
    assert AI_IDENTITY_ID in enabled["identity"]["userAssignedIdentities"]
    assert recovered["identity"]["userAssignedIdentities"][AI_IDENTITY_ID] is None
    enabled_env = _environment(enabled)
    recovered_env = _environment(recovered)
    assert enabled_env["BIZPULSE_AI_CHAT_ENABLED"]["value"] == "true"
    assert (
        "BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL" in enabled_env
    ) is rehearsal_expected
    assert enabled_env["BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME"]["value"] == (
        "openai-api-key"
    )
    assert recovered_env["BIZPULSE_AI_CHAT_ENABLED"]["value"] == "false"
    assert "BIZPULSE_OPENAI_KEY_VAULT_URL" not in recovered_env
    assert browser_calls == [
        {
            "scenario": scenario,
            "expected_revision_suffix": suffix,
        }
    ]


def test_browser_failure_recovers_once_before_safe_error() -> None:
    patches: list[dict[str, object]] = []

    with pytest.raises(
        HostedFailureCheckInvalid,
        match="hosted_failure_rehearsal_failed",
    ):
        _run(
            scenario="budget",
            patch_applier=lambda patch: patches.append(deepcopy(patch)),
            browser_checker=lambda **_values: (_ for _ in ()).throw(
                RuntimeError("unsafe remote detail")
            ),
        )

    assert len(patches) == 2
    assert _environment(patches[-1])["BIZPULSE_AI_CHAT_ENABLED"]["value"] == (
        "false"
    )


def test_first_patch_failure_stops_without_retry_cleanup_or_browser() -> None:
    patch_calls = 0
    browser_calls = 0

    def patch_applier(_patch) -> None:
        nonlocal patch_calls
        patch_calls += 1
        raise RuntimeError("unconfirmed")

    def browser_checker(**_values) -> None:
        nonlocal browser_calls
        browser_calls += 1

    with pytest.raises(
        HostedFailureCheckInvalid,
        match="hosted_failure_patch_unconfirmed",
    ):
        _run(
            scenario="budget",
            patch_applier=patch_applier,
            browser_checker=browser_checker,
        )

    assert patch_calls == 1
    assert browser_calls == 0


def test_projection_mismatch_stops_before_any_action() -> None:
    projection = _projection()
    projection["properties"]["configuration"] = {
        "secrets": [{"name": "database-url"}]
    }
    calls: list[object] = []

    with pytest.raises(
        HostedFailureCheckInvalid,
        match="hosted_failure_authority_invalid",
    ):
        run_failure_check(
            current_projection=projection,
            subscription_id=SUBSCRIPTION,
            resource_group="rg-approved",
            app_name="bp-approved-app",
            image=IMAGE,
            authorization_id=AUTHORIZATION,
            scenario="budget",
            ai_identity_resource_id=AI_IDENTITY_ID,
            vault_url="https://bp-ai-kv.vault.azure.net",
            secret_name="openai-api-key",
            managed_identity_client_id=(
                "33333333-3333-4333-8333-333333333333"
            ),
            patch_applier=lambda patch: calls.append(patch),
            browser_checker=lambda **values: calls.append(values),
        )
    assert calls == []


def test_source_has_no_broad_deployment_key_or_secret_read_path() -> None:
    source = inspect.getsource(
        __import__(
            "scripts.run_hosted_failure_check",
            fromlist=["run_hosted_failure_check"],
        )
    )
    signature = inspect.signature(run_failure_check)

    assert "deployment group" not in source
    assert '"deployment", "group"' not in source
    assert "BIZPULSE_DEPLOY_OPENAI_API_KEY" not in source
    assert "OPENAI_API_KEY" not in source
    assert "configuration.secrets" not in source
    assert "list-secrets" not in source
    assert "placeholder_factory" not in source
    assert "api_key" not in signature.parameters
    assert "parameters" not in signature.parameters


def test_standalone_cli_is_inert_until_package_runner_injects_executor(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 2
    captured = capsys.readouterr()
    assert captured.out == "hosted_failure_check=package_runner_required\n"
    assert captured.err == ""
