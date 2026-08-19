"""Generate a no-AI Azure resume authority bound to a Phase 1 receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.phase1_receipt import (  # noqa: E402
    Phase1ReceiptInvalid,
    load_receipt,
    load_source_authority,
)


SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9._/-]{1,255}")
UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
RESUME_STAGES = (
    "prepared_preflight",
    "registry_verify",
    "phase1_receipt",
    "activate_fence",
    "deploy",
    "health",
    "browser_acceptance",
    "capacity",
    "expiry",
    "restart_readback",
    "rollback",
)
CONTROL_FIELDS = frozenset(
    {
        "phase1_receipt_sha256",
        "resume_generator_sha256",
        "resume_runner_sha256",
    }
)


class ResumeAuthorityInvalid(ValueError):
    """The receipt-bound resume authority could not be proved exactly."""


def _mapping(value: object, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ResumeAuthorityInvalid(code)
    return value


def _string_sequence(value: object, code: str) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(row, str) or not row for row in value)
    ):
        raise ResumeAuthorityInvalid(code)
    return value


def _timestamp(value: object, code: str) -> datetime:
    if not isinstance(value, str):
        raise ResumeAuthorityInvalid(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ResumeAuthorityInvalid(code) from error
    if parsed.tzinfo is None:
        raise ResumeAuthorityInvalid(code)
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    normalized = value.astimezone(UTC)
    timespec = "microseconds" if normalized.microsecond else "seconds"
    return normalized.isoformat(timespec=timespec).replace("+00:00", "Z")


def _safe_reference(value: str) -> str:
    if (
        not isinstance(value, str)
        or REFERENCE_PATTERN.fullmatch(value) is None
        or "\\" in value
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        raise ResumeAuthorityInvalid("resume_reference_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ResumeAuthorityInvalid("resume_reference_invalid")
    return value


def _file_sha256(path: Path, code: str) -> str:
    try:
        if not path.is_file() or path.stat().st_size > 2_000_000:
            raise ResumeAuthorityInvalid(code)
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ResumeAuthorityInvalid(code) from error


def _require_sha256(value: str, code: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ResumeAuthorityInvalid(code)
    return value


def _load_source(path: Path, sha256: str) -> dict[str, object]:
    try:
        return load_source_authority(path, sha256)
    except Phase1ReceiptInvalid as error:
        raise ResumeAuthorityInvalid("resume_source_invalid") from error


def _load_bound_receipt(path: Path, sha256: str) -> dict[str, object]:
    _require_sha256(sha256, "resume_receipt_invalid")
    if _file_sha256(path, "resume_receipt_invalid") != sha256:
        raise ResumeAuthorityInvalid("resume_receipt_hash_mismatch")
    try:
        return load_receipt(path)
    except Phase1ReceiptInvalid as error:
        raise ResumeAuthorityInvalid("resume_receipt_invalid") from error


def _require_no_ai(source: dict[str, object]) -> None:
    ai_limits = _mapping(source.get("ai_limits"), "resume_no_ai_boundary_invalid")
    secrets = _mapping(
        source.get("secret_presence"), "resume_no_ai_boundary_invalid"
    )
    publication = _mapping(
        source.get("external_publication"), "resume_no_ai_boundary_invalid"
    )
    limits = _mapping(source.get("limits_usd"), "resume_no_ai_boundary_invalid")
    commands = _mapping(source.get("commands"), "resume_no_ai_boundary_invalid")
    settings = source.get("server_settings")
    if (
        ai_limits.get("enabled") is not False
        or secrets.get("openai_api_key") is not False
        or publication.get("paid_ai_smoke") is not False
        or limits.get("openai_smoke_cap") != "0.00"
        or not isinstance(settings, list)
        or "OPENAI_API_KEY" in settings
        or any(
            commands.get(stage) != []
            for stage in ("budget_failure", "provider_failure", "paid_ai_smoke")
        )
    ):
        raise ResumeAuthorityInvalid("resume_no_ai_boundary_invalid")


def _replace_not_before(command: str, anchor: str) -> str:
    pattern = re.compile(r"(?<!\S)--not-before\s+[^\s]+")
    matches = list(pattern.finditer(command))
    if len(matches) != 1:
        raise ResumeAuthorityInvalid("resume_command_invalid")
    replaced = pattern.sub(f"--not-before {anchor}", command)
    if replaced.count("--not-before") != 1:
        raise ResumeAuthorityInvalid("resume_command_invalid")
    return replaced


def _source_commands(source: dict[str, object], *, anchor: str) -> dict[str, list[str]]:
    commands = _mapping(source.get("commands"), "resume_command_invalid")

    activate = _string_sequence(commands.get("activate"), "resume_command_invalid")
    deploy = _string_sequence(commands.get("deploy"), "resume_command_invalid")
    registry_verify = _string_sequence(
        commands.get("registry_verify"), "resume_command_invalid"
    )
    if len(activate) != 2 or len(deploy) != 4 or len(registry_verify) not in (2, 3):
        raise ResumeAuthorityInvalid("resume_command_invalid")

    result = {
        "prepared_preflight": [activate[0]],
        "registry_verify": registry_verify[:2],
        "activate_fence": [_replace_not_before(activate[1], anchor)],
        "deploy": [*deploy[:3], _replace_not_before(deploy[3], anchor)],
    }
    for stage in (
        "health",
        "browser_acceptance",
        "capacity",
        "expiry",
        "restart_readback",
        "rollback",
    ):
        rows = _string_sequence(commands.get(stage), "resume_command_invalid")
        if len(rows) != 1:
            raise ResumeAuthorityInvalid("resume_command_invalid")
        result[stage] = rows
    return result


def _same_release(source: dict[str, object], receipt: dict[str, object]) -> bool:
    source_release = source.get("release")
    receipt_release = receipt.get("release")
    return (
        isinstance(source_release, dict)
        and isinstance(receipt_release, dict)
        and json.loads(json.dumps(source_release, sort_keys=True))
        == json.loads(json.dumps(receipt_release, sort_keys=True))
    )


def generate_resume_authority(
    *,
    source_path: Path,
    source_sha256: str,
    source_reference: str,
    receipt_path: Path,
    receipt_sha256: str,
    receipt_reference: str,
    control_paths: dict[str, Path],
    issued_at: datetime,
) -> dict[str, object]:
    """Build a canonical, no-AI resume authority without mutating its inputs."""

    _require_sha256(source_sha256, "resume_source_invalid")
    source = _load_source(source_path, source_sha256)
    receipt = _load_bound_receipt(receipt_path, receipt_sha256)
    _require_no_ai(source)

    source_id = source.get("authorization_id")
    receipt_id = receipt.get("receipt_id")
    if (
        receipt.get("source_launch_authorization_sha256") != source_sha256
        or receipt.get("source_authorization_id") != source_id
        or not isinstance(source_id, str)
        or UUID_PATTERN.fullmatch(source_id) is None
        or not isinstance(receipt_id, str)
        or UUID_PATTERN.fullmatch(receipt_id) is None
        or not _same_release(source, receipt)
    ):
        raise ResumeAuthorityInvalid("resume_receipt_mismatch")

    anchor = _timestamp(receipt.get("phase1_anchor_at"), "resume_receipt_invalid")
    observed = _timestamp(
        receipt.get("phase1_fence_observed_at"), "resume_receipt_invalid"
    )
    if issued_at.tzinfo is None or issued_at.astimezone(UTC) < observed:
        raise ResumeAuthorityInvalid("resume_issue_time_invalid")
    normalized_issue = issued_at.astimezone(UTC)

    if set(control_paths) != CONTROL_FIELDS:
        raise ResumeAuthorityInvalid("resume_control_invalid")
    control_sha256 = {
        field: _file_sha256(control_paths[field], "resume_control_invalid")
        for field in sorted(CONTROL_FIELDS)
    }

    anchor_text = _utc_text(anchor)
    commands = _source_commands(source, anchor=anchor_text)
    commands["phase1_receipt"] = [
        ".venv/bin/python scripts/phase1_receipt.py verify "
        f"--source-authorization {_safe_reference(source_reference)} "
        f"--source-sha256 {source_sha256} "
        f"--receipt {_safe_reference(receipt_reference)}"
    ]
    ordered_commands = {stage: commands[stage] for stage in RESUME_STAGES}

    return {
        "schema_version": (
            "newcaostone.phase1-receipt-resume-authorization.v1"
        ),
        "authorization_id": str(uuid4()),
        "issued_at": _utc_text(normalized_issue),
        "expires_at": _utc_text(normalized_issue + timedelta(hours=24)),
        "source_launch_authorization_reference": _safe_reference(
            source_reference
        ),
        "source_launch_authorization_sha256": source_sha256,
        "source_authorization_id": source_id,
        "receipt_reference": _safe_reference(receipt_reference),
        "receipt_sha256": receipt_sha256,
        "receipt_id": receipt_id,
        "receipt_anchor_at": anchor_text,
        "receipt_fence_observed_at": _utc_text(observed),
        "subscription_id": source["subscription_id"],
        "resource_group": source["resource_group"],
        "public_url": source["public_url"],
        "release": json.loads(json.dumps(source["release"], sort_keys=True)),
        "no_ai": True,
        "control_sha256": control_sha256,
        "commands": ordered_commands,
        "execution_order": list(RESUME_STAGES),
        "retry_limits": {"read": 1, "deploy": 0, "paid_provider": 0},
        "allowed_operations": [
            "azure_read_preflight",
            "registry_digest_readback",
            "phase1_receipt_revalidation",
            "deploy_digest",
            "hosted_verify",
            "rollback_rehearsal",
        ],
        "stop_conditions": [
            "receipt_or_source_changed",
            "phase1_fence_changed",
            "digest_or_migration_changed",
            "secret_boundary_failed",
            "hosted_verification_failed",
        ],
    }


def write_resume_authority(path: Path, authority: dict[str, object]) -> str:
    """Write a receipt-resume authority once, with owner-only permissions."""

    payload = (
        "# NEWCaostone Phase 1 Receipt Resume Authorization\n\n```json\n"
        + json.dumps(authority, ensure_ascii=True, indent=2, sort_keys=True)
        + "\n```\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ResumeAuthorityInvalid("resume_output_mode_invalid")
    return hashlib.sha256(payload).hexdigest()


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-authorization", required=True, type=Path)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--source-reference", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--receipt-reference", required=True)
    parser.add_argument("--phase1-receipt-script", required=True, type=Path)
    parser.add_argument("--resume-generator-script", required=True, type=Path)
    parser.add_argument("--resume-runner", required=True, type=Path)
    parser.add_argument("--issued-at", required=True)
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args(arguments)
    try:
        authority = generate_resume_authority(
            source_path=options.source_authorization,
            source_sha256=options.source_sha256,
            source_reference=options.source_reference,
            receipt_path=options.receipt,
            receipt_sha256=options.receipt_sha256,
            receipt_reference=options.receipt_reference,
            control_paths={
                "phase1_receipt_sha256": options.phase1_receipt_script,
                "resume_generator_sha256": options.resume_generator_script,
                "resume_runner_sha256": options.resume_runner,
            },
            issued_at=_timestamp(options.issued_at, "resume_issue_time_invalid"),
        )
        digest = write_resume_authority(options.output, authority)
    except (OSError, ResumeAuthorityInvalid):
        print("resume_authorization=invalid")
        return 1
    print("resume_authorization=ok")
    print(f"output={options.output}")
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
