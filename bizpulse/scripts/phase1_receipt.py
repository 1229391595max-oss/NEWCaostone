"""Collect and verify a value-safe Azure Phase 1 fence receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]{1,62}[a-z0-9]")
IMAGE_PATTERN = re.compile(
    r"[a-z0-9]{5,50}\.azurecr\.io/[a-z0-9][a-z0-9._/-]{1,127}"
    r"@sha256:[0-9a-f]{64}"
)
TERMINAL_EXECUTION_STATES = frozenset({"Failed", "Stopped", "Succeeded"})
RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_id",
        "kind",
        "source_launch_authorization_sha256",
        "source_authorization_id",
        "release",
        "phase1_deployment",
        "phase1_anchor_at",
        "phase1_fence_observed_at",
        "app",
        "jobs",
        "executions",
    }
)


class Phase1ReceiptInvalid(ValueError):
    """The Phase 1 receipt could not be proved from exact authority."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("phase1_receipt_json_duplicate_key")
        result[key] = value
    return result


def _mapping(value: object, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Phase1ReceiptInvalid(code)
    return value


def _sequence(value: object, code: str) -> list[Any]:
    if not isinstance(value, list):
        raise Phase1ReceiptInvalid(code)
    return value


def _timestamp(value: object, code: str) -> datetime:
    if not isinstance(value, str):
        raise Phase1ReceiptInvalid(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise Phase1ReceiptInvalid(code) from error
    if parsed.tzinfo is None:
        raise Phase1ReceiptInvalid(code)
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    normalized = value.astimezone(UTC)
    timespec = "microseconds" if normalized.microsecond else "seconds"
    return normalized.isoformat(timespec=timespec).replace("+00:00", "Z")


def _token_value(tokens: list[str], name: str, code: str) -> str:
    if tokens.count(name) != 1:
        raise Phase1ReceiptInvalid(code)
    index = tokens.index(name)
    if index + 1 >= len(tokens):
        raise Phase1ReceiptInvalid(code)
    value = tokens[index + 1]
    if not value or value.startswith("-"):
        raise Phase1ReceiptInvalid(code)
    return value


def _source_authority(source: dict[str, object]) -> dict[str, str]:
    commands = _mapping(source.get("commands"), "phase1_receipt_source_invalid")
    provision = _sequence(
        commands.get("provision"), "phase1_receipt_source_invalid"
    )
    if len(provision) != 3 or any(not isinstance(row, str) for row in provision):
        raise Phase1ReceiptInvalid("phase1_receipt_source_invalid")
    deployment_tokens = shlex.split(provision[1])
    fence_tokens = shlex.split(provision[2])
    if fence_tokens[-2:] != ["--mode", "initial"]:
        raise Phase1ReceiptInvalid("phase1_receipt_source_invalid")
    authority = {
        "subscription": _token_value(
            fence_tokens, "--subscription", "phase1_receipt_source_invalid"
        ),
        "resource_group": _token_value(
            fence_tokens, "--resource-group", "phase1_receipt_source_invalid"
        ),
        "app": _token_value(
            fence_tokens, "--app", "phase1_receipt_source_invalid"
        ),
        "image": _token_value(
            fence_tokens, "--image", "phase1_receipt_source_invalid"
        ),
        "prepare": _token_value(
            fence_tokens, "--prepare-job", "phase1_receipt_source_invalid"
        ),
        "seed": _token_value(
            fence_tokens, "--seed-job", "phase1_receipt_source_invalid"
        ),
        "maintain-sessions": _token_value(
            fence_tokens, "--session-job", "phase1_receipt_source_invalid"
        ),
        "maintain-storage": _token_value(
            fence_tokens, "--storage-job", "phase1_receipt_source_invalid"
        ),
        "manifest": _token_value(
            fence_tokens,
            "--synthetic-manifest-sha256",
            "phase1_receipt_source_invalid",
        ),
        "dataset_version": _token_value(
            fence_tokens,
            "--synthetic-dataset-version-id",
            "phase1_receipt_source_invalid",
        ),
        "deployment": _token_value(
            deployment_tokens, "--name", "phase1_receipt_source_invalid"
        ),
    }
    for field in ("subscription", "resource_group"):
        if authority[field] != _token_value(
            deployment_tokens, f"--{field.replace('_', '-')}", "phase1_receipt_source_invalid"
        ):
            raise Phase1ReceiptInvalid("phase1_receipt_source_invalid")
    if (
        UUID_PATTERN.fullmatch(authority["subscription"]) is None
        or any(
            NAME_PATTERN.fullmatch(authority[field]) is None
            for field in (
                "resource_group",
                "app",
                "prepare",
                "seed",
                "maintain-sessions",
                "maintain-storage",
                "deployment",
            )
        )
        or IMAGE_PATTERN.fullmatch(authority["image"]) is None
        or SHA256_PATTERN.fullmatch(authority["manifest"]) is None
        or UUID_PATTERN.fullmatch(authority["dataset_version"]) is None
    ):
        raise Phase1ReceiptInvalid("phase1_receipt_source_invalid")
    return authority


def _release(source: dict[str, object], expected_image: str) -> dict[str, object]:
    release = _mapping(source.get("release"), "phase1_receipt_release_invalid")
    required = {
        "git_sha": GIT_SHA_PATTERN,
        "image_digest": re.compile(r"sha256:[0-9a-f]{64}"),
        "image_input_sha256": SHA256_PATTERN,
        "rollback_git_sha": GIT_SHA_PATTERN,
        "rollback_image_digest": re.compile(r"sha256:[0-9a-f]{64}"),
        "rollback_image_input_sha256": SHA256_PATTERN,
    }
    if any(
        not isinstance(release.get(field), str)
        or pattern.fullmatch(release[field]) is None
        for field, pattern in required.items()
    ) or not expected_image.endswith(f"@{release['image_digest']}"):
        raise Phase1ReceiptInvalid("phase1_receipt_release_invalid")
    return json.loads(json.dumps(release, sort_keys=True))


def _deployment_anchor(
    deployment: dict[str, object], expected: dict[str, str]
) -> datetime:
    properties = _mapping(
        deployment.get("properties"), "phase1_receipt_deployment_invalid"
    )
    identifier = deployment.get("id")
    if (
        deployment.get("name") != expected["deployment"]
        or properties.get("provisioningState") != "Succeeded"
        or not isinstance(identifier, str)
        or not identifier.endswith(f"/deployments/{expected['deployment']}")
        or f"/resourceGroups/{expected['resource_group']}/" not in identifier
    ):
        raise Phase1ReceiptInvalid("phase1_receipt_deployment_invalid")
    return _timestamp(
        properties.get("timestamp"), "phase1_receipt_deployment_invalid"
    )


def _require_private_app(
    app: dict[str, object],
    revisions: list[dict[str, object]],
    expected: dict[str, str],
) -> str:
    properties = _mapping(app.get("properties"), "phase1_receipt_app_not_fenced")
    configuration = _mapping(
        properties.get("configuration"), "phase1_receipt_app_not_fenced"
    )
    ingress = _mapping(
        configuration.get("ingress"), "phase1_receipt_app_not_fenced"
    )
    template = _mapping(
        properties.get("template"), "phase1_receipt_app_not_fenced"
    )
    scale = _mapping(template.get("scale"), "phase1_receipt_app_not_fenced")
    containers = _sequence(
        template.get("containers"), "phase1_receipt_app_not_fenced"
    )
    digest = expected["image"].rsplit(":", 1)[1]
    revision = f"{expected['app']}--prep-{digest[:7]}"
    if len(containers) != 1:
        raise Phase1ReceiptInvalid("phase1_receipt_app_not_fenced")
    container = _mapping(containers[0], "phase1_receipt_app_not_fenced")
    scale_is_fenced = (
        set(scale)
        <= {
            "cooldownPeriod",
            "maxReplicas",
            "minReplicas",
            "pollingInterval",
            "rules",
        }
        and scale.get("maxReplicas") == 1
        and scale.get("minReplicas") == 0
        and (
            "cooldownPeriod" not in scale or scale.get("cooldownPeriod") == 300
        )
        and (
            "pollingInterval" not in scale or scale.get("pollingInterval") == 30
        )
        and ("rules" not in scale or scale.get("rules") in (None, []))
    )
    if (
        app.get("name") != expected["app"]
        or properties.get("latestRevisionName") != revision
        or configuration.get("activeRevisionsMode") != "Single"
        or configuration.get("secrets") not in (None, [])
        or ingress.get("external") is not False
        or ingress.get("traffic") != [{"latestRevision": True, "weight": 100}]
        or not scale_is_fenced
        or container.get("name") != "bizpulse"
        or container.get("image") != expected["image"]
        or container.get("command") != ["python"]
        or container.get("args") != ["scripts/phase1_fence_server.py"]
        or container.get("env")
        != [
            {
                "name": "BIZPULSE_RUNTIME_ENVIRONMENT",
                "value": "phase1-fenced",
            }
        ]
        or not revisions
    ):
        raise Phase1ReceiptInvalid("phase1_receipt_app_not_fenced")
    seen_revision = False
    for row in revisions:
        revision_row = _mapping(row, "phase1_receipt_revision_invalid")
        revision_properties = _mapping(
            revision_row.get("properties"), "phase1_receipt_revision_invalid"
        )
        replicas = revision_properties.get("replicas")
        if type(replicas) is not int or replicas != 0:
            raise Phase1ReceiptInvalid("phase1_receipt_revision_not_drained")
        seen_revision = seen_revision or revision_row.get("name") == revision
    if not seen_revision:
        raise Phase1ReceiptInvalid("phase1_receipt_revision_invalid")
    return revision


def _expected_job_args(expected: dict[str, str]) -> dict[str, list[str]]:
    return {
        "prepare": ["scripts/prepare_cloud.py"],
        "seed": [
            "scripts/seed_demo.py",
            "tests/fixtures/synthetic/v1",
            "--expected-manifest-sha256",
            expected["manifest"],
            "--expected-dataset-version-id",
            expected["dataset_version"],
        ],
        "maintain-sessions": ["scripts/maintain_sessions.py"],
        "maintain-storage": ["scripts/maintain_storage.py", "--expire-temporary"],
    }


def _require_jobs(
    jobs: dict[str, dict[str, object]], expected: dict[str, str]
) -> dict[str, str]:
    if set(jobs) != {
        "prepare",
        "seed",
        "maintain-sessions",
        "maintain-storage",
    }:
        raise Phase1ReceiptInvalid("phase1_receipt_job_invalid")
    args = _expected_job_args(expected)
    result: dict[str, str] = {}
    for role, job in jobs.items():
        properties = _mapping(job.get("properties"), "phase1_receipt_job_invalid")
        configuration = _mapping(
            properties.get("configuration"), "phase1_receipt_job_invalid"
        )
        template = _mapping(
            properties.get("template"), "phase1_receipt_job_invalid"
        )
        containers = _sequence(
            template.get("containers"), "phase1_receipt_job_invalid"
        )
        if len(containers) != 1:
            raise Phase1ReceiptInvalid("phase1_receipt_job_invalid")
        container = _mapping(containers[0], "phase1_receipt_job_invalid")
        if (
            job.get("name") != expected[role]
            or configuration.get("triggerType") != "Manual"
            or container.get("name") != role
            or container.get("image") != expected["image"]
            or container.get("command") != ["python"]
            or container.get("args") != args[role]
        ):
            raise Phase1ReceiptInvalid("phase1_receipt_job_invalid")
        result[role] = expected[role]
    return result


def _execution_projection(row: dict[str, object]) -> dict[str, str]:
    properties = _mapping(
        row.get("properties"), "phase1_receipt_execution_state_invalid"
    )
    name = row.get("name")
    status = properties.get("status")
    if (
        not isinstance(name, str)
        or NAME_PATTERN.fullmatch(name) is None
        or status not in TERMINAL_EXECUTION_STATES
    ):
        raise Phase1ReceiptInvalid("phase1_receipt_execution_state_invalid")
    started = _timestamp(
        properties.get("startTime"), "phase1_receipt_execution_state_invalid"
    )
    ended = _timestamp(
        properties.get("endTime"), "phase1_receipt_execution_state_invalid"
    )
    if ended < started:
        raise Phase1ReceiptInvalid("phase1_receipt_execution_state_invalid")
    return {
        "name": name,
        "status": status,
        "started_at": _utc_text(started),
        "ended_at": _utc_text(ended),
    }


def _execution_authority(
    executions: dict[str, list[dict[str, object]]],
    *,
    anchor: datetime,
    observed_at: datetime,
) -> dict[str, object]:
    expected_roles = {
        "prepare",
        "seed",
        "maintain-sessions",
        "maintain-storage",
    }
    if set(executions) != expected_roles:
        raise Phase1ReceiptInvalid("phase1_receipt_execution_state_invalid")
    projected = {
        role: [_execution_projection(row) for row in rows]
        for role, rows in executions.items()
    }
    result: dict[str, object] = {}
    for role in ("prepare", "seed"):
        qualified = [
            row
            for row in projected[role]
            if _timestamp(row["started_at"], "phase1_receipt_execution_state_invalid")
            >= anchor
        ]
        if len(qualified) != 1 or qualified[0]["status"] != "Succeeded":
            raise Phase1ReceiptInvalid(f"phase1_receipt_{role}_not_proved")
        if (
            _timestamp(
                qualified[0]["ended_at"], "phase1_receipt_execution_state_invalid"
            )
            > observed_at
        ):
            raise Phase1ReceiptInvalid("phase1_receipt_observation_invalid")
        result[role] = qualified[0]
    for role in ("maintain-sessions", "maintain-storage"):
        if any(
            _timestamp(row["started_at"], "phase1_receipt_execution_state_invalid")
            >= anchor
            for row in projected[role]
        ):
            raise Phase1ReceiptInvalid("phase1_receipt_maintenance_after_anchor")
        latest = max(
            (row["started_at"] for row in projected[role]),
            default=None,
        )
        result[role] = {
            "terminal_before_anchor_count": len(projected[role]),
            "latest_started_at": latest,
        }
    return result


def collect_legacy_receipt(
    *,
    source_authority: dict[str, object],
    source_sha256: str,
    deployment: dict[str, object],
    app: dict[str, object],
    revisions: list[dict[str, object]],
    jobs: dict[str, dict[str, object]],
    executions: dict[str, list[dict[str, object]]],
    observed_at: datetime,
) -> dict[str, object]:
    if SHA256_PATTERN.fullmatch(source_sha256) is None:
        raise Phase1ReceiptInvalid("phase1_receipt_source_invalid")
    source_id = source_authority.get("authorization_id")
    if not isinstance(source_id, str) or UUID_PATTERN.fullmatch(source_id) is None:
        raise Phase1ReceiptInvalid("phase1_receipt_source_invalid")
    expected = _source_authority(source_authority)
    release = _release(source_authority, expected["image"])
    anchor = _deployment_anchor(deployment, expected)
    if observed_at.tzinfo is None or observed_at.astimezone(UTC) < anchor:
        raise Phase1ReceiptInvalid("phase1_receipt_observation_invalid")
    revision = _require_private_app(app, revisions, expected)
    job_names = _require_jobs(jobs, expected)
    execution_authority = _execution_authority(
        executions,
        anchor=anchor,
        observed_at=observed_at.astimezone(UTC),
    )
    return {
        "schema_version": "newcaostone.phase1-receipt.v1",
        "receipt_id": str(uuid4()),
        "kind": "legacy",
        "source_launch_authorization_sha256": source_sha256,
        "source_authorization_id": source_id,
        "release": release,
        "phase1_deployment": {
            "id": deployment["id"],
            "name": deployment["name"],
            "status": "Succeeded",
            "finished_at": _utc_text(anchor),
        },
        "phase1_anchor_at": _utc_text(anchor),
        "phase1_fence_observed_at": _utc_text(observed_at),
        "app": {
            "name": expected["app"],
            "revision": revision,
            "image": expected["image"],
            "external": False,
        },
        "jobs": job_names,
        "executions": execution_authority,
    }


def _read_azure_json(
    arguments: tuple[str, ...],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> object:
    try:
        completed = runner(
            [
                "az",
                *arguments,
                "--only-show-errors",
                "--output",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise Phase1ReceiptInvalid("phase1_receipt_azure_read_failed") from error
    if not isinstance(completed.stdout, str) or len(completed.stdout) > 1_000_000:
        raise Phase1ReceiptInvalid("phase1_receipt_azure_response_invalid")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise Phase1ReceiptInvalid("phase1_receipt_azure_response_invalid") from error


def collect_from_azure(
    *,
    source_authority: dict[str, object],
    source_sha256: str,
    observed_at: datetime,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    expected = _source_authority(source_authority)
    common = (
        "--subscription",
        expected["subscription"],
        "--resource-group",
        expected["resource_group"],
    )
    deployment = _mapping(
        _read_azure_json(
            (
                "deployment",
                "group",
                "show",
                *common,
                "--name",
                expected["deployment"],
            ),
            runner=runner,
        ),
        "phase1_receipt_azure_response_invalid",
    )
    app = _mapping(
        _read_azure_json(
            ("containerapp", "show", *common, "--name", expected["app"]),
            runner=runner,
        ),
        "phase1_receipt_azure_response_invalid",
    )
    revisions = _sequence(
        _read_azure_json(
            (
                "containerapp",
                "revision",
                "list",
                *common,
                "--name",
                expected["app"],
            ),
            runner=runner,
        ),
        "phase1_receipt_azure_response_invalid",
    )
    jobs: dict[str, dict[str, object]] = {}
    executions: dict[str, list[dict[str, object]]] = {}
    for role in (
        "prepare",
        "seed",
        "maintain-sessions",
        "maintain-storage",
    ):
        job_name = expected[role]
        jobs[role] = _mapping(
            _read_azure_json(
                ("containerapp", "job", "show", *common, "--name", job_name),
                runner=runner,
            ),
            "phase1_receipt_azure_response_invalid",
        )
        execution_rows = _sequence(
            _read_azure_json(
                (
                    "containerapp",
                    "job",
                    "execution",
                    "list",
                    *common,
                    "--name",
                    job_name,
                ),
                runner=runner,
            ),
            "phase1_receipt_azure_response_invalid",
        )
        if any(not isinstance(row, dict) for row in execution_rows):
            raise Phase1ReceiptInvalid("phase1_receipt_azure_response_invalid")
        executions[role] = execution_rows
    return collect_legacy_receipt(
        source_authority=source_authority,
        source_sha256=source_sha256,
        deployment=deployment,
        app=app,
        revisions=revisions,
        jobs=jobs,
        executions=executions,
        observed_at=observed_at,
    )


def _validate_receipt_shape(receipt: dict[str, object]) -> None:
    receipt_id = receipt.get("receipt_id")
    if (
        set(receipt) != RECEIPT_FIELDS
        or receipt.get("schema_version") != "newcaostone.phase1-receipt.v1"
        or receipt.get("kind") != "legacy"
        or not isinstance(receipt_id, str)
        or UUID_PATTERN.fullmatch(receipt_id) is None
        or SHA256_PATTERN.fullmatch(
            str(receipt.get("source_launch_authorization_sha256"))
        )
        is None
    ):
        raise Phase1ReceiptInvalid("phase1_receipt_fields_invalid")
    _timestamp(
        receipt.get("phase1_anchor_at"), "phase1_receipt_fields_invalid"
    )
    _timestamp(
        receipt.get("phase1_fence_observed_at"),
        "phase1_receipt_fields_invalid",
    )


def verify_receipt(
    *, expected: dict[str, object], observed: dict[str, object]
) -> None:
    _validate_receipt_shape(expected)
    _validate_receipt_shape(observed)
    expected_copy = json.loads(json.dumps(expected, sort_keys=True))
    observed_copy = json.loads(json.dumps(observed, sort_keys=True))
    expected_observed_at = _timestamp(
        expected_copy.pop("phase1_fence_observed_at"),
        "phase1_receipt_fields_invalid",
    )
    observed_observed_at = _timestamp(
        observed_copy.pop("phase1_fence_observed_at"),
        "phase1_receipt_fields_invalid",
    )
    expected_copy.pop("receipt_id")
    observed_copy.pop("receipt_id")
    if observed_observed_at < expected_observed_at or observed_copy != expected_copy:
        raise Phase1ReceiptInvalid("phase1_receipt_observation_mismatch")


def write_receipt(path: Path, receipt: dict[str, object]) -> None:
    _validate_receipt_shape(receipt)
    payload = (
        json.dumps(
            receipt,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise Phase1ReceiptInvalid("phase1_receipt_mode_invalid")


def load_source_authority(path: Path, sha256: str) -> dict[str, object]:
    if SHA256_PATTERN.fullmatch(sha256) is None:
        raise Phase1ReceiptInvalid("phase1_receipt_source_invalid")
    try:
        source_bytes = path.read_bytes()
        source_text = source_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise Phase1ReceiptInvalid("phase1_receipt_source_unavailable") from error
    if hashlib.sha256(source_bytes).hexdigest() != sha256:
        raise Phase1ReceiptInvalid("phase1_receipt_source_hash_mismatch")
    match = re.fullmatch(
        r"# NEWCaostone Launch Authorization\n\n```json\n(?P<payload>.*)\n```\n?",
        source_text,
        flags=re.DOTALL,
    )
    if match is None:
        raise Phase1ReceiptInvalid("phase1_receipt_source_invalid")
    try:
        payload = json.loads(
            match.group("payload"), object_pairs_hook=_unique_object
        )
    except (ValueError, json.JSONDecodeError) as error:
        raise Phase1ReceiptInvalid("phase1_receipt_source_invalid") from error
    if not isinstance(payload, dict):
        raise Phase1ReceiptInvalid("phase1_receipt_source_invalid")
    issued_at = _timestamp(
        payload.get("issued_at"), "phase1_receipt_source_invalid"
    )
    try:
        from tests.hosted import verify_azure_demo as verifier
    except ImportError as error:
        raise Phase1ReceiptInvalid("phase1_receipt_source_invalid") from error
    try:
        authority = verifier.load_authorization(
            path,
            now=issued_at.replace(microsecond=0) + timedelta(seconds=1),
        )
    except verifier.AuthorizationInvalid as error:
        raise Phase1ReceiptInvalid("phase1_receipt_source_invalid") from error
    return authority


def load_receipt(path: Path) -> dict[str, object]:
    try:
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise Phase1ReceiptInvalid("phase1_receipt_mode_invalid")
        source = path.read_bytes()
    except OSError as error:
        raise Phase1ReceiptInvalid("phase1_receipt_unavailable") from error
    if len(source) > 262_144:
        raise Phase1ReceiptInvalid("phase1_receipt_fields_invalid")
    try:
        parsed = json.loads(source, object_pairs_hook=_unique_object)
    except (ValueError, json.JSONDecodeError) as error:
        raise Phase1ReceiptInvalid("phase1_receipt_fields_invalid") from error
    if not isinstance(parsed, dict):
        raise Phase1ReceiptInvalid("phase1_receipt_fields_invalid")
    _validate_receipt_shape(parsed)
    canonical = (
        json.dumps(
            parsed,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    if source != canonical:
        raise Phase1ReceiptInvalid("phase1_receipt_canonical_invalid")
    return parsed


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    collect_parser = subparsers.add_parser("collect")
    verify_parser = subparsers.add_parser("verify")
    for command_parser in (collect_parser, verify_parser):
        command_parser.add_argument(
            "--source-authorization", required=True, type=Path
        )
        command_parser.add_argument("--source-sha256", required=True)
    collect_parser.add_argument("--output", required=True, type=Path)
    verify_parser.add_argument("--receipt", required=True, type=Path)
    options = parser.parse_args(arguments)
    try:
        authority = load_source_authority(
            options.source_authorization, options.source_sha256
        )
        observed = collect_from_azure(
            source_authority=authority,
            source_sha256=options.source_sha256,
            observed_at=datetime.now(UTC),
        )
        if options.operation == "collect":
            write_receipt(options.output, observed)
            digest = hashlib.sha256(options.output.read_bytes()).hexdigest()
            print("phase1_receipt=ok")
            print(f"output={options.output}")
            print(f"sha256={digest}")
        else:
            expected = load_receipt(options.receipt)
            verify_receipt(expected=expected, observed=observed)
            print("phase1_receipt=ok")
    except (OSError, Phase1ReceiptInvalid):
        print("phase1_receipt=invalid")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
