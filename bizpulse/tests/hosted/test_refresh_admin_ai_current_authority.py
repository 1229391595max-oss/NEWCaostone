from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path

import pytest

from scripts.admin_ai_current_successor import (
    CURRENT_RECOVERY_REVISION,
    CurrentAdminAISuccessorInvalid,
    derive_current_admin_ai_successor,
)
from scripts.create_ai_enablement_package import (
    AZURE_TARGET,
    PRIOR_AI_ATTEMPTS,
    validate_ai_enablement_package,
)
from scripts.refresh_admin_ai_current_authority import (
    CurrentAuthorityRefreshInvalid,
    build_authority_observation,
    main,
    run_readonly_authority_refresh,
    validate_r19_deployment_provenance,
)
from scripts.release_authority import load_current_authority


NOW = datetime(2026, 8, 18, 20, 0, tzinfo=UTC)
SOURCE_SHA = "a" * 40
SOURCE_TREE = "b" * 40
R19_SOURCE_SHA = "962a4fa438045890f145f5ab728924da781e2332"
R19_SOURCE_TREE = "aee615fc2546894d910ce682b3a22d819cf8cbe5"
R19_IMAGE_INPUT = "0fd0eda5ebeb7d39c269ed9ea7bb86233c0b9e4ebfb6b9adca1d259f962eec00"


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    path.chmod(0o400)
    return path


def _r19_files(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    receipt_contract = {
        "schema_version": "newcaostone.ai-enablement-attempt.v2",
        "package_sha256": "pending",
        "state": "failed",
        "failure_code": "ai_enablement_emergency_disable_failed",
        "completed_states": [
            "readonly_revalidation",
            "publish_candidate_image",
            "activate_ai_disabled_candidate",
            "verify_ai_disabled_candidate",
            "reconcile_ai_vault_identity_role_diagnostics",
        ],
        "reconciliations": [
            {
                "acknowledgement": "accepted",
                "application_read_count": 5,
                "elapsed_milliseconds": 33073,
                "final_state": "healthy_target",
                "predecessor_revision": (
                    "newcaostone-demo-app--recover-b-22767486-20f39c8"
                ),
                "revision_read_count": 5,
                "role": "ai_disabled_candidate",
                "target_image_digest": AZURE_TARGET["rollback_image"].rsplit(
                    "@", 1
                )[-1],
                "target_revision": AZURE_TARGET["rollback_revision"],
            }
        ],
        "recovery": None,
    }
    package_payload = {
        "repository": {
            "branch": "codex/newcaostone-authoritative-v1",
            "clean": True,
            "head_sha": R19_SOURCE_SHA,
            "tree_sha": R19_SOURCE_TREE,
        },
        "candidate": {
            "candidate_image_digest": None,
            "image_input_sha256": R19_IMAGE_INPUT,
            "image_repository": "bizpulse",
            "source_tree_sha": R19_SOURCE_TREE,
        },
        "azure_target": {
            **AZURE_TARGET,
            "rollback_revision": receipt_contract["reconciliations"][0][
                "predecessor_revision"
            ],
            "rollback_image": (
                "sellernorthbpacr.azurecr.io/bizpulse@sha256:"
                "20f39c82b499c98ba10c68129531a46b4fb7fe3a6c4e91a87ddcdff99bfc18c1"
            ),
        },
        "prepackage_gate": {
            "rollback_registry_tag": "ai-790b71a7b95e-22767486"
        },
    }
    package = _write_json(tmp_path / "r19-package.json", package_payload)
    package_sha = hashlib.sha256(package.read_bytes()).hexdigest()
    receipt_contract["package_sha256"] = package_sha
    receipt = _write_json(tmp_path / "r19-receipt.json", receipt_contract)
    expected = {
        "package_sha256": package_sha,
        "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
        "receipt_contract": receipt_contract,
    }
    return package, receipt, expected


def _baseline(**overrides: object) -> dict[str, object]:
    return {
        "observed_at": "2026-08-18T20:00:00Z",
        "observation_sha256": "d" * 64,
        "required_azure_reads": 12,
        "health_state": "Healthy",
        "ready": True,
        "revision": CURRENT_RECOVERY_REVISION,
        "image_digest": AZURE_TARGET["rollback_image"].rsplit("@", 1)[-1],
        "traffic_weight": 100,
        "operator_ai_enabled": False,
        "demo_ai_enabled": False,
        "role_assignment_phase": "officer_only",
        "database_revision": "0014_import_base_lineage",
        **overrides,
    }


def _successor_provenance() -> tuple[dict[str, object], dict[str, object]]:
    attempt = PRIOR_AI_ATTEMPTS["r19"]
    return (
        {
            "candidate_git_sha": R19_SOURCE_SHA,
            "candidate_git_tree": R19_SOURCE_TREE,
            "candidate_image_input_sha256": R19_IMAGE_INPUT,
            "image_digest": AZURE_TARGET["rollback_image"].rsplit("@", 1)[-1],
            "revision": AZURE_TARGET["rollback_revision"],
            "registry_tag": "ai-962a4fa43804-9c35ae6a",
            "r19_package_sha256": attempt["package_sha256"],
            "r19_receipt_sha256": attempt["receipt_sha256"],
        },
        deepcopy(attempt["receipt_contract"]),
    )


def _successor_contract() -> tuple[dict[str, object], dict[str, str]]:
    provenance, receipt_contract = _successor_provenance()
    return (
        provenance,
        derive_current_admin_ai_successor(
            provenance,
            receipt_contract=receipt_contract,
        ),
    )


def test_r19_provenance_is_hash_bound_but_not_reused_as_a_request(
    tmp_path: Path,
) -> None:
    package, receipt, expected = _r19_files(tmp_path)

    provenance = validate_r19_deployment_provenance(
        package,
        receipt,
        expected=expected,
    )

    assert provenance == {
        "candidate_git_sha": R19_SOURCE_SHA,
        "candidate_git_tree": R19_SOURCE_TREE,
        "candidate_image_input_sha256": R19_IMAGE_INPUT,
        "image_digest": AZURE_TARGET["rollback_image"].rsplit("@", 1)[-1],
        "revision": AZURE_TARGET["rollback_revision"],
        "registry_tag": f"ai-962a4fa43804-{str(expected['package_sha256'])[:8]}",
        "r19_package_sha256": expected["package_sha256"],
        "r19_receipt_sha256": expected["receipt_sha256"],
    }

    package.chmod(0o600)
    package.write_bytes(package.read_bytes() + b"\n")
    with pytest.raises(
        CurrentAuthorityRefreshInvalid,
        match="authority_refresh_r19_provenance_invalid",
    ):
        validate_r19_deployment_provenance(package, receipt, expected=expected)


def test_r19_provenance_rejects_a_rehashed_stale_predecessor(
    tmp_path: Path,
) -> None:
    package, receipt, expected = _r19_files(tmp_path)
    package_payload = json.loads(package.read_text())
    package_payload["azure_target"]["rollback_image"] = (
        "sellernorthbpacr.azurecr.io/bizpulse@sha256:" + "c" * 64
    )
    package.chmod(0o600)
    _write_json(package, package_payload)
    expected["package_sha256"] = hashlib.sha256(package.read_bytes()).hexdigest()
    receipt_payload = json.loads(receipt.read_text())
    receipt_payload["package_sha256"] = expected["package_sha256"]
    receipt.chmod(0o600)
    _write_json(receipt, receipt_payload)
    expected["receipt_sha256"] = hashlib.sha256(receipt.read_bytes()).hexdigest()
    expected["receipt_contract"] = receipt_payload

    with pytest.raises(
        CurrentAuthorityRefreshInvalid,
        match="authority_refresh_r19_provenance_invalid",
    ):
        validate_r19_deployment_provenance(package, receipt, expected=expected)


def test_current_successor_is_derived_from_exact_failed_r19_provenance() -> None:
    provenance, receipt_contract = _successor_provenance()

    successor = derive_current_admin_ai_successor(
        provenance,
        receipt_contract=receipt_contract,
    )

    assert successor == {
        "historical_revision": AZURE_TARGET["rollback_revision"],
        "identity_state": "registry_only",
        "image": AZURE_TARGET["rollback_image"],
        "image_digest": AZURE_TARGET["rollback_image"].rsplit("@", 1)[-1],
        "registry_tag": "ai-962a4fa43804-9c35ae6a",
        "revision": "newcaostone-demo-app--recover-b-9c35ae6a-2bf7086",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("r19_package_sha256", "c" * 64),
        ("image_digest", "sha256:" + "d" * 64),
        ("revision", "newcaostone-demo-app--ai-off-arbitrary-2bf7086"),
    ),
)
def test_current_successor_rejects_changed_r19_provenance(
    field: str,
    value: object,
) -> None:
    provenance, receipt_contract = _successor_provenance()
    provenance[field] = value

    with pytest.raises(
        CurrentAdminAISuccessorInvalid,
        match="current_admin_ai_successor_invalid",
    ):
        derive_current_admin_ai_successor(
            provenance,
            receipt_contract=receipt_contract,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("failure_code", "ai_enablement_operation_failed"),
        ("completed_states", []),
        ("recovery", {"acknowledgement": "accepted"}),
    ),
)
def test_current_successor_rejects_changed_r19_failure_contract(
    field: str,
    value: object,
) -> None:
    provenance, contract = _successor_provenance()
    contract[field] = value

    with pytest.raises(
        CurrentAdminAISuccessorInvalid,
        match="current_admin_ai_successor_invalid",
    ):
        derive_current_admin_ai_successor(
            provenance,
            receipt_contract=contract,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        (
            "revision",
            "newcaostone-demo-app--ai-off-9c35ae6a-2bf7086",
        ),
        ("revision", "newcaostone-demo-app--recover-b-22767486-20f39c8"),
        ("revision", "newcaostone-demo-app--recover-b-arbitrary-2bf7086"),
        ("image_digest", "sha256:" + "e" * 64),
        ("traffic_weight", 99),
        ("role_assignment_phase", "legacy_only"),
        ("database_revision", "0015_admin_ai_control"),
        ("operator_ai_enabled", True),
        ("demo_ai_enabled", True),
        ("required_azure_reads", 11),
        ("ready", False),
    ),
)
def test_observation_rejects_any_nonexact_hosted_authority(
    field: str,
    value: object,
) -> None:
    provenance, successor = _successor_contract()

    with pytest.raises(
        CurrentAuthorityRefreshInvalid,
        match="authority_refresh_observation_invalid",
    ):
        build_authority_observation(
            source_sha=SOURCE_SHA,
            provenance=provenance,
            successor=successor,
            baseline=_baseline(**{field: value}),
            observed_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )


def test_observation_binds_fresh_evidence_and_exact_deployed_provenance() -> None:
    provenance, successor = _successor_contract()

    observation = build_authority_observation(
        source_sha=SOURCE_SHA,
        provenance=provenance,
        successor=successor,
        baseline=_baseline(),
        observed_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    assert observation == {
        "ai_runtime_state": "disabled",
        "attestation_git_sha": SOURCE_SHA,
        "candidate_git_sha": R19_SOURCE_SHA,
        "database_migration_head": "0014_import_base_lineage",
        "evidence_kind": "sanitized_azure_readback",
        "evidence_sha256": "d" * 64,
        "expires_at": "2026-08-18T21:00:00Z",
        "image_digest": AZURE_TARGET["rollback_image"].rsplit("@", 1)[-1],
        "observed_at": "2026-08-18T20:00:00Z",
        "revision": CURRENT_RECOVERY_REVISION,
    }


def test_observation_requires_exact_one_hour_freshness() -> None:
    provenance, successor = _successor_contract()

    with pytest.raises(
        CurrentAuthorityRefreshInvalid,
        match="authority_refresh_freshness_invalid",
    ):
        build_authority_observation(
            source_sha=SOURCE_SHA,
            provenance=deepcopy(provenance),
            successor=successor,
            baseline=_baseline(),
            observed_at=NOW,
            expires_at=NOW + timedelta(hours=2),
        )


def _current_authority_payload() -> dict[str, object]:
    return {
        "attested_rollback": {
            "candidate_attestation_path": "release/attestations/" + "1" * 40 + ".json",
            "git_sha": "1" * 40,
            "image_digest": "sha256:" + "2" * 64,
        },
        "development": {
            "ai_capability_state": "implemented",
            "repository_migration_head": "0017_ai_turn_credential_binding",
        },
        "freshness": {
            "evidence_kind": "sanitized_azure_readback",
            "evidence_sha256": "3" * 64,
            "expires_at": "2026-08-16T01:00:00Z",
            "observed_at": "2026-08-16T00:00:00Z",
        },
        "observed_deployment": {
            "ai_runtime_state": "disabled",
            "attestation_git_sha": "4" * 40,
            "candidate_git_sha": "5" * 40,
            "database_migration_head": "0014_import_base_lineage",
            "image_digest": "sha256:" + "6" * 64,
            "revision": "newcaostone-demo-app--old-12345678",
        },
        "prepared_candidate": {"state": "preserve-me"},
        "schema_version": "bizpulse.current-authority.v1",
    }


def test_readonly_refresh_builds_a_fresh_request_then_updates_once(
    tmp_path: Path,
) -> None:
    package, receipt, expected = _r19_files(tmp_path)
    authority_path = _write_json(
        tmp_path / "current_authority.json",
        _current_authority_payload(),
    )
    current = load_current_authority(authority_path)
    calls: list[str] = []

    def request_builder(**kwargs: object) -> dict[str, object]:
        calls.append("request")
        assert kwargs["artifact_id"] == "11111111-1111-4111-8111-111111111111"
        assert kwargs["role_assignment_state"] == "officer_only"
        return {"fresh": True}

    def baseline_reader(request: object, **kwargs: object) -> dict[str, object]:
        calls.append("reads")
        assert request == {"fresh": True}
        assert kwargs["source_sha"] == SOURCE_SHA
        return _baseline()

    written: dict[str, object] = {}

    def bundle_writer(**kwargs: object) -> tuple[Path, ...]:
        calls.append("write")
        written.update(kwargs)
        return (authority_path,)

    result = run_readonly_authority_refresh(
        r19_package=package,
        r19_receipt=receipt,
        authority_output_root=tmp_path,
        source_sha=SOURCE_SHA,
        source_tree=SOURCE_TREE,
        artifact_id="11111111-1111-4111-8111-111111111111",
        now=NOW,
        r19_expected=expected,
        current_authority=current,
        document_policy={
            "schema_version": "bizpulse.authority-document-policy.v1",
            "documents": [],
        },
        request_builder=request_builder,
        baseline_reader=baseline_reader,
        bundle_writer=bundle_writer,
        preflight=lambda: calls.append("preflight"),
        postread_fence=lambda: calls.append("postread"),
        provenance_validator=lambda *_args, **_kwargs: (
            _successor_provenance()[0]
        ),
        successor_deriver=lambda *_args, **_kwargs: _successor_contract()[1],
    )

    assert calls == ["preflight", "request", "reads", "postread", "write"]
    assert result == {
        "azure_read_count": 12,
        "database_revision": "0014_import_base_lineage",
        "evidence_sha256": "d" * 64,
        "expires_at": "2026-08-18T21:00:00Z",
        "revision": CURRENT_RECOVERY_REVISION,
    }
    refreshed = written["authority"]
    assert refreshed.prepared_candidate == {"state": "preserve-me"}
    assert refreshed.development.repository_migration_head == (
        "0017_ai_turn_credential_binding"
    )


def test_default_request_builder_creates_a_new_strict_task10_successor(
    tmp_path: Path,
) -> None:
    package, receipt, expected = _r19_files(tmp_path)
    authority_path = _write_json(
        tmp_path / "current_authority.json",
        _current_authority_payload(),
    )
    observed_request: dict[str, object] = {}

    def baseline_reader(request: object, **_kwargs: object) -> dict[str, object]:
        validated = validate_ai_enablement_package(request, now=NOW)
        observed_request.update(validated)
        return _baseline()

    run_readonly_authority_refresh(
        r19_package=package,
        r19_receipt=receipt,
        authority_output_root=tmp_path,
        source_sha=SOURCE_SHA,
        source_tree=SOURCE_TREE,
        artifact_id="11111111-1111-4111-8111-111111111111",
        now=NOW,
        r19_expected=expected,
        current_authority=load_current_authority(authority_path),
        document_policy={
            "schema_version": "bizpulse.authority-document-policy.v1",
            "documents": [],
        },
        baseline_reader=baseline_reader,
        bundle_writer=lambda **_kwargs: (),
        provenance_validator=lambda *_args, **_kwargs: (
            _successor_provenance()[0]
        ),
        successor_deriver=lambda *_args, **_kwargs: _successor_contract()[1],
    )

    assert observed_request["repository"]["head_sha"] == SOURCE_SHA
    assert observed_request["repository"]["tree_sha"] == SOURCE_TREE
    assert observed_request["azure_target"]["rollback_revision"] == (
        CURRENT_RECOVERY_REVISION
    )
    assert observed_request["prepackage_gate"]["rollback_identity_state"] == (
        "registry_only"
    )
    assert observed_request["artifacts"] == {
        "package_path": (
            ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_TASK12_"
            "11111111-1111-4111-8111-111111111111.json"
        ),
        "receipt_path": (
            ".tmp/AI_ENABLEMENT_RECEIPT_TASK12_"
            "11111111-1111-4111-8111-111111111111.json"
        ),
        "observation_path": (
            ".tmp/AI_ENABLEMENT_OBSERVATION_TASK12_"
            "11111111-1111-4111-8111-111111111111.json"
        ),
    }
    assert observed_request["artifacts"] != PRIOR_AI_ATTEMPTS["r19"]
    assert observed_request["prior_attempts"]["r19"] == PRIOR_AI_ATTEMPTS["r19"]
    assert observed_request["prepackage_gate"]["role_assignment_state"] == (
        "officer_only"
    )


def test_readonly_refresh_stops_before_reads_when_document_preflight_fails(
    tmp_path: Path,
) -> None:
    package, receipt, expected = _r19_files(tmp_path)
    authority_path = _write_json(
        tmp_path / "current_authority.json",
        _current_authority_payload(),
    )
    reads = 0

    def fail_preflight() -> None:
        raise CurrentAuthorityRefreshInvalid("authority_refresh_document_drift")

    def baseline_reader(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal reads
        reads += 1
        return _baseline()

    with pytest.raises(
        CurrentAuthorityRefreshInvalid,
        match="authority_refresh_document_drift",
    ):
        run_readonly_authority_refresh(
            r19_package=package,
            r19_receipt=receipt,
            authority_output_root=tmp_path,
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            artifact_id="11111111-1111-4111-8111-111111111111",
            now=NOW,
            r19_expected=expected,
            current_authority=load_current_authority(authority_path),
            document_policy={
                "schema_version": "bizpulse.authority-document-policy.v1",
                "documents": [],
            },
            request_builder=lambda **_kwargs: {"fresh": True},
            baseline_reader=baseline_reader,
            bundle_writer=lambda **_kwargs: (),
            preflight=fail_preflight,
            postread_fence=lambda: None,
        )

    assert reads == 0


def test_cli_emits_only_bounded_safe_refresh_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    package, receipt, _expected = _r19_files(tmp_path)
    observed: dict[str, object] = {}

    def refresh_runner(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {
            "azure_read_count": 12,
            "database_revision": "0014_import_base_lineage",
            "evidence_sha256": "d" * 64,
            "expires_at": "2026-08-18T21:00:00Z",
            "revision": CURRENT_RECOVERY_REVISION,
        }

    result = main(
        [
            "--r19-package",
            str(package),
            "--r19-receipt",
            str(receipt),
            "--authority-output-root",
            str(tmp_path),
        ],
        now_factory=lambda: NOW,
        artifact_id_factory=lambda: "11111111-1111-4111-8111-111111111111",
        refresh_runner=refresh_runner,
        runtime_context_loader=lambda _root, _output: {
            "source_sha": SOURCE_SHA,
            "source_tree": SOURCE_TREE,
            "current_authority": load_current_authority(
                _write_json(
                    tmp_path / "authority-for-cli.json",
                    _current_authority_payload(),
                )
            ),
            "document_policy": {
                "schema_version": "bizpulse.authority-document-policy.v1",
                "documents": [],
            },
            "preflight": lambda: None,
            "postread_fence": lambda: None,
            "bundle_writer": lambda **_kwargs: (),
        },
    )

    output = capsys.readouterr().out.splitlines()
    assert result == 0
    assert output == [
        "admin_ai_authority_refresh=updated",
        "azure_read_count=12",
        f"revision={CURRENT_RECOVERY_REVISION}",
        "database_revision=0014_import_base_lineage",
        "expires_at=2026-08-18T21:00:00Z",
        "evidence_sha256=" + "d" * 64,
    ]
    assert observed["artifact_id"] == "11111111-1111-4111-8111-111111111111"
    assert "raw" not in json.dumps(output).casefold()
