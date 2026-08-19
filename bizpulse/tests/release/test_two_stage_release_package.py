from __future__ import annotations

import json
from pathlib import Path
import shlex

import pytest

from scripts.create_two_stage_release_package import (
    TwoStagePackageInvalid,
    build_data_stage_authority,
    build_two_stage_package,
    render_two_stage_package,
    write_two_stage_package,
)
from scripts.qualify_openai_model import build_cases
from scripts.verify_stage_receipts import (
    StageReceiptInvalid,
    validate_stage_receipts,
)
from tests.hosted.test_verify_azure_demo import NOW, _authorization
from tests.hosted.verify_azure_demo import (
    _expected_ai_transition_commands,
    data_authority_sha256,
    load_two_stage_authorization,
)


def _data_authority() -> dict[str, object]:
    authority = _authorization()
    authority["external_publication"]["registry_publish"] = True
    authority["allowed_operations"].insert(1, "registry_publish")
    from tests.hosted.test_verify_azure_demo import _commands, _execution_order

    authority["commands"] = _commands(authority)
    authority["execution_order"] = _execution_order(authority)
    return authority


def _package() -> dict[str, object]:
    return build_two_stage_package(
        data_authority=_data_authority(),
        tenant_id="44444444-4444-4444-8444-444444444444",
        package_id="33333333-3333-4333-8333-333333333333",
        hard_cap_usd="100.00",
        qualification_cap_usd="1.00",
        hosted_smoke_cap_usd="0.25",
    )


def test_builder_creates_exact_valid_data_then_ai_package(tmp_path: Path) -> None:
    package = _package()
    path = tmp_path / "LAUNCH_AUTHORIZATION_TWO_STAGE_V1.md"
    write_two_stage_package(path, package)

    assert load_two_stage_authorization(path, now=NOW) == package
    assert package["data_authority_sha256"] == data_authority_sha256(
        package["data_scope_revision"]["authority"]
    )
    assert package["ai_revision"]["commands"] == (
        _expected_ai_transition_commands(package)
    )
    assert len(package["ai_revision"]["commands"]["deploy"]) == 2
    assert "--ai-enabled true" in package["ai_revision"]["commands"]["deploy"][1]
    assert (
        "--expected-revision " + package["ai_revision"]["revision"]
        in package["ai_revision"]["commands"]["deploy"][1]
    )
    rollback = package["ai_revision"]["commands"]["rollback_on_failure"]
    assert len(rollback) == 5
    assert "revision activate" in rollback[0]
    assert package["data_scope_revision"]["revision"] in rollback[0]
    assert "ingress traffic set" in rollback[1]
    assert "revision deactivate" in rollback[2]
    assert package["ai_revision"]["revision"] in rollback[2]
    assert "secret remove" in rollback[3]
    assert "openai-api-key" in rollback[3]
    assert rollback[4].endswith("--check browser --scenario core")
    assert path.stat().st_mode & 0o777 == 0o600
    assert "sk-" not in render_two_stage_package(package).decode()


def test_builder_rejects_ai_enabled_data_stage() -> None:
    authority = _data_authority()
    authority["ai_limits"]["enabled"] = True

    with pytest.raises(TwoStagePackageInvalid, match="data_stage_ai_must_be_disabled"):
        build_two_stage_package(
            data_authority=authority,
            tenant_id="44444444-4444-4444-8444-444444444444",
            package_id="33333333-3333-4333-8333-333333333333",
            hard_cap_usd="100.00",
            qualification_cap_usd="1.00",
            hosted_smoke_cap_usd="0.25",
        )


def test_data_stage_builder_binds_exact_existing_target_and_ai_disabled(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "attestation.json"
    manifest_path.write_text(
        json.dumps(
            {
                "candidate_git_sha": "a" * 40,
                "candidate_image": {"digest": "sha256:" + "b" * 64},
                "image_input_sha256": "c" * 64,
                "migration_head": "0014_import_base_lineage",
                "rollback_compatible_prior_sha": "d" * 40,
                "rollback_image_digest": "sha256:" + "e" * 64,
                "rollback_image_input_sha256": "f" * 64,
                "synthetic_fixture": {
                    "manifest_sha256": "ignored-and-recomputed"
                },
            }
        )
    )

    authority = build_data_stage_authority(
        attestation_path=manifest_path,
        attestation_git_sha="1" * 40,
        authorization_id="22222222-2222-4222-8222-222222222222",
        issued_at="2026-08-14T14:00:00Z",
        expires_at="2026-08-16T14:00:00Z",
        subscription_id="11111111-1111-4111-8111-111111111111",
        region="brazilsouth",
        resource_group="rg-synthetic-demo-approved",
        public_url="https://bp-approved-app.synthetic.azurecontainerapps.io",
        name_prefix="bp-approved",
        registry_name="bpapprovedregistry",
        image_repository="bizpulse",
        storage_account="bpapprovedstorage",
        postgres_server="bp-approved-pg",
        postgres_administrator_login="bpoperator",
        observed_current_image_digest="sha256:" + "e" * 64,
        hard_cap_usd="100.00",
        one_time_estimate_usd="10.00",
        monthly_estimate_usd="80.00",
    )

    assert authority["generated_names"]["container_app"] == "bp-approved-app"
    assert authority["generated_names"]["container_environment"] == "bp-approved-env"
    assert authority["release"]["migration_head"] == "0014_import_base_lineage"
    assert authority["release"]["image_digest"] == "sha256:" + "b" * 64
    assert authority["ai_limits"]["enabled"] is False
    assert authority["secret_presence"]["openai_api_key"] is False
    assert authority["external_publication"]["registry_publish"] is True
    assert len(authority["commands"]["registry_publish"]) == 1
    assert "--candidate-git-sha " + "a" * 40 in authority["commands"][
        "registry_publish"
    ][0]
    assert len(authority["commands"]["provision"]) == 2
    assert authority["commands"]["activate"] == []
    assert "applicationEnabled=false" not in json.dumps(authority["commands"])


def test_update_mode_provision_binds_job_image_command_and_authority_args(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "attestation.json"
    manifest_path.write_text(
        json.dumps(
            {
                "candidate_git_sha": "a" * 40,
                "candidate_image": {"digest": "sha256:" + "b" * 64},
                "image_input_sha256": "c" * 64,
                "migration_head": "0014_import_base_lineage",
                "rollback_compatible_prior_sha": "d" * 40,
                "rollback_image_digest": "sha256:" + "e" * 64,
                "rollback_image_input_sha256": "f" * 64,
                "synthetic_fixture": {
                    "manifest_sha256": "ignored-and-recomputed"
                },
            }
        )
    )
    authority = build_data_stage_authority(
        attestation_path=manifest_path,
        attestation_git_sha="1" * 40,
        authorization_id="22222222-2222-4222-8222-222222222222",
        issued_at="2026-08-14T14:00:00Z",
        expires_at="2026-08-16T14:00:00Z",
        subscription_id="11111111-1111-4111-8111-111111111111",
        region="brazilsouth",
        resource_group="rg-synthetic-demo-approved",
        public_url="https://bp-approved-app.synthetic.azurecontainerapps.io",
        name_prefix="bp-approved",
        registry_name="bpapprovedregistry",
        image_repository="bizpulse",
        storage_account="bpapprovedstorage",
        postgres_server="bp-approved-pg",
        postgres_administrator_login="bpoperator",
        observed_current_image_digest="sha256:" + "e" * 64,
        hard_cap_usd="100.00",
        one_time_estimate_usd="10.00",
        monthly_estimate_usd="80.00",
    )

    prepare, seed = (
        shlex.split(command) for command in authority["commands"]["provision"]
    )
    assert prepare[:2] == [
        ".venv/bin/python",
        "scripts/update_azure_job_binding.py",
    ]
    assert seed[:2] == prepare[:2]
    assert "containerapp job update" not in authority["commands"]["provision"][0]
    assert json.loads(prepare[prepare.index("--arguments-json") + 1]) == [
        "scripts/prepare_cloud.py"
    ]
    assert json.loads(seed[seed.index("--arguments-json") + 1]) == [
        "scripts/seed_demo.py",
        "tests/fixtures/synthetic/v1",
        "--expected-manifest-sha256",
        authority["release"]["synthetic_manifest_sha256"],
        "--expected-dataset-version-id",
        authority["release"]["synthetic_dataset_version_id"],
    ]


def test_recovery_data_authority_uses_present_registry_without_publication(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "attestation.json"
    manifest_path.write_text(
        json.dumps(
            {
                "candidate_git_sha": "a" * 40,
                "candidate_image": {"digest": "sha256:" + "b" * 64},
                "image_input_sha256": "c" * 64,
                "migration_head": "0014_import_base_lineage",
                "rollback_compatible_prior_sha": "d" * 40,
                "rollback_image_digest": "sha256:" + "e" * 64,
                "rollback_image_input_sha256": "f" * 64,
                "synthetic_fixture": {
                    "manifest_sha256": "ignored-and-recomputed"
                },
            }
        )
    )

    authority = build_data_stage_authority(
        attestation_path=manifest_path,
        attestation_git_sha="1" * 40,
        authorization_id="22222222-2222-4222-8222-222222222222",
        issued_at="2026-08-14T14:00:00Z",
        expires_at="2026-08-16T14:00:00Z",
        subscription_id="11111111-1111-4111-8111-111111111111",
        region="brazilsouth",
        resource_group="rg-synthetic-demo-approved",
        public_url="https://bp-approved-app.synthetic.azurecontainerapps.io",
        name_prefix="bp-approved",
        registry_name="bpapprovedregistry",
        image_repository="bizpulse",
        storage_account="bpapprovedstorage",
        postgres_server="bp-approved-pg",
        postgres_administrator_login="bpoperator",
        observed_current_image_digest="sha256:" + "e" * 64,
        hard_cap_usd="100.00",
        one_time_estimate_usd="0.00",
        monthly_estimate_usd="80.00",
        registry_publish=False,
    )

    assert authority["external_publication"]["registry_publish"] is False
    assert authority["commands"]["registry_publish"] == []
    assert "registry_publish" not in authority["allowed_operations"]
    assert authority["execution_order"][:3] == [
        "preflight",
        "registry_verify",
        "provision",
    ]


def _data_receipt(package: dict[str, object]) -> dict[str, object]:
    data = package["data_scope_revision"]
    authority = data["authority"]
    return {
        "schema_version": "newcaostone.data-scope-receipt.v1",
        "package_id": package["package_id"],
        "data_authority_sha256": package["data_authority_sha256"],
        "revision": data["revision"],
        "image_digest": authority["release"]["image_digest"],
        "ai_enabled": False,
        "openai_api_key_present": False,
        "checks": [
            {"name": name, "passed": True}
            for name in data["receipt_contract"]["required_checks"]
        ],
    }


def _qualification_receipt() -> dict[str, object]:
    cases = [
        {"case_id": case.case_id, "passed": True}
        for case in build_cases()
    ]
    return {
        "schema_version": 1,
        "model_snapshot": {
            "model": "gpt-5.4-nano-2026-03-17",
            "reasoning_effort": "low",
            "max_output_tokens": 2800,
        },
        "case_ids": [case["case_id"] for case in cases],
        "cases": cases,
        "passed": True,
    }


def test_stage_receipts_bind_exact_data_revision_and_all_12_cases() -> None:
    package = _package()

    validate_stage_receipts(
        package,
        data_receipt=_data_receipt(package),
        qualification_receipt=_qualification_receipt(),
    )


@pytest.mark.parametrize(
    "mutation",
    (
        lambda data, _qualification: data.update(revision="wrong-revision"),
        lambda data, _qualification: data.update(openai_api_key_present=True),
        lambda _data, qualification: qualification["cases"].pop(),
        lambda _data, qualification: qualification.update(passed=False),
        lambda _data, qualification: qualification["model_snapshot"].update(model="mutable-alias"),
    ),
)
def test_stage_receipts_fail_closed_on_drift(mutation) -> None:
    package = _package()
    data = _data_receipt(package)
    qualification = _qualification_receipt()
    mutation(data, qualification)

    with pytest.raises(StageReceiptInvalid):
        validate_stage_receipts(
            package,
            data_receipt=data,
            qualification_receipt=qualification,
        )


def test_receipts_do_not_need_or_accept_a_key_value() -> None:
    package = _package()
    data = _data_receipt(package)
    qualification = _qualification_receipt()
    serialized = json.dumps({"data": data, "qualification": qualification})

    assert "OPENAI_API_KEY" not in serialized
    assert "sk-" not in serialized
