from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _subject():
    try:
        return importlib.import_module("scripts.verify_partial_release_state")
    except ModuleNotFoundError:
        pytest.fail("partial release state verifier is not implemented")


def _incident() -> dict[str, Any]:
    return {
        "schema_version": "newcaostone.partial-release-incident.v2",
        "observed_at": "2026-08-16T20:36:02Z",
        "source_package": {
            "authorization_id": "22222222-2222-4222-8222-222222222222",
            "sha256": "a" * 64,
        },
        "target": {
            "subscription_id": "11111111-1111-4111-8111-111111111111",
            "tenant_id": "44444444-4444-4444-8444-444444444444",
            "region": "centralus",
            "resource_group": "rg-synthetic-demo-approved",
            "public_url": "https://bp-approved-app.synthetic.azurecontainerapps.io",
            "name_prefix": "bp-approved",
            "registry_name": "bpapprovedregistry",
            "image_repository": "bizpulse",
            "storage_account": "bpapprovedstorage",
            "postgres_server": "bp-approved-pg",
            "postgres_administrator_login": "bpoperator",
            "application": "bp-approved-app",
            "application_revision": "bp-approved-app--oldrevision1",
            "prepare_job": "bp-approved-prepare",
            "seed_job": "bp-approved-seed",
        },
        "release": {
            "candidate_git_sha": "b" * 40,
            "attestation_git_sha": "c" * 40,
            "attestation_path": "release/attestations/" + "b" * 40 + ".json",
            "candidate_image_digest": "sha256:" + "d" * 64,
            "candidate_image_input_sha256": "e" * 64,
            "migration_head": "0014_import_base_lineage",
            "synthetic_manifest_sha256": "f" * 64,
            "synthetic_dataset_version_id": (
                "33333333-3333-4333-8333-333333333333"
            ),
            "rollback_git_sha": "1" * 40,
            "rollback_image_digest": "sha256:" + "2" * 64,
            "rollback_image_input_sha256": "3" * 64,
        },
        "prepare": {
            "execution": "bp-approved-prepare-abc123",
            "started_at": "2026-08-16T20:25:35Z",
            "ended_at": "2026-08-16T20:26:09Z",
            "status": "Succeeded",
            "arguments": ["scripts/prepare_cloud.py"],
        },
        "seed": {
            "execution": "bp-approved-seed-def456",
            "started_at": "2026-08-16T20:26:17Z",
            "status": "Failed",
            "error": "seed_authority_mismatch",
            "previous_manifest_sha256": "4" * 64,
            "previous_dataset_version_id": (
                "55555555-5555-4555-8555-555555555555"
            ),
        },
        "boundaries": {
            "application_deployed": False,
            "traffic_switched": False,
            "ai_enabled": False,
            "openai_key_accessed": False,
            "paid_ai_called": False,
            "candidate_seed_writes": False,
        },
        "recovery_attempts": [],
    }


def _reader(incident: dict[str, Any], *, rebound: bool):
    target = incident["target"]
    release = incident["release"]
    candidate_image = (
        f"{target['registry_name']}.azurecr.io/{target['image_repository']}@"
        f"{release['candidate_image_digest']}"
    )
    rollback_image = (
        f"{target['registry_name']}.azurecr.io/{target['image_repository']}@"
        f"{release['rollback_image_digest']}"
    )
    seed = incident["seed"]
    seed_manifest = (
        release["synthetic_manifest_sha256"]
        if rebound
        else seed["previous_manifest_sha256"]
    )
    seed_version = (
        release["synthetic_dataset_version_id"]
        if rebound
        else seed["previous_dataset_version_id"]
    )
    responses = {
        ("containerapp", "show", target["application"]): {
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
        ("job", "show", target["prepare_job"]): {
            "properties": {
                "template": {
                    "containers": [
                        {
                            "name": "prepare",
                            "image": candidate_image,
                            "command": ["python"],
                            "args": incident["prepare"]["arguments"],
                        }
                    ]
                }
            }
        },
        ("job", "show", target["seed_job"]): {
            "properties": {
                "template": {
                    "containers": [
                        {
                            "name": "seed",
                            "image": candidate_image,
                            "command": ["python"],
                            "args": [
                                "scripts/seed_demo.py",
                                "tests/fixtures/synthetic/v1",
                                "--expected-manifest-sha256",
                                seed_manifest,
                                "--expected-dataset-version-id",
                                seed_version,
                            ],
                        }
                    ]
                }
            }
        },
        ("job", "execution", target["prepare_job"]): [
            {
                "name": incident["prepare"]["execution"],
                "properties": {"status": "Succeeded"},
            }
        ],
        ("job", "execution", target["seed_job"]): [
            {
                "name": incident["seed"]["execution"],
                "properties": {"status": "Failed"},
            }
        ],
    }
    calls: list[tuple[str, str, str]] = []

    def reader(command: tuple[str, ...]) -> object:
        if command[1:3] == ("containerapp", "show"):
            key = ("containerapp", "show", command[command.index("--name") + 1])
        elif command[1:4] == ("containerapp", "job", "show"):
            key = ("job", "show", command[command.index("--name") + 1])
        else:
            key = ("job", "execution", command[command.index("--name") + 1])
        calls.append(key)
        return responses[key]

    return reader, calls, responses


@pytest.mark.parametrize("mode,rebound", (("failed", False), ("rebound", True)))
def test_partial_state_verifier_accepts_exact_failed_and_rebound_modes(
    mode: str,
    rebound: bool,
) -> None:
    subject = _subject()
    incident = _incident()
    reader, calls, _ = _reader(incident, rebound=rebound)

    result = subject.verify_partial_release_state(
        incident,
        mode=mode,
        reader=reader,
    )

    assert result == {"mode": mode, "state": "verified"}
    assert len(calls) == 5


def test_partial_state_verifier_rejects_job_argument_drift() -> None:
    subject = _subject()
    incident = _incident()
    reader, _, responses = _reader(incident, rebound=False)
    responses[("job", "show", incident["target"]["seed_job"])]["properties"][
        "template"
    ]["containers"][0]["args"][-1] = "66666666-6666-4666-8666-666666666666"

    with pytest.raises(
        subject.PartialReleaseStateInvalid,
        match="partial_release_seed_job_invalid",
    ):
        subject.verify_partial_release_state(
            incident,
            mode="failed",
            reader=reader,
        )


def test_checked_in_partial_release_incident_is_valid() -> None:
    subject = _subject()

    incident = subject.load_partial_release_incident(
        PROJECT_ROOT
        / "release/incidents/2026-08-16-two-stage-partial-failure.json"
    )

    assert incident["release"]["candidate_git_sha"] == (
        "82fd4a4dcfbc04a6cbe6386ce8891b750a1ea7e3"
    )
    assert incident["boundaries"]["application_deployed"] is False
    assert incident["boundaries"]["openai_key_accessed"] is False
