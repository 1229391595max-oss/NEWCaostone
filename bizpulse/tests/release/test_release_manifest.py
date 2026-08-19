from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import scripts.verify_release as verify_release_module
from scripts.verify_release import attested_release_identity


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PROJECT_ROOT.parent
MANIFEST_PATH = PROJECT_ROOT / "release/local-release-manifest.json"
MANIFEST_GIT_PATH = "bizpulse/release/local-release-manifest.json"


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_local_release_manifest_is_truthful_two_commit_evidence() -> None:
    payload = json.loads(MANIFEST_PATH.read_text())
    candidate = payload["candidate_git_sha"]
    attestation = _git("log", "-1", "--format=%H", "--", MANIFEST_GIT_PATH)

    assert re.fullmatch(r"[0-9a-f]{40}", candidate)
    assert _git("rev-parse", f"{attestation}^") == candidate
    assert _git("diff", "--name-only", candidate, attestation) == MANIFEST_GIT_PATH
    assert payload["claims"] == {
        "accepted": False,
        "ci_verified": False,
        "deployed": False,
        "hosted_verified": False,
        "local_verified": True,
        "production_ready": False,
    }
    assert len(payload["verification_evidence"]["checks"]) == 8


def test_release_manifest_contains_no_path_or_secret_value() -> None:
    source = MANIFEST_PATH.read_text()

    assert "/Users/" not in source
    assert "AccountKey=" not in source
    assert "postgresql://" not in source
    assert not re.search(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b", source)


def test_historical_manifest_keeps_its_committed_release_identity() -> None:
    payload = json.loads(MANIFEST_PATH.read_text())

    identity = attested_release_identity(payload)

    assert identity.rollback_sha == payload["rollback_compatible_prior_sha"]
    assert identity.migration_head == payload["migration_head"]
    assert identity.rollback_image_digest is None
    assert identity.current_authority_evidence_sha256 is None


def test_release_verifier_allowlists_only_the_exact_manifest_path() -> None:
    from scripts.verify_release import ALLOWED_NON_SOURCE_JSON

    assert "bizpulse/release/local-release-manifest.json" in ALLOWED_NON_SOURCE_JSON
    assert (
        "bizpulse/release/task15-local-release-manifest.json"
        in ALLOWED_NON_SOURCE_JSON
    )
    successor = "bizpulse/release/attestations/" + "a" * 40 + ".json"
    assert verify_release_module.is_allowed_non_source_json(successor)
    assert not verify_release_module.is_allowed_non_source_json(
        "bizpulse/release/attestations/not-a-commit.json"
    )
    assert "release.json" not in ALLOWED_NON_SOURCE_JSON
