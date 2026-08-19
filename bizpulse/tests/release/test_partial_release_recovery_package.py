from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import shlex
import stat

import pytest

from tests.hosted.verify_azure_demo import (
    _expected_commands,
    _expected_execution_order,
)
from tests.release.test_two_stage_release_package import _data_authority


NOW = "2026-08-16T21:00:00Z"
EXPIRES = "2026-08-17T21:00:00Z"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _subject():
    try:
        return importlib.import_module(
            "scripts.create_partial_release_recovery_package"
        )
    except ModuleNotFoundError:
        pytest.fail("partial release recovery package builder is not implemented")


def _authority() -> dict[str, object]:
    authority = _data_authority()
    authority["issued_at"] = NOW
    authority["expires_at"] = EXPIRES
    authority["public_url"] = (
        "https://bp-approved-app.synthetic.azurecontainerapps.io"
    )
    authority["public_url_source"] = "exact"
    authority["recovery"].update(
        target_mode="update",
        observed_current_image_digest=authority["release"][
            "rollback_image_digest"
        ],
    )
    authority["external_publication"]["registry_publish"] = False
    authority["allowed_operations"].remove("registry_publish")
    authority["commands"] = {
        stage: [shlex.join(tokens) for tokens in commands]
        for stage, commands in _expected_commands(authority).items()
    }
    authority["execution_order"] = list(_expected_execution_order(authority))
    return authority


def _incident(authority: dict[str, object]) -> dict[str, object]:
    release = authority["release"]
    generated = authority["generated_names"]
    return {
        "schema_version": "newcaostone.partial-release-incident.v2",
        "observed_at": "2026-08-16T20:36:02Z",
        "source_package": {
            "authorization_id": "22222222-2222-4222-8222-222222222222",
            "sha256": "a" * 64,
        },
        "target": {
            "subscription_id": authority["subscription_id"],
            "tenant_id": "44444444-4444-4444-8444-444444444444",
            "region": authority["region"],
            "resource_group": authority["resource_group"],
            "public_url": authority["public_url"],
            "name_prefix": generated["name_prefix"],
            "registry_name": generated["registry_name"],
            "image_repository": generated["image_repository"],
            "storage_account": generated["storage_account"],
            "postgres_server": generated["postgres_server"],
            "postgres_administrator_login": generated[
                "postgres_administrator_login"
            ],
            "application": generated["container_app"],
            "application_revision": "bp-approved-app--oldrevision1",
            "prepare_job": generated["migration_job"],
            "seed_job": generated["seed_job"],
        },
        "release": {
            "candidate_git_sha": release["git_sha"],
            "attestation_git_sha": release["attestation_git_sha"],
            "attestation_path": (
                "release/attestations/" + release["git_sha"] + ".json"
            ),
            "candidate_image_digest": release["image_digest"],
            "candidate_image_input_sha256": release["image_input_sha256"],
            "migration_head": release["migration_head"],
            "synthetic_manifest_sha256": release[
                "synthetic_manifest_sha256"
            ],
            "synthetic_dataset_version_id": release[
                "synthetic_dataset_version_id"
            ],
            "rollback_git_sha": release["rollback_git_sha"],
            "rollback_image_digest": release["rollback_image_digest"],
            "rollback_image_input_sha256": release[
                "rollback_image_input_sha256"
            ],
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


def _write_incident(tmp_path: Path, incident: dict[str, object]) -> tuple[Path, str]:
    path = tmp_path / "incident.json"
    path.write_text(json.dumps(incident, indent=2, sort_keys=True) + "\n")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_recovery_package_skips_completed_and_unauthorized_stages(
    tmp_path: Path,
) -> None:
    subject = _subject()
    authority = _authority()
    incident = _incident(authority)
    incident_path, incident_sha256 = _write_incident(tmp_path, incident)

    package = subject.build_partial_release_recovery_package(
        authority=authority,
        incident=incident,
        incident_reference="incident.json",
        incident_sha256=incident_sha256,
        authorization_id="77777777-7777-4777-8777-777777777777",
        issued_at=NOW,
        expires_at=EXPIRES,
    )

    assert package["execution_order"] == [
        "incident_preflight",
        "registry_verify",
        "bind_seed",
        "rebound_preflight",
        "seed",
        "deploy",
        "health",
        "browser_acceptance",
        "capacity",
        "expiry",
        "restart_readback",
        "rollback",
    ]
    assert set(package["commands"]) == set(package["execution_order"])
    assert package["control_sha256"] == {
        path: hashlib.sha256((PROJECT_ROOT / path).read_bytes()).hexdigest()
        for path in (
            "scripts/create_partial_release_recovery_package.py",
            "scripts/update_azure_job_binding.py",
            "scripts/verify_partial_release_state.py",
        )
    }
    assert "--mode failed" in package["commands"]["incident_preflight"][0]
    assert "--mode rebound" in package["commands"]["rebound_preflight"][0]
    assert len(package["commands"]["bind_seed"]) == 1
    serialized_commands = json.dumps(package["commands"], sort_keys=True)
    for forbidden in (
        "registry_publish",
        "publish_registry_image.py",
        '"migrate"',
        "run_azure_job.py --subscription "
        + authority["subscription_id"]
        + " --resource-group "
        + authority["resource_group"]
        + " --job "
        + authority["generated_names"]["migration_job"],
        "qualify_openai_model.py",
        "openai-api-key",
        "aiChatEnabled=true",
    ):
        assert forbidden not in serialized_commands

    output = tmp_path / "RECOVERY.md"
    subject.write_partial_release_recovery_package(output, package)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert subject.load_partial_release_recovery_package(
        output,
        incident_path=incident_path,
        now=NOW,
    ) == package


def test_recovery_package_rejects_incident_release_drift(tmp_path: Path) -> None:
    subject = _subject()
    authority = _authority()
    incident = _incident(authority)
    incident["release"]["candidate_image_digest"] = "sha256:" + "9" * 64
    _, incident_sha256 = _write_incident(tmp_path, incident)

    with pytest.raises(
        subject.PartialReleaseRecoveryInvalid,
        match="partial_recovery_release_mismatch",
    ):
        subject.build_partial_release_recovery_package(
            authority=authority,
            incident=incident,
            incident_reference="incident.json",
            incident_sha256=incident_sha256,
            authorization_id="77777777-7777-4777-8777-777777777777",
            issued_at=NOW,
            expires_at=EXPIRES,
        )
