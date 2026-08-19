from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from scripts.build_deployed_release_desired_projection import (
    compile_desired_projection,
)
from scripts.deployed_release_diagnostic_contract import (
    DeployedReleaseDiagnosticInvalid,
    evaluate_execution_history,
    parse_utc,
)
from scripts.observe_deployed_release_state import (
    ArmScope,
    ReadBudget,
    collect_arm_payloads,
    observe_deployed_release_state,
    project_deployed_resources,
    read_arm_collection,
    read_arm_page,
)
from scripts.verify_deployed_release_state import (
    load_deployed_release_continuation,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTINUATION_PATH = (
    PROJECT_ROOT / "release/incidents/2026-08-16-recovery-v4-deployed-continuation.json"
)
CONTINUATION_SHA256 = "d355c9215ee9dec22adb93392705107dfd8f06db37ca8d03b240c519278af4af"


@pytest.fixture(scope="module")
def continuation() -> dict[str, object]:
    return load_deployed_release_continuation(
        CONTINUATION_PATH,
        expected_sha256=CONTINUATION_SHA256,
    )


@pytest.fixture(scope="module")
def desired_projection(
    continuation: dict[str, object],
) -> dict[str, object]:
    return compile_desired_projection(
        PROJECT_ROOT / "infra/modules/app.bicep",
        continuation,
        continuation_sha256=CONTINUATION_SHA256,
    )


def _arm(continuation: dict[str, object]) -> dict[str, object]:
    target = continuation["target"]
    prefix = (
        f"/subscriptions/{target['subscription_id']}/resourceGroups/"
        f"{target['resource_group']}/providers/Microsoft.App"
    )
    application = f"{prefix}/containerApps/{target['application']}"
    paths = [application, f"{application}/revisions"]
    for key in (
        "prepare_job",
        "seed_job",
        "session_maintenance_job",
        "storage_maintenance_job",
    ):
        job = f"{prefix}/jobs/{target[key]}"
        paths.extend((job, f"{job}/executions"))
    return {
        "allowed_http_methods": ["GET"],
        "allowed_resource_paths": paths,
        "api_version": "2024-03-01",
        "host": "management.azure.com",
        "max_page_bytes": 1_000_000,
        "max_pages_per_collection": 5,
        "max_total_requests": 30,
        "max_total_response_bytes": 8_000_000,
        "request_retry_limit": 0,
        "request_timeout_seconds": 30,
    }


def _scope(continuation: dict[str, object]) -> ArmScope:
    return ArmScope.from_arm_authority(_arm(continuation))


def _url(path: str, query: str = "api-version=2024-03-01") -> str:
    return f"https://management.azure.com{path}?{query}"


def _runner(
    payloads: list[object],
    calls: list[list[str]],
    kwargs_seen: list[dict[str, object]] | None = None,
    *,
    returncode: int = 0,
    stderr: bytes = b"",
) -> Callable[..., subprocess.CompletedProcess[bytes]]:
    queue = list(payloads)

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        if kwargs_seen is not None:
            kwargs_seen.append(dict(kwargs))
        payload = queue.pop(0)
        stdout = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return subprocess.CompletedProcess(
            command,
            returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return run


def test_arm_reader_uses_exact_sanitized_az_rest_command(
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
) -> None:
    arm = _arm(continuation)
    expected_app_url = _url(arm["allowed_resource_paths"][0])
    calls: list[list[str]] = []
    kwargs_seen: list[dict[str, object]] = []
    monkeypatch.setenv("D1_SHOULD_NOT_LEAK", "do-not-forward")

    page = read_arm_page(
        expected_app_url,
        limits=arm,
        runner=_runner([{"name": "app"}], calls, kwargs_seen),
    )

    assert calls[0] == [
        "az",
        "rest",
        "--method",
        "get",
        "--url",
        expected_app_url,
        "--only-show-errors",
        "--output",
        "json",
    ]
    assert page.payload == {"name": "app"}
    assert page.byte_count > 0
    assert len(page.sha256) == 64
    assert kwargs_seen[0]["check"] is False
    assert kwargs_seen[0]["capture_output"] is True
    assert kwargs_seen[0]["text"] is False
    assert kwargs_seen[0]["timeout"] == 30
    assert kwargs_seen[0]["cwd"] == PROJECT_ROOT
    assert kwargs_seen[0]["shell"] is False
    assert "D1_SHOULD_NOT_LEAK" not in kwargs_seen[0]["env"]
    assert set(kwargs_seen[0]["env"]) <= {
        "AZURE_CONFIG_DIR",
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "TMPDIR",
    }


def test_arm_page_rejects_out_of_scope_url_before_runner(
    continuation: dict[str, object],
) -> None:
    arm = _arm(continuation)
    calls: list[list[str]] = []
    out_of_scope = _url(arm["allowed_resource_paths"][0]).replace(
        "management.azure.com", "example.com"
    )

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_arm_scope_invalid",
    ):
        read_arm_page(
            out_of_scope,
            limits=arm,
            runner=_runner([{}], calls),
        )

    assert calls == []


@pytest.mark.parametrize(
    ("method", "mutator"),
    (
        ("post", lambda url: url),
        ("get", lambda url: url.replace("https://", "http://")),
        ("get", lambda url: url.replace("management.azure.com", "example.com")),
        ("get", lambda url: url.replace("https://", "https://user:pass@")),
        ("get", lambda url: url.replace("/subscriptions/", "/subscriptions/wrong-")),
        ("get", lambda url: url.replace("/resourceGroups/", "/resourceGroups/wrong-")),
        ("get", lambda url: url.replace("Microsoft.App", "Microsoft.Storage")),
        ("get", lambda url: url.replace("newcaostone-demo-app", "other-app")),
        ("get", lambda url: url.replace("2024-03-01", "2025-01-01")),
        ("get", lambda url: url + "#fragment"),
        ("get", lambda url: url + "&other=value"),
    ),
)
def test_arm_scope_rejects_requests_outside_exact_authority(
    continuation: dict[str, object],
    method: str,
    mutator: Callable[[str], str],
) -> None:
    arm = _arm(continuation)
    url = _url(arm["allowed_resource_paths"][0])

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_arm_scope_invalid",
    ):
        _scope(continuation).validate_request(method, mutator(url))


@pytest.mark.parametrize(
    "query",
    (
        "api-version=2024-03-01&api-version=2024-03-01&skiptoken=one",
        "api-version=2024-03-01&$skiptoken=",
        "api-version=2024-03-01&skiptoken=one&$skiptoken=two",
        "api-version=2024-03-01&continuationToken=one",
    ),
)
def test_arm_scope_rejects_invalid_pagination_query(
    continuation: dict[str, object], query: str
) -> None:
    arm = _arm(continuation)
    path = arm["allowed_resource_paths"][1]

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_pagination_invalid",
    ):
        _scope(continuation).validate_request(
            "get",
            _url(path, query),
            expected_path=path,
            pagination=True,
        )


@pytest.mark.parametrize("token_key", ("skiptoken", "$skiptoken", "SkipToken"))
def test_arm_scope_accepts_one_opaque_pagination_token(
    continuation: dict[str, object], token_key: str
) -> None:
    arm = _arm(continuation)
    path = arm["allowed_resource_paths"][1]
    query = f"API-Version=2024-03-01&{token_key}=opaque%2Btoken"

    _scope(continuation).validate_request(
        "get",
        _url(path, query),
        expected_path=path,
        pagination=True,
    )


def test_arm_reader_rejects_duplicate_json_and_discards_secret_output(
    continuation: dict[str, object],
) -> None:
    arm = _arm(continuation)
    url = _url(arm["allowed_resource_paths"][0])
    for stdout, returncode, stderr in (
        (b'{"name":"one","name":"two"}', 0, b""),
        (b'{"error":"Authorization: Bearer do-not-record"}', 0, b""),
        (b"{}", 1, b"Authorization: Bearer do-not-record"),
    ):
        with pytest.raises(DeployedReleaseDiagnosticInvalid) as captured:
            read_arm_page(
                url,
                limits=arm,
                runner=_runner(
                    [stdout],
                    [],
                    returncode=returncode,
                    stderr=stderr,
                ),
            )
        assert "do-not-record" not in str(captured.value)
        assert "do-not-record" not in repr(captured.value)


@pytest.mark.parametrize(
    "error",
    (
        subprocess.TimeoutExpired(["az", "rest"], 30),
        OSError("Authorization: Bearer do-not-record"),
    ),
)
def test_arm_reader_converts_runner_failures_to_safe_code(
    continuation: dict[str, object], error: BaseException
) -> None:
    arm = _arm(continuation)
    url = _url(arm["allowed_resource_paths"][0])

    def failing_runner(
        _command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        raise error

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_arm_request_failed",
    ) as captured:
        read_arm_page(url, limits=arm, runner=failing_runner)

    assert "do-not-record" not in str(captured.value)


def test_arm_page_limit_is_enforced_without_returning_payload(
    continuation: dict[str, object],
) -> None:
    arm = {**_arm(continuation), "max_page_bytes": 3}
    url = _url(arm["allowed_resource_paths"][0])

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_pagination_limit_exceeded",
    ):
        read_arm_page(url, limits=arm, runner=_runner([b"{}  "], []))


def test_arm_pagination_two_pages_succeeds_and_tracks_global_budget(
    continuation: dict[str, object],
) -> None:
    arm = _arm(continuation)
    path = arm["allowed_resource_paths"][1]
    first = _url(path)
    second = _url(path, "api-version=2024-03-01&$skiptoken=second")
    calls: list[list[str]] = []
    budget = ReadBudget.from_limits(arm)

    pages = read_arm_collection(
        first,
        scope=_scope(continuation),
        budget=budget,
        runner=_runner(
            [
                {"nextLink": second, "value": [{"name": "r1"}]},
                {"nextLink": None, "value": [{"name": "r2"}]},
            ],
            calls,
        ),
    )

    assert [page.payload["value"][0]["name"] for page in pages] == ["r1", "r2"]
    assert budget.request_count == 2
    assert budget.total_response_bytes == sum(page.byte_count for page in pages)
    assert [call[5] for call in calls] == [first, second]


def test_arm_pagination_rejects_path_change(
    continuation: dict[str, object],
) -> None:
    arm = _arm(continuation)
    revision_path = arm["allowed_resource_paths"][1]
    other_collection = arm["allowed_resource_paths"][3]
    changed_path = _url(other_collection, "api-version=2024-03-01&skiptoken=second")

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_pagination_invalid",
    ):
        read_arm_collection(
            _url(revision_path),
            scope=_scope(continuation),
            budget=ReadBudget.from_limits(arm),
            runner=_runner(
                [{"nextLink": changed_path, "value": []}],
                [],
            ),
        )


@pytest.mark.parametrize(
    "payload",
    (
        {"value": []},
        {"nextLink": None, "value": []},
        {"count": 0, "value": []},
    ),
)
def test_arm_collection_accepts_azure_terminal_page_shapes(
    continuation: dict[str, object], payload: dict[str, object]
) -> None:
    arm = _arm(continuation)
    path = arm["allowed_resource_paths"][1]
    budget = ReadBudget.from_limits(arm)

    pages = read_arm_collection(
        _url(path),
        scope=_scope(continuation),
        budget=budget,
        runner=_runner([payload], []),
    )

    assert len(pages) == 1
    assert pages[0].payload["value"] == []
    assert budget.request_count == 1


@pytest.mark.parametrize(
    "payload",
    (
        {"nextLink": None},
        {"nextLink": None, "value": {}},
        {"nextLink": 7, "value": []},
        {"nextLink": "", "value": []},
    ),
)
def test_arm_collection_rejects_missing_rows_and_invalid_next_link(
    continuation: dict[str, object], payload: dict[str, object]
) -> None:
    arm = _arm(continuation)
    revision_path = arm["allowed_resource_paths"][1]

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_arm_response_invalid",
    ):
        read_arm_collection(
            _url(revision_path),
            scope=_scope(continuation),
            budget=ReadBudget.from_limits(arm),
            runner=_runner([payload], []),
        )


def test_revision_collection_failure_preserves_safe_context(
    continuation: dict[str, object],
) -> None:
    arm = _arm(continuation)
    path = arm["allowed_resource_paths"][1]

    with pytest.raises(DeployedReleaseDiagnosticInvalid) as captured:
        read_arm_collection(
            _url(path),
            scope=_scope(continuation),
            budget=ReadBudget.from_limits(arm),
            runner=_runner([{"nextLink": 7, "value": []}], []),
            stage="revision",
            role="revision",
        )

    assert captured.value.code == "diagnostic_arm_response_invalid"
    assert captured.value.stage == "revision"
    assert captured.value.resource_role == "revision"


@pytest.mark.parametrize(
    ("payloads", "expected_stage"),
    (
        ([{}, {"value": []}, b"not-json"], "job"),
        ([{}, {"value": []}, {}, b"not-json"], "execution"),
    ),
)
def test_prepare_read_failure_preserves_resource_context(
    continuation: dict[str, object],
    payloads: list[object],
    expected_stage: str,
) -> None:
    with pytest.raises(DeployedReleaseDiagnosticInvalid) as captured:
        collect_arm_payloads(
            {"arm": _arm(continuation)},
            continuation,
            runner=_runner(payloads, []),
        )

    assert captured.value.code == "diagnostic_arm_response_invalid"
    assert captured.value.stage == expected_stage
    assert captured.value.resource_role == "prepare"


@pytest.mark.parametrize(
    ("limit_name", "limit_value"),
    (
        ("max_pages_per_collection", 1),
        ("max_total_requests", 1),
        ("max_total_response_bytes", 1),
    ),
)
def test_arm_pagination_limits_fail_closed(
    continuation: dict[str, object],
    limit_name: str,
    limit_value: int,
) -> None:
    arm = {**_arm(continuation), limit_name: limit_value}
    path = arm["allowed_resource_paths"][1]
    second = _url(path, "api-version=2024-03-01&skiptoken=second")

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_pagination_limit_exceeded",
    ):
        read_arm_collection(
            _url(path),
            scope=ArmScope.from_arm_authority(arm),
            budget=ReadBudget.from_limits(arm),
            runner=_runner(
                [
                    {"nextLink": second, "value": []},
                    {"nextLink": None, "value": []},
                ],
                [],
            ),
        )


def test_collect_arm_payloads_reads_exact_app_revision_and_job_paths(
    continuation: dict[str, object],
) -> None:
    arm = _arm(continuation)
    package = {"arm": arm}
    payloads: list[object] = []
    for index in range(10):
        if index == 1 or index % 2 == 1 and index > 1:
            payloads.append({"nextLink": None, "value": []})
        else:
            payloads.append({"id": f"resource-{index}"})
    calls: list[list[str]] = []

    result = collect_arm_payloads(
        package,
        continuation,
        runner=_runner(payloads, calls),
    )

    assert len(calls) == 10
    assert result["application"] == {"id": "resource-0"}
    assert result["revisions"] == []
    assert set(result["jobs"]) == {
        "prepare",
        "seed",
        "session_maintenance",
        "storage_maintenance",
    }
    assert result["read_metrics"]["request_count"] == 10
    assert result["read_metrics"]["total_response_bytes"] > 0


def _live_env(contract: dict[str, object]) -> list[dict[str, object]]:
    expected_values = contract["expected_value_env"]
    rows: list[dict[str, object]] = []
    for name, binding in contract["environment_bindings"].items():
        if binding == "value":
            value = expected_values.get(name)
            if name == "APPLICATIONINSIGHTS_CONNECTION_STRING":
                value = (
                    "InstrumentationKey=11111111-1111-4111-8111-111111111111;"
                    "IngestionEndpoint=https://centralus-0.in.applicationinsights.azure.com/"
                )
            assert isinstance(value, str)
            rows.append({"name": name, "value": value})
        else:
            rows.append(
                {
                    "name": name,
                    "secretRef": binding.removeprefix("secretRef:"),
                }
            )
    return rows


def _live_payloads_from_desired(
    desired: dict[str, object], continuation: dict[str, object]
) -> dict[str, object]:
    target = continuation["target"]
    prefix = (
        f"/subscriptions/{target['subscription_id']}/resourceGroups/"
        f"{target['resource_group']}/providers/Microsoft.App"
    )
    application_contract = desired["application"]
    application_id = f"{prefix}/containerApps/{application_contract['resource_name']}"
    application = {
        "id": application_id,
        "name": application_contract["resource_name"],
        "properties": {
            "configuration": {
                "activeRevisionsMode": "Single",
                "ingress": {
                    **deepcopy(application_contract["ingress"]),
                    "fqdn": target["public_url"].removeprefix("https://"),
                },
                "secrets": [
                    {"name": name, "value": None}
                    for name in application_contract["secret_names"]
                ],
            },
            "environmentId": application_contract["environment_id"],
            "latestReadyRevisionName": application_contract["revision_name"],
            "latestRevisionName": application_contract["revision_name"],
            "provisioningState": "Succeeded",
            "template": {
                "containers": [
                    {
                        "args": None,
                        "command": None,
                        "env": _live_env(application_contract),
                        "image": application_contract["image"],
                        "name": application_contract["container_name"],
                        "probes": deepcopy(application_contract["probes"]),
                        "resources": deepcopy(application_contract["resources"]),
                    }
                ],
                "scale": {
                    **deepcopy(application_contract["scale"]),
                    "pollingInterval": None,
                },
            },
        },
        "systemData": {"createdByType": "User"},
    }
    revision_name = application_contract["revision_name"]
    revisions = [
        {
            "id": f"{application_id}/revisions/{revision_name}",
            "name": revision_name,
            "properties": {
                "active": True,
                "healthState": "Healthy",
                "provisioningState": "Provisioned",
                "replicas": 1,
            },
            "systemData": None,
        }
    ]
    jobs: dict[str, object] = {}
    for role, contract in desired["jobs"].items():
        configuration = {
            "eventStreamEndpoint": "azure-owned",
            "manualTriggerConfig": deepcopy(contract["manual_trigger_config"]),
            "replicaRetryLimit": contract["replica_retry_limit"],
            "replicaTimeout": contract["replica_timeout"],
            "scheduleTriggerConfig": deepcopy(contract["schedule_trigger_config"]),
            "secrets": [
                {"name": name, "value": ""} for name in contract["secret_names"]
            ],
            "triggerType": contract["trigger_type"],
        }
        jobs[role] = {
            "id": f"{prefix}/jobs/{contract['job_name']}",
            "name": contract["job_name"],
            "properties": {
                "configuration": configuration,
                "environmentId": application_contract["environment_id"],
                "provisioningState": "Succeeded",
                "template": {
                    "containers": [
                        {
                            "args": deepcopy(contract["arguments"]),
                            "command": deepcopy(contract["command"]),
                            "env": _live_env(contract),
                            "image": contract["image"],
                            "name": contract["container_name"],
                            "resources": deepcopy(contract["resources"]),
                        }
                    ]
                },
            },
            "systemData": {"lastModifiedByType": "User"},
        }
    return {
        "application": application,
        "executions": {role: [] for role in jobs},
        "jobs": jobs,
        "page_evidence": {},
        "read_metrics": {"request_count": 10, "total_response_bytes": 1000},
        "revisions": revisions,
    }


def _mutate_application(raw: dict[str, object], mutation: str) -> None:
    application = raw["application"]
    assert isinstance(application, dict)
    properties = application["properties"]
    assert isinstance(properties, dict)
    configuration = properties["configuration"]
    template = properties["template"]
    assert isinstance(configuration, dict)
    assert isinstance(template, dict)
    containers = template["containers"]
    assert isinstance(containers, list) and len(containers) == 1
    container = containers[0]
    assert isinstance(container, dict)
    if mutation == "application_image":
        container["image"] = "wrong"
    elif mutation == "application_runtime":
        container["command"] = ["wrong"]
    elif mutation == "application_probe":
        container["probes"] = []
    elif mutation == "application_resources":
        resources = container["resources"]
        assert isinstance(resources, dict)
        resources["cpu"] = 1
    elif mutation == "application_scale":
        scale = template["scale"]
        assert isinstance(scale, dict)
        scale["minReplicas"] = 0
    elif mutation == "application_traffic":
        ingress = configuration["ingress"]
        assert isinstance(ingress, dict)
        traffic = ingress["traffic"]
        assert isinstance(traffic, list) and len(traffic) == 1
        row = traffic[0]
        assert isinstance(row, dict)
        row["weight"] = 99
    elif mutation == "application_environment_id":
        properties["environmentId"] = "wrong"
    elif mutation == "application_revision_state":
        properties["latestRevisionName"] = "wrong"
    elif mutation == "application_env_name":
        environment = container["env"]
        assert isinstance(environment, list) and environment
        row = environment[0]
        assert isinstance(row, dict)
        row["name"] = "WRONG"
    elif mutation == "application_secret_ref":
        environment = container["env"]
        assert isinstance(environment, list)
        secret_row = next(row for row in environment if "secretRef" in row)
        assert isinstance(secret_row, dict)
        secret_row["secretRef"] = "wrong"
    elif mutation == "application_secret_name":
        secrets = configuration["secrets"]
        assert isinstance(secrets, list) and secrets
        secret = secrets[0]
        assert isinstance(secret, dict)
        secret["name"] = "wrong"
    else:
        raise AssertionError(f"unknown application mutation: {mutation}")


def _malform_application(raw: dict[str, object], family: str) -> None:
    application = raw["application"]
    assert isinstance(application, dict)
    properties = application["properties"]
    assert isinstance(properties, dict)
    configuration = properties["configuration"]
    template = properties["template"]
    assert isinstance(configuration, dict)
    assert isinstance(template, dict)
    containers = template["containers"]
    assert isinstance(containers, list) and len(containers) == 1
    container = containers[0]
    assert isinstance(container, dict)
    if family == "environment_binding":
        properties["environmentId"] = []
    elif family == "revision_state":
        properties["latestRevisionName"] = []
    elif family == "ingress_traffic":
        ingress = configuration["ingress"]
        assert isinstance(ingress, dict)
        ingress["targetPort"] = True
    elif family == "scale":
        scale = template["scale"]
        assert isinstance(scale, dict)
        scale["minReplicas"] = True
    elif family == "container_runtime":
        container["command"] = [1]
    elif family == "container_image":
        container["image"] = []
    elif family == "probe_contract":
        container["probes"] = "malformed-probe-shape"
    elif family == "resource_limits":
        resources = container["resources"]
        assert isinstance(resources, dict)
        resources["cpu"] = True
    elif family == "secret_reference_names":
        secrets = configuration["secrets"]
        assert isinstance(secrets, list) and secrets
        secret = secrets[0]
        assert isinstance(secret, dict)
        secret["name"] = []
    else:
        raise AssertionError(f"unknown application family: {family}")


def test_resource_projection_accepts_the_compiled_bicep_job_contract(
    continuation: dict[str, object], desired_projection: dict[str, object]
) -> None:
    raw = _live_payloads_from_desired(desired_projection, continuation)

    result = project_deployed_resources(raw, desired_projection, continuation)

    assert result["application"]["checks"] == {"desired_contract_match": True}
    assert result["application"]["resource_name"] == ("newcaostone-demo-app")
    assert "expected_value_env" not in result["application"]
    assert (
        result["application"]["environment_bindings"]["BIZPULSE_OPERATOR_PASSWORD_HASH"]
        == "secretRef:operator-password-hash"
    )
    assert "operator-password-hash" in result["application"]["secret_names"]
    for role in desired_projection["jobs"]:
        bindings = result["jobs"][role]["environment_bindings"]
        assert "BIZPULSE_ALLOWED_ORIGIN" in bindings
        assert "BIZPULSE_OPERATOR_PASSWORD_HASH" in bindings
        assert bindings["BIZPULSE_OPERATOR_PASSWORD_HASH"] == (
            "secretRef:operator-password-hash"
        )
        assert "operator-password-hash" in result["jobs"][role]["secret_names"]
        assert "expected_value_env" not in result["jobs"][role]


def test_resource_projection_ignores_only_azure_owned_fields(
    continuation: dict[str, object], desired_projection: dict[str, object]
) -> None:
    raw = _live_payloads_from_desired(desired_projection, continuation)
    baseline = project_deployed_resources(raw, desired_projection, continuation)
    raw["application"]["properties"]["outboundIpAddresses"] = ["192.0.2.1"]
    raw["application"]["properties"]["configuration"]["dapr"] = None
    raw["jobs"]["prepare"]["properties"]["template"]["initContainers"] = None

    assert project_deployed_resources(raw, desired_projection, continuation) == baseline


@pytest.mark.parametrize(
    ("mutation", "category"),
    (
        ("application_image", "container_image"),
        ("application_runtime", "container_runtime"),
        ("application_probe", "probe_contract"),
        ("application_resources", "resource_limits"),
        ("application_scale", "scale"),
        ("application_traffic", "ingress_traffic"),
        ("application_environment_id", "environment_binding"),
        ("application_revision_state", "revision_state"),
        ("application_env_name", "environment_binding"),
        ("application_secret_ref", "environment_binding"),
        ("application_secret_name", "secret_reference_names"),
    ),
)
def test_application_drift_maps_to_closed_safe_category(
    continuation: dict[str, object],
    desired_projection: dict[str, object],
    mutation: str,
    category: str,
) -> None:
    raw = _live_payloads_from_desired(desired_projection, continuation)
    _mutate_application(raw, mutation)

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_application_drift",
    ) as captured:
        project_deployed_resources(raw, desired_projection, continuation)

    assert captured.value.resource_role == "application"
    assert captured.value.mismatch_category == category


@pytest.mark.parametrize("malformed", ("container", "environment_row"))
def test_application_drift_unclassifiable_input_has_no_category_or_values(
    continuation: dict[str, object],
    desired_projection: dict[str, object],
    malformed: str,
) -> None:
    raw = _live_payloads_from_desired(desired_projection, continuation)
    application = raw["application"]
    assert isinstance(application, dict)
    properties = application["properties"]
    assert isinstance(properties, dict)
    template = properties["template"]
    assert isinstance(template, dict)
    if malformed == "container":
        template["containers"] = ["do-not-record-secret-value"]
    else:
        containers = template["containers"]
        assert isinstance(containers, list) and len(containers) == 1
        container = containers[0]
        assert isinstance(container, dict)
        container["env"] = [{"value": "https://do-not-record.example/path"}]

    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_application_drift",
    ) as captured:
        project_deployed_resources(raw, desired_projection, continuation)

    assert captured.value.mismatch_category is None
    assert "do-not-record-secret-value" not in str(captured.value)
    assert "https://do-not-record.example/path" not in str(captured.value)


@pytest.mark.parametrize(
    "family",
    (
        "environment_binding",
        "revision_state",
        "ingress_traffic",
        "scale",
        "container_runtime",
        "container_image",
        "probe_contract",
        "resource_limits",
        "secret_reference_names",
    ),
)
def test_malformed_application_family_has_no_mismatch_category(
    continuation: dict[str, object],
    desired_projection: dict[str, object],
    family: str,
) -> None:
    raw = _live_payloads_from_desired(desired_projection, continuation)
    _malform_application(raw, family)

    with pytest.raises(DeployedReleaseDiagnosticInvalid) as captured:
        project_deployed_resources(raw, desired_projection, continuation)

    assert str(captured.value) == "diagnostic_application_drift"
    assert captured.value.resource_role == "application"
    assert captured.value.mismatch_category is None


@pytest.mark.parametrize(
    ("mutation", "code", "role"),
    (
        ("application_image", "diagnostic_application_drift", "application"),
        ("application_env_name", "diagnostic_application_drift", "application"),
        ("application_secret_ref", "diagnostic_application_drift", "application"),
        ("application_revision", "diagnostic_revision_drift", "revision"),
        ("application_traffic", "diagnostic_application_drift", "application"),
        ("job_command", "diagnostic_job_drift", "prepare"),
        ("job_schedule", "diagnostic_job_drift", "session_maintenance"),
        ("job_timeout", "diagnostic_job_drift", "seed"),
        ("job_resources", "diagnostic_job_drift", "storage_maintenance"),
        ("job_secret_value", "diagnostic_job_drift", "prepare"),
    ),
)
def test_resource_drift_is_rejected_with_only_safe_role(
    continuation: dict[str, object],
    desired_projection: dict[str, object],
    mutation: str,
    code: str,
    role: str,
) -> None:
    raw = _live_payloads_from_desired(desired_projection, continuation)
    if mutation == "application_image":
        raw["application"]["properties"]["template"]["containers"][0]["image"] = "wrong"
    elif mutation == "application_env_name":
        raw["application"]["properties"]["template"]["containers"][0]["env"][0][
            "name"
        ] = "WRONG"
    elif mutation == "application_secret_ref":
        secret_row = next(
            row
            for row in raw["application"]["properties"]["template"]["containers"][0][
                "env"
            ]
            if "secretRef" in row
        )
        secret_row["secretRef"] = "wrong"
    elif mutation == "application_revision":
        raw["revisions"][0]["name"] = "wrong"
    elif mutation == "application_traffic":
        raw["application"]["properties"]["configuration"]["ingress"]["traffic"][0][
            "weight"
        ] = 99
    elif mutation == "job_command":
        raw["jobs"]["prepare"]["properties"]["template"]["containers"][0]["command"] = [
            "sh"
        ]
    elif mutation == "job_schedule":
        raw["jobs"]["session_maintenance"]["properties"]["configuration"][
            "scheduleTriggerConfig"
        ]["cronExpression"] = "0 0 * * *"
    elif mutation == "job_timeout":
        raw["jobs"]["seed"]["properties"]["configuration"]["replicaTimeout"] = 1
    elif mutation == "job_resources":
        raw["jobs"]["storage_maintenance"]["properties"]["template"]["containers"][0][
            "resources"
        ]["cpu"] = 1
    else:
        raw["jobs"]["prepare"]["properties"]["configuration"]["secrets"][0]["value"] = (
            "do-not-record"
        )

    with pytest.raises(DeployedReleaseDiagnosticInvalid, match=code) as captured:
        project_deployed_resources(raw, desired_projection, continuation)

    assert captured.value.resource_role == role
    assert "do-not-record" not in str(captured.value)


def _execution(
    name: str,
    status: str,
    start: str,
    end: str | None,
) -> dict[str, object]:
    return {
        "name": name,
        "properties": {
            "endTime": end,
            "startTime": start,
            "status": status,
        },
        "systemData": None,
    }


def test_older_failed_seed_is_execution_history_not_current_drift() -> None:
    result = evaluate_execution_history(
        "seed",
        [
            _execution(
                "newcaostone-demo-seed-8a8k7de",
                "Failed",
                "2026-08-16T20:00:00Z",
                "2026-08-16T20:01:00Z",
            ),
            _execution(
                "newcaostone-demo-seed-vhamoeo",
                "Succeeded",
                "2026-08-16T20:10:00Z",
                "2026-08-16T20:11:00Z",
            ),
        ],
        {"name": "newcaostone-demo-seed-vhamoeo", "status": "Succeeded"},
        continuation_recorded_at=parse_utc("2026-08-16T22:18:28Z"),
        observed_at=parse_utc("2026-08-16T23:30:00Z"),
        replica_timeout=1800,
    )

    assert result["bound"]["status"] == "Succeeded"
    assert result["historical"][0]["status"] == "Failed"
    assert result["later"] == []


@pytest.mark.parametrize(
    ("role", "additional", "timeout", "accepted"),
    (
        (
            "prepare",
            _execution(
                "prepare-newer",
                "Succeeded",
                "2026-08-16T20:20:00Z",
                "2026-08-16T20:21:00Z",
            ),
            900,
            False,
        ),
        (
            "seed",
            _execution(
                "seed-newer",
                "Succeeded",
                "2026-08-16T20:20:00Z",
                "2026-08-16T20:21:00Z",
            ),
            1800,
            False,
        ),
        (
            "seed",
            _execution(
                "seed-overlap",
                "Failed",
                "2026-08-16T20:09:00Z",
                "2026-08-16T20:10:30Z",
            ),
            1800,
            False,
        ),
        (
            "seed",
            _execution(
                "seed-unknown",
                "Unknown",
                "2026-08-16T20:00:00Z",
                "2026-08-16T20:01:00Z",
            ),
            1800,
            False,
        ),
        (
            "session_maintenance",
            _execution(
                "sessions-later-success",
                "Succeeded",
                "2026-08-16T20:20:00Z",
                "2026-08-16T20:21:00Z",
            ),
            300,
            True,
        ),
        (
            "storage_maintenance",
            _execution(
                "storage-later-failed",
                "Failed",
                "2026-08-16T20:20:00Z",
                "2026-08-16T20:21:00Z",
            ),
            600,
            False,
        ),
        (
            "session_maintenance",
            _execution(
                "sessions-running",
                "Running",
                "2026-08-16T23:24:00Z",
                None,
            ),
            300,
            True,
        ),
        (
            "session_maintenance",
            _execution(
                "sessions-over-age",
                "Processing",
                "2026-08-16T23:22:59Z",
                None,
            ),
            300,
            False,
        ),
    ),
)
def test_execution_history_applies_manual_and_scheduled_time_policy(
    role: str,
    additional: dict[str, object],
    timeout: int,
    accepted: bool,
) -> None:
    bound_name = f"{role}-bound"
    rows = [
        _execution(
            bound_name,
            "Succeeded",
            "2026-08-16T20:10:00Z",
            "2026-08-16T20:11:00Z",
        ),
        additional,
    ]
    arguments = {
        "continuation_recorded_at": parse_utc("2026-08-16T22:18:28Z"),
        "observed_at": parse_utc("2026-08-16T23:30:00Z"),
        "replica_timeout": timeout,
    }

    if accepted:
        result = evaluate_execution_history(
            role,
            rows,
            {"name": bound_name, "status": "Succeeded"},
            **arguments,
        )
        assert result["later"][0]["name"] == additional["name"]
    else:
        with pytest.raises(
            DeployedReleaseDiagnosticInvalid,
            match="diagnostic_execution_history_invalid",
        ):
            evaluate_execution_history(
                role,
                rows,
                {"name": bound_name, "status": "Succeeded"},
                **arguments,
            )


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_bound",
        "duplicate_name",
        "missing_timestamp",
        "undocumented_state",
    ),
)
def test_execution_history_rejects_incomplete_or_ambiguous_collection(
    mutation: str,
) -> None:
    bound = _execution(
        "seed-bound",
        "Succeeded",
        "2026-08-16T20:10:00Z",
        "2026-08-16T20:11:00Z",
    )
    rows = [bound]
    if mutation == "missing_bound":
        rows = []
    elif mutation == "duplicate_name":
        rows.append(deepcopy(bound))
    elif mutation == "missing_timestamp":
        bound["properties"]["endTime"] = None
    else:
        bound["properties"]["status"] = "Pending"

    expected_code = (
        "diagnostic_bound_execution_invalid"
        if mutation in {"missing_bound", "missing_timestamp"}
        else "diagnostic_execution_history_invalid"
    )
    with pytest.raises(DeployedReleaseDiagnosticInvalid, match=expected_code):
        evaluate_execution_history(
            "seed",
            rows,
            {"name": "seed-bound", "status": "Succeeded"},
            continuation_recorded_at=parse_utc("2026-08-16T22:18:28Z"),
            observed_at=parse_utc("2026-08-16T23:30:00Z"),
            replica_timeout=1800,
        )


def test_observation_is_exact_sanitized_and_evidence_bound(
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object],
    desired_projection: dict[str, object],
) -> None:
    raw = _live_payloads_from_desired(desired_projection, continuation)

    def page(digit: str) -> dict[str, object]:
        return {"byte_count": 100, "sha256": digit * 64}

    raw["page_evidence"] = {
        "application": {
            "collection_page_count": 0,
            "collection_pages": [],
            "complete": True,
            "resource_page_count": 1,
            "resource_pages": [page("1")],
        },
        "revision": {
            "collection_page_count": 1,
            "collection_pages": [page("2")],
            "complete": True,
            "resource_page_count": 0,
            "resource_pages": [],
        },
    }
    for index, role in enumerate(desired_projection["jobs"], start=3):
        raw["page_evidence"][role] = {
            "collection_page_count": 1,
            "collection_pages": [page(format(index + 4, "x"))],
            "complete": True,
            "resource_page_count": 1,
            "resource_pages": [page(format(index, "x"))],
        }
    for index, role in enumerate(desired_projection["jobs"]):
        bound = continuation["executions"][role]
        raw["executions"][role] = [
            _execution(
                bound["name"],
                "Succeeded",
                f"2026-08-16T20:{index + 10:02d}:00Z",
                f"2026-08-16T20:{index + 10:02d}:30Z",
            )
        ]
    monkeypatch.setattr(
        "scripts.observe_deployed_release_state.collect_arm_payloads",
        lambda _package, _continuation, *, runner, on_completed_read=None: raw,
    )
    package = {
        "authorization_id": "11111111-1111-4111-8111-111111111111",
        "continuation": {
            "reference": (
                "release/incidents/2026-08-16-recovery-v4-deployed-continuation.json"
            ),
            "sha256": CONTINUATION_SHA256,
        },
        "desired_projection_sha256": "2" * 64,
        "repository": {
            "branch": "codex/integrated-viewer-ai-anti-drift",
            "head_sha": "3" * 40,
            "tracked_clean_required": True,
            "tree_sha": "4" * 40,
        },
        "toolchain": {
            "azure_cli": "2.89.0",
            "bicep": "0.46.1",
            "containerapp_extension_observed": "1.3.0b4",
            "python": "Python 3.12.10",
        },
    }

    observation = observe_deployed_release_state(
        package,
        continuation,
        desired_projection,
        observed_at=parse_utc("2026-08-16T23:30:00Z"),
        package_sha256="5" * 64,
        runner=lambda *_args, **_kwargs: None,
    )

    assert set(observation) == {
        "authorization_id",
        "checks",
        "claim",
        "continuation",
        "desired_projection_sha256",
        "executions",
        "observed_at",
        "package_sha256",
        "page_evidence",
        "repository",
        "resources",
        "schema_version",
        "toolchain",
    }
    assert observation["checks"] == {
        "bound_executions_match": True,
        "desired_contract_match": True,
        "execution_history_acceptable": True,
        "pagination_complete": True,
    }
    assert observation["claim"] == "read_only_deployed_state_observed"

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return {
                *(str(key).lower() for key in value),
                *(nested for item in value.values() for nested in keys(item)),
            }
        if isinstance(value, list):
            return {nested for item in value for nested in keys(item)}
        return set()

    assert keys(observation).isdisjoint(
        {
            "value",
            "raw",
            "stdout",
            "stderr",
            "token",
            "password",
            "connection_string",
        }
    )
