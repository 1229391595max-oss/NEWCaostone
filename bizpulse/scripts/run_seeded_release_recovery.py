#!/usr/bin/env python3
"""Execute one approved seeded-release recovery without exposing credentials."""

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

from scripts.create_seeded_release_recovery_package import (  # noqa: E402
    SeededReleaseRecoveryInvalid,
    load_seeded_release_recovery_package,
)
from src.config import (  # noqa: E402
    ConfigError,
    _validate_cloud_operator_password_hash,
)


SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
READ_ONLY_STAGES = ("seeded_preflight", "registry_verify")
DEPLOY_ENVIRONMENTS = (
    "BIZPULSE_DEPLOY_POSTGRES_PASSWORD",
    "BIZPULSE_DEPLOY_OPERATOR_PASSWORD_HASH",
    "BIZPULSE_DEPLOY_SESSION_PEPPER",
)
BROWSER_ENVIRONMENT = "BIZPULSE_BROWSER_OPERATOR_PASSWORD"
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


class SeededReleaseExecutionInvalid(RuntimeError):
    """The approved seeded-release package cannot be executed safely."""


def _timestamp_text(value: str | datetime | None) -> str:
    if value is None:
        parsed = datetime.now(UTC)
    elif isinstance(value, datetime):
        if value.tzinfo is None:
            raise SeededReleaseExecutionInvalid("seeded_execution_time_invalid")
        parsed = value.astimezone(UTC)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise SeededReleaseExecutionInvalid(
                "seeded_execution_time_invalid"
            ) from error
        if parsed.tzinfo is None:
            raise SeededReleaseExecutionInvalid("seeded_execution_time_invalid")
        parsed = parsed.astimezone(UTC)
    else:
        raise SeededReleaseExecutionInvalid("seeded_execution_time_invalid")
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
            values.clear()
            raise SeededReleaseExecutionInvalid(
                "seeded_execution_keychain_unavailable"
            )
        values[source["environment"]] = value
    if len(values[DEPLOY_ENVIRONMENTS[0]]) < 16:
        values.clear()
        raise SeededReleaseExecutionInvalid(
            "seeded_execution_postgres_password_invalid"
        )
    if len(values[DEPLOY_ENVIRONMENTS[2]]) < 32:
        values.clear()
        raise SeededReleaseExecutionInvalid("seeded_execution_session_pepper_invalid")
    try:
        _validate_cloud_operator_password_hash(values[DEPLOY_ENVIRONMENTS[1]])
        PasswordHasher().verify(
            values[DEPLOY_ENVIRONMENTS[1]], values[BROWSER_ENVIRONMENT]
        )
    except (ConfigError, VerificationError, TypeError, ValueError) as error:
        values.clear()
        raise SeededReleaseExecutionInvalid(
            "seeded_execution_operator_pair_invalid"
        ) from error
    return values


def _write_new_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise SeededReleaseExecutionInvalid(
            "seeded_execution_package_consumed"
        ) from error
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise SeededReleaseExecutionInvalid("seeded_execution_receipt_mode_invalid")


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
        raise SeededReleaseExecutionInvalid("seeded_execution_receipt_mode_invalid")


def _run_command(
    command: str,
    *,
    environment: dict[str, str],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError as error:
        raise SeededReleaseExecutionInvalid(
            "seeded_execution_command_invalid"
        ) from error
    if not tokens:
        raise SeededReleaseExecutionInvalid("seeded_execution_command_invalid")
    try:
        completed = runner(
            tokens,
            check=False,
            capture_output=True,
            text=True,
            timeout=3600,
            env=environment,
            cwd=Path(__file__).resolve().parents[1],
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SeededReleaseExecutionInvalid(
            "seeded_execution_command_failed"
        ) from error
    if completed.returncode != 0:
        raise SeededReleaseExecutionInvalid("seeded_execution_command_failed")


def execute_seeded_release_recovery(
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
        raise SeededReleaseExecutionInvalid(
            "seeded_execution_package_unavailable"
        ) from error
    if (
        SHA256_PATTERN.fullmatch(expected_package_sha256) is None
        or not hmac.compare_digest(
            hashlib.sha256(package_bytes).hexdigest(), expected_package_sha256
        )
    ):
        raise SeededReleaseExecutionInvalid(
            "seeded_execution_package_hash_mismatch"
        )
    try:
        package = load_seeded_release_recovery_package(
            package_path,
            continuation_path=continuation_path,
            now=now,
        )
    except SeededReleaseRecoveryInvalid as error:
        raise SeededReleaseExecutionInvalid(
            "seeded_execution_package_invalid"
        ) from error
    if receipt_path.exists():
        raise SeededReleaseExecutionInvalid("seeded_execution_package_consumed")

    base = _clean_base_environment(base_environment)
    for stage in READ_ONLY_STAGES:
        for command in package["commands"][stage]:
            try:
                _run_command(command, environment=dict(base), runner=command_runner)
            except SeededReleaseExecutionInvalid as error:
                raise SeededReleaseExecutionInvalid(
                    "seeded_execution_readonly_stage_failed"
                ) from error

    credentials = _load_and_validate_credentials(package, reader=keychain_reader)
    receipt = {
        "schema_version": "newcaostone.seeded-release-execution-receipt.v1",
        "authorization_id": package["authorization_id"],
        "package_sha256": expected_package_sha256,
        "started_at": _timestamp_text(now),
        "status": "started",
        "completed_stages": list(READ_ONLY_STAGES),
        "failed_stage": None,
    }
    try:
        _write_new_receipt(receipt_path, receipt)
        for stage in package["execution_order"][len(READ_ONLY_STAGES) :]:
            try:
                for command in package["commands"][stage]:
                    environment = dict(base)
                    tokens = shlex.split(command, posix=True)
                    if tokens[:4] == ["az", "deployment", "group", "create"]:
                        environment.update(
                            {name: credentials[name] for name in DEPLOY_ENVIRONMENTS}
                        )
                    elif stage == "browser_acceptance":
                        environment[BROWSER_ENVIRONMENT] = credentials[
                            BROWSER_ENVIRONMENT
                        ]
                    _run_command(
                        command,
                        environment=environment,
                        runner=command_runner,
                    )
            except SeededReleaseExecutionInvalid as error:
                receipt["status"] = "failed"
                receipt["failed_stage"] = stage
                _replace_receipt(receipt_path, receipt)
                raise SeededReleaseExecutionInvalid(
                    "seeded_execution_stage_failed"
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
        execute_seeded_release_recovery(
            package_path=options.package,
            expected_package_sha256=options.approved_sha256,
            continuation_path=options.continuation,
            receipt_path=options.receipt,
        )
    except SeededReleaseExecutionInvalid as error:
        print(str(error))
        print("seeded_recovery_execution=failed")
        return 1
    print("seeded_recovery_execution=completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
