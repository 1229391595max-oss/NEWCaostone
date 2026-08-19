#!/usr/bin/env python3
"""Execute one approved V6 hosted-acceptance recovery without secret leakage."""

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
import shlex
import stat
import subprocess
import sys
from typing import Any
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.create_deployed_release_recovery_package import (  # noqa: E402
    DeployedReleaseRecoveryInvalid,
    load_deployed_release_recovery_package,
)
from src.config import (  # noqa: E402
    ConfigError,
    _validate_cloud_operator_password_hash,
)


SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
READ_ONLY_PRE_RECEIPT_STAGES = ("deployed_preflight", "registry_verify")
POST_RECEIPT_STAGES = (
    "health",
    "browser_acceptance",
    "capacity",
    "expiry",
    "restart_readback",
    "rollback",
)
BROWSER_ENVIRONMENT = "BIZPULSE_BROWSER_OPERATOR_PASSWORD"
HASH_CHECK_ENVIRONMENT = "BIZPULSE_OPERATOR_PASSWORD_HASH_CHECK"
BASE_ENVIRONMENT_NAMES = (
    "AZURE_CONFIG_DIR",
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_FILE",
    "TMPDIR",
)


class DeployedReleaseExecutionInvalid(RuntimeError):
    """The approved V5 package cannot be executed safely."""


def _timestamp_text(value: str | datetime | None) -> str:
    if value is None:
        parsed = datetime.now(UTC)
    elif isinstance(value, datetime):
        if value.tzinfo is None:
            raise DeployedReleaseExecutionInvalid(
                "deployed_execution_time_invalid"
            )
        parsed = value.astimezone(UTC)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise DeployedReleaseExecutionInvalid(
                "deployed_execution_time_invalid"
            ) from error
        if parsed.tzinfo is None:
            raise DeployedReleaseExecutionInvalid(
                "deployed_execution_time_invalid"
            )
        parsed = parsed.astimezone(UTC)
    else:
        raise DeployedReleaseExecutionInvalid(
            "deployed_execution_time_invalid"
        )
    return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_base_environment(source: Mapping[str, str]) -> dict[str, str]:
    environment = {
        name: value
        for name in BASE_ENVIRONMENT_NAMES
        if (value := source.get(name)) is not None
    }
    environment.setdefault("PATH", "/usr/bin:/bin")
    return environment


def read_keychain_secret(service: str, account: str) -> str | None:
    """Read one exact generic-password value without printing it."""
    try:
        completed = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                service,
                "-a",
                account,
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_base_environment(os.environ),
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.removesuffix("\n")
    return value if value else None


def _load_and_validate_credentials(
    package: dict[str, Any],
    *,
    reader: Callable[[str, str], str | None],
) -> dict[str, str]:
    values: dict[str, str] = {}
    for source in package["keychain_sources"]:
        value = reader(source["service"], source["account"])
        if not isinstance(value, str) or not value:
            for name in list(values):
                values[name] = ""
            values.clear()
            raise DeployedReleaseExecutionInvalid(
                "deployed_execution_keychain_unavailable"
            )
        values[source["environment"]] = value
    try:
        _validate_cloud_operator_password_hash(values[HASH_CHECK_ENVIRONMENT])
        PasswordHasher().verify(
            values[HASH_CHECK_ENVIRONMENT], values[BROWSER_ENVIRONMENT]
        )
    except (ConfigError, VerificationError, TypeError, ValueError) as error:
        for name in list(values):
            values[name] = ""
        values.clear()
        raise DeployedReleaseExecutionInvalid(
            "deployed_execution_operator_pair_invalid"
        ) from error
    return values


def _write_new_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise DeployedReleaseExecutionInvalid(
            "deployed_execution_package_consumed"
        ) from error
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise DeployedReleaseExecutionInvalid(
            "deployed_execution_receipt_mode_invalid"
        )


def _replace_receipt(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise DeployedReleaseExecutionInvalid(
            "deployed_execution_receipt_mode_invalid"
        )


def _run_command(
    command: str,
    *,
    environment: dict[str, str],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError as error:
        raise DeployedReleaseExecutionInvalid(
            "deployed_execution_command_invalid"
        ) from error
    if not tokens:
        raise DeployedReleaseExecutionInvalid(
            "deployed_execution_command_invalid"
        )
    try:
        completed = runner(
            tokens,
            check=False,
            capture_output=True,
            text=True,
            timeout=3600,
            env=environment,
            cwd=PROJECT_ROOT,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DeployedReleaseExecutionInvalid(
            "deployed_execution_command_failed"
        ) from error
    if completed.returncode != 0:
        raise DeployedReleaseExecutionInvalid(
            "deployed_execution_command_failed"
        )


def execute_deployed_release_recovery(
    *,
    package_path: Path,
    expected_package_sha256: str,
    continuation_path: Path,
    receipt_path: Path,
    now: str | datetime | None = None,
    keychain_reader: Callable[[str, str], str | None] = read_keychain_secret,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    base_environment: Mapping[str, str] = os.environ,
) -> dict[str, str]:
    try:
        package_bytes = package_path.read_bytes()
    except OSError as error:
        raise DeployedReleaseExecutionInvalid(
            "deployed_execution_package_unavailable"
        ) from error
    if (
        SHA256_PATTERN.fullmatch(expected_package_sha256) is None
        or not hmac.compare_digest(
            hashlib.sha256(package_bytes).hexdigest(),
            expected_package_sha256,
        )
    ):
        raise DeployedReleaseExecutionInvalid(
            "deployed_execution_package_hash_mismatch"
        )
    try:
        package = load_deployed_release_recovery_package(
            package_path,
            continuation_path=continuation_path,
            now=now,
        )
    except DeployedReleaseRecoveryInvalid as error:
        raise DeployedReleaseExecutionInvalid(
            "deployed_execution_package_invalid"
        ) from error
    if receipt_path.exists():
        raise DeployedReleaseExecutionInvalid(
            "deployed_execution_package_consumed"
        )
    if tuple(package["execution_order"]) != (
        *READ_ONLY_PRE_RECEIPT_STAGES,
        *POST_RECEIPT_STAGES,
    ):
        raise DeployedReleaseExecutionInvalid(
            "deployed_execution_package_invalid"
        )

    base = _clean_base_environment(base_environment)
    for stage in READ_ONLY_PRE_RECEIPT_STAGES:
        for command in package["commands"][stage]:
            try:
                _run_command(
                    command,
                    environment=dict(base),
                    runner=command_runner,
                )
            except DeployedReleaseExecutionInvalid as error:
                raise DeployedReleaseExecutionInvalid(
                    "deployed_execution_readonly_stage_failed"
                ) from error

    credentials = _load_and_validate_credentials(
        package, reader=keychain_reader
    )
    receipt: dict[str, Any] = {
        "schema_version": "newcaostone.deployed-release-execution-receipt.v1",
        "authorization_id": package["authorization_id"],
        "package_sha256": expected_package_sha256,
        "started_at": _timestamp_text(now),
        "status": "started",
        "completed_stages": list(READ_ONLY_PRE_RECEIPT_STAGES),
        "failed_stage": None,
    }
    try:
        _write_new_receipt(receipt_path, receipt)
        for stage in POST_RECEIPT_STAGES:
            try:
                for command in package["commands"][stage]:
                    environment = dict(base)
                    if stage == "browser_acceptance":
                        environment[BROWSER_ENVIRONMENT] = credentials[
                            BROWSER_ENVIRONMENT
                        ]
                    _run_command(
                        command,
                        environment=environment,
                        runner=command_runner,
                    )
            except DeployedReleaseExecutionInvalid as error:
                receipt["status"] = "failed"
                receipt["failed_stage"] = stage
                _replace_receipt(receipt_path, receipt)
                raise DeployedReleaseExecutionInvalid(
                    "deployed_execution_stage_failed"
                ) from error
            receipt["completed_stages"].append(stage)
            _replace_receipt(receipt_path, receipt)
        receipt["status"] = "completed"
        receipt["completed_at"] = _timestamp_text(now)
        _replace_receipt(receipt_path, receipt)
    finally:
        for name in list(credentials):
            credentials[name] = ""
        credentials.clear()
    return {
        "status": "completed",
        "authorization_id": package["authorization_id"],
    }


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--approved-sha256", required=True)
    parser.add_argument("--continuation", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    options = parser.parse_args(arguments)
    try:
        execute_deployed_release_recovery(
            package_path=options.package,
            expected_package_sha256=options.approved_sha256,
            continuation_path=options.continuation,
            receipt_path=options.receipt,
        )
    except DeployedReleaseExecutionInvalid as error:
        print(str(error))
        print("deployed_recovery_execution=failed")
        return 1
    print("deployed_recovery_execution=completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
