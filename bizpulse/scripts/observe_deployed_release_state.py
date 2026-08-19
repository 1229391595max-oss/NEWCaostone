#!/usr/bin/env python3
"""Collect a bounded, value-safe ARM view of the deployed release."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from scripts.deployed_release_diagnostic_contract import (
    DeployedReleaseDiagnosticInvalid,
    canonical_sha256,
    evaluate_execution_history,
    parse_utc,
    unique_object,
    utc_text,
)
from scripts.secret_boundary import SECRET_PATTERN


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ENVIRONMENT_KEYS = frozenset(
    {
        "AZURE_CONFIG_DIR",
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "TMPDIR",
    }
)
ROLE_TO_TARGET_KEY = {
    "prepare": "prepare_job",
    "seed": "seed_job",
    "session_maintenance": "session_maintenance_job",
    "storage_maintenance": "storage_maintenance_job",
}
OBSERVATION_SCHEMA = "newcaostone.deployed-release-diagnostic-observation.v1"
FORBIDDEN_OBSERVATION_KEYS = frozenset(
    {"value", "raw", "stdout", "stderr", "token", "password", "connection_string"}
)


def _invalid(
    code: str, *, stage: str = "local", role: str = "local"
) -> DeployedReleaseDiagnosticInvalid:
    return DeployedReleaseDiagnosticInvalid(code, stage, role)


@dataclass(frozen=True, slots=True)
class ArmPage:
    payload: object
    sha256: str
    byte_count: int


@dataclass(frozen=True, slots=True)
class ArmScope:
    host: str
    api_version: str
    allowed_methods: frozenset[str]
    allowed_paths: frozenset[str]

    @classmethod
    def from_arm_authority(cls, authority: Mapping[str, Any]) -> ArmScope:
        try:
            methods = authority["allowed_http_methods"]
            paths = authority["allowed_resource_paths"]
            host = authority["host"]
            api_version = authority["api_version"]
        except (KeyError, TypeError) as error:
            raise _invalid("diagnostic_arm_scope_invalid") from error
        if (
            host != "management.azure.com"
            or api_version != "2024-03-01"
            or methods != ["GET"]
            or not isinstance(paths, list)
            or not paths
            or len(paths) != len(set(paths))
            or any(
                not isinstance(path, str)
                or not path.startswith("/subscriptions/")
                or "?" in path
                or "#" in path
                for path in paths
            )
        ):
            raise _invalid("diagnostic_arm_scope_invalid")
        return cls(
            host=host,
            api_version=api_version,
            allowed_methods=frozenset(method.lower() for method in methods),
            allowed_paths=frozenset(paths),
        )

    def validate_request(
        self,
        method: str,
        url: str,
        *,
        expected_path: str | None = None,
        pagination: bool = False,
        stage: str = "local",
        role: str = "local",
    ) -> None:
        code = (
            "diagnostic_pagination_invalid"
            if pagination
            else "diagnostic_arm_scope_invalid"
        )
        if (
            not isinstance(method, str)
            or method.lower() not in self.allowed_methods
            or not isinstance(url, str)
            or not 1 <= len(url) <= 4096
        ):
            raise _invalid(code, stage=stage, role=role)
        try:
            parsed = urlsplit(url)
            pairs = parse_qsl(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=True,
            )
            port = parsed.port
        except (TypeError, ValueError) as error:
            raise _invalid(code, stage=stage, role=role) from error
        if (
            parsed.scheme != "https"
            or parsed.hostname != self.host
            or parsed.netloc != self.host
            or port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.path not in self.allowed_paths
            or (expected_path is not None and parsed.path != expected_path)
        ):
            raise _invalid(code, stage=stage, role=role)
        normalized: dict[str, str] = {}
        for key, value in pairs:
            normalized_key = key.lower()
            if normalized_key in normalized:
                raise _invalid(code, stage=stage, role=role)
            normalized[normalized_key] = value
        if normalized.get("api-version") != self.api_version:
            raise _invalid(code, stage=stage, role=role)
        token_keys = {"skiptoken", "$skiptoken"} & set(normalized)
        if pagination:
            if len(token_keys) != 1 or set(normalized) != {"api-version", *token_keys}:
                raise _invalid(code, stage=stage, role=role)
            token = normalized[next(iter(token_keys))]
            if (
                not token
                or len(token) > 2048
                or any(ord(character) < 0x20 for character in token)
            ):
                raise _invalid(code, stage=stage, role=role)
        elif set(normalized) != {"api-version"}:
            raise _invalid(code, stage=stage, role=role)


@dataclass(slots=True)
class ReadBudget:
    max_page_bytes: int
    max_pages_per_collection: int
    max_total_requests: int
    max_total_response_bytes: int
    request_count: int = 0
    total_response_bytes: int = 0

    @classmethod
    def from_limits(cls, limits: Mapping[str, Any]) -> ReadBudget:
        try:
            values = {
                key: limits[key]
                for key in (
                    "max_page_bytes",
                    "max_pages_per_collection",
                    "max_total_requests",
                    "max_total_response_bytes",
                )
            }
        except (KeyError, TypeError) as error:
            raise _invalid("diagnostic_pagination_limit_exceeded") from error
        if any(type(value) is not int or value <= 0 for value in values.values()):
            raise _invalid("diagnostic_pagination_limit_exceeded")
        return cls(**values)

    def reserve_request(self, *, stage: str = "local", role: str = "local") -> None:
        if self.request_count >= self.max_total_requests:
            raise _invalid(
                "diagnostic_pagination_limit_exceeded", stage=stage, role=role
            )
        self.request_count += 1

    def record_bytes(
        self, byte_count: int, *, stage: str = "local", role: str = "local"
    ) -> None:
        if (
            byte_count > self.max_page_bytes
            or self.total_response_bytes + byte_count > self.max_total_response_bytes
        ):
            raise _invalid(
                "diagnostic_pagination_limit_exceeded", stage=stage, role=role
            )
        self.total_response_bytes += byte_count


def read_arm_page(
    url: str,
    *,
    limits: Mapping[str, Any],
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    stage: str = "local",
    role: str = "local",
) -> ArmPage:
    scope = ArmScope.from_arm_authority(limits)
    try:
        parsed_url = urlsplit(url)
        query_keys = {
            key.lower()
            for key, _value in parse_qsl(
                parsed_url.query, keep_blank_values=True, strict_parsing=True
            )
        }
    except (TypeError, ValueError) as error:
        raise _invalid(
            "diagnostic_arm_scope_invalid", stage=stage, role=role
        ) from error
    pagination = bool({"skiptoken", "$skiptoken"} & query_keys)
    scope.validate_request(
        "get",
        url,
        expected_path=parsed_url.path if pagination else None,
        pagination=pagination,
        stage=stage,
        role=role,
    )
    timeout = limits.get("request_timeout_seconds")
    max_page_bytes = limits.get("max_page_bytes")
    if (
        type(timeout) is not int
        or timeout != 30
        or type(max_page_bytes) is not int
        or max_page_bytes <= 0
    ):
        raise _invalid("diagnostic_arm_scope_invalid", stage=stage, role=role)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in ALLOWED_ENVIRONMENT_KEYS
    }
    command = [
        "az",
        "rest",
        "--method",
        "get",
        "--url",
        url,
        "--only-show-errors",
        "--output",
        "json",
    ]
    try:
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=False,
            timeout=30,
            cwd=PROJECT_ROOT,
            env=environment,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise _invalid(
            "diagnostic_arm_request_failed", stage=stage, role=role
        ) from error
    if completed.returncode != 0 or not isinstance(completed.stdout, bytes):
        raise _invalid("diagnostic_arm_request_failed", stage=stage, role=role)
    raw = completed.stdout
    byte_count = len(raw)
    if byte_count > max_page_bytes:
        raise _invalid("diagnostic_pagination_limit_exceeded", stage=stage, role=role)
    try:
        decoded = raw.decode("utf-8")
        if SECRET_PATTERN.search(decoded):
            raise ValueError("diagnostic_secret_in_response")
        payload = json.loads(decoded, object_pairs_hook=unique_object)
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise _invalid(
            "diagnostic_arm_response_invalid", stage=stage, role=role
        ) from error
    return ArmPage(
        payload=payload,
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_count=byte_count,
    )


def read_arm_collection(
    url: str,
    *,
    scope: ArmScope,
    budget: ReadBudget,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    limits: Mapping[str, Any] | None = None,
    stage: str = "local",
    role: str = "local",
) -> Sequence[ArmPage]:
    parsed = urlsplit(url)
    initial_path = parsed.path
    scope.validate_request(
        "get", url, expected_path=initial_path, stage=stage, role=role
    )
    effective_limits: Mapping[str, Any] = limits or {
        "allowed_http_methods": ["GET"],
        "allowed_resource_paths": sorted(scope.allowed_paths),
        "api_version": scope.api_version,
        "host": scope.host,
        "max_page_bytes": budget.max_page_bytes,
        "request_timeout_seconds": 30,
    }
    pages: list[ArmPage] = []
    current = url
    while True:
        budget.reserve_request(stage=stage, role=role)
        page = read_arm_page(
            current,
            limits=effective_limits,
            runner=runner,
            stage=stage,
            role=role,
        )
        budget.record_bytes(page.byte_count, stage=stage, role=role)
        if not isinstance(page.payload, Mapping) or "value" not in page.payload:
            raise _invalid("diagnostic_arm_response_invalid", stage=stage, role=role)
        rows = page.payload["value"]
        next_link = page.payload.get("nextLink")
        if not isinstance(rows, list) or not (
            next_link is None or (isinstance(next_link, str) and bool(next_link))
        ):
            raise _invalid("diagnostic_arm_response_invalid", stage=stage, role=role)
        pages.append(page)
        if next_link is None:
            return tuple(pages)
        if len(pages) >= budget.max_pages_per_collection:
            raise _invalid(
                "diagnostic_pagination_limit_exceeded", stage=stage, role=role
            )
        scope.validate_request(
            "get",
            next_link,
            expected_path=initial_path,
            pagination=True,
            stage=stage,
            role=role,
        )
        current = next_link


def _resource_page(
    url: str,
    *,
    scope: ArmScope,
    budget: ReadBudget,
    limits: Mapping[str, Any],
    runner: Callable[..., subprocess.CompletedProcess[bytes]],
    stage: str,
    role: str,
) -> ArmPage:
    scope.validate_request("get", url, stage=stage, role=role)
    budget.reserve_request(stage=stage, role=role)
    page = read_arm_page(url, limits=limits, runner=runner, stage=stage, role=role)
    budget.record_bytes(page.byte_count, stage=stage, role=role)
    if not isinstance(page.payload, Mapping):
        raise _invalid("diagnostic_arm_response_invalid", stage=stage, role=role)
    return page


def _page_metadata(pages: Sequence[ArmPage]) -> list[dict[str, Any]]:
    return [{"byte_count": page.byte_count, "sha256": page.sha256} for page in pages]


def collect_arm_payloads(
    package: Mapping[str, Any],
    continuation: Mapping[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    on_completed_read: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    try:
        arm = package["arm"]
        target = continuation["target"]
    except (KeyError, TypeError) as error:
        raise _invalid("diagnostic_arm_scope_invalid") from error
    if not isinstance(arm, Mapping) or not isinstance(target, Mapping):
        raise _invalid("diagnostic_arm_scope_invalid")
    scope = ArmScope.from_arm_authority(arm)
    budget = ReadBudget.from_limits(arm)
    prefix = (
        f"/subscriptions/{target['subscription_id']}/resourceGroups/"
        f"{target['resource_group']}/providers/Microsoft.App"
    )

    def url(path: str) -> str:
        return f"https://{scope.host}{path}?api-version={scope.api_version}"

    application_path = f"{prefix}/containerApps/{target['application']}"
    application_page = _resource_page(
        url(application_path),
        scope=scope,
        budget=budget,
        limits=arm,
        runner=runner,
        stage="application",
        role="application",
    )
    if on_completed_read is not None:
        on_completed_read("application")
    revision_pages = read_arm_collection(
        url(f"{application_path}/revisions"),
        scope=scope,
        budget=budget,
        limits=arm,
        runner=runner,
        stage="revision",
        role="revision",
    )
    if on_completed_read is not None:
        on_completed_read("revision")
    revisions = [row for page in revision_pages for row in page.payload["value"]]
    jobs: dict[str, object] = {}
    executions: dict[str, list[object]] = {}
    page_evidence: dict[str, dict[str, Any]] = {
        "application": {
            "collection_page_count": 0,
            "collection_pages": [],
            "complete": True,
            "resource_page_count": 1,
            "resource_pages": _page_metadata((application_page,)),
        },
        "revision": {
            "collection_page_count": len(revision_pages),
            "collection_pages": _page_metadata(revision_pages),
            "complete": True,
            "resource_page_count": 0,
            "resource_pages": [],
        },
    }
    for role, target_key in ROLE_TO_TARGET_KEY.items():
        job_path = f"{prefix}/jobs/{target[target_key]}"
        job_page = _resource_page(
            url(job_path),
            scope=scope,
            budget=budget,
            limits=arm,
            runner=runner,
            stage="job",
            role=role,
        )
        execution_pages = read_arm_collection(
            url(f"{job_path}/executions"),
            scope=scope,
            budget=budget,
            limits=arm,
            runner=runner,
            stage="execution",
            role=role,
        )
        if on_completed_read is not None:
            on_completed_read(role)
        jobs[role] = job_page.payload
        executions[role] = [
            row for page in execution_pages for row in page.payload["value"]
        ]
        page_evidence[role] = {
            "collection_page_count": len(execution_pages),
            "collection_pages": _page_metadata(execution_pages),
            "complete": True,
            "resource_page_count": 1,
            "resource_pages": _page_metadata((job_page,)),
        }
    return {
        "application": application_page.payload,
        "executions": executions,
        "jobs": jobs,
        "page_evidence": page_evidence,
        "read_metrics": {
            "request_count": budget.request_count,
            "total_response_bytes": budget.total_response_bytes,
        },
        "revisions": revisions,
    }


def _resource_invalid(
    code: str,
    stage: str,
    role: str,
    *,
    mismatch_category: str | None = None,
) -> DeployedReleaseDiagnosticInvalid:
    return DeployedReleaseDiagnosticInvalid(code, stage, role, mismatch_category)


def _application_drift(
    mismatch_category: str | None = None,
) -> DeployedReleaseDiagnosticInvalid:
    return _resource_invalid(
        "diagnostic_application_drift",
        "application",
        "application",
        mismatch_category=mismatch_category,
    )


def _has_expected_shape(expected: object, remote: object) -> bool:
    if isinstance(expected, Mapping):
        return isinstance(remote, Mapping) and all(
            key in remote and _has_expected_shape(value, remote[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(remote, list):
            return False
        if not expected:
            return not remote
        return all(
            _has_expected_shape(expected[min(index, len(expected) - 1)], value)
            for index, value in enumerate(remote)
        )
    return type(remote) is type(expected)


def _live_container(
    payload: Mapping[str, Any], *, code: str, stage: str, role: str
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    try:
        properties = payload["properties"]
        template = properties["template"]
        containers = template["containers"]
    except (KeyError, TypeError) as error:
        raise _resource_invalid(code, stage, role) from error
    if (
        not isinstance(properties, Mapping)
        or not isinstance(template, Mapping)
        or not isinstance(containers, list)
        or len(containers) != 1
        or not isinstance(containers[0], Mapping)
    ):
        raise _resource_invalid(code, stage, role)
    return properties, template, containers[0]


def _live_environment(
    container: Mapping[str, Any], *, code: str, stage: str, role: str
) -> tuple[dict[str, str], dict[str, str]]:
    rows = container.get("env")
    if not isinstance(rows, list):
        raise _resource_invalid(code, stage, role)
    bindings: dict[str, str] = {}
    values: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping) or set(row) not in (
            {"name", "value"},
            {"name", "secretRef"},
        ):
            raise _resource_invalid(code, stage, role)
        name = row.get("name")
        if not isinstance(name, str) or not name or name in bindings:
            raise _resource_invalid(code, stage, role)
        if "secretRef" in row:
            reference = row["secretRef"]
            if not isinstance(reference, str) or not reference:
                raise _resource_invalid(code, stage, role)
            bindings[name] = f"secretRef:{reference}"
        else:
            value = row["value"]
            if not isinstance(value, str):
                raise _resource_invalid(code, stage, role)
            bindings[name] = "value"
            values[name] = value
    return bindings, values


def _live_secret_names(
    configuration: Mapping[str, Any], *, code: str, stage: str, role: str
) -> list[str]:
    rows = configuration.get("secrets")
    if not isinstance(rows, list):
        raise _resource_invalid(code, stage, role)
    names: set[str] = set()
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or not {"name"} <= set(row) <= {"name", "value"}
            or not isinstance(row.get("name"), str)
            or row["name"] in names
            or row.get("value") not in (None, "")
        ):
            raise _resource_invalid(code, stage, role)
        names.add(row["name"])
    return sorted(names)


def _environment_matches(
    container: Mapping[str, Any],
    desired: Mapping[str, Any],
    *,
    code: str,
    stage: str,
    role: str,
    application: bool = False,
    mismatch_category: str | None = None,
) -> dict[str, str]:
    bindings, values = _live_environment(container, code=code, stage=stage, role=role)
    desired_bindings = desired.get("environment_bindings")
    expected_values = desired.get("expected_value_env")
    if (
        not isinstance(desired_bindings, Mapping)
        or not isinstance(expected_values, Mapping)
        or bindings != desired_bindings
        or any(values.get(name) != value for name, value in expected_values.items())
    ):
        raise _resource_invalid(
            code, stage, role, mismatch_category=mismatch_category
        )
    expected_value_names = set(expected_values)
    if application:
        insights = values.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
        if (
            not isinstance(insights, str)
            or not insights.startswith("InstrumentationKey=")
            or "IngestionEndpoint=https://" not in insights
            or "\n" in insights
            or len(insights) > 4096
        ):
            raise _resource_invalid(
                code, stage, role, mismatch_category=mismatch_category
            )
        expected_value_names.add("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if set(values) != expected_value_names:
        raise _resource_invalid(
            code, stage, role, mismatch_category=mismatch_category
        )
    return dict(sorted(bindings.items()))


def _canonical_prefix(continuation: Mapping[str, Any]) -> str:
    try:
        target = continuation["target"]
        return (
            f"/subscriptions/{target['subscription_id']}/resourceGroups/"
            f"{target['resource_group']}/providers/Microsoft.App"
        )
    except (KeyError, TypeError) as error:
        raise _resource_invalid(
            "diagnostic_application_drift", "application", "application"
        ) from error


def _project_revision(
    rows: object,
    desired: Mapping[str, Any],
    *,
    application_id: str,
) -> dict[str, Any]:
    code = "diagnostic_revision_drift"
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise _resource_invalid(code, "revision", "revision")
    revision_name = desired["revision_name"]
    candidates = [row for row in rows if row.get("name") == revision_name]
    active = [
        row
        for row in rows
        if isinstance(row.get("properties"), Mapping)
        and row["properties"].get("active") is True
    ]
    if len(candidates) != 1 or active != candidates:
        raise _resource_invalid(code, "revision", "revision")
    candidate = candidates[0]
    properties = candidate.get("properties")
    if (
        not isinstance(properties, Mapping)
        or candidate.get("id") != f"{application_id}/revisions/{revision_name}"
        or properties.get("active") is not True
        or properties.get("healthState") != "Healthy"
        or properties.get("provisioningState") != "Provisioned"
        or type(properties.get("replicas")) is not int
        or properties["replicas"] < 1
    ):
        raise _resource_invalid(code, "revision", "revision")
    return {
        "active": True,
        "checks": {"desired_contract_match": True},
        "name": revision_name,
        "replicas": properties["replicas"],
        "resource_id": f"{application_id}/revisions/{revision_name}",
    }


def _project_application(
    payload: object,
    revisions: object,
    desired: Mapping[str, Any],
    continuation: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    code = "diagnostic_application_drift"
    stage = "application"
    role = "application"
    if not isinstance(payload, Mapping):
        raise _resource_invalid(code, stage, role)
    properties, template, container = _live_container(
        payload, code=code, stage=stage, role=role
    )
    try:
        configuration = properties["configuration"]
        ingress = configuration["ingress"]
        scale = template["scale"]
        target = continuation["target"]
    except (KeyError, TypeError) as error:
        raise _resource_invalid(code, stage, role) from error
    if not all(
        isinstance(item, Mapping) for item in (configuration, ingress, scale, target)
    ):
        raise _resource_invalid(code, stage, role)
    try:
        application_id = (
            f"{_canonical_prefix(continuation)}/containerApps/{desired['resource_name']}"
        )
        expected_ingress = desired["ingress"]
        expected_fqdn = target["public_url"].removeprefix("https://")
    except (KeyError, TypeError, AttributeError) as error:
        raise _application_drift() from error
    if (
        payload.get("id") != application_id
        or payload.get("name") != desired["resource_name"]
        or properties.get("provisioningState") != "Succeeded"
    ):
        raise _application_drift()
    if not isinstance(properties.get("environmentId"), str):
        raise _application_drift()
    if properties.get("environmentId") != desired["environment_id"]:
        raise _application_drift("environment_binding")
    bindings = _environment_matches(
        container,
        desired,
        code=code,
        stage=stage,
        role=role,
        application=True,
        mismatch_category="environment_binding",
    )
    if not all(
        isinstance(value, str)
        for value in (
            properties.get("latestRevisionName"),
            properties.get("latestReadyRevisionName"),
            configuration.get("activeRevisionsMode"),
        )
    ):
        raise _application_drift()
    if (
        properties.get("latestRevisionName") != desired["revision_name"]
        or properties.get("latestReadyRevisionName") != desired["revision_name"]
        or configuration.get("activeRevisionsMode") != "Single"
    ):
        raise _application_drift("revision_state")
    if (
        not _has_expected_shape(expected_ingress, ingress)
        or not isinstance(ingress.get("fqdn"), str)
    ):
        raise _application_drift()
    if (
        any(ingress.get(key) != value for key, value in expected_ingress.items())
        or ingress.get("fqdn") != expected_fqdn
    ):
        raise _application_drift("ingress_traffic")
    expected_scale = desired["scale"]
    if not isinstance(expected_scale, Mapping) or any(
        type(scale.get(key)) is not int for key in ("minReplicas", "maxReplicas")
    ):
        raise _application_drift()
    if (
        scale.get("minReplicas") != expected_scale["minReplicas"]
        or scale.get("maxReplicas") != expected_scale["maxReplicas"]
    ):
        raise _application_drift("scale")
    command = container.get("command")
    arguments = container.get("args")
    if (
        not isinstance(container.get("name"), str)
        or not (
            command is None
            or isinstance(command, list)
            and all(isinstance(value, str) for value in command)
        )
        or not (
            arguments is None
            or isinstance(arguments, list)
            and all(isinstance(value, str) for value in arguments)
        )
    ):
        raise _application_drift()
    if (
        container.get("name") != desired["container_name"]
        or command not in (None, [])
        or arguments not in (None, [])
    ):
        raise _application_drift("container_runtime")
    if not isinstance(container.get("image"), str):
        raise _application_drift()
    if container.get("image") != desired["image"]:
        raise _application_drift("container_image")
    if not _has_expected_shape(desired["probes"], container.get("probes")):
        raise _application_drift()
    if container.get("probes") != desired["probes"]:
        raise _application_drift("probe_contract")
    expected_resources = desired["resources"]
    resources = container.get("resources")
    if (
        not isinstance(expected_resources, Mapping)
        or not isinstance(resources, Mapping)
        or any(key not in resources for key in expected_resources)
        or not (
            type(resources.get("cpu")) in (int, float)
            and type(expected_resources.get("cpu")) in (int, float)
        )
        or any(
            not _has_expected_shape(value, resources[key])
            for key, value in expected_resources.items()
            if key != "cpu"
        )
    ):
        raise _application_drift()
    if resources != expected_resources:
        raise _application_drift("resource_limits")
    if (
        _live_secret_names(configuration, code=code, stage=stage, role=role)
        != desired["secret_names"]
    ):
        raise _application_drift("secret_reference_names")
    revision = _project_revision(revisions, desired, application_id=application_id)
    return (
        {
            "checks": {"desired_contract_match": True},
            "container": {
                "image": desired["image"],
                "name": desired["container_name"],
            },
            "environment_bindings": bindings,
            "fqdn": expected_fqdn,
            "resource_id": application_id,
            "resource_name": desired["resource_name"],
            "revision": {
                "latest": desired["revision_name"],
                "latest_ready": desired["revision_name"],
            },
            "scale": dict(desired["scale"]),
            "secret_names": list(desired["secret_names"]),
            "traffic": expected_ingress["traffic"],
        },
        revision,
    )


def _project_job(
    role: str,
    payload: object,
    desired: Mapping[str, Any],
    application: Mapping[str, Any],
    continuation: Mapping[str, Any],
) -> dict[str, Any]:
    code = "diagnostic_job_drift"
    if role not in ROLE_TO_TARGET_KEY or not isinstance(payload, Mapping):
        raise _resource_invalid(code, "job", "local")
    properties, _template, container = _live_container(
        payload, code=code, stage="job", role=role
    )
    configuration = properties.get("configuration")
    if not isinstance(configuration, Mapping):
        raise _resource_invalid(code, "job", role)
    resource_id = f"{_canonical_prefix(continuation)}/jobs/{desired['job_name']}"
    if (
        payload.get("id") != resource_id
        or payload.get("name") != desired["job_name"]
        or properties.get("provisioningState") != "Succeeded"
        or properties.get("environmentId") != application["environment_id"]
        or configuration.get("triggerType") != desired["trigger_type"]
        or configuration.get("replicaTimeout") != desired["replica_timeout"]
        or configuration.get("replicaRetryLimit") != desired["replica_retry_limit"]
        or configuration.get("manualTriggerConfig") != desired["manual_trigger_config"]
        or configuration.get("scheduleTriggerConfig")
        != desired["schedule_trigger_config"]
        or _live_secret_names(configuration, code=code, stage="job", role=role)
        != desired["secret_names"]
        or container.get("name") != desired["container_name"]
        or container.get("image") != desired["image"]
        or container.get("command") != desired["command"]
        or container.get("args") != desired["arguments"]
        or container.get("resources") != desired["resources"]
    ):
        raise _resource_invalid(code, "job", role)
    bindings = _environment_matches(
        container,
        desired,
        code=code,
        stage="job",
        role=role,
    )
    return {
        "checks": {"desired_contract_match": True},
        "container": {
            "image": desired["image"],
            "name": desired["container_name"],
        },
        "arguments": list(desired["arguments"]),
        "command": list(desired["command"]),
        "environment_bindings": bindings,
        "manual_trigger_config": desired["manual_trigger_config"],
        "replica_retry_limit": desired["replica_retry_limit"],
        "replica_timeout": desired["replica_timeout"],
        "resource_id": resource_id,
        "resource_name": desired["job_name"],
        "resources": dict(desired["resources"]),
        "schedule_trigger_config": desired["schedule_trigger_config"],
        "secret_names": list(desired["secret_names"]),
        "trigger_type": desired["trigger_type"],
    }


def project_deployed_resources(
    raw: Mapping[str, Any],
    desired: Mapping[str, Any],
    continuation: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        desired_application = desired["application"]
        desired_jobs = desired["jobs"]
        raw_jobs = raw["jobs"]
    except (KeyError, TypeError) as error:
        raise _resource_invalid(
            "diagnostic_application_drift", "application", "application"
        ) from error
    if not all(
        isinstance(item, Mapping)
        for item in (desired_application, desired_jobs, raw_jobs)
    ):
        raise _resource_invalid(
            "diagnostic_application_drift", "application", "application"
        )
    application, revision = _project_application(
        raw.get("application"),
        raw.get("revisions"),
        desired_application,
        continuation,
    )
    if set(raw_jobs) != set(desired_jobs) or set(desired_jobs) != set(
        ROLE_TO_TARGET_KEY
    ):
        raise _resource_invalid("diagnostic_job_drift", "job", "local")
    jobs = {
        role: _project_job(
            role,
            raw_jobs[role],
            desired_jobs[role],
            desired_application,
            continuation,
        )
        for role in ROLE_TO_TARGET_KEY
    }
    return {"application": application, "jobs": jobs, "revision": revision}


def _safe_page_evidence(raw: Mapping[str, Any]) -> dict[str, Any]:
    evidence = raw.get("page_evidence")
    metrics = raw.get("read_metrics")
    roles = {"application", "revision", *ROLE_TO_TARGET_KEY}
    if (
        not isinstance(evidence, Mapping)
        or set(evidence) != roles
        or not isinstance(metrics, Mapping)
        or set(metrics) != {"request_count", "total_response_bytes"}
    ):
        raise _invalid(
            "diagnostic_arm_response_invalid", stage="observation", role="local"
        )
    safe_roles: dict[str, Any] = {}
    observed_request_count = 0
    observed_bytes = 0
    for role in sorted(roles):
        record = evidence[role]
        if not isinstance(record, Mapping) or set(record) != {
            "collection_page_count",
            "collection_pages",
            "complete",
            "resource_page_count",
            "resource_pages",
        }:
            raise _invalid(
                "diagnostic_arm_response_invalid",
                stage="observation",
                role="local",
            )
        resource_pages = record["resource_pages"]
        collection_pages = record["collection_pages"]
        expected_resource_count = 1 if role != "revision" else 0
        expected_collection_minimum = 0 if role == "application" else 1
        if (
            record["complete"] is not True
            or not isinstance(resource_pages, list)
            or not isinstance(collection_pages, list)
            or record["resource_page_count"] != len(resource_pages)
            or record["collection_page_count"] != len(collection_pages)
            or len(resource_pages) != expected_resource_count
            or len(collection_pages) < expected_collection_minimum
        ):
            raise _invalid(
                "diagnostic_arm_response_invalid",
                stage="observation",
                role="local",
            )
        safe_pages: list[dict[str, Any]] = []
        for page in [*resource_pages, *collection_pages]:
            if (
                not isinstance(page, Mapping)
                or set(page) != {"byte_count", "sha256"}
                or type(page["byte_count"]) is not int
                or page["byte_count"] <= 0
                or not isinstance(page["sha256"], str)
                or len(page["sha256"]) != 64
                or any(
                    character not in "0123456789abcdef" for character in page["sha256"]
                )
            ):
                raise _invalid(
                    "diagnostic_arm_response_invalid",
                    stage="observation",
                    role="local",
                )
            safe_pages.append(dict(page))
            observed_bytes += page["byte_count"]
        observed_request_count += len(safe_pages)
        safe_roles[role] = {
            "collection_page_count": len(collection_pages),
            "collection_pages": [dict(page) for page in collection_pages],
            "complete": True,
            "resource_page_count": len(resource_pages),
            "resource_pages": [dict(page) for page in resource_pages],
        }
    if (
        metrics.get("request_count") != observed_request_count
        or metrics.get("total_response_bytes") != observed_bytes
    ):
        raise _invalid(
            "diagnostic_arm_response_invalid", stage="observation", role="local"
        )
    return {
        "request_count": observed_request_count,
        "roles": safe_roles,
        "total_response_bytes": observed_bytes,
    }


def _contains_forbidden_observation_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower() in FORBIDDEN_OBSERVATION_KEYS
            or _contains_forbidden_observation_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_observation_key(item) for item in value)
    return False


def observe_deployed_release_state(
    package: Mapping[str, Any],
    continuation: Mapping[str, Any],
    desired: Mapping[str, Any],
    *,
    observed_at: datetime,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    package_sha256: str | None = None,
    on_completed_read: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if package_sha256 is None:
        package_sha256 = canonical_sha256(package)
    if (
        not isinstance(package_sha256, str)
        or len(package_sha256) != 64
        or any(character not in "0123456789abcdef" for character in package_sha256)
        or getattr(observed_at, "tzinfo", None) is None
    ):
        raise _invalid("diagnostic_package_invalid", stage="observation", role="local")
    raw = collect_arm_payloads(
        package,
        continuation,
        runner=runner,
        on_completed_read=on_completed_read,
    )
    resources = project_deployed_resources(raw, desired, continuation)
    try:
        recorded_at = parse_utc(continuation["recorded_at"])
        desired_jobs = desired["jobs"]
        execution_authority = continuation["executions"]
        raw_executions = raw["executions"]
    except (KeyError, TypeError, DeployedReleaseDiagnosticInvalid) as error:
        raise _invalid(
            "diagnostic_execution_history_invalid",
            stage="execution",
            role="local",
        ) from error
    executions: dict[str, Any] = {}
    for role in ROLE_TO_TARGET_KEY:
        try:
            executions[role] = evaluate_execution_history(
                role,
                raw_executions[role],
                execution_authority[role],
                continuation_recorded_at=recorded_at,
                observed_at=observed_at,
                replica_timeout=desired_jobs[role]["replica_timeout"],
            )
        except KeyError as error:
            raise _invalid(
                "diagnostic_execution_history_invalid",
                stage="execution",
                role=role,
            ) from error
    page_evidence = _safe_page_evidence(raw)
    try:
        observation = {
            "authorization_id": package["authorization_id"],
            "checks": {
                "bound_executions_match": True,
                "desired_contract_match": True,
                "execution_history_acceptable": True,
                "pagination_complete": True,
            },
            "claim": "read_only_deployed_state_observed",
            "continuation": package["continuation"],
            "desired_projection_sha256": package["desired_projection_sha256"],
            "executions": executions,
            "observed_at": utc_text(observed_at),
            "package_sha256": package_sha256,
            "page_evidence": page_evidence,
            "repository": package["repository"],
            "resources": resources,
            "schema_version": OBSERVATION_SCHEMA,
            "toolchain": package["toolchain"],
        }
    except (KeyError, TypeError, DeployedReleaseDiagnosticInvalid) as error:
        raise _invalid(
            "diagnostic_package_invalid", stage="observation", role="local"
        ) from error
    serialized = json.dumps(observation, ensure_ascii=True, sort_keys=True)
    if SECRET_PATTERN.search(serialized) or _contains_forbidden_observation_key(
        observation
    ):
        raise _invalid(
            "diagnostic_observation_write_failed",
            stage="observation",
            role="local",
        )
    return observation
