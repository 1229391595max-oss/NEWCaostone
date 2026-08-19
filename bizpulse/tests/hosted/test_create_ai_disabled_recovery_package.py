from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import stat
import subprocess

from scripts.create_ai_disabled_recovery_package import (
    PROJECT_ROOT,
    RECOVERY_CONTROL_PATHS,
    _collect_recovery_control_sha256,
    capture_ai_disabled_recovery_authority,
    generate_ai_disabled_recovery_package,
)


SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"
REGISTRY_IDENTITY = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-bizpulse-centralus/"
    "providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
    "newcaostone-demo-registry"
)
AI_IDENTITY = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-bizpulse-centralus/"
    "providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
    "newcaostone-ai-identity"
)
R8_DIGEST = "sha256:" + ("a" * 64)
R8_IMAGE = f"sellernorthbpacr.azurecr.io/bizpulse@{R8_DIGEST}"
R8_REVISION = "newcaostone-demo-app--budget-3ae0101c-4152f5a"


def _authority() -> dict[str, object]:
    return {
        "subscription_id": SUBSCRIPTION,
        "tenant_id": TENANT,
        "resource_group": "rg-bizpulse-centralus",
        "location": "centralus",
        "app_name": "newcaostone-demo-app",
        "registry_name": "sellernorthbpacr",
        "vault_name": "newcaostone-ai-kv",
        "identity_name": "newcaostone-ai-identity",
        "existing_registry_identity_name": "newcaostone-demo-registry",
        "latest_revision": R8_REVISION,
        "latest_ready_revision": R8_REVISION,
        "image": R8_IMAGE,
        "active_revisions_mode": "Single",
        "traffic": [{"latestRevision": True, "weight": 100}],
        "ai_chat_enabled": True,
        "budget_failure_rehearsal": True,
        "identity_ids": [REGISTRY_IDENTITY, AI_IDENTITY],
        "revision_active": True,
        "revision_health": "Healthy",
        "revision_provisioning": "Provisioned",
        "vault_rbac_enabled": True,
        "vault_public_network_enabled": True,
        "identity_exists": True,
        "manifest_digest": R8_DIGEST,
    }


def test_generate_recovery_package_binds_one_no_key_disabled_transition(
    tmp_path: Path,
) -> None:
    package_path = tmp_path / "r9.json"
    receipt_path = tmp_path / "r9-receipt.json"
    observation_path = tmp_path / "r9-observation.json"

    generated = generate_ai_disabled_recovery_package(
        output_path=package_path,
        receipt_path=receipt_path,
        observation_path=observation_path,
        authority_reader=_authority,
        repository_reader=lambda: {
            "branch": "codex/ai-enable-preset-buttons",
            "head_sha": "b" * 40,
            "tree_sha": "c" * 40,
            "clean": True,
        },
        control_reader=lambda: {"scripts/azure_arm_lro.py": "d" * 64},
        now=lambda: datetime(2026, 8, 17, 17, 0, tzinfo=UTC),
    )

    package = json.loads(package_path.read_text())
    assert stat.S_IMODE(package_path.stat().st_mode) == 0o600
    assert generated["package_sha256"] == hashlib.sha256(package_path.read_bytes()).hexdigest()
    assert "package_sha256" not in package
    assert package["execution"] == {
        "azure.read.sanitized": 6,
        "azure.write.containerapp.patch": 1,
        "keyvault.secret.read": 0,
        "keyvault.secret.write": 0,
        "openai.paid": 0,
    }
    assert package["source"]["ai_chat_enabled"] is True
    assert package["target"]["ai_chat_enabled"] is False
    assert package["target"]["identity_ids"] == [REGISTRY_IDENTITY]
    serialized = json.dumps(package).casefold()
    assert "openai-api-key" not in serialized
    assert "sk-" not in serialized
    assert not receipt_path.exists()
    assert not observation_path.exists()


def test_capture_recovery_authority_uses_only_nonsecret_control_plane_reads() -> None:
    target = {
        key: _authority()[key]
        for key in (
            "subscription_id",
            "tenant_id",
            "resource_group",
            "location",
            "app_name",
            "registry_name",
            "vault_name",
            "identity_name",
            "existing_registry_identity_name",
        )
    }
    calls: list[tuple[str, ...]] = []

    def runner(command, **_kwargs):
        calls.append(tuple(command))
        if command[:3] == ["az", "account", "show"]:
            payload = {"id": SUBSCRIPTION, "tenantId": TENANT}
        elif command[:3] == ["az", "containerapp", "show"]:
            payload = {
                "location": "Central US",
                "identity": {
                    "type": "UserAssigned",
                    "userAssignedIdentities": {REGISTRY_IDENTITY: {}, AI_IDENTITY: {}},
                },
                "properties": {
                    "latestRevisionName": R8_REVISION,
                    "latestReadyRevisionName": R8_REVISION,
                    "provisioningState": "Succeeded",
                    "configuration": {
                        "activeRevisionsMode": "Single",
                        "ingress": {
                            "traffic": [{"latestRevision": True, "weight": 100}],
                        },
                    },
                    "template": {
                        "containers": [
                            {
                                "image": R8_IMAGE,
                                "env": [
                                    {"name": "BIZPULSE_AI_CHAT_ENABLED", "value": "true"},
                                    {
                                        "name": "BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL",
                                        "value": "true",
                                    },
                                ],
                            }
                        ]
                    },
                },
            }
        elif command[:4] == ["az", "containerapp", "revision", "show"]:
            payload = {
                "name": R8_REVISION,
                "properties": {
                    "active": True,
                    "healthState": "Healthy",
                    "provisioningState": "Provisioned",
                },
            }
        elif command[:3] == ["az", "identity", "show"]:
            payload = {"id": AI_IDENTITY.replace("/resourceGroups/", "/resourcegroups/")}
        elif command[:3] == ["az", "keyvault", "show"]:
            payload = {
                "properties": {
                    "enableRbacAuthorization": True,
                    "publicNetworkAccess": "Enabled",
                    "provisioningState": "Succeeded",
                }
            }
        elif command[:4] == ["az", "acr", "manifest", "show-metadata"]:
            payload = {"digest": R8_DIGEST}
        else:  # pragma: no cover - unexpected command fails the contract
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    assert capture_ai_disabled_recovery_authority(
        target,
        runner=runner,
        environment={"PATH": "/safe-bin"},
    ) == _authority()
    assert len(calls) == 6
    assert all("secret" not in " ".join(command).casefold() for command in calls)


def test_recovery_control_hashes_are_limited_to_the_recovery_execution_path() -> None:
    controls = _collect_recovery_control_sha256()

    assert set(controls) == set(RECOVERY_CONTROL_PATHS)
    assert all(len(digest) == 64 for digest in controls.values())
    assert PROJECT_ROOT / "infra/ai_secret_write.bicep" not in {
        PROJECT_ROOT / path for path in controls
    }
