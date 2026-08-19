from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import scripts.run_ai_disabled_recovery as recovery
from scripts.azure_ai_enablement_actions import AzureAIEnablementActionInvalid
from scripts.create_ai_disabled_recovery_package import ARTIFACTS, PROJECT_ROOT
from scripts.create_ai_disabled_recovery_package import (
    generate_ai_disabled_recovery_package,
)
from scripts.run_ai_disabled_recovery import run_ai_disabled_recovery


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
DIGEST = "sha256:" + ("a" * 64)
IMAGE = f"sellernorthbpacr.azurecr.io/bizpulse@{DIGEST}"
REVISION = "newcaostone-demo-app--budget-3ae0101c-4152f5a"


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
        "latest_revision": REVISION,
        "latest_ready_revision": REVISION,
        "image": IMAGE,
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
        "manifest_digest": DIGEST,
    }


def _reconciliation(target_revision: str) -> dict[str, object]:
    return {
        "role": "emergency_disabled",
        "acknowledgement": "accepted",
        "predecessor_revision": REVISION,
        "target_revision": target_revision,
        "target_image_digest": DIGEST,
        "final_state": "healthy_target",
        "application_read_count": 2,
        "revision_read_count": 1,
        "elapsed_milliseconds": 5000,
    }


def test_run_recovery_reserves_receipt_then_executes_one_no_key_transition(
    tmp_path: Path,
) -> None:
    package_path = tmp_path / "r9.json"
    receipt_path = tmp_path / "receipt.json"
    observation_path = tmp_path / "observation.json"
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
    events: list[str] = []
    target_revision = "newcaostone-demo-app--r9-disable-aaaaaaaa-aaaaaaa"

    result = run_ai_disabled_recovery(
        package_path=package_path,
        approved_sha256=str(generated["package_sha256"]),
        receipt_path=receipt_path,
        observation_path=observation_path,
        authority_reader=lambda _package: events.append("read") or _authority(),
        recovery_executor=lambda _package, _sha, _authority: events.append("patch")
        or {
            "target_revision": target_revision,
            "target_image": IMAGE,
            "ai_chat_enabled": False,
            "budget_failure_rehearsal": False,
            "identity_ids": [REGISTRY_IDENTITY],
            "reconciliation": _reconciliation(target_revision),
            "browser": {"externalRequests": 0, "providerTurns": 0},
        },
        now=lambda: datetime(2026, 8, 17, 17, 1, tzinfo=UTC),
    )

    receipt = json.loads(receipt_path.read_text())
    observation = json.loads(observation_path.read_text())
    assert events == ["read", "patch"]
    assert result["target_revision"] == target_revision
    assert receipt["state"] == "completed"
    assert receipt["observation_sha256"] == hashlib.sha256(
        observation_path.read_bytes()
    ).hexdigest()
    assert observation["ai_chat_enabled"] is False
    assert observation["browser"] == {"externalRequests": 0, "providerTurns": 0}
    serialized = receipt_path.read_text() + observation_path.read_text()
    assert "openai-api-key" not in serialized
    assert "sk-" not in serialized


def test_execute_recovery_wires_one_disabled_patch_after_six_read_state(
    tmp_path: Path, monkeypatch
) -> None:
    package_path = tmp_path / "r9.json"
    generated = generate_ai_disabled_recovery_package(
        output_path=package_path,
        receipt_path=tmp_path / "receipt.json",
        observation_path=tmp_path / "observation.json",
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
    events: list[str] = []
    target_revision = "newcaostone-demo-app--r9-disable-aaaaaaaa-aaaaaaa"

    app = {
        "location": "Central US",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {
                REGISTRY_IDENTITY.replace("/resourceGroups/", "/resourcegroups/"): {},
                AI_IDENTITY.replace("/resourceGroups/", "/resourcegroups/"): {},
            },
        },
        "properties": {
            "configuration": {
                "activeRevisionsMode": "Single",
                "ingress": {
                    "external": True,
                    "fqdn": "demo.example.azurecontainerapps.io",
                    "traffic": [{"latestRevision": True, "weight": 100}],
                },
                "registries": [
                    {
                        "server": "sellernorthbpacr.azurecr.io",
                        "identity": REGISTRY_IDENTITY,
                        "passwordSecretRef": "",
                        "username": "",
                    }
                ],
            },
            "template": {"opaque": "validated-by-revision-module"},
        },
    }

    instances: list[FakeActions] = []

    class FakeActions:
        def __init__(self, **kwargs) -> None:
            assert kwargs["package"]["candidate"] == {"image_repository": "bizpulse"}
            assert "secret_writer" not in kwargs
            self.current_projection = None
            self._immutable_configuration = None
            self._current_revision = None
            self._hosted_url = None
            instances.append(self)

        def _apply_revision(self, **kwargs):
            events.append("patch")
            assert kwargs["enabled"] is False
            assert kwargs["role"] == "emergency_disabled"
            return target_revision

        def _reconcile_revision(self, **kwargs):
            events.append("reconcile")
            assert kwargs["revision"] == target_revision
            return _reconciliation(target_revision)

        def _prepare_browser_credential(self):
            events.append("browser-credential")

        def _run_browser_gate(self, scenario):
            events.append("browser-gate")
            assert scenario == "ai-disabled"

        def clear_browser_credential(self):
            events.append("browser-credential-cleared")

    monkeypatch.setattr(
        recovery,
        "canonicalize_azure_template_readback",
        lambda _template: {"canonical": "template"},
    )
    monkeypatch.setattr(recovery, "AzureAIEnablementActions", FakeActions)

    result = recovery.execute_azure_ai_disabled_recovery(
        package,
        str(generated["package_sha256"]),
        authority=_authority(),
        app=app,
        runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError),
        browser_credential_provider=lambda: "operator-only",
    )

    assert events == [
        "patch",
        "reconcile",
        "browser-credential",
        "browser-gate",
        "browser-credential-cleared",
    ]
    assert result["identity_ids"] == [REGISTRY_IDENTITY]
    assert result["browser"] == {"externalRequests": 0, "providerTurns": 0}
    assert instances[0]._immutable_configuration == {
        "activeRevisionsMode": "Single",
        "ingress": {
            "external": True,
            "fqdn": "demo.example.azurecontainerapps.io",
            "traffic": [{"latestRevision": True, "weight": 100}],
        },
        "registries": [
            {
                "server": "sellernorthbpacr.azurecr.io",
                "identity": REGISTRY_IDENTITY,
            }
        ],
    }


def test_recovery_cli_maps_adapter_failure_to_closed_output(monkeypatch, capsys) -> None:
    paths = {name: PROJECT_ROOT / path for name, path in ARTIFACTS.items()}
    monkeypatch.setattr(
        recovery,
        "run_ai_disabled_recovery",
        lambda **_kwargs: (_ for _ in ()).throw(
            AzureAIEnablementActionInvalid("ai_enablement_patch_unconfirmed")
        ),
    )

    result = recovery.main(
        [
            "--package",
            str(paths["package"]),
            "--approved-sha256",
            "a" * 64,
            "--receipt",
            str(paths["receipt"]),
            "--observation",
            str(paths["observation"]),
        ]
    )

    assert result == 1
    assert capsys.readouterr().out == "ai_disabled_recovery=failed\n"
