#!/usr/bin/env python3
"""Create one owner-only, no-Key Container Apps AI-disabled recovery package."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from uuid import UUID

_LOCAL_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_LOCAL_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_LOCAL_PROJECT_ROOT))

from scripts.create_ai_enablement_package import (  # noqa: E402
    AIEnablementPackageInvalid,
    capture_repository_state,
)


PACKAGE_SCHEMA = "newcaostone.ai-disabled-recovery-package.v1"
AUTHORIZED_BRANCH = "codex/ai-enable-preset-buttons"
EXECUTION = {
    "azure.read.sanitized": 6,
    "azure.write.containerapp.patch": 1,
    "keyvault.secret.read": 0,
    "keyvault.secret.write": 0,
    "openai.paid": 0,
}
PROJECT_ROOT = _LOCAL_PROJECT_ROOT
AZURE_TARGET = {
    "subscription_id": "fc89e7d3-5428-425e-863f-415859810c2c",
    "tenant_id": "13d04c38-d91c-4f9f-8b65-6af2b515dd63",
    "resource_group": "rg-bizpulse-centralus",
    "location": "centralus",
    "app_name": "newcaostone-demo-app",
    "registry_name": "sellernorthbpacr",
    "vault_name": "newcaostone-ai-kv",
    "identity_name": "newcaostone-ai-identity",
    "existing_registry_identity_name": "newcaostone-demo-registry",
}
ARTIFACTS = {
    "package": ".tmp/LAUNCH_AUTHORIZATION_AI_DISABLED_RECOVERY_R10_2026-08-17.json",
    "receipt": ".tmp/AI_DISABLED_RECOVERY_RECEIPT_R10_2026-08-17.json",
    "observation": ".tmp/AI_DISABLED_RECOVERY_OBSERVATION_R10_2026-08-17.json",
}
RECOVERY_CONTROL_PATHS = (
    "requirements.txt",
    "scripts/ai_enablement_contract.py",
    "scripts/azure_arm_lro.py",
    "scripts/azure_ai_enablement_actions.py",
    "scripts/azure_ai_reconciliation.py",
    "scripts/azure_ai_revision.py",
    "scripts/browser_process_env.mjs",
    "scripts/browser_release_gate.mjs",
    "scripts/create_ai_disabled_recovery_package.py",
    "scripts/run_ai_disabled_recovery.py",
    "scripts/run_ai_enablement.py",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_REVISION = re.compile(r"[a-z][a-z0-9-]{2,126}")
_IMAGE = re.compile(
    r"[a-z0-9][a-z0-9-]{2,49}\.azurecr\.io/"
    r"[a-z0-9][a-z0-9._/-]{1,127}@sha256:[0-9a-f]{64}"
)
_AUTHORITY_KEYS = frozenset(
    {
        "subscription_id",
        "tenant_id",
        "resource_group",
        "location",
        "app_name",
        "registry_name",
        "vault_name",
        "identity_name",
        "existing_registry_identity_name",
        "latest_revision",
        "latest_ready_revision",
        "image",
        "active_revisions_mode",
        "traffic",
        "ai_chat_enabled",
        "budget_failure_rehearsal",
        "identity_ids",
        "revision_active",
        "revision_health",
        "revision_provisioning",
        "vault_rbac_enabled",
        "vault_public_network_enabled",
        "identity_exists",
        "manifest_digest",
    }
)
_PACKAGE_KEYS = frozenset(
    {
        "schema_version",
        "issued_at",
        "expires_at",
        "approval",
        "repository",
        "control_sha256",
        "azure_target",
        "source",
        "target",
        "execution",
        "stop_conditions",
    }
)


class AIDisabledRecoveryPackageInvalid(ValueError):
    """The recovery authority or package is unsafe, stale, or malformed."""


def _invalid(code: str = "ai_disabled_recovery_package_invalid") -> AIDisabledRecoveryPackageInvalid:
    return AIDisabledRecoveryPackageInvalid(code)


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


def _uuid4(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
    except ValueError:
        return False
    return parsed.version == 4 and str(parsed) == value


def _identity_id(
    *, subscription_id: str, resource_group: str, identity_name: str
) -> str:
    return (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/"
        "providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
        f"{identity_name}"
    )


def _location_identifier(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(character for character in value.casefold() if character.isalnum())


def _validate_authority(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _AUTHORITY_KEYS:
        raise _invalid("ai_disabled_recovery_authority_drift")
    raw = dict(value)
    if (
        not _uuid4(raw["subscription_id"])
        or not _uuid4(raw["tenant_id"])
        or any(
            not isinstance(raw[name], str) or not raw[name]
            for name in (
                "resource_group",
                "location",
                "app_name",
                "registry_name",
                "vault_name",
                "identity_name",
                "existing_registry_identity_name",
            )
        )
        or raw["latest_revision"] != raw["latest_ready_revision"]
        or not isinstance(raw["latest_revision"], str)
        or _REVISION.fullmatch(raw["latest_revision"]) is None
        or not isinstance(raw["image"], str)
        or _IMAGE.fullmatch(raw["image"]) is None
        or raw["active_revisions_mode"] != "Single"
        or raw["traffic"] != [{"latestRevision": True, "weight": 100}]
        or raw["ai_chat_enabled"] is not True
        or raw["budget_failure_rehearsal"] is not True
        or raw["revision_active"] is not True
        or raw["revision_health"] != "Healthy"
        or raw["revision_provisioning"] != "Provisioned"
        or raw["vault_rbac_enabled"] is not True
        or raw["vault_public_network_enabled"] is not True
        or raw["identity_exists"] is not True
    ):
        raise _invalid("ai_disabled_recovery_authority_drift")
    digest = raw["image"].rsplit("@", 1)[-1]
    if raw["manifest_digest"] != digest:
        raise _invalid("ai_disabled_recovery_authority_drift")
    registry_identity = _identity_id(
        subscription_id=str(raw["subscription_id"]),
        resource_group=str(raw["resource_group"]),
        identity_name=str(raw["existing_registry_identity_name"]),
    )
    ai_identity = _identity_id(
        subscription_id=str(raw["subscription_id"]),
        resource_group=str(raw["resource_group"]),
        identity_name=str(raw["identity_name"]),
    )
    if raw["identity_ids"] != [registry_identity, ai_identity]:
        raise _invalid("ai_disabled_recovery_authority_drift")
    return raw


def _validate_repository(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "branch",
        "head_sha",
        "tree_sha",
        "clean",
    }:
        raise _invalid()
    result = dict(value)
    if (
        result["branch"] != AUTHORIZED_BRANCH
        or not isinstance(result["head_sha"], str)
        or _GIT_SHA.fullmatch(result["head_sha"]) is None
        or not isinstance(result["tree_sha"], str)
        or _GIT_SHA.fullmatch(result["tree_sha"]) is None
        or result["clean"] is not True
    ):
        raise _invalid()
    return result


def _validate_controls(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise _invalid()
    result = {str(path): item for path, item in value.items()}
    if (
        len(result) != len(value)
        or any(
            not path
            or path.startswith("/")
            or not isinstance(item, str)
            or _SHA256.fullmatch(item) is None
            for path, item in result.items()
        )
    ):
        raise _invalid()
    return dict(sorted(result.items()))


def _collect_recovery_control_sha256(
    *,
    project_root: Path = PROJECT_ROOT,
    paths: tuple[str, ...] = RECOVERY_CONTROL_PATHS,
) -> dict[str, str]:
    """Hash only the files that can affect an R10 disabled recovery."""

    result: dict[str, str] = {}
    try:
        root = project_root.resolve(strict=True)
        for relative in paths:
            raw = root / relative
            raw_metadata = raw.lstat()
            path = raw.resolve(strict=True)
            if (
                not path.is_relative_to(root)
                or path != raw
                or not stat.S_ISREG(raw_metadata.st_mode)
                or stat.S_ISLNK(raw_metadata.st_mode)
            ):
                raise _invalid("ai_disabled_recovery_control_drift")
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise _invalid("ai_disabled_recovery_control_drift") from error
    return _validate_controls(result)


def _write_exclusive_json(path: Path, payload: Mapping[str, object]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        raise _invalid("ai_disabled_recovery_package_write_failed") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _safe_process_environment(source: Mapping[str, str]) -> dict[str, str]:
    names = ("AZURE_CONFIG_DIR", "HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")
    return {
        name: value for name in names if isinstance((value := source.get(name)), str)
    }


def _run_json(
    command: list[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    environment: Mapping[str, str],
) -> object:
    try:
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            shell=False,
            env=environment,
        )
        if (
            completed.returncode != 0
            or not isinstance(completed.stdout, str)
            or len(completed.stdout) > 1_000_000
        ):
            raise TypeError
        return json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, TypeError, json.JSONDecodeError):
        raise _invalid("ai_disabled_recovery_authority_drift") from None


def _capture_ai_disabled_recovery_authority_state(
    target: Mapping[str, object],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    environment: Mapping[str, str] = os.environ,
) -> tuple[dict[str, object], dict[str, object]]:
    """Perform six non-secret reads and retain one in-memory app projection."""

    required = {
        "subscription_id",
        "tenant_id",
        "resource_group",
        "location",
        "app_name",
        "registry_name",
        "vault_name",
        "identity_name",
        "existing_registry_identity_name",
    }
    if not isinstance(target, Mapping) or set(target) != required:
        raise _invalid("ai_disabled_recovery_authority_drift")
    values = {name: target[name] for name in required}
    if not _uuid4(values["subscription_id"]) or not _uuid4(values["tenant_id"]):
        raise _invalid("ai_disabled_recovery_authority_drift")
    if any(
        not isinstance(values[name], str) or not values[name]
        for name in required - {"subscription_id", "tenant_id"}
    ):
        raise _invalid("ai_disabled_recovery_authority_drift")
    child_environment = _safe_process_environment(environment)
    subscription = str(values["subscription_id"])
    resource_group = str(values["resource_group"])
    app_name = str(values["app_name"])
    account = _run_json(
        [
            "az",
            "account",
            "show",
            "--query",
            "{id:id,tenantId:tenantId}",
            "--only-show-errors",
            "--output",
            "json",
        ],
        runner=runner,
        environment=child_environment,
    )
    app = _run_json(
        [
            "az",
            "containerapp",
            "show",
            "--subscription",
            subscription,
            "--resource-group",
            resource_group,
            "--name",
            app_name,
            "--query",
            (
                "{location:location,identity:identity,properties:{latestRevisionName:"
                "properties.latestRevisionName,latestReadyRevisionName:properties."
                "latestReadyRevisionName,provisioningState:properties.provisioningState,"
                "configuration:{activeRevisionsMode:properties.configuration."
                "activeRevisionsMode,ingress:{external:properties.configuration."
                "ingress.external,fqdn:properties.configuration.ingress.fqdn,traffic:"
                "properties.configuration.ingress.traffic},registries:properties."
                "configuration.registries[].{server:server,identity:identity}},"
                "template:properties.template}}"
            ),
            "--only-show-errors",
            "--output",
            "json",
        ],
        runner=runner,
        environment=child_environment,
    )
    if not isinstance(app, Mapping):
        raise _invalid("ai_disabled_recovery_authority_drift")
    try:
        properties = app["properties"]
        configuration = properties["configuration"]
        containers = properties["template"]["containers"]
        identity = app["identity"]
        assigned = identity["userAssignedIdentities"]
    except (KeyError, TypeError):
        raise _invalid("ai_disabled_recovery_authority_drift") from None
    latest_revision = properties.get("latestRevisionName") if isinstance(properties, Mapping) else None
    revision = _run_json(
        [
            "az",
            "containerapp",
            "revision",
            "show",
            "--subscription",
            subscription,
            "--resource-group",
            resource_group,
            "--name",
            app_name,
            "--revision",
            str(latest_revision),
            "--query",
            "{name:name,properties:{active:properties.active,healthState:properties.healthState,provisioningState:properties.provisioningState}}",
            "--only-show-errors",
            "--output",
            "json",
        ],
        runner=runner,
        environment=child_environment,
    )
    identity_metadata = _run_json(
        [
            "az",
            "identity",
            "show",
            "--subscription",
            subscription,
            "--resource-group",
            resource_group,
            "--name",
            str(values["identity_name"]),
            "--query",
            "{id:id}",
            "--only-show-errors",
            "--output",
            "json",
        ],
        runner=runner,
        environment=child_environment,
    )
    vault = _run_json(
        [
            "az",
            "keyvault",
            "show",
            "--subscription",
            subscription,
            "--resource-group",
            resource_group,
            "--name",
            str(values["vault_name"]),
            "--query",
            "{properties:{enableRbacAuthorization:properties.enableRbacAuthorization,publicNetworkAccess:properties.publicNetworkAccess,provisioningState:properties.provisioningState}}",
            "--only-show-errors",
            "--output",
            "json",
        ],
        runner=runner,
        environment=child_environment,
    )
    image = containers[0].get("image") if isinstance(containers, list) and len(containers) == 1 and isinstance(containers[0], Mapping) else None
    digest = image.rsplit("@", 1)[-1] if isinstance(image, str) else None
    manifest = _run_json(
        [
            "az",
            "acr",
            "manifest",
            "show-metadata",
            "--registry",
            str(values["registry_name"]),
            "--name",
            f"bizpulse@{digest}",
            "--query",
            "{digest:digest}",
            "--only-show-errors",
            "--output",
            "json",
        ],
        runner=runner,
        environment=child_environment,
    )
    try:
        environment_rows = containers[0]["env"]
        by_name = {
            row["name"]: row["value"]
            for row in environment_rows
            if isinstance(row, Mapping)
            and isinstance(row.get("name"), str)
            and isinstance(row.get("value"), str)
        }
        revision_properties = revision["properties"]
        vault_properties = vault["properties"]
    except (KeyError, TypeError):
        raise _invalid("ai_disabled_recovery_authority_drift") from None
    registry_identity = _identity_id(
        subscription_id=subscription,
        resource_group=resource_group,
        identity_name=str(values["existing_registry_identity_name"]),
    )
    ai_identity = _identity_id(
        subscription_id=subscription,
        resource_group=resource_group,
        identity_name=str(values["identity_name"]),
    )
    authority = {
        **values,
        "latest_revision": latest_revision,
        "latest_ready_revision": properties.get("latestReadyRevisionName"),
        "image": image,
        "active_revisions_mode": configuration.get("activeRevisionsMode"),
        "traffic": configuration.get("ingress", {}).get("traffic"),
        "ai_chat_enabled": by_name.get("BIZPULSE_AI_CHAT_ENABLED") == "true",
        "budget_failure_rehearsal": by_name.get("BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL") == "true",
        "identity_ids": [registry_identity, ai_identity],
        "revision_active": revision_properties.get("active"),
        "revision_health": revision_properties.get("healthState"),
        "revision_provisioning": revision_properties.get("provisioningState"),
        "vault_rbac_enabled": vault_properties.get("enableRbacAuthorization"),
        "vault_public_network_enabled": vault_properties.get("publicNetworkAccess") == "Enabled",
        "identity_exists": isinstance(identity_metadata, Mapping)
        and isinstance(identity_metadata.get("id"), str)
        and identity_metadata["id"].casefold() == ai_identity.casefold(),
        "manifest_digest": manifest.get("digest") if isinstance(manifest, Mapping) else None,
    }
    if (
        account != {"id": subscription, "tenantId": values["tenant_id"]}
        or _location_identifier(app.get("location"))
        != _location_identifier(values["location"])
        or not isinstance(identity, Mapping)
        or identity.get("type") != "UserAssigned"
        or not isinstance(assigned, Mapping)
        or {str(item).casefold() for item in assigned}
        != {registry_identity.casefold(), ai_identity.casefold()}
        or properties.get("provisioningState") != "Succeeded"
        or revision.get("name") != latest_revision
        or vault_properties.get("provisioningState") != "Succeeded"
    ):
        raise _invalid("ai_disabled_recovery_authority_drift")
    return _validate_authority(authority), dict(app)


def capture_ai_disabled_recovery_authority(
    target: Mapping[str, object],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    environment: Mapping[str, str] = os.environ,
) -> dict[str, object]:
    """Perform exactly six non-secret reads of the R8 budget rehearsal state."""

    authority, _app = _capture_ai_disabled_recovery_authority_state(
        target,
        runner=runner,
        environment=environment,
    )
    return authority


def validate_ai_disabled_recovery_package(value: object) -> dict[str, object]:
    """Validate the closed, no-Key recovery package body."""

    if not isinstance(value, Mapping) or set(value) != _PACKAGE_KEYS:
        raise _invalid()
    package = dict(value)
    issued_at = _parse_utc(package["issued_at"])
    expires_at = _parse_utc(package["expires_at"])
    if (
        package["schema_version"] != PACKAGE_SCHEMA
        or expires_at <= issued_at
        or expires_at - issued_at > timedelta(hours=24)
        or package["approval"] != {"approved_sha256": None, "approved_at": None}
        or package["execution"] != EXECUTION
        or package["stop_conditions"]
        != [
            "authority_drift",
            "arm_operation_failed",
            "revision_unverified",
            "browser_gate_failed",
        ]
    ):
        raise _invalid()
    repository = _validate_repository(package["repository"])
    controls = _validate_controls(package["control_sha256"])
    target = package["azure_target"]
    source = package["source"]
    destination = package["target"]
    if (
        not isinstance(target, Mapping)
        or set(target)
        != {
            "subscription_id",
            "tenant_id",
            "resource_group",
            "location",
            "app_name",
            "registry_name",
            "vault_name",
            "identity_name",
            "existing_registry_identity_name",
        }
        or not isinstance(source, Mapping)
        or set(source)
        != {
            "revision",
            "image",
            "active_revisions_mode",
            "traffic",
            "ai_chat_enabled",
            "budget_failure_rehearsal",
            "identity_ids",
            "revision_active",
            "revision_health",
            "revision_provisioning",
        }
        or not isinstance(destination, Mapping)
        or set(destination)
        != {
            "candidate_image",
            "ai_chat_enabled",
            "budget_failure_rehearsal",
            "identity_ids",
            "role",
        }
        or not _uuid4(target.get("subscription_id"))
        or not _uuid4(target.get("tenant_id"))
        or any(
            not isinstance(target.get(name), str) or not target[name]
            for name in (
                "resource_group",
                "location",
                "app_name",
                "registry_name",
                "vault_name",
                "identity_name",
                "existing_registry_identity_name",
            )
        )
        or not isinstance(source.get("revision"), str)
        or _REVISION.fullmatch(source["revision"]) is None
        or not isinstance(source.get("image"), str)
        or _IMAGE.fullmatch(source["image"]) is None
        or source.get("active_revisions_mode") != "Single"
        or source.get("traffic") != [{"latestRevision": True, "weight": 100}]
        or source.get("ai_chat_enabled") is not True
        or source.get("budget_failure_rehearsal") is not True
        or source.get("revision_active") is not True
        or source.get("revision_health") != "Healthy"
        or source.get("revision_provisioning") != "Provisioned"
        or destination.get("candidate_image") != source["image"]
        or destination.get("ai_chat_enabled") is not False
        or destination.get("budget_failure_rehearsal") is not False
        or destination.get("role") != "emergency_disabled"
    ):
        raise _invalid()
    registry_identity = _identity_id(
        subscription_id=str(target["subscription_id"]),
        resource_group=str(target["resource_group"]),
        identity_name=str(target["existing_registry_identity_name"]),
    )
    ai_identity = _identity_id(
        subscription_id=str(target["subscription_id"]),
        resource_group=str(target["resource_group"]),
        identity_name=str(target["identity_name"]),
    )
    if (
        source.get("identity_ids") != [registry_identity, ai_identity]
        or destination.get("identity_ids") != [registry_identity]
    ):
        raise _invalid()
    return {
        "schema_version": PACKAGE_SCHEMA,
        "issued_at": _utc_text(issued_at),
        "expires_at": _utc_text(expires_at),
        "approval": {"approved_sha256": None, "approved_at": None},
        "repository": repository,
        "control_sha256": controls,
        "azure_target": dict(target),
        "source": dict(source),
        "target": dict(destination),
        "execution": dict(EXECUTION),
        "stop_conditions": list(package["stop_conditions"]),
    }


def generate_ai_disabled_recovery_package(
    *,
    output_path: Path,
    receipt_path: Path,
    observation_path: Path,
    authority_reader: Callable[[], object],
    repository_reader: Callable[[], object],
    control_reader: Callable[[], object],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    """Write a fresh R10 package only after a non-secret exact authority read."""

    if (
        output_path.exists()
        or receipt_path.exists()
        or observation_path.exists()
        or output_path.parent != receipt_path.parent
        or output_path.parent != observation_path.parent
    ):
        raise _invalid("ai_disabled_recovery_artifact_conflict")
    authority = _validate_authority(authority_reader())
    repository = _validate_repository(repository_reader())
    controls = _validate_controls(control_reader())
    issued_at = now()
    if not isinstance(issued_at, datetime):
        raise _invalid()
    issued_text = _utc_text(issued_at)
    expires_text = _utc_text(issued_at + timedelta(hours=24))
    source = {
        "revision": authority["latest_revision"],
        "image": authority["image"],
        "active_revisions_mode": authority["active_revisions_mode"],
        "traffic": authority["traffic"],
        "ai_chat_enabled": True,
        "budget_failure_rehearsal": True,
        "identity_ids": authority["identity_ids"],
        "revision_active": True,
        "revision_health": "Healthy",
        "revision_provisioning": "Provisioned",
    }
    target = {
        "candidate_image": authority["image"],
        "ai_chat_enabled": False,
        "budget_failure_rehearsal": False,
        "identity_ids": [authority["identity_ids"][0]],
        "role": "emergency_disabled",
    }
    package = {
        "schema_version": PACKAGE_SCHEMA,
        "issued_at": issued_text,
        "expires_at": expires_text,
        "approval": {"approved_sha256": None, "approved_at": None},
        "repository": repository,
        "control_sha256": controls,
        "azure_target": {
            key: authority[key]
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
        },
        "source": source,
        "target": target,
        "execution": dict(EXECUTION),
        "stop_conditions": [
            "authority_drift",
            "arm_operation_failed",
            "revision_unverified",
            "browser_gate_failed",
        ],
    }
    package = validate_ai_disabled_recovery_package(package)
    _write_exclusive_json(output_path, package)
    return {
        "package_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "expires_at": expires_text,
        "execution": dict(EXECUTION),
    }


def main(arguments: list[str] | None = None) -> int:
    """Create only the next owner-approved no-Key recovery package."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--observation", type=Path, required=True)
    options = parser.parse_args(arguments)
    expected = {name: (PROJECT_ROOT / path).resolve() for name, path in ARTIFACTS.items()}
    if (
        options.output.resolve() != expected["package"]
        or options.receipt.resolve() != expected["receipt"]
        or options.observation.resolve() != expected["observation"]
    ):
        print("ai_disabled_recovery_package=failed")
        return 1
    try:
        generated = generate_ai_disabled_recovery_package(
            output_path=options.output,
            receipt_path=options.receipt,
            observation_path=options.observation,
            authority_reader=lambda: capture_ai_disabled_recovery_authority(AZURE_TARGET),
            repository_reader=capture_repository_state,
            control_reader=_collect_recovery_control_sha256,
        )
    except (AIDisabledRecoveryPackageInvalid, AIEnablementPackageInvalid, OSError):
        print("ai_disabled_recovery_package=failed")
        return 1
    print("ai_disabled_recovery_package=created")
    print(f"package_sha256={generated['package_sha256']}")
    print(f"expires_at={generated['expires_at']}")
    print("key_vault_secret_reads=0")
    print("key_vault_secret_writes=0")
    print("openai_paid_calls=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
