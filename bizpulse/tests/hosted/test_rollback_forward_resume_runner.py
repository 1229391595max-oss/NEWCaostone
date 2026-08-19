from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = PROJECT_ROOT / ".tmp/run_approved_rollback_forward_resume.py"


def _runner_module():
    if not RUNNER_PATH.is_file():
        pytest.skip("consumed rollback-forward runner is not a source artifact")
    specification = importlib.util.spec_from_file_location(
        "rollback_forward_resume_runner", RUNNER_PATH
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_executor_revalidates_authority_before_every_forward_stage() -> None:
    runner = _runner_module()
    authority = {
        "execution_order": [
            "rollback_preflight",
            "registry_verify",
            "recover",
            "health",
        ],
        "commands": {
            "rollback_preflight": ["python preflight.py"],
            "registry_verify": ["python verify.py one", "python verify.py two"],
            "recover": ["python recover.py"],
            "health": ["python health.py"],
        },
    }
    calls: list[tuple[str, ...]] = []
    validations = 0

    def validator():
        nonlocal validations
        validations += 1
        return authority

    def command_runner(command, **_kwargs):
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    runner.execute(
        authority,
        base_environment={"PATH": "/usr/bin:/bin"},
        validator=validator,
        command_runner=command_runner,
    )

    assert calls == [
        ("python", "preflight.py"),
        ("python", "verify.py", "one"),
        ("python", "verify.py", "two"),
        ("python", "recover.py"),
        ("python", "health.py"),
    ]
    assert validations == 9


def test_executor_stops_before_command_when_authority_changes() -> None:
    runner = _runner_module()
    authority = {
        "execution_order": [
            "rollback_preflight",
            "registry_verify",
            "recover",
            "health",
        ],
        "commands": {
            "rollback_preflight": ["python preflight.py"],
            "registry_verify": ["python verify.py"],
            "recover": ["python recover.py"],
            "health": ["python health.py"],
        },
    }
    calls: list[tuple[str, ...]] = []

    with pytest.raises(
        runner.ForwardResumeExecutionInvalid, match="forward_authority_changed"
    ):
        runner.execute(
            authority,
            base_environment={"PATH": "/usr/bin:/bin"},
            validator=lambda: {**authority, "changed": True},
            command_runner=lambda command, **_kwargs: calls.append(tuple(command)),
        )

    assert calls == []
