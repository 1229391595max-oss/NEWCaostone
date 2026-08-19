from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

import pytest

from scripts.create_deployed_release_diagnostic_package import (
    AUTHORIZED_BRANCH,
    D3_ENTRYPOINTS,
    HEADER,
    build_deployed_release_diagnostic_package,
    discover_control_paths,
    load_deployed_release_diagnostic_package,
    write_deployed_release_diagnostic_package,
)
from scripts.deployed_release_diagnostic_contract import (
    DeployedReleaseDiagnosticInvalid,
)
from scripts.verify_deployed_release_state import (
    load_deployed_release_continuation,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTINUATION_REFERENCE = (
    "release/incidents/2026-08-16-recovery-v4-deployed-continuation.json"
)
CONTINUATION_PATH = PROJECT_ROOT / CONTINUATION_REFERENCE
CONTINUATION_SHA256 = "d355c9215ee9dec22adb93392705107dfd8f06db37ca8d03b240c519278af4af"
AUTHORIZATION_ID = "11111111-1111-4111-8111-111111111111"
ISSUED_AT = "2026-08-16T23:00:00Z"
EXPIRES_AT = "2026-08-17T23:00:00Z"
REPOSITORY = {
    "branch": "codex/deployed-diagnostic-d3",
    "head_sha": "1" * 40,
    "tracked_clean_required": True,
    "tree_sha": "2" * 40,
}
TOOLCHAIN = {
    "azure_cli": "2.77.0",
    "bicep": "0.46.1",
    "containerapp_extension_observed": "1.3.1",
    "python": "Python 3.12.11",
}
CONTROL_SHA256 = {
    "infra/modules/app.bicep": "3" * 64,
    "package-lock.json": "4" * 64,
    "scripts/build_deployed_release_desired_projection.py": "5" * 64,
}


@pytest.fixture(scope="module")
def continuation() -> dict[str, object]:
    return load_deployed_release_continuation(
        CONTINUATION_PATH,
        expected_sha256=CONTINUATION_SHA256,
    )


@pytest.fixture(scope="module")
def desired_projection() -> dict[str, object]:
    return {
        "application": {"resource_name": "newcaostone-demo-app"},
        "continuation_sha256": CONTINUATION_SHA256,
        "jobs": {},
        "schema_version": ("newcaostone.deployed-release-desired-projection.v1"),
    }


def _git_runner(
    command: list[str], **_kwargs: object
) -> subprocess.CompletedProcess[str]:
    outputs = {
        ("git", "branch", "--show-current"): REPOSITORY["branch"] + "\n",
        ("git", "rev-parse", "HEAD"): REPOSITORY["head_sha"] + "\n",
        ("git", "rev-parse", "HEAD^{tree}"): REPOSITORY["tree_sha"] + "\n",
        ("git", "status", "--porcelain=v1", "--untracked-files=no"): "",
    }
    return subprocess.CompletedProcess(
        command,
        0,
        stdout=outputs[tuple(command)],
        stderr="",
    )


def _command_runner(
    command: list[str], **_kwargs: object
) -> subprocess.CompletedProcess[str]:
    if command[-1] == "--version":
        output = TOOLCHAIN["python"] + "\n"
    elif command == ["az", "version", "--output", "json"]:
        output = json.dumps(
            {
                "azure-cli": TOOLCHAIN["azure_cli"],
                "extensions": {
                    "containerapp": TOOLCHAIN["containerapp_extension_observed"]
                },
            }
        )
    else:
        assert command == ["az", "bicep", "version"]
        output = f"Bicep CLI version {TOOLCHAIN['bicep']} (fixture)\n"
    return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")


def _build(
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired_projection: dict[str, object],
    *,
    git_runner=_git_runner,
    expires_at: str = EXPIRES_AT,
    continuation_reference: str = CONTINUATION_REFERENCE,
) -> dict[str, object]:
    monkeypatch.setattr(
        "scripts.create_deployed_release_diagnostic_package._control_sha256",
        lambda: CONTROL_SHA256,
    )
    return build_deployed_release_diagnostic_package(
        continuation=continuation,
        continuation_reference=continuation_reference,
        continuation_sha256=CONTINUATION_SHA256,
        desired_projection=desired_projection,
        authorization_id=AUTHORIZATION_ID,
        issued_at=ISSUED_AT,
        expires_at=expires_at,
        git_runner=git_runner,
        command_runner=_command_runner,
    )


def _expected_arm_paths(continuation: dict[str, object]) -> list[str]:
    target = continuation["target"]
    prefix = (
        f"/subscriptions/{target['subscription_id']}/resourceGroups/"
        f"{target['resource_group']}/providers/Microsoft.App"
    )
    application = f"{prefix}/containerApps/{target['application']}"
    paths = [application, f"{application}/revisions"]
    for key in (
        "prepare_job",
        "seed_job",
        "session_maintenance_job",
        "storage_maintenance_job",
    ):
        job = f"{prefix}/jobs/{target[key]}"
        paths.extend((job, f"{job}/executions"))
    return paths


def test_package_binds_clean_repository_projection_controls_and_limits(
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired_projection: dict[str, object],
) -> None:
    package = _build(monkeypatch, continuation, desired_projection)

    assert package["schema_version"] == (
        "newcaostone.deployed-release-diagnostic-package.v2"
    )
    assert package["attempt_schema"] == (
        "newcaostone.deployed-release-diagnostic-attempt.v2"
    )
    assert package["repository"] == REPOSITORY
    assert package["repository"]["branch"] == AUTHORIZED_BRANCH
    assert D3_ENTRYPOINTS == (
        "scripts/build_deployed_release_desired_projection.py",
        "scripts/create_deployed_release_diagnostic_package.py",
        "scripts/deployed_release_diagnostic_contract.py",
        "scripts/observe_deployed_release_state.py",
        "scripts/run_deployed_release_diagnostic.py",
    )
    assert package["repository"]["tracked_clean_required"] is True
    assert package["toolchain"] == TOOLCHAIN
    assert package["control_sha256"] == CONTROL_SHA256
    assert package["arm"] == {
        "allowed_http_methods": ["GET"],
        "allowed_resource_paths": _expected_arm_paths(continuation),
        "api_version": "2024-03-01",
        "host": "management.azure.com",
        "max_page_bytes": 1_000_000,
        "max_pages_per_collection": 5,
        "max_total_requests": 30,
        "max_total_response_bytes": 8_000_000,
        "request_retry_limit": 0,
        "request_timeout_seconds": 30,
    }
    assert package["forbidden_operations"] == [
        "azure_mutation",
        "registry_access",
        "keychain_access",
        "public_url_access",
        "ai_access",
    ]
    assert package["allowed_operations"] == [
        "local_contract_validation",
        "azure_resource_manager_read",
        "local_attempt_receipt_write",
        "local_sanitized_observation_write",
    ]
    assert (
        package["desired_projection_sha256"]
        == hashlib.sha256(
            json.dumps(
                desired_projection,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
    )


def test_package_rejects_dirty_tracked_repository(
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired_projection: dict[str, object],
) -> None:
    def dirty_git(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        completed = _git_runner(command, **kwargs)
        if command[:2] == ["git", "status"]:
            completed.stdout = " M scripts/changed.py\n"
        return completed

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_repository_drift",
    ):
        _build(
            monkeypatch,
            continuation,
            desired_projection,
            git_runner=dirty_git,
        )


def test_package_rejects_old_implementation_branch(
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired_projection: dict[str, object],
) -> None:
    def old_branch_git(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        completed = _git_runner(command, **kwargs)
        if command == ["git", "branch", "--show-current"]:
            completed.stdout = "codex/integrated-viewer-ai-anti-drift\n"
        return completed

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_repository_drift",
    ):
        _build(
            monkeypatch,
            continuation,
            desired_projection,
            git_runner=old_branch_git,
        )


@pytest.mark.parametrize(
    ("expires_at", "reference"),
    (
        ("2026-08-18T23:00:01Z", CONTINUATION_REFERENCE),
        (EXPIRES_AT, "../recovery-v4-deployed-continuation.json"),
    ),
)
def test_package_rejects_expiry_over_24_hours_and_path_traversal(
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired_projection: dict[str, object],
    expires_at: str,
    reference: str,
) -> None:
    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_package_invalid",
    ):
        _build(
            monkeypatch,
            continuation,
            desired_projection,
            expires_at=expires_at,
            continuation_reference=reference,
        )


def test_package_writer_is_owner_only_exclusive_and_digest_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired_projection: dict[str, object],
) -> None:
    package = _build(monkeypatch, continuation, desired_projection)
    output = tmp_path / "D3.md"

    digest = write_deployed_release_diagnostic_package(output, package)

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert digest == hashlib.sha256(output.read_bytes()).hexdigest()
    assert HEADER == "# NEWCaostone Deployed Release Diagnostic D3 Authorization"
    assert output.read_text().startswith(HEADER + "\n\n```json\n")
    with pytest.raises(FileExistsError):
        write_deployed_release_diagnostic_package(output, package)


def _patch_current_facts(
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired_projection: dict[str, object],
) -> None:
    monkeypatch.setattr(
        "scripts.create_deployed_release_diagnostic_package._repository_state",
        lambda _runner: REPOSITORY,
    )
    monkeypatch.setattr(
        "scripts.create_deployed_release_diagnostic_package._toolchain_state",
        lambda _runner: TOOLCHAIN,
    )
    monkeypatch.setattr(
        "scripts.create_deployed_release_diagnostic_package._control_sha256",
        lambda: CONTROL_SHA256,
    )
    monkeypatch.setattr(
        "scripts.create_deployed_release_diagnostic_package.load_deployed_release_continuation",
        lambda _path, *, expected_sha256: continuation,
    )
    monkeypatch.setattr(
        "scripts.create_deployed_release_diagnostic_package.compile_desired_projection",
        lambda _path, _continuation, *, continuation_sha256: desired_projection,
    )


@pytest.mark.parametrize(
    ("case", "expected_code"),
    (
        ("repository_head", "diagnostic_repository_drift"),
        ("repository_tree", "diagnostic_repository_drift"),
        ("toolchain", "diagnostic_toolchain_drift"),
        ("control_bicep", "diagnostic_control_drift"),
        ("control_lock", "diagnostic_control_drift"),
        ("desired_projection", "diagnostic_bicep_projection_invalid"),
    ),
)
def test_package_loader_rejects_bound_fact_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired_projection: dict[str, object],
    case: str,
    expected_code: str,
) -> None:
    package = _build(monkeypatch, continuation, desired_projection)
    drifted = deepcopy(package)
    if case == "repository_head":
        drifted["repository"]["head_sha"] = "9" * 40
    elif case == "repository_tree":
        drifted["repository"]["tree_sha"] = "9" * 40
    elif case == "toolchain":
        drifted["toolchain"]["bicep"] = "0.0.0"
    elif case == "control_bicep":
        drifted["control_sha256"]["infra/modules/app.bicep"] = "9" * 64
    elif case == "control_lock":
        drifted["control_sha256"]["package-lock.json"] = "9" * 64
    else:
        drifted["desired_projection_sha256"] = "9" * 64
    output = tmp_path / f"{case}.md"
    write_deployed_release_diagnostic_package(output, drifted)
    _patch_current_facts(monkeypatch, continuation, desired_projection)

    with pytest.raises(DeployedReleaseDiagnosticInvalid, match=expected_code):
        load_deployed_release_diagnostic_package(
            output,
            continuation_path=CONTINUATION_PATH,
            now=datetime(2026, 8, 17, tzinfo=UTC),
        )


def test_package_loader_rejects_duplicate_json_key_and_wrong_mode(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.md"
    duplicate.write_text(
        HEADER + '\n\n```json\n{"schema_version":"one","schema_version":"two"}\n```\n'
    )
    os.chmod(duplicate, 0o600)

    with pytest.raises(DeployedReleaseDiagnosticInvalid):
        load_deployed_release_diagnostic_package(
            duplicate,
            continuation_path=CONTINUATION_PATH,
            now=datetime(2026, 8, 17, tzinfo=UTC),
        )
    os.chmod(duplicate, 0o644)
    with pytest.raises(DeployedReleaseDiagnosticInvalid):
        load_deployed_release_diagnostic_package(
            duplicate,
            continuation_path=CONTINUATION_PATH,
            now=datetime(2026, 8, 17, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "case",
    ("missing_attempt_schema", "v1_attempt_schema", "unknown_key", "d2_branch"),
)
def test_package_loader_rejects_non_d3_identity_before_arm_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired_projection: dict[str, object],
    case: str,
) -> None:
    package = _build(monkeypatch, continuation, desired_projection)
    invalid = deepcopy(package)
    if case == "missing_attempt_schema":
        invalid.pop("attempt_schema")
    elif case == "v1_attempt_schema":
        invalid["attempt_schema"] = "newcaostone.deployed-release-diagnostic-attempt.v1"
    elif case == "unknown_key":
        invalid["unknown"] = "not-authorized"
    else:
        invalid["repository"]["branch"] = (
            "codex/integrated-viewer-ai-anti-drift-d2-integration"
        )
    output = tmp_path / f"{case}.md"
    write_deployed_release_diagnostic_package(output, invalid)

    with pytest.raises(DeployedReleaseDiagnosticInvalid, match="diagnostic_package_invalid"):
        load_deployed_release_diagnostic_package(
            output,
            continuation_path=CONTINUATION_PATH,
            now=datetime(2026, 8, 17, tzinfo=UTC),
        )

def test_control_discovery_follows_local_imports_and_bound_data(
    tmp_path: Path,
) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts/entry.py").write_text(
        "from scripts.helper import VALUE\nfrom src.local import service\n"
    )
    (tmp_path / "scripts/helper.py").write_text("VALUE = 1\n")
    (tmp_path / "src/local.py").write_text("service = 'safe'\n")
    (tmp_path / "bound.txt").write_text("bound\n")

    paths = discover_control_paths(
        project_root=tmp_path,
        entrypoints=("scripts/entry.py",),
        bound_data_paths=("bound.txt",),
    )

    assert paths == (
        "bound.txt",
        "scripts/entry.py",
        "scripts/helper.py",
        "src/local.py",
    )
