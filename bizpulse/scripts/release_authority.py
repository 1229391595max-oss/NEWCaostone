"""Typed current-release authority and document drift contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import tempfile
from typing import Callable, Mapping


CURRENT_AUTHORITY_SCHEMA = "bizpulse.current-authority.v1"
DOCUMENT_POLICY_SCHEMA = "bizpulse.authority-document-policy.v1"
CURRENT_START = "<!-- authority:current:start -->"
CURRENT_END = "<!-- authority:current:end -->"
HISTORY_START = "<!-- authority:history:start -->"
HISTORY_END = "<!-- authority:history:end -->"

_SHA = re.compile(r"(?<![0-9a-f])([0-9a-f]{40})(?![0-9a-f])")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_MIGRATION = re.compile(r"[0-9]{4}_[a-z0-9_]+")
_REVISION = re.compile(r"[a-z0-9][a-z0-9-]{2,127}")
_ACTIVE_HEADING = re.compile(
    r"^#{1,6}\s+.*\b(current|active|next|deployment|rollback)\b",
    re.IGNORECASE,
)
_ANY_HEADING = re.compile(r"^#{1,6}\s+")
_COMMAND_LANGUAGES = {"bash", "console", "sh", "shell", "zsh"}


class AuthorityInvalid(ValueError):
    """Raised when current authority cannot be trusted."""


@dataclass(frozen=True, slots=True)
class ObservedDeployment:
    ai_runtime_state: str
    attestation_git_sha: str
    candidate_git_sha: str
    database_migration_head: str
    image_digest: str
    revision: str


@dataclass(frozen=True, slots=True)
class AttestedRollback:
    candidate_attestation_path: str
    git_sha: str
    image_digest: str


@dataclass(frozen=True, slots=True)
class DevelopmentAuthority:
    ai_capability_state: str
    repository_migration_head: str


@dataclass(frozen=True, slots=True)
class Freshness:
    evidence_kind: str
    evidence_sha256: str
    expires_at: datetime
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class CurrentAuthority:
    attested_rollback: AttestedRollback
    development: DevelopmentAuthority
    freshness: Freshness
    observed_deployment: ObservedDeployment
    prepared_candidate: Mapping[str, object] | None
    schema_version: str = CURRENT_AUTHORITY_SCHEMA

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        freshness = payload["freshness"]
        assert isinstance(freshness, dict)
        freshness["observed_at"] = _render_time(self.freshness.observed_at)
        freshness["expires_at"] = _render_time(self.freshness.expires_at)
        return payload

    def with_development(
        self,
        *,
        repository_migration_head: str,
        ai_capability_state: str,
    ) -> CurrentAuthority:
        return replace(
            self,
            development=DevelopmentAuthority(
                ai_capability_state=ai_capability_state,
                repository_migration_head=repository_migration_head,
            ),
        )


@dataclass(frozen=True, slots=True)
class AuthorityViolation:
    path: str
    line: int
    field: str
    expected: str
    actual: str

    def render(self) -> str:
        return (
            f"authority_doc_drift:{self.path}:{self.line}:{self.field}:"
            f"expected={self.expected}:actual={self.actual}"
        )


def _require_keys(
    value: object,
    expected: set[str],
    *,
    context: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise AuthorityInvalid(f"authority_keys_invalid:{context}")
    return value


def _string(value: object, pattern: re.Pattern[str], *, field: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise AuthorityInvalid(f"authority_value_invalid:{field}")
    return value


def _sha(value: object, *, field: str) -> str:
    return _string(value, re.compile(r"[0-9a-f]{40}"), field=field)


def _digest(value: object, *, field: str) -> str:
    return _string(value, re.compile(r"sha256:[0-9a-f]{64}"), field=field)


def _parse_time(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise AuthorityInvalid(f"authority_time_invalid:{field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AuthorityInvalid(f"authority_time_invalid:{field}") from error
    if parsed.tzinfo is None:
        raise AuthorityInvalid(f"authority_time_invalid:{field}")
    return parsed.astimezone(UTC)


def _render_time(value: datetime) -> str:
    if value.tzinfo is None:
        raise AuthorityInvalid("authority_time_timezone_required")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_authority(payload: object) -> CurrentAuthority:
    root = _require_keys(
        payload,
        {
            "attested_rollback",
            "development",
            "freshness",
            "observed_deployment",
            "prepared_candidate",
            "schema_version",
        },
        context="root",
    )
    if root["schema_version"] != CURRENT_AUTHORITY_SCHEMA:
        raise AuthorityInvalid("authority_schema_invalid")

    observed = _require_keys(
        root["observed_deployment"],
        {
            "ai_runtime_state",
            "attestation_git_sha",
            "candidate_git_sha",
            "database_migration_head",
            "image_digest",
            "revision",
        },
        context="observed_deployment",
    )
    if observed["ai_runtime_state"] not in {"disabled", "enabled"}:
        raise AuthorityInvalid("authority_value_invalid:ai_runtime_state")
    observed_authority = ObservedDeployment(
        ai_runtime_state=str(observed["ai_runtime_state"]),
        attestation_git_sha=_sha(
            observed["attestation_git_sha"],
            field="observed_deployment.attestation_git_sha",
        ),
        candidate_git_sha=_sha(
            observed["candidate_git_sha"],
            field="observed_deployment.candidate_git_sha",
        ),
        database_migration_head=_string(
            observed["database_migration_head"],
            _MIGRATION,
            field="observed_deployment.database_migration_head",
        ),
        image_digest=_digest(
            observed["image_digest"],
            field="observed_deployment.image_digest",
        ),
        revision=_string(
            observed["revision"],
            _REVISION,
            field="observed_deployment.revision",
        ),
    )

    rollback = _require_keys(
        root["attested_rollback"],
        {"candidate_attestation_path", "git_sha", "image_digest"},
        context="attested_rollback",
    )
    rollback_path = rollback["candidate_attestation_path"]
    if (
        not isinstance(rollback_path, str)
        or re.fullmatch(
            r"release/attestations/[0-9a-f]{40}\.json",
            rollback_path,
        )
        is None
    ):
        raise AuthorityInvalid(
            "authority_value_invalid:attested_rollback.candidate_attestation_path"
        )
    rollback_authority = AttestedRollback(
        candidate_attestation_path=rollback_path,
        git_sha=_sha(rollback["git_sha"], field="attested_rollback.git_sha"),
        image_digest=_digest(
            rollback["image_digest"], field="attested_rollback.image_digest"
        ),
    )

    development = _require_keys(
        root["development"],
        {"ai_capability_state", "repository_migration_head"},
        context="development",
    )
    if development["ai_capability_state"] not in {
        "absent",
        "implemented",
    }:
        raise AuthorityInvalid("authority_value_invalid:ai_capability_state")
    development_authority = DevelopmentAuthority(
        ai_capability_state=str(development["ai_capability_state"]),
        repository_migration_head=_string(
            development["repository_migration_head"],
            _MIGRATION,
            field="development.repository_migration_head",
        ),
    )

    freshness = _require_keys(
        root["freshness"],
        {"evidence_kind", "evidence_sha256", "expires_at", "observed_at"},
        context="freshness",
    )
    if freshness["evidence_kind"] != "sanitized_azure_readback":
        raise AuthorityInvalid("authority_value_invalid:freshness.evidence_kind")
    freshness_authority = Freshness(
        evidence_kind="sanitized_azure_readback",
        evidence_sha256=_string(
            freshness["evidence_sha256"],
            _HEX_64,
            field="freshness.evidence_sha256",
        ),
        expires_at=_parse_time(freshness["expires_at"], field="freshness.expires_at"),
        observed_at=_parse_time(
            freshness["observed_at"], field="freshness.observed_at"
        ),
    )
    if freshness_authority.observed_at >= freshness_authority.expires_at:
        raise AuthorityInvalid("authority_freshness_window_invalid")

    prepared = root["prepared_candidate"]
    if prepared is not None and not isinstance(prepared, Mapping):
        raise AuthorityInvalid("authority_value_invalid:prepared_candidate")

    return CurrentAuthority(
        attested_rollback=rollback_authority,
        development=development_authority,
        freshness=freshness_authority,
        observed_deployment=observed_authority,
        prepared_candidate=prepared,
    )


def load_current_authority(
    path: Path,
    *,
    now: datetime | None = None,
    require_fresh_observation: bool = False,
) -> CurrentAuthority:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuthorityInvalid(f"authority_file_invalid:{path}") from error
    authority = _parse_authority(payload)
    if require_fresh_observation:
        checked_at = now or datetime.now(UTC)
        if checked_at.tzinfo is None:
            raise AuthorityInvalid("authority_time_timezone_required")
        if checked_at.astimezone(UTC) >= authority.freshness.expires_at:
            raise AuthorityInvalid(
                "authority_observation_stale:"
                f"{_render_time(authority.freshness.observed_at)}:"
                f"{_render_time(authority.freshness.expires_at)}"
            )
    return authority


def refresh_current_authority(
    observation: Mapping[str, object],
    attestations: Path | None,
    *,
    observed_at: datetime,
    expires_at: datetime,
    current_authority: CurrentAuthority | None = None,
    verified_provenance: Mapping[str, object] | None = None,
) -> dict[str, object]:
    observed = _require_keys(
        observation,
        {
            "ai_runtime_state",
            "attestation_git_sha",
            "candidate_git_sha",
            "database_migration_head",
            "evidence_kind",
            "evidence_sha256",
            "image_digest",
            "revision",
        },
        context="observation",
    )
    candidate = _sha(observed["candidate_git_sha"], field="candidate_git_sha")
    if (current_authority is None) != (verified_provenance is None):
        raise AuthorityInvalid("authority_observation_unbound")
    if verified_provenance is None:
        if attestations is None:
            raise AuthorityInvalid("authority_observation_unbound")
        attestation_path = attestations / f"{candidate}.json"
        try:
            attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AuthorityInvalid("authority_observation_unbound") from error
        if (
            not isinstance(attestation, Mapping)
            or attestation.get("candidate_git_sha") != candidate
            or attestation.get("migration_head")
            != observed["database_migration_head"]
            or attestation.get("image_input_sha256")
            != observed["evidence_sha256"]
        ):
            raise AuthorityInvalid("authority_observation_unbound")
        rollback_payload = {
            "candidate_attestation_path": f"release/attestations/{candidate}.json",
            "git_sha": candidate,
            "image_digest": observed["image_digest"],
        }
        prepared_payload = None
    else:
        assert current_authority is not None
        if set(verified_provenance) != {
            "attestation_git_sha",
            "candidate_git_sha",
            "image_digest",
            "revision",
        } or any(
            verified_provenance[field] != observed[field]
            for field in verified_provenance
        ):
            raise AuthorityInvalid("authority_observation_unbound")
        rollback_payload = asdict(current_authority.attested_rollback)
        prepared_payload = current_authority.prepared_candidate

    payload = {
        "attested_rollback": rollback_payload,
        "development": {
            "ai_capability_state": "implemented",
            "repository_migration_head": observed["database_migration_head"],
        },
        "freshness": {
            "evidence_kind": observed["evidence_kind"],
            "evidence_sha256": observed["evidence_sha256"],
            "expires_at": _render_time(expires_at),
            "observed_at": _render_time(observed_at),
        },
        "observed_deployment": {
            key: observed[key]
            for key in (
                "ai_runtime_state",
                "attestation_git_sha",
                "candidate_git_sha",
                "database_migration_head",
                "image_digest",
                "revision",
            )
        },
        "prepared_candidate": prepared_payload,
        "schema_version": CURRENT_AUTHORITY_SCHEMA,
    }
    _parse_authority(payload)
    return payload


def authority_block(authority: CurrentAuthority) -> str:
    observed = authority.observed_deployment
    rollback = authority.attested_rollback
    development = authority.development
    freshness = authority.freshness
    lines = (
        CURRENT_START,
        "Current deployed and development facts are generated from "
        "`bizpulse/release/current_authority.json`.",
        "",
        f"- Deployed candidate: `{observed.candidate_git_sha}`",
        f"- Deployed attestation: `{observed.attestation_git_sha}`",
        f"- Deployed image: `{observed.image_digest}`",
        f"- Deployed revision: `{observed.revision}`",
        f"- Hosted migration: `{observed.database_migration_head}`",
        f"- Hosted AI: `{observed.ai_runtime_state}`",
        f"- Attested rollback candidate: `{rollback.git_sha}`",
        f"- Attested rollback image: `{rollback.image_digest}`",
        f"- Repository migration: `{development.repository_migration_head}`",
        f"- Repository AI capability: `{development.ai_capability_state}`",
        f"- Observation: `{_render_time(freshness.observed_at)}`",
        f"- Observation expires: `{_render_time(freshness.expires_at)}`",
        "- This block grants no Azure, registry, secret, paid-AI, push, PR, CI, "
        "or deployment authority.",
        CURRENT_END,
    )
    return "\n".join(lines)


def _policy_documents(policy: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    root = _require_keys(
        policy,
        {"documents", "schema_version"},
        context="document_policy",
    )
    if root["schema_version"] != DOCUMENT_POLICY_SCHEMA:
        raise AuthorityInvalid("authority_document_policy_schema_invalid")
    documents = root["documents"]
    if not isinstance(documents, list):
        raise AuthorityInvalid("authority_document_policy_invalid")
    parsed: list[Mapping[str, object]] = []
    for index, item in enumerate(documents):
        if not isinstance(item, Mapping) or set(item) not in (
            {"path"},
            {"path", "require_current_block"},
        ):
            raise AuthorityInvalid(f"authority_document_policy_invalid:{index}")
        logical_path = Path(str(item["path"]))
        if (
            not isinstance(item["path"], str)
            or logical_path.is_absolute()
            or "." in logical_path.parts
            or ".." in logical_path.parts
        ):
            raise AuthorityInvalid(f"authority_document_policy_invalid:{index}")
        parsed.append(item)
    return tuple(parsed)


def load_document_policy(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuthorityInvalid(f"authority_document_policy_invalid:{path}") from error
    if not isinstance(payload, Mapping):
        raise AuthorityInvalid("authority_document_policy_invalid")
    _policy_documents(payload)
    return payload


def _replace_or_insert_block(source: str, block: str) -> str:
    starts = [match.start() for match in re.finditer(re.escape(CURRENT_START), source)]
    ends = [match.end() for match in re.finditer(re.escape(CURRENT_END), source)]
    if len(starts) > 1 or len(ends) > 1 or len(starts) != len(ends):
        raise AuthorityInvalid("authority_current_block_invalid")
    if starts:
        return source[: starts[0]] + block + source[ends[0] :]
    lines = source.splitlines()
    if lines and lines[0].startswith("# "):
        remainder = "\n".join(lines[1:]).lstrip("\n")
        return lines[0] + "\n\n" + block + "\n\n" + remainder + "\n"
    return block + "\n\n" + source


def render_authority_blocks(
    authority: CurrentAuthority,
    policy: Mapping[str, object],
    repository_root: Path,
) -> tuple[Path, ...]:
    block = authority_block(authority)
    written: list[Path] = []
    for document in _policy_documents(policy):
        path = repository_root / str(document["path"])
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as error:
            raise AuthorityInvalid(f"authority_document_missing:{document['path']}") from error
        updated = _replace_or_insert_block(source, block)
        if updated != source:
            path.write_text(updated, encoding="utf-8")
        written.append(path)
    return tuple(written)


def _authority_bytes(authority: CurrentAuthority) -> bytes:
    return (
        json.dumps(authority.to_payload(), indent=2, sort_keys=True) + "\n"
    ).encode()


def render_authority_document_bytes(
    authority: CurrentAuthority,
    policy: Mapping[str, object],
    repository_root: Path,
) -> dict[Path, bytes]:
    """Render every policy document without mutating a target."""

    block = authority_block(authority)
    rendered: dict[Path, bytes] = {}
    for document in _policy_documents(policy):
        path = repository_root / str(document["path"])
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as error:
            raise AuthorityInvalid(
                f"authority_document_missing:{document['path']}"
            ) from error
        rendered[path] = _replace_or_insert_block(source, block).encode()
    return rendered


def _stage_regular_file(path: Path, payload: bytes, *, mode: int) -> Path:
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    staged = Path(raw)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return staged
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        staged.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _set_regular_file_mode(path: Path, mode: int) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise AuthorityInvalid("authority_bundle_target_invalid")
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        if (
            (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or stat.S_IMODE(after.st_mode) != mode
        ):
            raise AuthorityInvalid("authority_bundle_target_invalid")
    finally:
        os.close(descriptor)


def apply_authority_bundle_atomic(
    *,
    authority_path: Path,
    authority: CurrentAuthority,
    policy: Mapping[str, object],
    repository_root: Path,
    expected_sha256: Mapping[Path, str] | None = None,
    replacer: Callable[[Path, Path], None] = os.replace,
) -> tuple[Path, ...]:
    """Replace the authority/document bundle or restore every original target."""

    rendered = {
        authority_path: _authority_bytes(authority),
        **render_authority_document_bytes(authority, policy, repository_root),
    }
    originals: dict[Path, tuple[bytes, int]] = {}
    staged: dict[Path, Path] = {}
    replaced: list[Path] = []
    try:
        for path in rendered:
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
                raise AuthorityInvalid("authority_bundle_target_invalid")
            encoded = path.read_bytes()
            expected = None if expected_sha256 is None else expected_sha256.get(path)
            if expected is not None and hashlib.sha256(encoded).hexdigest() != expected:
                raise AuthorityInvalid("authority_bundle_source_drift")
            originals[path] = (encoded, stat.S_IMODE(metadata.st_mode))
        if expected_sha256 is not None and set(expected_sha256) != set(rendered):
            raise AuthorityInvalid("authority_bundle_source_drift")
        for path, payload in rendered.items():
            staged[path] = _stage_regular_file(
                path,
                payload,
                mode=0o600,
            )
        for path in rendered:
            if expected_sha256 is not None:
                current = path.read_bytes()
                if hashlib.sha256(current).hexdigest() != expected_sha256[path]:
                    raise AuthorityInvalid("authority_bundle_source_drift")
            replacer(staged[path], path)
            replaced.append(path)
            _set_regular_file_mode(path, originals[path][1])
            _fsync_directory(path.parent)
        loaded = load_current_authority(authority_path)
        if loaded != authority or check_authority_documents(
            authority,
            policy,
            repository_root,
        ):
            raise AuthorityInvalid("authority_bundle_post_write_invalid")
        return tuple(rendered)
    except AuthorityInvalid:
        failure: Exception | None = None
        for path in reversed(replaced):
            try:
                payload, mode = originals[path]
                rollback = _stage_regular_file(path, payload, mode=0o600)
                replacer(rollback, path)
                _set_regular_file_mode(path, mode)
                _fsync_directory(path.parent)
            except Exception as error:  # pragma: no cover - catastrophic storage fault
                failure = error
        if failure is not None:
            raise AuthorityInvalid("authority_bundle_rollback_failed") from failure
        raise
    except Exception as error:
        failure: Exception | None = None
        for path in reversed(replaced):
            try:
                payload, mode = originals[path]
                rollback = _stage_regular_file(path, payload, mode=0o600)
                replacer(rollback, path)
                _set_regular_file_mode(path, mode)
                _fsync_directory(path.parent)
            except Exception as rollback_error:  # pragma: no cover
                failure = rollback_error
        if failure is not None:
            raise AuthorityInvalid("authority_bundle_rollback_failed") from failure
        raise AuthorityInvalid("authority_bundle_write_failed") from error
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)


def _literal_violation(
    *,
    authority: CurrentAuthority,
    path: str,
    line: int,
    value: str,
) -> AuthorityViolation | None:
    if value.startswith("sha256:"):
        allowed = {
            authority.observed_deployment.image_digest,
            authority.attested_rollback.image_digest,
        }
        if value in allowed:
            return None
        return AuthorityViolation(
            path,
            line,
            "observed_deployment.image_digest",
            authority.observed_deployment.image_digest,
            value,
        )
    allowed_sha = {
        authority.observed_deployment.candidate_git_sha,
        authority.observed_deployment.attestation_git_sha,
        authority.attested_rollback.git_sha,
    }
    if value in allowed_sha:
        return None
    return AuthorityViolation(
        path,
        line,
        "observed_deployment.candidate_git_sha",
        authority.observed_deployment.candidate_git_sha,
        value,
    )


def _scan_document_literals(
    authority: CurrentAuthority,
    *,
    path: str,
    source: str,
) -> tuple[AuthorityViolation, ...]:
    violations: list[AuthorityViolation] = []
    in_history = False
    in_current = False
    active_heading = False
    command_fence = False
    for number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped == CURRENT_START:
            in_current = True
            continue
        if stripped == CURRENT_END:
            in_current = False
            continue
        if stripped == HISTORY_START:
            in_history = True
            active_heading = False
            continue
        if stripped == HISTORY_END:
            in_history = False
            active_heading = False
            continue
        if stripped.startswith("```"):
            language = stripped[3:].strip().lower()
            if command_fence:
                command_fence = False
            else:
                command_fence = language in _COMMAND_LANGUAGES
            continue
        if _ANY_HEADING.match(line):
            active_heading = _ACTIVE_HEADING.match(line) is not None
        if in_history and not command_fence:
            continue
        if not in_current and not active_heading and not command_fence:
            continue
        for digest in _DIGEST.findall(line):
            violation = _literal_violation(
                authority=authority,
                path=path,
                line=number,
                value=digest,
            )
            if violation is not None:
                violations.append(violation)
        without_digests = _DIGEST.sub("", line)
        for sha in _SHA.findall(without_digests):
            violation = _literal_violation(
                authority=authority,
                path=path,
                line=number,
                value=sha,
            )
            if violation is not None:
                violations.append(violation)
    return tuple(violations)


def check_authority_documents(
    authority: CurrentAuthority,
    policy: Mapping[str, object],
    repository_root: Path,
) -> tuple[AuthorityViolation, ...]:
    expected_block = authority_block(authority)
    violations: list[AuthorityViolation] = []
    for document in _policy_documents(policy):
        relative = str(document["path"])
        path = repository_root / relative
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            violations.append(
                AuthorityViolation(relative, 1, "document", "present", "missing")
            )
            continue
        starts = source.count(CURRENT_START)
        ends = source.count(CURRENT_END)
        required = bool(document.get("require_current_block", False))
        if required and (starts != 1 or ends != 1):
            violations.append(
                AuthorityViolation(
                    relative,
                    1,
                    "authority.current_block",
                    "one",
                    f"start={starts},end={ends}",
                )
            )
        elif starts == 1 and ends == 1:
            actual = source[
                source.index(CURRENT_START) : source.index(CURRENT_END) + len(CURRENT_END)
            ]
            if actual != expected_block:
                line = source[: source.index(CURRENT_START)].count("\n") + 1
                violations.append(
                    AuthorityViolation(
                        relative,
                        line,
                        "authority.current_block",
                        "generated",
                        "drifted",
                    )
                )
        elif starts != ends or starts > 1:
            violations.append(
                AuthorityViolation(
                    relative,
                    1,
                    "authority.current_block",
                    "zero_or_one",
                    f"start={starts},end={ends}",
                )
            )
        violations.extend(
            _scan_document_literals(authority, path=relative, source=source)
        )
    return tuple(violations)


def write_authority(path: Path, authority: CurrentAuthority) -> None:
    path.write_text(
        json.dumps(
            authority.to_payload(),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
