from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
import stat
import subprocess
from urllib.parse import urlsplit

import pytest

from scripts.build_deployed_release_desired_projection import (
    compile_desired_projection,
)
from scripts.create_deployed_release_diagnostic_package import (
    write_deployed_release_diagnostic_package,
)
from scripts.deployed_release_diagnostic_contract import (
    DeployedReleaseDiagnosticInvalid,
    parse_utc,
    replace_owner_json_atomic,
    write_owner_json_exclusive,
)
from scripts.run_deployed_release_diagnostic import (
    execute_deployed_release_diagnostic,
)
from scripts.verify_deployed_release_state import (
    load_deployed_release_continuation,
)
from tests.hosted.test_observe_deployed_release_state import (
    _arm,
    _execution,
    _live_payloads_from_desired,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTINUATION_PATH = (
    PROJECT_ROOT / "release/incidents/2026-08-16-recovery-v4-deployed-continuation.json"
)
CONTINUATION_SHA256 = "d355c9215ee9dec22adb93392705107dfd8f06db37ca8d03b240c519278af4af"


@pytest.fixture(scope="module")
def continuation() -> dict[str, object]:
    return load_deployed_release_continuation(
        CONTINUATION_PATH,
        expected_sha256=CONTINUATION_SHA256,
    )


@pytest.fixture(scope="module")
def desired(
    continuation: dict[str, object],
) -> dict[str, object]:
    return compile_desired_projection(
        PROJECT_ROOT / "infra/modules/app.bicep",
        continuation,
        continuation_sha256=CONTINUATION_SHA256,
    )


def _package(continuation: dict[str, object]) -> dict[str, object]:
    return {
        "arm": _arm(continuation),
        "attempt_schema": "newcaostone.deployed-release-diagnostic-attempt.v2",
        "authorization_id": "11111111-1111-4111-8111-111111111111",
        "continuation": {
            "reference": (
                "release/incidents/2026-08-16-recovery-v4-deployed-continuation.json"
            ),
            "sha256": CONTINUATION_SHA256,
        },
        "desired_projection_sha256": "2" * 64,
        "repository": {
            "branch": "codex/integrated-viewer-ai-anti-drift",
            "head_sha": "3" * 40,
            "tracked_clean_required": True,
            "tree_sha": "4" * 40,
        },
        "toolchain": {
            "azure_cli": "2.89.0",
            "bicep": "0.46.1",
            "containerapp_extension_observed": "1.3.0b4",
            "python": "Python 3.12.10",
        },
    }


def _valid_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired: dict[str, object],
) -> tuple[Path, str, dict[str, object]]:
    package = _package(continuation)
    package_path = tmp_path / "D1.md"
    digest = write_deployed_release_diagnostic_package(package_path, package)
    monkeypatch.setattr(
        "scripts.run_deployed_release_diagnostic.load_deployed_release_diagnostic_package",
        lambda _path, *, continuation_path, now: package,
    )
    monkeypatch.setattr(
        "scripts.run_deployed_release_diagnostic.compile_desired_projection",
        lambda _path, _continuation, *, continuation_sha256: desired,
    )
    return package_path, digest, package


def _raw_payloads(
    continuation: dict[str, object], desired: dict[str, object]
) -> dict[str, object]:
    raw = _live_payloads_from_desired(desired, continuation)
    for index, role in enumerate(desired["jobs"]):
        bound = continuation["executions"][role]
        raw["executions"][role] = [
            _execution(
                bound["name"],
                "Succeeded",
                f"2026-08-16T20:{index + 10:02d}:00Z",
                f"2026-08-16T20:{index + 10:02d}:30Z",
            )
        ]
    return raw


def _arm_runner(
    raw: dict[str, object],
    calls: list[list[str]],
    *,
    receipt_path: Path | None = None,
) -> object:
    jobs_by_name = {
        payload["name"]: (role, payload) for role, payload in raw["jobs"].items()
    }

    def run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        if receipt_path is not None:
            assert receipt_path.exists()
            receipt = json.loads(receipt_path.read_text())
            assert receipt["status"] == "started"
        path = urlsplit(command[5]).path
        if path.endswith("/revisions"):
            payload = {"nextLink": None, "value": raw["revisions"]}
        elif path.endswith("/executions"):
            job_name = path.split("/")[-2]
            role, _job = jobs_by_name[job_name]
            payload = {"nextLink": None, "value": raw["executions"][role]}
        elif "/containerApps/" in path:
            payload = raw["application"]
        else:
            job_name = path.split("/")[-1]
            _role, payload = jobs_by_name[job_name]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload).encode(),
            stderr=b"",
        )

    return run


def test_attempt_receipt_exists_before_first_arm_read_and_completion_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired: dict[str, object],
) -> None:
    package_path, digest, _package_data = _valid_package(
        tmp_path, monkeypatch, continuation, desired
    )
    receipt_path = tmp_path / "attempt.json"
    observation_path = tmp_path / "observation.json"
    raw = _raw_payloads(continuation, desired)
    calls: list[list[str]] = []

    result = execute_deployed_release_diagnostic(
        package_path=package_path,
        approved_sha256=digest,
        continuation_path=CONTINUATION_PATH,
        receipt_path=receipt_path,
        observation_path=observation_path,
        now=parse_utc("2026-08-16T23:30:00Z"),
        completion_clock=lambda: parse_utc("2026-08-16T23:30:08Z"),
        arm_runner=_arm_runner(raw, calls, receipt_path=receipt_path),
    )

    assert result == {
        "observation_sha256": hashlib.sha256(observation_path.read_bytes()).hexdigest(),
        "state": "completed",
    }
    assert len(calls) == 10
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(observation_path.stat().st_mode) == 0o600
    receipt = json.loads(receipt_path.read_text())
    assert receipt["schema_version"] == (
        "newcaostone.deployed-release-diagnostic-attempt.v2"
    )
    assert receipt["failure"] is None
    assert receipt["status"] == "completed"
    assert receipt["started_at"] == "2026-08-16T23:30:00Z"
    assert receipt["completed_at"] == "2026-08-16T23:30:08Z"
    assert receipt["completed_resource_roles"] == [
        "application",
        "revision",
        "prepare",
        "seed",
        "session_maintenance",
        "storage_maintenance",
    ]
    assert receipt["completed_reads"] == 6
    assert receipt["observation"]["sha256"] == result["observation_sha256"]
    for command in calls:
        assert command[:4] == ["az", "rest", "--method", "get"]
        serialized = " ".join(command).lower()
        assert command[:2] != ["az", "containerapp"]
        for forbidden in ("keychain", "docker", "--method post"):
            assert forbidden not in serialized


def test_wrong_sha_creates_no_receipt_and_makes_no_arm_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired: dict[str, object],
) -> None:
    package_path, _digest, _package_data = _valid_package(
        tmp_path, monkeypatch, continuation, desired
    )
    receipt_path = tmp_path / "attempt.json"
    calls: list[list[str]] = []

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_package_hash_mismatch",
    ):
        execute_deployed_release_diagnostic(
            package_path=package_path,
            approved_sha256="9" * 64,
            continuation_path=CONTINUATION_PATH,
            receipt_path=receipt_path,
            observation_path=tmp_path / "observation.json",
            now=parse_utc("2026-08-16T23:30:00Z"),
            arm_runner=_arm_runner(_raw_payloads(continuation, desired), calls),
        )

    assert not receipt_path.exists()
    assert calls == []


def test_invalid_local_package_creates_no_receipt_or_arm_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired: dict[str, object],
) -> None:
    package_path, digest, _package_data = _valid_package(
        tmp_path, monkeypatch, continuation, desired
    )
    monkeypatch.setattr(
        "scripts.run_deployed_release_diagnostic.load_deployed_release_diagnostic_package",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            DeployedReleaseDiagnosticInvalid(
                "diagnostic_control_drift", "local", "local"
            )
        ),
    )
    calls: list[list[str]] = []
    receipt_path = tmp_path / "attempt.json"

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_control_drift",
    ):
        execute_deployed_release_diagnostic(
            package_path=package_path,
            approved_sha256=digest,
            continuation_path=CONTINUATION_PATH,
            receipt_path=receipt_path,
            observation_path=tmp_path / "observation.json",
            now=parse_utc("2026-08-16T23:30:00Z"),
            arm_runner=_arm_runner(_raw_payloads(continuation, desired), calls),
        )

    assert not receipt_path.exists()
    assert calls == []


def test_arm_failure_records_completion_time_and_safe_mode_600_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired: dict[str, object],
) -> None:
    package_path, digest, _package_data = _valid_package(
        tmp_path, monkeypatch, continuation, desired
    )
    receipt_path = tmp_path / "attempt.json"
    observation_path = tmp_path / "observation.json"

    def failing_runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        assert receipt_path.exists()
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=b"password=do-not-record",
            stderr=b"Authorization: Bearer do-not-record",
        )

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_execution_failed",
    ):
        execute_deployed_release_diagnostic(
            package_path=package_path,
            approved_sha256=digest,
            continuation_path=CONTINUATION_PATH,
            receipt_path=receipt_path,
            observation_path=observation_path,
            now=parse_utc("2026-08-16T23:30:00Z"),
            completion_clock=lambda: parse_utc("2026-08-16T23:30:03Z"),
            arm_runner=failing_runner,
        )

    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    receipt_text = receipt_path.read_text()
    assert "do-not-record" not in receipt_text
    assert not observation_path.exists()
    receipt = json.loads(receipt_text)
    assert receipt["status"] == "failed"
    assert receipt["started_at"] == "2026-08-16T23:30:00Z"
    assert receipt["completed_at"] == "2026-08-16T23:30:03Z"
    assert receipt["failure"] == {
        "code": "diagnostic_arm_request_failed",
        "resource_role": "application",
        "stage": "application",
        "mismatch_category": None,
    }


def test_naive_completion_time_is_rejected_and_receipt_stays_consumed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired: dict[str, object],
) -> None:
    package_path, digest, _package_data = _valid_package(
        tmp_path, monkeypatch, continuation, desired
    )
    receipt_path = tmp_path / "attempt.json"
    calls: list[list[str]] = []

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_execution_failed",
    ):
        execute_deployed_release_diagnostic(
            package_path=package_path,
            approved_sha256=digest,
            continuation_path=CONTINUATION_PATH,
            receipt_path=receipt_path,
            observation_path=tmp_path / "observation.json",
            now=parse_utc("2026-08-16T23:30:00Z"),
            completion_clock=lambda: datetime(2026, 8, 16, 23, 30, 8),
            arm_runner=_arm_runner(_raw_payloads(continuation, desired), calls),
        )

    assert len(calls) == 10
    assert receipt_path.exists()


def test_initial_receipt_persistence_failure_makes_zero_arm_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired: dict[str, object],
) -> None:
    package_path, digest, _package_data = _valid_package(
        tmp_path, monkeypatch, continuation, desired
    )
    calls: list[list[str]] = []

    def fail_write(_path: Path, _payload: object) -> None:
        raise OSError("Authorization: Bearer do-not-record")

    monkeypatch.setattr(
        "scripts.run_deployed_release_diagnostic.write_owner_json_exclusive",
        fail_write,
    )

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_observation_write_failed",
    ):
        execute_deployed_release_diagnostic(
            package_path=package_path,
            approved_sha256=digest,
            continuation_path=CONTINUATION_PATH,
            receipt_path=tmp_path / "attempt.json",
            observation_path=tmp_path / "observation.json",
            now=parse_utc("2026-08-16T23:30:00Z"),
            arm_runner=_arm_runner(_raw_payloads(continuation, desired), calls),
        )

    assert calls == []


@pytest.mark.parametrize("failure_mode", ("creation", "readback"))
def test_observation_write_persistence_failure_leaves_safe_failed_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired: dict[str, object],
    failure_mode: str,
) -> None:
    package_path, digest, _package_data = _valid_package(
        tmp_path, monkeypatch, continuation, desired
    )
    receipt_path = tmp_path / "attempt.json"
    observation_path = tmp_path / "observation.json"
    calls: list[list[str]] = []

    if failure_mode == "creation":

        def conditional_write(path: Path, payload: object) -> None:
            if path == observation_path:
                raise OSError("password=do-not-record")
            write_owner_json_exclusive(path, payload)

        monkeypatch.setattr(
            "scripts.run_deployed_release_diagnostic.write_owner_json_exclusive",
            conditional_write,
        )
    else:
        real_read_bytes = Path.read_bytes

        def conditional_read_bytes(path: Path) -> bytes:
            if path == observation_path:
                raise OSError("Authorization: Bearer do-not-record")
            return real_read_bytes(path)

        monkeypatch.setattr(Path, "read_bytes", conditional_read_bytes)

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_execution_failed",
    ):
        execute_deployed_release_diagnostic(
            package_path=package_path,
            approved_sha256=digest,
            continuation_path=CONTINUATION_PATH,
            receipt_path=receipt_path,
            observation_path=observation_path,
            now=parse_utc("2026-08-16T23:30:00Z"),
            completion_clock=lambda: parse_utc("2026-08-16T23:30:04Z"),
            arm_runner=_arm_runner(_raw_payloads(continuation, desired), calls),
        )

    receipt_text = receipt_path.read_text()
    assert receipt_path.exists()
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    assert "do-not-record" not in receipt_text
    receipt = json.loads(receipt_text)
    assert receipt["status"] == "failed"
    assert receipt["completed_at"] == "2026-08-16T23:30:04Z"
    assert receipt["observation"] is None
    assert receipt["failure"] == {
        "code": "diagnostic_observation_write_failed",
        "resource_role": "local",
        "stage": "observation",
        "mismatch_category": None,
    }


def test_final_receipt_persistence_failure_remains_consumed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired: dict[str, object],
) -> None:
    package_path, digest, _package_data = _valid_package(
        tmp_path, monkeypatch, continuation, desired
    )
    receipt_path = tmp_path / "attempt.json"
    observation_path = tmp_path / "observation.json"
    calls: list[list[str]] = []

    def fail_completed_receipt(path: Path, payload: object) -> None:
        if isinstance(payload, dict) and payload.get("status") == "completed":
            raise OSError("password=do-not-record")
        replace_owner_json_atomic(path, payload)

    monkeypatch.setattr(
        "scripts.run_deployed_release_diagnostic.replace_owner_json_atomic",
        fail_completed_receipt,
    )

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_execution_failed",
    ):
        execute_deployed_release_diagnostic(
            package_path=package_path,
            approved_sha256=digest,
            continuation_path=CONTINUATION_PATH,
            receipt_path=receipt_path,
            observation_path=observation_path,
            now=parse_utc("2026-08-16T23:30:00Z"),
            completion_clock=lambda: parse_utc("2026-08-16T23:30:05Z"),
            arm_runner=_arm_runner(_raw_payloads(continuation, desired), calls),
        )

    receipt_text = receipt_path.read_text()
    assert "do-not-record" not in receipt_text
    assert json.loads(receipt_text)["status"] == "failed"
    assert observation_path.exists()


def test_revision_response_failure_records_safe_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired: dict[str, object],
) -> None:
    package_path, digest, _package_data = _valid_package(
        tmp_path, monkeypatch, continuation, desired
    )
    receipt_path = tmp_path / "attempt.json"
    observation_path = tmp_path / "observation.json"
    responses = [{}, {"nextLink": 7, "value": []}]

    def revision_failure_runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(responses.pop(0)).encode(),
            stderr=b"",
        )

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_execution_failed",
    ):
        execute_deployed_release_diagnostic(
            package_path=package_path,
            approved_sha256=digest,
            continuation_path=CONTINUATION_PATH,
            receipt_path=receipt_path,
            observation_path=observation_path,
            now=parse_utc("2026-08-16T23:30:00Z"),
            arm_runner=revision_failure_runner,
        )

    receipt = json.loads(receipt_path.read_text())
    assert receipt["completed_resource_roles"] == ["application"]
    assert receipt["failure"] == {
        "code": "diagnostic_arm_response_invalid",
        "resource_role": "revision",
        "stage": "revision",
        "mismatch_category": None,
    }


def test_application_drift_records_safe_category_without_image_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired: dict[str, object],
) -> None:
    package_path, digest, _package_data = _valid_package(
        tmp_path, monkeypatch, continuation, desired
    )
    receipt_path = tmp_path / "attempt.json"
    observation_path = tmp_path / "observation.json"
    raw = _raw_payloads(continuation, desired)
    application = raw["application"]
    assert isinstance(application, dict)
    properties = application["properties"]
    assert isinstance(properties, dict)
    template = properties["template"]
    assert isinstance(template, dict)
    containers = template["containers"]
    assert isinstance(containers, list) and len(containers) == 1
    container = containers[0]
    assert isinstance(container, dict)
    container["image"] = "do-not-record-image-value"
    calls: list[list[str]] = []

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_execution_failed",
    ):
        execute_deployed_release_diagnostic(
            package_path=package_path,
            approved_sha256=digest,
            continuation_path=CONTINUATION_PATH,
            receipt_path=receipt_path,
            observation_path=observation_path,
            now=parse_utc("2026-08-16T23:30:00Z"),
            completion_clock=lambda: parse_utc("2026-08-16T23:30:06Z"),
            arm_runner=_arm_runner(raw, calls),
        )

    receipt = json.loads(receipt_path.read_text())
    assert receipt["failure"] == {
        "code": "diagnostic_application_drift",
        "resource_role": "application",
        "stage": "application",
        "mismatch_category": "container_image",
    }
    assert "do-not-record-image-value" not in receipt_path.read_text()
    assert not observation_path.exists()
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600


def test_invalid_diagnostic_fields_fall_back_without_category() -> None:
    error = DeployedReleaseDiagnosticInvalid(
        "diagnostic_application_drift",
        "application",
        "application",
        "unexpected-remote-field",
    )

    assert (error.code, error.stage, error.resource_role, error.mismatch_category) == (
        "diagnostic_package_invalid",
        "local",
        "local",
        None,
    )


@pytest.mark.parametrize("unhashable_category", ([], {}), ids=("list", "mapping"))
def test_unhashable_mismatch_category_falls_back_safely(
    unhashable_category: object,
) -> None:
    error = DeployedReleaseDiagnosticInvalid(
        "diagnostic_application_drift",
        "application",
        "application",
        unhashable_category,  # type: ignore[arg-type]
    )

    assert (error.code, error.stage, error.resource_role, error.mismatch_category) == (
        "diagnostic_package_invalid",
        "local",
        "local",
        None,
    )


def test_mismatch_category_requires_the_application_drift_tuple() -> None:
    error = DeployedReleaseDiagnosticInvalid(
        "diagnostic_revision_drift",
        "revision",
        "revision",
        "revision_state",
    )

    assert (error.code, error.stage, error.resource_role, error.mismatch_category) == (
        "diagnostic_package_invalid",
        "local",
        "local",
        None,
    )


def test_process_crash_leaves_started_receipt_consumed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired: dict[str, object],
) -> None:
    package_path, digest, _package_data = _valid_package(
        tmp_path, monkeypatch, continuation, desired
    )
    receipt_path = tmp_path / "attempt.json"

    def crashing_runner(_command: list[str], **_kwargs: object) -> object:
        assert receipt_path.exists()
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        execute_deployed_release_diagnostic(
            package_path=package_path,
            approved_sha256=digest,
            continuation_path=CONTINUATION_PATH,
            receipt_path=receipt_path,
            observation_path=tmp_path / "observation.json",
            now=parse_utc("2026-08-16T23:30:00Z"),
            arm_runner=crashing_runner,
        )

    assert json.loads(receipt_path.read_text())["status"] == "started"
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600


@pytest.mark.parametrize("status", ("started", "failed", "completed"))
def test_any_existing_receipt_blocks_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired: dict[str, object],
    status: str,
) -> None:
    package_path, digest, _package_data = _valid_package(
        tmp_path, monkeypatch, continuation, desired
    )
    receipt_path = tmp_path / "attempt.json"
    write_owner_json_exclusive(receipt_path, {"status": status})
    calls: list[list[str]] = []

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_package_consumed",
    ):
        execute_deployed_release_diagnostic(
            package_path=package_path,
            approved_sha256=digest,
            continuation_path=CONTINUATION_PATH,
            receipt_path=receipt_path,
            observation_path=tmp_path / "observation.json",
            now=parse_utc("2026-08-16T23:30:00Z"),
            arm_runner=_arm_runner(_raw_payloads(continuation, desired), calls),
        )

    assert calls == []


def test_existing_observation_blocks_attempt_before_arm_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired: dict[str, object],
) -> None:
    package_path, digest, _package_data = _valid_package(
        tmp_path, monkeypatch, continuation, desired
    )
    observation_path = tmp_path / "observation.json"
    write_owner_json_exclusive(observation_path, {"state": "existing"})
    calls: list[list[str]] = []

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_package_consumed",
    ):
        execute_deployed_release_diagnostic(
            package_path=package_path,
            approved_sha256=digest,
            continuation_path=CONTINUATION_PATH,
            receipt_path=tmp_path / "attempt.json",
            observation_path=observation_path,
            now=parse_utc("2026-08-16T23:30:00Z"),
            arm_runner=_arm_runner(_raw_payloads(continuation, desired), calls),
        )

    assert calls == []


def test_direct_entrypoint_help_works_without_pythonpath() -> None:
    completed = subprocess.run(
        [
            str(PROJECT_ROOT / ".venv/bin/python"),
            "scripts/run_deployed_release_diagnostic.py",
            "--help",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": str(PROJECT_ROOT / ".venv/bin")},
    )

    assert completed.returncode == 0, completed.stderr
    for argument in (
        "--package",
        "--approved-sha256",
        "--continuation",
        "--receipt",
        "--observation",
    ):
        assert argument in completed.stdout
