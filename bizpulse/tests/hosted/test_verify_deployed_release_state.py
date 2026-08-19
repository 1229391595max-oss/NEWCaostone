from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_EXECUTIONS = {
    "prepare": {
        "job": "newcaostone-demo-prepare",
        "name": "newcaostone-demo-prepare-pc747ae",
        "status": "Succeeded",
    },
    "seed": {
        "job": "newcaostone-demo-seed",
        "name": "newcaostone-demo-seed-vhamoeo",
        "status": "Succeeded",
    },
    "session_maintenance": {
        "job": "newcaostone-demo-sessions",
        "name": "newcaostone-demo-sessions-8yiqp1m",
        "status": "Succeeded",
    },
    "storage_maintenance": {
        "job": "newcaostone-demo-storage",
        "name": "newcaostone-demo-storage-bch1i2u",
        "status": "Succeeded",
    },
}
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
        "httpGet": {
            "path": "/health/ready",
            "port": 8000,
            "scheme": "HTTP",
        },
        "initialDelaySeconds": 10,
        "periodSeconds": 10,
        "timeoutSeconds": 5,
        "failureThreshold": 3,
    },
]


def _subject():
    try:
        return importlib.import_module("scripts.verify_deployed_release_state")
    except ModuleNotFoundError:
        pytest.fail("deployed release state verifier is not implemented")


def deployed_continuation() -> dict[str, Any]:
    return {
        "schema_version": "newcaostone.deployed-release-continuation.v1",
        "recorded_at": "2026-08-16T22:18:28Z",
        "source_recovery": {
            "authorization_id": "993b492e-aba0-40e8-87e5-65019caaa291",
            "package_sha256": (
                "978110287eb3335bcf5537ee59e9bd887a41eee9753861148680f1a5475beae8"
            ),
            "receipt_reference": ".tmp/RECOVERY_V4_EXECUTION_RECEIPT.json",
            "receipt_schema_version": (
                "newcaostone.seeded-release-execution-receipt.v1"
            ),
            "receipt_status": "failed",
            "completed_stages": ["seeded_preflight", "registry_verify"],
            "failed_stage": "deploy",
        },
        "source_seeded_continuation": {
            "reference": (
                "release/incidents/"
                "2026-08-16-recovery-v2-seeded-continuation.json"
            ),
            "sha256": (
                "dd5b39ee23d7e053f5454a4c8500cc748c74a3d6cec7717b9ae3a19e96e40cdc"
            ),
        },
        "target": {
            "subscription_id": "fc89e7d3-5428-425e-863f-415859810c2c",
            "tenant_id": "13d04c38-d91c-4f9f-8b65-6af2b515dd63",
            "region": "centralus",
            "resource_group": "rg-bizpulse-centralus",
            "public_url": (
                "https://newcaostone-demo-app."
                "delightfulstone-15318d59.centralus.azurecontainerapps.io"
            ),
            "name_prefix": "newcaostone-demo",
            "application": "newcaostone-demo-app",
            "application_revision": "newcaostone-demo-app--713a6984d4a0",
            "environment": "newcaostone-demo-env",
            "prepare_job": "newcaostone-demo-prepare",
            "seed_job": "newcaostone-demo-seed",
            "session_maintenance_job": "newcaostone-demo-sessions",
            "storage_maintenance_job": "newcaostone-demo-storage",
            "registry_name": "sellernorthbpacr",
            "image_repository": "bizpulse",
            "storage_account": "newcaostonedemost",
            "postgres_server": "newcaostone-demo-pg",
            "postgres_administrator_login": "bpoperator",
        },
        "release": {
            "candidate_git_sha": "82fd4a4dcfbc04a6cbe6386ce8891b750a1ea7e3",
            "candidate_image_digest": (
                "sha256:713a6984d4a034a0be73b46c10a897aeb236c201325ff8a88ba524fc6c10295c"
            ),
            "rollback_git_sha": "537effe3036f77f83225beef12589bd447205a8b",
            "rollback_image_digest": (
                "sha256:2a95c20046cde04a383a280b350a450c15cc7c46df92e1e8eaf5014eeb5c8512"
            ),
            "migration_head": "0014_import_base_lineage",
            "synthetic_manifest_sha256": (
                "5e0d761fddae1d7add1739ed5cff06eb1e1aad7c494152abd3334841bec61fde"
            ),
            "synthetic_dataset_version_id": (
                "b91e1179-c76a-53a5-b036-ce7b88b74cbe"
            ),
        },
        "executions": deepcopy(EXPECTED_EXECUTIONS),
        "completed_operations": [
            "registry_publish",
            "postgres_migrate",
            "seed_job_bind",
            "prepare",
            "synthetic_seed",
            "application_deploy",
            "session_maintenance",
            "storage_maintenance",
        ],
        "boundaries": {
            "application_deployed": True,
            "traffic_switched": True,
            "ai_enabled": False,
            "hosted_health_verified": False,
            "browser_verified": False,
            "capacity_verified": False,
            "expiry_verified": False,
            "restart_verified": False,
            "rollback_verified": False,
            "openai_key_accessed": False,
            "paid_ai_called": False,
        },
    }


def test_deployed_continuation_requires_exact_v4_evidence(
    tmp_path: Path,
) -> None:
    subject = _subject()
    payload = deployed_continuation()
    path = tmp_path / "continuation.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    loaded = subject.load_deployed_release_continuation(
        path, expected_sha256=digest
    )

    assert loaded["executions"] == EXPECTED_EXECUTIONS
    assert loaded["boundaries"]["application_deployed"] is True
    assert loaded["boundaries"]["hosted_health_verified"] is False


def test_deployed_continuation_rejects_duplicate_json_keys(
    tmp_path: Path,
) -> None:
    subject = _subject()
    payload = json.dumps(deployed_continuation(), sort_keys=True)
    duplicate = payload.replace(
        '"schema_version":',
        '"schema_version": "newcaostone.deployed-release-continuation.v1", '
        '"schema_version":',
        1,
    )
    path = tmp_path / "duplicate.json"
    path.write_text(duplicate)

    with pytest.raises(
        subject.DeployedReleaseStateInvalid,
        match="deployed_release_json_duplicate_key",
    ):
        subject.load_deployed_release_continuation(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authorization_id", "77777777-7777-4777-8777-777777777777"),
        ("package_sha256", "a" * 64),
        ("receipt_status", "succeeded"),
    ],
)
def test_deployed_continuation_rejects_v4_source_drift(
    field: str, value: str
) -> None:
    subject = _subject()
    payload = deployed_continuation()
    payload["source_recovery"][field] = value

    with pytest.raises(
        subject.DeployedReleaseStateInvalid,
        match="deployed_release_continuation_invalid",
    ):
        subject.validate_deployed_release_continuation(payload)


def test_deployed_continuation_rejects_changed_execution_identity() -> None:
    subject = _subject()
    payload = deployed_continuation()
    payload["executions"]["prepare"]["name"] = (
        "newcaostone-demo-prepare-later123"
    )

    with pytest.raises(
        subject.DeployedReleaseStateInvalid,
        match="deployed_release_continuation_invalid",
    ):
        subject.validate_deployed_release_continuation(payload)


def test_deployed_continuation_rejects_false_completed_boundary() -> None:
    subject = _subject()
    payload = deployed_continuation()
    payload["boundaries"]["application_deployed"] = False

    with pytest.raises(
        subject.DeployedReleaseStateInvalid,
        match="deployed_release_continuation_invalid",
    ):
        subject.validate_deployed_release_continuation(payload)


def test_deployed_continuation_rejects_secret_shaped_content() -> None:
    subject = _subject()
    payload = deployed_continuation()
    payload["target"]["public_url"] += "?api_key=not-a-real-secret"

    with pytest.raises(
        subject.DeployedReleaseStateInvalid,
        match="deployed_release_secret_forbidden",
    ):
        subject.validate_deployed_release_continuation(payload)


def test_deployed_continuation_rejects_wrong_sha256(tmp_path: Path) -> None:
    subject = _subject()
    path = tmp_path / "continuation.json"
    path.write_text(json.dumps(deployed_continuation(), sort_keys=True))

    with pytest.raises(
        subject.DeployedReleaseStateInvalid,
        match="deployed_release_continuation_hash_mismatch",
    ):
        subject.load_deployed_release_continuation(
            path, expected_sha256="0" * 64
        )


def test_checked_in_deployed_continuation_is_valid() -> None:
    subject = _subject()

    loaded = subject.load_deployed_release_continuation(
        PROJECT_ROOT
        / "release/incidents/"
        "2026-08-16-recovery-v4-deployed-continuation.json"
    )

    assert loaded == deployed_continuation()


class DeployedReader:
    def __init__(self, continuation: dict[str, Any]) -> None:
        target = continuation["target"]
        release = continuation["release"]
        image = (
            f"{target['registry_name']}.azurecr.io/"
            f"{target['image_repository']}@{release['candidate_image_digest']}"
        )
        public_host = target["public_url"].removeprefix("https://")
        environment_id = (
            f"/subscriptions/{target['subscription_id']}/resourceGroups/"
            f"{target['resource_group']}/providers/Microsoft.App/"
            f"managedEnvironments/{target['environment']}"
        )
        secret_rows = [
            {"name": "database-url"},
            {"name": "blob-connection-string"},
            {"name": "operator-password-hash"},
            {"name": "session-pepper"},
        ]
        job_env = [
            {"name": "BIZPULSE_RUNTIME_ENVIRONMENT", "value": "cloud"},
            {
                "name": "BIZPULSE_DATABASE_URL",
                "secretRef": "database-url",
            },
            {
                "name": "BIZPULSE_BLOB_ENDPOINT",
                "value": "https://newcaostonedemost.blob.core.windows.net/",
            },
            {
                "name": "BIZPULSE_BLOB_CONTAINER",
                "value": "synthetic-demo",
            },
            {
                "name": "BIZPULSE_BLOB_CONNECTION_STRING",
                "secretRef": "blob-connection-string",
            },
            {
                "name": "BIZPULSE_SESSION_PEPPER",
                "secretRef": "session-pepper",
            },
        ]
        app_env = [
            *deepcopy(job_env),
            {
                "name": "BIZPULSE_OPERATOR_PASSWORD_HASH",
                "secretRef": "operator-password-hash",
            },
            {"name": "BIZPULSE_ALLOWED_ORIGIN", "value": target["public_url"]},
            {"name": "BIZPULSE_AI_CHAT_ENABLED", "value": "false"},
            {"name": "BIZPULSE_AI_DAILY_ATTEMPT_LIMIT", "value": "120"},
            {
                "name": "BIZPULSE_AI_MONTHLY_TOKEN_LIMIT",
                "value": "150000",
            },
            {"name": "BIZPULSE_AI_MAX_CONCURRENT_TURNS", "value": "15"},
            {
                "name": "BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE",
                "value": "3",
            },
            {
                "name": "BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE",
                "value": "20",
            },
            {
                "name": "BIZPULSE_DEMO_SESSION_RATE_LIMIT_PER_HOUR",
                "value": "50",
            },
            {
                "name": "BIZPULSE_OPENAI_MODEL",
                "value": "gpt-5.4-nano-2026-03-17",
            },
            {"name": "BIZPULSE_OPENAI_REASONING_EFFORT", "value": "low"},
            {
                "name": "APPLICATIONINSIGHTS_CONNECTION_STRING",
                "value": (
                    "InstrumentationKey=00000000-0000-4000-8000-000000000000;"
                    "IngestionEndpoint=https://centralus-0.in.applicationinsights.azure.com/"
                ),
            },
        ]
        self.responses: dict[tuple[str, str], Any] = {
            ("app", target["application"]): {
                "name": target["application"],
                "properties": {
                    "provisioningState": "Succeeded",
                    "latestRevisionName": target["application_revision"],
                    "latestReadyRevisionName": target["application_revision"],
                    "environmentId": environment_id,
                    "configuration": {
                        "activeRevisionsMode": "Single",
                        "ingress": {
                            "external": True,
                            "fqdn": public_host,
                            "traffic": [
                                {"latestRevision": True, "weight": 100}
                            ],
                        },
                        "secrets": deepcopy(secret_rows),
                    },
                    "template": {
                        "scale": {"minReplicas": 1, "maxReplicas": 1},
                        "containers": [
                            {
                                "name": "bizpulse",
                                "image": image,
                                "env": app_env,
                                "probes": deepcopy(EXPECTED_APP_PROBES),
                            }
                        ],
                    },
                },
            },
            ("revisions", target["application"]): [
                {
                    "name": target["application_revision"],
                    "properties": {"active": True, "replicas": 1},
                }
            ],
        }
        specs = {
            "prepare": {
                "container_name": "prepare",
                "arguments": ["scripts/prepare_cloud.py"],
                "trigger": "Manual",
                "timeout": 900,
            },
            "seed": {
                "container_name": "seed",
                "arguments": [
                    "scripts/seed_demo.py",
                    "tests/fixtures/synthetic/v1",
                    "--expected-manifest-sha256",
                    release["synthetic_manifest_sha256"],
                    "--expected-dataset-version-id",
                    release["synthetic_dataset_version_id"],
                ],
                "trigger": "Manual",
                "timeout": 1800,
            },
            "session_maintenance": {
                "container_name": "maintain-sessions",
                "arguments": ["scripts/maintain_sessions.py"],
                "trigger": "Schedule",
                "timeout": 300,
                "cron": "*/15 * * * *",
            },
            "storage_maintenance": {
                "container_name": "maintain-storage",
                "arguments": [
                    "scripts/maintain_storage.py",
                    "--expire-temporary",
                ],
                "trigger": "Schedule",
                "timeout": 600,
                "cron": "0 * * * *",
            },
        }
        for role, spec in specs.items():
            execution = continuation["executions"][role]
            configuration: dict[str, Any] = {
                "triggerType": spec["trigger"],
                "replicaTimeout": spec["timeout"],
                "replicaRetryLimit": 0,
                "secrets": deepcopy(secret_rows),
            }
            if spec["trigger"] == "Manual":
                configuration["manualTriggerConfig"] = {
                    "parallelism": 1,
                    "replicaCompletionCount": 1,
                }
            else:
                configuration["scheduleTriggerConfig"] = {
                    "cronExpression": spec["cron"],
                    "parallelism": 1,
                    "replicaCompletionCount": 1,
                }
            self.responses[("job", role)] = {
                "name": execution["job"],
                "properties": {
                    "environmentId": environment_id,
                    "configuration": configuration,
                    "template": {
                        "containers": [
                            {
                                "name": spec["container_name"],
                                "image": image,
                                "command": ["python"],
                                "args": spec["arguments"],
                                "env": deepcopy(job_env),
                            }
                        ]
                    },
                },
            }
            self.responses[("executions", role)] = [
                {
                    "name": execution["name"],
                    "properties": {"status": "Succeeded"},
                }
            ]
        self.calls: list[tuple[str, str]] = []

    def __call__(self, command: tuple[str, ...]) -> Any:
        name = command[command.index("--name") + 1]
        if command[1:3] == ("containerapp", "show"):
            key = ("app", name)
        elif command[1:4] == ("containerapp", "revision", "list"):
            key = ("revisions", name)
        elif command[1:4] == ("containerapp", "job", "show"):
            key = (
                "job",
                next(
                    role
                    for role, execution in EXPECTED_EXECUTIONS.items()
                    if execution["job"] == name
                ),
            )
        else:
            key = (
                "executions",
                next(
                    role
                    for role, execution in EXPECTED_EXECUTIONS.items()
                    if execution["job"] == name
                ),
            )
        self.calls.append(key)
        return self.responses[key]


def deployed_reader(continuation: dict[str, Any]) -> DeployedReader:
    return DeployedReader(continuation)


def test_deployed_state_verifier_accepts_exact_bound_state() -> None:
    subject = _subject()
    continuation = deployed_continuation()
    reader = deployed_reader(continuation)

    result = subject.verify_deployed_release_state(continuation, reader=reader)

    assert result == {"state": "deployed_awaiting_hosted_acceptance"}
    assert len(reader.calls) == 10


def test_deployed_state_accepts_azure_owned_scale_defaults() -> None:
    subject = _subject()
    continuation = deployed_continuation()
    reader = deployed_reader(continuation)
    app = reader.responses[("app", continuation["target"]["application"])]
    app["properties"]["template"]["scale"].update(
        {
            "cooldownPeriod": 300,
            "pollingInterval": 30,
            "rules": None,
        }
    )

    result = subject.verify_deployed_release_state(
        continuation,
        reader=reader,
    )

    assert result == {"state": "deployed_awaiting_hosted_acceptance"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("minReplicas", 0),
        ("maxReplicas", 2),
        ("minReplicas", True),
        ("maxReplicas", "1"),
    ],
)
def test_deployed_state_rejects_replica_bound_drift(
    field: str,
    value: object,
) -> None:
    subject = _subject()
    continuation = deployed_continuation()
    reader = deployed_reader(continuation)
    app = reader.responses[("app", continuation["target"]["application"])]
    app["properties"]["template"]["scale"][field] = value

    with pytest.raises(
        subject.DeployedReleaseStateInvalid,
        match="deployed_release_application_invalid",
    ):
        subject.verify_deployed_release_state(continuation, reader=reader)


def test_deployed_state_rejects_missing_scale_mapping() -> None:
    subject = _subject()
    continuation = deployed_continuation()
    reader = deployed_reader(continuation)
    app = reader.responses[("app", continuation["target"]["application"])]
    del app["properties"]["template"]["scale"]

    with pytest.raises(
        subject.DeployedReleaseStateInvalid,
        match="deployed_release_application_invalid",
    ):
        subject.verify_deployed_release_state(continuation, reader=reader)


def test_exact_bound_executions_cannot_be_substituted() -> None:
    subject = _subject()
    continuation = deployed_continuation()
    reader = deployed_reader(continuation)
    reader.responses[("executions", "prepare")] = [
        {
            "name": "newcaostone-demo-prepare-later123",
            "properties": {"status": "Succeeded"},
        }
    ]

    with pytest.raises(
        subject.DeployedReleaseStateInvalid,
        match="deployed_release_bound_execution_invalid",
    ):
        subject.verify_deployed_release_state(continuation, reader=reader)


def test_later_failed_maintenance_execution_is_rejected() -> None:
    subject = _subject()
    continuation = deployed_continuation()
    reader = deployed_reader(continuation)
    reader.responses[("executions", "session_maintenance")].append(
        {
            "name": "newcaostone-demo-sessions-later1",
            "properties": {"status": "Failed"},
        }
    )

    with pytest.raises(
        subject.DeployedReleaseStateInvalid,
        match="deployed_release_additional_execution_invalid",
    ):
        subject.verify_deployed_release_state(continuation, reader=reader)


def test_later_running_maintenance_execution_is_allowed() -> None:
    subject = _subject()
    continuation = deployed_continuation()
    reader = deployed_reader(continuation)
    reader.responses[("executions", "storage_maintenance")].append(
        {
            "name": "newcaostone-demo-storage-later1",
            "properties": {"status": "Running"},
        }
    )

    result = subject.verify_deployed_release_state(continuation, reader=reader)

    assert result == {"state": "deployed_awaiting_hosted_acceptance"}


@pytest.mark.parametrize("drift", ["image", "revision", "traffic", "ai"])
def test_deployed_state_rejects_candidate_application_drift(
    drift: str,
) -> None:
    subject = _subject()
    continuation = deployed_continuation()
    reader = deployed_reader(continuation)
    app = reader.responses[("app", continuation["target"]["application"])]
    if drift == "image":
        app["properties"]["template"]["containers"][0]["image"] = (
            "sellernorthbpacr.azurecr.io/bizpulse@sha256:" + "0" * 64
        )
    elif drift == "revision":
        app["properties"]["latestReadyRevisionName"] = "changed"
    elif drift == "traffic":
        app["properties"]["configuration"]["ingress"]["traffic"][0][
            "weight"
        ] = 99
    else:
        env = app["properties"]["template"]["containers"][0]["env"]
        next(
            row for row in env if row["name"] == "BIZPULSE_AI_CHAT_ENABLED"
        )["value"] = "true"

    with pytest.raises(
        subject.DeployedReleaseStateInvalid,
        match="deployed_release_application_invalid",
    ):
        subject.verify_deployed_release_state(continuation, reader=reader)


@pytest.mark.parametrize("drift", ["command", "schedule"])
def test_deployed_state_rejects_job_binding_drift(drift: str) -> None:
    subject = _subject()
    continuation = deployed_continuation()
    reader = deployed_reader(continuation)
    job = reader.responses[("job", "session_maintenance")]
    if drift == "command":
        job["properties"]["template"]["containers"][0]["args"] = [
            "scripts/other.py"
        ]
    else:
        job["properties"]["configuration"]["scheduleTriggerConfig"][
            "cronExpression"
        ] = "* * * * *"

    with pytest.raises(
        subject.DeployedReleaseStateInvalid,
        match="deployed_release_job_invalid",
    ):
        subject.verify_deployed_release_state(continuation, reader=reader)


def test_direct_entrypoint_help_works_without_pythonpath() -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            str(PROJECT_ROOT / ".venv/bin/python"),
            "scripts/verify_deployed_release_state.py",
            "--help",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--continuation-sha256" in completed.stdout


def test_deployed_verifier_runtime_does_not_import_test_modules() -> None:
    source = (
        PROJECT_ROOT / "scripts/verify_deployed_release_state.py"
    ).read_text()

    assert "from tests." not in source
    assert "import tests." not in source
