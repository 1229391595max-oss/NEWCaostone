from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any

from argon2 import PasswordHasher
import pytest

from tests.hosted.test_verify_deployed_release_state import deployed_continuation
from tests.release.test_deployed_release_recovery_package import (
    ATTESTATION,
    ATTESTATION_GIT_SHA,
    AUTHORIZATION_ID,
    EXPIRES,
    NOW,
    PROJECT_ROOT,
    _write_continuation,
)


SECRET_ENVIRONMENTS = {
    "BIZPULSE_OPERATOR_PASSWORD_HASH_CHECK",
    "BIZPULSE_BROWSER_OPERATOR_PASSWORD",
}


def _subject():
    try:
        return importlib.import_module("scripts.run_deployed_release_recovery")
    except ModuleNotFoundError:
        pytest.fail("deployed release recovery runner is not implemented")


def _package(tmp_path: Path):
    package_builder = importlib.import_module(
        "scripts.create_deployed_release_recovery_package"
    )
    continuation = deployed_continuation()
    continuation_path, continuation_sha256 = _write_continuation(
        tmp_path, continuation
    )
    authority = package_builder._build_authority_from_continuation(
        continuation=continuation,
        attestation_path=ATTESTATION,
        attestation_git_sha=ATTESTATION_GIT_SHA,
        authorization_id=AUTHORIZATION_ID,
        issued_at=NOW,
        expires_at=EXPIRES,
    )
    package = package_builder.build_deployed_release_recovery_package(
        authority=authority,
        continuation=continuation,
        continuation_reference="continuation.json",
        continuation_sha256=continuation_sha256,
        authorization_id=AUTHORIZATION_ID,
        issued_at=NOW,
        expires_at=EXPIRES,
    )
    package_path = tmp_path / "RECOVERY_V5.md"
    digest = package_builder.write_deployed_release_recovery_package(
        package_path, package
    )
    return package, package_path, continuation_path, digest


def _secrets(password: str = "operator-secret") -> dict[tuple[str, str], str]:
    return {
        ("NEWCaostone Azure Demo Operator Password Hash", "operator"): (
            PasswordHasher().hash(password)
        ),
        ("NEWCaostone Azure Demo Operator Password", "operator"): password,
    }


def _success_runner(calls: list[dict[str, Any]]):
    def run(command, **kwargs):
        calls.append({"command": tuple(command), "kwargs": kwargs})
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    return run


def test_wrong_hash_stops_before_keychain_or_commands(tmp_path: Path) -> None:
    subject = _subject()
    _, package_path, continuation_path, _ = _package(tmp_path)
    keychain_calls: list[tuple[str, str]] = []
    calls: list[dict[str, Any]] = []

    with pytest.raises(
        subject.DeployedReleaseExecutionInvalid,
        match="deployed_execution_package_hash_mismatch",
    ):
        subject.execute_deployed_release_recovery(
            package_path=package_path,
            expected_package_sha256="9" * 64,
            continuation_path=continuation_path,
            receipt_path=tmp_path / "receipt.json",
            now=NOW,
            keychain_reader=lambda service, account: keychain_calls.append(
                (service, account)
            ),
            command_runner=_success_runner(calls),
            base_environment={"PATH": "/usr/bin:/bin"},
        )

    assert keychain_calls == []
    assert calls == []


def test_existing_receipt_blocks_keychain_and_commands(tmp_path: Path) -> None:
    subject = _subject()
    _, package_path, continuation_path, digest = _package(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text("already consumed\n")
    keychain_calls: list[tuple[str, str]] = []
    calls: list[dict[str, Any]] = []

    with pytest.raises(
        subject.DeployedReleaseExecutionInvalid,
        match="deployed_execution_package_consumed",
    ):
        subject.execute_deployed_release_recovery(
            package_path=package_path,
            expected_package_sha256=digest,
            continuation_path=continuation_path,
            receipt_path=receipt_path,
            now=NOW,
            keychain_reader=lambda service, account: keychain_calls.append(
                (service, account)
            ),
            command_runner=_success_runner(calls),
            base_environment={"PATH": "/usr/bin:/bin"},
        )

    assert keychain_calls == []
    assert calls == []


def test_readonly_failure_stops_before_keychain_and_receipt(
    tmp_path: Path,
) -> None:
    subject = _subject()
    _, package_path, continuation_path, digest = _package(tmp_path)
    keychain_calls: list[tuple[str, str]] = []
    calls: list[dict[str, Any]] = []

    def fail(command, **kwargs):
        calls.append({"command": tuple(command), "kwargs": kwargs})
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="drift")

    with pytest.raises(
        subject.DeployedReleaseExecutionInvalid,
        match="deployed_execution_readonly_stage_failed",
    ):
        subject.execute_deployed_release_recovery(
            package_path=package_path,
            expected_package_sha256=digest,
            continuation_path=continuation_path,
            receipt_path=tmp_path / "receipt.json",
            now=NOW,
            keychain_reader=lambda service, account: keychain_calls.append(
                (service, account)
            ),
            command_runner=fail,
            base_environment={"PATH": "/usr/bin:/bin"},
        )

    assert len(calls) == 1
    assert keychain_calls == []
    assert not (tmp_path / "receipt.json").exists()


def test_operator_pair_mismatch_is_value_free_and_stops_before_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subject = _subject()
    _, package_path, continuation_path, digest = _package(tmp_path)
    values = _secrets(password="correct-password")
    values[("NEWCaostone Azure Demo Operator Password", "operator")] = (
        "wrong-plaintext-value"
    )
    calls: list[dict[str, Any]] = []

    with pytest.raises(
        subject.DeployedReleaseExecutionInvalid,
        match="deployed_execution_operator_pair_invalid",
    ) as captured:
        subject.execute_deployed_release_recovery(
            package_path=package_path,
            expected_package_sha256=digest,
            continuation_path=continuation_path,
            receipt_path=tmp_path / "receipt.json",
            now=NOW,
            keychain_reader=lambda service, account: values.get(
                (service, account)
            ),
            command_runner=_success_runner(calls),
            base_environment={"PATH": "/usr/bin:/bin"},
        )

    output = capsys.readouterr()
    serialized = str(captured.value) + output.out + output.err
    assert "correct-password" not in serialized
    assert "wrong-plaintext-value" not in serialized
    assert len(calls) == 3
    assert not (tmp_path / "receipt.json").exists()


def test_success_scopes_operator_plaintext_and_blocks_replay(
    tmp_path: Path,
) -> None:
    subject = _subject()
    package, package_path, continuation_path, digest = _package(tmp_path)
    values = _secrets()
    keychain_calls: list[tuple[str, str]] = []
    calls: list[dict[str, Any]] = []
    receipt_path = tmp_path / "receipt.json"

    def read_keychain(service: str, account: str) -> str | None:
        keychain_calls.append((service, account))
        return values.get((service, account))

    result = subject.execute_deployed_release_recovery(
        package_path=package_path,
        expected_package_sha256=digest,
        continuation_path=continuation_path,
        receipt_path=receipt_path,
        now=NOW,
        keychain_reader=read_keychain,
        command_runner=_success_runner(calls),
        base_environment={
            "PATH": "/usr/bin:/bin",
            "HOME": "/Users/tester",
            "BIZPULSE_BROWSER_OPERATOR_PASSWORD": "inherited-must-be-removed",
            "UNRELATED_SECRET": "must-not-be-inherited",
        },
    )

    assert result == {
        "status": "completed",
        "authorization_id": package["authorization_id"],
    }
    assert keychain_calls == [
        ("NEWCaostone Azure Demo Operator Password Hash", "operator"),
        ("NEWCaostone Azure Demo Operator Password", "operator"),
    ]
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    receipt_text = receipt_path.read_text()
    assert json.loads(receipt_text)["status"] == "completed"
    assert all(value not in receipt_text for value in values.values())

    browser = next(
        call
        for call in calls
        if "scripts/run_hosted_check.py" in call["command"]
        and "browser" in call["command"]
    )
    assert browser["kwargs"]["env"][
        "BIZPULSE_BROWSER_OPERATOR_PASSWORD"
    ] == "operator-secret"
    assert all(
        "BIZPULSE_OPERATOR_PASSWORD_HASH_CHECK" not in call["kwargs"]["env"]
        for call in calls
    )
    for call in calls:
        assert call["kwargs"]["shell"] is False
        assert "UNRELATED_SECRET" not in call["kwargs"]["env"]
        assert all(value not in call["command"] for value in values.values())
        if call is not browser:
            assert not SECRET_ENVIRONMENTS.intersection(call["kwargs"]["env"])

    replay_calls: list[dict[str, Any]] = []
    replay_keychain: list[tuple[str, str]] = []
    with pytest.raises(
        subject.DeployedReleaseExecutionInvalid,
        match="deployed_execution_package_consumed",
    ):
        subject.execute_deployed_release_recovery(
            package_path=package_path,
            expected_package_sha256=digest,
            continuation_path=continuation_path,
            receipt_path=receipt_path,
            now=NOW,
            keychain_reader=lambda service, account: replay_keychain.append(
                (service, account)
            ),
            command_runner=_success_runner(replay_calls),
            base_environment={"PATH": "/usr/bin:/bin"},
        )
    assert replay_calls == []
    assert replay_keychain == []


@pytest.mark.parametrize(
    ("failed_stage", "expected_completed", "expected_call_count"),
    [
        ("health", ["deployed_preflight", "registry_verify"], 4),
        (
            "browser_acceptance",
            ["deployed_preflight", "registry_verify", "health"],
            5,
        ),
    ],
)
def test_post_receipt_failure_is_recorded_and_stops_later_stages(
    tmp_path: Path,
    failed_stage: str,
    expected_completed: list[str],
    expected_call_count: int,
) -> None:
    subject = _subject()
    package, package_path, continuation_path, digest = _package(tmp_path)
    values = _secrets()
    calls: list[dict[str, Any]] = []
    receipt_path = tmp_path / "receipt.json"
    failed_command = package["commands"][failed_stage][0]

    def runner(command, **kwargs):
        calls.append({"command": tuple(command), "kwargs": kwargs})
        return subprocess.CompletedProcess(
            command,
            1 if " ".join(command) == failed_command else 0,
            stdout="",
            stderr="failure-secret-must-not-be-relayed",
        )

    with pytest.raises(
        subject.DeployedReleaseExecutionInvalid,
        match="deployed_execution_stage_failed",
    ):
        subject.execute_deployed_release_recovery(
            package_path=package_path,
            expected_package_sha256=digest,
            continuation_path=continuation_path,
            receipt_path=receipt_path,
            now=NOW,
            keychain_reader=lambda service, account: values.get(
                (service, account)
            ),
            command_runner=runner,
            base_environment={"PATH": "/usr/bin:/bin"},
        )

    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "failed"
    assert receipt["failed_stage"] == failed_stage
    assert receipt["completed_stages"] == expected_completed
    assert len(calls) == expected_call_count
    assert "failure-secret-must-not-be-relayed" not in receipt_path.read_text()


def test_real_control_hashes_cover_all_v5_entrypoints() -> None:
    package_builder = importlib.import_module(
        "scripts.create_deployed_release_recovery_package"
    )

    assert package_builder._control_sha256() == {
        path: hashlib.sha256((PROJECT_ROOT / path).read_bytes()).hexdigest()
        for path in (
            "scripts/create_deployed_release_recovery_package.py",
            "scripts/run_deployed_release_recovery.py",
            "scripts/verify_deployed_release_state.py",
        )
    }


def test_direct_entrypoint_help_works_without_pythonpath() -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            str(PROJECT_ROOT / ".venv/bin/python"),
            "scripts/run_deployed_release_recovery.py",
            "--help",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--approved-sha256" in completed.stdout
