from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any

import pytest

from tests.hosted.test_verify_deployed_release_state import deployed_continuation


NOW = "2026-08-16T23:00:00Z"
EXPIRES = "2026-08-17T23:00:00Z"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ATTESTATION = (
    PROJECT_ROOT
    / "release/attestations/82fd4a4dcfbc04a6cbe6386ce8891b750a1ea7e3.json"
)
ATTESTATION_GIT_SHA = "c573f2be9d8d6414143fbeab2fa2af788caf4f19"
AUTHORIZATION_ID = "99999999-9999-4999-8999-999999999999"
EXPECTED_ORDER = [
    "deployed_preflight",
    "registry_verify",
    "health",
    "browser_acceptance",
    "capacity",
    "expiry",
    "restart_readback",
    "rollback",
]
EXPECTED_KEYCHAIN = [
    {
        "account": "operator",
        "environment": "BIZPULSE_OPERATOR_PASSWORD_HASH_CHECK",
        "scope": "credential_pair_validation",
        "service": "NEWCaostone Azure Demo Operator Password Hash",
    },
    {
        "account": "operator",
        "environment": "BIZPULSE_BROWSER_OPERATOR_PASSWORD",
        "scope": "browser_acceptance",
        "service": "NEWCaostone Azure Demo Operator Password",
    },
]
SYNTHETIC_CONTROL_HASHES = {
    "scripts/create_deployed_release_recovery_package.py": "1" * 64,
    "scripts/run_deployed_release_recovery.py": "2" * 64,
    "scripts/verify_deployed_release_state.py": "3" * 64,
}


def _subject():
    try:
        return importlib.import_module(
            "scripts.create_deployed_release_recovery_package"
        )
    except ModuleNotFoundError:
        pytest.fail("deployed release recovery package builder is not implemented")


def _write_continuation(
    tmp_path: Path, continuation: dict[str, Any]
) -> tuple[Path, str]:
    path = tmp_path / "continuation.json"
    path.write_text(json.dumps(continuation, indent=2, sort_keys=True) + "\n")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _authority(subject, continuation: dict[str, Any]) -> dict[str, Any]:
    return subject._build_authority_from_continuation(
        continuation=continuation,
        attestation_path=ATTESTATION,
        attestation_git_sha=ATTESTATION_GIT_SHA,
        authorization_id=AUTHORIZATION_ID,
        issued_at=NOW,
        expires_at=EXPIRES,
    )


def test_v6_package_contains_only_pending_stages_and_keychain_descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject = _subject()
    monkeypatch.setattr(
        subject, "_control_sha256", lambda: SYNTHETIC_CONTROL_HASHES
    )
    continuation = deployed_continuation()
    continuation_path, continuation_sha256 = _write_continuation(
        tmp_path, continuation
    )
    authority = _authority(subject, continuation)

    package = subject.build_deployed_release_recovery_package(
        authority=authority,
        continuation=continuation,
        continuation_reference="continuation.json",
        continuation_sha256=continuation_sha256,
        authorization_id=AUTHORIZATION_ID,
        issued_at=NOW,
        expires_at=EXPIRES,
    )

    assert package["execution_order"] == EXPECTED_ORDER
    assert set(package["commands"]) == set(EXPECTED_ORDER)
    assert package["keychain_sources"] == EXPECTED_KEYCHAIN
    assert package["no_ai"] is True
    assert package["completed_operations"] == continuation[
        "completed_operations"
    ]
    assert package["control_sha256"] == SYNTHETIC_CONTROL_HASHES
    assert package["retry_limits"] == {
        "read": 1,
        "deploy": 0,
        "paid_provider": 0,
    }
    serialized = json.dumps(package["commands"], sort_keys=True)
    for forbidden in (
        "az deployment group create",
        "containerapp job start",
        "run_azure_job.py",
        "update_azure_job_binding.py",
        "prepare_cloud.py",
        "seed_demo.py",
        "publish_registry_image.py",
        "qualify_openai_model.py",
        "openai-api-key",
        "aiChatEnabled=true",
    ):
        assert forbidden not in serialized

    output = tmp_path / "RECOVERY_V6.md"
    digest = subject.write_deployed_release_recovery_package(output, package)
    assert digest == hashlib.sha256(output.read_bytes()).hexdigest()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.read_text().startswith(
        "# NEWCaostone Deployed Release Recovery V6 Authorization\n"
    )
    assert subject.load_deployed_release_recovery_package(
        output,
        continuation_path=continuation_path,
        now=NOW,
    ) == package


def test_v6_package_rejects_candidate_release_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject = _subject()
    monkeypatch.setattr(
        subject, "_control_sha256", lambda: SYNTHETIC_CONTROL_HASHES
    )
    continuation = deployed_continuation()
    authority = _authority(subject, continuation)
    continuation["release"]["candidate_image_digest"] = "sha256:" + "9" * 64
    _, continuation_sha256 = _write_continuation(tmp_path, continuation)

    with pytest.raises(
        subject.DeployedReleaseRecoveryInvalid,
        match="deployed_recovery_release_mismatch",
    ):
        subject.build_deployed_release_recovery_package(
            authority=authority,
            continuation=continuation,
            continuation_reference="continuation.json",
            continuation_sha256=continuation_sha256,
            authorization_id=AUTHORIZATION_ID,
            issued_at=NOW,
            expires_at=EXPIRES,
        )


def test_v6_loader_rejects_package_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject = _subject()
    monkeypatch.setattr(
        subject, "_control_sha256", lambda: SYNTHETIC_CONTROL_HASHES
    )
    continuation = deployed_continuation()
    continuation_path, continuation_sha256 = _write_continuation(
        tmp_path, continuation
    )
    authority = _authority(subject, continuation)
    package = subject.build_deployed_release_recovery_package(
        authority=authority,
        continuation=continuation,
        continuation_reference="continuation.json",
        continuation_sha256=continuation_sha256,
        authorization_id=AUTHORIZATION_ID,
        issued_at=NOW,
        expires_at=EXPIRES,
    )
    drifted = deepcopy(package)
    drifted["execution_order"] = list(reversed(EXPECTED_ORDER))
    output = tmp_path / "DRIFTED.md"
    subject.write_deployed_release_recovery_package(output, drifted)

    with pytest.raises(
        subject.DeployedReleaseRecoveryInvalid,
        match="deployed_recovery_drift",
    ):
        subject.load_deployed_release_recovery_package(
            output,
            continuation_path=continuation_path,
            now=NOW,
        )


def test_v6_writer_refuses_to_overwrite_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject = _subject()
    monkeypatch.setattr(
        subject, "_control_sha256", lambda: SYNTHETIC_CONTROL_HASHES
    )
    continuation = deployed_continuation()
    _, continuation_sha256 = _write_continuation(tmp_path, continuation)
    package = subject.build_deployed_release_recovery_package(
        authority=_authority(subject, continuation),
        continuation=continuation,
        continuation_reference="continuation.json",
        continuation_sha256=continuation_sha256,
        authorization_id=AUTHORIZATION_ID,
        issued_at=NOW,
        expires_at=EXPIRES,
    )
    output = tmp_path / "RECOVERY_V6.md"
    subject.write_deployed_release_recovery_package(output, package)

    with pytest.raises(FileExistsError):
        subject.write_deployed_release_recovery_package(output, package)


def test_v6_builder_direct_entrypoint_help_works_without_pythonpath() -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            str(PROJECT_ROOT / ".venv/bin/python"),
            "scripts/create_deployed_release_recovery_package.py",
            "--help",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--continuation-reference" in completed.stdout
