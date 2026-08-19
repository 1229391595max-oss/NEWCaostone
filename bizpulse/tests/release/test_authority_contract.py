from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from scripts.release_authority import (
    AuthorityInvalid,
    apply_authority_bundle_atomic,
    check_authority_documents,
    load_current_authority,
    load_document_policy,
    refresh_current_authority,
    render_authority_blocks,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _authority_payload(
    *,
    observed_image: str = "sha256:" + "a" * 64,
    rollback_image: str = "sha256:" + "b" * 64,
    expires_at: str = "2026-08-16T00:00:00Z",
) -> dict[str, object]:
    return {
        "attested_rollback": {
            "candidate_attestation_path": (
                "release/attestations/" + "d" * 40 + ".json"
            ),
            "git_sha": "d" * 40,
            "image_digest": rollback_image,
        },
        "development": {
            "ai_capability_state": "implemented",
            "repository_migration_head": "0008_ai_budget_ledger",
        },
        "freshness": {
            "evidence_kind": "sanitized_azure_readback",
            "evidence_sha256": "e" * 64,
            "expires_at": expires_at,
            "observed_at": "2026-08-15T00:00:00Z",
        },
        "observed_deployment": {
            "ai_runtime_state": "disabled",
            "attestation_git_sha": "f" * 40,
            "candidate_git_sha": "a" * 40,
            "database_migration_head": "0008_ai_budget_ledger",
            "image_digest": observed_image,
            "revision": "newcaostone-demo-app--" + "a" * 12,
        },
        "prepared_candidate": None,
        "schema_version": "bizpulse.current-authority.v1",
    }


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _policy(*paths: str) -> dict[str, object]:
    return {
        "schema_version": "bizpulse.authority-document-policy.v1",
        "documents": [{"path": path} for path in paths],
    }


def test_observed_image_and_attested_rollback_are_independent(tmp_path: Path) -> None:
    authority = load_current_authority(
        _write_json(tmp_path / "authority.json", _authority_payload())
    )

    assert authority.observed_deployment.image_digest.endswith("a" * 64)
    assert authority.attested_rollback.image_digest.endswith("b" * 64)


def test_active_old_sha_reports_exact_file_and_line(tmp_path: Path) -> None:
    authority = load_current_authority(
        _write_json(tmp_path / "authority.json", _authority_payload())
    )
    status = tmp_path / "CURRENT_STATUS.md"
    status.write_text("# Status\n## Current\nDeploy `" + "c" * 40 + "` next.\n")

    violations = check_authority_documents(
        authority,
        _policy("CURRENT_STATUS.md"),
        tmp_path,
    )

    assert violations[0].render().startswith(
        "authority_doc_drift:CURRENT_STATUS.md:3:"
        "observed_deployment.candidate_git_sha:"
        "expected=" + "a" * 40 + ":actual=" + "c" * 40
    )


def test_history_value_is_allowed_but_not_in_a_command_block(tmp_path: Path) -> None:
    authority = load_current_authority(
        _write_json(tmp_path / "authority.json", _authority_payload())
    )
    document = tmp_path / "CURRENT_STATUS.md"
    document.write_text(
        "# Status\n"
        "<!-- authority:history:start -->\n"
        "Historical candidate `" + "c" * 40 + "`.\n"
        "```sh\n"
        "deploy " + "c" * 40 + "\n"
        "```\n"
        "<!-- authority:history:end -->\n"
    )

    violations = check_authority_documents(
        authority,
        _policy("CURRENT_STATUS.md"),
        tmp_path,
    )

    assert violations[0].line == 5


def test_current_block_does_not_make_inactive_prose_active(tmp_path: Path) -> None:
    authority = load_current_authority(
        _write_json(tmp_path / "authority.json", _authority_payload())
    )
    document = tmp_path / "CURRENT_STATUS.md"
    document.write_text("# Status\n")
    render_authority_blocks(
        authority,
        _policy("CURRENT_STATUS.md"),
        tmp_path,
    )
    document.write_text(
        document.read_text()
        + "## Archived release\n"
        + "Archived candidate `"
        + "c" * 40
        + "`.\n"
    )

    assert check_authority_documents(
        authority,
        _policy("CURRENT_STATUS.md"),
        tmp_path,
    ) == ()


def test_release_mode_rejects_an_expired_observation(tmp_path: Path) -> None:
    path = _write_json(
        tmp_path / "authority.json",
        _authority_payload(expires_at="2026-08-15T17:00:00Z"),
    )

    with pytest.raises(AuthorityInvalid, match="authority_observation_stale"):
        load_current_authority(
            path,
            now=datetime(2026, 8, 15, 17, 0, 1, tzinfo=UTC),
            require_fresh_observation=True,
        )


def test_rendered_current_block_round_trips_without_document_drift(
    tmp_path: Path,
) -> None:
    authority = load_current_authority(
        _write_json(tmp_path / "authority.json", _authority_payload())
    )
    status = tmp_path / "CURRENT_STATUS.md"
    status.write_text("# Status\n\nHistorical notes remain.\n")
    policy = _policy("CURRENT_STATUS.md")

    assert render_authority_blocks(authority, policy, tmp_path) == (status,)
    assert check_authority_documents(authority, policy, tmp_path) == ()
    source = status.read_text()
    assert source.count("<!-- authority:current:start -->") == 1
    assert "Historical notes remain." in source


def test_authority_schema_rejects_unknown_fields(tmp_path: Path) -> None:
    payload = _authority_payload()
    payload["unexpected"] = True

    with pytest.raises(AuthorityInvalid, match="authority_keys_invalid"):
        load_current_authority(_write_json(tmp_path / "authority.json", payload))


def test_document_policy_rejects_parent_traversal(tmp_path: Path) -> None:
    policy = _write_json(
        tmp_path / "policy.json",
        _policy("../outside.md"),
    )

    with pytest.raises(AuthorityInvalid, match="authority_document_policy_invalid"):
        load_document_policy(policy)


def test_refresh_binds_observation_to_matching_checked_in_attestation(
    tmp_path: Path,
) -> None:
    candidate = "a" * 40
    attestation_dir = tmp_path / "release" / "attestations"
    attestation_dir.mkdir(parents=True)
    _write_json(
        attestation_dir / f"{candidate}.json",
        {
            "candidate_git_sha": candidate,
            "image_input_sha256": "e" * 64,
            "migration_head": "0008_ai_budget_ledger",
        },
    )

    payload = refresh_current_authority(
        {
            "ai_runtime_state": "disabled",
            "attestation_git_sha": "f" * 40,
            "candidate_git_sha": candidate,
            "database_migration_head": "0008_ai_budget_ledger",
            "evidence_kind": "sanitized_azure_readback",
            "evidence_sha256": "e" * 64,
            "image_digest": "sha256:" + "b" * 64,
            "revision": "newcaostone-demo-app--" + "b" * 12,
        },
        attestation_dir,
        observed_at=datetime(2026, 8, 15, tzinfo=UTC),
        expires_at=datetime(2026, 8, 16, tzinfo=UTC),
    )

    assert payload["observed_deployment"]["candidate_git_sha"] == candidate
    assert payload["attested_rollback"] == {
        "candidate_attestation_path": f"release/attestations/{candidate}.json",
        "git_sha": candidate,
        "image_digest": "sha256:" + "b" * 64,
    }


def test_refresh_rejects_an_unbound_observation(tmp_path: Path) -> None:
    attestation_dir = tmp_path / "release" / "attestations"
    attestation_dir.mkdir(parents=True)

    with pytest.raises(AuthorityInvalid, match="authority_observation_unbound"):
        refresh_current_authority(
            {
                "ai_runtime_state": "disabled",
                "attestation_git_sha": "f" * 40,
                "candidate_git_sha": "a" * 40,
                "database_migration_head": "0008_ai_budget_ledger",
                "evidence_kind": "sanitized_azure_readback",
                "evidence_sha256": "e" * 64,
                "image_digest": "sha256:" + "b" * 64,
                "revision": "newcaostone-demo-app--" + "b" * 12,
            },
            attestation_dir,
            observed_at=datetime(2026, 8, 15, tzinfo=UTC),
            expires_at=datetime(2026, 8, 16, tzinfo=UTC),
        )


def test_readonly_refresh_preserves_rollback_and_prepared_authority(
    tmp_path: Path,
) -> None:
    current_payload = _authority_payload()
    current_payload["prepared_candidate"] = {
        "state": "historical_prepared_boundary",
        "candidate_git_sha": "9" * 40,
    }
    current = load_current_authority(
        _write_json(tmp_path / "current.json", current_payload)
    )
    observation = {
        "ai_runtime_state": "disabled",
        "attestation_git_sha": "1" * 40,
        "candidate_git_sha": "2" * 40,
        "database_migration_head": "0014_import_base_lineage",
        "evidence_kind": "sanitized_azure_readback",
        "evidence_sha256": "3" * 64,
        "image_digest": "sha256:" + "4" * 64,
        "revision": "newcaostone-demo-app--ai-off-12345678-1234567",
    }
    verified_provenance = {
        "attestation_git_sha": "1" * 40,
        "candidate_git_sha": "2" * 40,
        "image_digest": "sha256:" + "4" * 64,
        "revision": "newcaostone-demo-app--ai-off-12345678-1234567",
    }

    payload = refresh_current_authority(
        observation,
        None,
        observed_at=datetime(2026, 8, 18, 20, tzinfo=UTC),
        expires_at=datetime(2026, 8, 18, 21, tzinfo=UTC),
        current_authority=current,
        verified_provenance=verified_provenance,
    )

    assert payload["attested_rollback"] == current_payload["attested_rollback"]
    assert payload["prepared_candidate"] == current_payload["prepared_candidate"]
    assert payload["observed_deployment"]["candidate_git_sha"] == "2" * 40
    assert payload["freshness"]["evidence_sha256"] == "3" * 64


def test_atomic_authority_bundle_restores_every_target_on_replace_failure(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    project = repository / "bizpulse"
    authority_path = project / "release/current_authority.json"
    authority_path.parent.mkdir(parents=True)
    status = repository / "CURRENT_STATUS.md"
    ledger = repository / "AUTHORIZATION_LEDGER.md"
    status.write_text("# Status\n")
    ledger.write_text("# Ledger\n")
    policy = _policy("CURRENT_STATUS.md", "AUTHORIZATION_LEDGER.md")
    original_payload = _authority_payload()
    _write_json(authority_path, original_payload)
    original = {
        authority_path: authority_path.read_bytes(),
        status: status.read_bytes(),
        ledger: ledger.read_bytes(),
    }
    refreshed_payload = _authority_payload(
        observed_image="sha256:" + "9" * 64,
        expires_at="2026-08-19T00:00:00Z",
    )
    refreshed = load_current_authority(
        _write_json(tmp_path / "refreshed.json", refreshed_payload)
    )
    replacements = 0

    def fail_second_replace(source: Path, destination: Path) -> None:
        nonlocal replacements
        replacements += 1
        if replacements == 2:
            raise OSError("injected replace failure")
        source.replace(destination)

    with pytest.raises(AuthorityInvalid, match="authority_bundle_write_failed"):
        apply_authority_bundle_atomic(
            authority_path=authority_path,
            authority=refreshed,
            policy=policy,
            repository_root=repository,
            replacer=fail_second_replace,
        )

    assert {path: path.read_bytes() for path in original} == original


def test_atomic_authority_bundle_updates_authority_and_generated_documents(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    project = repository / "bizpulse"
    authority_path = project / "release/current_authority.json"
    authority_path.parent.mkdir(parents=True)
    status = repository / "CURRENT_STATUS.md"
    status.write_text("# Status\n\nHistorical status.\n")
    policy = _policy("CURRENT_STATUS.md")
    _write_json(authority_path, _authority_payload())
    refreshed = load_current_authority(
        _write_json(
            tmp_path / "refreshed.json",
            _authority_payload(
                observed_image="sha256:" + "9" * 64,
                expires_at="2026-08-19T00:00:00Z",
            ),
        )
    )
    staged_modes: list[int] = []

    def replace_owner_only_stage(source: Path, destination: Path) -> None:
        staged_modes.append(stat.S_IMODE(source.lstat().st_mode))
        source.replace(destination)

    apply_authority_bundle_atomic(
        authority_path=authority_path,
        authority=refreshed,
        policy=policy,
        repository_root=repository,
        replacer=replace_owner_only_stage,
    )

    assert staged_modes == [0o600, 0o600]
    assert stat.S_IMODE(authority_path.lstat().st_mode) == 0o644
    assert stat.S_IMODE(status.lstat().st_mode) == 0o644
    assert load_current_authority(authority_path) == refreshed
    assert check_authority_documents(refreshed, policy, repository) == ()
    assert "Historical status." in status.read_text()


def test_document_check_cli_reports_machine_readable_success(tmp_path: Path) -> None:
    authority_path = _write_json(
        tmp_path / "authority.json",
        _authority_payload(),
    )
    status = tmp_path / "CURRENT_STATUS.md"
    status.write_text("# Status\n")
    policy_path = _write_json(
        tmp_path / "policy.json",
        _policy("CURRENT_STATUS.md"),
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts/check_authority_contract.py"),
            "--mode",
            "docs",
            "--authority",
            str(authority_path),
            "--document-policy",
            str(policy_path),
            "--repository-root",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "authority_contract=ok"


def test_repository_only_refresh_preserves_observed_deployment(tmp_path: Path) -> None:
    authority_path = _write_json(
        tmp_path / "authority.json",
        _authority_payload(),
    )
    status = tmp_path / "CURRENT_STATUS.md"
    status.write_text("# Status\n")
    policy_path = _write_json(
        tmp_path / "policy.json",
        _policy("CURRENT_STATUS.md"),
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts/refresh_current_authority.py"),
            "--repository-only",
            "--output",
            str(authority_path),
            "--document-policy",
            str(policy_path),
            "--repository-root",
            str(tmp_path),
            "--project-root",
            str(PROJECT_ROOT),
            "--write-documents",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "current_authority=updated"
    payload = json.loads(authority_path.read_text())
    assert payload["observed_deployment"]["candidate_git_sha"] == "a" * 40
    assert payload["development"] == {
        "ai_capability_state": "implemented",
        "repository_migration_head": "0017_ai_turn_credential_binding",
    }
    assert CURRENT_AUTHORITY_MARKER in status.read_text()


CURRENT_AUTHORITY_MARKER = "<!-- authority:current:start -->"
