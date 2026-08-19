from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from scripts.run_azure_job import AzureJobFailed, run_job_to_completion


def test_job_runner_starts_once_and_waits_for_exact_execution() -> None:
    calls: list[tuple[str, ...]] = []
    outputs = iter(("execution-123\n", "Running\n", "Succeeded\n"))

    def runner(command, **kwargs):
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, stdout=next(outputs), stderr="")

    result = run_job_to_completion(
        subscription_id="11111111-1111-4111-8111-111111111111",
        resource_group="rg-approved",
        job_name="bp-approved-prepare",
        timeout_seconds=60,
        runner=runner,
        monotonic=iter((0.0, 0.0, 1.0, 2.0)).__next__,
        sleeper=lambda _seconds: None,
    )

    assert result == "execution-123"
    assert sum(call[2:4] == ("job", "start") for call in calls) == 1
    assert all("execution-123" in call[-3] for call in calls[1:])


def test_job_runner_starts_with_one_exact_private_execution_template() -> None:
    outputs = iter(("execution-123\n", "Succeeded\n"))
    observed_template: dict[str, object] = {}
    template = {
        "containers": [
            {
                "name": "prepare",
                "image": "registry.example/bizpulse@sha256:" + "a" * 64,
                "command": ["python"],
                "args": ["scripts/prepare_cloud.py"],
                "env": [
                    {"name": "BIZPULSE_DATABASE_URL", "secretRef": "database-url"}
                ],
                "resources": {"cpu": 0.5, "memory": "1Gi"},
            }
        ],
        "initContainers": [],
        "volumes": [],
    }

    def runner(command, **kwargs):
        if command[2:4] == ["job", "start"]:
            template_path = Path(command[command.index("--yaml") + 1])
            assert template_path.is_file()
            assert template_path.stat().st_mode & 0o777 == 0o400
            observed_template.update(json.loads(template_path.read_text()))
        return subprocess.CompletedProcess(command, 0, stdout=next(outputs), stderr="")

    run_job_to_completion(
        subscription_id="11111111-1111-4111-8111-111111111111",
        resource_group="rg-approved",
        job_name="bp-approved-prepare",
        timeout_seconds=60,
        execution_template=template,
        runner=runner,
        monotonic=iter((0.0, 0.0, 1.0)).__next__,
        sleeper=lambda _seconds: None,
    )

    assert observed_template == template


@pytest.mark.parametrize("terminal", ["Failed", "Stopped", "Degraded"])
def test_job_runner_fails_closed_on_non_success_terminal(terminal: str) -> None:
    outputs = iter(("execution-123\n", f"{terminal}\n"))

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=next(outputs), stderr="")

    with pytest.raises(AzureJobFailed, match="azure_job_not_succeeded"):
        run_job_to_completion(
            subscription_id="11111111-1111-4111-8111-111111111111",
            resource_group="rg-approved",
            job_name="bp-approved-seed",
            timeout_seconds=60,
            runner=runner,
            monotonic=iter((0.0, 0.0, 1.0)).__next__,
            sleeper=lambda _seconds: None,
        )


def test_job_runner_does_not_retry_ambiguous_start() -> None:
    calls = 0

    def runner(command, **kwargs):
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"])

    with pytest.raises(AzureJobFailed, match="azure_job_start_outcome_unknown"):
        run_job_to_completion(
            subscription_id="11111111-1111-4111-8111-111111111111",
            resource_group="rg-approved",
            job_name="bp-approved-prepare",
            timeout_seconds=60,
            runner=runner,
        )
    assert calls == 1


def test_job_runner_can_use_an_explicit_minimal_child_environment() -> None:
    outputs = iter(("execution-123\n", "Succeeded\n"))
    environments: list[dict[str, str]] = []

    def runner(command, **kwargs):
        environments.append(kwargs["env"])
        return subprocess.CompletedProcess(command, 0, stdout=next(outputs), stderr="")

    run_job_to_completion(
        subscription_id="11111111-1111-4111-8111-111111111111",
        resource_group="rg-approved",
        job_name="bp-approved-prepare",
        timeout_seconds=60,
        runner=runner,
        environment={"HOME": "/tmp/rotation", "PATH": "/usr/bin:/bin"},
        monotonic=iter((0.0, 0.0, 1.0)).__next__,
        sleeper=lambda _seconds: None,
    )

    assert environments == [
        {"HOME": "/tmp/rotation", "PATH": "/usr/bin:/bin"},
        {"HOME": "/tmp/rotation", "PATH": "/usr/bin:/bin"},
    ]
