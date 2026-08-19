from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from scripts.ai_enablement_contract import (
    AIEnablementContractInvalid,
    STATE_ORDER,
    advance_contract,
    build_ai_enablement_contract,
    contract_template,
    initial_progress,
    sanitize_ai_enablement_observation,
    sanitize_failed_receipt,
    sanitize_terminal_receipt,
    validate_reconciliation_evidence,
)


ANCHORS = {
    "package_sha256": "a" * 64,
    "candidate_image_digest": "sha256:" + ("b" * 64),
    "revision": "newcaostone-demo-app--713a6984d4a0",
    "subscription_id": "11111111-1111-4111-8111-111111111111",
    "tenant_id": "22222222-2222-4222-8222-222222222222",
    "resource_group": "rg-bizpulse-centralus",
    "app_name": "newcaostone-demo-app",
    "vault_name": "newcaostone-ai-kv",
    "identity_name": "newcaostone-ai-identity",
    "model": "gpt-5.4-nano-2026-03-17",
    "expires_at": "2026-08-18T12:00:00Z",
}


def _reconciliation(
    role: str = "ai_disabled_candidate",
) -> dict[str, object]:
    return {
        "role": role,
        "acknowledgement": "accepted",
        "predecessor_revision": "newcaostone-demo-app--ai-off-old",
        "target_revision": "newcaostone-demo-app--ai-off-new",
        "target_image_digest": "sha256:" + ("b" * 64),
        "final_state": "healthy_target",
        "application_read_count": 4,
        "revision_read_count": 3,
        "elapsed_milliseconds": 15000,
    }


def _contract() -> dict[str, object]:
    return build_ai_enablement_contract(ANCHORS)


def test_contract_has_exact_order_and_fixed_paid_boundaries() -> None:
    assert STATE_ORDER == (
        "readonly_revalidation",
        "publish_candidate_image",
        "activate_ai_disabled_candidate",
        "verify_ai_disabled_candidate",
        "reconcile_ai_vault_identity_role_diagnostics",
        "budget_failure_rehearsal",
        "provider_failure_placeholder_write",
        "provider_failure_rehearsal",
        "paid_model_qualification",
        "real_secret_write",
        "activate_ai_enabled_revision",
        "verify_ai_enabled_revision",
        "paid_hosted_manual_send_smoke",
        "sanitize_receipt",
    )
    contract = _contract()
    assert contract["state_order"] == list(STATE_ORDER)
    assert contract["paid_calls"] == {
        "model_qualification_cases": 12,
        "hosted_manual_send_smoke": 1,
        "total_maximum": 13,
        "retries_per_call": 0,
    }
    assert contract["runtime_limits"] == {
        "daily_attempt_limit": 120,
        "monthly_token_limit": 150_000,
        "max_concurrent_turns": 15,
        "session_attempt_limit_per_minute": 3,
        "global_attempt_limit_per_minute": 20,
        "chat_output_token_limit": 2_800,
        "planning_token_reservation": 16_000,
        "answering_token_reservation": 80_000,
        "provider_timeout_seconds": 30,
        "provider_retries": 0,
        "provider_tools": 0,
        "reconciliation_timeout_seconds": 120,
        "reconciliation_poll_interval_seconds": 5,
        "reconciliation_application_read_max": 25,
        "reconciliation_revision_read_max": 25,
        "containerapp_patch_retries": 0,
    }
    assert contract["states"]["readonly_revalidation"]["operations"] == {
        "azure.read.sanitized": 12
    }
    assert contract["states"][
        "reconcile_ai_vault_identity_role_diagnostics"
    ] == {
        "operations": {
            "azure.resource.reconcile.identity": 1,
            "azure.resource.reconcile.keyvault": 1,
            "azure.resource.reconcile.role_assignment": 1,
            "azure.resource.reconcile.diagnostic_setting": 1,
        },
        "expected_evidence": {
            "resource_mode": "existing_exact_reconcile",
            "public_network_access": "Enabled",
            "rbac_authorization": True,
            "purge_protection": True,
            "secret_count": 0,
        },
    }


def test_failure_rehearsal_contract_is_ledger_safe_and_placeholder_ordered() -> None:
    states = _contract()["states"]
    assert states["budget_failure_rehearsal"]["expected_evidence"] == {
        "provider_calls": 0,
        "ledger_attempt_delta": 0,
        "ledger_token_delta": 0,
        "failure_code": "ai_budget_unavailable",
        "recovery_revision_ready": True,
    }
    assert states["budget_failure_rehearsal"]["operations"] == {
        "containerapp.patch.nonsecret": 2,
        "browser.manual_send": 1,
        "azure.read.containerapp.max": 50,
        "azure.read.revisions.max": 50,
    }
    assert states["verify_ai_disabled_candidate"]["operations"] == {
        "azure.read.containerapp.max": 25,
        "azure.read.revisions.max": 25,
        "browser.ai_disabled": 1,
    }
    assert states["provider_failure_rehearsal"]["expected_evidence"] == {
        "provider_calls": 1,
        "ledger_attempt_delta": 1,
        "minimum_reserved_tokens": 16_000,
        "provider_error_code": "provider_auth_rejected",
        "key_vault_read_succeeded": True,
        "failure_code": "ai_provider_unavailable",
        "recovery_ai_enabled": False,
        "recovery_revision_ready": True,
        "placeholder_inert": True,
    }
    assert states["provider_failure_rehearsal"]["operations"] == {
        "containerapp.patch.nonsecret": 2,
        "browser.manual_send": 1,
        "azure.read.containerapp.max": 50,
        "azure.read.revisions.max": 50,
    }
    assert states["provider_failure_placeholder_write"]["operations"] == {
        "keyvault.secret.placeholder_write": 1
    }
    assert STATE_ORDER.index("provider_failure_rehearsal") < STATE_ORDER.index(
        "real_secret_write"
    )
    assert states["real_secret_write"]["operations"] == {
        "keyvault.secret.real_write": 1
    }
    assert states["paid_hosted_manual_send_smoke"]["expected_evidence"] == {
        "manual_send_count": 1,
        "provider_calls": 1,
        "preset_auto_submit_count": 0,
        "public_demo_viewer": True,
        "csrf_session_scoped": True,
        "store_workspace_scope_enforced": True,
    }


def test_resume_token_is_bound_to_every_authority_anchor_and_next_state() -> None:
    contract = _contract()
    progress = initial_progress(contract)
    assert progress["next_state"] == STATE_ORDER[0]
    assert len(progress["resume_token"]) == 64

    for key in ANCHORS:
        changed = dict(ANCHORS)
        if key in {"package_sha256", "candidate_image_digest"}:
            changed[key] = changed[key][:-1] + "c"
        elif key == "model":
            changed[key] = "wrong-model"
        elif key == "expires_at":
            changed[key] = "2026-08-18T12:00:01Z"
        elif key in {"subscription_id", "tenant_id"}:
            changed[key] = "33333333-3333-4333-8333-333333333333"
        else:
            changed[key] = f"{changed[key]}-changed"
        if key == "model":
            with pytest.raises(AIEnablementContractInvalid):
                build_ai_enablement_contract(changed)
            continue
        changed_contract = build_ai_enablement_contract(changed)
        assert initial_progress(changed_contract)["resume_token"] != progress[
            "resume_token"
        ]


def test_transition_is_strict_single_step_and_first_mismatch_is_nonmutating() -> None:
    contract = _contract()
    progress = initial_progress(contract)
    before = deepcopy(progress)

    with pytest.raises(
        AIEnablementContractInvalid,
        match="ai_enablement_transition_invalid",
    ):
        advance_contract(
            contract,
            progress,
            state="publish_candidate_image",
            operations={"acr.publish": 1},
            evidence={"image_digest_verified": True},
        )
    assert progress == before

    advanced = advance_contract(
        contract,
        progress,
        state="readonly_revalidation",
        operations={"azure.read.sanitized": 12},
        evidence={"authority_matches": True, "secret_values_read": 0},
    )
    assert advanced["completed_states"] == ["readonly_revalidation"]
    assert advanced["next_state"] == "publish_candidate_image"
    assert advanced["resume_token"] != progress["resume_token"]


@pytest.mark.parametrize(
    ("operations", "evidence"),
    [
        ({"azure.read.sanitized": 11}, {"authority_matches": True, "secret_values_read": 0}),
        ({"azure.read.sanitized": 12}, {"authority_matches": False, "secret_values_read": 0}),
        ({"azure.read.sanitized": 12, "azure.secret.read": 1}, {"authority_matches": True, "secret_values_read": 1}),
        ({"azure.read.sanitized": 12}, {"authority_matches": True, "secret_values_read": 0, "extra": True}),
    ],
)
def test_transition_rejects_operation_or_evidence_drift(
    operations: dict[str, int],
    evidence: dict[str, object],
) -> None:
    contract = _contract()
    with pytest.raises(AIEnablementContractInvalid):
        advance_contract(
            contract,
            initial_progress(contract),
            state="readonly_revalidation",
            operations=operations,
            evidence=evidence,
        )


def test_terminal_receipt_is_allowlisted_and_rejects_key_shaped_content() -> None:
    reconciliations = [
        _reconciliation(role)
        for role in (
            "ai_disabled_candidate",
            "budget_enabled",
            "budget_recovery",
            "provider_enabled",
            "provider_recovery",
            "ai_enabled",
        )
    ]
    safe = sanitize_terminal_receipt(
        {
            "package_sha256": "a" * 64,
            "completed_states": list(STATE_ORDER),
            "candidate_image_digest": "sha256:" + ("b" * 64),
            "final_revision": "newcaostone-demo-app--ai-enabled-bbbbbbb",
            "vault_name": "newcaostone-ai-kv",
            "identity_name": "newcaostone-ai-identity",
            "paid_call_count": 13,
            "result": "completed",
            "reconciliations": reconciliations,
            "observation_sha256": "c" * 64,
        }
    )
    assert set(safe) == {
        "schema_version",
        "package_sha256",
        "completed_states",
        "candidate_image_digest",
        "final_revision",
        "vault_name",
        "identity_name",
        "paid_call_count",
        "result",
        "reconciliations",
        "observation_sha256",
    }
    assert safe["schema_version"] == "newcaostone.ai-enablement-receipt.v2"
    for unsafe in (
        {"api_key": "sentinel"},
        {"result": "sk-proj-abcdefghijklmnop"},
        {"secret_value": "hidden"},
        {"raw_prompt": "private"},
        {"user_data": "private"},
    ):
        payload = dict(safe)
        payload.update(unsafe)
        with pytest.raises(AIEnablementContractInvalid):
            sanitize_terminal_receipt(payload)


def test_reconciliation_contract_is_closed_bounded_and_secret_free() -> None:
    assert contract_template()["runtime_limits"] | {
        "reconciliation_timeout_seconds": 120,
        "reconciliation_poll_interval_seconds": 5,
        "reconciliation_application_read_max": 25,
        "reconciliation_revision_read_max": 25,
        "containerapp_patch_retries": 0,
    } == contract_template()["runtime_limits"]
    assert validate_reconciliation_evidence(_reconciliation()) == _reconciliation()

    mutations = [
        {**_reconciliation(), "role": "unexpected"},
        {**_reconciliation(), "application_read_count": 26},
        {**_reconciliation(), "revision_read_count": 26},
        {**_reconciliation(), "elapsed_milliseconds": 120001},
        {**_reconciliation(), "extra": True},
        {**_reconciliation(), "target_revision": "sk-proj-abcdefghijklmnop"},
        {**_reconciliation(), "raw_stdout": "private"},
        {**_reconciliation(), "exception": "provider exploded"},
        {**_reconciliation(), "prompt": "private prompt"},
        {**_reconciliation(), "user_data": "private user data"},
    ]
    for mutation in mutations:
        with pytest.raises(AIEnablementContractInvalid):
            validate_reconciliation_evidence(mutation)


def test_observation_and_failed_receipt_only_accept_sanitized_evidence() -> None:
    reconciliation = _reconciliation("emergency_disabled")
    observation = sanitize_ai_enablement_observation(
        {
            "package_sha256": "a" * 64,
            "candidate_image_digest": "sha256:" + ("b" * 64),
            "final_revision": "newcaostone-demo-app--ai-enabled-bbbbbbb",
            "ai_enabled": True,
            "paid_call_count": 13,
            "reconciliations": [
                _reconciliation(role)
                for role in (
                    "ai_disabled_candidate",
                    "budget_enabled",
                    "budget_recovery",
                    "provider_enabled",
                    "provider_recovery",
                    "ai_enabled",
                )
            ],
            "acceptance_requires_completed_receipt": True,
        }
    )
    assert observation["schema_version"] == (
        "newcaostone.ai-enablement-observation.v1"
    )

    failed = sanitize_failed_receipt(
        {
            "package_sha256": "a" * 64,
            "state": "failed",
            "failure_code": "ai_enablement_operation_failed",
            "completed_states": list(STATE_ORDER[:10]),
            "reconciliations": [],
            "recovery": {
                "ai_disabled_confirmed": True,
                "placeholder_overwrite_succeeded": True,
                "reconciliation": reconciliation,
            },
        }
    )
    assert failed["schema_version"] == "newcaostone.ai-enablement-attempt.v2"
    assert "provider exploded" not in repr(failed)


def test_runbook_documents_r19_identity_and_async_hosted_boundary() -> None:
    project_root = Path(__file__).resolve().parents[2]
    runbook = (project_root / "docs/runbooks/AI_ENABLEMENT.md").read_text()
    for required in (
        "202 Accepted",
        "exact original",
        "300-second",
        "zero PATCH retries",
        "R19",
        "twelve sanitized Azure reads",
        "registry_plus_ai",
        "JSON `null`",
        "topmost dialog",
        ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R19_2026-08-17.json",
        ".tmp/AI_ENABLEMENT_RECEIPT_R19_2026-08-17.json",
        ".tmp/AI_ENABLEMENT_OBSERVATION_R19_2026-08-17.json",
        "Hosted acceptance remains separate",
    ):
        assert required in runbook
    assert ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R6_2026-08-17.json" not in runbook
