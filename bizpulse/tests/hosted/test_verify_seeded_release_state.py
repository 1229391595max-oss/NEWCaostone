from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _subject():
    try:
        return importlib.import_module("scripts.verify_seeded_release_state")
    except ModuleNotFoundError:
        pytest.fail("seeded release state verifier is not implemented")


def test_direct_entrypoint_help_works_without_pythonpath() -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            str(PROJECT_ROOT / ".venv/bin/python"),
            "scripts/verify_seeded_release_state.py",
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


def seeded_continuation() -> dict[str, Any]:
    return {
        "schema_version": "newcaostone.seeded-release-continuation.v1",
        "recorded_at": "2026-08-16T21:22:46Z",
        "source_incident": {
            "reference": "release/incidents/2026-08-16-two-stage-partial-failure.json",
            "sha256": "a" * 64,
        },
        "source_recovery": {
            "authorization_id": "77777777-7777-4777-8777-777777777777",
            "package_sha256": "b" * 64,
            "completed_stages": [
                "incident_preflight",
                "registry_verify",
                "bind_seed",
                "rebound_preflight",
                "seed",
            ],
            "failed_stage": "deploy",
            "failure_code": "deployment_environment_missing",
            "azure_request_dispatched": False,
        },
        "target": {
            "subscription_id": "11111111-1111-4111-8111-111111111111",
            "tenant_id": "44444444-4444-4444-8444-444444444444",
            "region": "centralus",
            "resource_group": "rg-synthetic-demo-approved",
            "public_url": "https://bp-approved-app.synthetic.azurecontainerapps.io",
            "name_prefix": "bp-approved",
            "application": "bp-approved-app",
            "application_revision": "bp-approved-app--oldrevision1",
            "prepare_job": "bp-approved-prepare",
            "seed_job": "bp-approved-seed",
            "registry_name": "bpapprovedregistry",
            "image_repository": "bizpulse",
            "storage_account": "bpapprovedstorage",
            "postgres_server": "bp-approved-pg",
            "postgres_administrator_login": "bpoperator",
        },
        "release": {
            "candidate_git_sha": "c" * 40,
            "candidate_image_digest": "sha256:" + "d" * 64,
            "rollback_git_sha": "e" * 40,
            "rollback_image_digest": "sha256:" + "f" * 64,
            "migration_head": "0014_import_base_lineage",
            "synthetic_manifest_sha256": "1" * 64,
            "synthetic_dataset_version_id": (
                "33333333-3333-4333-8333-333333333333"
            ),
        },
        "prepare_execution": {
            "name": "bp-approved-prepare-abc123",
            "status": "Succeeded",
            "arguments": ["scripts/prepare_cloud.py"],
        },
        "seed_execution": {
            "name": "bp-approved-seed-vhamoeo",
            "status": "Succeeded",
            "arguments": [
                "scripts/seed_demo.py",
                "tests/fixtures/synthetic/v1",
                "--expected-manifest-sha256",
                "1" * 64,
                "--expected-dataset-version-id",
                "33333333-3333-4333-8333-333333333333",
            ],
        },
        "boundaries": {
            "application_deployed": False,
            "traffic_switched": False,
            "ai_enabled": False,
            "openai_key_accessed": False,
            "paid_ai_called": False,
        },
    }


def seeded_reader(continuation: dict[str, Any]):
    target = continuation["target"]
    release = continuation["release"]
    candidate_image = (
        f"{target['registry_name']}.azurecr.io/{target['image_repository']}@"
        f"{release['candidate_image_digest']}"
    )
    rollback_image = (
        f"{target['registry_name']}.azurecr.io/{target['image_repository']}@"
        f"{release['rollback_image_digest']}"
    )
    responses = {
        ("app", target["application"]): {
            "properties": {
                "provisioningState": "Succeeded",
                "latestRevisionName": target["application_revision"],
                "latestReadyRevisionName": target["application_revision"],
                "configuration": {
                    "ingress": {"traffic": [{"latestRevision": True, "weight": 100}]}
                },
                "template": {"containers": [{"image": rollback_image}]},
            }
        },
        ("job", target["prepare_job"]): {
            "properties": {
                "template": {
                    "containers": [
                        {
                            "name": "prepare",
                            "image": candidate_image,
                            "command": ["python"],
                            "args": continuation["prepare_execution"]["arguments"],
                        }
                    ]
                }
            }
        },
        ("job", target["seed_job"]): {
            "properties": {
                "template": {
                    "containers": [
                        {
                            "name": "seed",
                            "image": candidate_image,
                            "command": ["python"],
                            "args": continuation["seed_execution"]["arguments"],
                        }
                    ]
                }
            }
        },
        ("execution", target["prepare_job"]): [
            {
                "name": continuation["prepare_execution"]["name"],
                "properties": {"status": "Succeeded"},
            }
        ],
        ("execution", target["seed_job"]): [
            {
                "name": continuation["seed_execution"]["name"],
                "properties": {"status": "Succeeded"},
            }
        ],
    }
    calls: list[tuple[str, str]] = []

    def reader(command: tuple[str, ...]) -> object:
        name = command[command.index("--name") + 1]
        if command[1:3] == ("containerapp", "show"):
            key = ("app", name)
        elif command[1:4] == ("containerapp", "job", "show"):
            key = ("job", name)
        else:
            key = ("execution", name)
        calls.append(key)
        return responses[key]

    return reader, calls, responses


def test_seeded_state_verifier_accepts_exact_seeded_state() -> None:
    subject = _subject()
    continuation = seeded_continuation()
    reader, calls, _ = seeded_reader(continuation)

    result = subject.verify_seeded_release_state(continuation, reader=reader)

    assert result == {"state": "seeded_awaiting_application_deploy"}
    assert len(calls) == 5


def test_seeded_state_verifier_rejects_missing_successful_seed_execution() -> None:
    subject = _subject()
    continuation = seeded_continuation()
    reader, _, responses = seeded_reader(continuation)
    responses[("execution", continuation["target"]["seed_job"])][0][
        "properties"
    ]["status"] = "Failed"

    with pytest.raises(
        subject.SeededReleaseStateInvalid,
        match="seeded_release_seed_execution_invalid",
    ):
        subject.verify_seeded_release_state(continuation, reader=reader)


def test_seeded_continuation_rejects_openai_or_application_boundary_drift() -> None:
    subject = _subject()
    continuation = seeded_continuation()
    continuation["boundaries"]["openai_key_accessed"] = True

    with pytest.raises(
        subject.SeededReleaseStateInvalid,
        match="seeded_release_continuation_invalid",
    ):
        subject.validate_seeded_release_continuation(continuation)


def test_checked_in_seeded_continuation_is_valid() -> None:
    subject = _subject()

    continuation = subject.load_seeded_release_continuation(
        PROJECT_ROOT
        / "release/incidents/2026-08-16-recovery-v2-seeded-continuation.json"
    )

    assert continuation["source_recovery"]["package_sha256"] == (
        "91e210d5c41c430eec8685e39ae10377bdf293e96a5a77662f2e77a51b764f6a"
    )
    assert continuation["seed_execution"]["name"] == (
        "newcaostone-demo-seed-vhamoeo"
    )
