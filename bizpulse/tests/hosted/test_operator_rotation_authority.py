from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from uuid import uuid4

import pytest
from argon2 import PasswordHasher

from scripts.generate_operator_rotation_authority import (
    _DEPLOYMENT_PARAMETER_NAMES,
    PROJECT_ROOT,
    OperatorRotationAuthorityInvalid,
    build_inverse_rotation_authority,
    build_rotation_authority,
    generate_inverse_rotation_authority,
    generate_rotation_authority,
    write_rotation_authority,
)
from scripts.operator_rotation_keychain import OperatorCredentialPair
from src.db.readiness import EXPECTED_SCHEMA_REVISION


def _pair(password: str) -> OperatorCredentialPair:
    password_hash = PasswordHasher(
        time_cost=1,
        memory_cost=1_024,
        parallelism=1,
    ).hash(password)
    return OperatorCredentialPair(password=password, password_hash=password_hash)


def _app(*, revision: str = "bp-demo-app--current-abcdef0") -> dict[str, object]:
    return {
        "name": "bp-demo-app",
        "properties": {
            "provisioningState": "Succeeded",
            "latestReadyRevisionName": revision,
            "latestRevisionName": revision,
            "configuration": {
                "activeRevisionsMode": "Single",
                "ingress": {
                    "fqdn": "bp-demo-app.example.azurecontainerapps.io",
                    "external": True,
                    "traffic": [{"latestRevision": True, "weight": 100}],
                },
            },
            "template": {
                "containers": [
                    {
                        "image": "example.azurecr.io/bizpulse@sha256:" + "a" * 64,
                    }
                ]
            },
        },
    }


def _health() -> dict[str, object]:
    return {
        "status": "ready",
        "checks": {
            "blob": "ok",
            "configuration": "ok",
            "database": "ok",
            "foundation": "ok",
            "migration": EXPECTED_SCHEMA_REVISION,
        },
    }


def _deployment_parameters() -> dict[str, object]:
    return {
        "namePrefix": "bp-demo",
        "location": "centralus",
        "syntheticManifestSha256": "c" * 64,
        "syntheticDatasetVersionId": "00000000-0000-4000-8000-000000000000",
        "registryName": "example",
        "postgresAdministratorLogin": "bpadmin",
        "postgresServerName": "bp-demo-postgres",
        "aiChatEnabled": False,
        "openaiKeyVaultUrl": "",
        "openaiManagedIdentityClientId": "",
        "openaiManagedIdentityResourceId": "",
        "aiBudgetFailureRehearsal": False,
        "aiDailyAttemptLimit": 120,
        "aiMonthlyTokenLimit": 150_000,
        "aiMaxConcurrentTurns": 15,
        "aiSessionAttemptLimitPerMinute": 3,
        "aiGlobalAttemptLimitPerMinute": 20,
        "demoSessionRateLimitPerHour": 50,
        "storageSku": "Standard_LRS",
        "storageAccountName": "bpdemosynthetic",
        "postgresSkuName": "Standard_B1ms",
        "postgresTier": "Burstable",
        "postgresStorageSizeGb": 32,
        "postgresBackupRetentionDays": 7,
        "logRetentionDays": 30,
        "vnetAddressPrefix": "10.40.0.0/16",
        "appSubnetPrefix": "10.40.0.0/23",
        "postgresSubnetPrefix": "10.40.2.0/24",
        "tags": {
            "application": "newcaostone",
            "data_classification": "pure-synthetic",
            "environment": "demo",
            "production_ready": "false",
        },
    }


def test_authority_binds_exact_target_and_redacts_credential_values() -> None:
    current = _pair("current-operator-password")
    pending = _pair("replacement-operator-password")

    authority = build_rotation_authority(
        current=current,
        pending=pending,
        subscription_id="11111111-1111-4111-8111-111111111111",
        resource_group="rg-bizpulse-demo",
        app_name="bp-demo-app",
        image="example.azurecr.io/bizpulse@sha256:" + "a" * 64,
        git_sha="b" * 40,
        deployment_parameters=_deployment_parameters(),
        app=_app(),
        health=_health(),
    )

    assert authority["schema_version"] == "newcaostone.operator-password-rotation.v3"
    assert authority["operation"] == "operator-password-rotation"
    assert authority["target"] == {
        "app": "bp-demo-app",
        "fqdn": "bp-demo-app.example.azurecontainerapps.io",
        "resource_group": "rg-bizpulse-demo",
        "subscription_id": "11111111-1111-4111-8111-111111111111",
    }
    assert authority["source"] == {
        "git_sha": "b" * 40,
        "image": "example.azurecr.io/bizpulse@sha256:" + "a" * 64,
    }
    assert authority["expected"]["active_revision"] == "bp-demo-app--current-abcdef0"
    assert (
        authority["expected"]["old_hash_sha256"]
        != authority["expected"]["new_hash_sha256"]
    )
    assert authority["deployment"]["parameters"] == _deployment_parameters()
    assert authority["delivery"] == {"contract": "job-only-stage-v1"}
    assert len(authority["rotation_id"]) == 64
    serialized = json.dumps(authority, sort_keys=True)
    assert current.password not in serialized
    assert current.password_hash not in serialized
    assert pending.password not in serialized
    assert pending.password_hash not in serialized


def test_generator_binds_live_image_separately_from_candidate_image() -> None:
    current = _pair("current-operator-password")
    pending = _pair("replacement-operator-password")
    live_image = "example.azurecr.io/bizpulse@sha256:" + "a" * 64
    candidate_image = "example.azurecr.io/bizpulse@sha256:" + "b" * 64

    class Keychain:
        def current_pair(self):
            return current

        def pending_pair(self):
            return pending

    authority = generate_rotation_authority(
        subscription_id="11111111-1111-4111-8111-111111111111",
        resource_group="rg-bizpulse-demo",
        app_name="bp-demo-app",
        image=candidate_image,
        git_sha="c" * 40,
        deployment_parameters=_deployment_parameters(),
        keychain=Keychain(),
        az_reader=lambda _arguments: _app(),
        health_reader=lambda _url: _health(),
    )

    assert authority["source"] == {"git_sha": "c" * 40, "image": candidate_image}
    assert authority["expected"]["active_image"] == live_image
    assert "active_image_matches" in authority["preconditions"]


def test_authority_rejects_unhealthy_or_unchanged_pending_credential() -> None:
    current = _pair("current-operator-password")

    with pytest.raises(
        OperatorRotationAuthorityInvalid, match="pending_pair_matches_current"
    ):
        build_rotation_authority(
            current=current,
            pending=current,
            subscription_id="11111111-1111-4111-8111-111111111111",
            resource_group="rg-bizpulse-demo",
            app_name="bp-demo-app",
            image="example.azurecr.io/bizpulse@sha256:" + "a" * 64,
            git_sha="b" * 40,
            deployment_parameters=_deployment_parameters(),
            app=_app(),
            health=_health(),
        )

    unhealthy = _health()
    unhealthy["checks"] = {"database": "failed"}
    with pytest.raises(
        OperatorRotationAuthorityInvalid, match="hosted_health_not_ready"
    ):
        build_rotation_authority(
            current=current,
            pending=_pair("replacement-operator-password"),
            subscription_id="11111111-1111-4111-8111-111111111111",
            resource_group="rg-bizpulse-demo",
            app_name="bp-demo-app",
            image="example.azurecr.io/bizpulse@sha256:" + "a" * 64,
            git_sha="b" * 40,
            deployment_parameters=_deployment_parameters(),
            app=_app(),
            health=unhealthy,
        )


def test_authority_write_is_mode_600_and_refuses_different_reuse() -> None:
    authority = build_rotation_authority(
        current=_pair("current-operator-password"),
        pending=_pair("replacement-operator-password"),
        subscription_id="11111111-1111-4111-8111-111111111111",
        resource_group="rg-bizpulse-demo",
        app_name="bp-demo-app",
        image="example.azurecr.io/bizpulse@sha256:" + "a" * 64,
        git_sha="b" * 40,
        deployment_parameters=_deployment_parameters(),
        app=_app(),
        health=_health(),
    )
    output = PROJECT_ROOT / ".tmp" / f"rotation-test-{uuid4().hex}.json"
    try:
        write_rotation_authority(output, authority)

        assert stat.S_IMODE(output.stat().st_mode) == 0o600
        assert json.loads(output.read_text()) == authority
        changed = {**authority, "rotation_id": "f" * 64}
        with pytest.raises(
            OperatorRotationAuthorityInvalid,
            match="authority_output_conflict",
        ):
            write_rotation_authority(output, changed)
        os.chmod(output, 0o644)
        with pytest.raises(
            OperatorRotationAuthorityInvalid,
            match="authority_output_permissions_invalid",
        ):
            write_rotation_authority(output, authority)
    finally:
        output.unlink(missing_ok=True)


def test_authority_rejects_a_deployment_profile_with_a_secret_or_wrong_image() -> None:
    current = _pair("current-operator-password")
    pending = _pair("replacement-operator-password")
    invalid_parameters = _deployment_parameters() | {
        "operatorPasswordHash": "must-not-be-in-a-package"
    }

    with pytest.raises(
        OperatorRotationAuthorityInvalid,
        match="deployment_parameters_invalid",
    ):
        build_rotation_authority(
            current=current,
            pending=pending,
            subscription_id="11111111-1111-4111-8111-111111111111",
            resource_group="rg-bizpulse-demo",
            app_name="bp-demo-app",
            image="example.azurecr.io/bizpulse@sha256:" + "a" * 64,
            git_sha="b" * 40,
            deployment_parameters=invalid_parameters,
            app=_app(),
            health=_health(),
        )


def test_authority_binds_key_vault_ai_configuration_only_when_enabled() -> None:
    current = _pair("current-operator-password")
    pending = _pair("replacement-operator-password")
    ai_parameters = _deployment_parameters() | {
        "aiChatEnabled": True,
        "openaiKeyVaultUrl": "https://bp-ai.vault.azure.net/",
        "openaiManagedIdentityClientId": "11111111-1111-4111-8111-111111111111",
        "openaiManagedIdentityResourceId": (
            "/subscriptions/11111111-1111-4111-8111-111111111111/"
            "resourceGroups/rg-bizpulse-demo/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/bp-ai"
        ),
    }

    authority = build_rotation_authority(
        current=current,
        pending=pending,
        subscription_id="11111111-1111-4111-8111-111111111111",
        resource_group="rg-bizpulse-demo",
        app_name="bp-demo-app",
        image="example.azurecr.io/bizpulse@sha256:" + "a" * 64,
        git_sha="b" * 40,
        deployment_parameters=ai_parameters,
        app=_app(),
        health=_health(),
    )

    assert authority["deployment"]["parameters"] == ai_parameters
    with pytest.raises(
        OperatorRotationAuthorityInvalid,
        match="deployment_parameters_invalid",
    ):
        build_rotation_authority(
            current=current,
            pending=pending,
            subscription_id="11111111-1111-4111-8111-111111111111",
            resource_group="rg-bizpulse-demo",
            app_name="bp-demo-app",
            image="example.azurecr.io/bizpulse@sha256:" + "a" * 64,
            git_sha="b" * 40,
            deployment_parameters=ai_parameters | {"openaiKeyVaultSecretName": ""},
            app=_app(),
            health=_health(),
        )


def test_rotation_profile_has_direct_parity_with_compiled_main_bicep() -> None:
    az = shutil.which("az")
    assert az is not None, "azure_cli_missing_for_local_bicep_compile"
    completed = subprocess.run(
        [
            az,
            "bicep",
            "build",
            "--file",
            str(PROJECT_ROOT / "infra/main.bicep"),
            "--stdout",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    compiled = json.loads(completed.stdout)
    compiled_parameters = set(compiled["parameters"])
    execution_only = {
        "applicationEnabled",
        "applicationRevisionSuffix",
        "containerImage",
        "deploymentEnabled",
        "operatorPasswordHash",
        "operatorRotationEnabled",
        "operatorRotationExpectedHashFingerprint",
        "operatorRotationId",
        "operatorRotationPasswordHash",
        "postgresAdministratorPassword",
        "sessionPepper",
    }

    assert _DEPLOYMENT_PARAMETER_NAMES == compiled_parameters - execution_only
    assert "openaiKeyVaultSecretName" not in _DEPLOYMENT_PARAMETER_NAMES
    serialized = json.dumps(compiled, sort_keys=True)
    assert "BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME" in serialized
    assert "openai-api-key" in serialized


def test_inverse_authority_reverses_only_the_original_pair_and_keeps_values_redacted() -> (
    None
):
    current = _pair("current-operator-password")
    pending = _pair("replacement-operator-password")
    forward = build_rotation_authority(
        current=current,
        pending=pending,
        subscription_id="11111111-1111-4111-8111-111111111111",
        resource_group="rg-bizpulse-demo",
        app_name="bp-demo-app",
        image="example.azurecr.io/bizpulse@sha256:" + "a" * 64,
        git_sha="b" * 40,
        deployment_parameters=_deployment_parameters(),
        app=_app(),
        health=_health(),
    )

    inverse = build_inverse_rotation_authority(
        forward_authority=forward,
        current=current,
        pending=pending,
        app=_app(revision="bp-demo-app--rotate-0123456789ab"),
    )

    assert inverse["operation"] == "operator-password-inverse"
    assert inverse["inverse_of"] == forward["rotation_id"]
    assert (
        inverse["expected"]["old_hash_sha256"] == forward["expected"]["new_hash_sha256"]
    )
    assert (
        inverse["expected"]["new_hash_sha256"] == forward["expected"]["old_hash_sha256"]
    )
    assert inverse["expected"]["active_revision"] == "bp-demo-app--rotate-0123456789ab"
    serialized = json.dumps(inverse, sort_keys=True)
    assert current.password not in serialized
    assert current.password_hash not in serialized
    assert pending.password not in serialized
    assert pending.password_hash not in serialized

    with pytest.raises(
        OperatorRotationAuthorityInvalid, match="inverse_keychain_drift"
    ):
        build_inverse_rotation_authority(
            forward_authority=forward,
            current=_pair("unexpected-current-password"),
            pending=pending,
            app=_app(),
        )

    different_live_image = _app()
    different_live_image["properties"]["template"]["containers"][0]["image"] = (
        "example.azurecr.io/bizpulse@sha256:" + "d" * 64
    )
    different_live_authority = build_rotation_authority(
        current=current,
        pending=pending,
        subscription_id="11111111-1111-4111-8111-111111111111",
        resource_group="rg-bizpulse-demo",
        app_name="bp-demo-app",
        image="example.azurecr.io/bizpulse@sha256:" + "a" * 64,
        git_sha="b" * 40,
        deployment_parameters=_deployment_parameters(),
        app=different_live_image,
        health=_health(),
    )
    assert different_live_authority["source"]["image"] == (
        "example.azurecr.io/bizpulse@sha256:" + "a" * 64
    )
    assert different_live_authority["expected"]["active_image"] == (
        "example.azurecr.io/bizpulse@sha256:" + "d" * 64
    )

    mutable_live_image = _app()
    mutable_live_image["properties"]["template"]["containers"][0]["image"] = (
        "example.azurecr.io/bizpulse:mutable"
    )
    with pytest.raises(
        OperatorRotationAuthorityInvalid, match="azure_app_state_invalid"
    ):
        build_rotation_authority(
            current=current,
            pending=pending,
            subscription_id="11111111-1111-4111-8111-111111111111",
            resource_group="rg-bizpulse-demo",
            app_name="bp-demo-app",
            image="example.azurecr.io/bizpulse@sha256:" + "a" * 64,
            git_sha="b" * 40,
            deployment_parameters=_deployment_parameters(),
            app=mutable_live_image,
            health=_health(),
        )


def test_inverse_generator_reads_only_the_bound_app_and_local_pairs() -> None:
    current = _pair("current-operator-password")
    pending = _pair("replacement-operator-password")
    forward = build_rotation_authority(
        current=current,
        pending=pending,
        subscription_id="11111111-1111-4111-8111-111111111111",
        resource_group="rg-bizpulse-demo",
        app_name="bp-demo-app",
        image="example.azurecr.io/bizpulse@sha256:" + "a" * 64,
        git_sha="b" * 40,
        deployment_parameters=_deployment_parameters(),
        app=_app(),
        health=_health(),
    )

    class Keychain:
        def current_pair(self):
            return current

        def pending_pair(self):
            return pending

    calls: list[tuple[str, ...]] = []
    inverse = generate_inverse_rotation_authority(
        forward_authority=forward,
        keychain=Keychain(),
        az_reader=lambda arguments: (
            calls.append(tuple(arguments))
            or _app(revision="bp-demo-app--rotate-0123456789ab")
        ),
    )

    assert inverse["operation"] == "operator-password-inverse"
    assert calls == [
        (
            "containerapp",
            "show",
            "--subscription",
            "11111111-1111-4111-8111-111111111111",
            "--resource-group",
            "rg-bizpulse-demo",
            "--name",
            "bp-demo-app",
        )
    ]
