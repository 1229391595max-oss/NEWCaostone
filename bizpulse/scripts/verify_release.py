"""Fail-closed local release-candidate verification for NEWCaostone."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
MAX_CANDIDATE_FILE_BYTES = 5 * 1024 * 1024
REQUIRED_TEST_CHECKS = frozenset(
    {
        "browser",
        "compileall",
        "diff_check",
        "python",
        "frontend",
        "exact_15_restart_rollback",
        "ruff",
        "static_release_boundaries",
    }
)
SAFE_TEST_TOKENS = frozenset(
    {
        "sk-example-not-real-but-sensitive",
        "sk-proj-secretvalue12345",
        "sk-proj-abcdefghijklmnop",
        "AKIAIOSFODNN7EXAMPLE",
        "postgresql://operator:secret@db.example",
        "postgresql://operator:secret@db",
        "postgresql://operator:password@db",
    }
)
SECRET_PATTERNS = (
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    ("azure_account_key", re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}")),
    ("aws_access_key", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    (
        "openai_key",
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b"),
    ),
    (
        "credential_url",
        re.compile(
            r"postgres(?:ql)?://[^\s/:@]+:[^\s/@]+@[A-Za-z0-9.-]+",
            re.IGNORECASE,
        ),
    ),
)
PROHIBITED_SUFFIXES = frozenset(
    {".key", ".pem", ".p12", ".pfx", ".crt", ".cer"}
)
SOURCE_ARTIFACT_SUFFIXES = frozenset(
    {
        ".csv",
        ".db",
        ".dump",
        ".parquet",
        ".sqlite",
        ".tsv",
        ".xls",
        ".xlsx",
        ".zip",
    }
)
ALLOWED_NON_SOURCE_JSON = frozenset(
    {
        "bizpulse/package-lock.json",
        "bizpulse/package.json",
        "bizpulse/release/local-release-manifest.json",
        "bizpulse/release/task15-local-release-manifest.json",
        "bizpulse/release/authority-document-policy.json",
        "bizpulse/release/current_authority.json",
        "bizpulse/release/verification-policy.json",
        "bizpulse/scripts/admin_ai_runtime_dependencies.json",
        "bizpulse/tests/fixtures/ai/evaluation_cases.json",
        "bizpulse/deliverables/closeout/operator-upload-receipt.json",
    }
)
CANDIDATE_ATTESTATION_JSON = re.compile(
    r"bizpulse/release/attestations/[0-9a-f]{40}\.json"
)
PARTIAL_RELEASE_INCIDENT_JSON = re.compile(
    r"bizpulse/release/incidents/[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]+\.json"
)


class ReleaseVerificationError(RuntimeError):
    """A stable, value-free local release boundary failure."""


def _stable_failure_code(error: ReleaseVerificationError) -> str:
    value = str(error)
    if re.fullmatch(r"[a-z0-9_]+(?::[a-z0-9_]+)?", value):
        return value
    return "release_verification_failed"


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    rollback_sha: str
    rollback_image_digest: str | None
    migration_head: str
    current_authority_evidence_sha256: str | None


def _validated_sha(value: object, *, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ReleaseVerificationError(f"release_identity_invalid:{field}")
    return value


def _validated_digest(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
    ):
        raise ReleaseVerificationError(f"release_identity_invalid:{field}")
    return value


def _validated_hash(value: object, *, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ReleaseVerificationError(f"release_identity_invalid:{field}")
    return value


def attested_release_identity(manifest: dict[str, Any]) -> ReleaseIdentity:
    rollback_sha = _validated_sha(
        manifest.get("rollback_compatible_prior_sha"),
        field="rollback_compatible_prior_sha",
    )
    candidate_migration_head = manifest.get("migration_head")
    if not isinstance(candidate_migration_head, str) or re.fullmatch(
        r"[0-9]{4}_[a-z0-9_]+",
        candidate_migration_head,
    ) is None:
        raise ReleaseVerificationError("release_identity_invalid:migration_head")
    schema = manifest.get("schema_version")
    if schema in {
        "newcaostone.local-release.v1",
        "newcaostone.task15-local-release.v2",
    }:
        rollback_digest = None
        authority_evidence = None
    else:
        rollback_digest = _validated_digest(
            manifest.get("rollback_image_digest"),
            field="rollback_image_digest",
        )
        authority_evidence = _validated_hash(
            manifest.get("current_authority_evidence_sha256"),
            field="current_authority_evidence_sha256",
        )
    return ReleaseIdentity(
        rollback_sha=rollback_sha,
        rollback_image_digest=rollback_digest,
        migration_head=candidate_migration_head,
        current_authority_evidence_sha256=authority_evidence,
    )


def current_release_identity(
    path: Path,
    *,
    require_fresh_observation: bool = True,
) -> ReleaseIdentity:
    from scripts.release_authority import AuthorityInvalid, load_current_authority

    try:
        authority = load_current_authority(
            path,
            require_fresh_observation=require_fresh_observation,
        )
    except AuthorityInvalid as error:
        raise ReleaseVerificationError(str(error)) from error
    candidate_migration_head = migration_head()
    if candidate_migration_head != authority.development.repository_migration_head:
        raise ReleaseVerificationError("repository_migration_authority_drift")
    return ReleaseIdentity(
        rollback_sha=authority.observed_deployment.candidate_git_sha,
        rollback_image_digest=authority.observed_deployment.image_digest,
        migration_head=candidate_migration_head,
        current_authority_evidence_sha256=authority.freshness.evidence_sha256,
    )


def is_allowed_non_source_json(relative: str) -> bool:
    return relative in ALLOWED_NON_SOURCE_JSON or any(
        pattern.fullmatch(relative)
        for pattern in (
            CANDIDATE_ATTESTATION_JSON,
            PARTIAL_RELEASE_INCIDENT_JSON,
        )
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_output(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def candidate_files() -> tuple[Path, ...]:
    completed = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    paths = []
    for raw in completed.stdout.split(b"\0"):
        if not raw:
            continue
        path = REPOSITORY_ROOT / raw.decode("utf-8", errors="strict")
        if path.is_file():
            paths.append(path)
    return tuple(sorted(paths))


def assert_bounded_candidate_files(
    paths: tuple[Path, ...],
    *,
    max_bytes: int = MAX_CANDIDATE_FILE_BYTES,
    declared_artifacts: dict[Path, str] | None = None,
) -> None:
    declarations = {
        path.resolve(): digest
        for path, digest in (declared_artifacts or {}).items()
    }
    for path in paths:
        resolved = path.resolve()
        try:
            relative = str(resolved.relative_to(REPOSITORY_ROOT))
        except ValueError:
            relative = path.name
        if path.name == ".env" or path.name.startswith(".env."):
            raise ReleaseVerificationError("secret_candidate_filename")
        if path.suffix.lower() in PROHIBITED_SUFFIXES:
            raise ReleaseVerificationError("secret_candidate_filename")
        if path.stat().st_size > max_bytes:
            raise ReleaseVerificationError("large_candidate_file")
        content = path.read_bytes()
        declared_digest = declarations.get(resolved)
        data_artifact = path.suffix.lower() in SOURCE_ARTIFACT_SUFFIXES
        binary_artifact = b"\0" in content or path.suffix.lower() in {
            ".xls",
            ".xlsx",
            ".zip",
        }
        if data_artifact and declared_digest is None:
            code = (
                "undeclared_binary_artifact"
                if binary_artifact
                else "undeclared_source_artifact"
            )
            raise ReleaseVerificationError(code)
        if binary_artifact and declared_digest is None:
            raise ReleaseVerificationError("undeclared_binary_artifact")
        if path.suffix.lower() == ".json" and (
            not is_allowed_non_source_json(relative) and declared_digest is None
        ):
            raise ReleaseVerificationError("undeclared_json_artifact")
        if declared_digest is not None and sha256_file(path) != declared_digest:
            raise ReleaseVerificationError("declared_artifact_hash_mismatch")
        if binary_artifact:
            continue
        text = content.decode("utf-8", errors="ignore")
        for name, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                token = match.group(0)
                if token in SAFE_TEST_TOKENS:
                    continue
                raise ReleaseVerificationError(f"secret_candidate_file:{name}")


def assert_git_status(*, allow_dirty: bool) -> None:
    status = git_output("status", "--porcelain=v1", "--untracked-files=all")
    if status and not allow_dirty:
        raise ReleaseVerificationError("git_status_not_clean")


def migration_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise ReleaseVerificationError("migration_head_not_unique")
    return str(heads[0])


def _migration_assignment(source: str, name: str) -> object | None:
    tree = ast.parse(source)
    for node in tree.body:
        target = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        if isinstance(target, ast.Name) and target.id == name and value is not None:
            try:
                return ast.literal_eval(value)
            except (ValueError, SyntaxError) as error:
                raise ReleaseVerificationError(
                    "rollback_migration_metadata_invalid"
                ) from error
    return None


def rollback_migration_heads(revision: str) -> tuple[str, ...]:
    paths = tuple(
        path
        for path in git_output(
            "ls-tree",
            "-r",
            "--name-only",
            revision,
            "--",
            "bizpulse/alembic/versions",
        ).splitlines()
        if path.endswith(".py")
    )
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in paths:
        source = git_output("show", f"{revision}:{path}")
        migration_revision = _migration_assignment(source, "revision")
        down_revision = _migration_assignment(source, "down_revision")
        if not isinstance(migration_revision, str):
            raise ReleaseVerificationError("rollback_migration_metadata_invalid")
        revisions.add(migration_revision)
        if isinstance(down_revision, str):
            parents.add(down_revision)
        elif isinstance(down_revision, tuple) and all(
            isinstance(item, str) for item in down_revision
        ):
            parents.update(down_revision)
        elif down_revision is not None:
            raise ReleaseVerificationError("rollback_migration_metadata_invalid")
    heads = tuple(sorted(revisions - parents))
    if len(heads) != 1:
        raise ReleaseVerificationError("rollback_migration_head_not_unique")
    return heads


def assert_additive_migration_compatibility(identity: ReleaseIdentity) -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    current = scripts.get_revision(identity.migration_head)
    if current is None:
        raise ReleaseVerificationError("candidate_migration_missing")
    ancestors: set[str] = set()
    pending = [current]
    while pending:
        revision = pending.pop()
        if revision.revision in ancestors:
            continue
        ancestors.add(revision.revision)
        down_revisions = revision.down_revision
        if isinstance(down_revisions, str):
            down_revisions = (down_revisions,)
        for parent in down_revisions or ():
            resolved = scripts.get_revision(parent)
            if resolved is None:
                raise ReleaseVerificationError("candidate_migration_parent_missing")
            pending.append(resolved)
    if any(
        rollback_head not in ancestors
        for rollback_head in rollback_migration_heads(identity.rollback_sha)
    ):
        raise ReleaseVerificationError("rollback_migration_not_additive")


def verify_synthetic_manifest(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file() or resolved.name != "manifest.json":
        raise ReleaseVerificationError("synthetic_manifest_missing")
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.synthetic.manifest import verify_bundle_directory

    violations = verify_bundle_directory(resolved.parent)
    if violations:
        raise ReleaseVerificationError("synthetic_source_boundary_failed")
    try:
        payload = json.loads(resolved.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseVerificationError("synthetic_manifest_invalid") from error
    if payload.get("source_classification") != "pure_synthetic":
        raise ReleaseVerificationError("synthetic_source_not_pure")
    generator = payload.get("generator")
    if not isinstance(generator, dict) or not re.fullmatch(
        r"[0-9a-f]{64}", str(generator.get("source_sha256", ""))
    ):
        raise ReleaseVerificationError("synthetic_generator_hash_invalid")
    if generator["source_sha256"] != sha256_file(
        PROJECT_ROOT / "src/synthetic/generator.py"
    ):
        raise ReleaseVerificationError("synthetic_generator_hash_mismatch")
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.adapters import AdapterRegistry
    from src.adapters.protocol import SourceShapeInvalid, UnsupportedSource
    from src.adapters.upseller_excel import validate_safe_xlsx_package

    for declaration in payload.get("files", []):
        if not isinstance(declaration, dict):
            raise ReleaseVerificationError("synthetic_manifest_invalid")
        relative = str(declaration.get("path", ""))
        if Path(relative).suffix.lower() != ".xlsx":
            continue
        try:
            content = (resolved.parent / relative).read_bytes()
            validate_safe_xlsx_package(content)
        except (OSError, SourceShapeInvalid, ValueError) as error:
            raise ReleaseVerificationError(
                "synthetic_binary_boundary_failed"
            ) from error
        if relative == "bizpulse_demo_costs.xlsx":
            continue
        if relative != "operator_import.xlsx":
            raise ReleaseVerificationError("synthetic_binary_role_undeclared")
        try:
            AdapterRegistry().inspect(
                Path(relative).name,
                str(declaration.get("media_type", "")),
                content,
            )
        except (OSError, SourceShapeInvalid, UnsupportedSource, ValueError) as error:
            raise ReleaseVerificationError(
                "synthetic_binary_boundary_failed"
            ) from error
    return payload


def declared_synthetic_artifacts(
    manifest: Path,
    payload: dict[str, Any],
) -> dict[Path, str]:
    files = payload.get("files")
    if not isinstance(files, list):
        raise ReleaseVerificationError("synthetic_manifest_invalid")
    declared: dict[Path, str] = {}
    for item in files:
        if not isinstance(item, dict):
            raise ReleaseVerificationError("synthetic_manifest_invalid")
        path = item.get("path")
        digest = item.get("sha256")
        if not isinstance(path, str) or not re.fullmatch(
            r"[0-9a-f]{64}", str(digest)
        ):
            raise ReleaseVerificationError("synthetic_manifest_invalid")
        resolved = (manifest.parent / path).resolve()
        try:
            resolved.relative_to(manifest.parent.resolve())
        except ValueError as error:
            raise ReleaseVerificationError("synthetic_manifest_path_invalid") from error
        if resolved in declared:
            raise ReleaseVerificationError("synthetic_manifest_duplicate_path")
        declared[resolved] = str(digest)
    declared[manifest.resolve()] = sha256_file(manifest)
    return declared


def validate_evidence(
    evidence: dict[str, Any],
    *,
    candidate_git_sha: str,
    rollback_sha: str,
    required_checks: set[str] | frozenset[str] = REQUIRED_TEST_CHECKS,
) -> None:
    if set(evidence) != {
        "candidate_git_sha",
        "checks",
        "rollback_compatible_prior_sha",
        "schema_version",
    }:
        raise ReleaseVerificationError("release_evidence_fields_invalid")
    if evidence.get("schema_version") != "newcaostone.local-verification.v1":
        raise ReleaseVerificationError("release_evidence_schema_invalid")
    if evidence.get("candidate_git_sha") != candidate_git_sha:
        raise ReleaseVerificationError("release_evidence_sha_mismatch")
    if evidence.get("rollback_compatible_prior_sha") != rollback_sha:
        raise ReleaseVerificationError("release_evidence_rollback_mismatch")
    checks = evidence.get("checks")
    if not isinstance(checks, list):
        raise ReleaseVerificationError("release_evidence_invalid")
    if any(not isinstance(item, dict) for item in checks):
        raise ReleaseVerificationError("release_evidence_fields_invalid")
    names = tuple(item.get("name") for item in checks)
    if any(not isinstance(name, str) for name in names):
        raise ReleaseVerificationError("release_evidence_fields_invalid")
    if len(set(names)) != len(names):
        raise ReleaseVerificationError("release_evidence_duplicate_invalid")
    if set(names) < set(required_checks):
        raise ReleaseVerificationError("release_evidence_incomplete")
    if set(names) != set(required_checks):
        raise ReleaseVerificationError("release_evidence_gate_set_invalid")
    indexed = {str(item["name"]): item for item in checks}
    if set(indexed) != set(required_checks):
        raise ReleaseVerificationError("release_evidence_incomplete")
    commands = expected_gate_commands()
    for name in required_checks:
        item = indexed[name]
        if set(item) != {"command", "name", "passed", "summary"}:
            raise ReleaseVerificationError("release_evidence_fields_invalid")
        if item.get("passed") is not True:
            raise ReleaseVerificationError("release_evidence_failed")
        if item.get("command") != commands[name]:
            raise ReleaseVerificationError("release_evidence_command_invalid")
        for field in ("command", "summary"):
            value = item.get(field)
            limit = 8192 if field == "command" else 500
            if not isinstance(value, str) or not 1 <= len(value) <= limit:
                raise ReleaseVerificationError("release_evidence_value_invalid")
            if "/Users/" in value or "\\Users\\" in value:
                raise ReleaseVerificationError("release_evidence_path_invalid")
            for _, pattern in SECRET_PATTERNS:
                if pattern.search(value):
                    raise ReleaseVerificationError("release_evidence_secret")


def expected_gate_commands() -> dict[str, str]:
    frontend_tests = sorted(
        str(path.relative_to(PROJECT_ROOT))
        for path in (PROJECT_ROOT / "tests/frontend").glob("*.test.mjs")
    )
    return {
        "browser": (
            "python scripts/test_postgres.py "
            "tests/acceptance/test_browser_smoke.py -q"
        ),
        "compileall": "python -m compileall -q api src scripts",
        "diff_check": "git diff --check HEAD",
        "exact_15_restart_rollback": (
            "python scripts/test_postgres.py "
            "tests/acceptance/test_exact_15_sessions.py "
            "tests/acceptance/test_restart_readback.py "
            "tests/acceptance/test_rollback_compatibility.py -q"
        ),
        "frontend": "node --test " + " ".join(frontend_tests),
        "python": "python scripts/test_postgres.py tests -q",
        "ruff": "python -m ruff check .",
        "static_release_boundaries": (
            "static candidate, source, migration, model, secret, and size checks"
        ),
    }


def _run_gate(name: str, command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ReleaseVerificationError(f"release_gate_failed:{name}")
    combined = "\n".join((completed.stdout, completed.stderr))
    summaries = [
        line.strip()
        for line in combined.splitlines()
        if re.search(r"(?:\d+ passed|# pass \d+)", line)
    ]
    summary = "exit=0"
    if summaries:
        passed = re.search(r"(\d+) passed", summaries[-1])
        node_passed = re.search(r"# pass (\d+)", summaries[-1])
        match = passed or node_passed
        if match is not None:
            summary = f"{match.group(1)} passed"
    display_command = list(command)
    if Path(display_command[0]).resolve() == Path(sys.executable).resolve():
        display_command[0] = "python"
    return {
        "command": " ".join(display_command),
        "name": name,
        "passed": True,
        "summary": summary,
    }


def _static_checks(
    manifest: Path,
    *,
    allow_dirty: bool,
    identity: ReleaseIdentity,
) -> dict[str, Any]:
    assert_git_status(allow_dirty=allow_dirty)
    payload = verify_synthetic_manifest(manifest)
    assert_bounded_candidate_files(
        candidate_files(),
        declared_artifacts=declared_synthetic_artifacts(manifest, payload),
    )
    if migration_head() != identity.migration_head:
        raise ReleaseVerificationError("migration_head_mismatch")
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.config import APPROVED_OPENAI_MODEL, APPROVED_REASONING_EFFORT

    if (
        APPROVED_OPENAI_MODEL != "gpt-5.4-nano-2026-03-17"
        or APPROVED_REASONING_EFFORT != "low"
    ):
        raise ReleaseVerificationError("approved_model_snapshot_mismatch")
    return {
        "command": "static candidate, source, migration, model, secret, and size checks",
        "name": "static_release_boundaries",
        "passed": True,
        "summary": "all static boundaries passed",
    }


def assert_candidate_unchanged(
    candidate_sha: str,
    manifest: Path,
    *,
    allow_dirty: bool,
    identity: ReleaseIdentity,
) -> None:
    """Re-establish the exact candidate authority after executable gates."""

    if git_output("rev-parse", "HEAD") != candidate_sha:
        raise ReleaseVerificationError("candidate_head_changed_during_verification")
    _static_checks(manifest, allow_dirty=allow_dirty, identity=identity)


def verify_release(
    manifest: Path,
    *,
    allow_dirty: bool,
    skip_tests: bool,
    identity: ReleaseIdentity,
    authority_mode: str = "release",
) -> dict[str, Any]:
    if allow_dirty != skip_tests:
        raise ReleaseVerificationError("release_verification_mode_invalid")
    if authority_mode not in {"docs", "release"}:
        raise ReleaseVerificationError("release_authority_mode_invalid")
    _run_gate(
        "authority_contract",
        [
            sys.executable,
            "scripts/check_authority_contract.py",
            "--mode",
            authority_mode,
        ],
    )
    candidate_sha = git_output("rev-parse", "HEAD")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", identity.rollback_sha, candidate_sha],
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    if ancestor.returncode != 0:
        raise ReleaseVerificationError("rollback_sha_not_ancestor")
    assert_additive_migration_compatibility(identity)
    checks = [
        _static_checks(
            manifest,
            allow_dirty=allow_dirty,
            identity=identity,
        ),
    ]
    if not skip_tests:
        checks.append(
            _run_gate(
                "python",
                [sys.executable, "scripts/test_postgres.py", "tests", "-q"],
            )
        )
        frontend_tests = sorted(
            str(path.relative_to(PROJECT_ROOT))
            for path in (PROJECT_ROOT / "tests/frontend").glob("*.test.mjs")
        )
        checks.append(
            _run_gate("frontend", ["node", "--test", *frontend_tests])
        )
        checks.append(
            _run_gate(
                "exact_15_restart_rollback",
                [
                    sys.executable,
                    "scripts/test_postgres.py",
                    "tests/acceptance/test_exact_15_sessions.py",
                    "tests/acceptance/test_restart_readback.py",
                    "tests/acceptance/test_rollback_compatibility.py",
                    "-q",
                ],
            )
        )
        checks.extend(
            (
                _run_gate("ruff", [sys.executable, "-m", "ruff", "check", "."]),
                _run_gate(
                    "compileall",
                    [sys.executable, "-m", "compileall", "-q", "api", "src", "scripts"],
                ),
                _run_gate(
                    "diff_check",
                    ["git", "diff", "--check", "HEAD"],
                ),
                _run_gate(
                    "browser",
                    [
                        sys.executable,
                        "scripts/test_postgres.py",
                        "tests/acceptance/test_browser_smoke.py",
                        "-q",
                    ],
                ),
            )
        )
    assert_candidate_unchanged(
        candidate_sha,
        manifest,
        allow_dirty=allow_dirty,
        identity=identity,
    )
    return {
        "candidate_git_sha": candidate_sha,
        "checks": checks,
        "rollback_compatible_prior_sha": identity.rollback_sha,
        "schema_version": "newcaostone.local-verification.v1",
    }


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--evidence-output", type=Path)
    parser.add_argument("--attestation-identity", type=Path)
    options = parser.parse_args(arguments)
    try:
        if options.allow_dirty != options.skip_tests:
            raise ReleaseVerificationError("release_verification_mode_invalid")
        if options.allow_dirty and options.evidence_output is not None:
            raise ReleaseVerificationError("dirty_evidence_forbidden")
        if options.skip_tests and options.evidence_output is not None:
            raise ReleaseVerificationError("incomplete_evidence_forbidden")
        if options.attestation_identity is None:
            authority_path = PROJECT_ROOT / "release/current_authority.json"
            identity = (
                current_release_identity(
                    authority_path,
                    require_fresh_observation=False,
                )
                if options.allow_dirty
                else current_release_identity(authority_path)
            )
            authority_mode = "docs" if options.allow_dirty else "release"
        else:
            try:
                attestation_payload = json.loads(
                    options.attestation_identity.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as error:
                raise ReleaseVerificationError(
                    "release_attestation_identity_invalid"
                ) from error
            if not isinstance(attestation_payload, dict):
                raise ReleaseVerificationError("release_attestation_identity_invalid")
            identity = attested_release_identity(attestation_payload)
            authority_mode = "docs"
        evidence = verify_release(
            options.manifest,
            allow_dirty=options.allow_dirty,
            skip_tests=options.skip_tests,
            identity=identity,
            authority_mode=authority_mode,
        )
        if options.evidence_output is not None:
            output = options.evidence_output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(evidence, indent=2, sort_keys=True) + "\n"
            )
    except ReleaseVerificationError as error:
        print("release_verification=failed")
        print(f"release_failure_code={_stable_failure_code(error)}")
        return 1
    except (OSError, subprocess.SubprocessError):
        print("release_verification=failed")
        print("release_failure_code=release_verification_failed")
        return 1
    if options.skip_tests:
        print("development_static_check=ok")
    else:
        print("release_verification=ok")
    if not options.skip_tests:
        print(f"candidate_git_sha={evidence['candidate_git_sha']}")
    print(f"checks_passed={len(evidence['checks'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
