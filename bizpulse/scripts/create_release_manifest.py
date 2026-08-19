"""Create an immutable local verification manifest for one committed candidate."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_SCRIPT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_PROJECT_ROOT))

from scripts.verify_release import (  # noqa: E402
    PROJECT_ROOT,
    REQUIRED_TEST_CHECKS,
    ReleaseIdentity,
    ReleaseVerificationError,
    assert_candidate_unchanged,
    attested_release_identity,
    git_output,
    migration_head,
    sha256_file,
    validate_evidence,
    verify_release,
    verify_synthetic_manifest,
)
from scripts.release_authority import (  # noqa: E402
    AuthorityInvalid,
    load_current_authority,
)

DEPENDENCY_FILES = (
    "requirements.txt",
    "requirements-dev.txt",
    "package.json",
    "package-lock.json",
)
ATTESTATION_VERIFICATION_TIMEOUT_SECONDS = 2_400


class ReleaseManifestInvalid(RuntimeError):
    """The requested release attestation is incomplete or mutable."""


def release_identity_from_authority(
    path: Path,
    *,
    now: datetime | None = None,
) -> ReleaseIdentity:
    try:
        authority = load_current_authority(
            path,
            now=now,
            require_fresh_observation=True,
        )
    except AuthorityInvalid as error:
        raise ReleaseManifestInvalid(str(error)) from error
    candidate_migration_head = migration_head()
    if candidate_migration_head != authority.development.repository_migration_head:
        raise ReleaseManifestInvalid("repository_migration_authority_drift")
    return ReleaseIdentity(
        rollback_sha=authority.observed_deployment.candidate_git_sha,
        rollback_image_digest=authority.observed_deployment.image_digest,
        migration_head=candidate_migration_head,
        current_authority_evidence_sha256=authority.freshness.evidence_sha256,
    )


LEGACY_ATTESTATION_PATHS = {
    "3e933d083b3ab4dba36d8053f56ecf2d68d31f1e": (
        "bizpulse/release/task15-local-release-manifest.json"
    ),
    "6e5c1f98d3a68716ec687611dc3ccd03f44f2e7f": (
        "bizpulse/release/local-release-manifest.json"
    ),
}
ATTESTATION_DIRECTORY = "bizpulse/release/attestations"


def attestation_path(candidate_git_sha: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", candidate_git_sha):
        raise ReleaseManifestInvalid("release_commit_invalid")
    return LEGACY_ATTESTATION_PATHS.get(
        candidate_git_sha,
        f"{ATTESTATION_DIRECTORY}/{candidate_git_sha}.json",
    )


def build_release_manifest(
    *,
    candidate_git_sha: str,
    candidate_git_tree: str,
    candidate_committed_at: str,
    candidate_image_digest: str | None,
    rollback_sha: str,
    rollback_image_digest: str | None,
    rollback_image_input_sha256: str,
    candidate_migration_head: str,
    current_authority_evidence_sha256: str | None,
    generated_at: str | None,
    synthetic_manifest_path: str,
    synthetic_manifest_sha256: str,
    generator_source_sha256: str,
    dependency_hashes: dict[str, str],
    evidence: dict[str, Any],
    evidence_sha256: str,
    configuration_names: tuple[str, ...],
    schema_version: str = "newcaostone.integrated-release.v4",
) -> dict[str, Any]:
    try:
        validate_evidence(
            evidence,
            candidate_git_sha=candidate_git_sha,
            rollback_sha=rollback_sha,
            required_checks=REQUIRED_TEST_CHECKS,
        )
    except ReleaseVerificationError as error:
        raise ReleaseManifestInvalid(str(error)) from error
    for value, size in (
        (candidate_git_sha, 40),
        (candidate_git_tree, 40),
        (rollback_sha, 40),
        (synthetic_manifest_sha256, 64),
        (generator_source_sha256, 64),
        (evidence_sha256, 64),
        (rollback_image_input_sha256, 64),
    ):
        if not re.fullmatch(rf"[0-9a-f]{{{size}}}", value):
            raise ReleaseManifestInvalid("release_hash_invalid")
    if re.fullmatch(r"[0-9]{4}_[a-z0-9_]+", candidate_migration_head) is None:
        raise ReleaseManifestInvalid("release_migration_invalid")
    if schema_version in {
        "newcaostone.integrated-release.v3",
        "newcaostone.integrated-release.v4",
    }:
        if (
            rollback_image_digest is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", rollback_image_digest) is None
            or current_authority_evidence_sha256 is None
            or re.fullmatch(
                r"[0-9a-f]{64}", current_authority_evidence_sha256
            )
            is None
            or generated_at is None
            or (
                schema_version == "newcaostone.integrated-release.v4"
                and (
                    candidate_image_digest is None
                    or re.fullmatch(
                        r"sha256:[0-9a-f]{64}", candidate_image_digest
                    )
                    is None
                )
            )
        ):
            raise ReleaseManifestInvalid("release_authority_identity_invalid")
        try:
            parsed_generation = datetime.fromisoformat(
                generated_at.replace("Z", "+00:00")
            )
        except ValueError as error:
            raise ReleaseManifestInvalid("release_generation_time_invalid") from error
        if parsed_generation.tzinfo is None:
            raise ReleaseManifestInvalid("release_generation_time_invalid")
    elif schema_version not in {
        "newcaostone.local-release.v1",
        "newcaostone.task15-local-release.v2",
    }:
        raise ReleaseManifestInvalid("release_schema_invalid")
    current_image_input_sha256 = image_input_sha256(
        git_tree=candidate_git_tree,
        dependency_hashes=dependency_hashes,
    )
    payload = {
        "attestation_policy": {
            "allowed_paths": [attestation_path(candidate_git_sha)],
            "commit_parent_must_equal_candidate": True,
        },
        "candidate_committed_at": candidate_committed_at,
        "candidate_git_sha": candidate_git_sha,
        "candidate_git_tree": candidate_git_tree,
        "claims": {
            "accepted": False,
            "ci_verified": False,
            "deployed": False,
            "hosted_verified": False,
            "local_verified": True,
            "production_ready": False,
        },
        "configuration_names": sorted(set(configuration_names)),
        "dependencies": dict(sorted(dependency_hashes.items())),
        "image_input_sha256": current_image_input_sha256,
        "migration_head": candidate_migration_head,
        "model_snapshot": {
            "model": "gpt-5.4-nano-2026-03-17",
            "reasoning_effort": "low",
            "max_output_tokens": 2800,
        },
        "rollback_compatible_prior_sha": rollback_sha,
        "rollback_image_input_sha256": rollback_image_input_sha256,
        "schema_version": schema_version,
        "synthetic_fixture": {
            "generator_source_sha256": generator_source_sha256,
            "manifest_path": synthetic_manifest_path,
            "manifest_sha256": synthetic_manifest_sha256,
            "source_classification": "pure_synthetic",
        },
        "verification_evidence": {
            "checks": evidence["checks"],
            "sha256": evidence_sha256,
        },
    }
    if schema_version in {
        "newcaostone.integrated-release.v3",
        "newcaostone.integrated-release.v4",
    }:
        payload.update(
            {
                "current_authority_evidence_sha256": (
                    current_authority_evidence_sha256
                ),
                "generated_at": generated_at,
                "rollback_image_digest": rollback_image_digest,
            }
        )
    if schema_version == "newcaostone.integrated-release.v4":
        payload.update(
            {
                "candidate_image": {
                    "digest": candidate_image_digest,
                    "image_input_sha256": current_image_input_sha256,
                    "platform": "linux/amd64",
                    "source_revision": candidate_git_sha,
                },
                "release_package_contract": {
                    "ai_revision_requires": [
                        "data_scope_revision_receipt",
                        "model_qualification_receipt",
                    ],
                    "data_scope_revision_ai_enabled": False,
                    "model_qualification_case_count": 12,
                    "stage_order": ["data_scope_revision", "ai_revision"],
                },
            }
        )
    elif schema_version == "newcaostone.local-release.v1":
        payload.pop("rollback_image_input_sha256")
    return payload


def image_input_sha256(
    *,
    git_tree: str,
    dependency_hashes: dict[str, str],
) -> str:
    canonical = json.dumps(
        {
            "candidate_git_tree": git_tree,
            "dependencies": dict(sorted(dependency_hashes.items())),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def committed_image_input_sha256(revision: str) -> str:
    dependency_hashes: dict[str, str] = {}
    for path in DEPENDENCY_FILES:
        content = subprocess.run(
            ["git", "show", f"{revision}:bizpulse/{path}"],
            cwd=PROJECT_ROOT.parent,
            check=True,
            capture_output=True,
        ).stdout
        dependency_hashes[path] = hashlib.sha256(content).hexdigest()
    return image_input_sha256(
        git_tree=git_output("rev-parse", f"{revision}^{{tree}}"),
        dependency_hashes=dependency_hashes,
    )


def validate_local_candidate_image(
    *,
    candidate_git_sha: str,
    candidate_image_digest: str,
    expected_image_input_sha256: str,
) -> None:
    """Bind the locally built linux/amd64 image to the exact candidate inputs."""

    if re.fullmatch(r"[0-9a-f]{40}", candidate_git_sha) is None or re.fullmatch(
        r"sha256:[0-9a-f]{64}", candidate_image_digest
    ) is None:
        raise ReleaseManifestInvalid("candidate_image_identity_invalid")
    tag = f"newcaostone-local:{candidate_git_sha[:12]}"
    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", tag],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        projection = json.loads(completed.stdout)
        image = projection[0]
        labels = image["Config"]["Labels"]
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise ReleaseManifestInvalid("candidate_image_inspection_failed") from error
    if (
        completed.returncode != 0
        or image.get("Id") != candidate_image_digest
        or image.get("Os") != "linux"
        or image.get("Architecture") != "amd64"
        or labels.get("org.opencontainers.image.revision") != candidate_git_sha
        or labels.get("org.opencontainers.image.bizpulse.image-input-sha256")
        != expected_image_input_sha256
    ):
        raise ReleaseManifestInvalid("candidate_image_identity_invalid")


def assert_exact_manifest(
    payload: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    if payload != expected:
        raise ReleaseManifestInvalid("attestation_payload_mismatch")


def assert_reproduced_evidence(
    attested: dict[str, Any],
    reproduced: dict[str, Any],
) -> None:
    """Require final verification to reproduce the attested gate evidence."""

    if attested != reproduced:
        raise ReleaseManifestInvalid("attestation_evidence_not_reproduced")


def _evidence_bytes(evidence: dict[str, Any]) -> bytes:
    return (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode()


def _resolve_commit(revision: str) -> str:
    try:
        resolved = git_output("rev-parse", f"{revision}^{{commit}}")
    except subprocess.SubprocessError as error:
        raise ReleaseManifestInvalid("release_commit_missing") from error
    if not re.fullmatch(r"[0-9a-f]{40}", resolved):
        raise ReleaseManifestInvalid("release_commit_invalid")
    return resolved


def _configuration_names() -> tuple[str, ...]:
    source = (PROJECT_ROOT / "src/config.py").read_text()
    return tuple(sorted(set(re.findall(r"BIZPULSE_[A-Z0-9_]+", source))))


def _verified_azurite_executable() -> Path:
    configured = os.getenv("BIZPULSE_TEST_AZURITE_BLOB_EXECUTABLE")
    executable = (
        Path(configured)
        if configured is not None
        else PROJECT_ROOT / "node_modules/.bin/azurite-blob"
    ).resolve()
    if not executable.is_file() or not executable.stat().st_mode & 0o111:
        raise ReleaseManifestInvalid("attestation_azurite_dependency_missing")
    try:
        lock = json.loads((PROJECT_ROOT / "package-lock.json").read_text())
        expected = str(lock["packages"]["node_modules/azurite"]["version"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ReleaseManifestInvalid("attestation_azurite_lock_invalid") from error
    completed = subprocess.run(
        [str(executable), "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if completed.returncode != 0 or completed.stdout.strip() != expected:
        raise ReleaseManifestInvalid("attestation_azurite_version_mismatch")
    return executable


def create_manifest(
    *,
    synthetic_manifest: Path,
    output_path: Path,
    candidate_revision: str,
    candidate_image_digest: str,
) -> dict[str, Any]:
    identity = release_identity_from_authority(
        PROJECT_ROOT / "release/current_authority.json"
    )
    if git_output("status", "--porcelain=v1", "--untracked-files=all"):
        raise ReleaseManifestInvalid("git_status_not_clean")
    candidate_sha = _resolve_commit(candidate_revision)
    if candidate_sha != _resolve_commit("HEAD"):
        raise ReleaseManifestInvalid("candidate_must_equal_head")
    rollback_sha = _resolve_commit(identity.rollback_sha)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", rollback_sha, candidate_sha],
        cwd=PROJECT_ROOT.parent,
        check=False,
    )
    if ancestor.returncode != 0:
        raise ReleaseManifestInvalid("rollback_commit_not_ancestor")
    synthetic_payload = verify_synthetic_manifest(synthetic_manifest)
    evidence = verify_release(
        synthetic_manifest,
        allow_dirty=False,
        skip_tests=False,
        identity=identity,
    )
    dependencies = {
        path: sha256_file(PROJECT_ROOT / path) for path in DEPENDENCY_FILES
    }
    current_image_input_sha256 = image_input_sha256(
        git_tree=git_output("rev-parse", f"{candidate_sha}^{{tree}}"),
        dependency_hashes=dependencies,
    )
    validate_local_candidate_image(
        candidate_git_sha=candidate_sha,
        candidate_image_digest=candidate_image_digest,
        expected_image_input_sha256=current_image_input_sha256,
    )
    payload = build_release_manifest(
        candidate_git_sha=candidate_sha,
        candidate_git_tree=git_output("rev-parse", f"{candidate_sha}^{{tree}}"),
        candidate_committed_at=git_output(
            "show", "-s", "--format=%cI", candidate_sha
        ),
        candidate_image_digest=candidate_image_digest,
        rollback_sha=rollback_sha,
        rollback_image_digest=identity.rollback_image_digest,
        rollback_image_input_sha256=committed_image_input_sha256(rollback_sha),
        candidate_migration_head=identity.migration_head,
        current_authority_evidence_sha256=(
            identity.current_authority_evidence_sha256
        ),
        generated_at=datetime.now(UTC).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        synthetic_manifest_path=str(synthetic_manifest.relative_to(PROJECT_ROOT)),
        synthetic_manifest_sha256=sha256_file(synthetic_manifest),
        generator_source_sha256=str(
            synthetic_payload["generator"]["source_sha256"]
        ),
        dependency_hashes=dependencies,
        evidence=evidence,
        evidence_sha256=hashlib.sha256(_evidence_bytes(evidence)).hexdigest(),
        configuration_names=_configuration_names(),
    )
    output = output_path.resolve()
    try:
        output.relative_to(PROJECT_ROOT)
    except ValueError as error:
        raise ReleaseManifestInvalid("release_output_outside_project") from error
    if str(output.relative_to(PROJECT_ROOT.parent)) != attestation_path(
        candidate_sha
    ):
        raise ReleaseManifestInvalid("release_output_path_invalid")
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output.exists():
        if output.read_text() != serialized:
            raise ReleaseManifestInvalid("release_manifest_immutable_conflict")
        return payload
    assert_candidate_unchanged(
        candidate_sha,
        synthetic_manifest,
        allow_dirty=False,
        identity=identity,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized)
    return payload


def _reverify_committed_candidate(
    candidate: str,
    *,
    attestation_path: Path,
    schema_version: str,
) -> dict[str, Any]:
    """Run the full verifier from an exact detached candidate checkout."""

    temporary = tempfile.TemporaryDirectory(prefix="newcaostone-attestation-")
    root = Path(temporary.name)
    checkout = root / "candidate"
    evidence_path = root / "evidence.json"
    added = False
    cleanup_failed = False
    evidence: dict[str, Any] | None = None
    try:
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(checkout), candidate],
            cwd=PROJECT_ROOT.parent,
            check=True,
            capture_output=True,
            text=True,
        )
        added = True
        environment = dict(os.environ)
        environment["BIZPULSE_TEST_AZURITE_BLOB_EXECUTABLE"] = str(
            _verified_azurite_executable()
        )
        command = [
            sys.executable,
            "scripts/verify_release.py",
            "--manifest",
            "tests/fixtures/synthetic/v1/manifest.json",
            "--evidence-output",
            str(evidence_path),
        ]
        if schema_version in {
            "newcaostone.integrated-release.v3",
            "newcaostone.integrated-release.v4",
        }:
            command.extend(["--attestation-identity", str(attestation_path)])
        completed = subprocess.run(
            command,
            cwd=checkout / "bizpulse",
            check=False,
            capture_output=True,
            env=environment,
            text=True,
            timeout=ATTESTATION_VERIFICATION_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            raise ReleaseManifestInvalid("attestation_candidate_verification_failed")
        try:
            evidence = json.loads(evidence_path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise ReleaseManifestInvalid(
                "attestation_candidate_evidence_invalid"
            ) from error
        if not isinstance(evidence, dict):
            raise ReleaseManifestInvalid("attestation_candidate_evidence_invalid")
    finally:
        if added:
            removed = subprocess.run(
                ["git", "worktree", "remove", "--force", str(checkout)],
                cwd=PROJECT_ROOT.parent,
                check=False,
                capture_output=True,
                text=True,
            )
            cleanup_failed = removed.returncode != 0
        temporary.cleanup()
        if cleanup_failed:
            subprocess.run(
                ["git", "worktree", "prune"],
                cwd=PROJECT_ROOT.parent,
                check=False,
                capture_output=True,
                text=True,
            )
            raise ReleaseManifestInvalid("attestation_worktree_cleanup_failed")
    if evidence is None:
        raise ReleaseManifestInvalid("attestation_candidate_evidence_invalid")
    return evidence


def verify_attestation(manifest_path: Path) -> tuple[str, str]:
    """Verify the one-child proof commit without claiming a self-referential SHA."""

    if git_output("status", "--porcelain=v1", "--untracked-files=all"):
        raise ReleaseManifestInvalid("git_status_not_clean")
    resolved = manifest_path.resolve()
    try:
        relative = str(resolved.relative_to(PROJECT_ROOT.parent))
    except ValueError as error:
        raise ReleaseManifestInvalid("release_output_outside_project") from error
    try:
        payload = json.loads(resolved.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseManifestInvalid("release_manifest_invalid") from error
    candidate = str(payload.get("candidate_git_sha", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", candidate):
        raise ReleaseManifestInvalid("release_commit_invalid")
    expected_path = attestation_path(candidate)
    if relative != expected_path:
        raise ReleaseManifestInvalid("release_output_path_invalid")
    attestation = _resolve_commit("HEAD")
    if _resolve_commit("HEAD^") != candidate:
        raise ReleaseManifestInvalid("attestation_parent_mismatch")
    changed = tuple(
        line
        for line in git_output("diff", "--name-only", candidate, attestation).splitlines()
        if line
    )
    if changed != (expected_path,):
        raise ReleaseManifestInvalid("attestation_paths_invalid")
    committed = git_output("show", f"HEAD:{expected_path}") + "\n"
    if committed != resolved.read_text():
        raise ReleaseManifestInvalid("attestation_content_mismatch")
    expected_policy = {
        "allowed_paths": [expected_path],
        "commit_parent_must_equal_candidate": True,
    }
    if payload.get("attestation_policy") != expected_policy:
        raise ReleaseManifestInvalid("attestation_policy_invalid")
    identity = attested_release_identity(payload)
    schema_version = str(payload.get("schema_version", ""))
    evidence_projection = payload.get("verification_evidence")
    if not isinstance(evidence_projection, dict):
        raise ReleaseManifestInvalid("release_evidence_invalid")
    attested_evidence = {
        "candidate_git_sha": candidate,
        "checks": evidence_projection.get("checks"),
        "rollback_compatible_prior_sha": identity.rollback_sha,
        "schema_version": "newcaostone.local-verification.v1",
    }
    reproduced_evidence = _reverify_committed_candidate(
        candidate,
        attestation_path=resolved,
        schema_version=schema_version,
    )
    assert_reproduced_evidence(attested_evidence, reproduced_evidence)
    evidence = reproduced_evidence
    evidence_sha256 = hashlib.sha256(_evidence_bytes(evidence)).hexdigest()
    synthetic_manifest = (
        PROJECT_ROOT / "tests/fixtures/synthetic/v1/manifest.json"
    )
    synthetic_payload = verify_synthetic_manifest(synthetic_manifest)
    expected = build_release_manifest(
        candidate_git_sha=candidate,
        candidate_git_tree=git_output("rev-parse", f"{candidate}^{{tree}}"),
        candidate_committed_at=git_output(
            "show", "-s", "--format=%cI", candidate
        ),
        candidate_image_digest=(
            str(payload["candidate_image"]["digest"])
            if schema_version == "newcaostone.integrated-release.v4"
            else None
        ),
        rollback_sha=identity.rollback_sha,
        rollback_image_digest=identity.rollback_image_digest,
        rollback_image_input_sha256=committed_image_input_sha256(
            identity.rollback_sha
        ),
        candidate_migration_head=identity.migration_head,
        current_authority_evidence_sha256=(
            identity.current_authority_evidence_sha256
        ),
        generated_at=(
            str(payload.get("generated_at"))
            if payload.get("generated_at") is not None
            else None
        ),
        synthetic_manifest_path=str(synthetic_manifest.relative_to(PROJECT_ROOT)),
        synthetic_manifest_sha256=sha256_file(synthetic_manifest),
        generator_source_sha256=str(
            synthetic_payload["generator"]["source_sha256"]
        ),
        dependency_hashes={
            path: sha256_file(PROJECT_ROOT / path) for path in DEPENDENCY_FILES
        },
        evidence=evidence,
        evidence_sha256=evidence_sha256,
        configuration_names=_configuration_names(),
        schema_version=schema_version,
    )
    assert_exact_manifest(payload, expected)
    return candidate, attestation


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--synthetic-manifest",
        default=PROJECT_ROOT / "tests/fixtures/synthetic/v1/manifest.json",
        type=Path,
    )
    parser.add_argument(
        "--output",
        type=Path,
    )
    parser.add_argument("--candidate-sha", default="HEAD")
    parser.add_argument("--candidate-image-digest")
    parser.add_argument("--verify-attestation", action="store_true")
    options = parser.parse_args(arguments)
    try:
        if options.verify_attestation:
            candidate_for_output = _resolve_commit("HEAD^")
            output = options.output or (
                PROJECT_ROOT.parent / attestation_path(candidate_for_output)
            )
            candidate, attestation = verify_attestation(output)
            print("release_attestation=ok")
            print(f"candidate_git_sha={candidate}")
            print(f"attestation_git_sha={attestation}")
            return 0
        candidate_for_output = _resolve_commit(options.candidate_sha)
        output = options.output or (
            PROJECT_ROOT.parent / attestation_path(candidate_for_output)
        )
        payload = create_manifest(
            synthetic_manifest=options.synthetic_manifest.resolve(),
            output_path=output,
            candidate_revision=options.candidate_sha,
            candidate_image_digest=str(options.candidate_image_digest or ""),
        )
    except (
        ReleaseManifestInvalid,
        ReleaseVerificationError,
        OSError,
        subprocess.SubprocessError,
    ):
        print("release_manifest=failed")
        return 1
    print("release_manifest=ok")
    print(f"candidate_git_sha={payload['candidate_git_sha']}")
    print(f"output={output.resolve().relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
