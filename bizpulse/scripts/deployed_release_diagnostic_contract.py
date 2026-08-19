"""Strict value-safe primitives for the deployed release diagnostic."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import stat
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4


SAFE_CODES = frozenset(
    {
        "diagnostic_package_hash_mismatch",
        "diagnostic_package_invalid",
        "diagnostic_package_expired",
        "diagnostic_package_consumed",
        "diagnostic_repository_drift",
        "diagnostic_toolchain_drift",
        "diagnostic_control_drift",
        "diagnostic_bicep_projection_invalid",
        "diagnostic_arm_request_failed",
        "diagnostic_arm_response_invalid",
        "diagnostic_arm_scope_invalid",
        "diagnostic_pagination_invalid",
        "diagnostic_pagination_limit_exceeded",
        "diagnostic_application_drift",
        "diagnostic_revision_drift",
        "diagnostic_job_drift",
        "diagnostic_bound_execution_invalid",
        "diagnostic_execution_history_invalid",
        "diagnostic_observation_write_failed",
        "diagnostic_execution_failed",
    }
)
SAFE_STAGES = frozenset(
    {"local", "application", "revision", "job", "execution", "observation"}
)
SAFE_ROLES = frozenset(
    {
        "local",
        "application",
        "revision",
        "prepare",
        "seed",
        "session_maintenance",
        "storage_maintenance",
    }
)
MISMATCH_CATEGORIES = frozenset(
    {
        "container_image",
        "revision_state",
        "ingress_traffic",
        "environment_binding",
        "probe_contract",
        "scale",
        "resource_limits",
        "secret_reference_names",
        "container_runtime",
    }
)
OFFICIAL_EXECUTION_STATES = frozenset(
    {
        "Running",
        "Processing",
        "Stopped",
        "Degraded",
        "Failed",
        "Unknown",
        "Succeeded",
    }
)
HISTORICAL_TERMINAL_STATES = frozenset({"Succeeded", "Failed", "Stopped", "Degraded"})
ACTIVE_STATES = frozenset({"Running", "Processing"})
ACTIVE_GRACE_SECONDS = 120


class DeployedReleaseDiagnosticInvalid(RuntimeError):
    """One allowlisted diagnostic error without remote response detail."""

    def __init__(
        self,
        code: str,
        stage: str,
        resource_role: str,
        mismatch_category: str | None = None,
    ):
        if (
            code not in SAFE_CODES
            or stage not in SAFE_STAGES
            or resource_role not in SAFE_ROLES
            or not (
                mismatch_category is None or isinstance(mismatch_category, str)
            )
            or mismatch_category not in MISMATCH_CATEGORIES | {None}
            or (
                mismatch_category is not None
                and (code, stage, resource_role)
                != (
                    "diagnostic_application_drift",
                    "application",
                    "application",
                )
            )
        ):
            code, stage, resource_role, mismatch_category = (
                "diagnostic_package_invalid",
                "local",
                "local",
                None,
            )
        super().__init__(code)
        self.code = code
        self.stage = stage
        self.resource_role = resource_role
        self.mismatch_category = mismatch_category


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("diagnostic_json_duplicate_key")
        result[key] = value
    return result


def parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise DeployedReleaseDiagnosticInvalid(
            "diagnostic_package_invalid", "local", "local"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DeployedReleaseDiagnosticInvalid(
            "diagnostic_package_invalid", "local", "local"
        ) from error
    if parsed.tzinfo is None:
        raise DeployedReleaseDiagnosticInvalid(
            "diagnostic_package_invalid", "local", "local"
        )
    return parsed.astimezone(UTC)


def utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise DeployedReleaseDiagnosticInvalid(
            "diagnostic_package_invalid", "local", "local"
        )
    return (
        value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def assert_exact_keys(
    value: object,
    expected: set[str],
    *,
    code: str,
    stage: str = "local",
    role: str = "local",
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise DeployedReleaseDiagnosticInvalid(code, stage, role)
    return value


def _assert_owner_mode(path: Path) -> None:
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise DeployedReleaseDiagnosticInvalid(
            "diagnostic_observation_write_failed", "observation", "local"
        )


def load_strict_json(path: Path, *, max_bytes: int) -> Any:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= max_bytes:
            raise ValueError("invalid_json_file")
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream, object_pairs_hook=unique_object)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise DeployedReleaseDiagnosticInvalid(
            "diagnostic_package_invalid", "local", "local"
        ) from error


def write_owner_json_exclusive(path: Path, payload: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            json.dump(payload, stream, ensure_ascii=True, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _assert_owner_mode(path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def replace_owner_json_atomic(path: Path, payload: object) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        write_owner_json_exclusive(temporary, payload)
        os.replace(temporary, path)
        _assert_owner_mode(path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _execution_error(code: str, role: str) -> DeployedReleaseDiagnosticInvalid:
    return DeployedReleaseDiagnosticInvalid(code, "execution", role)


def _execution_time(value: object, *, code: str, role: str) -> datetime:
    try:
        return parse_utc(value)
    except DeployedReleaseDiagnosticInvalid as error:
        raise _execution_error(code, role) from error


def _execution_row(
    row: Mapping[str, Any], *, bound_name: str, role: str
) -> tuple[dict[str, Any], datetime, datetime | None]:
    name = row.get("name")
    properties = row.get("properties")
    code = (
        "diagnostic_bound_execution_invalid"
        if name == bound_name
        else "diagnostic_execution_history_invalid"
    )
    if not isinstance(name, str) or not name or not isinstance(properties, Mapping):
        raise _execution_error(code, role)
    if properties.get("status") not in OFFICIAL_EXECUTION_STATES:
        raise _execution_error("diagnostic_execution_history_invalid", role)
    status = properties["status"]
    start = _execution_time(properties.get("startTime"), code=code, role=role)
    end_source = properties.get("endTime")
    if status in ACTIVE_STATES and end_source is None:
        end = None
    else:
        end = _execution_time(end_source, code=code, role=role)
        if end < start:
            raise _execution_error(code, role)
    return (
        {
            "endTime": utc_text(end) if end is not None else None,
            "name": name,
            "startTime": utc_text(start),
            "status": status,
        },
        start,
        end,
    )


def evaluate_execution_history(
    role: str,
    rows: Sequence[Mapping[str, Any]],
    bound: Mapping[str, str],
    *,
    continuation_recorded_at: datetime,
    observed_at: datetime,
    replica_timeout: int,
) -> dict[str, Any]:
    if role not in {
        "prepare",
        "seed",
        "session_maintenance",
        "storage_maintenance",
    }:
        raise _execution_error("diagnostic_execution_history_invalid", "local")
    if (
        not isinstance(rows, Sequence)
        or isinstance(rows, (str, bytes))
        or not isinstance(bound, Mapping)
        or not isinstance(bound.get("name"), str)
        or bound.get("status") != "Succeeded"
        or type(replica_timeout) is not int
        or replica_timeout <= 0
        or continuation_recorded_at.tzinfo is None
        or observed_at.tzinfo is None
    ):
        raise _execution_error("diagnostic_execution_history_invalid", role)
    recorded_at = continuation_recorded_at.astimezone(UTC)
    observed = observed_at.astimezone(UTC)
    if observed < recorded_at:
        raise _execution_error("diagnostic_execution_history_invalid", role)
    bound_name = bound["name"]
    names: set[str] = set()
    parsed: list[tuple[dict[str, Any], datetime, datetime | None]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise _execution_error("diagnostic_execution_history_invalid", role)
        name = row.get("name")
        if not isinstance(name, str) or name in names:
            raise _execution_error("diagnostic_execution_history_invalid", role)
        names.add(name)
        parsed_row = _execution_row(row, bound_name=bound_name, role=role)
        if parsed_row[1] > observed or (
            parsed_row[2] is not None and parsed_row[2] > observed
        ):
            raise _execution_error("diagnostic_execution_history_invalid", role)
        parsed.append(parsed_row)
    bound_rows = [item for item in parsed if item[0]["name"] == bound_name]
    if len(bound_rows) != 1:
        raise _execution_error("diagnostic_bound_execution_invalid", role)
    bound_row, bound_start, bound_end = bound_rows[0]
    if (
        bound_row["status"] != "Succeeded"
        or bound_end is None
        or bound_end > recorded_at
    ):
        raise _execution_error("diagnostic_bound_execution_invalid", role)
    historical: list[dict[str, Any]] = []
    later: list[dict[str, Any]] = []
    scheduled = role in {"session_maintenance", "storage_maintenance"}
    for projected, start, end in parsed:
        if projected["name"] == bound_name:
            continue
        status = projected["status"]
        if (
            status in HISTORICAL_TERMINAL_STATES
            and end is not None
            and end <= bound_start
        ):
            historical.append(projected)
            continue
        if not scheduled:
            raise _execution_error("diagnostic_execution_history_invalid", role)
        if start < bound_end:
            raise _execution_error("diagnostic_execution_history_invalid", role)
        if status == "Succeeded" and end is not None:
            later.append(projected)
            continue
        if status in ACTIVE_STATES and end is None:
            age_seconds = (observed - start).total_seconds()
            if 0 <= age_seconds <= replica_timeout + ACTIVE_GRACE_SECONDS:
                later.append(projected)
                continue
        raise _execution_error("diagnostic_execution_history_invalid", role)

    def sort_key(item: Mapping[str, Any]) -> tuple[str, str]:
        return item["startTime"], item["name"]

    return {
        "bound": bound_row,
        "historical": sorted(historical, key=sort_key),
        "later": sorted(later, key=sort_key),
    }
