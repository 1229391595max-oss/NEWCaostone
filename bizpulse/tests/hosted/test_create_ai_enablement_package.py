from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import stat
import subprocess

import pytest

from scripts.ai_enablement_contract import STATE_ORDER
from scripts.admin_ai_current_successor import current_admin_ai_successor_target
from scripts.create_ai_enablement_package import (
    AIEnablementPackageInvalid,
    ARTIFACTS,
    AUTHORIZED_BRANCH,
    CONTROL_PATHS,
    PRIOR_AI_ATTEMPTS,
    _candidate_from_repository,
    build_ai_enablement_package,
    capture_local_candidate_image,
    capture_prior_ai_attempts,
    capture_repository_state,
    generate_ai_enablement_package,
    load_ai_enablement_package,
    validate_ai_enablement_package,
    write_ai_enablement_package,
)
from scripts.create_release_manifest import committed_image_input_sha256


NOW = datetime(2026, 8, 17, 12, 0, 0, tzinfo=UTC)
HEAD = "1" * 40
TREE = "2" * 40
D3_SHA256 = "2ca7c7aa0d133b94607569af437dcf0f6a2b7aa44afc475c332dfe16e0ac8687"
ROLLBACK_DIGEST = (
    "2bf7086bccec9cdb8fb6a9c2c5383909207b021344d8dfee692437829bd87425"
)
ROLLBACK_REVISION = "newcaostone-demo-app--ai-off-9c35ae6a-2bf7086"


def _inputs() -> dict[str, object]:
    return {
        "generated_at": NOW,
        "role_assignment_state": "legacy_only",
        "repository": {
            "branch": "codex/newcaostone-authoritative-v1",
            "head_sha": HEAD,
            "tree_sha": TREE,
            "clean": True,
        },
        "azure_target": {
            "subscription_id": "fc89e7d3-5428-425e-863f-415859810c2c",
            "tenant_id": "13d04c38-d91c-4f9f-8b65-6af2b515dd63",
            "resource_group": "rg-bizpulse-centralus",
            "location": "centralus",
            "app_name": "newcaostone-demo-app",
            "registry_name": "sellernorthbpacr",
            "log_analytics_workspace_name": "newcaostone-demo-logs",
            "existing_registry_identity_name": "newcaostone-demo-registry",
            "rollback_revision": ROLLBACK_REVISION,
            "rollback_image": (
                f"sellernorthbpacr.azurecr.io/bizpulse@sha256:{ROLLBACK_DIGEST}"
            ),
            "vault_name": "newcaostone-ai-kv",
            "identity_name": "newcaostone-ai-identity",
        },
        "candidate": {
            "image_repository": "bizpulse",
            "source_tree_sha": TREE,
            "dockerfile_sha256": "3" * 64,
            "runtime_lock_sha256": "4" * 64,
            "image_input_sha256": "5" * 64,
            "candidate_image_digest": None,
        },
        "control_sha256": {
            "infra/ai_enablement.bicep": "6" * 64,
            "infra/ai_secret_write.bicep": "a" * 64,
            "scripts/ai_enablement_contract.py": "7" * 64,
            "scripts/azure_ai_enablement_actions.py": "b" * 64,
            "scripts/azure_ai_reconciliation.py": "c" * 64,
            "scripts/azure_ai_revision.py": "8" * 64,
            "scripts/run_ai_enablement.py": "9" * 64,
        },
        "d3": {
            "branch": "codex/deployed-diagnostic-d3",
            "selected_base_sha": "afd3a2f0a9311aafaca35ad4a412c911aadf1e32",
            "package_sha256": D3_SHA256,
            "package_mode": "0600",
            "receipt_present": False,
            "observation_present": False,
        },
    }


def _package() -> dict[str, object]:
    return build_ai_enablement_package(**_inputs())


def test_package_is_deterministic_exactly_24_hours_and_blank_approval() -> None:
    first = _package()
    second = _package()

    assert first == second
    assert first["schema_version"] == "newcaostone.ai-enablement-package.v2"
    assert first["issued_at"] == "2026-08-17T12:00:00Z"
    assert first["expires_at"] == "2026-08-18T12:00:00Z"
    expires = datetime.fromisoformat(first["expires_at"].replace("Z", "+00:00"))
    issued = datetime.fromisoformat(first["issued_at"].replace("Z", "+00:00"))
    assert expires - issued == timedelta(hours=24)
    assert first["approval"] == {
        "approved_sha256": None,
        "approved_at": None,
    }
    assert first["candidate"]["candidate_image_digest"] is None
    assert first["artifacts"] == ARTIFACTS
    assert first["prior_attempts"] == PRIOR_AI_ATTEMPTS
    assert first["prepackage_gate"] == {
        "required_azure_reads": 12,
        "rollback_revision": ROLLBACK_REVISION,
        "rollback_image": (
            f"sellernorthbpacr.azurecr.io/bizpulse@sha256:{ROLLBACK_DIGEST}"
        ),
        "rollback_registry_tag": "ai-962a4fa43804-9c35ae6a",
        "rollback_identity_state": "registry_plus_ai",
        "replica_count": 1,
        "ai_enabled": False,
        "vault_state": "existing_exact",
        "identity_state": "existing_exact",
        "role_assignment_state": "legacy_only",
        "diagnostic_setting_state": "existing_exact",
        "secret_values_read": 0,
    }


def test_successor_package_accepts_one_fresh_task12_artifact_set() -> None:
    inputs = _inputs()
    inputs["azure_target"] = current_admin_ai_successor_target(
        inputs["azure_target"]
    )
    attempt_id = "11111111-1111-4111-8111-111111111111"
    artifacts = {
        "package_path": (
            f".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_TASK12_{attempt_id}.json"
        ),
        "receipt_path": f".tmp/AI_ENABLEMENT_RECEIPT_TASK12_{attempt_id}.json",
        "observation_path": (
            f".tmp/AI_ENABLEMENT_OBSERVATION_TASK12_{attempt_id}.json"
        ),
    }

    package = build_ai_enablement_package(**inputs, artifacts=artifacts)

    assert package["artifacts"] == artifacts
    assert package["azure_target"]["rollback_revision"] == (
        "newcaostone-demo-app--recover-b-9c35ae6a-2bf7086"
    )
    assert package["prepackage_gate"]["rollback_identity_state"] == (
        "registry_only"
    )


def test_successor_package_rejects_historical_r19_target_and_identity() -> None:
    inputs = _inputs()
    attempt_id = "11111111-1111-4111-8111-111111111111"
    artifacts = {
        "package_path": (
            f".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_TASK12_{attempt_id}.json"
        ),
        "receipt_path": f".tmp/AI_ENABLEMENT_RECEIPT_TASK12_{attempt_id}.json",
        "observation_path": (
            f".tmp/AI_ENABLEMENT_OBSERVATION_TASK12_{attempt_id}.json"
        ),
    }

    with pytest.raises(AIEnablementPackageInvalid):
        build_ai_enablement_package(**inputs, artifacts=artifacts)


def test_historical_r19_package_contract_remains_exactly_unchanged() -> None:
    package = _package()

    assert package["azure_target"]["rollback_revision"] == ROLLBACK_REVISION
    assert package["prepackage_gate"]["rollback_identity_state"] == (
        "registry_plus_ai"
    )
    assert validate_ai_enablement_package(package, now=NOW) == package


@pytest.mark.parametrize("attempt_id", ("R19_2026-08-17", "not-a-uuid", ""))
def test_successor_package_rejects_reused_or_nonunique_artifact_ids(
    attempt_id: str,
) -> None:
    inputs = _inputs()
    artifacts = {
        "package_path": (
            f".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_TASK12_{attempt_id}.json"
        ),
        "receipt_path": f".tmp/AI_ENABLEMENT_RECEIPT_TASK12_{attempt_id}.json",
        "observation_path": (
            f".tmp/AI_ENABLEMENT_OBSERVATION_TASK12_{attempt_id}.json"
        ),
    }

    with pytest.raises(AIEnablementPackageInvalid):
        build_ai_enablement_package(**inputs, artifacts=artifacts)


def test_fresh_successor_package_binds_exact_officer_only_phase() -> None:
    inputs = _inputs() | {"role_assignment_state": "officer_only"}

    successor = build_ai_enablement_package(**inputs)

    assert successor["prepackage_gate"]["role_assignment_state"] == (
        "officer_only"
    )


@pytest.mark.parametrize(
    "role_assignment_state",
    ["existing_exact", "legacy_plus_officer", "", "Officer_Only"],
)
def test_package_rejects_unrecognized_role_assignment_phase(
    role_assignment_state: str,
) -> None:
    with pytest.raises(AIEnablementPackageInvalid):
        build_ai_enablement_package(
            **(
                _inputs()
                | {"role_assignment_state": role_assignment_state}
            )
        )


def test_authoritative_closeout_uses_fresh_r19_paths_and_consumes_r18() -> None:
    assert AUTHORIZED_BRANCH == "codex/newcaostone-authoritative-v1"
    assert ARTIFACTS == {
        "package_path": ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R19_2026-08-17.json",
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R19_2026-08-17.json",
        "observation_path": ".tmp/AI_ENABLEMENT_OBSERVATION_R19_2026-08-17.json",
    }
    assert PRIOR_AI_ATTEMPTS["r11"] == {
        "package_path": (
            ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R11_2026-08-17.json"
        ),
        "package_sha256": (
            "d6e79358113e1294c76ba8b95bd5381e6c7a9f9546f454a4fec64ba6ecee2175"
        ),
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R11_2026-08-17.json",
        "observation_path": ".tmp/AI_ENABLEMENT_OBSERVATION_R11_2026-08-17.json",
        "receipt_present": False,
        "observation_present": False,
        "terminal_boundary": "pre_receipt_no_azure_write",
    }
    assert PRIOR_AI_ATTEMPTS["r12"] == {
        "package_path": (
            ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R12_2026-08-17.json"
        ),
        "package_sha256": (
            "d699a6a1c8381c9f7efa556431851f18dcb4a6596c9b458f3512081a7c9a5fae"
        ),
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R12_2026-08-17.json",
        "observation_path": ".tmp/AI_ENABLEMENT_OBSERVATION_R12_2026-08-17.json",
        "receipt_present": False,
        "observation_present": False,
        "terminal_boundary": "pre_receipt_no_azure_write",
        "failure_code": "ai_enablement_browser_credential_unavailable",
    }
    assert PRIOR_AI_ATTEMPTS["r13"] == {
        "package_path": (
            ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R13_2026-08-17.json"
        ),
        "package_sha256": (
            "c45f733ff9a0d8d9c0a6f1200afe466d0f1e496206cef118edd37f95292202af"
        ),
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R13_2026-08-17.json",
        "observation_path": ".tmp/AI_ENABLEMENT_OBSERVATION_R13_2026-08-17.json",
        "receipt_present": False,
        "observation_present": False,
        "terminal_boundary": "pre_receipt_no_azure_write",
        "failure_code": "ai_enablement_browser_credential_unavailable",
    }
    assert PRIOR_AI_ATTEMPTS["r14"] == {
        "package_path": (
            ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R14_2026-08-17.json"
        ),
        "package_sha256": (
            "0d0b5aad962127f98c41db01c4182fb5bdb657ffd2b51265e50ddd386db83d33"
        ),
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R14_2026-08-17.json",
        "observation_path": ".tmp/AI_ENABLEMENT_OBSERVATION_R14_2026-08-17.json",
        "receipt_present": False,
        "observation_present": False,
        "terminal_boundary": "never_submitted_superseded_before_execution",
        "superseded_reason": "hidden_tty_not_user_accessible",
    }
    assert PRIOR_AI_ATTEMPTS["r15"] == {
        "package_path": (
            ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R15_2026-08-17.json"
        ),
        "package_sha256": (
            "541650da4df9a15aa52c0ec7f05356c052c5151f6ac9c495d5b2c85bb30f8e81"
        ),
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R15_2026-08-17.json",
        "receipt_sha256": (
            "73cb734811e6d25b566c724e116e492d5dd6931bfaf4571c1482e90c602a29ac"
        ),
        "receipt_contract": {
            "schema_version": "newcaostone.ai-enablement-attempt.v2",
            "package_sha256": (
                "541650da4df9a15aa52c0ec7f05356c052c5151f6ac9c495d5b2c85bb30f8e81"
            ),
            "state": "failed",
            "failure_code": "ai_enablement_image_publish_failed",
            "completed_states": ["readonly_revalidation"],
            "reconciliations": [],
            "recovery": None,
        },
    }
    assert PRIOR_AI_ATTEMPTS["r16"] == {
        "package_path": (
            ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R16_2026-08-17.json"
        ),
        "package_sha256": (
            "a42dd26e824ffbdbfced0cb1f1ad216af20fd7ed90f439755041806e03e52e2a"
        ),
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R16_2026-08-17.json",
        "receipt_sha256": (
            "54dd3f93c90552d6c27a603e596033e09b4320b25f5bd44e32c4d34f80e953a9"
        ),
        "receipt_contract": {
            "schema_version": "newcaostone.ai-enablement-attempt.v2",
            "package_sha256": (
                "a42dd26e824ffbdbfced0cb1f1ad216af20fd7ed90f439755041806e03e52e2a"
            ),
            "state": "failed",
            "failure_code": "ai_enablement_patch_unconfirmed",
            "completed_states": [
                "readonly_revalidation",
                "publish_candidate_image",
            ],
            "reconciliations": [],
            "recovery": None,
        },
    }
    assert PRIOR_AI_ATTEMPTS["r17"] == {
        "package_path": (
            ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R17_2026-08-17.json"
        ),
        "package_sha256": (
            "8d2c76f25404dc1dec98811390b5f79fe57477706c9f7424ac160ab55d217db2"
        ),
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R17_2026-08-17.json",
        "receipt_sha256": (
            "5b1e34486efb62e664c82c678d190b027edc807b33da961576d0610b5aa0f149"
        ),
        "receipt_contract": {
            "schema_version": "newcaostone.ai-enablement-attempt.v2",
            "package_sha256": (
                "8d2c76f25404dc1dec98811390b5f79fe57477706c9f7424ac160ab55d217db2"
            ),
            "state": "failed",
            "failure_code": "ai_enablement_patch_unconfirmed",
            "completed_states": [
                "readonly_revalidation",
                "publish_candidate_image",
            ],
            "reconciliations": [],
            "recovery": None,
        },
    }
    assert PRIOR_AI_ATTEMPTS["r18"] == {
        "package_path": (
            ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R18_2026-08-17.json"
        ),
        "package_sha256": (
            "227674867e560111d355ba5734045313ba841deb1dfb934193b0f4e2afcc60ad"
        ),
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R18_2026-08-17.json",
        "receipt_sha256": (
            "51dc5bbc0b8dad86115b2a3d5270e717c0ac8c0fd542096e54724b4cea558161"
        ),
        "receipt_contract": {
            "schema_version": "newcaostone.ai-enablement-attempt.v2",
            "package_sha256": (
                "227674867e560111d355ba5734045313ba841deb1dfb934193b0f4e2afcc60ad"
            ),
            "state": "failed",
            "failure_code": "ai_enablement_emergency_disable_failed",
            "completed_states": [
                "readonly_revalidation",
                "publish_candidate_image",
                "activate_ai_disabled_candidate",
                "verify_ai_disabled_candidate",
                "reconcile_ai_vault_identity_role_diagnostics",
            ],
            "reconciliations": [
                {
                    "acknowledgement": "accepted",
                    "application_read_count": 5,
                    "elapsed_milliseconds": 33730,
                    "final_state": "healthy_target",
                    "predecessor_revision": (
                        "newcaostone-demo-app--ai-off-8d2c76f2-ef3d9df"
                    ),
                    "revision_read_count": 5,
                    "role": "ai_disabled_candidate",
                    "target_image_digest": (
                        "sha256:20f39c82b499c98ba10c68129531a46b4fb7fe3a6c4e91a87ddcdff99bfc18c1"
                    ),
                    "target_revision": (
                        "newcaostone-demo-app--ai-off-22767486-20f39c8"
                    ),
                }
            ],
            "recovery": None,
        },
    }
    assert PRIOR_AI_ATTEMPTS["r8"] == {
        "package_path": ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R8_2026-08-17.json",
        "package_sha256": (
            "3ae0101c67d7bfaf6b8fb0c09859306a716b63ed35d61f76f242321e0d59b8e3"
        ),
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R8_2026-08-17.json",
        "receipt_sha256": (
            "fa36c58b7d01ae16769049b22bfff751a55d5bbeb6573932e27bbe2a19ae9a9e"
        ),
        "receipt_contract": {
            "schema_version": "newcaostone.ai-enablement-attempt.v2",
            "package_sha256": (
                "3ae0101c67d7bfaf6b8fb0c09859306a716b63ed35d61f76f242321e0d59b8e3"
            ),
            "state": "failed",
            "failure_code": "ai_enablement_emergency_disable_failed",
            "completed_states": [
                "readonly_revalidation",
                "publish_candidate_image",
                "activate_ai_disabled_candidate",
                "verify_ai_disabled_candidate",
                "create_ai_vault_identity_role_diagnostics",
            ],
            "reconciliations": [
                {
                    "acknowledgement": "accepted",
                    "application_read_count": 7,
                    "elapsed_milliseconds": 46896,
                    "final_state": "healthy_target",
                    "predecessor_revision": (
                        "newcaostone-demo-app--ai-off-e95698c5-c12f2c7"
                    ),
                    "revision_read_count": 6,
                    "role": "ai_disabled_candidate",
                    "target_image_digest": (
                        "sha256:4152f5aa713ab1d3c9cb7dd53894791c7f8e6342c57fc5619f91635ebbb17b2b"
                    ),
                    "target_revision": (
                        "newcaostone-demo-app--ai-off-3ae0101c-4152f5a"
                    ),
                }
            ],
            "recovery": None,
        },
    }


def test_candidate_image_label_hash_uses_the_shared_committed_algorithm() -> None:
    head_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
    ).strip()
    tree_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
    ).strip()

    candidate = _candidate_from_repository(
        {"head_sha": head_sha, "tree_sha": tree_sha}
    )

    assert candidate["image_input_sha256"] == committed_image_input_sha256(head_sha)


def test_package_binds_clean_repository_controls_d3_and_exact_limits() -> None:
    package = _package()

    assert package["repository"] == {
        "branch": "codex/newcaostone-authoritative-v1",
        "head_sha": HEAD,
        "tree_sha": TREE,
        "clean": True,
    }
    assert package["candidate"]["source_tree_sha"] == TREE
    assert package["control_sha256"] == _inputs()["control_sha256"]
    assert package["d3"] == _inputs()["d3"]
    assert package["execution_contract"]["state_order"] == list(STATE_ORDER)
    assert package["execution_contract"]["runtime_limits"][
        "monthly_token_limit"
    ] == 150_000
    assert package["execution_contract"]["paid_calls"] == {
        "model_qualification_cases": 12,
        "hosted_manual_send_smoke": 1,
        "total_maximum": 13,
        "retries_per_call": 0,
    }
    assert package["cost_cap"] == {
        "currency": "USD",
        "maximum_paid_execution": "1.00",
        "maximum_paid_calls": 13,
        "stop_if_price_evidence_missing": True,
    }
    assert package["provider_pricing"] == {
        "model": "gpt-5.4-nano-2026-03-17",
        "official_source": (
            "https://developers.openai.com/api/docs/models/gpt-5.4-nano"
        ),
        "checked_at": "2026-08-17T12:00:00Z",
        "input_usd_per_million_tokens": "0.20",
        "output_usd_per_million_tokens": "1.25",
        "regional_processing_uplift_percent": "10",
        "execution_uses_regional_processing": False,
    }


def test_resource_allowlist_reconciles_only_task_owned_ai_resources() -> None:
    allowlist = _package()["resource_allowlist"]
    assert allowlist == {
        "reconcile": {
            "Microsoft.ManagedIdentity/userAssignedIdentities": 1,
            "Microsoft.KeyVault/vaults": 1,
            "Microsoft.Authorization/roleAssignments": 1,
            "Microsoft.Insights/diagnosticSettings": 1,
        },
        "secret_lifecycle": {
            "target_name": "openai-api-key",
            "placeholder_writes": 1,
            "placeholder_deletes": 0,
            "real_writes": 1,
            "reads_by_runner": 0,
            "emergency_placeholder_overwrite_max": 1,
        },
        "modify": {
            "Microsoft.App/containerApps": 6,
            "allowed_sections": ["identity", "properties.template"],
            "configuration_secret_changes": 0,
            "emergency_ai_disable_max": 1,
        },
        "existing_resource_mutations": {
            "task_owned_vaults": 1,
            "task_owned_identities": 1,
            "task_owned_role_assignments": 1,
            "task_owned_diagnostic_settings": 1,
            "registry_identities": 0,
            "postgres": 0,
            "storage": 0,
        },
    }


def test_package_write_is_owner_only_exclusive_and_hashable(tmp_path: Path) -> None:
    target = tmp_path / "ai-enablement.json"

    write_ai_enablement_package(target, _package())

    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    raw = target.read_bytes()
    assert raw.endswith(b"\n")
    assert load_ai_enablement_package(target, now=NOW) == _package()
    assert len(hashlib.sha256(raw).hexdigest()) == 64
    with pytest.raises(AIEnablementPackageInvalid):
        write_ai_enablement_package(target, _package())


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("approval", "approved_sha256"), "a" * 64),
        (("candidate", "candidate_image_digest"), "sha256:" + ("a" * 64)),
        (("repository", "clean"), False),
        (("d3", "receipt_present"), True),
        (("azure_target", "vault_name"), "sellernorthbp-kv"),
    ],
)
def test_package_rejects_authority_or_d3_drift(
    tmp_path: Path,
    path: tuple[str, str],
    value: object,
) -> None:
    package = _package()
    package[path[0]][path[1]] = value
    target = tmp_path / "invalid.json"
    target.write_text(json.dumps(package), encoding="utf-8")
    target.chmod(0o600)

    with pytest.raises(AIEnablementPackageInvalid):
        load_ai_enablement_package(target, now=NOW)


@pytest.mark.parametrize(
    "unsafe",
    [
        {"api_key": "sentinel"},
        {"public_demo_url": "https://demo.example.test"},
        {"database_url": "prohibited-database-authority"},
        {"operator_password": "sentinel"},
        {"session_pepper": "sentinel"},
        {"keychain_locator": "service/account"},
        {"prompt": "private prompt"},
        {"user_data": "private data"},
    ],
)
def test_package_rejects_prohibited_fields_or_values(
    tmp_path: Path,
    unsafe: dict[str, object],
) -> None:
    package = _package()
    package.update(unsafe)
    target = tmp_path / "unsafe.json"
    target.write_text(json.dumps(package), encoding="utf-8")
    target.chmod(0o600)

    with pytest.raises(AIEnablementPackageInvalid):
        load_ai_enablement_package(target, now=NOW)


def test_package_serialization_contains_no_key_token_url_or_existing_vault() -> None:
    serialized = json.dumps(_package(), sort_keys=True)
    for prohibited in (
        "sk-proj-",
        "Bearer ",
        "OPENAI_API_KEY",
        "BIZPULSE_DEPLOY_OPENAI_API_KEY",
        "postgresql://",
        "AccountKey=",
        "https://demo",
        "sellernorthbp-kv",
    ):
        assert prohibited not in serialized


def test_repository_capture_requires_exact_branch_head_tree_and_clean_status() -> None:
    values = {
        ("branch", "--show-current"): "codex/newcaostone-authoritative-v1\n",
        ("rev-parse", "HEAD"): HEAD + "\n",
        ("rev-parse", "HEAD^{tree}"): TREE + "\n",
        ("status", "--porcelain=v1", "--untracked-files=normal"): "",
    }

    def runner(command, **_kwargs):
        key = tuple(command[1:])
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=values[key],
            stderr="",
        )

    assert capture_repository_state(runner=runner) == {
        "branch": "codex/newcaostone-authoritative-v1",
        "head_sha": HEAD,
        "tree_sha": TREE,
        "clean": True,
    }
    values[("status", "--porcelain=v1", "--untracked-files=normal")] = (
        " M src/config.py\n"
    )
    with pytest.raises(AIEnablementPackageInvalid):
        capture_repository_state(runner=runner)


def test_checked_in_package_controls_are_regular_non_symlink_files() -> None:
    for relative in _inputs()["control_sha256"]:
        path = Path(__file__).resolve().parents[2] / relative
        assert path.is_file()
        assert not path.is_symlink()


def test_generated_package_hashes_every_execution_and_secret_write_control() -> None:
    assert {
        "api/container.py",
        "api/v1/routers/ai_chat.py",
        "api/v1/schemas/ai_chat.py",
        "frontend/assets/features/ask-bizpulse/effects.mjs",
        "frontend/assets/features/ask-bizpulse/state.mjs",
        "frontend/assets/features/ask-bizpulse/view-model.mjs",
        "frontend/assets/features/ask-bizpulse/view.mjs",
        "frontend/assets/i18n/catalog.mjs",
        "infra/ai_enablement.bicep",
        "infra/ai_secret_write.bicep",
        "infra/environments/ai_enablement.bicepparam",
        "infra/environments/ai_secret_write.bicepparam",
        "scripts/ai_enablement_contract.py",
        "scripts/admin_ai_current_successor.py",
        "scripts/azure_ai_enablement_actions.py",
        "scripts/azure_ai_reconciliation.py",
        "scripts/azure_ai_revision.py",
        "scripts/browser_process_env.mjs",
        "scripts/browser_release_gate.mjs",
        "scripts/create_ai_enablement_package.py",
        "scripts/create_release_manifest.py",
        "scripts/publish_registry_image.py",
        "scripts/qualify_openai_model.py",
        "scripts/run_ai_enablement.py",
        "src/ai/openai_gateway.py",
        "src/ai/prompt_catalog.py",
        "src/config.py",
        "src/repositories/ai_chat.py",
        "src/secrets/azure_openai.py",
        "src/services/ai_chat_service.py",
        "requirements.txt",
    } == set(CONTROL_PATHS)


def test_prior_attempts_are_exact_owner_only_consumed_artifacts(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    for attempt in PRIOR_AI_ATTEMPTS.values():
        keys = ["package_path"]
        if attempt.get("receipt_present") is not False:
            keys.append("receipt_path")
        for key in keys:
            relative = attempt[key]
            source = project_root / relative
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            target.chmod(0o600)

    assert capture_prior_ai_attempts(project_root=tmp_path) == PRIOR_AI_ATTEMPTS
    assert PRIOR_AI_ATTEMPTS["r19"]["receipt_contract"] == {
        "schema_version": "newcaostone.ai-enablement-attempt.v2",
        "package_sha256": (
            "9c35ae6a39e6db86b021b9938b966492046f0e745111dab2c1dd8bedbf3ddae9"
        ),
        "state": "failed",
        "failure_code": "ai_enablement_emergency_disable_failed",
        "completed_states": [
            "readonly_revalidation",
            "publish_candidate_image",
            "activate_ai_disabled_candidate",
            "verify_ai_disabled_candidate",
            "reconcile_ai_vault_identity_role_diagnostics",
        ],
        "reconciliations": [
            {
                "acknowledgement": "accepted",
                "application_read_count": 5,
                "elapsed_milliseconds": 33073,
                "final_state": "healthy_target",
                "predecessor_revision": (
                    "newcaostone-demo-app--recover-b-22767486-20f39c8"
                ),
                "revision_read_count": 5,
                "role": "ai_disabled_candidate",
                "target_image_digest": f"sha256:{ROLLBACK_DIGEST}",
                "target_revision": ROLLBACK_REVISION,
            }
        ],
        "recovery": None,
    }

    package_path = tmp_path / PRIOR_AI_ATTEMPTS["r1"]["package_path"]
    package_bytes = package_path.read_bytes()
    duplicate = package_path.with_name("r1-package-copy.json")
    duplicate.write_bytes(package_bytes)
    duplicate.chmod(0o600)
    package_path.unlink()
    package_path.symlink_to(duplicate.name)
    with pytest.raises(AIEnablementPackageInvalid):
        capture_prior_ai_attempts(project_root=tmp_path)
    package_path.unlink()
    package_path.write_bytes(package_bytes)
    package_path.chmod(0o600)

    receipt = tmp_path / PRIOR_AI_ATTEMPTS["r3"]["receipt_path"]
    receipt.write_text('{"state":"completed"}\n', encoding="utf-8")
    receipt.chmod(0o600)
    with pytest.raises(AIEnablementPackageInvalid):
        capture_prior_ai_attempts(project_root=tmp_path)

    receipt.write_bytes(
        (project_root / PRIOR_AI_ATTEMPTS["r3"]["receipt_path"]).read_bytes()
    )
    receipt.chmod(0o600)
    r14_receipt = tmp_path / PRIOR_AI_ATTEMPTS["r14"]["receipt_path"]
    r14_receipt.write_text("{}\n", encoding="utf-8")
    r14_receipt.chmod(0o600)
    with pytest.raises(AIEnablementPackageInvalid):
        capture_prior_ai_attempts(project_root=tmp_path)


@pytest.mark.parametrize("role_assignment_state", ["legacy_only", "officer_only"])
def test_generation_orders_live_gate_before_exact_exclusive_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role_assignment_state: str,
) -> None:
    events: list[str] = []
    repository_reads = 0
    control_reads = 0
    prior_reads = 0

    def repository_reader():
        nonlocal repository_reads
        repository_reads += 1
        events.append(
            "repository:before" if repository_reads == 1 else "repository:after"
        )
        return _inputs()["repository"]

    def control_reader():
        nonlocal control_reads
        control_reads += 1
        events.append("controls:before" if control_reads == 1 else "controls:after")
        return _inputs()["control_sha256"]

    def prior_reader():
        nonlocal prior_reads
        prior_reads += 1
        events.append(
            "prior_attempts:before"
            if prior_reads == 1
            else "prior_attempts:after"
        )
        return PRIOR_AI_ATTEMPTS

    def azure_reader(provisional):
        events.append("azure:read_only")
        assert provisional["prepackage_gate"]["role_assignment_state"] == (
            role_assignment_state
        )
        return {"prepackage_gate_matches": True, "required_azure_reads": 12}

    def local_image_reader(_repository, _candidate):
        events.append("local_image:read_only")
        return {"local_image_ready": True}

    output = tmp_path / ARTIFACTS["package_path"]
    receipt = tmp_path / ARTIFACTS["receipt_path"]
    observation = tmp_path / ARTIFACTS["observation_path"]
    output.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "scripts.create_ai_enablement_package.committed_image_input_sha256",
        lambda _revision: "5" * 64,
    )
    package = generate_ai_enablement_package(
        output_path=output,
        receipt_path=receipt,
        observation_path=observation,
        generated_at=lambda: NOW,
        repository_reader=repository_reader,
        control_reader=control_reader,
        prior_attempts_reader=prior_reader,
        azure_reader=azure_reader,
        local_image_reader=local_image_reader,
        role_assignment_state=role_assignment_state,
    )
    events.append("package:exclusive_write")

    assert events == [
        "repository:before",
        "controls:before",
        "prior_attempts:before",
        "azure:read_only",
        "repository:after",
        "controls:after",
        "prior_attempts:after",
        "local_image:read_only",
        "package:exclusive_write",
    ]
    assert package["issued_at"] == "2026-08-17T12:00:00Z"
    assert package["prepackage_gate"]["role_assignment_state"] == (
        role_assignment_state
    )
    assert output.exists()
    assert not receipt.exists()
    assert not observation.exists()


@pytest.mark.parametrize("failure", ["azure", "repository_after", "local_image"])
def test_generation_failure_leaves_all_r5_artifacts_absent(
    tmp_path: Path,
    failure: str,
) -> None:
    repository_reads = 0

    def repository_reader():
        nonlocal repository_reads
        repository_reads += 1
        repository = dict(_inputs()["repository"])
        if failure == "repository_after" and repository_reads == 2:
            repository["head_sha"] = "f" * 40
        return repository

    def azure_reader(_package):
        if failure == "azure":
            raise RuntimeError("synthetic read failure")
        return {"prepackage_gate_matches": True, "required_azure_reads": 12}

    output = tmp_path / ARTIFACTS["package_path"]
    receipt = tmp_path / ARTIFACTS["receipt_path"]
    observation = tmp_path / ARTIFACTS["observation_path"]
    output.parent.mkdir(parents=True, exist_ok=True)
    with pytest.raises((AIEnablementPackageInvalid, RuntimeError)):
        generate_ai_enablement_package(
            output_path=output,
            receipt_path=receipt,
            observation_path=observation,
            generated_at=lambda: NOW,
            repository_reader=repository_reader,
            control_reader=lambda: _inputs()["control_sha256"],
            prior_attempts_reader=lambda: PRIOR_AI_ATTEMPTS,
            azure_reader=azure_reader,
            local_image_reader=lambda _repository, _candidate: {
                "local_image_ready": failure != "local_image"
            },
            role_assignment_state="legacy_only",
        )

    assert not output.exists()
    assert not receipt.exists()
    assert not observation.exists()


def test_local_candidate_gate_requires_exact_linux_amd64_nonroot_labels() -> None:
    repository = {"head_sha": HEAD}
    candidate = {"image_input_sha256": "5" * 64}
    calls: list[tuple[str, ...]] = []

    def runner(command, **_kwargs):
        calls.append(tuple(command))
        payload = [
            {
                "Architecture": "amd64",
                "Config": {
                    "Labels": {
                        "org.opencontainers.image.revision": HEAD,
                        "org.opencontainers.image.bizpulse.image-input-sha256": (
                            "5" * 64
                        ),
                    },
                    "User": "bizpulse",
                },
                "Os": "linux",
            }
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload),
            stderr="",
        )

    assert capture_local_candidate_image(
        repository=repository,
        candidate=candidate,
        runner=runner,
    ) == {"local_image_ready": True}
    assert calls == [("docker", "image", "inspect", f"newcaostone-local:{HEAD[:12]}")]
