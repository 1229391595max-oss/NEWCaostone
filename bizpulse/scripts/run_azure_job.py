"""Start one approved Container Apps Job and wait for its exact execution."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence

UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]{1,62}[a-z0-9]")
IN_FLIGHT = frozenset({"Pending", "Processing", "Running", "Starting"})


class AzureJobFailed(RuntimeError):
    """The single authorized execution did not prove a successful result."""


def _invoke(
    command: Sequence[str],
    *,
    timeout: float,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    environment: Mapping[str, str] | None = None,
) -> str:
    keyword_arguments: dict[str, object] = {
        "check": True,
        "capture_output": True,
        "text": True,
        "timeout": timeout,
    }
    if environment is not None:
        keyword_arguments["env"] = dict(environment)
    result = runner(list(command), **keyword_arguments)
    output = result.stdout.strip()
    if len(output) > 512 or "\n" in output or "\r" in output:
        raise AzureJobFailed("azure_job_response_invalid")
    return output


def run_job_to_completion(
    *,
    subscription_id: str,
    resource_group: str,
    job_name: str,
    timeout_seconds: int,
    execution_template: Mapping[str, object] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    environment: Mapping[str, str] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> str:
    """Start exactly once, then poll only the returned execution identity."""

    if (
        UUID_PATTERN.fullmatch(subscription_id) is None
        or NAME_PATTERN.fullmatch(resource_group) is None
        or NAME_PATTERN.fullmatch(job_name) is None
        or not 60 <= timeout_seconds <= 1_900
    ):
        raise AzureJobFailed("azure_job_authority_invalid")
    authority_flags = (
        "--name",
        job_name,
        "--resource-group",
        resource_group,
        "--subscription",
        subscription_id,
        "--only-show-errors",
    )
    template_arguments: tuple[str, ...] = ()
    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    if execution_template is not None:
        try:
            encoded_template = json.dumps(
                execution_template,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        except (TypeError, ValueError) as error:
            raise AzureJobFailed("azure_job_authority_invalid") from error
        if len(encoded_template) > 100_000 or set(execution_template) != {
            "containers",
            "initContainers",
            "volumes",
        }:
            raise AzureJobFailed("azure_job_authority_invalid")
        temporary_directory = tempfile.TemporaryDirectory(
            prefix="newcaostone-job-template-"
        )
        template_path = Path(temporary_directory.name) / "execution-template.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(template_path, flags, 0o400)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded_template)
            template_path.chmod(0o400)
        except OSError as error:
            temporary_directory.cleanup()
            raise AzureJobFailed("azure_job_authority_invalid") from error
        template_arguments = ("--yaml", str(template_path))
    deadline = monotonic() + timeout_seconds
    try:
        execution_id = _invoke(
            (
                "az",
                "containerapp",
                "job",
                "start",
                *authority_flags,
                *template_arguments,
                "--query",
                "name",
                "--output",
                "tsv",
            ),
            timeout=min(60.0, float(timeout_seconds)),
            runner=runner,
            environment=environment,
        )
    except (subprocess.SubprocessError, OSError, AzureJobFailed) as error:
        raise AzureJobFailed("azure_job_start_outcome_unknown") from error
    finally:
        if temporary_directory is not None:
            temporary_directory.cleanup()
    if NAME_PATTERN.fullmatch(execution_id) is None:
        raise AzureJobFailed("azure_job_start_outcome_unknown")

    query = f"[?name=='{execution_id}'].properties.status | [0]"
    read_failures = 0
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise AzureJobFailed("azure_job_wait_timeout")
        try:
            status = _invoke(
                (
                    "az",
                    "containerapp",
                    "job",
                    "execution",
                    "list",
                    *authority_flags,
                    "--query",
                    query,
                    "--output",
                    "tsv",
                ),
                timeout=min(30.0, remaining),
                runner=runner,
                environment=environment,
            )
        except (subprocess.SubprocessError, OSError, AzureJobFailed) as error:
            read_failures += 1
            if read_failures > 1:
                raise AzureJobFailed("azure_job_status_unavailable") from error
            sleeper(min(5.0, max(0.0, deadline - monotonic())))
            continue
        if status == "Succeeded":
            return execution_id
        if status not in IN_FLIGHT:
            raise AzureJobFailed("azure_job_not_succeeded")
        sleeper(min(5.0, max(0.0, deadline - monotonic())))


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--timeout-seconds", required=True, type=int)
    options = parser.parse_args(arguments)
    try:
        execution_id = run_job_to_completion(
            subscription_id=options.subscription,
            resource_group=options.resource_group,
            job_name=options.job,
            timeout_seconds=options.timeout_seconds,
        )
    except AzureJobFailed:
        print("job_execution=failed")
        return 1
    print("job_execution=succeeded")
    print(f"execution_id={execution_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
