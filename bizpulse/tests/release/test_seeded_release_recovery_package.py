from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import stat

import pytest

from tests.hosted.test_verify_seeded_release_state import seeded_continuation
from tests.release.test_partial_release_recovery_package import _authority


NOW = "2026-08-16T22:00:00Z"
EXPIRES = "2026-08-17T22:00:00Z"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _subject():
    try:
        return importlib.import_module(
            "scripts.create_seeded_release_recovery_package"
        )
    except ModuleNotFoundError:
        pytest.fail("seeded release recovery package builder is not implemented")


def _continuation(authority: dict[str, object]) -> dict[str, object]:
    continuation = seeded_continuation()
    release = authority["release"]
    generated = authority["generated_names"]
    continuation["target"].update(
        subscription_id=authority["subscription_id"],
        region=authority["region"],
        resource_group=authority["resource_group"],
        application=generated["container_app"],
        application_revision=f"{generated['container_app']}--oldrevision1",
        prepare_job=generated["migration_job"],
        seed_job=generated["seed_job"],
        registry_name=generated["registry_name"],
        image_repository=generated["image_repository"],
    )
    continuation["release"].update(
        candidate_git_sha=release["git_sha"],
        candidate_image_digest=release["image_digest"],
        rollback_git_sha=release["rollback_git_sha"],
        rollback_image_digest=release["rollback_image_digest"],
        migration_head=release["migration_head"],
        synthetic_manifest_sha256=release["synthetic_manifest_sha256"],
        synthetic_dataset_version_id=release["synthetic_dataset_version_id"],
    )
    continuation["seed_execution"]["arguments"][-3] = release[
        "synthetic_manifest_sha256"
    ]
    continuation["seed_execution"]["arguments"][-1] = release[
        "synthetic_dataset_version_id"
    ]
    return continuation


def _write_continuation(
    tmp_path: Path, continuation: dict[str, object]
) -> tuple[Path, str]:
    path = tmp_path / "continuation.json"
    path.write_text(json.dumps(continuation, indent=2, sort_keys=True) + "\n")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_v4_package_contains_only_pending_stages_and_keychain_descriptors(
    tmp_path: Path,
) -> None:
    subject = _subject()
    authority = _authority()
    continuation = _continuation(authority)
    continuation_path, continuation_sha256 = _write_continuation(
        tmp_path, continuation
    )

    package = subject.build_seeded_release_recovery_package(
        authority=authority,
        continuation=continuation,
        continuation_reference="continuation.json",
        continuation_sha256=continuation_sha256,
        authorization_id="88888888-8888-4888-8888-888888888888",
        issued_at=NOW,
        expires_at=EXPIRES,
    )

    assert package["execution_order"] == [
        "seeded_preflight",
        "registry_verify",
        "deploy",
        "health",
        "browser_acceptance",
        "capacity",
        "expiry",
        "restart_readback",
        "rollback",
    ]
    assert set(package["commands"]) == set(package["execution_order"])
    assert package["completed_operations"] == [
        "registry_publish",
        "postgres_migrate",
        "seed_job_bind",
        "synthetic_seed",
    ]
    assert package["keychain_sources"] == [
        {
            "account": "bpoperator",
            "environment": "BIZPULSE_DEPLOY_POSTGRES_PASSWORD",
            "scope": "deploy",
            "service": "NEWCaostone Azure Demo PostgreSQL Password",
        },
        {
            "account": "operator",
            "environment": "BIZPULSE_DEPLOY_OPERATOR_PASSWORD_HASH",
            "scope": "deploy",
            "service": "NEWCaostone Azure Demo Operator Password Hash",
        },
        {
            "account": "newcaostone-demo-app",
            "environment": "BIZPULSE_DEPLOY_SESSION_PEPPER",
            "scope": "deploy",
            "service": "NEWCaostone Azure Demo Session Pepper",
        },
        {
            "account": "operator",
            "environment": "BIZPULSE_BROWSER_OPERATOR_PASSWORD",
            "scope": "browser_acceptance",
            "service": "NEWCaostone Azure Demo Operator Password",
        },
    ]
    assert package["control_sha256"] == {
        path: hashlib.sha256((PROJECT_ROOT / path).read_bytes()).hexdigest()
        for path in (
            "scripts/create_seeded_release_recovery_package.py",
            "scripts/run_seeded_release_recovery.py",
            "scripts/verify_seeded_release_state.py",
        )
    }
    commands = json.dumps(package["commands"], sort_keys=True)
    for forbidden in (
        "publish_registry_image.py",
        "update_azure_job_binding.py",
        "run_azure_job.py --subscription "
        + authority["subscription_id"]
        + " --resource-group "
        + authority["resource_group"]
        + " --job "
        + authority["generated_names"]["migration_job"],
        "run_azure_job.py --subscription "
        + authority["subscription_id"]
        + " --resource-group "
        + authority["resource_group"]
        + " --job "
        + authority["generated_names"]["seed_job"],
        "qualify_openai_model.py",
        "openai-api-key",
        "aiChatEnabled=true",
    ):
        assert forbidden not in commands

    output = tmp_path / "RECOVERY_V4.md"
    subject.write_seeded_release_recovery_package(output, package)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.read_text().startswith(
        "# NEWCaostone Seeded Release Recovery V4 Authorization\n"
    )
    assert subject.load_seeded_release_recovery_package(
        output,
        continuation_path=continuation_path,
        now=NOW,
    ) == package


def test_v4_package_rejects_candidate_release_drift(tmp_path: Path) -> None:
    subject = _subject()
    authority = _authority()
    continuation = _continuation(authority)
    continuation["release"]["candidate_image_digest"] = "sha256:" + "9" * 64
    _, continuation_sha256 = _write_continuation(tmp_path, continuation)

    with pytest.raises(
        subject.SeededReleaseRecoveryInvalid,
        match="seeded_recovery_release_mismatch",
    ):
        subject.build_seeded_release_recovery_package(
            authority=authority,
            continuation=continuation,
            continuation_reference="continuation.json",
            continuation_sha256=continuation_sha256,
            authorization_id="88888888-8888-4888-8888-888888888888",
            issued_at=NOW,
            expires_at=EXPIRES,
        )
