#!/usr/bin/env python3
"""Execute one exact-hash, no-Key AI-disabled recovery package."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

_LOCAL_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_LOCAL_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_LOCAL_PROJECT_ROOT))

from scripts.ai_enablement_contract import validate_reconciliation_evidence  # noqa: E402
from scripts.azure_ai_enablement_actions import (  # noqa: E402
    AzureAIEnablementActionInvalid,
    AzureAIEnablementActions,
)
from scripts.azure_ai_revision import (  # noqa: E402
    AzureAIRevisionInvalid,
    canonicalize_azure_template_readback,
)
from scripts.create_ai_disabled_recovery_package import (  # noqa: E402
    AIDisabledRecoveryPackageInvalid,
    ARTIFACTS,
    PROJECT_ROOT,
    _capture_ai_disabled_recovery_authority_state,
    _collect_recovery_control_sha256,
    _validate_authority,
    validate_ai_disabled_recovery_package,
)


_SHA256 = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"[a-z][a-z0-9-]{2,126}")


class AIDisabledRecoveryRunInvalid(RuntimeError):
    """The exact recovery authorization or its safe execution failed."""


def _invalid(code: str = "ai_disabled_recovery_execution_invalid") -> AIDisabledRecoveryRunInvalid:
    return AIDisabledRecoveryRunInvalid(code)


def _read_package(path: Path, approved_sha256: str) -> tuple[dict[str, object], str]:
    if _SHA256.fullmatch(approved_sha256) is None:
        raise _invalid("ai_disabled_recovery_package_hash_mismatch")
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or not 0 < metadata.st_size <= 1_000_000
        ):
            raise _invalid("ai_disabled_recovery_package_invalid")
        encoded = path.read_bytes()
        actual = hashlib.sha256(encoded).hexdigest()
        package = json.loads(encoded)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise _invalid("ai_disabled_recovery_package_invalid") from None
    if not hmac.compare_digest(actual, approved_sha256):
        raise _invalid("ai_disabled_recovery_package_hash_mismatch")
    try:
        return validate_ai_disabled_recovery_package(package), actual
    except AIDisabledRecoveryPackageInvalid:
        raise _invalid("ai_disabled_recovery_package_invalid") from None


def _write_exclusive_json(path: Path, payload: Mapping[str, object]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise _invalid("ai_disabled_recovery_receipt_write_failed") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _replace_json(path: Path, payload: Mapping[str, object]) -> None:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise _invalid("ai_disabled_recovery_receipt_write_failed")
        flags = os.O_WRONLY | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                descriptor = -1
                json.dump(
                    payload,
                    stream,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except OSError:
        raise _invalid("ai_disabled_recovery_receipt_write_failed") from None


def _source_matches_authority(
    package: Mapping[str, object], authority: Mapping[str, object]
) -> bool:
    source = package["source"]
    target = package["azure_target"]
    return source == {
        "revision": authority["latest_revision"],
        "image": authority["image"],
        "active_revisions_mode": authority["active_revisions_mode"],
        "traffic": authority["traffic"],
        "ai_chat_enabled": authority["ai_chat_enabled"],
        "budget_failure_rehearsal": authority["budget_failure_rehearsal"],
        "identity_ids": authority["identity_ids"],
        "revision_active": authority["revision_active"],
        "revision_health": authority["revision_health"],
        "revision_provisioning": authority["revision_provisioning"],
    } and all(authority[name] == target[name] for name in target)


def _validate_execution_result(
    package: Mapping[str, object], result: object
) -> dict[str, object]:
    if not isinstance(result, Mapping) or set(result) != {
        "target_revision",
        "target_image",
        "ai_chat_enabled",
        "budget_failure_rehearsal",
        "identity_ids",
        "reconciliation",
        "browser",
    }:
        raise _invalid("ai_disabled_recovery_result_invalid")
    target = package["target"]
    revision = result["target_revision"]
    if (
        not isinstance(revision, str)
        or _REVISION.fullmatch(revision) is None
        or result["target_image"] != target["candidate_image"]
        or result["ai_chat_enabled"] is not False
        or result["budget_failure_rehearsal"] is not False
        or result["identity_ids"] != target["identity_ids"]
        or not isinstance(result["browser"], Mapping)
        or dict(result["browser"])
        != {"externalRequests": 0, "providerTurns": 0}
    ):
        raise _invalid("ai_disabled_recovery_result_invalid")
    try:
        reconciliation = validate_reconciliation_evidence(result["reconciliation"])
    except Exception:
        raise _invalid("ai_disabled_recovery_result_invalid") from None
    if (
        reconciliation["role"] != "emergency_disabled"
        or reconciliation["target_revision"] != revision
        or reconciliation["target_image_digest"]
        != str(target["candidate_image"]).rsplit("@", 1)[-1]
        or reconciliation["final_state"] != "healthy_target"
    ):
        raise _invalid("ai_disabled_recovery_result_invalid")
    return {
        "target_revision": revision,
        "target_image": target["candidate_image"],
        "ai_chat_enabled": False,
        "budget_failure_rehearsal": False,
        "identity_ids": list(target["identity_ids"]),
        "reconciliation": reconciliation,
        "browser": {"externalRequests": 0, "providerTurns": 0},
    }


def _failure_code(error: BaseException) -> str:
    code = str(error)
    if re.fullmatch(r"ai_disabled_recovery_[a-z0-9_]{3,96}", code):
        return code
    return "ai_disabled_recovery_execution_invalid"


def execute_azure_ai_disabled_recovery(
    package: Mapping[str, object],
    package_sha256: str,
    *,
    authority: Mapping[str, object],
    app: Mapping[str, object],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    environment: Mapping[str, str] = os.environ,
    browser_credential_provider: Callable[[], object] | None = None,
) -> dict[str, object]:
    """Apply and verify the one package-bound disabled recovery transition."""

    target = package["azure_target"]
    source = package["source"]
    if not isinstance(target, Mapping) or not isinstance(source, Mapping):
        raise _invalid("ai_disabled_recovery_authority_drift")
    try:
        fresh_authority = _validate_authority(authority)
    except Exception:
        raise _invalid("ai_disabled_recovery_authority_drift") from None
    if not _source_matches_authority(package, fresh_authority):
        raise _invalid("ai_disabled_recovery_authority_drift")
    try:
        identity = app["identity"]
        assigned = identity["userAssignedIdentities"]
        properties = app["properties"]
        configuration = properties["configuration"]
        ingress = configuration["ingress"]
        template = canonicalize_azure_template_readback(properties["template"])
    except (KeyError, TypeError, AzureAIRevisionInvalid):
        raise _invalid("ai_disabled_recovery_authority_drift") from None
    if (
        not isinstance(identity, Mapping)
        or identity.get("type") != "UserAssigned"
        or not isinstance(assigned, Mapping)
        or not isinstance(configuration, Mapping)
        or not isinstance(ingress, Mapping)
        or configuration.get("activeRevisionsMode") != "Single"
        or ingress.get("traffic") != [{"latestRevision": True, "weight": 100}]
        or not isinstance(ingress.get("external"), bool)
        or ingress.get("external") is not True
        or not isinstance(ingress.get("fqdn"), str)
        or {str(item).casefold() for item in assigned}
        != {str(item).casefold() for item in source["identity_ids"]}
    ):
        raise _invalid("ai_disabled_recovery_authority_drift")
    registries = configuration.get("registries")
    if not isinstance(registries, list):
        raise _invalid("ai_disabled_recovery_authority_drift")
    canonical_registries: list[dict[str, str]] = []
    try:
        for registry in registries:
            if not isinstance(registry, Mapping):
                raise TypeError
            server = registry["server"]
            registry_identity = registry["identity"]
            if not isinstance(server, str) or not isinstance(registry_identity, str):
                raise TypeError
            canonical_registries.append(
                {"server": server, "identity": registry_identity}
            )
    except (KeyError, TypeError):
        raise _invalid("ai_disabled_recovery_authority_drift") from None
    immutable_configuration = {
        "activeRevisionsMode": "Single",
        "ingress": {
            "external": True,
            "fqdn": ingress["fqdn"],
            "traffic": ingress["traffic"],
        },
        "registries": canonical_registries,
    }
    adapter_package = {
        "azure_target": {
            **dict(target),
            "rollback_revision": source["revision"],
        },
        "candidate": {"image_repository": "bizpulse"},
    }
    if browser_credential_provider is None:
        from scripts.run_ai_enablement import read_browser_operator_password

        browser_credential_provider = read_browser_operator_password
    adapter = AzureAIEnablementActions(
        package=adapter_package,
        package_sha256=package_sha256,
        runner=runner,
        environment=environment,
        browser_credential_provider=browser_credential_provider,
    )
    adapter.current_projection = {
        "location": app.get("location"),
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {str(identity_id): {} for identity_id in assigned},
        },
        "properties": {"template": template},
    }
    adapter._immutable_configuration = immutable_configuration
    adapter._current_revision = str(source["revision"])
    adapter._hosted_url = f"https://{ingress['fqdn']}"
    context = {
        "candidate_image_digest": str(source["image"]).rsplit("@", 1)[-1]
    }
    try:
        revision = adapter._apply_revision(
            enabled=False,
            label="r9-disable",
            role="emergency_disabled",
            context=context,
        )
        reconciliation = adapter._reconcile_revision(
            enabled=False,
            image=str(source["image"]),
            revision=revision,
            context=context,
            role="emergency_disabled",
        )
        adapter._prepare_browser_credential()
        adapter._run_browser_gate("ai-disabled")
        return {
            "target_revision": revision,
            "target_image": source["image"],
            "ai_chat_enabled": False,
            "budget_failure_rehearsal": False,
            "identity_ids": package["target"]["identity_ids"],
            "reconciliation": reconciliation,
            "browser": {"externalRequests": 0, "providerTurns": 0},
        }
    finally:
        adapter.clear_browser_credential()


def run_ai_disabled_recovery(
    *,
    package_path: Path,
    approved_sha256: str,
    receipt_path: Path,
    observation_path: Path,
    authority_reader: Callable[[Mapping[str, object]], object],
    recovery_executor: Callable[[Mapping[str, object], str, Mapping[str, object]], object],
    control_reader: Callable[[], object] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    """Run the one allowed no-Key patch after fresh authority confirmation."""

    package, package_sha256 = _read_package(package_path, approved_sha256)
    current = now()
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise _invalid()
    expires_at = datetime.fromisoformat(
        str(package["expires_at"]).removesuffix("Z") + "+00:00"
    )
    if current.astimezone(UTC) >= expires_at:
        raise _invalid("ai_disabled_recovery_package_expired")
    if control_reader is not None and control_reader() != package["control_sha256"]:
        raise _invalid("ai_disabled_recovery_control_drift")
    try:
        authority = _validate_authority(authority_reader(package))
    except Exception:
        raise _invalid("ai_disabled_recovery_authority_drift") from None
    if not _source_matches_authority(package, authority):
        raise _invalid("ai_disabled_recovery_authority_drift")
    if receipt_path.exists() or observation_path.exists():
        raise _invalid("ai_disabled_recovery_artifact_conflict")
    _write_exclusive_json(
        receipt_path,
        {
            "schema_version": "newcaostone.ai-disabled-recovery-attempt.v1",
            "package_sha256": package_sha256,
            "state": "started",
        },
    )
    try:
        result = _validate_execution_result(
            package,
            recovery_executor(package, package_sha256, authority),
        )
        observation = {
            "schema_version": "newcaostone.ai-disabled-recovery-observation.v1",
            "package_sha256": package_sha256,
            **result,
        }
        _write_exclusive_json(observation_path, observation)
        observation_sha256 = hashlib.sha256(observation_path.read_bytes()).hexdigest()
        _replace_json(
            receipt_path,
            {
                "schema_version": "newcaostone.ai-disabled-recovery-receipt.v1",
                "package_sha256": package_sha256,
                "state": "completed",
                "observation_sha256": observation_sha256,
            },
        )
        return result
    except Exception as error:
        _replace_json(
            receipt_path,
            {
                "schema_version": "newcaostone.ai-disabled-recovery-attempt.v1",
                "package_sha256": package_sha256,
                "state": "failed",
                "failure_code": _failure_code(error),
            },
        )
        raise


def main(arguments: list[str] | None = None) -> int:
    """Execute only the user-approved R10 disabled recovery package."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--approved-sha256", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--observation", type=Path, required=True)
    options = parser.parse_args(arguments)
    expected = {name: (PROJECT_ROOT / path).resolve() for name, path in ARTIFACTS.items()}
    if (
        options.package.resolve() != expected["package"]
        or options.receipt.resolve() != expected["receipt"]
        or options.observation.resolve() != expected["observation"]
    ):
        print("ai_disabled_recovery=failed")
        return 1
    snapshot: dict[str, Mapping[str, object]] = {}

    def authority_reader(package: Mapping[str, object]) -> object:
        target = package.get("azure_target")
        if not isinstance(target, Mapping):
            raise _invalid("ai_disabled_recovery_authority_drift")
        authority, app = _capture_ai_disabled_recovery_authority_state(target)
        snapshot["app"] = app
        return authority

    def recovery_executor(
        package: Mapping[str, object],
        package_sha256: str,
        authority: Mapping[str, object],
    ) -> object:
        app = snapshot.pop("app", None)
        if not isinstance(app, Mapping):
            raise _invalid("ai_disabled_recovery_authority_drift")
        return execute_azure_ai_disabled_recovery(
            package,
            package_sha256,
            authority=authority,
            app=app,
        )

    try:
        run_ai_disabled_recovery(
            package_path=options.package,
            approved_sha256=options.approved_sha256,
            receipt_path=options.receipt,
            observation_path=options.observation,
            authority_reader=authority_reader,
            recovery_executor=recovery_executor,
            control_reader=_collect_recovery_control_sha256,
        )
    except (
        AIDisabledRecoveryRunInvalid,
        AzureAIEnablementActionInvalid,
        KeyboardInterrupt,
    ):
        print("ai_disabled_recovery=failed")
        return 1
    print("ai_disabled_recovery=completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
