from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any

from argon2 import PasswordHasher
import pytest

from tests.release.test_seeded_release_recovery_package import (
    EXPIRES,
    NOW,
    _authority,
    _continuation,
    _write_continuation,
)


SECRET_ENVIRONMENTS = {
    "BIZPULSE_DEPLOY_POSTGRES_PASSWORD",
    "BIZPULSE_DEPLOY_OPERATOR_PASSWORD_HASH",
    "BIZPULSE_DEPLOY_SESSION_PEPPER",
    "BIZPULSE_BROWSER_OPERATOR_PASSWORD",
}


def _subject():
    try:
        return importlib.import_module("scripts.run_seeded_release_recovery")
    except ModuleNotFoundError:
        pytest.fail("seeded release recovery runner is not implemented")


def test_direct_entrypoint_help_works_without_pythonpath() -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            str(Path(__file__).resolve().parents[2] / ".venv/bin/python"),
            "scripts/run_seeded_release_recovery.py",
            "--help",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--approved-sha256" in completed.stdout


def _package(tmp_path: Path):
    package_builder = importlib.import_module(
        "scripts.create_seeded_release_recovery_package"
    )
    authority = _authority()
    continuation = _continuation(authority)
    continuation_path, continuation_sha256 = _write_continuation(
        tmp_path, continuation
    )
    package = package_builder.build_seeded_release_recovery_package(
        authority=authority,
        continuation=continuation,
        continuation_reference="continuation.json",
        continuation_sha256=continuation_sha256,
        authorization_id="88888888-8888-4888-8888-888888888888",
        issued_at=NOW,
        expires_at=EXPIRES,
    )
    package_path = tmp_path / "RECOVERY_V3.md"
    digest = package_builder.write_seeded_release_recovery_package(
        package_path, package
    )
    return package, package_path, continuation_path, digest


def _secrets(password: str = "operator-secret") -> dict[tuple[str, str], str]:
    password_hash = PasswordHasher().hash(password)
    return {
        ("NEWCaostone Azure Demo PostgreSQL Password", "bpoperator"): (
            "database-password-value"
        ),
        ("NEWCaostone Azure Demo Operator Password Hash", "operator"): (
            password_hash
        ),
        ("NEWCaostone Azure Demo Session Pepper", "newcaostone-demo-app"): (
            "session-pepper-value-that-is-longer-than-thirty-two-characters"
        ),
        ("NEWCaostone Azure Demo Operator Password", "operator"): password,
    }


def _success_runner(calls: list[dict[str, Any]]):
    def run(command, **kwargs):
        calls.append({"command": tuple(command), "kwargs": kwargs})
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    return run


def test_wrong_approved_hash_fails_before_keychain_or_command(tmp_path: Path) -> None:
    subject = _subject()
    _, package_path, continuation_path, _ = _package(tmp_path)
    keychain_calls: list[tuple[str, str]] = []
    commands: list[dict[str, Any]] = []

    with pytest.raises(
        subject.SeededReleaseExecutionInvalid,
        match="seeded_execution_package_hash_mismatch",
    ):
        subject.execute_seeded_release_recovery(
            package_path=package_path,
            expected_package_sha256="9" * 64,
            continuation_path=continuation_path,
            receipt_path=tmp_path / "receipt.json",
            now=NOW,
            keychain_reader=lambda service, account: keychain_calls.append(
                (service, account)
            ),
            command_runner=_success_runner(commands),
            base_environment={"PATH": "/usr/bin:/bin"},
        )

    assert keychain_calls == []
    assert commands == []


def test_readonly_state_failure_stops_before_keychain_and_mutation(
    tmp_path: Path,
) -> None:
    subject = _subject()
    _, package_path, continuation_path, digest = _package(tmp_path)
    keychain_calls: list[tuple[str, str]] = []
    calls: list[dict[str, Any]] = []

    def fail_first(command, **kwargs):
        calls.append({"command": tuple(command), "kwargs": kwargs})
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="drift")

    with pytest.raises(
        subject.SeededReleaseExecutionInvalid,
        match="seeded_execution_readonly_stage_failed",
    ):
        subject.execute_seeded_release_recovery(
            package_path=package_path,
            expected_package_sha256=digest,
            continuation_path=continuation_path,
            receipt_path=tmp_path / "receipt.json",
            now=NOW,
            keychain_reader=lambda service, account: keychain_calls.append(
                (service, account)
            ),
            command_runner=fail_first,
            base_environment={"PATH": "/usr/bin:/bin"},
        )

    assert len(calls) == 1
    assert keychain_calls == []
    assert not (tmp_path / "receipt.json").exists()


def test_all_credentials_are_validated_before_first_mutation(tmp_path: Path) -> None:
    subject = _subject()
    _, package_path, continuation_path, digest = _package(tmp_path)
    values = _secrets()
    del values[("NEWCaostone Azure Demo Operator Password", "operator")]
    calls: list[dict[str, Any]] = []

    with pytest.raises(
        subject.SeededReleaseExecutionInvalid,
        match="seeded_execution_keychain_unavailable",
    ):
        subject.execute_seeded_release_recovery(
            package_path=package_path,
            expected_package_sha256=digest,
            continuation_path=continuation_path,
            receipt_path=tmp_path / "receipt.json",
            now=NOW,
            keychain_reader=lambda service, account: values.get((service, account)),
            command_runner=_success_runner(calls),
            base_environment={"PATH": "/usr/bin:/bin"},
        )

    assert len(calls) == 3
    assert all(
        "deployment" not in call["command"] and "run_azure_job.py" not in call["command"]
        for call in calls
    )
    assert not (tmp_path / "receipt.json").exists()


def test_hash_pair_mismatch_is_value_free_and_stops_before_mutation(
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
        subject.SeededReleaseExecutionInvalid,
        match="seeded_execution_operator_pair_invalid",
    ) as captured:
        subject.execute_seeded_release_recovery(
            package_path=package_path,
            expected_package_sha256=digest,
            continuation_path=continuation_path,
            receipt_path=tmp_path / "receipt.json",
            now=NOW,
            keychain_reader=lambda service, account: values.get((service, account)),
            command_runner=_success_runner(calls),
            base_environment={"PATH": "/usr/bin:/bin"},
        )

    output = capsys.readouterr()
    serialized = str(captured.value) + output.out + output.err
    assert "correct-password" not in serialized
    assert "wrong-plaintext-value" not in serialized
    assert len(calls) == 3


def test_success_scopes_secrets_and_owner_only_receipt_blocks_replay(
    tmp_path: Path,
) -> None:
    subject = _subject()
    package, package_path, continuation_path, digest = _package(tmp_path)
    values = _secrets()
    calls: list[dict[str, Any]] = []
    receipt_path = tmp_path / "receipt.json"
    base_environment = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/Users/tester",
        "BIZPULSE_DEPLOY_POSTGRES_PASSWORD": "inherited-must-be-removed",
        "UNRELATED_SECRET": "must-not-be-inherited",
    }

    result = subject.execute_seeded_release_recovery(
        package_path=package_path,
        expected_package_sha256=digest,
        continuation_path=continuation_path,
        receipt_path=receipt_path,
        now=NOW,
        keychain_reader=lambda service, account: values.get((service, account)),
        command_runner=_success_runner(calls),
        base_environment=base_environment,
    )

    assert result == {"status": "completed", "authorization_id": package["authorization_id"]}
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    receipt_text = receipt_path.read_text()
    assert json.loads(receipt_text)["status"] == "completed"
    assert all(value not in receipt_text for value in values.values())
    assert "inherited-must-be-removed" not in receipt_text

    deploy_calls = [
        call for call in calls if call["command"][:4] == ("az", "deployment", "group", "create")
    ]
    assert len(deploy_calls) == 1
    deploy_environment = deploy_calls[0]["kwargs"]["env"]
    assert deploy_environment["BIZPULSE_DEPLOY_POSTGRES_PASSWORD"] == (
        "database-password-value"
    )
    assert deploy_environment["BIZPULSE_DEPLOY_OPERATOR_PASSWORD_HASH"].startswith(
        "$argon2id$"
    )
    assert deploy_environment["BIZPULSE_DEPLOY_SESSION_PEPPER"].startswith(
        "session-pepper-value"
    )
    assert "BIZPULSE_BROWSER_OPERATOR_PASSWORD" not in deploy_environment

    browser_calls = [
        call
        for call in calls
        if "scripts/run_hosted_check.py" in call["command"]
        and "browser" in call["command"]
    ]
    assert len(browser_calls) == 1
    browser_environment = browser_calls[0]["kwargs"]["env"]
    assert browser_environment["BIZPULSE_BROWSER_OPERATOR_PASSWORD"] == (
        "operator-secret"
    )
    assert not (
        SECRET_ENVIRONMENTS - {"BIZPULSE_BROWSER_OPERATOR_PASSWORD"}
    ).intersection(browser_environment)

    for call in calls:
        command = call["command"]
        environment = call["kwargs"]["env"]
        assert call["kwargs"]["shell"] is False
        assert "UNRELATED_SECRET" not in environment
        if call not in deploy_calls + browser_calls:
            assert not SECRET_ENVIRONMENTS.intersection(environment)
        assert all(value not in command for value in values.values())

    replay_calls: list[dict[str, Any]] = []
    with pytest.raises(
        subject.SeededReleaseExecutionInvalid,
        match="seeded_execution_package_consumed",
    ):
        subject.execute_seeded_release_recovery(
            package_path=package_path,
            expected_package_sha256=digest,
            continuation_path=continuation_path,
            receipt_path=receipt_path,
            now=NOW,
            keychain_reader=lambda service, account: values.get((service, account)),
            command_runner=_success_runner(replay_calls),
            base_environment={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
    assert replay_calls == []
