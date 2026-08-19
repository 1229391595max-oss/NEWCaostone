"""Build bounded AI failure-rehearsal revisions for an approved package runner."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from pathlib import Path
import re
import sys
from typing import Any
from uuid import UUID

_SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_SCRIPT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_PROJECT_ROOT))

from scripts.azure_ai_revision import (  # noqa: E402
    AzureAIRevisionInvalid,
    build_ai_revision_patch,
)


_IMAGE_PATTERN = re.compile(
    r"[a-z0-9][a-z0-9-]{2,49}\.azurecr\.io/"
    r"[a-z0-9][a-z0-9._/-]{1,127}@sha256:[0-9a-f]{64}"
)
_NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]{1,62}[a-z0-9]")


class HostedFailureCheckInvalid(RuntimeError):
    """The bounded rehearsal could not prove its expected safe state."""


def _canonical_uuid4(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
    except ValueError:
        return False
    return str(parsed) == value and parsed.version == 4


def _current_image(projection: object) -> str | None:
    try:
        image = projection["properties"]["template"]["containers"][0]["image"]
    except (KeyError, IndexError, TypeError):
        return None
    return image if isinstance(image, str) else None


def _identity_scope_matches(
    projection: object,
    *,
    subscription_id: str,
    resource_group: str,
) -> bool:
    try:
        assigned = projection["identity"]["userAssignedIdentities"]
    except (KeyError, TypeError):
        return False
    if not isinstance(assigned, Mapping) or not assigned:
        return False
    prefix = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/"
    ).lower()
    return all(isinstance(resource_id, str) and resource_id.lower().startswith(prefix) for resource_id in assigned)


def run_failure_check(
    *,
    current_projection: object,
    subscription_id: str,
    resource_group: str,
    app_name: str,
    image: str,
    authorization_id: str,
    scenario: str,
    ai_identity_resource_id: str,
    vault_url: str,
    secret_name: str,
    managed_identity_client_id: str,
    patch_applier: Callable[[dict[str, Any]], None],
    browser_checker: Callable[..., None],
) -> dict[str, object]:
    """Apply one rehearsal patch and one recovery patch through injected actions."""

    if (
        not _canonical_uuid4(subscription_id)
        or not _canonical_uuid4(authorization_id)
        or _NAME_PATTERN.fullmatch(resource_group) is None
        or _NAME_PATTERN.fullmatch(app_name) is None
        or _IMAGE_PATTERN.fullmatch(image) is None
        or scenario not in {"budget", "provider-unavailable"}
        or _current_image(current_projection) != image
        or not _identity_scope_matches(
            current_projection,
            subscription_id=subscription_id,
            resource_group=resource_group,
        )
        or not ai_identity_resource_id.lower().startswith(
            (
                f"/subscriptions/{subscription_id}/resourceGroups/"
                f"{resource_group}/"
            ).lower()
        )
    ):
        raise HostedFailureCheckInvalid("hosted_failure_authority_invalid")

    authority_prefix = authorization_id.replace("-", "")[:8]
    digest_prefix = image.rsplit("@sha256:", 1)[1][:7]
    rehearsal_label = scenario.replace("provider-unavailable", "provider")
    rehearsal_suffix = f"{rehearsal_label}-{authority_prefix}-{digest_prefix}"
    recovery_suffix = f"recover-{scenario[0]}-{authority_prefix}-{digest_prefix}"
    try:
        rehearsal_patch = build_ai_revision_patch(
            current_projection,
            enabled=True,
            candidate_image=image,
            revision_suffix=rehearsal_suffix,
            ai_identity_resource_id=ai_identity_resource_id,
            vault_url=vault_url,
            secret_name=secret_name,
            managed_identity_client_id=managed_identity_client_id,
            budget_failure_rehearsal=scenario == "budget",
        )
    except AzureAIRevisionInvalid as error:
        raise HostedFailureCheckInvalid(
            "hosted_failure_authority_invalid"
        ) from error

    try:
        patch_applier(rehearsal_patch)
    except Exception as error:
        raise HostedFailureCheckInvalid("hosted_failure_patch_unconfirmed") from error

    rehearsal_error: Exception | None = None
    try:
        browser_checker(
            scenario=scenario,
            expected_revision_suffix=rehearsal_suffix,
        )
    except Exception as error:
        rehearsal_error = error

    try:
        recovery_patch = build_ai_revision_patch(
            rehearsal_patch,
            enabled=False,
            candidate_image=image,
            revision_suffix=recovery_suffix,
            ai_identity_resource_id=ai_identity_resource_id,
        )
        patch_applier(recovery_patch)
    except Exception as error:
        raise HostedFailureCheckInvalid("hosted_failure_recovery_invalid") from error
    if rehearsal_error is not None:
        raise HostedFailureCheckInvalid(
            "hosted_failure_rehearsal_failed"
        ) from rehearsal_error
    return {
        "scenario": scenario,
        "rehearsal_revision_suffix": rehearsal_suffix,
        "recovery_revision_suffix": recovery_suffix,
        "patch_count": 2,
    }


def main(_arguments: list[str] | None = None) -> int:
    """Refuse standalone execution; the exact-package runner injects actions."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(_arguments)
    print("hosted_failure_check=package_runner_required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
