#!/usr/bin/env python3
"""Committed live operations adapter for one admin-AI release attempt.

The controller owns ordering and the terminal receipt.  This module owns the
narrow Azure and same-origin HTTP integrations.  It has no retry loop and
never accepts credential material through argv or the process environment.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from scripts.create_admin_ai_release_package import (
    AdminAIReleasePackageInvalid,
    MIGRATION_JOB_QUERY,
    validate_migration_job_safe_projection,
)
from scripts.azure_ai_enablement_actions import (
    AzureAIEnablementActions,
    read_sanitized_azure_authority,
)
from scripts.publish_registry_image import publish_registry_oci_artifact
from scripts.run_azure_job import run_job_to_completion


STATES = (
    "readonly_revalidation",
    "publish_candidate_image",
    "deploy_admin_ai_capability",
    "verify_ai_disabled_candidate",
    "rotate_key_through_admin",
    "verify_operator_ai",
    "verify_demo_ai",
    "verify_independent_channel_switches",
    "verify_invalid_candidate_rollback",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?")
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,127}")
_PROCESS_ENVIRONMENT_NAMES = (
    "AZURE_CONFIG_DIR",
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_FILE",
    "TMPDIR",
)
_GENERIC_SECRET_PATTERN = re.compile(
    r"(?i)(sk-(?:proj-)?[A-Za-z0-9_-]{12,}|openai_api_key|candidate_key|"
    r"current_password|authorization\s*[:=]\s*bearer)"
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AdminAIReleaseOperationInvalid(RuntimeError):
    """One exact live adapter boundary failed closed with a value-free code."""


def _invalid(code: str) -> AdminAIReleaseOperationInvalid:
    return AdminAIReleaseOperationInvalid(f"admin_ai_release_{code}")


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _safe_environment(source: Mapping[str, str]) -> dict[str, str]:
    return {
        name: value
        for name in _PROCESS_ENVIRONMENT_NAMES
        if isinstance((value := source.get(name)), str)
    }


class OperationsBackend(Protocol):
    def execute(
        self,
        state: str,
        *,
        secret_value: str | None,
        context: dict[str, object],
    ) -> dict[str, object]: ...

    def reconcile_admin_ai_secret_access(
        self,
        *,
        context: dict[str, object],
    ) -> dict[str, object]: ...


class AdminAIReleaseOperations:
    """Order-checking adapter exposed to ``run_admin_ai_release.py``."""

    def __init__(
        self,
        *,
        package: Mapping[str, object],
        approved_sha256: str,
        backend: OperationsBackend,
    ) -> None:
        if (
            not isinstance(package, Mapping)
            or not isinstance(approved_sha256, str)
            or _SHA256.fullmatch(approved_sha256) is None
        ):
            raise _invalid("factory_authority_invalid")
        self._backend = backend
        self._next_state = 0
        self._rbac_reconciled = False

    def __repr__(self) -> str:
        return (
            "AdminAIReleaseOperations(backend=<redacted>, "
            f"next_state={self._next_state})"
        )

    def run(
        self,
        state: str,
        *,
        secret_value: str | None,
        context: dict[str, object],
    ) -> dict[str, object]:
        if self._next_state >= len(STATES) or state != STATES[self._next_state]:
            raise _invalid("state_order_invalid")
        if (state == "rotate_key_through_admin") != (secret_value is not None):
            raise _invalid("secret_boundary_invalid")
        if state == "rotate_key_through_admin" and not secret_value:
            raise _invalid("secret_boundary_invalid")
        if state == "deploy_admin_ai_capability" and not self._rbac_reconciled:
            raise _invalid("rbac_boundary_invalid")
        try:
            result = self._backend.execute(
                state,
                secret_value=secret_value,
                context=deepcopy(context),
            )
        except AdminAIReleaseOperationInvalid:
            raise
        except Exception as error:
            raise _invalid("operation_failed") from error
        finally:
            secret_value = None
        if not isinstance(result, dict):
            raise _invalid("evidence_invalid")
        self._next_state += 1
        return result

    def reconcile_admin_ai_secret_access(
        self,
        *,
        context: dict[str, object],
    ) -> dict[str, object]:
        if self._rbac_reconciled or self._next_state != 2:
            raise _invalid("rbac_boundary_invalid")
        self._rbac_reconciled = True
        try:
            result = self._backend.reconcile_admin_ai_secret_access(
                context=deepcopy(context)
            )
        except AdminAIReleaseOperationInvalid:
            raise
        except Exception as error:
            raise _invalid("rbac_failed") from error
        if not isinstance(result, dict):
            raise _invalid("rbac_evidence_invalid")
        return result


class AzureHostedAdminAIBackend:
    """No-retry Azure and hosted-HTTP implementation of the adapter boundary."""

    def __init__(
        self,
        *,
        package: Mapping[str, object],
        approved_sha256: str,
        password_provider: Callable[[str], str] = getpass.getpass,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        environment: Mapping[str, str] = os.environ,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
        actions: AzureAIEnablementActions | None = None,
        authority_reader: Callable[..., object] = read_sanitized_azure_authority,
        publisher: Callable[..., str] = publish_registry_oci_artifact,
        job_runner: Callable[..., str] = run_job_to_completion,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        try:
            operations_authority = package["operations_authority"]
            authority = deepcopy(operations_authority["task10_request"])
            migration_job_authority = deepcopy(
                operations_authority["migration_job"]
            )
            migration_job = migration_job_authority["safe_projection"]["name"]
            source_sha = package["repository"]["source_sha"]
            source_tree = package["repository"]["source_tree"]
            candidate = package["candidate"]
            authority["repository"]["head_sha"] = source_sha
            authority["repository"]["tree_sha"] = source_tree
            authority["candidate"]["candidate_image_digest"] = candidate[
                "image_digest"
            ]
            authority["candidate"]["image_input_sha256"] = candidate[
                "image_input_sha256"
            ]
        except (KeyError, TypeError) as error:
            raise _invalid("factory_authority_invalid") from error
        if (
            not isinstance(migration_job, str)
            or not isinstance(approved_sha256, str)
            or _SHA256.fullmatch(approved_sha256) is None
        ):
            raise _invalid("factory_authority_invalid")
        self._package = deepcopy(dict(package))
        self._authority = authority
        self._migration_job = migration_job
        self._migration_job_authority = migration_job_authority
        self._approved_sha256 = approved_sha256
        self._password_provider = password_provider
        self._runner = runner
        self._environment = _safe_environment(environment)
        self._client_factory = client_factory
        self._actions = actions or AzureAIEnablementActions(
            package=self._authority,
            package_sha256=approved_sha256,
            runner=runner,
            environment=self._environment,
        )
        self._authority_reader = authority_reader
        self._publisher = publisher
        self._job_runner = job_runner
        attempt_started_at = now()
        if attempt_started_at.tzinfo is None:
            raise _invalid("factory_authority_invalid")
        self._now = now
        self._sleeper = sleeper
        self._attempt_started_at = attempt_started_at.astimezone(UTC)
        self._hosted_origin: str | None = None
        self._deployed_revision: str | None = None
        self._operator: httpx.Client | None = None
        self._demo: httpx.Client | None = None
        self._csrf: str | None = None
        self._demo_csrf: str | None = None
        self._password_buffer: bytearray | None = None
        self._candidate_buffer: bytearray | None = None
        self._control: dict[str, object] | None = None
        self._operator_turn_id: str | None = None
        self._demo_turn_id: str | None = None
        self._safe_scan_matches = 0
        self._mutation_audit_expectations: list[dict[str, object]] = []

    def __repr__(self) -> str:
        return "AzureHostedAdminAIBackend(credentials=<redacted>)"

    def execute(
        self,
        state: str,
        *,
        secret_value: str | None,
        context: dict[str, object],
    ) -> dict[str, object]:
        methods = {
            "readonly_revalidation": self._readonly_revalidation,
            "publish_candidate_image": self._publish_candidate_image,
            "deploy_admin_ai_capability": self._deploy_admin_ai_capability,
            "verify_ai_disabled_candidate": self._verify_ai_disabled_candidate,
            "rotate_key_through_admin": self._rotate_key_through_admin,
            "verify_operator_ai": self._verify_operator_ai,
            "verify_demo_ai": self._verify_demo_ai,
            "verify_independent_channel_switches": (
                self._verify_independent_channel_switches
            ),
            "verify_invalid_candidate_rollback": (
                self._verify_invalid_candidate_rollback
            ),
        }
        method = methods.get(state)
        if method is None:
            raise _invalid("state_invalid")
        return method(secret_value=secret_value, context=context)

    def _readonly_revalidation(
        self,
        *,
        secret_value: str | None,
        context: dict[str, object],
    ) -> dict[str, object]:
        del context
        if secret_value is not None:
            raise _invalid("secret_boundary_invalid")
        observed: dict[str, object] = {}

        def safe_observer(value: Mapping[str, object]) -> None:
            observed.update(deepcopy(dict(value)))

        result, projection = self._authority_reader(
            self._authority,
            runner=self._runner,
            safe_observer=safe_observer,
            environment=self._environment,
        )
        hosted_origin = observed.get("hosted_url")
        configuration = observed.get("immutable_configuration")
        if not isinstance(hosted_origin, str) or not isinstance(
            configuration, Mapping
        ):
            raise _invalid("preflight_invalid")
        parsed = urlsplit(hosted_origin)
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise _invalid("preflight_invalid")
        self._hosted_origin = hosted_origin.rstrip("/")
        anonymous = self._client()
        try:
            readiness = self._json(
                anonymous.get("/health/ready"),
                status=200,
            )
        finally:
            anonymous.close()
        checks = readiness.get("checks")
        baseline = self._package["azure_baseline"]
        if (
            readiness.get("status") != "ready"
            or not isinstance(checks, Mapping)
            or checks.get("migration") != baseline["database_revision"]
        ):
            raise _invalid("preflight_database_drift")
        outputs = result.get("outputs", {})
        observation_sha256 = _canonical_hash(
            {"result": result, "projection": projection}
        )
        if (
            result.get("operations") != {"azure.read.sanitized": 12}
            or observation_sha256 != baseline["observation_sha256"]
            or outputs.get("role_assignment_state")
            != baseline["role_assignment_phase"]
        ):
            raise _invalid("preflight_drift")
        self._actions.current_projection = deepcopy(projection)
        self._actions._immutable_configuration = deepcopy(dict(configuration))
        self._actions._hosted_url = self._hosted_origin
        return {
            "required_azure_reads": 12,
            "observation_sha256": observation_sha256,
            "role_assignment_phase": outputs["role_assignment_state"],
            "database_revision": checks["migration"],
        }

    def _publish_candidate_image(
        self,
        *,
        secret_value: str | None,
        context: dict[str, object],
    ) -> dict[str, object]:
        del context
        if secret_value is not None:
            raise _invalid("secret_boundary_invalid")
        target = self._authority["azure_target"]
        candidate = self._package["candidate"]
        digest = self._publisher(
            subscription_id=str(target["subscription_id"]),
            registry_name=str(target["registry_name"]),
            repository=str(self._authority["candidate"]["image_repository"]),
            candidate_git_sha=str(self._package["repository"]["source_sha"]),
            source_tree=str(self._package["repository"]["source_tree"]),
            package_sha256=self._approved_sha256,
            artifact_path=PROJECT_ROOT / str(candidate["artifact_path"]),
            artifact_sha256=str(candidate["artifact_sha256"]),
            expected_digest=str(candidate["image_digest"]),
            oci_reference=str(candidate["oci_reference"]),
            image_input_sha256=str(candidate["image_input_sha256"]),
            build_context_sha256=str(candidate["build_context_sha256"]),
            environment=self._environment,
            runner=self._runner,
        )
        if digest != candidate["image_digest"]:
            raise _invalid("image_digest_drift")
        return {"image_digest": digest}

    def _candidate_reference(self) -> str:
        target = self._authority["azure_target"]
        repository = self._authority["candidate"]["image_repository"]
        digest = self._package["candidate"]["image_digest"]
        return f"{target['registry_name']}.azurecr.io/{repository}@{digest}"

    def _validate_migration_job_projection(
        self,
        payload: object,
        *,
        expected_image: str,
    ) -> str:
        try:
            observed = validate_migration_job_safe_projection(
                payload,
                task10_request=self._authority,
                expected_image=expected_image,
            )
            expected = deepcopy(
                self._migration_job_authority["safe_projection"]
            )
            expected = validate_migration_job_safe_projection(
                expected,
                task10_request=self._authority,
                expected_image=expected_image,
            )
        except (
            AdminAIReleasePackageInvalid,
            KeyError,
            TypeError,
        ) as error:
            raise _invalid("migration_job_authority_invalid") from error
        if observed != expected:
            raise _invalid("migration_job_authority_invalid")
        return _canonical_hash(observed)

    def _read_migration_job_projection(self, *, expected_image: str) -> str:
        target = self._authority["azure_target"]
        try:
            completed = self._runner(
                [
                    "az",
                    "containerapp",
                    "job",
                    "show",
                    "--subscription",
                    str(target["subscription_id"]),
                    "--resource-group",
                    str(target["resource_group"]),
                    "--name",
                    self._migration_job,
                    "--query",
                    MIGRATION_JOB_QUERY,
                    "--only-show-errors",
                    "--output",
                    "json",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
                shell=False,
                env=self._environment,
            )
            if len(completed.stdout) > 1_000_000:
                raise _invalid("migration_job_authority_invalid")
            payload = json.loads(completed.stdout)
        except (
            AdminAIReleaseOperationInvalid,
            OSError,
            subprocess.SubprocessError,
            json.JSONDecodeError,
            TypeError,
        ) as error:
            if isinstance(error, AdminAIReleaseOperationInvalid):
                raise
            raise _invalid("migration_job_authority_invalid") from error
        return self._validate_migration_job_projection(
            payload,
            expected_image=expected_image,
        )

    def _migration_execution_template(self, *, image: str) -> dict[str, object]:
        try:
            if image != self._migration_job_authority["approved_execution_image"]:
                raise TypeError
            approved = self._migration_job_authority["safe_projection"]
            container = approved["containers"][0]
            safe_values = {
                entry["name"]: entry["value"] for entry in container["safeEnv"]
            }
            environment = []
            for binding in container["env"]:
                name = binding["name"]
                secret_ref = binding["secretRef"]
                if secret_ref is None:
                    environment.append({"name": name, "value": safe_values[name]})
                else:
                    environment.append({"name": name, "secretRef": secret_ref})
            template = {
                "containers": [
                    {
                        "name": container["name"],
                        "image": image,
                        "command": list(container["command"]),
                        "args": list(container["args"]),
                        "env": sorted(environment, key=lambda item: item["name"]),
                        "resources": deepcopy(container["resources"]),
                    }
                ],
                "initContainers": [],
                "volumes": [],
            }
        except (KeyError, IndexError, TypeError) as error:
            raise _invalid("migration_job_authority_invalid") from error
        return template

    def _deploy_admin_ai_capability(
        self,
        *,
        secret_value: str | None,
        context: dict[str, object],
    ) -> dict[str, object]:
        if secret_value is not None or self._hosted_origin is None:
            raise _invalid("deploy_boundary_invalid")
        target = self._authority["azure_target"]
        image = self._candidate_reference()
        transition_context = {
            **context,
            "candidate_image_digest": self._package["candidate"]["image_digest"],
        }
        revision = self._actions._apply_revision(
            enabled=True,
            label="admin-ai-compatible",
            role="admin_ai_compatible_candidate",
            context=transition_context,
        )
        self._actions._reconcile_revision(
            enabled=True,
            image=image,
            revision=revision,
            context=transition_context,
            role="admin_ai_compatible_candidate",
        )
        if not isinstance(revision, str) or _REVISION.fullmatch(revision) is None:
            raise _invalid("deploy_boundary_invalid")
        self._deployed_revision = revision
        job_projection_sha256 = self._read_migration_job_projection(
            expected_image=str(target["rollback_image"])
        )
        execution_template = self._migration_execution_template(image=image)
        self._job_runner(
            subscription_id=str(target["subscription_id"]),
            resource_group=str(target["resource_group"]),
            job_name=self._migration_job,
            timeout_seconds=900,
            execution_template=execution_template,
            runner=self._runner,
            environment=self._environment,
        )
        return {
            "revision": revision,
            "migration": "0017_ai_turn_credential_binding",
            "operator_ai_enabled": False,
            "demo_ai_enabled": False,
            "migration_job_reads": 1,
            "migration_job_projection_sha256": job_projection_sha256,
            "migration_execution_template_sha256": _canonical_hash(
                execution_template
            ),
        }

    def reconcile_admin_ai_secret_access(
        self,
        *,
        context: dict[str, object],
    ) -> dict[str, object]:
        initial_phase = self._package["azure_baseline"]["role_assignment_phase"]
        result = self._actions.reconcile_admin_ai_secret_access(context=context)
        assignment_set_sha256 = result.get("assignment_set_sha256")
        if (
            not isinstance(assignment_set_sha256, str)
            or _SHA256.fullmatch(assignment_set_sha256) is None
        ):
            raise _invalid("rbac_evidence_invalid")
        return {
            "initial_phase": initial_phase,
            "final_phase": "officer_only",
            "assignment_set_sha256": assignment_set_sha256,
            "preflight_required_azure_reads": 12,
            "vault_url": result["vault_url"],
            "identity_resource_id": result["identity_resource_id"],
            "managed_identity_client_id": result["managed_identity_client_id"],
        }

    def _client(self) -> httpx.Client:
        if self._hosted_origin is None:
            raise _invalid("hosted_authority_missing")
        return self._client_factory(
            base_url=self._hosted_origin,
            timeout=30,
            follow_redirects=False,
            trust_env=False,
        )

    def _record_body(
        self,
        response: httpx.Response,
        *,
        sensitive_values: tuple[str, ...] = (),
    ) -> None:
        body = response.text[:65_537]
        headers = "\n".join(f"{name}: {value}" for name, value in response.headers.items())
        scanned = f"{headers}\n{body}"
        retained_values = tuple(
            buffer.decode("utf-8")
            for buffer in (self._candidate_buffer, self._password_buffer)
            if buffer is not None
        )
        exact_values = tuple(dict.fromkeys((*sensitive_values, *retained_values)))
        if (
            len(response.content) > 65_536
            or len(headers.encode("utf-8")) > 65_536
            or any(value and value in scanned for value in exact_values)
        ):
            raise _invalid("secret_scan_failed")
        generic_matches = len(_GENERIC_SECRET_PATTERN.findall(scanned))
        self._safe_scan_matches += generic_matches
        if generic_matches:
            raise _invalid("secret_scan_failed")

    def _json(
        self,
        response: httpx.Response,
        *,
        status: int,
        sensitive_values: tuple[str, ...] = (),
    ) -> dict[str, object]:
        self._record_body(response, sensitive_values=sensitive_values)
        if response.status_code != status:
            raise _invalid("hosted_response_invalid")
        try:
            value = response.json()
        except (json.JSONDecodeError, UnicodeError) as error:
            raise _invalid("hosted_response_invalid") from error
        if not isinstance(value, dict):
            raise _invalid("hosted_response_invalid")
        return value

    def _password(self) -> str:
        if self._password_buffer is None:
            provided = self._password_provider(
                "Operator current password (input hidden): "
            )
            try:
                if (
                    not isinstance(provided, str)
                    or not provided
                    or len(provided) > 1_024
                    or any(character in provided for character in "\0\r\n")
                ):
                    raise _invalid("operator_password_invalid")
                self._password_buffer = bytearray(provided.encode())
            finally:
                provided = ""
        return self._password_buffer.decode()

    def _login_operator(self) -> None:
        if self._operator is not None:
            return
        client = self._client()
        password = self._password()
        try:
            payload = self._json(
                client.post(
                    "/api/operator/login",
                    headers={"Origin": str(self._hosted_origin)},
                    json={"login_name": "operator", "password": password},
                ),
                status=201,
                sensitive_values=(password,),
            )
        finally:
            password = ""
        csrf = payload.get("csrf_token")
        if not isinstance(csrf, str) or not 32 <= len(csrf) <= 256:
            client.close()
            raise _invalid("operator_login_failed")
        self._operator = client
        self._csrf = csrf

    def _request_id(self, response: httpx.Response, label: str) -> str:
        del label
        observed = response.headers.get("X-Request-ID")
        if isinstance(observed, str) and _SAFE_REQUEST_ID.fullmatch(observed):
            return observed
        raise _invalid("request_id_invalid")

    def _remember_mutation_audit(
        self,
        response: httpx.Response,
        *,
        action: str,
        result: str,
        safe_error_code: str | None,
        prior_revision: int,
        resulting_revision: int,
        requested_operator_enabled: bool | None = None,
        requested_demo_enabled: bool | None = None,
    ) -> str:
        request_id = self._request_id(response, "mutation")
        self._mutation_audit_expectations.append(
            {
                "request_id": request_id,
                "action": action,
                "result": result,
                "safe_error_code": safe_error_code,
                "prior_revision": prior_revision,
                "resulting_revision": resulting_revision,
                "requested_operator_enabled": requested_operator_enabled,
                "requested_demo_enabled": requested_demo_enabled,
            }
        )
        return request_id

    def _operator_headers(self, idempotency: str | None = None) -> dict[str, str]:
        if self._csrf is None or self._hosted_origin is None:
            raise _invalid("operator_login_failed")
        headers = {"Origin": self._hosted_origin, "X-CSRF-Token": self._csrf}
        if idempotency is not None:
            headers["Idempotency-Key"] = idempotency
        return headers

    def _read_control(self) -> dict[str, object]:
        if self._operator is None:
            raise _invalid("operator_login_failed")
        control = self._json(self._operator.get("/api/v1/admin/ai"), status=200)
        required = {"revision", "operator_enabled", "demo_enabled", "credential"}
        if set(control) != required or not isinstance(control["credential"], dict):
            raise _invalid("control_projection_invalid")
        self._control = control
        return control

    def _verify_ai_disabled_candidate(
        self,
        *,
        secret_value: str | None,
        context: dict[str, object],
    ) -> dict[str, object]:
        del context
        if secret_value is not None:
            raise _invalid("secret_boundary_invalid")
        anonymous = self._client()
        try:
            health = anonymous.get("/health/ready")
            health_payload = self._json(health, status=200)
            denied = anonymous.get("/admin")
            self._record_body(denied)
            checks = health_payload.get("checks")
            if (
                health_payload.get("status") != "ready"
                or not isinstance(checks, Mapping)
                or checks.get("migration") != "0017_ai_turn_credential_binding"
                or denied.status_code not in {302, 303, 307}
            ):
                raise _invalid("disabled_gate_failed")
        finally:
            anonymous.close()
        self._login_operator()
        assert self._operator is not None
        admin = self._operator.get("/admin")
        self._record_body(admin)
        summary = self._json(
            self._operator.get("/api/v1/admin/summary"),
            status=200,
        )
        control = self._read_control()
        if (
            admin.status_code != 200
            or summary.get("ai", {}).get("status") != "ready"
            or control["operator_enabled"] is not False
            or control["demo_enabled"] is not False
        ):
            raise _invalid("disabled_gate_failed")
        return {
            "ready": True,
            "admin_protected": True,
            "summary_status": "ready",
            "operator_ai_enabled": False,
            "demo_ai_enabled": False,
            "request_id": self._request_id(admin, "admin-disabled"),
        }

    def _mutation(
        self,
        path: str,
        *,
        method: str,
        body: dict[str, object],
        idempotency: str,
        sensitive_values: tuple[str, ...],
        status: int = 200,
    ) -> tuple[dict[str, object], httpx.Response]:
        if self._operator is None:
            raise _invalid("operator_login_failed")
        response = self._operator.request(
            method,
            path,
            headers=self._operator_headers(idempotency),
            json=body,
        )
        return (
            self._json(
                response,
                status=status,
                sensitive_values=sensitive_values,
            ),
            response,
        )

    def _rotate_key_through_admin(
        self,
        *,
        secret_value: str | None,
        context: dict[str, object],
    ) -> dict[str, object]:
        del context
        if not secret_value or self._control is None:
            raise _invalid("secret_boundary_invalid")
        password = self._password()
        candidate = secret_value
        self._candidate_buffer = bytearray(candidate.encode())
        prior_revision = self._control["revision"]
        try:
            payload, response = self._mutation(
                "/api/v1/admin/ai/key-rotations",
                method="POST",
                body={
                    "candidate_key": candidate,
                    "current_password": password,
                    "expected_revision": self._control["revision"],
                },
                idempotency=f"admin-ai-rotation-{uuid4()}",
                sensitive_values=(candidate, password),
            )
        finally:
            candidate = ""
            password = ""
            secret_value = None
        credential = payload.get("credential")
        fingerprint = (
            credential.get("fingerprint") if isinstance(credential, dict) else None
        )
        if (
            payload.get("result_code") != "ADMIN_AI_KEY_ROTATED"
            or not isinstance(fingerprint, str)
            or re.fullmatch(r"[0-9a-f]{8}", fingerprint) is None
            or type(payload.get("revision")) is not int
        ):
            raise _invalid("rotation_evidence_invalid")
        self._control = {
            **self._control,
            "revision": payload["revision"],
            "credential": credential,
        }
        request_id = self._remember_mutation_audit(
            response,
            action="key.rotate",
            result="succeeded",
            safe_error_code=None,
            prior_revision=prior_revision,
            resulting_revision=payload["revision"],
        )
        return {
            "credential_fingerprint": fingerprint,
            "request_id": request_id,
            "revision": payload["revision"],
        }

    def _set_channels(self, operator_enabled: bool, demo_enabled: bool) -> None:
        if self._control is None:
            raise _invalid("control_projection_invalid")
        password = self._password()
        prior_revision = self._control["revision"]
        try:
            changed, response = self._mutation(
                "/api/v1/admin/ai/channels",
                method="PATCH",
                body={
                    "expected_revision": self._control["revision"],
                    "operator_enabled": operator_enabled,
                    "demo_enabled": demo_enabled,
                    "current_password": password,
                },
                idempotency=f"admin-ai-channel-{uuid4()}",
                sensitive_values=(password,),
            )
        finally:
            password = ""
        if (
            changed.get("operator_enabled") is not operator_enabled
            or changed.get("demo_enabled") is not demo_enabled
            or type(changed.get("revision")) is not int
        ):
            raise _invalid("channel_evidence_invalid")
        self._control = changed
        self._remember_mutation_audit(
            response,
            action="channels.update",
            result="succeeded",
            safe_error_code=None,
            prior_revision=prior_revision,
            resulting_revision=changed["revision"],
            requested_operator_enabled=operator_enabled,
            requested_demo_enabled=demo_enabled,
        )

    @staticmethod
    def _turn_body() -> dict[str, object]:
        return {"question": "Which inventory items need attention first?"}

    def _audit_binding(
        self,
        turn_ids: tuple[str, ...],
        *,
        actor_kinds: tuple[str, ...],
    ) -> list[dict[str, object]]:
        if self._operator is None:
            raise _invalid("operator_login_failed")
        if (
            len(turn_ids) != len(actor_kinds)
            or len(set(turn_ids)) != len(turn_ids)
            or any(kind not in {"operator", "demo"} for kind in actor_kinds)
        ):
            raise _invalid("binding_evidence_invalid")
        response = self._operator.get(
            "/api/v1/admin/ai/turn-bindings",
            params=[("turn_id", value) for value in turn_ids],
        )
        payload = self._json(response, status=200)
        items = payload.get("items")
        if not isinstance(items, list) or len(items) != len(turn_ids):
            raise _invalid("binding_evidence_invalid")
        expected_keys = {
            "turn_id",
            "actor_kind",
            "request_id",
            "credential_binding_id",
            "credential_control_revision",
            "status",
        }
        validated: list[dict[str, object]] = []
        for expected_turn, expected_actor, item in zip(
            turn_ids,
            actor_kinds,
            items,
            strict=True,
        ):
            if (
                not isinstance(item, Mapping)
                or set(item) != expected_keys
                or item["turn_id"] != expected_turn
                or item["actor_kind"] != expected_actor
                or item["status"] != "answered"
                or not isinstance(item["request_id"], str)
                or _SAFE_REQUEST_ID.fullmatch(item["request_id"]) is None
                or not isinstance(item["credential_binding_id"], str)
                or _SHA256.fullmatch(item["credential_binding_id"]) is None
                or type(item["credential_control_revision"]) is not int
                or item["credential_control_revision"] < 0
            ):
                raise _invalid("binding_evidence_invalid")
            validated.append(dict(item))
        return validated

    def _mutation_audit_evidence(self) -> dict[str, object]:
        if (
            self._operator is None
            or not self._mutation_audit_expectations
            or len(self._mutation_audit_expectations) > 16
        ):
            raise _invalid("mutation_audit_invalid")
        request_ids = [
            str(item["request_id"])
            for item in self._mutation_audit_expectations
        ]
        if len(set(request_ids)) != len(request_ids):
            raise _invalid("mutation_audit_invalid")
        response = self._operator.get(
            "/api/v1/admin/ai/audit-events",
            params=[("request_id", value) for value in request_ids],
        )
        payload = self._json(response, status=200)
        items = payload.get("items")
        if (
            not isinstance(items, list)
            or len(items) != len(self._mutation_audit_expectations)
        ):
            raise _invalid("mutation_audit_invalid")
        validated: list[dict[str, object]] = []
        expected_keys = {
            "request_id",
            "action",
            "result",
            "safe_error_code",
            "prior_revision",
            "resulting_revision",
            "requested_operator_enabled",
            "requested_demo_enabled",
        }
        for expected, item in zip(
            self._mutation_audit_expectations,
            items,
            strict=True,
        ):
            if (
                not isinstance(item, Mapping)
                or set(item) != expected_keys
                or dict(item) != expected
            ):
                raise _invalid("mutation_audit_invalid")
            validated.append(dict(item))
        return {
            "event_count": len(validated),
            "secret_scan_matches": 0,
            "evidence_sha256": _canonical_hash(validated),
        }

    def _verify_operator_ai(
        self,
        *,
        secret_value: str | None,
        context: dict[str, object],
    ) -> dict[str, object]:
        del context
        if secret_value is not None or self._operator is None:
            raise _invalid("secret_boundary_invalid")
        self._set_channels(True, False)
        response = self._operator.post(
            "/api/v1/ai-chat/turns",
            headers=self._operator_headers(f"admin-ai-operator-turn-{uuid4()}"),
            json=self._turn_body(),
        )
        turn = self._json(response, status=201)
        turn_id = turn.get("id")
        if turn.get("status") != "answered" or not isinstance(turn_id, str):
            raise _invalid("operator_turn_failed")
        self._operator_turn_id = turn_id
        item = self._audit_binding(
            (turn_id,),
            actor_kinds=("operator",),
        )[0]
        fingerprint = self._control["credential"]["fingerprint"]
        return {
            "status": "completed",
            "request_id": item["request_id"],
            "credential_fingerprint": fingerprint,
            "credential_binding_id": item["credential_binding_id"],
            "credential_control_revision": item["credential_control_revision"],
        }

    def _verify_demo_ai(
        self,
        *,
        secret_value: str | None,
        context: dict[str, object],
    ) -> dict[str, object]:
        del context
        if secret_value is not None or self._operator_turn_id is None:
            raise _invalid("secret_boundary_invalid")
        self._set_channels(True, True)
        demo = self._client()
        admitted = self._json(
            demo.post("/api/demo/sessions", headers={"Origin": self._hosted_origin}),
            status=201,
        )
        csrf = admitted.get("csrf_token")
        if not isinstance(csrf, str):
            demo.close()
            raise _invalid("demo_session_failed")
        self._demo = demo
        self._demo_csrf = csrf
        denied = demo.get("/admin")
        self._record_body(denied)
        if (
            denied.status_code not in {302, 303, 307, 403}
            or denied.headers.get("Cache-Control") != "private, no-store"
            or denied.headers.get("Vary") != "Cookie"
        ):
            raise _invalid("demo_admin_boundary_failed")
        headers = {"Origin": str(self._hosted_origin), "X-CSRF-Token": csrf}
        self._json(
            demo.post("/api/demo/sessions/current/import-demo-data", headers=headers),
            status=200,
        )
        turn_response = demo.post(
            "/api/v1/ai-chat/turns",
            headers={
                **headers,
                "Idempotency-Key": f"admin-ai-demo-turn-{uuid4()}",
            },
            json=self._turn_body(),
        )
        turn = self._json(turn_response, status=201)
        turn_id = turn.get("id")
        if turn.get("status") != "answered" or not isinstance(turn_id, str):
            raise _invalid("demo_turn_failed")
        self._demo_turn_id = turn_id
        items = self._audit_binding(
            (self._operator_turn_id, turn_id),
            actor_kinds=("operator", "demo"),
        )
        by_turn = {item.get("turn_id"): item for item in items}
        operator = by_turn.get(self._operator_turn_id)
        demo_item = by_turn.get(turn_id)
        if (
            not isinstance(operator, Mapping)
            or not isinstance(demo_item, Mapping)
            or operator.get("credential_binding_id")
            != demo_item.get("credential_binding_id")
        ):
            raise _invalid("shared_binding_failed")
        fingerprint = self._control["credential"]["fingerprint"]
        return {
            "status": "completed",
            "request_id": demo_item["request_id"],
            "credential_fingerprint": fingerprint,
            "credential_binding_id": demo_item["credential_binding_id"],
            "credential_control_revision": demo_item[
                "credential_control_revision"
            ],
            "admin_denied": True,
            "admin_cache_control": "private, no-store",
            "admin_vary": "Cookie",
        }

    def _verify_independent_channel_switches(
        self,
        *,
        secret_value: str | None,
        context: dict[str, object],
    ) -> dict[str, object]:
        del context
        if secret_value is not None:
            raise _invalid("secret_boundary_invalid")
        self._set_channels(False, True)
        self._set_channels(True, True)
        self._set_channels(True, False)
        self._set_channels(True, True)
        return {
            "status": "completed",
            "operator_independent": True,
            "demo_independent": True,
            "final_operator_enabled": True,
            "final_demo_enabled": True,
        }

    def _hosted_log_secret_matches(self, *, marker_request_id: str) -> int:
        target = self._authority["azure_target"]
        if (
            _SAFE_REQUEST_ID.fullmatch(marker_request_id) is None
            or self._deployed_revision is None
            or _REVISION.fullmatch(self._deployed_revision) is None
        ):
            raise _invalid("secret_scan_unavailable")
        started_text = self._attempt_started_at.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
        try:
            workspace = self._runner(
                [
                    "az",
                    "monitor",
                    "log-analytics",
                    "workspace",
                    "show",
                    "--subscription",
                    str(target["subscription_id"]),
                    "--resource-group",
                    str(target["resource_group"]),
                    "--workspace-name",
                    str(target["log_analytics_workspace_name"]),
                    "--query",
                    "customerId",
                    "--only-show-errors",
                    "--output",
                    "tsv",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
                shell=False,
                env=self._environment,
            ).stdout.strip()
        except (
            AdminAIReleaseOperationInvalid,
            OSError,
            subprocess.SubprocessError,
            TypeError,
        ) as error:
            if isinstance(error, AdminAIReleaseOperationInvalid):
                raise
            raise _invalid("secret_scan_unavailable") from error
        sensitive_values = tuple(
            buffer.decode()
            for buffer in (self._candidate_buffer, self._password_buffer)
            if buffer is not None
        )
        observed_at = self._now()
        if observed_at.tzinfo is None:
            raise _invalid("secret_scan_unavailable")
        completed_at = observed_at.astimezone(UTC)
        if (
            completed_at < self._attempt_started_at
            or completed_at - self._attempt_started_at > timedelta(hours=2)
        ):
            raise _invalid("secret_scan_unavailable")
        completed_text = completed_at.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )
        marker_observed = False
        for attempt in range(6):
            query = (
                "ContainerAppConsoleLogs_CL "
                f'| where ContainerAppName_s == "{target["app_name"]}" '
                f'| where RevisionName_s == "{self._deployed_revision}" '
                f"| where TimeGenerated between (datetime({started_text}) "
                f".. datetime({completed_text})) "
                "| project Log_s | take 1001"
            )
            try:
                completed = self._runner(
                    [
                        "az",
                        "monitor",
                        "log-analytics",
                        "query",
                        "--workspace",
                        workspace,
                        "--analytics-query",
                        query,
                        "--timespan",
                        "PT2H",
                        "--only-show-errors",
                        "--output",
                        "json",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=90,
                    shell=False,
                    env=self._environment,
                )
                if len(completed.stdout) > 1_000_000:
                    raise _invalid("secret_scan_unavailable")
                payload = json.loads(completed.stdout)
            except (
                AdminAIReleaseOperationInvalid,
                OSError,
                subprocess.SubprocessError,
                json.JSONDecodeError,
                TypeError,
            ) as error:
                if isinstance(error, AdminAIReleaseOperationInvalid):
                    raise
                raise _invalid("secret_scan_unavailable") from error
            if (
                not isinstance(payload, list)
                or len(payload) >= 1_001
                or any(
                    not isinstance(row, Mapping)
                    or set(row) != {"Log_s"}
                    or not isinstance(row["Log_s"], str)
                    or len(row["Log_s"].encode("utf-8")) > 65_536
                    for row in payload
                )
            ):
                raise _invalid("secret_scan_unavailable")
            log_text = "\n".join(str(row["Log_s"]) for row in payload)
            matches = len(_GENERIC_SECRET_PATTERN.findall(log_text)) + sum(
                log_text.count(value) for value in sensitive_values if value
            )
            if matches:
                return matches
            if marker_request_id in log_text:
                if marker_observed:
                    return 0
                marker_observed = True
            if attempt < 5:
                self._sleeper(5.0)
        raise _invalid("secret_scan_unavailable")

    def _wipe_credentials(self) -> None:
        if self._password_buffer is not None:
            for index in range(len(self._password_buffer)):
                self._password_buffer[index] = 0
            self._password_buffer.clear()
            self._password_buffer = None
        if self._candidate_buffer is not None:
            for index in range(len(self._candidate_buffer)):
                self._candidate_buffer[index] = 0
            self._candidate_buffer.clear()
            self._candidate_buffer = None
        self._csrf = None
        self._demo_csrf = None
        for client in (self._operator, self._demo):
            if client is not None:
                client.close()
        self._operator = None
        self._demo = None

    def _verify_invalid_candidate_rollback(
        self,
        *,
        secret_value: str | None,
        context: dict[str, object],
    ) -> dict[str, object]:
        if secret_value is not None or self._control is None:
            raise _invalid("secret_boundary_invalid")
        sentinel = context.get("known_invalid_sentinel")
        if not isinstance(sentinel, str) or not sentinel:
            raise _invalid("invalid_sentinel_missing")
        prior = deepcopy(self._control)
        password = self._password()
        try:
            if self._operator is None:
                raise _invalid("operator_login_failed")
            response = self._operator.post(
                "/api/v1/admin/ai/key-rotations",
                headers=self._operator_headers(f"admin-ai-invalid-{uuid4()}"),
                json={
                    "candidate_key": sentinel,
                    "current_password": password,
                    "expected_revision": prior["revision"],
                },
            )
            rejected = self._json(
                response,
                status=422,
                sensitive_values=(password,),
            )
            current = self._read_control()
            fingerprint = prior["credential"]["fingerprint"]
            if (
                rejected != {"code": "ADMIN_AI_KEY_REJECTED"}
                or current != prior
            ):
                raise _invalid("invalid_rollback_failed")
            marker_request_id = response.headers.get("X-Request-ID")
            if (
                not isinstance(marker_request_id, str)
                or _SAFE_REQUEST_ID.fullmatch(marker_request_id) is None
            ):
                raise _invalid("secret_scan_unavailable")
            self._remember_mutation_audit(
                response,
                action="key.rotate",
                result="failed",
                safe_error_code="ADMIN_AI_KEY_REJECTED",
                prior_revision=prior["revision"],
                resulting_revision=current["revision"],
            )
            audit_evidence = self._mutation_audit_evidence()
            matches = (
                self._safe_scan_matches
                + int(audit_evidence["secret_scan_matches"])
                + self._hosted_log_secret_matches(
                    marker_request_id=marker_request_id
                )
            )
            return {
                "status": "rejected",
                "safe_code": "ADMIN_AI_KEY_REJECTED",
                "prior_fingerprint": fingerprint,
                "resulting_fingerprint": current["credential"]["fingerprint"],
                "prior_operator_enabled": prior["operator_enabled"],
                "resulting_operator_enabled": current["operator_enabled"],
                "prior_demo_enabled": prior["demo_enabled"],
                "resulting_demo_enabled": current["demo_enabled"],
                "secret_scan_matches": matches,
                "audit_event_count": audit_evidence["event_count"],
                "audit_secret_scan_matches": audit_evidence[
                    "secret_scan_matches"
                ],
                "audit_evidence_sha256": audit_evidence["evidence_sha256"],
            }
        finally:
            password = ""
            self._wipe_credentials()


def create_operations(
    *,
    package: Mapping[str, object],
    approved_sha256: str,
    backend: OperationsBackend | None = None,
) -> AdminAIReleaseOperations:
    """Construct the package-bound adapter imported by the one-shot controller."""

    selected = (
        AzureHostedAdminAIBackend(
            package=package,
            approved_sha256=approved_sha256,
        )
        if backend is None
        else backend
    )
    return AdminAIReleaseOperations(
        package=package,
        approved_sha256=approved_sha256,
        backend=selected,
    )
