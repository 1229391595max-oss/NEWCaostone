"""Execute one explicitly approved, package-bound operator password rotation.

This controller intentionally has no command-line option for credential
material.  Passwords and Argon2 strings remain inside the Keychain process
boundary and the deployment adapter's child environment only.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import hashlib
import hmac
import json
import os
import re
import ssl
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPSHandler,
    HTTPCookieProcessor,
    Request,
    build_opener,
)

import truststore

from scripts.generate_operator_rotation_authority import (
    PROJECT_ROOT,
    OperatorRotationAuthorityInvalid,
    build_rotation_authority,
    validate_inverse_rotation_preflight,
)
from scripts.operator_rotation_keychain import OperatorCredentialPair
from scripts.run_azure_job import AzureJobFailed, run_job_to_completion
from scripts.run_hosted_check import HostedCheckInvalid, run_hosted_check

_SHA256 = re.compile(r"[0-9a-f]{64}")
_SCHEMA_VERSION = "newcaostone.operator-password-rotation.v3"
_DELIVERY_CONTRACT = "job-only-stage-v1"
_RECEIPT_SCHEMA_VERSION = "newcaostone.operator-password-rotation-receipt.v1"
_ROTATION_JOB_DEPLOYMENT_PARAMETER_NAMES = frozenset(
    {
        "location",
        "namePrefix",
        "postgresAdministratorLogin",
        "postgresServerName",
        "registryName",
        "storageAccountName",
        "tags",
    }
)


class OperatorRotationExecutionError(RuntimeError):
    """A value-free stop condition for a bounded password rotation."""

    def __init__(self, code: str, *, rotation_id: str | None = None) -> None:
        self.code = code
        self.rotation_id = rotation_id
        detail = f"{code}:{rotation_id}" if rotation_id else code
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class ForwardJobResult:
    execution_id: str
    status: str
    revoked_session_count: int
    deleted_ephemeral_chat_count: int


@dataclass(frozen=True, slots=True)
class RotationExecutionResult:
    rotation_id: str
    job_status: str
    receipt_path: Path


class RotationKeychain(Protocol):
    def current_pair(self) -> OperatorCredentialPair: ...

    def pending_pair(self) -> OperatorCredentialPair: ...

    def promote_pending(self, *, verified_rotation_id: str) -> None: ...


class RotationOperations(Protocol):
    """The narrow mutable boundary; test fakes never contact Azure."""

    def read_app(self, authority: dict[str, object]) -> Mapping[str, object]: ...

    def read_health(self, base_url: str) -> Mapping[str, object]: ...

    def stage_rotation_job(
        self,
        authority: dict[str, object],
        *,
        current_password_hash: str,
        pending_password_hash: str,
    ) -> None: ...

    def run_forward_job(self, authority: dict[str, object]) -> ForwardJobResult: ...

    def activate_target_app(
        self,
        authority: dict[str, object],
        *,
        pending_password_hash: str,
        target_revision_suffix: str,
    ) -> None: ...

    def verify_target_app(
        self,
        authority: dict[str, object],
        *,
        target_revision_suffix: str,
    ) -> None: ...

    def smoke_login_logout(
        self,
        authority: dict[str, object],
        *,
        pending_password: str,
    ) -> None: ...

    def remove_rotation_material(
        self,
        authority: dict[str, object],
        *,
        pending_password_hash: str,
    ) -> None: ...


def smoke_operator_login_logout(
    authority: Mapping[str, object],
    *,
    pending_password: str,
    opener_factory: Callable[[http.cookiejar.CookieJar], Any] | None = None,
) -> None:
    """Perform one origin-bound pending-password login and immediate logout.

    Cookies and CSRF tokens exist only in this function's local variables and
    are never included in errors, receipts, or command arguments.
    """

    target = _mapping(authority, "target")
    base_url = f"https://{_string(target, 'fqdn')}"
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise OperatorRotationExecutionError("rotation_smoke_authority_invalid")
    cookie_jar = http.cookiejar.CookieJar()
    if opener_factory is None:
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        opener = build_opener(
            HTTPCookieProcessor(cookie_jar),
            HTTPSHandler(context=context),
        )
    else:
        opener = opener_factory(cookie_jar)
    login_url = f"{base_url}/api/operator/login"
    logout_url = f"{base_url}/api/operator/logout"
    csrf_token: str | None = None
    try:
        login_payload = json.dumps(
            {"login_name": "operator", "password": pending_password},
            separators=(",", ":"),
        ).encode("utf-8")
        login_request = Request(
            login_url,
            data=login_payload,
            method="POST",
            headers={
                "Accept": "application/json",
                "Cache-Control": "no-store",
                "Content-Type": "application/json",
                "Origin": base_url,
            },
        )
        with opener.open(login_request, timeout=20) as response:
            login_body = response.read(4_097)
            if (
                response.geturl() != login_url
                or response.status != 201
                or response.headers.get_content_type() != "application/json"
                or len(login_body) > 4_096
            ):
                raise OperatorRotationExecutionError("rotation_smoke_login_failed")
        login_result = json.loads(login_body)
        if not isinstance(login_result, Mapping):
            raise OperatorRotationExecutionError("rotation_smoke_login_failed")
        candidate_csrf = login_result.get("csrf_token")
        if not isinstance(candidate_csrf, str) or not 32 <= len(candidate_csrf) <= 256:
            raise OperatorRotationExecutionError("rotation_smoke_login_failed")
        if not any(
            cookie.name == "bp_operator_session" and cookie.value
            for cookie in cookie_jar
        ):
            raise OperatorRotationExecutionError("rotation_smoke_login_failed")
        csrf_token = candidate_csrf
        logout_request = Request(
            logout_url,
            data=b"",
            method="POST",
            headers={
                "Cache-Control": "no-store",
                "Origin": base_url,
                "X-CSRF-Token": csrf_token,
            },
        )
        with opener.open(logout_request, timeout=20) as response:
            if response.geturl() != logout_url or response.status != 204:
                raise OperatorRotationExecutionError("rotation_smoke_logout_failed")
    except OperatorRotationExecutionError:
        raise
    except (
        HTTPError,
        URLError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise OperatorRotationExecutionError("rotation_smoke_request_failed") from error
    finally:
        csrf_token = None
        cookie_jar.clear()


class AzureRotationOperations:
    """Azure implementation whose CLI children receive minimal environments."""

    def __init__(
        self,
        *,
        command_runner: Callable[
            ..., subprocess.CompletedProcess[str]
        ] = subprocess.run,
        job_runner: Callable[..., str] = run_job_to_completion,
        smoke_runner: Callable[..., None] = smoke_operator_login_logout,
        target_verifier: Callable[..., None] = run_hosted_check,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._command_runner = command_runner
        self._job_runner = job_runner
        self._smoke_runner = smoke_runner
        self._target_verifier = target_verifier
        self._environment = dict(environment if environment is not None else os.environ)

    def read_app(self, authority: dict[str, object]) -> Mapping[str, object]:
        target = _mapping(authority, "target")
        command = [
            "az",
            "containerapp",
            "show",
            "--subscription",
            _string(target, "subscription_id"),
            "--resource-group",
            _string(target, "resource_group"),
            "--name",
            _string(target, "app"),
            "--only-show-errors",
            "--output",
            "json",
        ]
        try:
            completed = self._command_runner(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
                env=self._cli_environment(),
            )
            if len(completed.stdout) > 1_000_000:
                raise ValueError("response_too_large")
            payload = json.loads(completed.stdout)
        except (
            OSError,
            subprocess.SubprocessError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise OperatorRotationExecutionError(
                "rotation_preflight_app_unavailable"
            ) from error
        if not isinstance(payload, Mapping):
            raise OperatorRotationExecutionError("rotation_preflight_app_invalid")
        return payload

    def read_health(self, base_url: str) -> Mapping[str, object]:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.path != "/health/ready"
            or parsed.query
            or parsed.fragment
        ):
            raise OperatorRotationExecutionError("rotation_preflight_health_invalid")
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        request = Request(base_url, method="GET", headers={"Cache-Control": "no-cache"})
        try:
            with build_opener(HTTPSHandler(context=context)).open(
                request, timeout=15
            ) as response:
                if (
                    response.geturl() != base_url
                    or response.status != 200
                    or response.headers.get_content_type() != "application/json"
                ):
                    raise OperatorRotationExecutionError(
                        "rotation_preflight_health_invalid"
                    )
                body = response.read(4_097)
            if len(body) > 4_096:
                raise OperatorRotationExecutionError(
                    "rotation_preflight_health_invalid"
                )
            payload = json.loads(body)
        except OperatorRotationExecutionError:
            raise
        except (
            HTTPError,
            URLError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            raise OperatorRotationExecutionError(
                "rotation_preflight_health_unavailable"
            ) from error
        if not isinstance(payload, Mapping):
            raise OperatorRotationExecutionError("rotation_preflight_health_invalid")
        return payload

    def stage_rotation_job(
        self,
        authority: dict[str, object],
        *,
        current_password_hash: str,
        pending_password_hash: str,
    ) -> None:
        self._deploy_rotation_job(
            authority,
            phase="stage",
            application_password_hash=current_password_hash,
            rotation_password_hash=pending_password_hash,
            rotation_enabled=True,
        )

    def run_forward_job(self, authority: dict[str, object]) -> ForwardJobResult:
        target = _mapping(authority, "target")
        rotation_id = _string(authority, "rotation_id")
        job_name = self._rotation_job_name(authority)
        try:
            execution_id = self._job_runner(
                subscription_id=_string(target, "subscription_id"),
                resource_group=_string(target, "resource_group"),
                job_name=job_name,
                timeout_seconds=900,
                environment=self._cli_environment(),
            )
        except (AzureJobFailed, OSError, subprocess.SubprocessError) as error:
            raise OperatorRotationExecutionError(
                "forward_job_outcome_unknown",
                rotation_id=rotation_id,
            ) from error
        if (
            not isinstance(execution_id, str)
            or re.fullmatch(r"[a-z][a-z0-9-]{2,62}", execution_id) is None
        ):
            raise OperatorRotationExecutionError(
                "forward_job_outcome_unknown",
                rotation_id=rotation_id,
            )
        return self._read_forward_job_result(
            authority,
            job_name=job_name,
            execution_id=execution_id,
        )

    def activate_target_app(
        self,
        authority: dict[str, object],
        *,
        pending_password_hash: str,
        target_revision_suffix: str,
    ) -> None:
        self._deploy_application(
            authority,
            application_password_hash=pending_password_hash,
            rotation_password_hash=pending_password_hash,
            application_revision_suffix=target_revision_suffix,
        )

    def verify_target_app(
        self,
        authority: dict[str, object],
        *,
        target_revision_suffix: str,
    ) -> None:
        target = _mapping(authority, "target")
        source = _mapping(authority, "source")
        try:
            self._target_verifier(
                subscription_id=_string(target, "subscription_id"),
                resource_group=_string(target, "resource_group"),
                app_name=_string(target, "app"),
                image=_string(source, "image"),
                check="health",
                expected_url=f"https://{_string(target, 'fqdn')}",
                expected_revision_suffix=target_revision_suffix,
                az_runner=self._read_only_runner,
            )
        except (HostedCheckInvalid, OperatorRotationExecutionError) as error:
            raise OperatorRotationExecutionError("rotation_target_not_ready") from error

    def smoke_login_logout(
        self,
        authority: dict[str, object],
        *,
        pending_password: str,
    ) -> None:
        self._smoke_runner(authority, pending_password=pending_password)

    def remove_rotation_material(
        self,
        authority: dict[str, object],
        *,
        pending_password_hash: str,
    ) -> None:
        self._deploy_rotation_job(
            authority,
            phase="cleanup",
            application_password_hash=pending_password_hash,
            rotation_password_hash="",
            rotation_enabled=False,
        )

    def _deploy_rotation_job(
        self,
        authority: Mapping[str, object],
        *,
        phase: str,
        application_password_hash: str,
        rotation_password_hash: str,
        rotation_enabled: bool,
    ) -> None:
        target = _mapping(authority, "target")
        source = _mapping(authority, "source")
        deployment = _mapping(authority, "deployment")
        parameters = _mapping(deployment, "parameters")
        rotation_id = _string(authority, "rotation_id")
        if (
            phase not in {"stage", "cleanup"}
            or not application_password_hash
        ):
            raise OperatorRotationExecutionError("rotation_deployment_invalid")
        if rotation_enabled and not rotation_password_hash:
            raise OperatorRotationExecutionError("rotation_deployment_invalid")
        command = [
            "az",
            "deployment",
            "group",
            "create",
            "--subscription",
            _string(target, "subscription_id"),
            "--resource-group",
            _string(target, "resource_group"),
            "--name",
            f"rotation-{rotation_id[:12]}-{phase}",
            "--parameters",
            str(
                PROJECT_ROOT
                / "infra/environments/operator-rotation-job.bicepparam"
            ),
            *self._rotation_job_parameter_arguments(parameters),
            f"operatorRotationEnabled={str(rotation_enabled).lower()}",
            f"containerImage={_string(source, 'image')}",
            "--mode",
            "Incremental",
            "--output",
            "none",
            "--only-show-errors",
        ]
        try:
            self._command_runner(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=600,
                env=self._deployment_environment(
                    authority,
                    application_password_hash=application_password_hash,
                    rotation_password_hash=rotation_password_hash,
                    rotation_enabled=rotation_enabled,
                ),
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise OperatorRotationExecutionError(
                "rotation_deployment_failed",
                rotation_id=rotation_id,
            ) from error

    def _deploy_application(
        self,
        authority: Mapping[str, object],
        *,
        application_password_hash: str,
        rotation_password_hash: str,
        application_revision_suffix: str,
    ) -> None:
        target = _mapping(authority, "target")
        source = _mapping(authority, "source")
        deployment = _mapping(authority, "deployment")
        parameters = _mapping(deployment, "parameters")
        rotation_id = _string(authority, "rotation_id")
        if (
            not application_password_hash
            or not rotation_password_hash
            or re.fullmatch(r"(?:rotate|inverse)-[0-9a-f]{12}", application_revision_suffix)
            is None
        ):
            raise OperatorRotationExecutionError("rotation_deployment_invalid")
        command = [
            "az",
            "deployment",
            "group",
            "create",
            "--subscription",
            _string(target, "subscription_id"),
            "--resource-group",
            _string(target, "resource_group"),
            "--name",
            f"rotation-{rotation_id[:12]}-activate",
            "--parameters",
            str(PROJECT_ROOT / "infra/environments/demo.bicepparam"),
            *self._public_parameter_arguments(parameters),
            "deploymentEnabled=true",
            "applicationEnabled=true",
            "operatorRotationEnabled=true",
            f"containerImage={_string(source, 'image')}",
            f"applicationRevisionSuffix={application_revision_suffix}",
            "--mode",
            "Incremental",
            "--output",
            "none",
            "--only-show-errors",
        ]
        try:
            self._command_runner(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=600,
                env=self._deployment_environment(
                    authority,
                    application_password_hash=application_password_hash,
                    rotation_password_hash=rotation_password_hash,
                    rotation_enabled=True,
                ),
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise OperatorRotationExecutionError(
                "rotation_deployment_failed",
                rotation_id=rotation_id,
            ) from error

    def _read_forward_job_result(
        self,
        authority: Mapping[str, object],
        *,
        job_name: str,
        execution_id: str,
    ) -> ForwardJobResult:
        target = _mapping(authority, "target")
        rotation_id = _string(authority, "rotation_id")
        command = [
            "az",
            "containerapp",
            "job",
            "logs",
            "show",
            "--subscription",
            _string(target, "subscription_id"),
            "--resource-group",
            _string(target, "resource_group"),
            "--name",
            job_name,
            "--execution",
            execution_id,
            "--container",
            "operator-rotation",
            "--tail",
            "20",
            "--format",
            "json",
            "--only-show-errors",
        ]
        try:
            completed = self._command_runner(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
                env=self._cli_environment(),
            )
            if len(completed.stdout) > 65_536:
                raise ValueError("logs_too_large")
            payload = json.loads(completed.stdout)
        except (
            OSError,
            subprocess.SubprocessError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise OperatorRotationExecutionError(
                "forward_job_result_unavailable",
                rotation_id=rotation_id,
            ) from error
        candidates: list[dict[str, object]] = []
        for value in self._log_strings(payload):
            try:
                candidate = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(candidate, dict):
                candidates.append(candidate)
        matches = [
            candidate
            for candidate in candidates
            if candidate.get("rotation_id") == rotation_id
            and candidate.get("status") in {"rotated", "already_rotated"}
            and set(candidate)
            == {
                "rotation_id",
                "status",
                "revoked_session_count",
                "deleted_ephemeral_chat_count",
            }
        ]
        if len(matches) != 1:
            raise OperatorRotationExecutionError(
                "forward_job_result_invalid",
                rotation_id=rotation_id,
            )
        match = matches[0]
        revoked = match["revoked_session_count"]
        deleted = match["deleted_ephemeral_chat_count"]
        if (
            type(revoked) is not int
            or revoked < 0
            or type(deleted) is not int
            or deleted < 0
        ):
            raise OperatorRotationExecutionError(
                "forward_job_result_invalid",
                rotation_id=rotation_id,
            )
        return ForwardJobResult(
            execution_id=execution_id,
            status=str(match["status"]),
            revoked_session_count=revoked,
            deleted_ephemeral_chat_count=deleted,
        )

    @staticmethod
    def _log_strings(payload: object) -> list[str]:
        if isinstance(payload, str):
            return [payload]
        if isinstance(payload, Mapping):
            values: list[str] = []
            for value in payload.values():
                values.extend(AzureRotationOperations._log_strings(value))
            return values
        if isinstance(payload, list):
            values = []
            for value in payload:
                values.extend(AzureRotationOperations._log_strings(value))
            return values
        return []

    def _deployment_environment(
        self,
        authority: Mapping[str, object],
        *,
        application_password_hash: str,
        rotation_password_hash: str,
        rotation_enabled: bool,
    ) -> dict[str, str]:
        environment = self._cli_environment()
        for name in (
            "BIZPULSE_DEPLOY_POSTGRES_PASSWORD",
            "BIZPULSE_DEPLOY_SESSION_PEPPER",
        ):
            value = self._environment.get(name)
            if not isinstance(value, str) or not value:
                raise OperatorRotationExecutionError(
                    "rotation_deployment_secret_unavailable"
                )
            environment[name] = value
        environment["BIZPULSE_DEPLOY_OPERATOR_PASSWORD_HASH"] = (
            application_password_hash
        )
        environment["BIZPULSE_DEPLOY_OPERATOR_ROTATION_PASSWORD_HASH"] = (
            rotation_password_hash if rotation_enabled else ""
        )
        environment["BIZPULSE_DEPLOY_OPERATOR_ROTATION_EXPECTED_HASH_SHA256"] = (
            _string(_mapping(authority, "expected"), "old_hash_sha256")
            if rotation_enabled
            else ""
        )
        environment["BIZPULSE_DEPLOY_OPERATOR_ROTATION_ID"] = (
            _string(authority, "rotation_id") if rotation_enabled else ""
        )
        return environment

    def _cli_environment(self) -> dict[str, str]:
        return {
            name: value
            for name in ("AZURE_CONFIG_DIR", "HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")
            if isinstance((value := self._environment.get(name)), str) and value
        }

    def _read_only_runner(self, command: Sequence[str], **kwargs: Any):
        return self._command_runner(
            command,
            **kwargs,
            env=self._cli_environment(),
        )

    @staticmethod
    def _public_parameter_arguments(parameters: Mapping[str, object]) -> list[str]:
        arguments: list[str] = []
        for name in sorted(parameters):
            value = parameters[name]
            if type(value) is bool:
                rendered = str(value).lower()
            elif type(value) in {int, str}:
                rendered = str(value)
            elif name == "tags" and isinstance(value, Mapping):
                rendered = json.dumps(value, separators=(",", ":"), sort_keys=True)
            else:
                raise OperatorRotationExecutionError("rotation_deployment_invalid")
            arguments.append(f"{name}={rendered}")
        return arguments

    @staticmethod
    def _rotation_job_parameter_arguments(
        parameters: Mapping[str, object],
    ) -> list[str]:
        if not _ROTATION_JOB_DEPLOYMENT_PARAMETER_NAMES.issubset(parameters):
            raise OperatorRotationExecutionError("rotation_deployment_invalid")
        return AzureRotationOperations._public_parameter_arguments(
            {
                name: parameters[name]
                for name in _ROTATION_JOB_DEPLOYMENT_PARAMETER_NAMES
            }
        )

    @staticmethod
    def _rotation_job_name(authority: Mapping[str, object]) -> str:
        parameters = _mapping(_mapping(authority, "deployment"), "parameters")
        prefix = _string(parameters, "namePrefix")
        return f"{prefix}-rotate-operator"[:32]


def _canonical_sha256(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _read_authority(path: Path) -> dict[str, object]:
    try:
        source = path.resolve()
        source.relative_to(PROJECT_ROOT.resolve())
        if stat.S_IMODE(source.stat().st_mode) != 0o600:
            raise OperatorRotationExecutionError("rotation_package_permissions_invalid")
        payload = json.loads(source.read_text())
    except OperatorRotationExecutionError:
        raise
    except ValueError as error:
        raise OperatorRotationExecutionError(
            "rotation_package_outside_project"
        ) from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OperatorRotationExecutionError("rotation_package_unreadable") from error
    if not isinstance(payload, dict):
        raise OperatorRotationExecutionError("rotation_package_invalid")
    rotation_id = payload.get("rotation_id")
    delivery = payload.get("delivery")
    without_id = {key: value for key, value in payload.items() if key != "rotation_id"}
    if (
        payload.get("schema_version") != _SCHEMA_VERSION
        or payload.get("operation")
        not in {"operator-password-rotation", "operator-password-inverse"}
        or not isinstance(rotation_id, str)
        or _SHA256.fullmatch(rotation_id) is None
        or not isinstance(delivery, Mapping)
        or dict(delivery) != {"contract": _DELIVERY_CONTRACT}
        or not hmac.compare_digest(rotation_id, _canonical_sha256(without_id))
    ):
        raise OperatorRotationExecutionError("rotation_package_invalid")
    return payload


def _mapping(parent: Mapping[str, object], name: str) -> dict[str, object]:
    value = parent.get(name)
    if not isinstance(value, Mapping):
        raise OperatorRotationExecutionError("rotation_package_invalid")
    return dict(value)


def _string(mapping: Mapping[str, object], name: str) -> str:
    value = mapping.get(name)
    if not isinstance(value, str):
        raise OperatorRotationExecutionError("rotation_package_invalid")
    return value


def _approved(authority: Mapping[str, object], approved_rotation_id: str) -> str:
    rotation_id = _string(authority, "rotation_id")
    if _SHA256.fullmatch(approved_rotation_id) is None or not hmac.compare_digest(
        rotation_id, approved_rotation_id
    ):
        raise OperatorRotationExecutionError("rotation_approval_invalid")
    return rotation_id


def _fresh_preflight(
    authority: dict[str, object],
    *,
    current: OperatorCredentialPair,
    pending: OperatorCredentialPair,
    operations: RotationOperations,
) -> None:
    """Rebuild the package from fresh read-only state before the first write."""

    target = _mapping(authority, "target")
    source = _mapping(authority, "source")
    deployment = _mapping(authority, "deployment")
    deployment_parameters = _mapping(deployment, "parameters")
    try:
        app = operations.read_app(authority)
        health = operations.read_health(
            f"https://{_string(target, 'fqdn')}/health/ready"
        )
        fresh = build_rotation_authority(
            current=current,
            pending=pending,
            subscription_id=_string(target, "subscription_id"),
            resource_group=_string(target, "resource_group"),
            app_name=_string(target, "app"),
            image=_string(source, "image"),
            git_sha=_string(source, "git_sha"),
            deployment_parameters=deployment_parameters,
            app=app,
            health=health,
        )
    except (OperatorRotationAuthorityInvalid, OperatorRotationExecutionError) as error:
        raise OperatorRotationExecutionError("rotation_preflight_invalid") from error
    if not hmac.compare_digest(
        json.dumps(authority, separators=(",", ":"), sort_keys=True),
        json.dumps(fresh, separators=(",", ":"), sort_keys=True),
    ):
        raise OperatorRotationExecutionError("rotation_preflight_drift")


def _fresh_inverse_preflight(
    authority: dict[str, object],
    *,
    current: OperatorCredentialPair,
    pending: OperatorCredentialPair,
    operations: RotationOperations,
) -> None:
    """Revalidate the failed target without requiring it to be healthy yet."""

    try:
        validate_inverse_rotation_preflight(
            authority=authority,
            current=current,
            pending=pending,
        )
        validate_inverse_rotation_preflight(
            authority=authority,
            current=current,
            pending=pending,
            app=operations.read_app(authority),
        )
    except (OperatorRotationAuthorityInvalid, OperatorRotationExecutionError) as error:
        raise OperatorRotationExecutionError("rotation_preflight_invalid") from error


def _validate_forward_result(
    result: ForwardJobResult,
    *,
    rotation_id: str,
) -> ForwardJobResult:
    if (
        not isinstance(result, ForwardJobResult)
        or not re.fullmatch(r"[a-z][a-z0-9-]{2,62}", result.execution_id)
        or result.status not in {"rotated", "already_rotated"}
        or type(result.revoked_session_count) is not int
        or result.revoked_session_count < 0
        or type(result.deleted_ephemeral_chat_count) is not int
        or result.deleted_ephemeral_chat_count < 0
    ):
        raise OperatorRotationExecutionError(
            "forward_job_result_invalid",
            rotation_id=rotation_id,
        )
    return result


def _write_receipt(
    *,
    authority: Mapping[str, object],
    job: ForwardJobResult,
    path: Path,
) -> Path:
    rotation_id = _string(authority, "rotation_id")
    inverse = authority.get("operation") == "operator-password-inverse"
    receipt: dict[str, object] = {
        "schema_version": _RECEIPT_SCHEMA_VERSION,
        "operation": (
            "operator-password-inverse-receipt"
            if inverse
            else "operator-password-rotation-receipt"
        ),
        "rotation_id": rotation_id,
        "target": _mapping(authority, "target"),
        "source": _mapping(authority, "source"),
        "delivery": _mapping(authority, "delivery"),
        "expected": _mapping(authority, "expected"),
        "job": {
            "execution_id": job.execution_id,
            "status": job.status,
            "revoked_session_count": job.revoked_session_count,
            "deleted_ephemeral_chat_count": job.deleted_ephemeral_chat_count,
        },
        "verified_phases": [
            "fresh_preflight",
            "infrastructure_applied",
            "forward_job_committed",
            "target_app_ready",
            "pending_login_logout",
            "rollback_material_removed",
            *([] if inverse else ["pending_promoted"]),
            *(["pending_retained_after_inverse"] if inverse else []),
        ],
    }
    try:
        destination = path.resolve()
        destination.relative_to(PROJECT_ROOT.resolve())
    except ValueError as error:
        raise OperatorRotationExecutionError(
            "rotation_receipt_outside_project",
            rotation_id=rotation_id,
        ) from error
    serialized = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        try:
            existing = destination.read_text()
        except OSError as error:
            raise OperatorRotationExecutionError(
                "rotation_receipt_unreadable",
                rotation_id=rotation_id,
            ) from error
        if not hmac.compare_digest(existing, serialized):
            raise OperatorRotationExecutionError(
                "rotation_receipt_conflict",
                rotation_id=rotation_id,
            )
        return destination
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(serialized)
        os.chmod(destination, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as error:
        raise OperatorRotationExecutionError(
            "rotation_receipt_write_failed",
            rotation_id=rotation_id,
        ) from error
    return destination


def run_operator_rotation(
    *,
    package_path: Path,
    approved_rotation_id: str,
    keychain: RotationKeychain,
    operations: RotationOperations,
    receipt_path: Path | None = None,
) -> RotationExecutionResult:
    """Run one approved forward or inverse path without automatic retries."""

    authority = _read_authority(package_path)
    rotation_id = _approved(authority, approved_rotation_id)
    inverse = authority.get("operation") == "operator-password-inverse"
    try:
        current = keychain.current_pair()
        pending = keychain.pending_pair()
    except Exception as error:
        raise OperatorRotationExecutionError(
            "rotation_local_keychain_unavailable",
            rotation_id=rotation_id,
        ) from error

    if inverse:
        _fresh_inverse_preflight(
            authority,
            current=current,
            pending=pending,
            operations=operations,
        )
    else:
        _fresh_preflight(
            authority,
            current=current,
            pending=pending,
            operations=operations,
        )
    target_revision_suffix = (
        f"inverse-{rotation_id[:12]}" if inverse else f"rotate-{rotation_id[:12]}"
    )
    application_stage_hash = current.password_hash
    rotation_target_hash = current.password_hash if inverse else pending.password_hash
    target_pair = current if inverse else pending
    try:
        operations.stage_rotation_job(
            authority,
            current_password_hash=application_stage_hash,
            pending_password_hash=rotation_target_hash,
        )
    except Exception as error:
        raise OperatorRotationExecutionError(
            "rotation_infrastructure_apply_failed",
            rotation_id=rotation_id,
        ) from error
    try:
        forward = _validate_forward_result(
            operations.run_forward_job(authority),
            rotation_id=rotation_id,
        )
    except OperatorRotationExecutionError:
        raise
    except Exception as error:
        raise OperatorRotationExecutionError(
            "forward_job_outcome_unknown",
            rotation_id=rotation_id,
        ) from error

    try:
        operations.activate_target_app(
            authority,
            pending_password_hash=target_pair.password_hash,
            target_revision_suffix=target_revision_suffix,
        )
        operations.verify_target_app(
            authority,
            target_revision_suffix=target_revision_suffix,
        )
        operations.smoke_login_logout(
            authority,
            pending_password=target_pair.password,
        )
    except Exception as error:
        raise OperatorRotationExecutionError(
            (
                "inverse_committed_manual_intervention_required"
                if inverse
                else "forward_committed_manual_inverse_required"
            ),
            rotation_id=rotation_id,
        ) from error
    try:
        operations.remove_rotation_material(
            authority,
            pending_password_hash=target_pair.password_hash,
        )
    except Exception as error:
        raise OperatorRotationExecutionError(
            "rotation_cleanup_failed",
            rotation_id=rotation_id,
        ) from error
    if not inverse:
        try:
            keychain.promote_pending(verified_rotation_id=rotation_id)
        except Exception as error:
            raise OperatorRotationExecutionError(
                "rotation_local_promotion_failed",
                rotation_id=rotation_id,
            ) from error
    resolved_receipt = _write_receipt(
        authority=authority,
        job=forward,
        path=receipt_path
        or PROJECT_ROOT
        / "deliverables/operator-password-rotation"
        / f"{rotation_id}.receipt.json",
    )
    return RotationExecutionResult(
        rotation_id=rotation_id,
        job_status=forward.status,
        receipt_path=resolved_receipt,
    )


def _parse_args(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--approved-rotation-id", required=True)
    return parser.parse_args(arguments)


def _default_keychain() -> RotationKeychain:
    from scripts.operator_rotation_keychain import (  # noqa: PLC0415
        MacOSKeychainBackend,
        OperatorRotationKeychain,
    )

    return OperatorRotationKeychain(backend=MacOSKeychainBackend())


def _default_operations() -> RotationOperations:
    return AzureRotationOperations()


def main(arguments: list[str] | None = None) -> int:
    options = _parse_args(arguments)
    try:
        result = run_operator_rotation(
            package_path=Path(options.package),
            approved_rotation_id=options.approved_rotation_id,
            keychain=_default_keychain(),
            operations=_default_operations(),
        )
    except OperatorRotationExecutionError as error:
        print("rotation=stopped", file=sys.stderr)
        print(f"reason={error.code}", file=sys.stderr)
        if error.rotation_id is not None:
            print(f"rotation_id={error.rotation_id}", file=sys.stderr)
        if error.code == "forward_committed_manual_inverse_required":
            print(
                "next_step=python scripts/generate_operator_rotation_authority.py "
                f"--inverse-from {options.package};separately_approve_the_new_package;do_not_retry",
                file=sys.stderr,
            )
        return 2
    except Exception:
        print("rotation=stopped", file=sys.stderr)
        print("reason=rotation_controller_unavailable", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "job_status": result.job_status,
                "receipt": str(result.receipt_path),
                "rotation_id": result.rotation_id,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
