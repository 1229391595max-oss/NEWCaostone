from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.select_required_checks import (
    Check,
    DomainPolicy,
    VerificationPolicyError,
    can_reuse,
    domain_fingerprint,
    load_verification_policy,
    select_required_checks,
)
from scripts.verify_changed import (
    FullReleaseRequired,
    changed_paths,
    combined_domain_fingerprint,
    execute_check,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
POLICY = load_verification_policy(PROJECT_ROOT / "release/verification-policy.json")


def test_current_admin_ai_successor_contract_selects_authority_and_release_gates() -> None:
    selected = select_required_checks(
        ("bizpulse/scripts/admin_ai_current_successor.py",),
        POLICY,
    )

    assert {item.name for item in selected} == {
        "ai_focused",
        "ai_infra_boundary",
        "authority_contract",
        "browser_local",
        "frontend",
        "release_static",
    }


@pytest.mark.parametrize(
    ("paths", "names"),
    [
        (("CURRENT_STATUS.md",), ("authority_contract",)),
        (
            ("bizpulse/frontend/assets/views.mjs",),
            ("frontend", "browser_local"),
        ),
        (
            ("bizpulse/scripts/browser_release_gate.mjs",),
            ("frontend", "browser_local"),
        ),
        (
            ("bizpulse/src/ai/prompt_catalog.py",),
            ("ai_focused", "frontend", "browser_local"),
        ),
        (
            ("bizpulse/api/v1/routers/ai_chat.py",),
            ("ai_focused", "frontend", "browser_local"),
        ),
        (
            ("bizpulse/infra/main.bicep",),
            ("ai_infra_boundary", "release_static"),
        ),
        (
            ("bizpulse/src/synthetic/generator.py",),
            ("synthetic", "postgres_seed", "browser_local"),
        ),
            (
                ("bizpulse/api/container.py",),
                (
                    "library_focused",
                    "frontend",
                    "browser_local",
                    "public_release_focused",
                    "postgres_seed",
                ),
            ),
            (
                ("bizpulse/src/services/library_service.py",),
                ("library_focused", "frontend", "browser_local"),
            ),
        (
            ("bizpulse/src/services/store_scope.py",),
            (
                "library_focused",
                "frontend",
                "browser_local",
                "public_release_focused",
                "postgres_seed",
            ),
        ),
        (
            ("bizpulse/src/actions/simulation.py",),
            ("actions_focused", "browser_local"),
        ),
        (
            ("bizpulse/src/services/business_keys.py",),
            ("imports_focused", "browser_local"),
        ),
        (
            ("bizpulse/src/services/canonical_contracts.py",),
            ("imports_focused", "browser_local"),
        ),
        (
            ("bizpulse/src/services/canonical_dataset_assembler.py",),
            ("imports_focused", "browser_local"),
        ),
        (
            ("bizpulse/tests/property/test_canonical_dataset_assembler.py",),
            ("imports_focused", "browser_local"),
        ),
        (
            ("bizpulse/api/dependencies/session.py",),
            ("viewer_session_focused", "browser_local"),
        ),
        (
            ("bizpulse/api/routers/demo_preferences.py",),
            ("preferences_focused", "frontend", "browser_local"),
        ),
        (
            ("bizpulse/tests/security/test_upload_boundary.py",),
            ("public_release_focused", "postgres_seed", "browser_local"),
        ),
        (
            ("bizpulse/alembic/versions/0009_prompt_preset_audit.py",),
            ("migration", "restart", "rollback"),
        ),
        (
            ("bizpulse/src/db/schema.py",),
            ("migration", "restart", "rollback"),
        ),
        (
            ("bizpulse/tests/api/test_application_shell.py",),
            ("migration", "restart", "rollback"),
        ),
        (
            ("bizpulse/tests/integration/test_cloud_prepare.py",),
            ("migration", "restart", "rollback"),
        ),
        (
            ("bizpulse/tests/postgres/test_0008_ai_budget_ledger.py",),
            ("migration", "restart", "rollback"),
        ),
        (
            ("bizpulse/tests/integration/test_session_version_pinning.py",),
            ("public_release_focused", "postgres_seed", "browser_local"),
        ),
        (
            ("bizpulse/tests/hosted/test_phase1_receipt_resume.py",),
            ("release_static",),
        ),
        (
            ("bizpulse/tests/hosted/test_rollback_forward_resume_runner.py",),
            ("release_static",),
        ),
        (
            ("bizpulse/tests/acceptance/test_exact_15_sessions.py",),
            ("exact_15",),
        ),
        (
            ("bizpulse/tests/acceptance/test_viewer_demo_activation_capacity.py",),
            ("exact_15",),
        ),
        (
            ("bizpulse/tests/acceptance/test_browser_smoke.py",),
            ("browser_local",),
        ),
        (
            ("bizpulse/tests/browser/test_corrected_viewer_operator_experience.py",),
            ("browser_local",),
        ),
        (
            ("bizpulse/tests/acceptance/test_rollback_compatibility.py",),
            ("migration", "restart", "rollback", "release_static"),
        ),
        (
            ("bizpulse/release/attestations/" + "a" * 40 + ".json",),
            ("full_release_gate",),
        ),
    ],
)
def test_policy_selects_required_checks(
    paths: tuple[str, ...],
    names: tuple[str, ...],
) -> None:
    assert tuple(item.name for item in select_required_checks(paths, POLICY)) == names


def test_domain_fingerprint_changes_for_unchanged_path_in_same_domain(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.py").write_text("one")
    (tmp_path / "b.py").write_text("two")
    domain = DomainPolicy(
        name="python",
        include=("*.py",),
        exclude=(),
        checks=("python",),
    )

    first = domain_fingerprint(tmp_path, domain)
    (tmp_path / "b.py").write_text("changed")

    assert domain_fingerprint(tmp_path, domain) != first


def test_release_evidence_never_reuses_a_domain_cache() -> None:
    assert POLICY.check("full_release_gate").reuse == "never"


def test_reuse_requires_matching_development_evidence() -> None:
    check = Check(
        name="frontend",
        argv=("npm", "test"),
        reuse="development_only",
    )
    evidence = {
        "schema_version": "bizpulse.development-evidence.v1",
        "check": "frontend",
        "domain_fingerprint": "abc",
        "passed": True,
    }

    assert can_reuse(evidence, check=check, fingerprint="abc") is True
    assert can_reuse(evidence, check=check, fingerprint="changed") is False
    assert can_reuse(evidence, check=POLICY.check("full_release_gate"), fingerprint="abc") is False


def test_unmapped_path_fails_closed() -> None:
    with pytest.raises(
        VerificationPolicyError,
        match="verification_policy_unmapped_path:bizpulse/src/new_module.py",
    ):
        select_required_checks(("bizpulse/src/new_module.py",), POLICY)


def test_action_end_to_end_contract_is_mapped_to_action_checks() -> None:
    for path in (
        "bizpulse/tests/integration/test_action_card_end_to_end.py",
        "bizpulse/tests/security/test_action_export.py",
    ):
        selected = select_required_checks((path,), POLICY)

        assert {item.name for item in selected} == {
            "actions_focused",
            "browser_local",
        }


def test_model_qualification_and_hosted_ai_contracts_are_mapped() -> None:
    qualification = select_required_checks(
        ("bizpulse/scripts/qualify_openai_model.py",),
        POLICY,
    )
    hosted = select_required_checks(
        ("bizpulse/tests/hosted/verify_azure_demo.py",),
        POLICY,
    )

    assert "ai_focused" in {item.name for item in qualification}
    assert {item.name for item in hosted} == {"release_static"}


@pytest.mark.parametrize(
    "path",
    (
        "bizpulse/scripts/ai_enablement_contract.py",
        "bizpulse/scripts/azure_ai_enablement_actions.py",
        "bizpulse/scripts/azure_ai_reconciliation.py",
        "bizpulse/scripts/azure_ai_revision.py",
        "bizpulse/scripts/create_ai_enablement_package.py",
        "bizpulse/scripts/create_release_manifest.py",
        "bizpulse/scripts/publish_registry_image.py",
        "bizpulse/scripts/run_ai_enablement.py",
        "bizpulse/tests/hosted/test_ai_enablement_contract.py",
        "bizpulse/tests/hosted/test_azure_ai_enablement_actions.py",
        "bizpulse/tests/hosted/test_azure_ai_reconciliation.py",
        "bizpulse/tests/hosted/test_azure_ai_revision.py",
        "bizpulse/tests/hosted/test_create_ai_enablement_package.py",
        "bizpulse/tests/hosted/test_publish_registry_image.py",
        "bizpulse/tests/hosted/test_run_ai_enablement.py",
    ),
)
def test_ai_enablement_release_tooling_is_mapped_to_all_safety_gates(
    path: str,
) -> None:
    selected = select_required_checks((path,), POLICY)

    assert {item.name for item in selected} == {
        "ai_focused",
        "ai_infra_boundary",
        "frontend",
        "browser_local",
        "release_static",
    }


def test_release_static_executes_the_registry_publication_boundary_suite() -> None:
    assert "tests/hosted/test_publish_registry_image.py" in POLICY.check(
        "release_static"
    ).argv


@pytest.mark.parametrize(
    "path",
    (
        "bizpulse/scripts/create_two_stage_release_package.py",
        "bizpulse/scripts/create_partial_release_recovery_package.py",
        "bizpulse/scripts/create_seeded_release_recovery_package.py",
        "bizpulse/scripts/create_deployed_release_recovery_package.py",
        "bizpulse/scripts/run_deployed_release_recovery.py",
        "bizpulse/scripts/run_seeded_release_recovery.py",
        "bizpulse/scripts/update_azure_job_binding.py",
        "bizpulse/scripts/verify_partial_release_state.py",
        "bizpulse/scripts/verify_seeded_release_state.py",
        "bizpulse/scripts/verify_deployed_release_state.py",
        "bizpulse/scripts/verify_stage_receipts.py",
        "bizpulse/scripts/secret_boundary.py",
        "bizpulse/scripts/deployed_release_diagnostic_contract.py",
        "bizpulse/scripts/build_deployed_release_desired_projection.py",
        "bizpulse/scripts/create_deployed_release_diagnostic_package.py",
        "bizpulse/scripts/observe_deployed_release_state.py",
        "bizpulse/scripts/run_deployed_release_diagnostic.py",
        "bizpulse/tests/release/test_two_stage_release_package.py",
        "bizpulse/tests/release/test_partial_release_recovery_package.py",
        "bizpulse/tests/release/test_deployed_release_recovery_package.py",
        "bizpulse/tests/hosted/test_verify_partial_release_state.py",
        "bizpulse/tests/hosted/test_verify_seeded_release_state.py",
        "bizpulse/tests/hosted/test_verify_deployed_release_state.py",
        "bizpulse/tests/hosted/test_run_deployed_release_recovery.py",
        "bizpulse/tests/hosted/test_run_seeded_release_recovery.py",
        "bizpulse/tests/hosted/test_update_azure_job_binding.py",
        "bizpulse/tests/release/test_deployed_release_diagnostic_package.py",
        "bizpulse/tests/hosted/test_observe_deployed_release_state.py",
        "bizpulse/tests/hosted/test_run_deployed_release_diagnostic.py",
        (
            "bizpulse/release/incidents/"
            "2026-08-16-recovery-v4-deployed-continuation.json"
        ),
    ),
)
def test_two_stage_release_tooling_is_mapped_to_static_release_gate(
    path: str,
) -> None:
    selected = select_required_checks((path,), POLICY)

    assert {item.name for item in selected} == {"release_static"}


def test_deployed_diagnostic_bicep_projection_keeps_both_infra_gates() -> None:
    selected = select_required_checks(
        ("bizpulse/tests/infra/test_deployed_release_bicep_projection.py",),
        POLICY,
    )

    assert {item.name for item in selected} == {
        "ai_infra_boundary",
        "release_static",
    }


def test_policy_commands_are_argv_arrays() -> None:
    payload = json.loads(
        (PROJECT_ROOT / "release/verification-policy.json").read_text()
    )

    assert all(
        isinstance(item["argv"], list)
        for item in payload["checks"].values()
    )


def test_execute_check_records_metadata_but_not_process_output(tmp_path: Path) -> None:
    check = Check(
        name="safe",
        argv=(sys.executable, "-c", "print('runtime-' + 'output')"),
        reuse="development_only",
    )
    evidence_dir = tmp_path / "evidence"

    assert execute_check(
        check,
        fingerprint="abc",
        project_root=tmp_path,
        evidence_dir=evidence_dir,
    ) == 0

    evidence_path = evidence_dir / "safe.json"
    payload = json.loads(evidence_path.read_text())
    assert payload["argv"] == list(check.argv)
    assert payload["passed"] is True
    assert "runtime-output" not in evidence_path.read_text()
    assert set(payload) == {
        "argv",
        "check",
        "domain_fingerprint",
        "ended_at",
        "exit_code",
        "passed",
        "schema_version",
        "started_at",
    }


def test_full_release_gate_cannot_execute_or_cache(tmp_path: Path) -> None:
    with pytest.raises(FullReleaseRequired, match="full_release_gate_required"):
        execute_check(
            POLICY.check("full_release_gate"),
            fingerprint="abc",
            project_root=tmp_path,
            evidence_dir=tmp_path / "evidence",
        )


def test_combined_fingerprint_covers_every_domain_for_check(tmp_path: Path) -> None:
    (tmp_path / "one.py").write_text("one")
    (tmp_path / "two.txt").write_text("two")
    check = Check(name="combined", argv=("true",), reuse="development_only")
    policy = type(POLICY)(
        checks=(check,),
        domains=(
            DomainPolicy("python", ("*.py",), (), ("combined",)),
            DomainPolicy("text", ("*.txt",), (), ("combined",)),
        ),
    )
    first = combined_domain_fingerprint(tmp_path, policy, check)

    (tmp_path / "two.txt").write_text("changed")

    assert combined_domain_fingerprint(tmp_path, policy, check) != first


def test_changed_paths_includes_deleted_files(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repository,
        check=True,
    )
    deleted = repository / "deleted.py"
    deleted.write_text("remove me")
    subprocess.run(["git", "add", "deleted.py"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repository, check=True)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    deleted.unlink()

    assert "deleted.py" in changed_paths(repository, base)
