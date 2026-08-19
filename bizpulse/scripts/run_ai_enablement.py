#!/usr/bin/env python3
"""Execute an exact-hash AI package through injected, allowlisted actions."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime
import errno
import hashlib
import hmac
from io import BufferedRandom
import json
import os
from pathlib import Path
import re
import stat
import sys
from uuid import UUID


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ai_enablement_contract import (  # noqa: E402
    STATE_ORDER,
    sanitize_ai_enablement_observation,
    sanitize_failed_receipt,
    sanitize_terminal_receipt,
    validate_reconciliation_evidence,
)
from scripts.create_ai_enablement_package import (  # noqa: E402
    ARTIFACTS,
    D3_BRANCH,
    D3_PACKAGE_SHA256,
    D3_SELECTED_BASE_SHA,
    capture_repository_state,
    capture_prior_ai_attempts,
    collect_control_sha256,
    load_ai_enablement_package,
)
from scripts.azure_ai_enablement_actions import (  # noqa: E402
    AzureAIEnablementActions,
    AzureAIEnablementActionInvalid,
    provider_price_preflight,
)
from scripts.operator_rotation_keychain import (  # noqa: E402
    MacOSKeychainBackend,
    OperatorRotationKeychain,
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_REVISION_PATTERN = re.compile(r"[a-z][a-z0-9-]{2,126}")


class AIEnablementRunInvalid(RuntimeError):
    """An approval, authority, operation, evidence, or secret boundary failed."""


def _invalid(code: str = "ai_enablement_execution_invalid") -> AIEnablementRunInvalid:
    return AIEnablementRunInvalid(code)


def _operator_keychain_controller() -> OperatorRotationKeychain:
    return OperatorRotationKeychain(backend=MacOSKeychainBackend())


def read_browser_operator_password() -> str:
    """Read only the exact browser-gate credential without printing it."""

    try:
        value = _operator_keychain_controller().current_pair().password
    except Exception as error:
        raise _invalid("ai_enablement_browser_credential_unavailable") from error
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4_096
        or any(character in value for character in ("\0", "\r", "\n"))
    ):
        raise _invalid("ai_enablement_browser_credential_unavailable")
    return value


def read_openai_api_key(
    *,
    root_factory: Callable[[], object] | None = None,
    dialog_reader: Callable[..., object] | None = None,
) -> str:
    """Collect the provider key in a local hidden dialog without logging it."""

    root: object | None = None
    try:
        if root_factory is None or dialog_reader is None:
            import tkinter as tk
            from tkinter import simpledialog

            if root_factory is None:
                root_factory = tk.Tk
            if dialog_reader is None:
                dialog_reader = simpledialog.askstring
        root = root_factory()
        root.withdraw()  # type: ignore[attr-defined]
        root.attributes("-topmost", True)  # type: ignore[attr-defined]
        value = dialog_reader(
            "BizPulse AI Enablement",
            (
                "Enter the OpenAI Platform API key for one-time qualification "
                "and the approved Azure Key Vault write.\n\n"
                "The value is hidden and will not be logged."
            ),
            show="*",
            parent=root,
        )
    except Exception as error:
        raise _invalid("ai_enablement_secure_input_unavailable") from error
    finally:
        if root is not None:
            try:
                root.destroy()  # type: ignore[attr-defined]
            except Exception:
                pass
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _invalid("ai_enablement_secure_input_unavailable")
    return value


def _package_digest(path: Path, approved_sha256: str) -> str:
    if _SHA256_PATTERN.fullmatch(approved_sha256) is None:
        raise _invalid("ai_enablement_package_hash_mismatch")
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or not 0 < metadata.st_size <= 2_000_000
        ):
            raise _invalid("ai_enablement_package_invalid")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise _invalid("ai_enablement_package_invalid") from error
    if not hmac.compare_digest(actual, approved_sha256):
        raise _invalid("ai_enablement_package_hash_mismatch")
    return actual


def d3_state_from_paths(
    *,
    expected: Mapping[str, object],
    package_path: Path,
    receipt_path: Path,
    observation_path: Path,
) -> dict[str, object]:
    """Verify the preserved D3 package without reading or replaying its body."""

    required = {
        "branch": D3_BRANCH,
        "selected_base_sha": D3_SELECTED_BASE_SHA,
        "package_sha256": expected.get("package_sha256"),
        "package_mode": "0600",
        "receipt_present": False,
        "observation_present": False,
    }
    if dict(expected) != required:
        raise _invalid("ai_enablement_d3_drift")
    try:
        metadata = package_path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size <= 0
            or metadata.st_size > 2_000_000
            or receipt_path.exists()
            or observation_path.exists()
        ):
            raise _invalid("ai_enablement_d3_drift")
        actual = hashlib.sha256(package_path.read_bytes()).hexdigest()
    except OSError as error:
        raise _invalid("ai_enablement_d3_drift") from error
    if not hmac.compare_digest(actual, str(expected["package_sha256"])):
        raise _invalid("ai_enablement_d3_drift")
    return dict(expected)


def _exact_result(
    package: Mapping[str, object],
    state: str,
    result: object,
    *,
    context: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(result, Mapping) or set(result) != {
        "operations",
        "evidence",
        "outputs",
    }:
        raise _invalid("ai_enablement_state_mismatch")
    try:
        specification = package["execution_contract"]["states"][state]
    except (KeyError, TypeError) as error:
        raise _invalid("ai_enablement_package_invalid") from error
    if (
        not isinstance(specification, Mapping)
        or result["operations"] != specification["operations"]
        or result["evidence"] != specification["expected_evidence"]
        or not isinstance(result["outputs"], Mapping)
    ):
        raise _invalid("ai_enablement_state_mismatch")
    outputs = dict(result["outputs"])
    target = package["azure_target"]
    expected_empty = {
        "provider_failure_placeholder_write",
        "real_secret_write",
        "sanitize_receipt",
    }
    if state == "readonly_revalidation":
        expected = {
            "rollback_revision": target["rollback_revision"],
            "ai_enabled": False,
            "vault_state": "existing_exact",
            "identity_state": "existing_exact",
            "role_assignment_state": package["prepackage_gate"][
                "role_assignment_state"
            ],
            "diagnostic_setting_state": "existing_exact",
            "secret_values_read": 0,
        }
        if outputs != expected:
            raise _invalid("ai_enablement_azure_authority_drift")
    elif state == "publish_candidate_image":
        if (
            set(outputs) != {"candidate_image_digest"}
            or not isinstance(outputs["candidate_image_digest"], str)
            or _DIGEST_PATTERN.fullmatch(outputs["candidate_image_digest"]) is None
        ):
            raise _invalid("ai_enablement_image_digest_invalid")
    elif state == "activate_ai_disabled_candidate":
        if (
            set(outputs) != {"candidate_image_digest", "revision"}
            or outputs["candidate_image_digest"] != context.get("candidate_image_digest")
            or not isinstance(outputs["revision"], str)
            or _REVISION_PATTERN.fullmatch(outputs["revision"]) is None
        ):
            raise _invalid("ai_enablement_image_digest_drift")
    elif state == "verify_ai_disabled_candidate":
        if (
            set(outputs)
            != {"candidate_image_digest", "ai_enabled", "reconciliation"}
            or outputs["candidate_image_digest"]
            != context.get("candidate_image_digest")
            or outputs["ai_enabled"] is not False
        ):
            raise _invalid("ai_enablement_image_digest_drift")
        outputs["reconciliation"] = validate_reconciliation_evidence(
            outputs["reconciliation"]
        )
        if outputs["reconciliation"]["role"] != "ai_disabled_candidate":
            raise _invalid("ai_enablement_reconciliation_invalid")
    elif state == "reconcile_ai_vault_identity_role_diagnostics":
        expected_vault_url = f"https://{target['vault_name']}.vault.azure.net"
        expected_identity_id = (
            f"/subscriptions/{target['subscription_id']}/resourceGroups/"
            f"{target['resource_group']}/providers/Microsoft.ManagedIdentity/"
            f"userAssignedIdentities/{target['identity_name']}"
        )
        if (
            set(outputs)
            != {
                "vault_url",
                "identity_resource_id",
                "managed_identity_client_id",
            }
            or outputs["vault_url"] != expected_vault_url
            or outputs["identity_resource_id"] != expected_identity_id
            or not _canonical_uuid4(outputs["managed_identity_client_id"])
        ):
            raise _invalid("ai_enablement_resource_output_drift")
    elif state == "paid_model_qualification":
        if outputs != {"paid_call_count": 12}:
            raise _invalid("ai_enablement_paid_call_drift")
    elif state in {"budget_failure_rehearsal", "provider_failure_rehearsal"}:
        expected_roles = (
            ["budget_enabled", "budget_recovery"]
            if state == "budget_failure_rehearsal"
            else ["provider_enabled", "provider_recovery"]
        )
        reconciliations = outputs.get("reconciliations")
        if set(outputs) != {"reconciliations"} or not isinstance(
            reconciliations,
            list,
        ):
            raise _invalid("ai_enablement_reconciliation_invalid")
        validated_reconciliations = [
            validate_reconciliation_evidence(item)
            for item in reconciliations
        ]
        if [item["role"] for item in validated_reconciliations] != expected_roles:
            raise _invalid("ai_enablement_reconciliation_invalid")
        outputs["reconciliations"] = validated_reconciliations
    elif state == "activate_ai_enabled_revision":
        if (
            set(outputs) != {"candidate_image_digest", "final_revision"}
            or outputs["candidate_image_digest"] != context.get("candidate_image_digest")
            or not isinstance(outputs["final_revision"], str)
            or _REVISION_PATTERN.fullmatch(outputs["final_revision"]) is None
        ):
            raise _invalid("ai_enablement_image_digest_drift")
    elif state == "verify_ai_enabled_revision":
        if (
            set(outputs)
            != {"candidate_image_digest", "ai_enabled", "reconciliation"}
            or outputs["candidate_image_digest"]
            != context.get("candidate_image_digest")
            or outputs["ai_enabled"] is not True
        ):
            raise _invalid("ai_enablement_image_digest_drift")
        outputs["reconciliation"] = validate_reconciliation_evidence(
            outputs["reconciliation"]
        )
        if outputs["reconciliation"]["role"] != "ai_enabled":
            raise _invalid("ai_enablement_reconciliation_invalid")
    elif state == "paid_hosted_manual_send_smoke":
        if outputs != {"paid_call_count": 1}:
            raise _invalid("ai_enablement_paid_call_drift")
    elif state in expected_empty:
        if outputs:
            raise _invalid("ai_enablement_state_mismatch")
    else:
        raise _invalid("ai_enablement_state_mismatch")
    return {
        "operations": deepcopy(result["operations"]),
        "evidence": deepcopy(result["evidence"]),
        "outputs": outputs,
    }


def _canonical_uuid4(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
    except ValueError:
        return False
    return str(parsed) == value and parsed.version == 4


def _wipe(buffer: bytearray | None) -> None:
    if buffer is not None:
        for index in range(len(buffer)):
            buffer[index] = 0
        buffer.clear()


def _reserve_attempt_receipt(
    path: Path,
    *,
    package_sha256: str,
) -> BufferedRandom:
    payload = {
        "schema_version": "newcaostone.ai-enablement-attempt.v2",
        "package_sha256": package_sha256,
        "state": "started",
    }
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    stream: BufferedRandom | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        stream = os.fdopen(descriptor, "w+b")
        stream.write(
            (
                json.dumps(payload, sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode()
        )
        stream.flush()
        os.fsync(stream.fileno())
        return stream
    except OSError as error:
        if stream is not None:
            stream.close()
        elif descriptor is not None:
            os.close(descriptor)
        if error.errno == errno.EEXIST:
            raise _invalid("ai_enablement_receipt_exists") from error
        raise _invalid("ai_enablement_receipt_write_failed") from error


def _finalize_reserved_receipt(
    stream: BufferedRandom,
    receipt: Mapping[str, object],
) -> None:
    encoded = (
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    stream.seek(0)
    stream.truncate(0)
    stream.write(encoded)
    stream.flush()
    os.fsync(stream.fileno())


def _write_owner_only_observation(
    path: Path,
    observation: Mapping[str, object],
) -> str:
    encoded = (
        json.dumps(observation, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(path, flags, 0o600)
        created = True
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        if error.errno == errno.EEXIST:
            raise _invalid("ai_enablement_observation_exists") from error
        raise _invalid("ai_enablement_observation_write_failed") from error
    return hashlib.sha256(encoded).hexdigest()


def _closed_failure_code(error: BaseException) -> str:
    if isinstance(error, (AIEnablementRunInvalid, AzureAIEnablementActionInvalid)):
        code = str(error)
        if re.fullmatch(r"ai_enablement_[a-z0-9_]{3,96}", code):
            return code
    return "ai_enablement_operation_failed"


def execute_ai_enablement(
    *,
    package_path: Path,
    approved_sha256: str,
    receipt_path: Path,
    observation_path: Path,
    now: datetime,
    repository_reader: Callable[[], object],
    control_reader: Callable[[], object],
    prior_attempts_reader: Callable[[], object],
    d3_reader: Callable[[], object],
    azure_revalidator: Callable[[Mapping[str, object]], object],
    paid_preflight: Callable[[Mapping[str, object]], object],
    operation_executor: Callable[..., object],
    emergency_recovery: Callable[..., object],
    key_provider: Callable[[], object],
    stdin_is_tty: Callable[[], bool],
) -> dict[str, object]:
    """Execute a fully injected operation chain after every local/read-only gate."""

    package_sha256 = _package_digest(package_path, approved_sha256)
    try:
        package = load_ai_enablement_package(package_path, now=now)
    except Exception as error:
        raise _invalid("ai_enablement_package_invalid") from error
    artifact_root = package_path.parent.parent
    expected_paths = {
        key: (artifact_root / relative).resolve()
        for key, relative in ARTIFACTS.items()
    }
    if (
        package.get("artifacts") != ARTIFACTS
        or package_path.resolve() != expected_paths["package_path"]
        or receipt_path.resolve() != expected_paths["receipt_path"]
        or observation_path.resolve() != expected_paths["observation_path"]
    ):
        raise _invalid("ai_enablement_artifact_path_drift")
    if receipt_path.exists():
        raise _invalid("ai_enablement_receipt_exists")
    if observation_path.exists():
        raise _invalid("ai_enablement_observation_exists")
    if stdin_is_tty() is not True:
        raise _invalid("ai_enablement_tty_required")
    try:
        if repository_reader() != package["repository"]:
            raise _invalid("ai_enablement_repository_drift")
        if control_reader() != package["control_sha256"]:
            raise _invalid("ai_enablement_control_drift")
        if prior_attempts_reader() != package["prior_attempts"]:
            raise _invalid("ai_enablement_prior_attempt_drift")
        if d3_reader() != package["d3"]:
            raise _invalid("ai_enablement_d3_drift")
        readonly = azure_revalidator(package)
        price_evidence = paid_preflight(package)
    except AIEnablementRunInvalid:
        raise
    except AzureAIEnablementActionInvalid as error:
        raise _invalid(_closed_failure_code(error)) from error
    except Exception as error:
        raise _invalid("ai_enablement_preflight_failed") from error
    _exact_result(
        package,
        "readonly_revalidation",
        readonly,
        context={},
    )
    if price_evidence != {
        "price_evidence_present": True,
        "maximum_estimated_cost": "0.19",
    }:
        raise _invalid("ai_enablement_paid_preflight_failed")

    context: dict[str, object] = {
        "package_sha256": package_sha256,
        "source_git_sha": package["repository"]["head_sha"],
        "completed_states": ["readonly_revalidation"],
        "reconciliations": [],
    }
    key_buffer: bytearray | None = None
    paid_call_count = 0
    final_revision: str | None = None
    real_secret_write_attempted = False
    receipt_stream = _reserve_attempt_receipt(
        receipt_path,
        package_sha256=package_sha256,
    )
    receipt_finalization_attempted = False
    try:
        for state in STATE_ORDER[1:]:
            if state == "paid_model_qualification":
                try:
                    provided = key_provider()
                except Exception as error:
                    raise _invalid("ai_enablement_key_input_failed") from error
                if not isinstance(provided, str) or not provided:
                    raise _invalid("ai_enablement_key_input_missing")
                key_buffer = bytearray(provided.encode())
                provided = None

            environment: dict[str, str] = {}
            secret_value: str | None = None
            if state == "paid_model_qualification":
                assert key_buffer is not None
                environment["BIZPULSE_DEPLOY_OPENAI_API_KEY"] = key_buffer.decode()
            elif state == "real_secret_write":
                assert key_buffer is not None
                secret_value = key_buffer.decode()
                real_secret_write_attempted = True
            try:
                result = operation_executor(
                    state,
                    environment=environment,
                    secret_value=secret_value,
                    context=deepcopy(context),
                )
            except (Exception, KeyboardInterrupt) as error:
                raise _invalid(_closed_failure_code(error)) from error
            finally:
                environment.clear()
                secret_value = None
            validated = _exact_result(
                package,
                state,
                result,
                context=context,
            )
            outputs = validated["outputs"]
            reconciliations = context["reconciliations"]
            assert isinstance(reconciliations, list)
            if "reconciliation" in outputs:
                reconciliations.append(deepcopy(outputs["reconciliation"]))
            if "reconciliations" in outputs:
                state_reconciliations = outputs["reconciliations"]
                assert isinstance(state_reconciliations, list)
                reconciliations.extend(deepcopy(state_reconciliations))
            if state == "publish_candidate_image":
                context["candidate_image_digest"] = outputs[
                    "candidate_image_digest"
                ]
            elif state == "activate_ai_disabled_candidate":
                context["ai_disabled_revision"] = outputs["revision"]
            elif state == "reconcile_ai_vault_identity_role_diagnostics":
                context.update(outputs)
            elif state == "paid_model_qualification":
                paid_call_count += int(outputs["paid_call_count"])
            elif state == "real_secret_write":
                _wipe(key_buffer)
                key_buffer = None
            elif state == "activate_ai_enabled_revision":
                final_revision = str(outputs["final_revision"])
                context["final_revision"] = final_revision
            elif state == "paid_hosted_manual_send_smoke":
                paid_call_count += int(outputs["paid_call_count"])
            completed_states = context["completed_states"]
            assert isinstance(completed_states, list)
            completed_states.append(state)
        if (
            context.get("completed_states") != list(STATE_ORDER)
            or paid_call_count != 13
            or final_revision is None
            or not isinstance(context.get("candidate_image_digest"), str)
            or context.get("reconciliations") is None
        ):
            raise _invalid("ai_enablement_terminal_state_invalid")
        observation = sanitize_ai_enablement_observation(
            {
                "package_sha256": package_sha256,
                "candidate_image_digest": context["candidate_image_digest"],
                "final_revision": final_revision,
                "ai_enabled": True,
                "paid_call_count": paid_call_count,
                "reconciliations": context["reconciliations"],
                "acceptance_requires_completed_receipt": True,
            }
        )
        observation_sha256 = _write_owner_only_observation(
            observation_path,
            observation,
        )
        receipt = sanitize_terminal_receipt(
            {
                "package_sha256": package_sha256,
                "completed_states": list(STATE_ORDER),
                "candidate_image_digest": context["candidate_image_digest"],
                "final_revision": final_revision,
                "vault_name": package["azure_target"]["vault_name"],
                "identity_name": package["azure_target"]["identity_name"],
                "paid_call_count": paid_call_count,
                "result": "completed",
                "reconciliations": context["reconciliations"],
                "observation_sha256": observation_sha256,
            }
        )
        try:
            receipt_finalization_attempted = True
            _finalize_reserved_receipt(receipt_stream, receipt)
        except OSError as error:
            raise _invalid("ai_enablement_receipt_write_failed") from error
    except (Exception, KeyboardInterrupt) as error:
        recovery: object = None
        failure_code = _closed_failure_code(error)
        if real_secret_write_attempted:
            try:
                recovery = emergency_recovery(
                    context=deepcopy(context),
                    real_secret_write_attempted=True,
                )
            except (Exception, KeyboardInterrupt):
                recovery = None
                failure_code = "ai_enablement_emergency_disable_failed"
        if not receipt_finalization_attempted:
            try:
                failed_receipt = sanitize_failed_receipt(
                    {
                        "package_sha256": package_sha256,
                        "state": "failed",
                        "failure_code": failure_code,
                        "completed_states": context["completed_states"],
                        "reconciliations": context["reconciliations"],
                        "recovery": recovery,
                    }
                )
                receipt_finalization_attempted = True
                _finalize_reserved_receipt(receipt_stream, failed_receipt)
            except Exception:
                if failure_code != "ai_enablement_emergency_disable_failed":
                    raise _invalid("ai_enablement_receipt_write_failed") from None
        if failure_code == "ai_enablement_emergency_disable_failed":
            raise _invalid(failure_code) from None
        if isinstance(error, AIEnablementRunInvalid):
            raise
        raise _invalid(failure_code) from error
    finally:
        _wipe(key_buffer)
        receipt_stream.close()
    return {
        "state": "completed",
        "candidate_image_digest": context["candidate_image_digest"],
        "final_revision": final_revision,
        "paid_call_count": paid_call_count,
    }


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--approved-sha256", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--d3-package", type=Path, required=True)
    parser.add_argument("--d3-receipt", type=Path, required=True)
    parser.add_argument("--d3-observation", type=Path, required=True)
    options = parser.parse_args(arguments)

    expected_d3 = {
        "branch": D3_BRANCH,
        "selected_base_sha": D3_SELECTED_BASE_SHA,
        "package_sha256": D3_PACKAGE_SHA256,
        "package_mode": "0600",
        "receipt_present": False,
        "observation_present": False,
    }
    actions: dict[str, AzureAIEnablementActions] = {}

    def azure_revalidator(package: Mapping[str, object]) -> object:
        adapter = AzureAIEnablementActions(
            package=package,
            package_sha256=options.approved_sha256,
            browser_credential_provider=read_browser_operator_password,
        )
        actions["adapter"] = adapter
        return adapter.azure_revalidator(package)

    def operation_executor(state: str, **kwargs: object) -> object:
        adapter = actions.get("adapter")
        if adapter is None:
            raise _invalid("ai_enablement_preflight_failed")
        return adapter.operation_executor(state, **kwargs)

    def emergency_recovery(**kwargs: object) -> object:
        adapter = actions.get("adapter")
        if adapter is None:
            raise _invalid("ai_enablement_preflight_failed")
        return adapter.emergency_recovery(**kwargs)

    try:
        execute_ai_enablement(
            package_path=options.package,
            approved_sha256=options.approved_sha256,
            receipt_path=options.receipt,
            observation_path=options.observation,
            now=datetime.now(UTC),
            repository_reader=capture_repository_state,
            control_reader=collect_control_sha256,
            prior_attempts_reader=capture_prior_ai_attempts,
            d3_reader=lambda: d3_state_from_paths(
                expected=expected_d3,
                package_path=options.d3_package,
                receipt_path=options.d3_receipt,
                observation_path=options.d3_observation,
            ),
            azure_revalidator=azure_revalidator,
            paid_preflight=provider_price_preflight,
            operation_executor=operation_executor,
            emergency_recovery=emergency_recovery,
            key_provider=read_openai_api_key,
            stdin_is_tty=sys.stdin.isatty,
        )
    except AIEnablementRunInvalid as error:
        print("ai_enablement=failed")
        print(f"reason={_closed_failure_code(error)}")
        return 1
    except KeyboardInterrupt:
        print("ai_enablement=failed")
        print("reason=ai_enablement_interrupted")
        return 1
    finally:
        adapter = actions.get("adapter")
        if adapter is not None:
            adapter.clear_browser_credential()
    print("ai_enablement=completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
