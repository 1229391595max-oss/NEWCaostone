"""Exact post-R19 recovery-adoption authority profile."""

from __future__ import annotations

from collections.abc import Mapping


R19_PACKAGE_SHA256 = (
    "9c35ae6a39e6db86b021b9938b966492046f0e745111dab2c1dd8bedbf3ddae9"
)
R19_RECEIPT_SHA256 = (
    "fdec28661cb43268526b3c0aa34944b2a472191dc9a362035acc3c8a446f9cb1"
)
R19_TERMINAL_REVISION = "newcaostone-demo-app--ai-off-9c35ae6a-2bf7086"
R19_IMAGE_DIGEST = (
    "sha256:2bf7086bccec9cdb8fb6a9c2c5383909207b021344d8dfee692437829bd87425"
)
R19_IMAGE = f"sellernorthbpacr.azurecr.io/bizpulse@{R19_IMAGE_DIGEST}"
R19_REGISTRY_TAG = "ai-962a4fa43804-9c35ae6a"
CURRENT_RECOVERY_REVISION = (
    "newcaostone-demo-app--recover-b-9c35ae6a-2bf7086"
)
CURRENT_IDENTITY_STATE = "registry_only"
_HISTORICAL_TARGET = {
    "subscription_id": "fc89e7d3-5428-425e-863f-415859810c2c",
    "tenant_id": "13d04c38-d91c-4f9f-8b65-6af2b515dd63",
    "resource_group": "rg-bizpulse-centralus",
    "location": "centralus",
    "app_name": "newcaostone-demo-app",
    "registry_name": "sellernorthbpacr",
    "log_analytics_workspace_name": "newcaostone-demo-logs",
    "existing_registry_identity_name": "newcaostone-demo-registry",
    "rollback_revision": R19_TERMINAL_REVISION,
    "rollback_image": R19_IMAGE,
    "vault_name": "newcaostone-ai-kv",
    "identity_name": "newcaostone-ai-identity",
}
CURRENT_ADMIN_AI_SUCCESSOR_TARGET = {
    **_HISTORICAL_TARGET,
    "rollback_revision": CURRENT_RECOVERY_REVISION,
}
_R19_COMPLETED_STATES = [
    "readonly_revalidation",
    "publish_candidate_image",
    "activate_ai_disabled_candidate",
    "verify_ai_disabled_candidate",
    "reconcile_ai_vault_identity_role_diagnostics",
]


class CurrentAdminAISuccessorInvalid(ValueError):
    """The post-R19 recovery-adoption contract is not exact."""


def _invalid() -> CurrentAdminAISuccessorInvalid:
    return CurrentAdminAISuccessorInvalid("current_admin_ai_successor_invalid")


def derive_current_admin_ai_successor(
    provenance: Mapping[str, object],
    *,
    receipt_contract: object,
) -> dict[str, str]:
    """Derive the only accepted recovery target from immutable R19 evidence."""

    if not isinstance(receipt_contract, Mapping):
        raise _invalid()
    try:
        reconciliations = receipt_contract["reconciliations"]
        if not isinstance(reconciliations, list) or len(reconciliations) != 1:
            raise TypeError
        terminal = reconciliations[0]
        if not isinstance(terminal, Mapping):
            raise TypeError
        package_sha = provenance["r19_package_sha256"]
        receipt_sha = provenance["r19_receipt_sha256"]
        image_digest = provenance["image_digest"]
        historical_revision = provenance["revision"]
        registry_tag = provenance["registry_tag"]
    except (KeyError, TypeError) as error:
        raise _invalid() from error
    if (
        package_sha != R19_PACKAGE_SHA256
        or receipt_sha != R19_RECEIPT_SHA256
        or image_digest != R19_IMAGE_DIGEST
        or historical_revision != R19_TERMINAL_REVISION
        or registry_tag != R19_REGISTRY_TAG
        or receipt_contract.get("package_sha256") != package_sha
        or receipt_contract.get("state") != "failed"
        or receipt_contract.get("failure_code")
        != "ai_enablement_emergency_disable_failed"
        or receipt_contract.get("completed_states") != _R19_COMPLETED_STATES
        or receipt_contract.get("recovery") is not None
        or terminal.get("acknowledgement") != "accepted"
        or terminal.get("final_state") != "healthy_target"
        or terminal.get("role") != "ai_disabled_candidate"
        or terminal.get("target_revision") != historical_revision
        or terminal.get("target_image_digest") != image_digest
    ):
        raise _invalid()
    application = str(historical_revision).split("--", 1)[0]
    digest_prefix = str(image_digest).removeprefix("sha256:")[:7]
    derived_revision = (
        f"{application}--recover-b-{str(package_sha)[:8]}-{digest_prefix}"
    )
    if derived_revision != CURRENT_RECOVERY_REVISION:
        raise _invalid()
    return {
        "historical_revision": R19_TERMINAL_REVISION,
        "identity_state": CURRENT_IDENTITY_STATE,
        "image": R19_IMAGE,
        "image_digest": R19_IMAGE_DIGEST,
        "registry_tag": R19_REGISTRY_TAG,
        "revision": CURRENT_RECOVERY_REVISION,
    }


def current_admin_ai_successor_target(
    historical_target: object,
) -> dict[str, str]:
    """Return the successor target only from the exact historical target."""

    if historical_target != _HISTORICAL_TARGET:
        raise _invalid()
    return dict(CURRENT_ADMIN_AI_SUCCESSOR_TARGET)
