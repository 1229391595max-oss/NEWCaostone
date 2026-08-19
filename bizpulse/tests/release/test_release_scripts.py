from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

import scripts.create_release_manifest as create_release_manifest_module
import scripts.verify_release as verify_release_module
from scripts.create_release_manifest import (
    ReleaseManifestInvalid,
    _verified_azurite_executable,
    assert_exact_manifest,
    assert_reproduced_evidence,
    build_release_manifest,
    validate_local_candidate_image,
)
from scripts.verify_release import (
    REQUIRED_TEST_CHECKS,
    ReleaseVerificationError,
    _run_gate,
    assert_bounded_candidate_files,
    expected_gate_commands,
    validate_evidence,
    verify_synthetic_manifest,
)
from tests.acceptance.support import _azurite_blob_executable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC_MANIFEST = PROJECT_ROOT / "tests/fixtures/synthetic/v1/manifest.json"


def test_candidate_file_boundary_rejects_secret_and_large_file(
    tmp_path: Path,
) -> None:
    secret = tmp_path / "runtime.txt"
    secret.write_text("Account" + "Key=abcdefghijklmnopqrstuvwxyz0123456789")
    with pytest.raises(ReleaseVerificationError, match="secret_candidate_file"):
        assert_bounded_candidate_files((secret,), max_bytes=1024)
    secret.write_bytes(b"x" * 1025)
    with pytest.raises(ReleaseVerificationError, match="large_candidate_file"):
        assert_bounded_candidate_files((secret,), max_bytes=1024)


def test_candidate_file_boundary_rejects_undeclared_binary_and_source(
    tmp_path: Path,
) -> None:
    binary = tmp_path / "untracked.xlsx"
    binary.write_bytes(b"PK\x03\x04\x00hidden")
    source = tmp_path / "orders.csv"
    source.write_text("order_id,total\nREAL-1,10\n")

    with pytest.raises(ReleaseVerificationError, match="undeclared_binary_artifact"):
        assert_bounded_candidate_files((binary,))
    with pytest.raises(ReleaseVerificationError, match="undeclared_source_artifact"):
        assert_bounded_candidate_files((source,))


def test_candidate_file_boundary_accepts_only_exact_declared_binary(
    tmp_path: Path,
) -> None:
    binary = tmp_path / "operator_import.xlsx"
    binary.write_bytes(b"PK\x03\x04\x00synthetic")
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()

    assert_bounded_candidate_files(
        (binary,), declared_artifacts={binary.resolve(): digest}
    )
    with pytest.raises(ReleaseVerificationError, match="declared_artifact_hash_mismatch"):
        assert_bounded_candidate_files(
            (binary,), declared_artifacts={binary.resolve(): "0" * 64}
        )


def test_candidate_file_boundary_rejects_undeclared_deliverables_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "bizpulse/deliverables/closeout/unrelated.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"artifact":"unrelated"}')
    monkeypatch.setattr(verify_release_module, "REPOSITORY_ROOT", tmp_path)

    with pytest.raises(ReleaseVerificationError, match="undeclared_json_artifact"):
        assert_bounded_candidate_files((artifact,))


def test_synthetic_verifier_binds_generator_and_scans_xlsx_package(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "synthetic"
    shutil.copytree(SYNTHETIC_MANIFEST.parent, fixture)
    manifest_path = fixture / "manifest.json"
    payload = json.loads(manifest_path.read_text())
    payload["generator"]["source_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(payload, separators=(",", ":")))
    with pytest.raises(ReleaseVerificationError, match="generator_hash_mismatch"):
        verify_synthetic_manifest(manifest_path)

    shutil.rmtree(fixture)
    shutil.copytree(SYNTHETIC_MANIFEST.parent, fixture)
    manifest_path = fixture / "manifest.json"
    workbook = fixture / "operator_import.xlsx"
    rebuilt = fixture / "operator_import.rebuilt.xlsx"
    with zipfile.ZipFile(workbook) as source, zipfile.ZipFile(rebuilt, "w") as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename.lower() == "xl/styles.xml":
                content += b"<!-- person@example.test -->"
            target.writestr(info, content)
    rebuilt.replace(workbook)
    payload = json.loads(manifest_path.read_text())
    declaration = next(
        item for item in payload["files"] if item["path"] == workbook.name
    )
    declaration["sha256"] = hashlib.sha256(workbook.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(payload, separators=(",", ":")))
    with pytest.raises(ReleaseVerificationError, match="binary_boundary_failed"):
        verify_synthetic_manifest(manifest_path)

def test_release_evidence_requires_every_named_gate_to_pass() -> None:
    commands = expected_gate_commands()
    evidence = {
        "candidate_git_sha": "a" * 40,
        "rollback_compatible_prior_sha": "c" * 40,
        "schema_version": "newcaostone.local-verification.v1",
        "checks": [
            {
                "command": commands["python"],
                "name": "python",
                "passed": True,
                "summary": "1 passed",
            },
            {
                "command": commands["exact_15_restart_rollback"],
                "name": "exact_15_restart_rollback",
                "passed": False,
                "summary": "1 failed",
            },
        ],
    }

    with pytest.raises(ReleaseVerificationError, match="release_evidence_failed"):
        validate_evidence(
            evidence,
            candidate_git_sha="a" * 40,
            rollback_sha="c" * 40,
            required_checks={"python", "exact_15_restart_rollback"},
        )


def test_release_evidence_rejects_forged_command_and_sensitive_summary() -> None:
    commands = expected_gate_commands()
    evidence = {
        "candidate_git_sha": "a" * 40,
        "rollback_compatible_prior_sha": "c" * 40,
        "schema_version": "newcaostone.local-verification.v1",
        "checks": [
            {
                "command": "python -m pytest tests -q",
                "name": "python",
                "passed": True,
                "summary": "1 passed",
            }
        ],
    }
    with pytest.raises(ReleaseVerificationError, match="command_invalid"):
        validate_evidence(
            evidence,
            candidate_git_sha="a" * 40,
            rollback_sha="c" * 40,
            required_checks={"python"},
        )
    evidence["checks"][0]["command"] = commands["python"]
    evidence["checks"][0]["summary"] = "/Users/private/release passed"
    with pytest.raises(ReleaseVerificationError, match="path_invalid"):
        validate_evidence(
            evidence,
            candidate_git_sha="a" * 40,
            rollback_sha="c" * 40,
            required_checks={"python"},
        )
    evidence["checks"][0]["summary"] = (
        "Account" + "Key=abcdefghijklmnopqrstuvwxyz0123456789"
    )
    with pytest.raises(ReleaseVerificationError, match="release_evidence_secret"):
        validate_evidence(
            evidence,
            candidate_git_sha="a" * 40,
            rollback_sha="c" * 40,
            required_checks={"python"},
        )


def test_release_evidence_rejects_extra_and_duplicate_gate_entries() -> None:
    commands = expected_gate_commands()
    valid = {
        "command": commands["python"],
        "name": "python",
        "passed": True,
        "summary": "1 passed",
    }
    base = {
        "candidate_git_sha": "a" * 40,
        "rollback_compatible_prior_sha": "c" * 40,
        "schema_version": "newcaostone.local-verification.v1",
        "checks": [valid],
    }
    for injected in (
        {
            "command": "extra",
            "name": "extra",
            "passed": True,
            "summary": "must-not-enter-manifest",
        },
        {
            "command": "extra",
            "name": "python",
            "passed": True,
            "summary": "must-not-enter-manifest",
        },
    ):
        evidence = {**base, "checks": [injected, valid]}
        with pytest.raises(
            ReleaseVerificationError,
            match="release_evidence_(?:gate_set|duplicate)_invalid",
        ):
            validate_evidence(
                evidence,
                candidate_git_sha="a" * 40,
                rollback_sha="c" * 40,
                required_checks={"python"},
            )


def test_manifest_creator_has_no_external_evidence_input() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/create_release_manifest.py", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "--evidence" not in completed.stdout
    assert "--candidate-image-digest" in completed.stdout


def test_manifest_accepts_only_exact_linux_amd64_candidate_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = "a" * 40
    digest = "sha256:" + "b" * 64
    image_input = "c" * 64

    class Completed:
        returncode = 0
        stdout = json.dumps(
            [
                {
                    "Id": digest,
                    "Os": "linux",
                    "Architecture": "amd64",
                    "Config": {
                        "Labels": {
                            "org.opencontainers.image.revision": candidate,
                            "org.opencontainers.image.bizpulse.image-input-sha256": image_input,
                        }
                    },
                }
            ]
        )

    monkeypatch.setattr(
        create_release_manifest_module.subprocess,
        "run",
        lambda *args, **kwargs: Completed(),
    )
    validate_local_candidate_image(
        candidate_git_sha=candidate,
        candidate_image_digest=digest,
        expected_image_input_sha256=image_input,
    )

    projection = json.loads(Completed.stdout)
    projection[0]["Architecture"] = "arm64"
    Completed.stdout = json.dumps(projection)
    with pytest.raises(ReleaseManifestInvalid, match="candidate_image_identity_invalid"):
        validate_local_candidate_image(
            candidate_git_sha=candidate,
            candidate_image_digest=digest,
            expected_image_input_sha256=image_input,
        )


def test_attestation_requires_freshly_reproduced_candidate_evidence() -> None:
    attested = {"candidate_git_sha": "a" * 40, "checks": [{"name": "python"}]}
    reproduced = json.loads(json.dumps(attested))
    reproduced["checks"][0]["summary"] = "338 passed"

    with pytest.raises(
        ReleaseManifestInvalid,
        match="attestation_evidence_not_reproduced",
    ):
        assert_reproduced_evidence(attested, reproduced)

    source = Path(create_release_manifest_module.__file__).read_text()
    verifier = source[source.index("def verify_attestation"):]
    assert "_reverify_committed_candidate(" in verifier
    assert "assert_reproduced_evidence(" in verifier


def test_attestation_reverification_budget_covers_the_full_release_gate() -> None:
    timeout_seconds = getattr(
        create_release_manifest_module,
        "ATTESTATION_VERIFICATION_TIMEOUT_SECONDS",
        0,
    )
    source = Path(create_release_manifest_module.__file__).read_text()
    reverify = source[
        source.index("def _reverify_committed_candidate") : source.index(
            "def verify_attestation"
        )
    ]

    assert timeout_seconds >= 30 * 60
    assert "timeout=ATTESTATION_VERIFICATION_TIMEOUT_SECONDS" in reverify


def test_attestation_dependency_path_is_version_verified_and_explicit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "azurite-blob"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    monkeypatch.setenv(
        "BIZPULSE_TEST_AZURITE_BLOB_EXECUTABLE",
        str(executable),
    )

    class Completed:
        returncode = 0
        stdout = json.loads((PROJECT_ROOT / "package-lock.json").read_text())[
            "packages"
        ]["node_modules/azurite"]["version"]

    monkeypatch.setattr(
        create_release_manifest_module.subprocess,
        "run",
        lambda *args, **kwargs: Completed(),
    )

    assert _verified_azurite_executable() == executable.resolve()
    assert _azurite_blob_executable() == executable.resolve()


def test_release_verifier_rechecks_exact_candidate_after_all_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Completed:
        returncode = 0

    monkeypatch.setattr(
        verify_release_module.subprocess,
        "run",
        lambda *args, **kwargs: Completed(),
    )
    monkeypatch.setattr(
        verify_release_module,
        "git_output",
        lambda *args: "a" * 40,
    )
    monkeypatch.setattr(
        verify_release_module,
        "_static_checks",
        lambda *args, **kwargs: {
            "command": "static",
            "name": "static_release_boundaries",
            "passed": True,
            "summary": "passed",
        },
    )
    monkeypatch.setattr(
        verify_release_module,
        "_run_gate",
        lambda name, command: events.append(name) or {
            "command": " ".join(command),
            "name": name,
            "passed": True,
            "summary": "passed",
        },
    )
    monkeypatch.setattr(
        verify_release_module,
        "assert_additive_migration_compatibility",
        lambda _identity: None,
    )
    monkeypatch.setattr(
        verify_release_module,
        "assert_candidate_unchanged",
        lambda *args, **kwargs: events.append("candidate_rechecked"),
        raising=False,
    )

    verify_release_module.verify_release(
        SYNTHETIC_MANIFEST,
        allow_dirty=False,
        skip_tests=False,
        identity=verify_release_module.ReleaseIdentity(
            rollback_sha="c" * 40,
            rollback_image_digest="sha256:" + "d" * 64,
            migration_head="0008_ai_budget_ledger",
            current_authority_evidence_sha256="e" * 64,
        ),
    )

    assert events[0] == "authority_contract"
    assert events[-1] == "candidate_rechecked"
    assert "browser" in events[:-1]


def test_manifest_rechecks_candidate_immediately_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Path(create_release_manifest_module.__file__).read_text()

    assert "assert_candidate_unchanged(" in source
    assert source.index("assert_candidate_unchanged(") < source.index(
        "output.write_text(serialized)"
    )


def test_final_candidate_recheck_rejects_gate_created_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def changed_git_output(*arguments: str) -> str:
        if arguments == ("rev-parse", "HEAD"):
            return "a" * 40
        if arguments[0] == "status":
            return "?? gate-created.txt"
        raise AssertionError(arguments)

    monkeypatch.setattr(verify_release_module, "git_output", changed_git_output)

    with pytest.raises(ReleaseVerificationError, match="git_status_not_clean"):
        verify_release_module.assert_candidate_unchanged(
            "a" * 40,
            SYNTHETIC_MANIFEST,
            allow_dirty=False,
            identity=verify_release_module.ReleaseIdentity(
                rollback_sha="c" * 40,
                rollback_image_digest="sha256:" + "d" * 64,
                migration_head="0008_ai_budget_ledger",
                current_authority_evidence_sha256="e" * 64,
            ),
        )

def test_manifest_contains_hashes_names_and_truthful_local_claims() -> None:
    commands = expected_gate_commands()
    evidence = {
        "candidate_git_sha": "a" * 40,
        "rollback_compatible_prior_sha": "c" * 40,
        "schema_version": "newcaostone.local-verification.v1",
        "checks": [
            {
                "command": commands[name],
                "name": name,
                "passed": True,
                "summary": "1 passed",
            }
            for name in REQUIRED_TEST_CHECKS
        ],
    }
    payload = build_release_manifest(
        candidate_git_sha="a" * 40,
        candidate_git_tree="b" * 40,
        candidate_committed_at="2026-08-14T12:00:00+00:00",
        candidate_image_digest="sha256:" + "5" * 64,
        rollback_sha="c" * 40,
        rollback_image_digest="sha256:" + "3" * 64,
        rollback_image_input_sha256="2" * 64,
        candidate_migration_head="0008_ai_budget_ledger",
        current_authority_evidence_sha256="4" * 64,
        generated_at="2026-08-15T00:00:00Z",
        synthetic_manifest_path="tests/fixtures/synthetic/v1/manifest.json",
        synthetic_manifest_sha256="d" * 64,
        generator_source_sha256="e" * 64,
        dependency_hashes={"requirements.txt": "f" * 64},
        evidence=evidence,
        evidence_sha256="1" * 64,
        configuration_names=("BIZPULSE_DATABASE_URL", "BIZPULSE_SESSION_PEPPER"),
    )

    serialized = json.dumps(payload, sort_keys=True)
    assert payload["candidate_git_sha"] == "a" * 40
    assert payload["migration_head"] == "0008_ai_budget_ledger"
    assert payload["claims"] == {
        "accepted": False,
        "ci_verified": False,
        "deployed": False,
        "hosted_verified": False,
        "local_verified": True,
        "production_ready": False,
    }
    assert "BIZPULSE_SESSION_PEPPER" in payload["configuration_names"]
    assert "pepper-value" not in serialized
    assert payload["verification_evidence"]["sha256"] == "1" * 64
    assert payload["rollback_image_input_sha256"] == "2" * 64
    assert payload["schema_version"] == "newcaostone.integrated-release.v4"
    assert payload["candidate_image"] == {
        "digest": "sha256:" + "5" * 64,
        "image_input_sha256": payload["image_input_sha256"],
        "platform": "linux/amd64",
        "source_revision": "a" * 40,
    }
    assert payload["release_package_contract"] == {
        "ai_revision_requires": [
            "data_scope_revision_receipt",
            "model_qualification_receipt",
        ],
        "data_scope_revision_ai_enabled": False,
        "model_qualification_case_count": 12,
        "stage_order": ["data_scope_revision", "ai_revision"],
    }
    assert payload["rollback_image_digest"] == "sha256:" + "3" * 64
    assert payload["current_authority_evidence_sha256"] == "4" * 64
    assert payload["generated_at"] == "2026-08-15T00:00:00Z"
    assert payload["attestation_policy"] == {
        "allowed_paths": [
            "bizpulse/release/attestations/" + "a" * 40 + ".json"
        ],
        "commit_parent_must_equal_candidate": True,
    }

    tampered = json.loads(json.dumps(payload))
    tampered["claims"]["production_ready"] = True
    with pytest.raises(ReleaseManifestInvalid, match="attestation_payload_mismatch"):
        assert_exact_manifest(tampered, payload)


def test_task15_successor_attestation_path_is_candidate_addressed() -> None:
    candidate = "a" * 40

    assert create_release_manifest_module.attestation_path(candidate) == (
        f"bizpulse/release/attestations/{candidate}.json"
    )
    assert create_release_manifest_module.attestation_path(
        "3e933d083b3ab4dba36d8053f56ecf2d68d31f1e"
    ) == "bizpulse/release/task15-local-release-manifest.json"
    with pytest.raises(ReleaseManifestInvalid, match="release_commit_invalid"):
        create_release_manifest_module.attestation_path("not-a-commit")


def test_manifest_cli_reports_success_for_a_candidate_addressed_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = "a" * 40
    monkeypatch.setattr(
        create_release_manifest_module,
        "_resolve_commit",
        lambda _revision: candidate,
    )
    monkeypatch.setattr(
        create_release_manifest_module,
        "create_manifest",
        lambda **_kwargs: {"candidate_git_sha": candidate},
    )

    assert create_release_manifest_module.main(["--candidate-sha", candidate]) == 0
    output = capsys.readouterr().out

    assert "release_manifest=ok" in output
    assert f"candidate_git_sha={candidate}" in output
    assert f"output=release/attestations/{candidate}.json" in output


def test_rollback_probe_reads_attested_identity_without_a_source_literal() -> None:
    rollback_probe = (
        PROJECT_ROOT / "tests/acceptance/test_rollback_compatibility.py"
    ).read_text()

    assert "ROLLBACK_SHA" not in rollback_probe
    assert "rollback_identity" in rollback_probe


def test_candidate_identity_captures_fresh_current_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority_path = tmp_path / "current_authority.json"
    authority_path.write_text(
        json.dumps(
            {
                "attested_rollback": {
                    "candidate_attestation_path": (
                        "release/attestations/" + "a" * 40 + ".json"
                    ),
                    "git_sha": "a" * 40,
                    "image_digest": "sha256:" + "b" * 64,
                },
                "development": {
                    "ai_capability_state": "implemented",
                    "repository_migration_head": "0008_ai_budget_ledger",
                },
                "freshness": {
                    "evidence_kind": "sanitized_azure_readback",
                    "evidence_sha256": "c" * 64,
                    "expires_at": "2026-08-16T00:00:00Z",
                    "observed_at": "2026-08-15T00:00:00Z",
                },
                "observed_deployment": {
                    "ai_runtime_state": "disabled",
                    "attestation_git_sha": "d" * 40,
                    "candidate_git_sha": "a" * 40,
                    "database_migration_head": "0008_ai_budget_ledger",
                    "image_digest": "sha256:" + "b" * 64,
                    "revision": "newcaostone-demo-app--bbbbbbbbbbbb",
                },
                "prepared_candidate": None,
                "schema_version": "bizpulse.current-authority.v1",
            }
        )
    )
    monkeypatch.setattr(
        create_release_manifest_module,
        "migration_head",
        lambda: "0008_ai_budget_ledger",
    )

    identity = create_release_manifest_module.release_identity_from_authority(
        authority_path,
        now=datetime(2026, 8, 15, 12, tzinfo=UTC),
    )

    assert identity.rollback_sha == "a" * 40
    assert identity.rollback_image_digest == "sha256:" + "b" * 64
    assert identity.migration_head == "0008_ai_budget_ledger"
    assert identity.current_authority_evidence_sha256 == "c" * 64


def test_attestation_identity_ignores_later_current_authority_changes() -> None:
    manifest = {
        "current_authority_evidence_sha256": "c" * 64,
        "migration_head": "0008_ai_budget_ledger",
        "rollback_compatible_prior_sha": "a" * 40,
        "rollback_image_digest": "sha256:" + "b" * 64,
    }

    identity = verify_release_module.attested_release_identity(manifest)

    assert identity.rollback_sha == "a" * 40


def test_migration_compatibility_requires_rollback_head_in_candidate_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = verify_release_module.ReleaseIdentity(
        rollback_sha="a" * 40,
        rollback_image_digest="sha256:" + "b" * 64,
        migration_head=verify_release_module.migration_head(),
        current_authority_evidence_sha256="c" * 64,
    )
    monkeypatch.setattr(
        verify_release_module,
        "rollback_migration_heads",
        lambda _revision: ("missing_revision",),
    )

    with pytest.raises(
        ReleaseVerificationError,
        match="rollback_migration_not_additive",
    ):
        verify_release_module.assert_additive_migration_compatibility(identity)


def test_release_modules_have_no_mutable_identity_constants() -> None:
    sources = (
        Path(verify_release_module.__file__).read_text(),
        Path(create_release_manifest_module.__file__).read_text(),
    )

    assert all("EXPECTED_MIGRATION_HEAD" not in source for source in sources)
    assert all("VERIFIED_ROLLBACK_SHA" not in source for source in sources)


def test_dirty_development_verifier_is_path_safe_and_secret_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "must-not-appear-in-release-output"
    monkeypatch.setenv("BIZPULSE_SESSION_PEPPER", sentinel)
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/verify_release.py",
            "--manifest",
            str(SYNTHETIC_MANIFEST),
            "--allow-dirty",
            "--skip-tests",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "development_static_check=ok" in completed.stdout
    assert "release_verification=ok" not in completed.stdout
    assert sentinel not in completed.stdout + completed.stderr


def test_partial_release_incident_allowlist_is_narrow() -> None:
    assert verify_release_module.is_allowed_non_source_json(
        "bizpulse/release/incidents/2026-08-16-two-stage-partial-failure.json"
    )
    assert not verify_release_module.is_allowed_non_source_json(
        "bizpulse/release/incidents/secrets.json"
    )
    assert not verify_release_module.is_allowed_non_source_json(
        "bizpulse/release/incidents/2026-08-16-partial-failure.json.backup"
    )


def test_operator_upload_receipt_allowlist_is_narrow() -> None:
    assert verify_release_module.is_allowed_non_source_json(
        "bizpulse/deliverables/closeout/operator-upload-receipt.json"
    )
    assert not verify_release_module.is_allowed_non_source_json(
        "bizpulse/deliverables/closeout/unrelated.json"
    )


def test_release_verifier_reports_only_a_stable_failure_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    identity = verify_release_module.ReleaseIdentity(
        rollback_sha="a" * 40,
        rollback_image_digest="sha256:" + "b" * 64,
        migration_head=verify_release_module.migration_head(),
        current_authority_evidence_sha256="c" * 64,
    )
    monkeypatch.setattr(
        verify_release_module,
        "current_release_identity",
        lambda _path: identity,
    )

    def fail_gate(*_args, **_kwargs):
        raise ReleaseVerificationError("release_gate_failed:python")

    monkeypatch.setattr(verify_release_module, "verify_release", fail_gate)

    assert verify_release_module.main(
        ["--manifest", str(SYNTHETIC_MANIFEST)]
    ) == 1
    assert capsys.readouterr().out.splitlines() == [
        "release_verification=failed",
        "release_failure_code=release_gate_failed:python",
    ]


def test_release_verifier_redacts_an_unstable_failure_value(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    identity = verify_release_module.ReleaseIdentity(
        rollback_sha="a" * 40,
        rollback_image_digest="sha256:" + "b" * 64,
        migration_head=verify_release_module.migration_head(),
        current_authority_evidence_sha256="c" * 64,
    )
    monkeypatch.setattr(
        verify_release_module,
        "current_release_identity",
        lambda _path: identity,
    )

    def fail_with_value(*_args, **_kwargs):
        raise ReleaseVerificationError("unsafe /Users/example secret")

    monkeypatch.setattr(verify_release_module, "verify_release", fail_with_value)

    assert verify_release_module.main(
        ["--manifest", str(SYNTHETIC_MANIFEST)]
    ) == 1
    output = capsys.readouterr().out
    assert output.splitlines() == [
        "release_verification=failed",
        "release_failure_code=release_verification_failed",
    ]
    assert "/Users/" not in output
    assert "secret" not in output


def test_dirty_verifier_cannot_emit_attestable_evidence(tmp_path: Path) -> None:
    output = tmp_path / "evidence.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/verify_release.py",
            "--manifest",
            str(SYNTHETIC_MANIFEST),
            "--allow-dirty",
            "--skip-tests",
            "--evidence-output",
            str(output),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "release_verification=failed" in completed.stdout
    assert not output.exists()


def test_dirty_verifier_cannot_claim_complete_release() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/verify_release.py",
            "--manifest",
            str(SYNTHETIC_MANIFEST),
            "--allow-dirty",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "release_verification=ok" not in completed.stdout


def test_manifest_builder_rejects_incomplete_evidence() -> None:
    with pytest.raises(ReleaseManifestInvalid, match="release_evidence_incomplete"):
        build_release_manifest(
            candidate_git_sha="a" * 40,
            candidate_git_tree="b" * 40,
            candidate_committed_at="2026-08-14T12:00:00+00:00",
            candidate_image_digest="sha256:" + "5" * 64,
            rollback_sha="c" * 40,
            rollback_image_digest="sha256:" + "3" * 64,
            rollback_image_input_sha256="2" * 64,
            candidate_migration_head="0008_ai_budget_ledger",
            current_authority_evidence_sha256="4" * 64,
            generated_at="2026-08-15T00:00:00Z",
            synthetic_manifest_path="tests/fixtures/synthetic/v1/manifest.json",
            synthetic_manifest_sha256="d" * 64,
            generator_source_sha256="e" * 64,
            dependency_hashes={"requirements.txt": "f" * 64},
            evidence={
                "candidate_git_sha": "a" * 40,
                "checks": [],
                "rollback_compatible_prior_sha": "c" * 40,
                "schema_version": "newcaostone.local-verification.v1",
            },
            evidence_sha256="1" * 64,
            configuration_names=("BIZPULSE_DATABASE_URL",),
        )


def test_manifest_generator_is_directly_executable() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/create_release_manifest.py", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "--synthetic-manifest" in completed.stdout


def test_gate_evidence_redacts_absolute_python_interpreter_path() -> None:
    evidence = _run_gate(
        "probe",
        [sys.executable, "-c", "print('1 passed')"],
    )

    assert evidence["command"] == "python -c print('1 passed')"
    assert evidence["summary"] == "1 passed"
    assert "/Users/" not in json.dumps(evidence)


def test_gate_evidence_normalizes_variable_test_duration() -> None:
    evidence = _run_gate(
        "probe",
        [sys.executable, "-c", "print('17 passed in 9.876s')"],
    )

    assert evidence["summary"] == "17 passed"
