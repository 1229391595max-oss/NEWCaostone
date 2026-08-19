from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

import pytest

from scripts.build_deployed_release_desired_projection import (
    compile_desired_projection,
)
from scripts.deployed_release_diagnostic_contract import (
    DeployedReleaseDiagnosticInvalid,
    canonical_sha256,
    load_strict_json,
    replace_owner_json_atomic,
    write_owner_json_exclusive,
)
from scripts.verify_deployed_release_state import (
    load_deployed_release_continuation,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTINUATION = (
    PROJECT_ROOT / "release/incidents/2026-08-16-recovery-v4-deployed-continuation.json"
)
CONTINUATION_SHA256 = "d355c9215ee9dec22adb93392705107dfd8f06db37ca8d03b240c519278af4af"
BICEP = PROJECT_ROOT / "infra/modules/app.bicep"


@pytest.fixture(scope="module")
def continuation() -> dict[str, object]:
    return load_deployed_release_continuation(
        CONTINUATION,
        expected_sha256=CONTINUATION_SHA256,
    )


@pytest.fixture(scope="module")
def compiled_template() -> dict[str, object]:
    completed = subprocess.run(
        ["az", "bicep", "build", "--file", str(BICEP), "--stdout"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return json.loads(completed.stdout)


def _fake_bicep(
    compiled: dict[str, object],
) -> object:
    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(compiled),
            stderr="",
        )

    return run


def _job_resource(
    compiled: dict[str, object], container_name: str
) -> dict[str, object]:
    resources = compiled["resources"]
    assert isinstance(resources, list)
    for resource in resources:
        if (
            not isinstance(resource, dict)
            or resource.get("type") != "Microsoft.App/jobs"
        ):
            continue
        container = resource["properties"]["template"]["containers"][0]
        if container["name"] == container_name:
            return resource
    raise AssertionError(container_name)


def test_compiled_bicep_projection_includes_complete_job_environment() -> None:
    continuation = load_deployed_release_continuation(
        CONTINUATION, expected_sha256=CONTINUATION_SHA256
    )

    projection = compile_desired_projection(
        PROJECT_ROOT / "infra/modules/app.bicep",
        continuation,
        continuation_sha256=CONTINUATION_SHA256,
    )

    for role in (
        "prepare",
        "seed",
        "session_maintenance",
        "storage_maintenance",
    ):
        bindings = projection["jobs"][role]["environment_bindings"]
        assert bindings["BIZPULSE_ALLOWED_ORIGIN"] == "value"
        assert bindings["BIZPULSE_OPERATOR_PASSWORD_HASH"] == (
            "secretRef:operator-password-hash"
        )


def test_compiled_bicep_projection_excludes_scoped_operator_rotation_job() -> None:
    continuation = load_deployed_release_continuation(
        CONTINUATION, expected_sha256=CONTINUATION_SHA256
    )

    projection = compile_desired_projection(
        BICEP,
        continuation,
        continuation_sha256=CONTINUATION_SHA256,
    )

    assert set(projection["jobs"]) == {
        "prepare",
        "seed",
        "session_maintenance",
        "storage_maintenance",
    }


def test_bicep_projection_rejects_unknown_job_alongside_scoped_rotation(
    compiled_template: dict[str, object],
    continuation: dict[str, object],
) -> None:
    compiled = deepcopy(compiled_template)
    unexpected = deepcopy(_job_resource(compiled, "operator-rotation"))
    unexpected["properties"]["template"]["containers"][0]["name"] = "unexpected"
    compiled["resources"].append(unexpected)

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_bicep_projection_invalid",
    ):
        compile_desired_projection(
            BICEP,
            continuation,
            continuation_sha256=CONTINUATION_SHA256,
            runner=_fake_bicep(compiled),
        )


def test_compiled_bicep_projection_includes_complete_no_ai_application() -> None:
    continuation = load_deployed_release_continuation(
        CONTINUATION, expected_sha256=CONTINUATION_SHA256
    )

    projection = compile_desired_projection(
        BICEP,
        continuation,
        continuation_sha256=CONTINUATION_SHA256,
    )

    application = projection["application"]
    assert application["resource_name"] == "newcaostone-demo-app"
    assert application["revision_name"] == ("newcaostone-demo-app--713a6984d4a0")
    assert application["container_name"] == "bizpulse"
    assert application["image"].endswith(
        "@sha256:713a6984d4a034a0be73b46c10a897aeb236c201325ff8a88ba524fc6c10295c"
    )
    assert (
        application["environment_bindings"]["BIZPULSE_OPERATOR_PASSWORD_HASH"]
        == "secretRef:operator-password-hash"
    )
    assert "OPENAI_API_KEY" not in application["environment_bindings"]
    assert "OPENAI_BASE_URL" not in application["environment_bindings"]
    assert application["secret_names"] == [
        "blob-connection-string",
        "database-url",
        "operator-password-hash",
        "session-pepper",
    ]
    assert application["resources"] == {"cpu": 0.5, "memory": "1Gi"}
    assert application["scale"] == {"maxReplicas": 1, "minReplicas": 1}
    assert application["ingress"] == {
        "allowInsecure": False,
        "external": True,
        "targetPort": 8000,
        "traffic": [{"latestRevision": True, "weight": 100}],
        "transport": "auto",
    }
    assert [probe["type"] for probe in application["probes"]] == [
        "Liveness",
        "Readiness",
    ]
    assert application["expected_value_env"]["BIZPULSE_AI_CHAT_ENABLED"] == ("false")
    for channel_flag in (
        "BIZPULSE_OPERATOR_AI_ENABLED",
        "BIZPULSE_DEMO_AI_ENABLED",
        "BIZPULSE_AI_OPERATOR_ENABLED",
        "BIZPULSE_AI_DEMO_ENABLED",
    ):
        assert channel_flag not in application["environment_bindings"]


def test_admin_ai_app_identity_does_not_change_operator_rotation_authority(
    compiled_template: dict[str, object],
) -> None:
    rotation = _job_resource(compiled_template, "operator-rotation")
    identities = rotation["identity"]["userAssignedIdentities"]
    serialized = json.dumps(rotation, sort_keys=True)

    assert identities == {
        "[format('{0}', parameters('registryIdentityResourceId'))]": {}
    }
    assert "openaiManagedIdentityResourceId" not in serialized
    assert "BIZPULSE_OPENAI" not in serialized
    assert "BIZPULSE_AI_CHAT_ENABLED" not in serialized


def test_projection_top_level_keys_are_exact() -> None:
    continuation = load_deployed_release_continuation(
        CONTINUATION, expected_sha256=CONTINUATION_SHA256
    )

    projection = compile_desired_projection(
        BICEP,
        continuation,
        continuation_sha256=CONTINUATION_SHA256,
    )

    assert set(projection) == {
        "application",
        "continuation_sha256",
        "jobs",
        "schema_version",
    }
    assert projection["schema_version"] == (
        "newcaostone.deployed-release-desired-projection.v1"
    )
    for job in projection["jobs"].values():
        assert job["command"] == ["python"]
        assert job["resources"] == {"cpu": 0.5, "memory": "1Gi"}


def test_shared_contract_primitives_are_strict_and_owner_only(
    tmp_path: Path,
) -> None:
    assert canonical_sha256({"b": 2, "a": 1}) == canonical_sha256({"a": 1, "b": 2})
    target = tmp_path / "observation.json"

    write_owner_json_exclusive(target, {"state": "started"})

    assert os.stat(target).st_mode & 0o777 == 0o600
    assert load_strict_json(target, max_bytes=1_000) == {"state": "started"}
    with pytest.raises(FileExistsError):
        write_owner_json_exclusive(target, {"state": "unexpected"})

    replace_owner_json_atomic(target, {"state": "completed"})

    assert os.stat(target).st_mode & 0o777 == 0o600
    assert load_strict_json(target, max_bytes=1_000) == {"state": "completed"}


def test_strict_json_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    target = tmp_path / "duplicate.json"
    target.write_text('{"state":"started","state":"completed"}')

    with pytest.raises(DeployedReleaseDiagnosticInvalid):
        load_strict_json(target, max_bytes=1_000)


def test_diagnostic_error_falls_back_to_safe_enums() -> None:
    error = DeployedReleaseDiagnosticInvalid("unsafe", "remote", "secret")

    assert (error.code, error.stage, error.resource_role) == (
        "diagnostic_package_invalid",
        "local",
        "local",
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "remove_allowed_origin",
        "change_operator_hash_binding",
        "duplicate_env_name",
        "add_literal_secret_value",
        "add_scheduled_literal_secret",
        "add_application_literal_secret",
        "change_job_command",
        "remove_seed_job",
        "remove_application",
        "duplicate_application",
        "change_application_probe",
        "change_scoped_rotation_args",
        "change_scoped_rotation_secret",
        "add_scoped_rotation_computed_key_environment",
    ),
)
def test_bicep_projection_rejects_contract_drift(
    mutation: str,
    compiled_template: dict[str, object],
    continuation: dict[str, object],
) -> None:
    compiled = deepcopy(compiled_template)
    prepare = _job_resource(compiled, "prepare")
    prepare_container = prepare["properties"]["template"]["containers"][0]
    env = prepare_container["env"]
    if mutation == "remove_allowed_origin":
        env[:] = [row for row in env if row["name"] != "BIZPULSE_ALLOWED_ORIGIN"]
    elif mutation == "change_operator_hash_binding":
        next(row for row in env if row["name"] == "BIZPULSE_OPERATOR_PASSWORD_HASH")[
            "secretRef"
        ] = "other-secret"
    elif mutation == "duplicate_env_name":
        env.append(deepcopy(env[0]))
    elif mutation == "add_literal_secret_value":
        next(
            row
            for row in prepare["properties"]["configuration"]["secrets"]
            if row["name"] == "operator-password-hash"
        )["value"] = "literal-secret-value"
    elif mutation == "add_scheduled_literal_secret":
        scheduled = _job_resource(compiled, "maintain-sessions")
        configuration = scheduled["properties"]["configuration"]
        scheduled["properties"]["configuration"] = configuration.replace(
            "parameters('operatorPasswordHash')", "'literal-secret-value'"
        )
    elif mutation == "add_application_literal_secret":
        application = next(
            resource
            for resource in compiled["resources"]
            if isinstance(resource, dict)
            and resource.get("type") == "Microsoft.App/containerApps"
        )
        secrets = application["properties"]["configuration"]["secrets"]
        application["properties"]["configuration"]["secrets"] = secrets.replace(
            "parameters('operatorPasswordHash')", "'literal-secret-value'"
        )
    elif mutation == "change_job_command":
        prepare_container["command"] = ["sh"]
    elif mutation == "remove_seed_job":
        resources = compiled["resources"]
        resources[:] = [
            resource
            for resource in resources
            if not (
                isinstance(resource, dict)
                and resource.get("type") == "Microsoft.App/jobs"
                and resource["properties"]["template"]["containers"][0]["name"]
                == "seed"
            )
        ]
    elif mutation == "remove_application":
        resources = compiled["resources"]
        resources[:] = [
            resource
            for resource in resources
            if not (
                isinstance(resource, dict)
                and resource.get("type") == "Microsoft.App/containerApps"
            )
        ]
    elif mutation == "duplicate_application":
        resources = compiled["resources"]
        application = next(
            resource
            for resource in resources
            if isinstance(resource, dict)
            and resource.get("type") == "Microsoft.App/containerApps"
        )
        resources.append(deepcopy(application))
    elif mutation == "change_scoped_rotation_args":
        rotation = _job_resource(compiled, "operator-rotation")
        rotation["properties"]["template"]["containers"][0]["args"] = [
            "scripts/unexpected.py"
        ]
    elif mutation == "change_scoped_rotation_secret":
        rotation = _job_resource(compiled, "operator-rotation")
        secrets = rotation["properties"]["configuration"]["secrets"]
        next(
            row for row in secrets if row["name"] == "operator-password-hash"
        )["value"] = "[parameters('operatorPasswordHash')]"
    elif mutation == "add_scoped_rotation_computed_key_environment":
        rotation = _job_resource(compiled, "operator-rotation")
        container = rotation["properties"]["template"]["containers"][0]
        environment = container["env"]
        assert isinstance(environment, str)
        container["env"] = environment.replace(
            "parameters('operatorRotationId'), ''))",
            "parameters('operatorRotationId'), '')), "
            "createObject(concat('na', 'me'), 'BIZPULSE_UNEXPECTED', "
            "'value', 'unexpected')",
        )
    else:
        compiled["variables"]["appProbes"][0]["httpGet"]["path"] = "/wrong"

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_bicep_projection_invalid",
    ):
        compile_desired_projection(
            BICEP,
            continuation,
            continuation_sha256=CONTINUATION_SHA256,
            runner=_fake_bicep(compiled),
        )
