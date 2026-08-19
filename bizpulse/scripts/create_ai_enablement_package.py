#!/usr/bin/env python3
"""Create one owner-only, 24-hour BizPulse AI enablement package."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from typing import Any
from uuid import UUID


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ai_enablement_contract import contract_template  # noqa: E402
from scripts.admin_ai_current_successor import (  # noqa: E402
    CURRENT_ADMIN_AI_SUCCESSOR_TARGET,
    CURRENT_IDENTITY_STATE,
    R19_REGISTRY_TAG,
)
from scripts.create_release_manifest import (  # noqa: E402
    committed_image_input_sha256,
)


PACKAGE_SCHEMA = "newcaostone.ai-enablement-package.v2"
AUTHORIZED_BRANCH = "codex/newcaostone-authoritative-v1"
D3_BRANCH = "codex/deployed-diagnostic-d3"
D3_SELECTED_BASE_SHA = "afd3a2f0a9311aafaca35ad4a412c911aadf1e32"
D3_PACKAGE_SHA256 = "2ca7c7aa0d133b94607569af437dcf0f6a2b7aa44afc475c332dfe16e0ac8687"
ROLLBACK_REVISION = "newcaostone-demo-app--ai-off-9c35ae6a-2bf7086"
ROLLBACK_DIGEST = (
    "2bf7086bccec9cdb8fb6a9c2c5383909207b021344d8dfee692437829bd87425"
)
ROLLBACK_IMAGE = (
    f"sellernorthbpacr.azurecr.io/bizpulse@sha256:{ROLLBACK_DIGEST}"
)
ROLLBACK_REGISTRY_TAG = "ai-962a4fa43804-9c35ae6a"
ARTIFACTS = {
    "package_path": ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R19_2026-08-17.json",
    "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R19_2026-08-17.json",
    "observation_path": ".tmp/AI_ENABLEMENT_OBSERVATION_R19_2026-08-17.json",
}
PRIOR_AI_ATTEMPTS = {
    "r1": {
        "package_path": ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_2026-08-17.json",
        "package_sha256": "77d3d2747df21f79d27f7cd700080fc710653cda425c9c3e48a0c865efdd0180",
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_2026-08-17.json",
        "receipt_sha256": "bd6bc07e071c26f0ce91051cbf2e607ff7fe4d5cb641482ffbedac1b1ed9ae20",
        "receipt_contract": {
            "schema_version": "newcaostone.ai-enablement-attempt.v1",
            "package_sha256": "77d3d2747df21f79d27f7cd700080fc710653cda425c9c3e48a0c865efdd0180",
            "state": "started",
        },
    },
    "r2": {
        "package_path": ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R2_2026-08-17.json",
        "package_sha256": "71ce801f0a007327c1a35424306bbe0d987cb5303e1a2d7e613237c2c419e0a4",
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R2_2026-08-17.json",
        "receipt_sha256": "83ce72f7adf7152b29e2123df84a770e05bd378c0c9b3dbdfe50539678ff3bd2",
        "receipt_contract": {
            "schema_version": "newcaostone.ai-enablement-attempt.v1",
            "package_sha256": "71ce801f0a007327c1a35424306bbe0d987cb5303e1a2d7e613237c2c419e0a4",
            "state": "started",
        },
    },
    "r3": {
        "package_path": ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R3_2026-08-17.json",
        "package_sha256": "ba92c00d154e47944d909ed5ea3204262b335487690252810eda9c669ea599b0",
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R3_2026-08-17.json",
        "receipt_sha256": "260c5d24e960198af4598b441f88ab4444a604718b60197569b0446fc2b5a924",
        "receipt_contract": {
            "schema_version": "newcaostone.ai-enablement-attempt.v1",
            "package_sha256": "ba92c00d154e47944d909ed5ea3204262b335487690252810eda9c669ea599b0",
            "state": "started",
        },
    },
    "r5": {
        "package_path": ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R5_2026-08-17.json",
        "package_sha256": "0cd6205790d80d9d32d50b38c5bc1d5cbc3b5efd563e85fb5c0b653c9767cc46",
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R5_2026-08-17.json",
        "receipt_sha256": "325679c405534a94c1656ff37a8355c32c1eb9ddc2a919b065d16cd2fd4d3906",
        "receipt_contract": {
            "schema_version": "newcaostone.ai-enablement-attempt.v2",
            "package_sha256": "0cd6205790d80d9d32d50b38c5bc1d5cbc3b5efd563e85fb5c0b653c9767cc46",
            "state": "failed",
            "failure_code": "ai_enablement_operation_failed",
            "completed_states": [
                "readonly_revalidation",
                "publish_candidate_image",
                "activate_ai_disabled_candidate",
            ],
            "reconciliations": [],
            "recovery": None,
        },
    },
    "r6": {
        "package_path": ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R6_2026-08-17.json",
        "package_sha256": "ca719f71a58c58d44eef89354fc850a05cfa55f12131707bc86a47c0187e184c",
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R6_2026-08-17.json",
        "receipt_sha256": "777609bdda99e2664518d4e9c0e9e9aa161153a3fdfaff39ed256698445e8f95",
        "receipt_contract": {
            "schema_version": "newcaostone.ai-enablement-attempt.v2",
            "package_sha256": "ca719f71a58c58d44eef89354fc850a05cfa55f12131707bc86a47c0187e184c",
            "state": "failed",
            "failure_code": "ai_enablement_operation_failed",
            "completed_states": [
                "readonly_revalidation",
                "publish_candidate_image",
                "activate_ai_disabled_candidate",
            ],
            "reconciliations": [],
            "recovery": None,
        },
    },
    "r7": {
        "package_path": ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R7_2026-08-17.json",
        "package_sha256": "e95698c5c5fb8c9d88c4a60ee2ea3735662d7782dbf99d96b93fdd9e347ef7bf",
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R7_2026-08-17.json",
        "receipt_sha256": "759e1b8960521e9ad5dc13b894e22446f156052e88d5da2bd57fc40b5e5ebc6e",
        "receipt_contract": {
            "schema_version": "newcaostone.ai-enablement-attempt.v2",
            "package_sha256": "e95698c5c5fb8c9d88c4a60ee2ea3735662d7782dbf99d96b93fdd9e347ef7bf",
            "state": "failed",
            "failure_code": "ai_enablement_revision_unverified",
            "completed_states": [
                "readonly_revalidation",
                "publish_candidate_image",
                "activate_ai_disabled_candidate",
            ],
            "reconciliations": [],
            "recovery": None,
        },
    },
    "r8": {
        "package_path": ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R8_2026-08-17.json",
        "package_sha256": "3ae0101c67d7bfaf6b8fb0c09859306a716b63ed35d61f76f242321e0d59b8e3",
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R8_2026-08-17.json",
        "receipt_sha256": "fa36c58b7d01ae16769049b22bfff751a55d5bbeb6573932e27bbe2a19ae9a9e",
        "receipt_contract": {
            "schema_version": "newcaostone.ai-enablement-attempt.v2",
            "package_sha256": "3ae0101c67d7bfaf6b8fb0c09859306a716b63ed35d61f76f242321e0d59b8e3",
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
    },
    "r11": {
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
    },
    "r12": {
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
    },
    "r13": {
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
    },
    "r14": {
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
    },
    "r15": {
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
    },
    "r16": {
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
    },
    "r17": {
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
    },
    "r18": {
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
    },
    "r19": {
        "package_path": (
            ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R19_2026-08-17.json"
        ),
        "package_sha256": (
            "9c35ae6a39e6db86b021b9938b966492046f0e745111dab2c1dd8bedbf3ddae9"
        ),
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R19_2026-08-17.json",
        "receipt_sha256": (
            "fdec28661cb43268526b3c0aa34944b2a472191dc9a362035acc3c8a446f9cb1"
        ),
        "receipt_contract": {
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
                    "target_image_digest": (
                        "sha256:"
                        "2bf7086bccec9cdb8fb6a9c2c5383909207b021344d8dfee692437829bd87425"
                    ),
                    "target_revision": (
                        "newcaostone-demo-app--ai-off-9c35ae6a-2bf7086"
                    ),
                }
            ],
            "recovery": None,
        },
    },
}
AZURE_TARGET = {
    "subscription_id": "fc89e7d3-5428-425e-863f-415859810c2c",
    "tenant_id": "13d04c38-d91c-4f9f-8b65-6af2b515dd63",
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
}
CONTROL_PATHS = (
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
)
_PACKAGE_KEYS = frozenset(
    {
        "approval",
        "artifacts",
        "azure_target",
        "candidate",
        "control_sha256",
        "cost_cap",
        "d3",
        "execution_contract",
        "expected_safe_observations",
        "expires_at",
        "issued_at",
        "provider_pricing",
        "prepackage_gate",
        "prior_attempts",
        "repository",
        "resource_allowlist",
        "schema_version",
        "stop_conditions",
    }
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
_NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]{1,62}[a-z0-9]")
_VAULT_NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]{1,22}[a-z0-9]")
_REGISTRY_PATTERN = re.compile(r"[a-z0-9]{5,50}")
_IMAGE_PATTERN = re.compile(
    r"[a-z0-9]{5,50}\.azurecr\.io/"
    r"[a-z0-9][a-z0-9._/-]{1,127}@sha256:[0-9a-f]{64}"
)
_REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9._/-]{1,255}")
_REVISION_PATTERN = re.compile(r"[a-z][a-z0-9-]{2,126}")
_KEY_PATTERN = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b")


class AIEnablementPackageInvalid(ValueError):
    """The package is stale, unsafe, incomplete, or not package-bound."""


def _invalid(code: str = "ai_enablement_package_invalid") -> AIEnablementPackageInvalid:
    return AIEnablementPackageInvalid(code)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise _invalid()
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise _invalid()
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise _invalid() from error
    if _utc_text(parsed) != value:
        raise _invalid()
    return parsed


def _canonical_uuid4(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
    except ValueError:
        return False
    return str(parsed) == value and parsed.version == 4


def _exact_mapping(value: object, keys: set[str] | frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _invalid()
    return value


def _validate_repository(value: object) -> dict[str, object]:
    raw = _exact_mapping(value, {"branch", "head_sha", "tree_sha", "clean"})
    if (
        raw["branch"] != AUTHORIZED_BRANCH
        or not isinstance(raw["head_sha"], str)
        or _GIT_SHA_PATTERN.fullmatch(raw["head_sha"]) is None
        or not isinstance(raw["tree_sha"], str)
        or _GIT_SHA_PATTERN.fullmatch(raw["tree_sha"]) is None
        or raw["clean"] is not True
    ):
        raise _invalid()
    return dict(raw)


def _validate_azure_target(value: object) -> dict[str, str]:
    keys = {
        "subscription_id",
        "tenant_id",
        "resource_group",
        "location",
        "app_name",
        "registry_name",
        "log_analytics_workspace_name",
        "existing_registry_identity_name",
        "rollback_revision",
        "rollback_image",
        "vault_name",
        "identity_name",
    }
    raw = _exact_mapping(value, keys)
    if (
        not _canonical_uuid4(raw["subscription_id"])
        or not _canonical_uuid4(raw["tenant_id"])
        or any(
            not isinstance(raw[name], str)
            or _NAME_PATTERN.fullmatch(raw[name]) is None
            for name in (
                "resource_group",
                "app_name",
                "log_analytics_workspace_name",
                "existing_registry_identity_name",
                "identity_name",
            )
        )
        or not isinstance(raw["registry_name"], str)
        or _REGISTRY_PATTERN.fullmatch(raw["registry_name"]) is None
        or not isinstance(raw["location"], str)
        or re.fullmatch(r"[a-z0-9]{3,32}", raw["location"]) is None
        or not isinstance(raw["rollback_revision"], str)
        or _REVISION_PATTERN.fullmatch(raw["rollback_revision"]) is None
        or not isinstance(raw["rollback_image"], str)
        or _IMAGE_PATTERN.fullmatch(raw["rollback_image"]) is None
        or not isinstance(raw["vault_name"], str)
        or _VAULT_NAME_PATTERN.fullmatch(raw["vault_name"]) is None
        or raw["vault_name"] == "sellernorthbp-kv"
    ):
        raise _invalid()
    return {key: str(raw[key]) for key in sorted(keys)}


def _validate_candidate(value: object, *, tree_sha: str) -> dict[str, object]:
    keys = {
        "image_repository",
        "source_tree_sha",
        "dockerfile_sha256",
        "runtime_lock_sha256",
        "image_input_sha256",
        "candidate_image_digest",
    }
    raw = _exact_mapping(value, keys)
    if (
        not isinstance(raw["image_repository"], str)
        or re.fullmatch(r"[a-z0-9][a-z0-9._/-]{1,127}", raw["image_repository"])
        is None
        or raw["source_tree_sha"] != tree_sha
        or any(
            not isinstance(raw[name], str)
            or _SHA256_PATTERN.fullmatch(raw[name]) is None
            for name in (
                "dockerfile_sha256",
                "runtime_lock_sha256",
                "image_input_sha256",
            )
        )
        or raw["candidate_image_digest"] is not None
    ):
        raise _invalid()
    return dict(raw)


def _validate_controls(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise _invalid()
    result: dict[str, str] = {}
    for raw_path, digest in value.items():
        if (
            not isinstance(raw_path, str)
            or _REFERENCE_PATTERN.fullmatch(raw_path) is None
            or not isinstance(digest, str)
            or _SHA256_PATTERN.fullmatch(digest) is None
        ):
            raise _invalid()
        logical = PurePosixPath(raw_path)
        if logical.is_absolute() or "." in logical.parts or ".." in logical.parts:
            raise _invalid()
        result[raw_path] = digest
    required = {
        "infra/ai_enablement.bicep",
        "infra/ai_secret_write.bicep",
        "scripts/ai_enablement_contract.py",
        "scripts/azure_ai_enablement_actions.py",
        "scripts/azure_ai_reconciliation.py",
        "scripts/azure_ai_revision.py",
        "scripts/run_ai_enablement.py",
    }
    if not required.issubset(result):
        raise _invalid()
    return dict(sorted(result.items()))


def _validate_d3(value: object) -> dict[str, object]:
    keys = {
        "branch",
        "selected_base_sha",
        "package_sha256",
        "package_mode",
        "receipt_present",
        "observation_present",
    }
    raw = _exact_mapping(value, keys)
    if raw != {
        "branch": D3_BRANCH,
        "selected_base_sha": D3_SELECTED_BASE_SHA,
        "package_sha256": D3_PACKAGE_SHA256,
        "package_mode": "0600",
        "receipt_present": False,
        "observation_present": False,
    }:
        raise _invalid()
    return dict(raw)


def _validate_artifacts(value: object) -> dict[str, str]:
    if value == ARTIFACTS:
        return dict(ARTIFACTS)
    raw = _exact_mapping(
        value,
        {"package_path", "receipt_path", "observation_path"},
    )
    prefixes = {
        "package_path": ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_TASK12_",
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_TASK12_",
        "observation_path": ".tmp/AI_ENABLEMENT_OBSERVATION_TASK12_",
    }
    attempt_ids: set[str] = set()
    for key, prefix in prefixes.items():
        path = raw[key]
        if (
            not isinstance(path, str)
            or not path.startswith(prefix)
            or not path.endswith(".json")
        ):
            raise _invalid()
        attempt_ids.add(path.removeprefix(prefix).removesuffix(".json"))
    if len(attempt_ids) != 1 or not _canonical_uuid4(next(iter(attempt_ids))):
        raise _invalid()
    return {key: str(raw[key]) for key in sorted(raw)}


def _authority_profile(
    artifacts: Mapping[str, object],
) -> tuple[Mapping[str, object], str, str]:
    if artifacts == ARTIFACTS:
        return AZURE_TARGET, ROLLBACK_REGISTRY_TAG, "registry_plus_ai"
    return (
        CURRENT_ADMIN_AI_SUCCESSOR_TARGET,
        R19_REGISTRY_TAG,
        CURRENT_IDENTITY_STATE,
    )


def _validate_prior_attempts(value: object) -> dict[str, object]:
    if value != PRIOR_AI_ATTEMPTS:
        raise _invalid()
    return json.loads(json.dumps(PRIOR_AI_ATTEMPTS))


def _prepackage_gate(
    azure_target: Mapping[str, object],
    *,
    rollback_registry_tag: str,
    role_assignment_state: str,
    rollback_identity_state: str = "registry_plus_ai",
) -> dict[str, object]:
    if (
        role_assignment_state not in {"legacy_only", "officer_only"}
        or rollback_identity_state
        not in {"registry_only", "registry_plus_ai"}
    ):
        raise _invalid()
    return {
        "required_azure_reads": 12,
        "rollback_revision": azure_target["rollback_revision"],
        "rollback_image": azure_target["rollback_image"],
        "rollback_registry_tag": rollback_registry_tag,
        "rollback_identity_state": rollback_identity_state,
        "replica_count": 1,
        "ai_enabled": False,
        "vault_state": "existing_exact",
        "identity_state": "existing_exact",
        "role_assignment_state": role_assignment_state,
        "diagnostic_setting_state": "existing_exact",
        "secret_values_read": 0,
    }


def _validate_prepackage_gate(
    value: object,
    *,
    azure_target: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise _invalid()
    role_assignment_state = value.get("role_assignment_state")
    if not isinstance(role_assignment_state, str):
        raise _invalid()
    if azure_target == AZURE_TARGET:
        registry_tag = ROLLBACK_REGISTRY_TAG
        identity_state = "registry_plus_ai"
    elif azure_target == CURRENT_ADMIN_AI_SUCCESSOR_TARGET:
        registry_tag = R19_REGISTRY_TAG
        identity_state = CURRENT_IDENTITY_STATE
    else:
        raise _invalid()
    expected = _prepackage_gate(
        azure_target,
        rollback_registry_tag=registry_tag,
        role_assignment_state=role_assignment_state,
        rollback_identity_state=identity_state,
    )
    if value != expected:
        raise _invalid()
    return dict(expected)


def _resource_allowlist() -> dict[str, object]:
    return {
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


def _package_body(
    *,
    issued_at: str,
    expires_at: str,
    repository: dict[str, object],
    azure_target: dict[str, str],
    candidate: dict[str, object],
    control_sha256: dict[str, str],
    d3: dict[str, object],
    artifacts: dict[str, str],
    prior_attempts: dict[str, object],
    prepackage_gate: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": PACKAGE_SCHEMA,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "approval": {"approved_sha256": None, "approved_at": None},
        "artifacts": artifacts,
        "repository": repository,
        "azure_target": azure_target,
        "candidate": candidate,
        "control_sha256": control_sha256,
        "d3": d3,
        "prior_attempts": prior_attempts,
        "prepackage_gate": prepackage_gate,
        "resource_allowlist": _resource_allowlist(),
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
            "checked_at": issued_at,
            "input_usd_per_million_tokens": "0.20",
            "output_usd_per_million_tokens": "1.25",
            "regional_processing_uplift_percent": "10",
            "execution_uses_regional_processing": False,
        },
        "expected_safe_observations": {
            "azure_authority_matches": True,
            "d3_unchanged": True,
            "existing_secret_values_read": 0,
            "application_configuration_secret_changes": 0,
            "preset_auto_submit_count": 0,
            "terminal_prohibited_content_matches": 0,
        },
        "stop_conditions": [
            "approval_hash_or_expiry_mismatch",
            "repository_or_control_drift",
            "azure_authority_or_ai_state_drift",
            "d3_invariant_drift",
            "image_digest_or_revision_drift",
            "resource_or_operation_count_drift",
            "secret_boundary_or_output_leak",
            "price_or_paid_cap_ambiguous",
            "provider_outcome_unknown",
            "rollback_readiness_missing",
        ],
    }


def build_ai_enablement_package(
    *,
    generated_at: datetime,
    role_assignment_state: str,
    repository: Mapping[str, object],
    azure_target: Mapping[str, object],
    candidate: Mapping[str, object],
    control_sha256: Mapping[str, object],
    d3: Mapping[str, object],
    artifacts: Mapping[str, object] = ARTIFACTS,
    prior_attempts: Mapping[str, object] = PRIOR_AI_ATTEMPTS,
    rollback_registry_tag: str = ROLLBACK_REGISTRY_TAG,
) -> dict[str, object]:
    """Build a deterministic package containing no credentials or public URL."""

    issued_at = _utc_text(generated_at)
    expires_at = _utc_text(generated_at.astimezone(UTC) + timedelta(hours=24))
    validated_repository = _validate_repository(repository)
    validated_target = _validate_azure_target(azure_target)
    validated_artifacts = _validate_artifacts(artifacts)
    expected_target, expected_tag, expected_identity = _authority_profile(
        validated_artifacts
    )
    if (
        validated_target != expected_target
        or rollback_registry_tag != expected_tag
    ):
        raise _invalid("ai_enablement_generation_authority_drift")
    package = _package_body(
        issued_at=issued_at,
        expires_at=expires_at,
        repository=validated_repository,
        azure_target=validated_target,
        candidate=_validate_candidate(
            candidate,
            tree_sha=str(validated_repository["tree_sha"]),
        ),
        control_sha256=_validate_controls(control_sha256),
        d3=_validate_d3(d3),
        artifacts=validated_artifacts,
        prior_attempts=_validate_prior_attempts(prior_attempts),
        prepackage_gate=_prepackage_gate(
            validated_target,
            rollback_registry_tag=rollback_registry_tag,
            role_assignment_state=role_assignment_state,
            rollback_identity_state=expected_identity,
        ),
    )
    _validate_package(package, now=generated_at.astimezone(UTC))
    return package


def _validate_package(package: object, *, now: datetime) -> dict[str, object]:
    raw = _exact_mapping(package, _PACKAGE_KEYS)
    issued = _parse_utc(raw["issued_at"])
    expires = _parse_utc(raw["expires_at"])
    if (
        raw["schema_version"] != PACKAGE_SCHEMA
        or expires - issued != timedelta(hours=24)
        or now.tzinfo is None
        or now.astimezone(UTC) < issued
        or now.astimezone(UTC) >= expires
        or raw["approval"]
        != {"approved_sha256": None, "approved_at": None}
    ):
        raise _invalid()
    repository = _validate_repository(raw["repository"])
    azure_target = _validate_azure_target(raw["azure_target"])
    artifacts = _validate_artifacts(raw["artifacts"])
    expected_target, _expected_tag, _expected_identity = _authority_profile(
        artifacts
    )
    if azure_target != expected_target:
        raise _invalid()
    _validate_candidate(raw["candidate"], tree_sha=str(repository["tree_sha"]))
    _validate_controls(raw["control_sha256"])
    _validate_d3(raw["d3"])
    _validate_prior_attempts(raw["prior_attempts"])
    _validate_prepackage_gate(raw["prepackage_gate"], azure_target=azure_target)
    if (
        raw["resource_allowlist"] != _resource_allowlist()
        or raw["execution_contract"] != contract_template()
        or raw["cost_cap"]
        != {
            "currency": "USD",
            "maximum_paid_execution": "1.00",
            "maximum_paid_calls": 13,
            "stop_if_price_evidence_missing": True,
        }
        or raw["provider_pricing"]
        != {
            "model": "gpt-5.4-nano-2026-03-17",
            "official_source": (
                "https://developers.openai.com/api/docs/models/gpt-5.4-nano"
            ),
            "checked_at": raw["issued_at"],
            "input_usd_per_million_tokens": "0.20",
            "output_usd_per_million_tokens": "1.25",
            "regional_processing_uplift_percent": "10",
            "execution_uses_regional_processing": False,
        }
        or raw["expected_safe_observations"]
        != {
            "azure_authority_matches": True,
            "d3_unchanged": True,
            "existing_secret_values_read": 0,
            "application_configuration_secret_changes": 0,
            "preset_auto_submit_count": 0,
            "terminal_prohibited_content_matches": 0,
        }
        or raw["stop_conditions"]
        != [
            "approval_hash_or_expiry_mismatch",
            "repository_or_control_drift",
            "azure_authority_or_ai_state_drift",
            "d3_invariant_drift",
            "image_digest_or_revision_drift",
            "resource_or_operation_count_drift",
            "secret_boundary_or_output_leak",
            "price_or_paid_cap_ambiguous",
            "provider_outcome_unknown",
            "rollback_readiness_missing",
        ]
    ):
        raise _invalid()
    serialized = json.dumps(raw, sort_keys=True, ensure_ascii=False)
    if _KEY_PATTERN.search(serialized) or any(
        prohibited in serialized
        for prohibited in (
            "Bearer ",
            "OPENAI_API_KEY",
            "BIZPULSE_DEPLOY_OPENAI_API_KEY",
            "postgresql://",
            "AccountKey=",
            "sellernorthbp-kv",
        )
    ):
        raise _invalid()
    return dict(raw)


def validate_ai_enablement_package(
    package: object,
    *,
    now: datetime,
) -> dict[str, object]:
    """Validate an in-memory Task 10 request against its complete exact contract."""

    return _validate_package(package, now=now)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _invalid()
        result[key] = value
    return result


def load_ai_enablement_package(
    path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Load one regular 0600 package with duplicate-key and expiry checks."""

    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or not 0 < metadata.st_size <= 2_000_000
        ):
            raise _invalid()
        package = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _invalid() from error
    observed_at = datetime.now(UTC) if now is None else now
    return _validate_package(package, now=observed_at)


def write_ai_enablement_package(path: Path, package: Mapping[str, object]) -> None:
    """Create an owner-only package without replacing any existing path."""

    issued = _parse_utc(package.get("issued_at"))
    _validate_package(package, now=issued)
    encoded = (
        json.dumps(package, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode()
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        raise _invalid("ai_enablement_package_write_failed") from error


def capture_repository_state(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    """Capture exact clean branch, HEAD and tree without network access."""

    def git(*arguments: str) -> str:
        try:
            completed = runner(
                ["git", *arguments],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise _invalid("ai_enablement_repository_drift") from error
        if completed.returncode != 0 or not isinstance(completed.stdout, str):
            raise _invalid("ai_enablement_repository_drift")
        return completed.stdout.strip()

    repository = {
        "branch": git("branch", "--show-current"),
        "head_sha": git("rev-parse", "HEAD"),
        "tree_sha": git("rev-parse", "HEAD^{tree}"),
        "clean": not bool(
            git("status", "--porcelain=v1", "--untracked-files=normal")
        ),
    }
    try:
        return _validate_repository(repository)
    except AIEnablementPackageInvalid as error:
        raise _invalid("ai_enablement_repository_drift") from error


def collect_control_sha256(
    *,
    project_root: Path = PROJECT_ROOT,
    paths: tuple[str, ...] = CONTROL_PATHS,
) -> dict[str, str]:
    """Hash regular package-control files without following symlinks."""

    result: dict[str, str] = {}
    root = project_root.resolve(strict=True)
    for relative in paths:
        try:
            path = (root / relative).resolve(strict=True)
            metadata = path.lstat()
            if (
                not path.is_relative_to(root)
                or not stat.S_ISREG(metadata.st_mode)
                or path.is_symlink()
            ):
                raise _invalid("ai_enablement_control_drift")
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise _invalid("ai_enablement_control_drift") from error
    return _validate_controls(result)


def capture_prior_ai_attempts(
    project_root: Path = PROJECT_ROOT,
) -> dict[str, object]:
    """Verify every consumed AI package and its replay-fence receipt."""

    try:
        root = project_root.resolve(strict=True)
        for attempt in PRIOR_AI_ATTEMPTS.values():
            raw_package_path = root / str(attempt["package_path"])
            artifact_checks: list[tuple[Path, object]] = [
                (raw_package_path, attempt["package_sha256"]),
            ]
            if attempt.get("receipt_present") is False:
                terminal_boundary = attempt.get("terminal_boundary")
                if (
                    attempt.get("observation_present") is not False
                    or terminal_boundary
                    not in {
                        "pre_receipt_no_azure_write",
                        "never_submitted_superseded_before_execution",
                    }
                    or (
                        terminal_boundary
                        == "never_submitted_superseded_before_execution"
                        and attempt.get("superseded_reason")
                        != "hidden_tty_not_user_accessible"
                    )
                ):
                    raise _invalid("ai_enablement_prior_attempt_drift")
                for key in ("receipt_path", "observation_path"):
                    if os.path.lexists(root / str(attempt[key])):
                        raise _invalid("ai_enablement_prior_attempt_drift")
            else:
                raw_receipt_path = root / str(attempt["receipt_path"])
                artifact_checks.append(
                    (raw_receipt_path, attempt["receipt_sha256"])
                )

            for raw_path, expected_sha in artifact_checks:
                metadata = raw_path.lstat()
                path = raw_path.resolve(strict=True)
                if (
                    not path.is_relative_to(root)
                    or not stat.S_ISREG(metadata.st_mode)
                    or stat.S_ISLNK(metadata.st_mode)
                    or stat.S_IMODE(metadata.st_mode) != 0o600
                    or not 0 < metadata.st_size <= 2_000_000
                    or hashlib.sha256(path.read_bytes()).hexdigest()
                    != expected_sha
                ):
                    raise _invalid("ai_enablement_prior_attempt_drift")
            if attempt.get("receipt_present") is False:
                continue
            receipt = json.loads(
                raw_receipt_path.read_text(encoding="utf-8"),
                object_pairs_hook=_unique_object,
            )
            if receipt != attempt["receipt_contract"]:
                raise _invalid("ai_enablement_prior_attempt_drift")
    except (
        AIEnablementPackageInvalid,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ) as error:
        if isinstance(error, AIEnablementPackageInvalid):
            raise
        raise _invalid("ai_enablement_prior_attempt_drift") from error
    return json.loads(json.dumps(PRIOR_AI_ATTEMPTS))


def _candidate_from_repository(
    repository: Mapping[str, object],
) -> dict[str, object]:
    try:
        dockerfile_sha = hashlib.sha256(
            (PROJECT_ROOT / "Dockerfile").read_bytes()
        ).hexdigest()
        runtime_lock_sha = hashlib.sha256(
            (PROJECT_ROOT / "requirements.txt").read_bytes()
        ).hexdigest()
        image_input_sha = committed_image_input_sha256(
            str(repository["head_sha"])
        )
    except (KeyError, OSError, subprocess.SubprocessError) as error:
        raise _invalid("ai_enablement_control_drift") from error
    return {
        "image_repository": "bizpulse",
        "source_tree_sha": repository["tree_sha"],
        "dockerfile_sha256": dockerfile_sha,
        "runtime_lock_sha256": runtime_lock_sha,
        "image_input_sha256": image_input_sha,
        "candidate_image_digest": None,
    }


def capture_local_candidate_image(
    repository: Mapping[str, object],
    candidate: Mapping[str, object],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    """Require the exact package-bound linux/amd64 image before package write."""

    head_sha = repository.get("head_sha")
    image_input_sha256 = candidate.get("image_input_sha256")
    if (
        not isinstance(head_sha, str)
        or re.fullmatch(r"[0-9a-f]{40}", head_sha) is None
        or not isinstance(image_input_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", image_input_sha256) is None
    ):
        raise _invalid("ai_enablement_local_image_invalid")
    tag = f"newcaostone-local:{head_sha[:12]}"
    try:
        completed = runner(
            ("docker", "image", "inspect", tag),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env={
                name: value
                for name in (
                    "HOME",
                    "LANG",
                    "LC_ALL",
                    "PATH",
                    "TMPDIR",
                )
                if isinstance((value := os.environ.get(name)), str)
            },
        )
        if completed.returncode != 0 or len(completed.stdout) > 1_000_000:
            raise _invalid("ai_enablement_local_image_unavailable")
        payload = json.loads(completed.stdout)
        image = payload[0]
        configuration = image["Config"]
        labels = configuration["Labels"]
    except AIEnablementPackageInvalid:
        raise
    except (OSError, subprocess.SubprocessError) as error:
        raise _invalid("ai_enablement_local_image_unavailable") from error
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise _invalid("ai_enablement_local_image_invalid") from error
    if (
        not isinstance(payload, list)
        or len(payload) != 1
        or not isinstance(image, Mapping)
        or image.get("Os") != "linux"
        or image.get("Architecture") != "amd64"
        or configuration.get("User") != "bizpulse"
        or labels.get("org.opencontainers.image.revision") != head_sha
        or labels.get("org.opencontainers.image.bizpulse.image-input-sha256")
        != image_input_sha256
    ):
        raise _invalid("ai_enablement_local_image_invalid")
    return {"local_image_ready": True}


def generate_ai_enablement_package(
    *,
    output_path: Path,
    receipt_path: Path,
    observation_path: Path,
    generated_at: Callable[[], datetime],
    repository_reader: Callable[[], object],
    control_reader: Callable[[], object],
    prior_attempts_reader: Callable[[], object],
    azure_reader: Callable[[Mapping[str, object]], object],
    local_image_reader: Callable[
        [Mapping[str, object], Mapping[str, object]], object
    ],
    role_assignment_state: str,
) -> dict[str, object]:
    """Gate one exclusive package write on stable local and live authority."""

    artifact_root = output_path.parent.parent
    expected_paths = {
        key: (artifact_root / relative).resolve()
        for key, relative in ARTIFACTS.items()
    }
    if (
        output_path.resolve() != expected_paths["package_path"]
        or receipt_path.resolve() != expected_paths["receipt_path"]
        or observation_path.resolve() != expected_paths["observation_path"]
    ):
        raise _invalid("ai_enablement_artifact_path_drift")
    if output_path.exists() or receipt_path.exists() or observation_path.exists():
        raise _invalid("ai_enablement_artifact_exists")
    repository_before = _validate_repository(repository_reader())
    controls_before = _validate_controls(control_reader())
    prior_before = _validate_prior_attempts(prior_attempts_reader())
    provisional = {
        "azure_target": dict(AZURE_TARGET),
        "candidate": {"image_repository": "bizpulse"},
        "execution_contract": contract_template(),
        "provider_pricing": {"model": "gpt-5.4-nano-2026-03-17"},
        "prepackage_gate": _prepackage_gate(
            AZURE_TARGET,
            rollback_registry_tag=ROLLBACK_REGISTRY_TAG,
            role_assignment_state=role_assignment_state,
        ),
    }
    if azure_reader(provisional) != {
        "prepackage_gate_matches": True,
        "required_azure_reads": 12,
    }:
        raise _invalid("ai_enablement_azure_authority_drift")
    repository_after = _validate_repository(repository_reader())
    controls_after = _validate_controls(control_reader())
    prior_after = _validate_prior_attempts(prior_attempts_reader())
    if (
        repository_after != repository_before
        or controls_after != controls_before
        or prior_after != prior_before
        or output_path.exists()
        or receipt_path.exists()
        or observation_path.exists()
    ):
        raise _invalid("ai_enablement_prepackage_drift")
    candidate = _candidate_from_repository(repository_after)
    if local_image_reader(repository_after, candidate) != {
        "local_image_ready": True
    }:
        raise _invalid("ai_enablement_local_image_invalid")
    issued_at = generated_at()
    package = build_ai_enablement_package(
        generated_at=issued_at,
        role_assignment_state=role_assignment_state,
        repository=repository_after,
        azure_target=AZURE_TARGET,
        candidate=candidate,
        control_sha256=controls_after,
        d3={
            "branch": D3_BRANCH,
            "selected_base_sha": D3_SELECTED_BASE_SHA,
            "package_sha256": D3_PACKAGE_SHA256,
            "package_mode": "0600",
            "receipt_present": False,
            "observation_present": False,
        },
        artifacts=ARTIFACTS,
        prior_attempts=prior_after,
        rollback_registry_tag=ROLLBACK_REGISTRY_TAG,
    )
    write_ai_enablement_package(output_path, package)
    return package


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--log-workspace", required=True)
    parser.add_argument("--registry-identity", required=True)
    parser.add_argument("--rollback-revision", required=True)
    parser.add_argument("--rollback-image", required=True)
    parser.add_argument("--rollback-registry-tag", required=True)
    parser.add_argument("--vault", required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument(
        "--role-assignment-state",
        choices=("legacy_only", "officer_only"),
        required=True,
    )
    options = parser.parse_args(arguments)
    try:
        cli_target = {
                "subscription_id": options.subscription,
                "tenant_id": options.tenant,
                "resource_group": options.resource_group,
                "location": options.location,
                "app_name": options.app,
                "registry_name": options.registry,
                "log_analytics_workspace_name": options.log_workspace,
                "existing_registry_identity_name": options.registry_identity,
                "rollback_revision": options.rollback_revision,
                "rollback_image": options.rollback_image,
                "vault_name": options.vault,
                "identity_name": options.identity,
        }
        expected_paths = {
            "package_path": (PROJECT_ROOT / ARTIFACTS["package_path"]).resolve(),
            "receipt_path": (PROJECT_ROOT / ARTIFACTS["receipt_path"]).resolve(),
            "observation_path": (
                PROJECT_ROOT / ARTIFACTS["observation_path"]
            ).resolve(),
        }
        if (
            cli_target != AZURE_TARGET
            or options.rollback_registry_tag != ROLLBACK_REGISTRY_TAG
            or options.output.resolve() != expected_paths["package_path"]
            or options.receipt.resolve() != expected_paths["receipt_path"]
            or options.observation.resolve() != expected_paths["observation_path"]
        ):
            raise _invalid("ai_enablement_generation_authority_drift")

        from scripts.azure_ai_enablement_actions import (  # noqa: PLC0415
            read_sanitized_azure_authority,
        )

        def azure_reader(provisional: Mapping[str, object]) -> object:
            result, _projection = read_sanitized_azure_authority(provisional)
            if result.get("operations") != {"azure.read.sanitized": 12}:
                raise _invalid("ai_enablement_azure_authority_drift")
            return {
                "prepackage_gate_matches": True,
                "required_azure_reads": 12,
            }

        package = generate_ai_enablement_package(
            output_path=options.output,
            receipt_path=options.receipt,
            observation_path=options.observation,
            generated_at=lambda: datetime.now(UTC),
            repository_reader=capture_repository_state,
            control_reader=collect_control_sha256,
            prior_attempts_reader=capture_prior_ai_attempts,
            azure_reader=azure_reader,
            local_image_reader=capture_local_candidate_image,
            role_assignment_state=options.role_assignment_state,
        )
    except (AIEnablementPackageInvalid, OSError):
        print("ai_enablement_package=failed")
        return 1
    digest = hashlib.sha256(options.output.read_bytes()).hexdigest()
    print("ai_enablement_package=created")
    print(f"package_sha256={digest}")
    print(f"expires_at={package['expires_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
