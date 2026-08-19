"""Read back the disabled phase-1 application and maintenance fences."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]{1,62}[a-z0-9]")
IMAGE_PATTERN = re.compile(
    r"[a-z0-9]{5,50}\.azurecr\.io/[a-z0-9][a-z0-9._/-]{1,127}@sha256:[0-9a-f]{64}"
)
STORAGE_ACCOUNT_PATTERN = re.compile(r"[a-z0-9]{3,24}")
BLOB_CONTAINER_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])")
TERMINAL_EXECUTION_STATES = frozenset({"Failed", "Stopped", "Succeeded"})
ACTIVE_EXECUTION_STATES = frozenset({"Deactivating", "Processing", "Queued", "Running"})
EXPECTED_APP_PROBES = [
    {
        "type": "Liveness",
        "httpGet": {"path": "/health/live", "port": 8000, "scheme": "HTTP"},
        "initialDelaySeconds": 15,
        "periodSeconds": 30,
        "timeoutSeconds": 5,
        "failureThreshold": 3,
    },
    {
        "type": "Readiness",
        "httpGet": {"path": "/health/ready", "port": 8000, "scheme": "HTTP"},
        "initialDelaySeconds": 10,
        "periodSeconds": 10,
        "timeoutSeconds": 5,
        "failureThreshold": 3,
    },
]
PHASE1_VALUE_ENV = {"BIZPULSE_RUNTIME_ENVIRONMENT": "phase1-fenced"}
PHASE2_SECRET_REFS = {
    "BIZPULSE_DATABASE_URL": "database-url",
    "BIZPULSE_BLOB_CONNECTION_STRING": "blob-connection-string",
    "BIZPULSE_OPERATOR_PASSWORD_HASH": "operator-password-hash",
    "BIZPULSE_SESSION_PEPPER": "session-pepper",
}
PHASE2_SECRET_NAMES = frozenset(PHASE2_SECRET_REFS.values())


class Phase1FenceFailed(RuntimeError):
    """Phase 1 did not prove that public and scheduled writes are fenced."""


def _read(
    arguments: tuple[str, ...],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> Any:
    try:
        completed = runner(
            ["az", *arguments, "--only-show-errors", "--output", "json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise Phase1FenceFailed("phase1_fence_read_failed") from error
    if len(completed.stdout) > 1_000_000:
        raise Phase1FenceFailed("phase1_fence_response_invalid")
    try:
        return json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise Phase1FenceFailed("phase1_fence_response_invalid") from error


def _env_authority(
    container: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    rows = container.get("env")
    if not isinstance(rows, list):
        raise Phase1FenceFailed("phase1_app_not_fenced")
    values: dict[str, str] = {}
    secret_refs: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) not in (
            {"name", "value"},
            {"name", "secretRef"},
        ):
            raise Phase1FenceFailed("phase1_app_not_fenced")
        name = row.get("name")
        if not isinstance(name, str) or name in values or name in secret_refs:
            raise Phase1FenceFailed("phase1_app_not_fenced")
        if "value" in row:
            value = row["value"]
            if not isinstance(value, str):
                raise Phase1FenceFailed("phase1_app_not_fenced")
            values[name] = value
        else:
            secret_ref = row["secretRef"]
            if not isinstance(secret_ref, str):
                raise Phase1FenceFailed("phase1_app_not_fenced")
            secret_refs[name] = secret_ref
    return values, secret_refs


def _secret_names(configuration: dict[str, Any]) -> frozenset[str]:
    rows = configuration.get("secrets")
    if not isinstance(rows, list):
        raise Phase1FenceFailed("phase1_app_not_fenced")
    names: list[str] = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) - {"name", "value"}
            or not isinstance(row.get("name"), str)
            or ("value" in row and row["value"] not in (None, ""))
        ):
            raise Phase1FenceFailed("phase1_app_not_fenced")
        names.append(row["name"])
    if len(names) != len(set(names)):
        raise Phase1FenceFailed("phase1_app_not_fenced")
    return frozenset(names)


def _require_phase1_app(
    container: dict[str, Any],
    configuration: dict[str, Any],
) -> None:
    value_env, secret_env = _env_authority(container)
    if (
        container.get("name") != "bizpulse"
        or container.get("command") != ["python"]
        or container.get("args") != ["scripts/phase1_fence_server.py"]
        or value_env != PHASE1_VALUE_ENV
        or secret_env
        or configuration.get("secrets") not in (None, [])
        or container.get("probes") != EXPECTED_APP_PROBES
    ):
        raise Phase1FenceFailed("phase1_app_not_fenced")


def _require_phase2_app(
    container: dict[str, Any],
    configuration: dict[str, Any],
    expected_values: dict[str, str],
    *,
    ai_enabled: bool,
) -> None:
    value_env, secret_env = _env_authority(container)
    insights = value_env.pop("APPLICATIONINSIGHTS_CONNECTION_STRING", None)
    expected_secret_refs = dict(PHASE2_SECRET_REFS)
    expected_secret_names = set(PHASE2_SECRET_NAMES)
    if ai_enabled:
        expected_secret_refs["OPENAI_API_KEY"] = "openai-api-key"
        expected_secret_names.add("openai-api-key")
    if (
        container.get("name") != "bizpulse"
        or container.get("command") not in (None, [])
        or container.get("args") not in (None, [])
        or value_env != expected_values
        or secret_env != expected_secret_refs
        or _secret_names(configuration) != frozenset(expected_secret_names)
        or container.get("probes") != EXPECTED_APP_PROBES
        or not isinstance(insights, str)
        or not 1 <= len(insights) <= 4096
        or "\n" in insights
        or not insights.startswith("InstrumentationKey=")
        or "IngestionEndpoint=https://" not in insights
    ):
        raise Phase1FenceFailed("phase1_app_not_fenced")


def verify_phase1_fence(
    *,
    subscription_id: str,
    resource_group: str,
    app_name: str,
    image: str,
    job_names: tuple[str, str, str, str],
    storage_account_name: str,
    blob_container_name: str,
    mode: str = "initial",
    expected_revision_name: str | None = None,
    not_before: datetime | None = None,
    synthetic_manifest_sha256: str | None = None,
    synthetic_dataset_version_id: str | None = None,
    environment_name: str | None = None,
    ai_enabled: bool | None = None,
    ai_daily_attempt_limit: int | None = None,
    ai_monthly_token_limit: int | None = None,
    ai_max_concurrent_turns: int | None = None,
    ai_session_attempt_limit_per_minute: int | None = None,
    ai_global_attempt_limit_per_minute: int | None = None,
    demo_session_rate_limit_per_hour: int | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    drain_timeout_seconds: int = 600,
) -> None:
    if (
        UUID_PATTERN.fullmatch(subscription_id) is None
        or NAME_PATTERN.fullmatch(resource_group) is None
        or NAME_PATTERN.fullmatch(app_name) is None
        or IMAGE_PATTERN.fullmatch(image) is None
        or STORAGE_ACCOUNT_PATTERN.fullmatch(storage_account_name) is None
        or BLOB_CONTAINER_PATTERN.fullmatch(blob_container_name) is None
        or len(set(job_names)) != 4
        or any(NAME_PATTERN.fullmatch(name) is None for name in job_names)
        or mode not in {"activate", "initial", "phase2"}
        or (
            expected_revision_name is not None
            and (
                mode != "phase2"
                or re.fullmatch(
                    rf"{re.escape(app_name)}--[a-z0-9](?:[a-z0-9-]{{0,62}}[a-z0-9])?",
                    expected_revision_name,
                )
                is None
            )
        )
        or (mode in {"activate", "phase2"} and not_before is None)
        or synthetic_manifest_sha256 is None
        or synthetic_dataset_version_id is None
        or (
            synthetic_manifest_sha256 is not None
            and re.fullmatch(r"[0-9a-f]{64}", synthetic_manifest_sha256) is None
        )
        or (
            synthetic_dataset_version_id is not None
            and re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                synthetic_dataset_version_id,
            )
            is None
        )
        or not 300 <= drain_timeout_seconds <= 900
        or (
            mode == "phase2"
            and (
                environment_name is None
                or NAME_PATTERN.fullmatch(environment_name) is None
                or ai_enabled is None
                or any(
                    type(value) is not int or value < 1
                    for value in (
                        ai_daily_attempt_limit,
                        ai_monthly_token_limit,
                        ai_max_concurrent_turns,
                        ai_session_attempt_limit_per_minute,
                        ai_global_attempt_limit_per_minute,
                        demo_session_rate_limit_per_hour,
                    )
                )
            )
        )
    ):
        raise Phase1FenceFailed("phase1_fence_authority_invalid")
    common = (
        "--subscription",
        subscription_id,
        "--resource-group",
        resource_group,
    )
    app = _read(
        ("containerapp", "show", *common, "--name", app_name),
        runner=runner,
    )
    if not isinstance(app, dict):
        raise Phase1FenceFailed("phase1_app_not_fenced")
    properties = app.get("properties", {})
    if not isinstance(properties, dict):
        raise Phase1FenceFailed("phase1_app_not_fenced")
    configuration = properties.get("configuration", {})
    template = properties.get("template", {})
    if not isinstance(configuration, dict) or not isinstance(template, dict):
        raise Phase1FenceFailed("phase1_app_not_fenced")
    containers = template.get("containers", [])
    digest = image.rsplit(":", 1)[1]
    expected_revision = expected_revision_name or (
        f"{app_name}--{digest[:12]}"
        if mode == "phase2"
        else f"{app_name}--prep-{digest[:7]}"
    )
    expected_external = mode == "phase2"
    expected_min_replicas = 1 if mode == "phase2" else 0
    expected_environment_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        "/providers/Microsoft.App/managedEnvironments/"
        f"{environment_name}"
    )
    ingress = configuration.get("ingress", {})
    fqdn = ingress.get("fqdn")
    expected_phase2_env = {
        "BIZPULSE_RUNTIME_ENVIRONMENT": "cloud",
        "BIZPULSE_BLOB_ENDPOINT": (
            f"https://{storage_account_name}.blob.core.windows.net/"
        ),
        "BIZPULSE_BLOB_CONTAINER": blob_container_name,
        "BIZPULSE_ALLOWED_ORIGIN": (
            f"https://{fqdn}" if isinstance(fqdn, str) else ""
        ),
        "BIZPULSE_AI_CHAT_ENABLED": str(ai_enabled).lower(),
        "BIZPULSE_AI_DAILY_ATTEMPT_LIMIT": str(ai_daily_attempt_limit),
        "BIZPULSE_AI_MONTHLY_TOKEN_LIMIT": str(ai_monthly_token_limit),
        "BIZPULSE_AI_MAX_CONCURRENT_TURNS": str(ai_max_concurrent_turns),
        "BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE": str(
            ai_session_attempt_limit_per_minute
        ),
        "BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE": str(
            ai_global_attempt_limit_per_minute
        ),
        "BIZPULSE_DEMO_SESSION_RATE_LIMIT_PER_HOUR": str(
            demo_session_rate_limit_per_hour
        ),
        "BIZPULSE_OPENAI_MODEL": "gpt-5.4-nano-2026-03-17",
        "BIZPULSE_OPENAI_REASONING_EFFORT": "low",
    }
    if (
        not isinstance(ingress, dict)
        or not isinstance(containers, list)
        or len(containers) != 1
        or not isinstance(containers[0], dict)
    ):
        raise Phase1FenceFailed("phase1_app_not_fenced")
    container = containers[0]
    if mode == "phase2":
        _require_phase2_app(
            container,
            configuration,
            expected_phase2_env,
            ai_enabled=ai_enabled is True,
        )
    else:
        _require_phase1_app(container, configuration)
    if (
        app.get("name") != app_name
        or properties.get("latestRevisionName") != expected_revision
        or (
            mode == "phase2"
            and (
                properties.get("latestReadyRevisionName") != expected_revision
                or properties.get("provisioningState") != "Succeeded"
            )
        )
        or ingress.get("external") is not expected_external
        or configuration.get("activeRevisionsMode") != "Single"
        or ingress.get("traffic") != [{"latestRevision": True, "weight": 100}]
        or template.get("scale", {}).get("minReplicas") != expected_min_replicas
        or template.get("scale", {}).get("maxReplicas") != 1
        or container.get("image") != image
        or (
            mode == "phase2"
            and (
                properties.get("environmentId") != expected_environment_id
            )
        )
    ):
        raise Phase1FenceFailed("phase1_app_not_fenced")

    deadline = monotonic() + drain_timeout_seconds
    while True:
        revisions = _read(
            ("containerapp", "revision", "list", *common, "--name", app_name),
            runner=runner,
        )
        if not isinstance(revisions, list) or not revisions or any(
            not isinstance(revision, dict)
            or type(revision.get("properties", {}).get("replicas")) is not int
            or revision.get("properties", {}).get("replicas") < 0
            for revision in revisions
        ):
            raise Phase1FenceFailed("phase1_revision_read_invalid")
        if mode == "phase2" and any(
            revision.get("name") == expected_revision
            and revision["properties"]["replicas"] >= 1
            for revision in revisions
        ):
            break
        if mode != "phase2" and all(
            revision["properties"]["replicas"] == 0 for revision in revisions
        ):
            break
        if monotonic() >= deadline:
            raise Phase1FenceFailed("phase1_replicas_not_drained")
        sleeper(5)

    job_specs = (
        ("prepare", ["scripts/prepare_cloud.py"]),
        (
            "seed",
            [
                "scripts/seed_demo.py",
                "tests/fixtures/synthetic/v1",
                "--expected-manifest-sha256",
                synthetic_manifest_sha256,
                "--expected-dataset-version-id",
                synthetic_dataset_version_id,
            ],
        ),
        ("maintain-sessions", ["scripts/maintain_sessions.py"]),
        (
            "maintain-storage",
            ["scripts/maintain_storage.py", "--expire-temporary"],
        ),
    )
    for index, job_name in enumerate(job_names):
        job = _read(
            ("containerapp", "job", "show", *common, "--name", job_name),
            runner=runner,
        )
        job_containers = job.get("properties", {}).get("template", {}).get("containers", [])
        expected_name, expected_args = job_specs[index]
        configuration = job.get("properties", {}).get("configuration", {})
        expected_trigger = (
            "Schedule" if mode == "phase2" and index >= 2 else "Manual"
        )
        expected_schedule = (
            {
                "cronExpression": "*/15 * * * *" if index == 2 else "0 * * * *",
                "parallelism": 1,
                "replicaCompletionCount": 1,
            }
            if expected_trigger == "Schedule"
            else None
        )
        if (
            job.get("name") != job_name
            or configuration.get("triggerType") != expected_trigger
            or (
                expected_schedule is not None
                and configuration.get("scheduleTriggerConfig") != expected_schedule
            )
            or len(job_containers) != 1
            or job_containers[0].get("name") != expected_name
            or job_containers[0].get("image") != image
            or job_containers[0].get("command") != ["python"]
            or job_containers[0].get("args") != expected_args
        ):
            raise Phase1FenceFailed("phase1_job_not_fenced")
        executions = _read(
            (
                "containerapp",
                "job",
                "execution",
                "list",
                *common,
                "--name",
                job_name,
            ),
            runner=runner,
        )
        if not isinstance(executions, list) or any(not isinstance(row, dict) for row in executions):
            raise Phase1FenceFailed("phase1_job_execution_active")
        statuses = [row.get("properties", {}).get("status") for row in executions]
        if any(status in ACTIVE_EXECUTION_STATES or status not in TERMINAL_EXECUTION_STATES for status in statuses):
            raise Phase1FenceFailed("phase1_job_execution_active")
        if mode in {"activate", "phase2"}:
            qualified = []
            for execution in executions:
                properties = execution.get("properties", {})
                started = properties.get("startTime")
                try:
                    started_at = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
                except ValueError as error:
                    raise Phase1FenceFailed("phase1_job_execution_invalid") from error
                if started_at >= not_before.astimezone(UTC):
                    qualified.append(properties)
            if mode == "activate":
                if index < 2 and (
                    len(qualified) != 1
                    or qualified[0].get("status") != "Succeeded"
                ):
                    raise Phase1FenceFailed("phase1_job_execution_not_proved")
                if index >= 2 and qualified:
                    raise Phase1FenceFailed("phase1_maintenance_execution_detected")
            elif not qualified or any(
                execution.get("status") != "Succeeded" for execution in qualified
            ):
                raise Phase1FenceFailed("phase2_job_execution_not_proved")


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--prepare-job", required=True)
    parser.add_argument("--seed-job", required=True)
    parser.add_argument("--session-job", required=True)
    parser.add_argument("--storage-job", required=True)
    parser.add_argument("--storage-account", required=True)
    parser.add_argument("--blob-container", required=True)
    parser.add_argument(
        "--mode",
        choices=("activate", "initial", "phase2"),
        default="initial",
    )
    parser.add_argument("--not-before")
    parser.add_argument("--expected-revision")
    parser.add_argument("--synthetic-manifest-sha256", required=True)
    parser.add_argument("--synthetic-dataset-version-id", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--ai-enabled", choices=("true", "false"), required=True)
    parser.add_argument("--ai-daily-attempt-limit", type=int, required=True)
    parser.add_argument("--ai-monthly-token-limit", type=int, required=True)
    parser.add_argument("--ai-max-concurrent-turns", type=int, required=True)
    parser.add_argument(
        "--ai-session-attempt-limit-per-minute", type=int, required=True
    )
    parser.add_argument(
        "--ai-global-attempt-limit-per-minute", type=int, required=True
    )
    parser.add_argument("--demo-session-rate-limit-per-hour", type=int, required=True)
    options = parser.parse_args(arguments)
    try:
        not_before = (
            datetime.fromisoformat(options.not_before.replace("Z", "+00:00"))
            if options.not_before is not None
            else None
        )
        verify_phase1_fence(
            subscription_id=options.subscription,
            resource_group=options.resource_group,
            app_name=options.app,
            image=options.image,
            job_names=(
                options.prepare_job,
                options.seed_job,
                options.session_job,
                options.storage_job,
            ),
            storage_account_name=options.storage_account,
            blob_container_name=options.blob_container,
            mode=options.mode,
            expected_revision_name=options.expected_revision,
            not_before=not_before,
            synthetic_manifest_sha256=options.synthetic_manifest_sha256,
            synthetic_dataset_version_id=options.synthetic_dataset_version_id,
            environment_name=options.environment,
            ai_enabled=options.ai_enabled == "true",
            ai_daily_attempt_limit=options.ai_daily_attempt_limit,
            ai_monthly_token_limit=options.ai_monthly_token_limit,
            ai_max_concurrent_turns=options.ai_max_concurrent_turns,
            ai_session_attempt_limit_per_minute=(
                options.ai_session_attempt_limit_per_minute
            ),
            ai_global_attempt_limit_per_minute=(
                options.ai_global_attempt_limit_per_minute
            ),
            demo_session_rate_limit_per_hour=(
                options.demo_session_rate_limit_per_hour
            ),
        )
    except (Phase1FenceFailed, ValueError):
        print("phase1_fence=failed")
        return 1
    print("phase1_fence=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
