"""Build a read-only, redacted authority package for one operator rotation."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.operator_rotation_keychain import (  # noqa: E402
    MacOSKeychainBackend,
    OperatorCredentialPair,
    OperatorRotationKeychain,
)
from scripts.verify_hosted_health import (  # noqa: E402
    EXPECTED_READY,
    HostedHealthInvalid,
    verify_hosted_health,
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_SHA1 = re.compile(r"[0-9a-f]{40}")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_MANAGED_IDENTITY_RESOURCE_ID = re.compile(
    r"/subscriptions/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}/resourceGroups/"
    r"[A-Za-z0-9._()-]{1,90}/providers/Microsoft\.ManagedIdentity/"
    r"userAssignedIdentities/[A-Za-z0-9-]{1,128}",
    re.IGNORECASE,
)
_IMAGE = re.compile(r"[^\s@/]+(?:/[^\s@]+)+@sha256:[0-9a-f]{64}")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._()/-]{0,127}")
_SCHEMA_VERSION = "newcaostone.operator-password-rotation.v3"
_DELIVERY_CONTRACT = "job-only-stage-v1"
_DEPLOYMENT_PROFILE_SCHEMA_VERSION = (
    "newcaostone.operator-password-rotation-deployment-profile.v1"
)
_DEPLOYMENT_PARAMETER_NAMES = frozenset(
    {
        "namePrefix",
        "location",
        "syntheticManifestSha256",
        "syntheticDatasetVersionId",
        "registryName",
        "postgresAdministratorLogin",
        "postgresServerName",
        "aiChatEnabled",
        "openaiKeyVaultUrl",
        "openaiManagedIdentityClientId",
        "openaiManagedIdentityResourceId",
        "aiBudgetFailureRehearsal",
        "aiDailyAttemptLimit",
        "aiMonthlyTokenLimit",
        "aiMaxConcurrentTurns",
        "aiSessionAttemptLimitPerMinute",
        "aiGlobalAttemptLimitPerMinute",
        "demoSessionRateLimitPerHour",
        "storageSku",
        "storageAccountName",
        "postgresSkuName",
        "postgresTier",
        "postgresStorageSizeGb",
        "postgresBackupRetentionDays",
        "logRetentionDays",
        "vnetAddressPrefix",
        "appSubnetPrefix",
        "postgresSubnetPrefix",
        "tags",
    }
)
_NAME_PREFIX = re.compile(r"[a-z][a-z0-9-]{2,17}")
_AZURE_NAME = re.compile(r"[a-z][a-z0-9-]{2,62}[a-z0-9]")
_REGISTRY_NAME = re.compile(r"[a-z0-9]{5,50}")
_SIMPLE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_SKU = re.compile(r"[A-Za-z0-9_]{3,64}")
_TAG_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_TAG_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}")


class OperatorRotationAuthorityInvalid(RuntimeError):
    """Raised for a missing or drifted rotation precondition without secrets."""


def build_rotation_authority(
    *,
    current: OperatorCredentialPair,
    pending: OperatorCredentialPair,
    subscription_id: str,
    resource_group: str,
    app_name: str,
    image: str,
    git_sha: str,
    deployment_parameters: Mapping[str, object],
    app: Mapping[str, object],
    health: Mapping[str, object],
) -> dict[str, object]:
    """Validate local and hosted read-only evidence, then bind it to one ID."""

    _validate_pair(current, "current")
    _validate_pair(pending, "pending")
    if hmac.compare_digest(current.password, pending.password):
        raise OperatorRotationAuthorityInvalid("pending_pair_matches_current")
    if (
        _UUID.fullmatch(subscription_id) is None
        or _NAME.fullmatch(resource_group) is None
        or _NAME.fullmatch(app_name) is None
        or _IMAGE.fullmatch(image) is None
        or _SHA1.fullmatch(git_sha) is None
    ):
        raise OperatorRotationAuthorityInvalid("rotation_authority_input_invalid")
    target = _validate_app(app, app_name)
    _validate_health(health)
    validated_parameters = _validate_deployment_parameters(deployment_parameters)
    payload: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "operation": "operator-password-rotation",
        "target": {
            "subscription_id": subscription_id,
            "resource_group": resource_group,
            "app": app_name,
            "fqdn": target["fqdn"],
        },
        "source": {
            "git_sha": git_sha,
            "image": image,
        },
        "deployment": {
            "parameters": validated_parameters,
        },
        "delivery": {
            "contract": _DELIVERY_CONTRACT,
        },
        "expected": {
            "active_image": target["active_image"],
            "active_revision": target["active_revision"],
            "old_hash_sha256": _fingerprint(current.password_hash),
            "new_hash_sha256": _fingerprint(pending.password_hash),
        },
        "preconditions": [
            "active_image_matches",
            "single_revision_mode",
            "latest_ready_revision_matches",
            "ready_health_all_checks_ok",
            "current_pair_matches",
            "pending_pair_matches",
            "pending_differs_from_current",
        ],
        "rollback": {
            "automatic": False,
            "requires_new_authority": True,
            "expected_hash_sha256": _fingerprint(pending.password_hash),
        },
    }
    rotation_id = _canonical_sha256(payload)
    return {**payload, "rotation_id": rotation_id}


def build_inverse_rotation_authority(
    *,
    forward_authority: Mapping[str, object],
    current: OperatorCredentialPair,
    pending: OperatorCredentialPair,
    app: Mapping[str, object],
) -> dict[str, object]:
    """Create a new, separately approvable inverse from one forward package.

    The inverse does not assume the forward Job committed.  Its expected-hash
    guard makes the eventual Job a no-op conflict unless the database holds
    exactly the forward target hash.
    """

    _validate_pair(current, "current")
    _validate_pair(pending, "pending")
    forward = _validate_forward_authority(forward_authority)
    expected = forward["expected"]
    if (
        not hmac.compare_digest(
            _fingerprint(current.password_hash), expected["old_hash_sha256"]
        )
        or not hmac.compare_digest(
            _fingerprint(pending.password_hash), expected["new_hash_sha256"]
        )
        or hmac.compare_digest(current.password, pending.password)
    ):
        raise OperatorRotationAuthorityInvalid("inverse_keychain_drift")
    target = forward["target"]
    source = forward["source"]
    observed = _validate_inverse_app(
        app,
        app_name=target["app"],
        image=source["image"],
        expected_fqdn=target["fqdn"],
    )
    payload: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "operation": "operator-password-inverse",
        "inverse_of": forward["rotation_id"],
        "target": target,
        "source": source,
        "deployment": forward["deployment"],
        "delivery": forward["delivery"],
        "expected": {
            "active_revision": observed["active_revision"],
            "old_hash_sha256": _fingerprint(pending.password_hash),
            "new_hash_sha256": _fingerprint(current.password_hash),
        },
        "preconditions": [
            "single_revision_mode",
            "source_image_matches",
            "current_keychain_matches_forward_old",
            "pending_keychain_matches_forward_new",
            "exact_inverse_job_guard",
        ],
        "rollback": {
            "automatic": False,
            "requires_new_authority": True,
            "expected_hash_sha256": _fingerprint(current.password_hash),
        },
    }
    return {**payload, "rotation_id": _canonical_sha256(payload)}


def write_rotation_authority(path: Path, authority: Mapping[str, object]) -> None:
    """Write a new immutable local package with restrictive file permissions."""

    serialized = json.dumps(dict(authority), indent=2, sort_keys=True) + "\n"
    destination = path.resolve()
    try:
        destination.relative_to(PROJECT_ROOT.resolve())
    except ValueError as error:
        raise OperatorRotationAuthorityInvalid(
            "authority_output_outside_project"
        ) from error
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        try:
            if stat.S_IMODE(destination.stat().st_mode) != 0o600:
                raise OperatorRotationAuthorityInvalid(
                    "authority_output_permissions_invalid"
                )
            existing = destination.read_text()
        except OperatorRotationAuthorityInvalid:
            raise
        except OSError as error:
            raise OperatorRotationAuthorityInvalid(
                "authority_output_unreadable"
            ) from error
        if not hmac.compare_digest(existing, serialized):
            raise OperatorRotationAuthorityInvalid("authority_output_conflict")
        return
    try:
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(serialized)
        os.chmod(destination, 0o600)
    except OSError as error:
        raise OperatorRotationAuthorityInvalid(
            "authority_output_write_failed"
        ) from error


def generate_rotation_authority(
    *,
    subscription_id: str,
    resource_group: str,
    app_name: str,
    image: str,
    git_sha: str,
    deployment_parameters: Mapping[str, object],
    keychain: OperatorRotationKeychain,
    az_reader: Callable[[Sequence[str]], object],
    health_reader: Callable[[str], Mapping[str, object]],
) -> dict[str, object]:
    app = az_reader(
        (
            "containerapp",
            "show",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--name",
            app_name,
        )
    )
    if not isinstance(app, Mapping):
        raise OperatorRotationAuthorityInvalid("azure_app_read_invalid")
    app_target = _validate_app(app, app_name)
    health = health_reader(f"https://{app_target['fqdn']}/health/ready")
    return build_rotation_authority(
        current=keychain.current_pair(),
        pending=keychain.pending_pair(),
        subscription_id=subscription_id,
        resource_group=resource_group,
        app_name=app_name,
        image=image,
        git_sha=git_sha,
        deployment_parameters=deployment_parameters,
        app=app,
        health=health,
    )


def generate_inverse_rotation_authority(
    *,
    forward_authority: Mapping[str, object],
    keychain: OperatorRotationKeychain,
    az_reader: Callable[[Sequence[str]], object],
) -> dict[str, object]:
    """Read one bound app and produce a fresh inverse authority without writes."""

    forward = _validate_forward_authority(forward_authority)
    target = forward["target"]
    app = az_reader(
        (
            "containerapp",
            "show",
            "--subscription",
            str(target["subscription_id"]),
            "--resource-group",
            str(target["resource_group"]),
            "--name",
            str(target["app"]),
        )
    )
    if not isinstance(app, Mapping):
        raise OperatorRotationAuthorityInvalid("azure_app_read_invalid")
    return build_inverse_rotation_authority(
        forward_authority=forward_authority,
        current=keychain.current_pair(),
        pending=keychain.pending_pair(),
        app=app,
    )


def _validate_pair(pair: OperatorCredentialPair, name: str) -> None:
    try:
        verified = PasswordHasher().verify(pair.password_hash, pair.password)
    except (InvalidHashError, VerificationError) as error:
        raise OperatorRotationAuthorityInvalid(f"{name}_pair_invalid") from error
    if not verified:
        raise OperatorRotationAuthorityInvalid(f"{name}_pair_invalid")


def _validate_app(
    app: Mapping[str, object],
    app_name: str,
) -> dict[str, str]:
    properties = app.get("properties")
    if not isinstance(properties, Mapping):
        raise OperatorRotationAuthorityInvalid("azure_app_read_invalid")
    configuration = properties.get("configuration")
    if not isinstance(configuration, Mapping):
        raise OperatorRotationAuthorityInvalid("azure_app_read_invalid")
    ingress = configuration.get("ingress")
    if not isinstance(ingress, Mapping):
        raise OperatorRotationAuthorityInvalid("azure_app_read_invalid")
    fqdn = ingress.get("fqdn")
    ready = properties.get("latestReadyRevisionName")
    latest = properties.get("latestRevisionName")
    traffic = ingress.get("traffic")
    template = properties.get("template")
    containers = template.get("containers") if isinstance(template, Mapping) else None
    active_image = (
        containers[0].get("image")
        if isinstance(containers, list)
        and len(containers) == 1
        and isinstance(containers[0], Mapping)
        else None
    )
    if (
        app.get("name") != app_name
        or properties.get("provisioningState") != "Succeeded"
        or configuration.get("activeRevisionsMode") != "Single"
        or ingress.get("external") is not True
        or not isinstance(fqdn, str)
        or not fqdn.endswith(".azurecontainerapps.io")
        or not isinstance(ready, str)
        or ready != latest
        or traffic != [{"latestRevision": True, "weight": 100}]
        or not isinstance(containers, list)
        or len(containers) != 1
        or not isinstance(containers[0], Mapping)
        or not isinstance(active_image, str)
        or _IMAGE.fullmatch(active_image) is None
    ):
        raise OperatorRotationAuthorityInvalid("azure_app_state_invalid")
    return {
        "active_image": active_image,
        "fqdn": fqdn,
        "active_revision": ready,
    }


def _validate_inverse_app(
    app: Mapping[str, object],
    *,
    app_name: str,
    image: str,
    expected_fqdn: str,
) -> dict[str, str]:
    """Validate target identity while deliberately allowing a failed readiness gate."""

    properties = app.get("properties")
    if not isinstance(properties, Mapping):
        raise OperatorRotationAuthorityInvalid("inverse_app_state_invalid")
    configuration = properties.get("configuration")
    ingress = (
        configuration.get("ingress") if isinstance(configuration, Mapping) else None
    )
    template = properties.get("template")
    containers = template.get("containers") if isinstance(template, Mapping) else None
    latest = properties.get("latestRevisionName")
    if (
        app.get("name") != app_name
        or properties.get("provisioningState") != "Succeeded"
        or not isinstance(configuration, Mapping)
        or configuration.get("activeRevisionsMode") != "Single"
        or not isinstance(ingress, Mapping)
        or ingress.get("external") is not True
        or ingress.get("fqdn") != expected_fqdn
        or ingress.get("traffic") != [{"latestRevision": True, "weight": 100}]
        or not isinstance(latest, str)
        or not isinstance(containers, list)
        or len(containers) != 1
        or not isinstance(containers[0], Mapping)
        or containers[0].get("image") != image
    ):
        raise OperatorRotationAuthorityInvalid("inverse_app_state_invalid")
    return {"active_revision": latest}


def _validate_forward_authority(
    authority: Mapping[str, object],
) -> dict[str, dict[str, object] | str]:
    """Read only the public fields that may seed a new inverse package."""

    payload = dict(authority)
    rotation_id = payload.pop("rotation_id", None)
    if (
        authority.get("schema_version") != _SCHEMA_VERSION
        or authority.get("operation") != "operator-password-rotation"
        or not isinstance(rotation_id, str)
        or _SHA256.fullmatch(rotation_id) is None
        or not hmac.compare_digest(rotation_id, _canonical_sha256(payload))
    ):
        raise OperatorRotationAuthorityInvalid("forward_authority_invalid")
    target = authority.get("target")
    source = authority.get("source")
    deployment = authority.get("deployment")
    delivery = authority.get("delivery")
    expected = authority.get("expected")
    if (
        not isinstance(target, Mapping)
        or not isinstance(source, Mapping)
        or not isinstance(deployment, Mapping)
        or not isinstance(delivery, Mapping)
        or not isinstance(expected, Mapping)
    ):
        raise OperatorRotationAuthorityInvalid("forward_authority_invalid")
    subscription_id = target.get("subscription_id")
    resource_group = target.get("resource_group")
    app_name = target.get("app")
    fqdn = target.get("fqdn")
    image = source.get("image")
    git_sha = source.get("git_sha")
    parameters = deployment.get("parameters")
    if (
        not isinstance(subscription_id, str)
        or _UUID.fullmatch(subscription_id) is None
        or not isinstance(resource_group, str)
        or _NAME.fullmatch(resource_group) is None
        or not isinstance(app_name, str)
        or _NAME.fullmatch(app_name) is None
        or not isinstance(fqdn, str)
        or not fqdn.endswith(".azurecontainerapps.io")
        or not isinstance(image, str)
        or _IMAGE.fullmatch(image) is None
        or not isinstance(git_sha, str)
        or _SHA1.fullmatch(git_sha) is None
        or not isinstance(parameters, Mapping)
    ):
        raise OperatorRotationAuthorityInvalid("forward_authority_invalid")
    _validate_deployment_parameters(parameters)
    validated_delivery = _validate_delivery(delivery)
    for name in (
        "active_image",
        "active_revision",
        "old_hash_sha256",
        "new_hash_sha256",
    ):
        value = expected.get(name)
        if not isinstance(value, str):
            raise OperatorRotationAuthorityInvalid("forward_authority_invalid")
    if (
        _IMAGE.fullmatch(str(expected["active_image"])) is None
        or _SHA256.fullmatch(str(expected["old_hash_sha256"])) is None
        or _SHA256.fullmatch(str(expected["new_hash_sha256"])) is None
    ):
        raise OperatorRotationAuthorityInvalid("forward_authority_invalid")
    return {
        "rotation_id": rotation_id,
        "target": dict(target),
        "source": dict(source),
        "deployment": {"parameters": _validate_deployment_parameters(parameters)},
        "delivery": validated_delivery,
        "expected": dict(expected),
    }


def validate_inverse_rotation_preflight(
    *,
    authority: Mapping[str, object],
    current: OperatorCredentialPair,
    pending: OperatorCredentialPair,
    app: Mapping[str, object] | None = None,
) -> None:
    """Fail closed unless an inverse binds the local pair and optional app read."""

    payload = dict(authority)
    rotation_id = payload.pop("rotation_id", None)
    inverse_of = authority.get("inverse_of")
    target = authority.get("target")
    source = authority.get("source")
    deployment = authority.get("deployment")
    delivery = authority.get("delivery")
    expected = authority.get("expected")
    if (
        authority.get("schema_version") != _SCHEMA_VERSION
        or authority.get("operation") != "operator-password-inverse"
        or not isinstance(rotation_id, str)
        or _SHA256.fullmatch(rotation_id) is None
        or not isinstance(inverse_of, str)
        or _SHA256.fullmatch(inverse_of) is None
        or not hmac.compare_digest(rotation_id, _canonical_sha256(payload))
        or not isinstance(target, Mapping)
        or not isinstance(source, Mapping)
        or not isinstance(deployment, Mapping)
        or not isinstance(delivery, Mapping)
        or not isinstance(expected, Mapping)
    ):
        raise OperatorRotationAuthorityInvalid("inverse_authority_invalid")
    subscription_id = target.get("subscription_id")
    resource_group = target.get("resource_group")
    app_name = target.get("app")
    fqdn = target.get("fqdn")
    image = source.get("image")
    git_sha = source.get("git_sha")
    parameters = deployment.get("parameters")
    if (
        not isinstance(subscription_id, str)
        or _UUID.fullmatch(subscription_id) is None
        or not isinstance(resource_group, str)
        or _NAME.fullmatch(resource_group) is None
        or not isinstance(app_name, str)
        or _NAME.fullmatch(app_name) is None
        or not isinstance(fqdn, str)
        or not fqdn.endswith(".azurecontainerapps.io")
        or not isinstance(image, str)
        or _IMAGE.fullmatch(image) is None
        or not isinstance(git_sha, str)
        or _SHA1.fullmatch(git_sha) is None
        or not isinstance(parameters, Mapping)
    ):
        raise OperatorRotationAuthorityInvalid("inverse_authority_invalid")
    _validate_deployment_parameters(parameters)
    _validate_delivery(delivery)
    active_revision = expected.get("active_revision")
    old_fingerprint = expected.get("old_hash_sha256")
    new_fingerprint = expected.get("new_hash_sha256")
    if (
        not isinstance(active_revision, str)
        or not isinstance(old_fingerprint, str)
        or _SHA256.fullmatch(old_fingerprint) is None
        or not isinstance(new_fingerprint, str)
        or _SHA256.fullmatch(new_fingerprint) is None
    ):
        raise OperatorRotationAuthorityInvalid("inverse_authority_invalid")
    _validate_pair(current, "current")
    _validate_pair(pending, "pending")
    if (
        not hmac.compare_digest(_fingerprint(current.password_hash), new_fingerprint)
        or not hmac.compare_digest(_fingerprint(pending.password_hash), old_fingerprint)
        or hmac.compare_digest(current.password, pending.password)
    ):
        raise OperatorRotationAuthorityInvalid("inverse_keychain_drift")
    if app is None:
        return
    observed = _validate_inverse_app(
        app,
        app_name=app_name,
        image=image,
        expected_fqdn=fqdn,
    )
    if not hmac.compare_digest(observed["active_revision"], active_revision):
        raise OperatorRotationAuthorityInvalid("inverse_preflight_drift")


def _validate_health(health: Mapping[str, object]) -> None:
    if dict(health) != EXPECTED_READY:
        raise OperatorRotationAuthorityInvalid("hosted_health_not_ready")


def _validate_deployment_parameters(
    parameters: Mapping[str, object],
) -> dict[str, object]:
    """Allow only the public, full topology profile needed for Bicep replay."""

    if (
        not isinstance(parameters, Mapping)
        or set(parameters) != _DEPLOYMENT_PARAMETER_NAMES
    ):
        raise OperatorRotationAuthorityInvalid("deployment_parameters_invalid")
    result = dict(parameters)
    strings = {
        "namePrefix": _NAME_PREFIX,
        "location": re.compile(r"[a-z0-9]{3,32}"),
        "syntheticManifestSha256": _SHA256,
        "syntheticDatasetVersionId": _UUID,
        "registryName": _REGISTRY_NAME,
        "postgresAdministratorLogin": _SIMPLE_IDENTIFIER,
        "postgresServerName": _AZURE_NAME,
        "storageSku": _SKU,
        "storageAccountName": re.compile(r"[a-z0-9]{3,24}"),
        "postgresSkuName": _SKU,
        "postgresTier": _SIMPLE_IDENTIFIER,
    }
    for name, pattern in strings.items():
        value = result[name]
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise OperatorRotationAuthorityInvalid("deployment_parameters_invalid")
    for name in ("vnetAddressPrefix", "appSubnetPrefix", "postgresSubnetPrefix"):
        value = result[name]
        if not isinstance(value, str):
            raise OperatorRotationAuthorityInvalid("deployment_parameters_invalid")
        try:
            network = ipaddress.ip_network(value, strict=True)
        except ValueError as error:
            raise OperatorRotationAuthorityInvalid(
                "deployment_parameters_invalid"
            ) from error
        if network.version != 4:
            raise OperatorRotationAuthorityInvalid("deployment_parameters_invalid")
    if (
        type(result["aiChatEnabled"]) is not bool
        or type(result["aiBudgetFailureRehearsal"]) is not bool
    ):
        raise OperatorRotationAuthorityInvalid("deployment_parameters_invalid")
    key_vault_url = result["openaiKeyVaultUrl"]
    managed_identity_client_id = result["openaiManagedIdentityClientId"]
    managed_identity_resource_id = result["openaiManagedIdentityResourceId"]
    if not all(
        isinstance(value, str)
        for value in (
            key_vault_url,
            managed_identity_client_id,
            managed_identity_resource_id,
        )
    ):
        raise OperatorRotationAuthorityInvalid("deployment_parameters_invalid")
    if result["aiChatEnabled"]:
        parsed = urlsplit(key_vault_url)
        if (
            key_vault_url != f"https://{parsed.hostname}/"
            or parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(".vault.azure.net")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.path != "/"
            or parsed.query
            or parsed.fragment
            or _UUID.fullmatch(managed_identity_client_id) is None
            or _MANAGED_IDENTITY_RESOURCE_ID.fullmatch(managed_identity_resource_id)
            is None
        ):
            raise OperatorRotationAuthorityInvalid("deployment_parameters_invalid")
    elif (
        key_vault_url
        or managed_identity_client_id
        or managed_identity_resource_id
        or result["aiBudgetFailureRehearsal"]
    ):
        raise OperatorRotationAuthorityInvalid("deployment_parameters_invalid")
    fixed_ai_limits = {
        "aiDailyAttemptLimit": 120,
        "aiMonthlyTokenLimit": 150_000,
        "aiMaxConcurrentTurns": 15,
        "aiSessionAttemptLimitPerMinute": 3,
        "aiGlobalAttemptLimitPerMinute": 20,
    }
    for name in (
        "aiDailyAttemptLimit",
        "aiMonthlyTokenLimit",
        "aiMaxConcurrentTurns",
        "aiSessionAttemptLimitPerMinute",
        "aiGlobalAttemptLimitPerMinute",
        "demoSessionRateLimitPerHour",
        "postgresStorageSizeGb",
        "postgresBackupRetentionDays",
        "logRetentionDays",
    ):
        value = result[name]
        if type(value) is not int or not 1 <= value <= 1_000_000:
            raise OperatorRotationAuthorityInvalid("deployment_parameters_invalid")
        if name in fixed_ai_limits and value != fixed_ai_limits[name]:
            raise OperatorRotationAuthorityInvalid("deployment_parameters_invalid")
    tags = result["tags"]
    if not isinstance(tags, Mapping) or not 1 <= len(tags) <= 15:
        raise OperatorRotationAuthorityInvalid("deployment_parameters_invalid")
    normalized_tags: dict[str, str] = {}
    for key, value in tags.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or _TAG_KEY.fullmatch(key) is None
            or _TAG_VALUE.fullmatch(value) is None
        ):
            raise OperatorRotationAuthorityInvalid("deployment_parameters_invalid")
        normalized_tags[key] = value
    result["tags"] = normalized_tags
    return result


def _validate_delivery(value: Mapping[str, object]) -> dict[str, str]:
    if dict(value) != {"contract": _DELIVERY_CONTRACT}:
        raise OperatorRotationAuthorityInvalid("rotation_delivery_invalid")
    return {"contract": _DELIVERY_CONTRACT}


def load_deployment_profile(path: Path) -> dict[str, object]:
    """Read a public profile without ever accepting Bicep secure parameters."""

    try:
        payload = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OperatorRotationAuthorityInvalid(
            "deployment_profile_unreadable"
        ) from error
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != _DEPLOYMENT_PROFILE_SCHEMA_VERSION
        or set(payload) != {"schema_version", "parameters"}
        or not isinstance(payload.get("parameters"), Mapping)
    ):
        raise OperatorRotationAuthorityInvalid("deployment_profile_invalid")
    return _validate_deployment_parameters(payload["parameters"])


def load_forward_rotation_authority(path: Path) -> dict[str, object]:
    """Load only a mode-600, in-project forward package for inverse generation."""

    try:
        source = path.resolve()
        source.relative_to(PROJECT_ROOT.resolve())
        if stat.S_IMODE(source.stat().st_mode) != 0o600:
            raise OperatorRotationAuthorityInvalid(
                "forward_authority_permissions_invalid"
            )
        payload = json.loads(source.read_text())
    except OperatorRotationAuthorityInvalid:
        raise
    except ValueError as error:
        raise OperatorRotationAuthorityInvalid(
            "forward_authority_outside_project"
        ) from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OperatorRotationAuthorityInvalid(
            "forward_authority_unreadable"
        ) from error
    if not isinstance(payload, Mapping):
        raise OperatorRotationAuthorityInvalid("forward_authority_invalid")
    _validate_forward_authority(payload)
    return dict(payload)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_sha256(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _az_reader(arguments: Sequence[str]) -> object:
    try:
        completed = subprocess.run(
            ["az", *arguments, "--only-show-errors", "--output", "json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OperatorRotationAuthorityInvalid("azure_app_read_failed") from error
    if len(completed.stdout) > 1_000_000:
        raise OperatorRotationAuthorityInvalid("azure_app_read_invalid")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise OperatorRotationAuthorityInvalid("azure_app_read_invalid") from error


def _health_reader(url: str) -> Mapping[str, object]:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path != "/health/ready"
        or parsed.query
        or parsed.fragment
    ):
        raise OperatorRotationAuthorityInvalid("hosted_health_read_failed")
    try:
        verify_hosted_health(f"https://{parsed.hostname}")
    except HostedHealthInvalid as error:
        raise OperatorRotationAuthorityInvalid("hosted_health_read_failed") from error
    return dict(EXPECTED_READY)


def _git_head() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OperatorRotationAuthorityInvalid("git_head_read_failed") from error
    candidate = completed.stdout.strip()
    if _SHA1.fullmatch(candidate) is None:
        raise OperatorRotationAuthorityInvalid("git_head_invalid")
    return candidate


def _parse_args(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription")
    parser.add_argument("--resource-group")
    parser.add_argument("--app")
    parser.add_argument("--image")
    parser.add_argument("--deployment-profile")
    parser.add_argument("--inverse-from")
    parser.add_argument("--git-sha")
    parser.add_argument("--output")
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    options = _parse_args(arguments)
    try:
        keychain = OperatorRotationKeychain(backend=MacOSKeychainBackend())
        if options.inverse_from:
            if any(
                value is not None
                for value in (
                    options.subscription,
                    options.resource_group,
                    options.app,
                    options.image,
                    options.deployment_profile,
                    options.git_sha,
                )
            ):
                raise OperatorRotationAuthorityInvalid("inverse_arguments_invalid")
            authority = generate_inverse_rotation_authority(
                forward_authority=load_forward_rotation_authority(
                    Path(options.inverse_from)
                ),
                keychain=keychain,
                az_reader=_az_reader,
            )
        else:
            if not all(
                (
                    options.subscription,
                    options.resource_group,
                    options.app,
                    options.image,
                    options.deployment_profile,
                )
            ):
                raise OperatorRotationAuthorityInvalid(
                    "rotation_authority_input_missing"
                )
            authority = generate_rotation_authority(
                subscription_id=options.subscription,
                resource_group=options.resource_group,
                app_name=options.app,
                image=options.image,
                git_sha=options.git_sha or _git_head(),
                deployment_parameters=load_deployment_profile(
                    Path(options.deployment_profile)
                ),
                keychain=keychain,
                az_reader=_az_reader,
                health_reader=_health_reader,
            )
        output = (
            Path(options.output)
            if options.output
            else PROJECT_ROOT
            / "deliverables/operator-password-rotation"
            / f"{authority['rotation_id']}.json"
        )
        write_rotation_authority(output, authority)
        print(
            json.dumps(
                {
                    "app": authority["target"]["app"],
                    "fqdn": authority["target"]["fqdn"],
                    "image": authority["source"]["image"],
                    "operation": authority["operation"],
                    "output": str(output),
                    "rotation_id": authority["rotation_id"],
                },
                sort_keys=True,
            )
        )
        return 0
    except OperatorRotationAuthorityInvalid as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
