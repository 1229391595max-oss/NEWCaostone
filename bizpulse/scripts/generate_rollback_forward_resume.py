"""Generate a narrow no-AI authority to forward one exact rollback revision."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import shlex
import stat
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import generate_phase1_receipt_resume as receipt_resume  # noqa: E402
from scripts.phase1_receipt import Phase1ReceiptInvalid, load_receipt  # noqa: E402

HEADER = "# NEWCaostone Rollback Forward Resume Authorization"
SOURCE_HEADER = "# NEWCaostone Phase 1 Receipt Resume Authorization"
LAUNCH_HEADER = "# NEWCaostone Launch Authorization"
SCHEMA = "newcaostone.rollback-forward-resume-authorization.v1"
STAGES = ("rollback_preflight", "registry_verify", "recover", "health")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
SHA1_PATTERN = re.compile(r"[0-9a-f]{40}")
UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9._/-]{1,255}")
NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]{1,62}[a-z0-9]")
REGISTRY_PATTERN = re.compile(r"[a-z0-9]{5,50}")
REPOSITORY_PATTERN = re.compile(r"[a-z0-9][a-z0-9._/-]{1,127}")
CONTROL_FIELDS = frozenset(
    {
        "azure_readback_sha256",
        "forward_generator_sha256",
        "forward_runner_sha256",
    }
)
SOURCE_FIELDS = frozenset(
    {
        "schema_version",
        "authorization_id",
        "issued_at",
        "expires_at",
        "source_launch_authorization_reference",
        "source_launch_authorization_sha256",
        "source_authorization_id",
        "receipt_reference",
        "receipt_sha256",
        "receipt_id",
        "receipt_anchor_at",
        "receipt_fence_observed_at",
        "subscription_id",
        "resource_group",
        "public_url",
        "release",
        "no_ai",
        "control_sha256",
        "commands",
        "execution_order",
        "retry_limits",
        "allowed_operations",
        "stop_conditions",
    }
)
AUTHORITY_FIELDS = frozenset(
    {
        "schema_version",
        "authorization_id",
        "issued_at",
        "expires_at",
        "source_resume_authorization_reference",
        "source_resume_authorization_sha256",
        "source_resume_authorization_id",
        "source_launch_authorization_reference",
        "source_launch_authorization_sha256",
        "source_authorization_id",
        "receipt_reference",
        "receipt_sha256",
        "receipt_id",
        "subscription_id",
        "resource_group",
        "public_url",
        "release",
        "candidate_image",
        "rollback_image",
        "rollback_revision",
        "no_ai",
        "control_sha256",
        "commands",
        "execution_order",
        "retry_limits",
        "allowed_operations",
        "stop_conditions",
    }
)
RETRY_LIMITS = {"read": 1, "deploy": 0, "paid_provider": 0}
ALLOWED_OPERATIONS = [
    "azure_read_preflight",
    "registry_digest_readback",
    "deploy_digest",
    "hosted_verify",
]
STOP_CONDITIONS = [
    "rollback_state_changed",
    "source_receipt_or_digest_changed",
    "revision_not_ready",
    "pinned_viewer_authority_changed",
    "hosted_verification_failed",
]


class ForwardResumeInvalid(ValueError):
    """The rollback-forward authority is not exactly proved."""


@dataclass(frozen=True)
class _SourceContext:
    source_resume: dict[str, object]
    source_resume_reference: str
    source_resume_sha256: str
    source_launch: dict[str, object]
    receipt: dict[str, object]
    app_name: str
    candidate_image: str
    rollback_image: str
    rollback_revision: str


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("forward_resume_duplicate_json_key")
        result[key] = value
    return result


def _mapping(value: object, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ForwardResumeInvalid(code)
    return value


def _string(value: object, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise ForwardResumeInvalid(code)
    return value


def _timestamp(value: object, code: str) -> datetime:
    text = _string(value, code)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ForwardResumeInvalid(code) from error
    if parsed.tzinfo is None:
        raise ForwardResumeInvalid(code)
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    normalized = value.astimezone(UTC)
    timespec = "microseconds" if normalized.microsecond else "seconds"
    return normalized.isoformat(timespec=timespec).replace("+00:00", "Z")


def _safe_reference(value: object, code: str) -> str:
    text = _string(value, code)
    if (
        REFERENCE_PATTERN.fullmatch(text) is None
        or "\\" in text
        or any(character in text for character in ("\x00", "\r", "\n"))
    ):
        raise ForwardResumeInvalid(code)
    logical = PurePosixPath(text)
    if logical.is_absolute() or ".." in logical.parts or "." in logical.parts:
        raise ForwardResumeInvalid(code)
    return text


def _reference_path(project_root: Path, reference: str, code: str) -> Path:
    safe = _safe_reference(reference, code)
    resolved = (project_root / safe).resolve()
    if not resolved.is_relative_to(project_root.resolve()):
        raise ForwardResumeInvalid(code)
    return resolved


def _require_sha256(value: object, code: str) -> str:
    text = _string(value, code)
    if SHA256_PATTERN.fullmatch(text) is None:
        raise ForwardResumeInvalid(code)
    return text


def _require_digest(value: object, code: str) -> str:
    text = _string(value, code)
    if not text.startswith("sha256:") or SHA256_PATTERN.fullmatch(text[7:]) is None:
        raise ForwardResumeInvalid(code)
    return text


def _file_sha256(path: Path, code: str) -> str:
    try:
        if not path.is_file() or path.stat().st_size > 2_000_000:
            raise ForwardResumeInvalid(code)
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ForwardResumeInvalid(code) from error


def _document(
    path: Path,
    *,
    expected_header: str,
    expected_sha256: str,
    code: str,
) -> dict[str, object]:
    _require_sha256(expected_sha256, code)
    try:
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise ForwardResumeInvalid(code)
        source = path.read_bytes()
        decoded = source.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ForwardResumeInvalid(code) from error
    if len(source) > 524_288 or not hmac.compare_digest(
        hashlib.sha256(source).hexdigest(), expected_sha256
    ):
        raise ForwardResumeInvalid(code)
    match = re.fullmatch(
        re.escape(expected_header) + r"\n\n```json\n(?P<payload>.*)\n```\n?",
        decoded,
        flags=re.DOTALL,
    )
    if match is None:
        raise ForwardResumeInvalid(code)
    try:
        payload = json.loads(
            match.group("payload"), object_pairs_hook=_unique_object
        )
    except (ValueError, json.JSONDecodeError) as error:
        raise ForwardResumeInvalid(code) from error
    if not isinstance(payload, dict):
        raise ForwardResumeInvalid(code)
    return payload


def _image(registry: str, repository: str, digest: str) -> str:
    if (
        REGISTRY_PATTERN.fullmatch(registry) is None
        or REPOSITORY_PATTERN.fullmatch(repository) is None
    ):
        raise ForwardResumeInvalid("forward_resume_source_invalid")
    return f"{registry}.azurecr.io/{repository}@{digest}"


def _command(tokens: list[str]) -> str:
    return shlex.join(tokens)


def _expected_source_commands(
    source_launch: dict[str, object],
    *,
    app_name: str,
    candidate_image: str,
    rollback_image: str,
) -> dict[str, list[str]]:
    release = _mapping(source_launch.get("release"), "forward_resume_source_invalid")
    generated_names = _mapping(
        source_launch.get("generated_names"), "forward_resume_source_invalid"
    )
    subscription_id = _string(
        source_launch.get("subscription_id"), "forward_resume_source_invalid"
    )
    resource_group = _string(
        source_launch.get("resource_group"), "forward_resume_source_invalid"
    )
    public_url = _string(
        source_launch.get("public_url"), "forward_resume_source_invalid"
    )
    authorization_id = _string(
        source_launch.get("authorization_id"), "forward_resume_source_invalid"
    )
    if UUID_PATTERN.fullmatch(authorization_id) is None:
        raise ForwardResumeInvalid("forward_resume_source_invalid")
    registry = _string(
        generated_names.get("registry_name"), "forward_resume_source_invalid"
    )
    repository = _string(
        generated_names.get("image_repository"), "forward_resume_source_invalid"
    )
    current_git = _string(release.get("git_sha"), "forward_resume_source_invalid")
    rollback_git = _string(
        release.get("rollback_git_sha"), "forward_resume_source_invalid"
    )
    if SHA1_PATTERN.fullmatch(current_git) is None or SHA1_PATTERN.fullmatch(rollback_git) is None:
        raise ForwardResumeInvalid("forward_resume_source_invalid")
    current_input = _require_sha256(
        release.get("image_input_sha256"), "forward_resume_source_invalid"
    )
    rollback_input = _require_sha256(
        release.get("rollback_image_input_sha256"), "forward_resume_source_invalid"
    )
    return {
        "registry_verify": [
            _command(
                [
                    ".venv/bin/python",
                    "scripts/verify_registry_image.py",
                    "--subscription",
                    subscription_id,
                    "--registry",
                    registry,
                    "--repository",
                    repository,
                    "--source-git-sha",
                    current_git,
                    "--expected-digest",
                    candidate_image.rsplit("@", 1)[1],
                    "--image-input-sha256",
                    current_input,
                ]
            ),
            _command(
                [
                    ".venv/bin/python",
                    "scripts/verify_registry_image.py",
                    "--subscription",
                    subscription_id,
                    "--registry",
                    registry,
                    "--repository",
                    repository,
                    "--source-git-sha",
                    rollback_git,
                    "--expected-digest",
                    rollback_image.rsplit("@", 1)[1],
                    "--image-input-sha256",
                    rollback_input,
                ]
            ),
        ],
        "rollback": [
            _command(
                [
                    ".venv/bin/python",
                    "scripts/run_azure_readback.py",
                    "--subscription",
                    subscription_id,
                    "--resource-group",
                    resource_group,
                    "--app",
                    app_name,
                    "--current-image",
                    candidate_image,
                    "--authorization-id",
                    authorization_id,
                    "--ai-enabled",
                    "false",
                    "--operation",
                    "rollback",
                    "--rollback-image",
                    rollback_image,
                ]
            )
        ],
        "health": [
            _command(
                [
                    ".venv/bin/python",
                    "scripts/run_hosted_check.py",
                    "--subscription",
                    subscription_id,
                    "--resource-group",
                    resource_group,
                    "--app",
                    app_name,
                    "--image",
                    candidate_image,
                    "--expected-url",
                    public_url,
                    "--check",
                    "health",
                ]
            )
        ],
    }


def _load_source_context(
    *,
    source_resume_path: Path,
    source_resume_sha256: str,
    source_resume_reference: str,
    project_root: Path,
) -> _SourceContext:
    source_resume = _document(
        source_resume_path,
        expected_header=SOURCE_HEADER,
        expected_sha256=source_resume_sha256,
        code="forward_resume_source_invalid",
    )
    if (
        set(source_resume) != SOURCE_FIELDS
        or source_resume.get("schema_version")
        != "newcaostone.phase1-receipt-resume-authorization.v1"
        or source_resume.get("no_ai") is not True
        or source_resume.get("execution_order") != list(receipt_resume.RESUME_STAGES)
        or source_resume.get("retry_limits")
        != {"read": 1, "deploy": 0, "paid_provider": 0}
    ):
        raise ForwardResumeInvalid("forward_resume_source_invalid")
    source_resume_id = _string(
        source_resume.get("authorization_id"), "forward_resume_source_invalid"
    )
    if UUID_PATTERN.fullmatch(source_resume_id) is None:
        raise ForwardResumeInvalid("forward_resume_source_invalid")
    issued = _timestamp(source_resume.get("issued_at"), "forward_resume_source_invalid")
    expires = _timestamp(source_resume.get("expires_at"), "forward_resume_source_invalid")
    if expires - issued != timedelta(hours=24):
        raise ForwardResumeInvalid("forward_resume_source_invalid")

    original_reference = _safe_reference(
        source_resume.get("source_launch_authorization_reference"),
        "forward_resume_source_invalid",
    )
    receipt_reference = _safe_reference(
        source_resume.get("receipt_reference"), "forward_resume_source_invalid"
    )
    original_sha256 = _require_sha256(
        source_resume.get("source_launch_authorization_sha256"),
        "forward_resume_source_invalid",
    )
    receipt_sha256 = _require_sha256(
        source_resume.get("receipt_sha256"), "forward_resume_source_invalid"
    )
    try:
        source_launch = _document(
            _reference_path(
                project_root, original_reference, "forward_resume_source_invalid"
            ),
            expected_header=LAUNCH_HEADER,
            expected_sha256=original_sha256,
            code="forward_resume_source_invalid",
        )
        receipt_path = _reference_path(
            project_root, receipt_reference, "forward_resume_source_invalid"
        )
        if not hmac.compare_digest(
            _file_sha256(receipt_path, "forward_resume_source_invalid"), receipt_sha256
        ):
            raise ForwardResumeInvalid("forward_resume_source_invalid")
        receipt = load_receipt(receipt_path)
        receipt_resume._require_no_ai(source_launch)
    except (Phase1ReceiptInvalid, receipt_resume.ResumeAuthorityInvalid) as error:
        raise ForwardResumeInvalid("forward_resume_source_invalid") from error

    source_launch_id = _string(
        source_launch.get("authorization_id"), "forward_resume_source_invalid"
    )
    source_launch_schema = source_launch.get("schema_version")
    if (
        source_launch_schema != "newcaostone.launch-authorization.v4"
        or UUID_PATTERN.fullmatch(source_launch_id) is None
        or source_launch.get("public_url_source") != "exact"
        or not isinstance(source_launch.get("generated_names"), dict)
        or not isinstance(source_launch.get("release"), dict)
        or not isinstance(source_launch.get("commands"), dict)
        or source_resume.get("source_authorization_id") != source_launch_id
        or source_resume.get("receipt_id") != receipt.get("receipt_id")
        or source_resume.get("receipt_sha256") != receipt_sha256
        or source_resume.get("release") != source_launch.get("release")
        or source_resume.get("release") != receipt.get("release")
        or source_resume.get("subscription_id") != source_launch.get("subscription_id")
        or source_resume.get("resource_group") != source_launch.get("resource_group")
        or source_resume.get("public_url") != source_launch.get("public_url")
    ):
        raise ForwardResumeInvalid("forward_resume_source_invalid")

    generated_names = _mapping(
        source_launch.get("generated_names"), "forward_resume_source_invalid"
    )
    release = _mapping(source_launch.get("release"), "forward_resume_source_invalid")
    app_name = _string(
        generated_names.get("container_app"), "forward_resume_source_invalid"
    )
    registry = _string(
        generated_names.get("registry_name"), "forward_resume_source_invalid"
    )
    repository = _string(
        generated_names.get("image_repository"), "forward_resume_source_invalid"
    )
    if NAME_PATTERN.fullmatch(app_name) is None:
        raise ForwardResumeInvalid("forward_resume_source_invalid")
    candidate_image = _image(
        registry,
        repository,
        _require_digest(release.get("image_digest"), "forward_resume_source_invalid"),
    )
    rollback_image = _image(
        registry,
        repository,
        _require_digest(
            release.get("rollback_image_digest"), "forward_resume_source_invalid"
        ),
    )
    source_authorization_id = _string(
        source_launch.get("authorization_id"), "forward_resume_source_invalid"
    )
    if UUID_PATTERN.fullmatch(source_authorization_id) is None:
        raise ForwardResumeInvalid("forward_resume_source_invalid")
    rollback_revision = (
        f"{app_name}--rollback-{source_authorization_id.replace('-', '')[:8]}-"
        f"{rollback_image.rsplit('@sha256:', 1)[1][:7]}"
    )
    commands = _mapping(source_resume.get("commands"), "forward_resume_source_invalid")
    expected = _expected_source_commands(
        source_launch,
        app_name=app_name,
        candidate_image=candidate_image,
        rollback_image=rollback_image,
    )
    if (
        set(commands) != set(receipt_resume.RESUME_STAGES)
        or any(commands.get(stage) != rows for stage, rows in expected.items())
    ):
        raise ForwardResumeInvalid("forward_resume_source_invalid")
    return _SourceContext(
        source_resume=source_resume,
        source_resume_reference=_safe_reference(
            source_resume_reference, "forward_resume_reference_invalid"
        ),
        source_resume_sha256=source_resume_sha256,
        source_launch=source_launch,
        receipt=receipt,
        app_name=app_name,
        candidate_image=candidate_image,
        rollback_image=rollback_image,
        rollback_revision=rollback_revision,
    )


def _control_hashes(control_paths: dict[str, Path]) -> dict[str, str]:
    if set(control_paths) != CONTROL_FIELDS:
        raise ForwardResumeInvalid("forward_resume_control_invalid")
    return {
        field: _file_sha256(control_paths[field], "forward_resume_control_invalid")
        for field in sorted(CONTROL_FIELDS)
    }


def _commands(context: _SourceContext) -> dict[str, list[str]]:
    source_launch = context.source_launch
    subscription_id = _string(
        source_launch.get("subscription_id"), "forward_resume_source_invalid"
    )
    resource_group = _string(
        source_launch.get("resource_group"), "forward_resume_source_invalid"
    )
    public_url = _string(
        source_launch.get("public_url"), "forward_resume_source_invalid"
    )
    authorization_id = _string(
        source_launch.get("authorization_id"), "forward_resume_source_invalid"
    )
    candidate_digest = context.candidate_image.rsplit("@sha256:", 1)[1]
    recover_suffix = (
        f"recover-{authorization_id.replace('-', '')[:8]}-{candidate_digest[:7]}"
    )
    expected = _expected_source_commands(
        source_launch,
        app_name=context.app_name,
        candidate_image=context.candidate_image,
        rollback_image=context.rollback_image,
    )
    return {
        "rollback_preflight": [
            _command(
                [
                    ".venv/bin/python",
                    "scripts/run_hosted_check.py",
                    "--subscription",
                    subscription_id,
                    "--resource-group",
                    resource_group,
                    "--app",
                    context.app_name,
                    "--image",
                    context.rollback_image,
                    "--expected-url",
                    public_url,
                    "--check",
                    "health",
                    "--expected-revision-suffix",
                    context.rollback_revision.rsplit("--", 1)[1],
                ]
            )
        ],
        "registry_verify": expected["registry_verify"],
        "recover": [
            _command(
                [
                    ".venv/bin/python",
                    "scripts/run_azure_readback.py",
                    "--subscription",
                    subscription_id,
                    "--resource-group",
                    resource_group,
                    "--app",
                    context.app_name,
                    "--current-image",
                    context.candidate_image,
                    "--authorization-id",
                    authorization_id,
                    "--ai-enabled",
                    "false",
                    "--operation",
                    "recover",
                    "--rollback-image",
                    context.rollback_image,
                ]
            )
        ],
        "health": [
            _command(
                [
                    ".venv/bin/python",
                    "scripts/run_hosted_check.py",
                    "--subscription",
                    subscription_id,
                    "--resource-group",
                    resource_group,
                    "--app",
                    context.app_name,
                    "--image",
                    context.candidate_image,
                    "--expected-url",
                    public_url,
                    "--check",
                    "health",
                    "--expected-revision-suffix",
                    recover_suffix,
                ]
            )
        ],
    }


def _build_authority(
    *,
    context: _SourceContext,
    rollback_revision: str,
    control_sha256: dict[str, str],
    authorization_id: str,
    issued_at: datetime,
) -> dict[str, object]:
    if (
        rollback_revision != context.rollback_revision
        or UUID_PATTERN.fullmatch(authorization_id) is None
        or issued_at.tzinfo is None
        or set(control_sha256) != CONTROL_FIELDS
    ):
        raise ForwardResumeInvalid("forward_resume_identity_invalid")
    source = context.source_launch
    return {
        "schema_version": SCHEMA,
        "authorization_id": authorization_id,
        "issued_at": _utc_text(issued_at),
        "expires_at": _utc_text(issued_at + timedelta(hours=24)),
        "source_resume_authorization_reference": context.source_resume_reference,
        "source_resume_authorization_sha256": context.source_resume_sha256,
        "source_resume_authorization_id": context.source_resume["authorization_id"],
        "source_launch_authorization_reference": context.source_resume[
            "source_launch_authorization_reference"
        ],
        "source_launch_authorization_sha256": context.source_resume[
            "source_launch_authorization_sha256"
        ],
        "source_authorization_id": source["authorization_id"],
        "receipt_reference": context.source_resume["receipt_reference"],
        "receipt_sha256": context.source_resume["receipt_sha256"],
        "receipt_id": context.source_resume["receipt_id"],
        "subscription_id": source["subscription_id"],
        "resource_group": source["resource_group"],
        "public_url": source["public_url"],
        "release": json.loads(json.dumps(source["release"], sort_keys=True)),
        "candidate_image": context.candidate_image,
        "rollback_image": context.rollback_image,
        "rollback_revision": rollback_revision,
        "no_ai": True,
        "control_sha256": control_sha256,
        "commands": _commands(context),
        "execution_order": list(STAGES),
        "retry_limits": RETRY_LIMITS,
        "allowed_operations": ALLOWED_OPERATIONS,
        "stop_conditions": STOP_CONDITIONS,
    }


def generate_forward_resume(
    *,
    source_resume_path: Path,
    source_resume_sha256: str,
    source_resume_reference: str,
    rollback_revision: str,
    control_paths: dict[str, Path],
    issued_at: datetime,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, object]:
    """Build one exact no-AI forward-only recovery authority."""

    context = _load_source_context(
        source_resume_path=source_resume_path,
        source_resume_sha256=source_resume_sha256,
        source_resume_reference=source_resume_reference,
        project_root=project_root,
    )
    return _build_authority(
        context=context,
        rollback_revision=rollback_revision,
        control_sha256=_control_hashes(control_paths),
        authorization_id=str(uuid4()),
        issued_at=issued_at.astimezone(UTC),
    )


def write_forward_resume(path: Path, authority: dict[str, object]) -> str:
    """Write a canonical owner-only forward authority without overwriting it."""

    payload = (
        HEADER
        + "\n\n```json\n"
        + json.dumps(authority, ensure_ascii=True, indent=2, sort_keys=True)
        + "\n```\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ForwardResumeInvalid("forward_resume_output_mode_invalid")
    return hashlib.sha256(payload).hexdigest()


def validate_forward_resume(
    *,
    authorization_path: Path,
    approved_sha256: str,
    project_root: Path = PROJECT_ROOT,
    control_paths: dict[str, Path] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Validate the exact authority again before every recovery stage."""

    authority = _document(
        authorization_path,
        expected_header=HEADER,
        expected_sha256=approved_sha256,
        code="forward_approval_hash_mismatch",
    )
    if set(authority) != AUTHORITY_FIELDS:
        raise ForwardResumeInvalid("forward_resume_fields_invalid")
    issued = _timestamp(authority.get("issued_at"), "forward_resume_identity_invalid")
    expires = _timestamp(authority.get("expires_at"), "forward_resume_identity_invalid")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    authorization_id = _string(
        authority.get("authorization_id"), "forward_resume_identity_invalid"
    )
    if (
        authority.get("schema_version") != SCHEMA
        or UUID_PATTERN.fullmatch(authorization_id) is None
        or authority.get("no_ai") is not True
        or authority.get("execution_order") != list(STAGES)
        or authority.get("retry_limits") != RETRY_LIMITS
        or authority.get("allowed_operations") != ALLOWED_OPERATIONS
        or authority.get("stop_conditions") != STOP_CONDITIONS
        or expires - issued != timedelta(hours=24)
        or current < issued
        or current >= expires
    ):
        raise ForwardResumeInvalid("forward_resume_identity_invalid")
    paths = control_paths or {
        "azure_readback_sha256": project_root / "scripts/run_azure_readback.py",
        "forward_generator_sha256": project_root
        / "scripts/generate_rollback_forward_resume.py",
        "forward_runner_sha256": project_root
        / ".tmp/run_approved_rollback_forward_resume.py",
    }
    controls = authority.get("control_sha256")
    if controls != _control_hashes(paths):
        raise ForwardResumeInvalid("forward_resume_control_hash_invalid")
    source_reference = _safe_reference(
        authority.get("source_resume_authorization_reference"),
        "forward_resume_reference_invalid",
    )
    context = _load_source_context(
        source_resume_path=_reference_path(
            project_root, source_reference, "forward_resume_reference_invalid"
        ),
        source_resume_sha256=_require_sha256(
            authority.get("source_resume_authorization_sha256"),
            "forward_resume_identity_invalid",
        ),
        source_resume_reference=source_reference,
        project_root=project_root,
    )
    expected = _build_authority(
        context=context,
        rollback_revision=_string(
            authority.get("rollback_revision"), "forward_resume_identity_invalid"
        ),
        control_sha256=_control_hashes(paths),
        authorization_id=authorization_id,
        issued_at=issued,
    )
    if authority != expected:
        raise ForwardResumeInvalid("forward_resume_authority_changed")
    return authority


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-resume-authorization", required=True, type=Path)
    parser.add_argument("--source-resume-sha256", required=True)
    parser.add_argument("--source-resume-reference", required=True)
    parser.add_argument("--rollback-revision", required=True)
    parser.add_argument("--azure-readback-script", required=True, type=Path)
    parser.add_argument("--forward-generator-script", required=True, type=Path)
    parser.add_argument("--forward-runner", required=True, type=Path)
    parser.add_argument("--issued-at", required=True)
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args(arguments)
    try:
        authority = generate_forward_resume(
            source_resume_path=options.source_resume_authorization,
            source_resume_sha256=options.source_resume_sha256,
            source_resume_reference=options.source_resume_reference,
            rollback_revision=options.rollback_revision,
            control_paths={
                "azure_readback_sha256": options.azure_readback_script,
                "forward_generator_sha256": options.forward_generator_script,
                "forward_runner_sha256": options.forward_runner,
            },
            issued_at=_timestamp(options.issued_at, "forward_resume_identity_invalid"),
        )
        digest = write_forward_resume(options.output, authority)
    except (OSError, ForwardResumeInvalid):
        print("rollback_forward_authorization=invalid")
        return 1
    print("rollback_forward_authorization=ok")
    print(f"output={options.output}")
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
