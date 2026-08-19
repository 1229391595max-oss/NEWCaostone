#!/usr/bin/env python3
"""Execute one approved read-only deployed release diagnostic attempt."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
import hmac
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_deployed_release_desired_projection import (  # noqa: E402
    compile_desired_projection,
)
from scripts.create_deployed_release_diagnostic_package import (  # noqa: E402
    load_deployed_release_diagnostic_package,
)
from scripts.deployed_release_diagnostic_contract import (  # noqa: E402
    DeployedReleaseDiagnosticInvalid,
    replace_owner_json_atomic,
    utc_text,
    write_owner_json_exclusive,
)
from scripts.observe_deployed_release_state import (  # noqa: E402
    observe_deployed_release_state,
)
from scripts.verify_deployed_release_state import (  # noqa: E402
    load_deployed_release_continuation,
)


ATTEMPT_SCHEMA = "newcaostone.deployed-release-diagnostic-attempt.v2"
FAILURE_KEYS = {
    "code",
    "stage",
    "resource_role",
    "mismatch_category",
}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
COMPLETED_READ_ROLES = (
    "application",
    "revision",
    "prepare",
    "seed",
    "session_maintenance",
    "storage_maintenance",
)


def _invalid(
    code: str, *, stage: str = "local", role: str = "local"
) -> DeployedReleaseDiagnosticInvalid:
    return DeployedReleaseDiagnosticInvalid(code, stage, role)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _finished_at(clock: Callable[[], datetime], *, started_at: datetime) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid("diagnostic_execution_failed", stage="execution", role="local")
    value = value.astimezone(UTC)
    if value < started_at:
        raise _invalid("diagnostic_execution_failed", stage="execution", role="local")
    return value


def _write_evidence_exclusive(path: Path, payload: object) -> None:
    try:
        write_owner_json_exclusive(path, payload)
    except OSError as error:
        raise _invalid(
            "diagnostic_observation_write_failed",
            stage="observation",
            role="local",
        ) from error


def _replace_evidence_atomic(path: Path, payload: object) -> None:
    try:
        replace_owner_json_atomic(path, payload)
    except OSError as error:
        raise _invalid(
            "diagnostic_observation_write_failed",
            stage="observation",
            role="local",
        ) from error


def _package_digest(path: Path, approved_sha256: str) -> str:
    if SHA256_PATTERN.fullmatch(approved_sha256) is None:
        raise _invalid("diagnostic_package_hash_mismatch")
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= 4_000_000:
            raise _invalid("diagnostic_package_invalid")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise _invalid("diagnostic_package_invalid") from error
    if not hmac.compare_digest(actual, approved_sha256):
        raise _invalid("diagnostic_package_hash_mismatch")
    return actual


def _started_receipt(
    *, package: dict[str, Any], package_sha256: str, started_at: datetime
) -> dict[str, Any]:
    try:
        authorization_id = package["authorization_id"]
        attempt_schema = package["attempt_schema"]
    except (KeyError, TypeError) as error:
        raise _invalid("diagnostic_package_invalid") from error
    if attempt_schema != ATTEMPT_SCHEMA:
        raise _invalid("diagnostic_package_invalid")
    return {
        "authorization_id": authorization_id,
        "completed_at": None,
        "completed_reads": 0,
        "completed_resource_roles": [],
        "failure": None,
        "observation": None,
        "package_sha256": package_sha256,
        "schema_version": attempt_schema,
        "started_at": utc_text(started_at),
        "status": "started",
    }


def execute_deployed_release_diagnostic(
    *,
    package_path: Path,
    approved_sha256: str,
    continuation_path: Path,
    receipt_path: Path,
    observation_path: Path,
    now: datetime | None = None,
    completion_clock: Callable[[], datetime] = _utc_now,
    arm_runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> dict[str, str]:
    package_sha256 = _package_digest(package_path, approved_sha256)
    observed_at = now if now is not None else datetime.now(UTC)
    if observed_at.tzinfo is None:
        raise _invalid("diagnostic_package_invalid")
    observed_at = observed_at.astimezone(UTC)
    package = load_deployed_release_diagnostic_package(
        package_path,
        continuation_path=continuation_path,
        now=observed_at,
    )
    try:
        continuation_authority = package["continuation"]
        continuation = load_deployed_release_continuation(
            continuation_path,
            expected_sha256=continuation_authority["sha256"],
        )
        desired = compile_desired_projection(
            PROJECT_ROOT / "infra/modules/app.bicep",
            continuation,
            continuation_sha256=continuation_authority["sha256"],
        )
    except (KeyError, TypeError) as error:
        raise _invalid("diagnostic_package_invalid") from error
    if os.path.lexists(receipt_path) or os.path.lexists(observation_path):
        raise _invalid("diagnostic_package_consumed")
    receipt = _started_receipt(
        package=package,
        package_sha256=package_sha256,
        started_at=observed_at,
    )
    _write_evidence_exclusive(receipt_path, receipt)

    def record_completed_read(role: str) -> None:
        completed = receipt["completed_resource_roles"]
        if (
            not isinstance(completed, list)
            or role not in COMPLETED_READ_ROLES
            or len(completed) >= len(COMPLETED_READ_ROLES)
            or role != COMPLETED_READ_ROLES[len(completed)]
        ):
            raise _invalid(
                "diagnostic_execution_failed", stage="execution", role="local"
            )
        completed.append(role)
        receipt["completed_reads"] = len(completed)
        _replace_evidence_atomic(receipt_path, receipt)

    try:
        observation = observe_deployed_release_state(
            package,
            continuation,
            desired,
            observed_at=observed_at,
            runner=arm_runner,
            package_sha256=package_sha256,
            on_completed_read=record_completed_read,
        )
        _write_evidence_exclusive(observation_path, observation)
        try:
            observation_bytes = observation_path.read_bytes()
        except OSError as error:
            raise _invalid(
                "diagnostic_observation_write_failed",
                stage="observation",
                role="local",
            ) from error
        observation_sha256 = hashlib.sha256(observation_bytes).hexdigest()
        completed_at = _finished_at(completion_clock, started_at=observed_at)
        receipt["completed_at"] = utc_text(completed_at)
        receipt["observation"] = {
            "path": str(observation_path),
            "sha256": observation_sha256,
        }
        receipt["status"] = "completed"
        _replace_evidence_atomic(receipt_path, receipt)
    except DeployedReleaseDiagnosticInvalid as error:
        completed_at = _finished_at(completion_clock, started_at=observed_at)
        receipt["completed_at"] = utc_text(completed_at)
        receipt["failure"] = {
            "code": error.code,
            "resource_role": error.resource_role,
            "stage": error.stage,
            "mismatch_category": error.mismatch_category,
        }
        receipt["observation"] = None
        receipt["status"] = "failed"
        _replace_evidence_atomic(receipt_path, receipt)
        raise _invalid(
            "diagnostic_execution_failed", stage="execution", role="local"
        ) from None
    return {"observation_sha256": observation_sha256, "state": "completed"}


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--approved-sha256", required=True)
    parser.add_argument("--continuation", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--observation", type=Path, required=True)
    options = parser.parse_args(arguments)
    try:
        execute_deployed_release_diagnostic(
            package_path=options.package,
            approved_sha256=options.approved_sha256,
            continuation_path=options.continuation,
            receipt_path=options.receipt,
            observation_path=options.observation,
        )
    except DeployedReleaseDiagnosticInvalid as error:
        print(error.code)
        print("deployed_release_diagnostic=failed")
        return 1
    print("deployed_release_diagnostic=completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
