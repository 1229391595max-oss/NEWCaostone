from __future__ import annotations

import json
import os
import stat
import subprocess
from email.message import Message
from http.cookiejar import Cookie
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pytest
from argon2 import PasswordHasher

import scripts.run_operator_rotation as executor_module
from scripts.generate_operator_rotation_authority import (
    PROJECT_ROOT,
    build_inverse_rotation_authority,
    build_rotation_authority,
    write_rotation_authority,
)
from scripts.operator_rotation_keychain import OperatorCredentialPair
from scripts.run_operator_rotation import (
    AzureRotationOperations,
    ForwardJobResult,
    OperatorRotationExecutionError,
    RotationExecutionResult,
    run_operator_rotation,
    smoke_operator_login_logout,
)
from src.db.readiness import EXPECTED_SCHEMA_REVISION


def _pair(password: str) -> OperatorCredentialPair:
    return OperatorCredentialPair(
        password=password,
        password_hash=PasswordHasher(
            time_cost=1,
            memory_cost=1_024,
            parallelism=1,
        ).hash(password),
    )


def _app(
    *,
    revision: str = "bp-demo-app--current-abcdef0",
    image: str = "example.azurecr.io/bizpulse@sha256:" + "a" * 64,
) -> dict[str, object]:
    return {
        "name": "bp-demo-app",
        "properties": {
            "provisioningState": "Succeeded",
            "latestReadyRevisionName": revision,
            "latestRevisionName": revision,
            "configuration": {
                "activeRevisionsMode": "Single",
                "ingress": {
                    "fqdn": "bp-demo-app.example.azurecontainerapps.io",
                    "external": True,
                    "traffic": [{"latestRevision": True, "weight": 100}],
                },
            },
            "template": {
                "containers": [
                    {
                        "image": image,
                    }
                ]
            },
        },
    }


def _health() -> dict[str, object]:
    return {
        "status": "ready",
        "checks": {
            "blob": "ok",
            "configuration": "ok",
            "database": "ok",
            "foundation": "ok",
            "migration": EXPECTED_SCHEMA_REVISION,
        },
    }


def _deployment_parameters() -> dict[str, object]:
    return {
        "namePrefix": "bp-demo",
        "location": "centralus",
        "syntheticManifestSha256": "c" * 64,
        "syntheticDatasetVersionId": "00000000-0000-4000-8000-000000000000",
        "registryName": "example",
        "postgresAdministratorLogin": "bpadmin",
        "postgresServerName": "bp-demo-postgres",
        "aiChatEnabled": False,
        "openaiKeyVaultUrl": "",
        "openaiManagedIdentityClientId": "",
        "openaiManagedIdentityResourceId": "",
        "aiBudgetFailureRehearsal": False,
        "aiDailyAttemptLimit": 120,
        "aiMonthlyTokenLimit": 150_000,
        "aiMaxConcurrentTurns": 15,
        "aiSessionAttemptLimitPerMinute": 3,
        "aiGlobalAttemptLimitPerMinute": 20,
        "demoSessionRateLimitPerHour": 50,
        "storageSku": "Standard_LRS",
        "storageAccountName": "bpdemosynthetic",
        "postgresSkuName": "Standard_B1ms",
        "postgresTier": "Burstable",
        "postgresStorageSizeGb": 32,
        "postgresBackupRetentionDays": 7,
        "logRetentionDays": 30,
        "vnetAddressPrefix": "10.40.0.0/16",
        "appSubnetPrefix": "10.40.0.0/23",
        "postgresSubnetPrefix": "10.40.2.0/24",
        "tags": {
            "application": "newcaostone",
            "data_classification": "pure-synthetic",
            "environment": "demo",
            "production_ready": "false",
        },
    }


@dataclass
class _Keychain:
    current: OperatorCredentialPair
    pending: OperatorCredentialPair
    promoted: list[str] = field(default_factory=list)

    def current_pair(self) -> OperatorCredentialPair:
        return self.current

    def pending_pair(self) -> OperatorCredentialPair:
        return self.pending

    def promote_pending(self, *, verified_rotation_id: str) -> None:
        self.promoted.append(verified_rotation_id)
        self.current = self.pending


@dataclass
class _Operations:
    app: dict[str, object]
    health: dict[str, object]
    phases: list[str] = field(default_factory=list)
    smoke_password: str | None = None
    fail_target_check: bool = False
    inverse: bool = False

    def read_app(self, _authority: dict[str, object]) -> dict[str, object]:
        self.phases.append("precheck_app")
        return self.app

    def read_health(self, _base_url: str) -> dict[str, object]:
        assert self.inverse is False
        self.phases.append("precheck_health")
        return self.health

    def stage_rotation_job(
        self,
        _authority: dict[str, object],
        *,
        current_password_hash: str,
        pending_password_hash: str,
    ) -> None:
        if self.inverse:
            assert current_password_hash == pending_password_hash
        else:
            assert current_password_hash != pending_password_hash
        self.phases.append("infrastructure_applied")

    def run_forward_job(self, _authority: dict[str, object]) -> ForwardJobResult:
        self.phases.append("forward_job_committed")
        return ForwardJobResult(
            execution_id="bp-demo-rotate-operator-exec",
            status="rotated",
            revoked_session_count=2,
            deleted_ephemeral_chat_count=1,
        )

    def activate_target_app(
        self,
        _authority: dict[str, object],
        *,
        pending_password_hash: str,
        target_revision_suffix: str,
    ) -> None:
        assert pending_password_hash
        assert target_revision_suffix.startswith(
            "inverse-" if self.inverse else "rotate-"
        )
        self.phases.append("app_activated")

    def verify_target_app(
        self,
        _authority: dict[str, object],
        *,
        target_revision_suffix: str,
    ) -> None:
        assert target_revision_suffix.startswith(
            "inverse-" if self.inverse else "rotate-"
        )
        self.phases.append("app_ready")
        if self.fail_target_check:
            raise RuntimeError("injected_target_readiness_failure")

    def smoke_login_logout(
        self,
        _authority: dict[str, object],
        *,
        pending_password: str,
    ) -> None:
        self.smoke_password = pending_password
        self.phases.append("new_credential_smoked")

    def remove_rotation_material(
        self,
        _authority: dict[str, object],
        *,
        pending_password_hash: str,
    ) -> None:
        assert pending_password_hash
        self.phases.append("rollback_secret_removed")


def _package_and_keychain() -> tuple[Path, dict[str, object], _Keychain]:
    current = _pair("current-operator-password")
    pending = _pair("replacement-operator-password")
    authority = build_rotation_authority(
        current=current,
        pending=pending,
        subscription_id="11111111-1111-4111-8111-111111111111",
        resource_group="rg-bizpulse-demo",
        app_name="bp-demo-app",
        image="example.azurecr.io/bizpulse@sha256:" + "a" * 64,
        git_sha="b" * 40,
        deployment_parameters=_deployment_parameters(),
        app=_app(),
        health=_health(),
    )
    package = PROJECT_ROOT / ".tmp" / f"rotation-package-{uuid4().hex}.json"
    write_rotation_authority(package, authority)
    return package, authority, _Keychain(current=current, pending=pending)


def test_rotation_refuses_an_unapproved_or_drifted_package_before_writes() -> None:
    package, authority, keychain = _package_and_keychain()
    operations = _Operations(app=_app(), health=_health())
    try:
        with pytest.raises(
            OperatorRotationExecutionError,
            match="rotation_approval_invalid",
        ):
            run_operator_rotation(
                package_path=package,
                approved_rotation_id="f" * 64,
                keychain=keychain,
                operations=operations,
            )
        assert operations.phases == []

        operations.app = _app(image="example.azurecr.io/bizpulse@sha256:" + "d" * 64)
        with pytest.raises(
            OperatorRotationExecutionError,
            match="rotation_preflight_drift",
        ):
            run_operator_rotation(
                package_path=package,
                approved_rotation_id=authority["rotation_id"],
                keychain=keychain,
                operations=operations,
            )
        assert "infrastructure_applied" not in operations.phases
        assert keychain.promoted == []
    finally:
        package.unlink(missing_ok=True)


def test_rotation_refuses_a_package_with_nonprivate_permissions() -> None:
    package, authority, keychain = _package_and_keychain()
    operations = _Operations(app=_app(), health=_health())
    try:
        os.chmod(package, 0o644)
        with pytest.raises(
            OperatorRotationExecutionError,
            match="rotation_package_permissions_invalid",
        ):
            run_operator_rotation(
                package_path=package,
                approved_rotation_id=authority["rotation_id"],
                keychain=keychain,
                operations=operations,
            )
        assert operations.phases == []
    finally:
        package.unlink(missing_ok=True)


def test_rotation_runs_one_forward_path_then_promotes_and_writes_redacted_receipt() -> (
    None
):
    package, authority, keychain = _package_and_keychain()
    receipt = PROJECT_ROOT / ".tmp" / f"rotation-receipt-{uuid4().hex}.json"
    operations = _Operations(app=_app(), health=_health())
    try:
        result = run_operator_rotation(
            package_path=package,
            approved_rotation_id=authority["rotation_id"],
            keychain=keychain,
            operations=operations,
            receipt_path=receipt,
        )

        assert result.rotation_id == authority["rotation_id"]
        assert result.job_status == "rotated"
        assert operations.phases == [
            "precheck_app",
            "precheck_health",
            "infrastructure_applied",
            "forward_job_committed",
            "app_activated",
            "app_ready",
            "new_credential_smoked",
            "rollback_secret_removed",
        ]
        assert operations.smoke_password == "replacement-operator-password"
        assert keychain.promoted == [authority["rotation_id"]]
        assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
        receipt_text = receipt.read_text()
        assert "current-operator-password" not in receipt_text
        assert "replacement-operator-password" not in receipt_text
        current_hash = keychain.current.password_hash
        assert current_hash
        assert current_hash not in receipt_text
        assert json.loads(receipt_text)["rotation_id"] == authority["rotation_id"]
    finally:
        package.unlink(missing_ok=True)
        receipt.unlink(missing_ok=True)


def test_forward_commit_that_fails_acceptance_never_promotes_or_auto_rolls_back() -> (
    None
):
    package, authority, keychain = _package_and_keychain()
    operations = _Operations(app=_app(), health=_health(), fail_target_check=True)
    try:
        with pytest.raises(
            OperatorRotationExecutionError,
            match="forward_committed_manual_inverse_required",
        ) as error:
            run_operator_rotation(
                package_path=package,
                approved_rotation_id=authority["rotation_id"],
                keychain=keychain,
                operations=operations,
            )

        assert authority["rotation_id"] in str(error.value)
        assert keychain.promoted == []
        assert operations.phases == [
            "precheck_app",
            "precheck_health",
            "infrastructure_applied",
            "forward_job_committed",
            "app_activated",
            "app_ready",
        ]
    finally:
        package.unlink(missing_ok=True)


def test_separately_approved_inverse_uses_the_exact_reverse_guard_without_promoting_keychain() -> (
    None
):
    forward_package, forward, keychain = _package_and_keychain()
    inverse_package = PROJECT_ROOT / ".tmp" / f"inverse-package-{uuid4().hex}.json"
    receipt = PROJECT_ROOT / ".tmp" / f"inverse-receipt-{uuid4().hex}.json"
    observed_app = _app(revision="bp-demo-app--rotate-0123456789ab")
    inverse = build_inverse_rotation_authority(
        forward_authority=forward,
        current=keychain.current,
        pending=keychain.pending,
        app=observed_app,
    )
    write_rotation_authority(inverse_package, inverse)
    operations = _Operations(
        app=observed_app,
        health=_health(),
        inverse=True,
    )
    try:
        result = run_operator_rotation(
            package_path=inverse_package,
            approved_rotation_id=inverse["rotation_id"],
            keychain=keychain,
            operations=operations,
            receipt_path=receipt,
        )

        assert result.job_status == "rotated"
        assert keychain.promoted == []
        assert keychain.current.password == "current-operator-password"
        assert keychain.pending.password == "replacement-operator-password"
        assert operations.smoke_password == "current-operator-password"
        assert operations.phases == [
            "precheck_app",
            "infrastructure_applied",
            "forward_job_committed",
            "app_activated",
            "app_ready",
            "new_credential_smoked",
            "rollback_secret_removed",
        ]
        receipt_payload = json.loads(receipt.read_text())
        assert receipt_payload["operation"] == "operator-password-inverse-receipt"
        assert "pending_promoted" not in receipt_payload["verified_phases"]
    finally:
        forward_package.unlink(missing_ok=True)
        inverse_package.unlink(missing_ok=True)
        receipt.unlink(missing_ok=True)


def test_inverse_rejects_an_invalid_scope_before_any_azure_read() -> None:
    forward_package, forward, keychain = _package_and_keychain()
    inverse_package = PROJECT_ROOT / ".tmp" / f"inverse-invalid-{uuid4().hex}.json"
    inverse = build_inverse_rotation_authority(
        forward_authority=forward,
        current=keychain.current,
        pending=keychain.pending,
        app=_app(revision="bp-demo-app--rotate-0123456789ab"),
    )
    inverse["target"] = {
        **inverse["target"],
        "subscription_id": "not-a-subscription-id",
    }
    unsigned = {key: value for key, value in inverse.items() if key != "rotation_id"}
    inverse["rotation_id"] = executor_module._canonical_sha256(unsigned)
    write_rotation_authority(inverse_package, inverse)
    operations = _Operations(
        app=_app(revision="bp-demo-app--rotate-0123456789ab"),
        health=_health(),
        inverse=True,
    )
    try:
        with pytest.raises(
            OperatorRotationExecutionError,
            match="rotation_preflight_invalid",
        ):
            run_operator_rotation(
                package_path=inverse_package,
                approved_rotation_id=inverse["rotation_id"],
                keychain=keychain,
                operations=operations,
            )
        assert operations.phases == []
    finally:
        forward_package.unlink(missing_ok=True)
        inverse_package.unlink(missing_ok=True)


def test_azure_operations_keep_hashes_out_of_argv_and_scope_them_per_phase() -> None:
    package, authority, _keychain = _package_and_keychain()
    commands: list[list[str]] = []
    environments: list[dict[str, str]] = []
    smoke_passwords: list[str] = []
    current_hash = "$argon2id$current-operator-hash"
    pending_hash = "$argon2id$pending-operator-hash"

    def runner(command, **kwargs):
        commands.append(list(command))
        environments.append(dict(kwargs.get("env", {})))
        if "logs" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    [
                        {
                            "Log": json.dumps(
                                {
                                    "rotation_id": authority["rotation_id"],
                                    "status": "rotated",
                                    "revoked_session_count": 2,
                                    "deleted_ephemeral_chat_count": 1,
                                }
                            )
                        }
                    ]
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    operations = AzureRotationOperations(
        command_runner=runner,
        job_runner=lambda **_kwargs: "bp-demo-rotate-operator-exec",
        smoke_runner=lambda _authority, *, pending_password: smoke_passwords.append(
            pending_password
        ),
        environment={
            "PATH": "/usr/bin:/bin",
            "HOME": "/tmp/test-home",
            "BIZPULSE_DEPLOY_POSTGRES_PASSWORD": "database-secret",
            "BIZPULSE_DEPLOY_SESSION_PEPPER": "session-pepper-secret",
            "BIZPULSE_BROWSER_OPERATOR_PASSWORD": "must-not-reach-azure",
            "OPENAI_API_KEY": "must-not-reach-azure",
        },
    )
    try:
        operations.stage_rotation_job(
            authority,
            current_password_hash=current_hash,
            pending_password_hash=pending_hash,
        )
        forward = operations.run_forward_job(authority)
        operations.activate_target_app(
            authority,
            pending_password_hash=pending_hash,
            target_revision_suffix="rotate-0123456789ab",
        )
        operations.smoke_login_logout(
            authority,
            pending_password="replacement-operator-password",
        )
        operations.remove_rotation_material(
            authority,
            pending_password_hash=pending_hash,
        )

        assert forward.status == "rotated"
        assert forward.execution_id == "bp-demo-rotate-operator-exec"
        assert smoke_passwords == ["replacement-operator-password"]
        deployment_commands = [
            command for command in commands if "deployment" in command
        ]
        assert len(deployment_commands) == 3
        assert all(
            any(parameter.startswith("tags={") for parameter in command)
            for command in deployment_commands
        )
        assert all(current_hash not in repr(command) for command in commands)
        assert all(pending_hash not in repr(command) for command in commands)
        assert all("database-secret" not in repr(command) for command in commands)
        assert all("session-pepper-secret" not in repr(command) for command in commands)

        (
            stage_environment,
            logs_environment,
            activate_environment,
            cleanup_environment,
        ) = environments
        assert (
            stage_environment["BIZPULSE_DEPLOY_OPERATOR_PASSWORD_HASH"] == current_hash
        )
        assert (
            stage_environment["BIZPULSE_DEPLOY_OPERATOR_ROTATION_PASSWORD_HASH"]
            == pending_hash
        )
        assert (
            stage_environment["BIZPULSE_DEPLOY_OPERATOR_ROTATION_EXPECTED_HASH_SHA256"]
            == authority["expected"]["old_hash_sha256"]
        )
        assert logs_environment == {"HOME": "/tmp/test-home", "PATH": "/usr/bin:/bin"}
        assert (
            activate_environment["BIZPULSE_DEPLOY_OPERATOR_PASSWORD_HASH"]
            == pending_hash
        )
        assert (
            activate_environment["BIZPULSE_DEPLOY_OPERATOR_ROTATION_PASSWORD_HASH"]
            == pending_hash
        )
        assert (
            cleanup_environment["BIZPULSE_DEPLOY_OPERATOR_PASSWORD_HASH"]
            == pending_hash
        )
        assert (
            cleanup_environment["BIZPULSE_DEPLOY_OPERATOR_ROTATION_PASSWORD_HASH"] == ""
        )
        assert (
            cleanup_environment[
                "BIZPULSE_DEPLOY_OPERATOR_ROTATION_EXPECTED_HASH_SHA256"
            ]
            == ""
        )
        assert "BIZPULSE_BROWSER_OPERATOR_PASSWORD" not in stage_environment
        assert "OPENAI_API_KEY" not in stage_environment
        assert "BIZPULSE_DEPLOY_POSTGRES_PASSWORD" not in logs_environment
    finally:
        package.unlink(missing_ok=True)


def test_azure_stage_and_cleanup_deploy_only_the_rotation_job() -> None:
    package, authority, _keychain = _package_and_keychain()
    commands: list[list[str]] = []
    current_hash = "$argon2id$current-operator-hash"
    pending_hash = "$argon2id$pending-operator-hash"

    def runner(command, **_kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    operations = AzureRotationOperations(
        command_runner=runner,
        environment={
            "PATH": "/usr/bin:/bin",
            "HOME": "/tmp/test-home",
            "BIZPULSE_DEPLOY_POSTGRES_PASSWORD": "database-secret",
            "BIZPULSE_DEPLOY_SESSION_PEPPER": "session-pepper-secret",
        },
    )
    try:
        operations.stage_rotation_job(
            authority,
            current_password_hash=current_hash,
            pending_password_hash=pending_hash,
        )
        operations.remove_rotation_material(
            authority,
            pending_password_hash=pending_hash,
        )

        assert len(commands) == 2
        for command in commands:
            assert str(PROJECT_ROOT / "infra/environments/operator-rotation-job.bicepparam") in command
            assert all(not value.startswith("applicationEnabled=") for value in command)
            assert all(not value.startswith("applicationRevisionSuffix=") for value in command)
            assert all(not value.startswith("deploymentEnabled=") for value in command)
            assert any(value.startswith("operatorRotationEnabled=") for value in command)
    finally:
        package.unlink(missing_ok=True)


def test_azure_operations_do_not_forward_provider_key_for_key_vault_ai() -> None:
    current = _pair("current-operator-password")
    pending = _pair("replacement-operator-password")
    authority = build_rotation_authority(
        current=current,
        pending=pending,
        subscription_id="11111111-1111-4111-8111-111111111111",
        resource_group="rg-bizpulse-demo",
        app_name="bp-demo-app",
        image="example.azurecr.io/bizpulse@sha256:" + "a" * 64,
        git_sha="b" * 40,
        deployment_parameters=_deployment_parameters()
        | {
            "aiChatEnabled": True,
            "openaiKeyVaultUrl": "https://bp-ai.vault.azure.net/",
            "openaiManagedIdentityClientId": ("11111111-1111-4111-8111-111111111111"),
            "openaiManagedIdentityResourceId": (
                "/subscriptions/11111111-1111-4111-8111-111111111111/"
                "resourceGroups/rg-bizpulse-demo/providers/"
                "Microsoft.ManagedIdentity/userAssignedIdentities/bp-ai"
            ),
        },
        app=_app(),
        health=_health(),
    )
    captured: dict[str, object] = {}

    def runner(command, **kwargs):
        captured["command"] = command
        captured["environment"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    operations = AzureRotationOperations(
        command_runner=runner,
        environment={
            "PATH": "/usr/bin:/bin",
            "HOME": "/tmp/test-home",
            "BIZPULSE_DEPLOY_POSTGRES_PASSWORD": "database-secret",
            "BIZPULSE_DEPLOY_SESSION_PEPPER": "session-pepper-secret",
            "BIZPULSE_DEPLOY_OPENAI_API_KEY": "must-not-reach-azure",
        },
    )

    operations.stage_rotation_job(
        authority,
        current_password_hash=current.password_hash,
        pending_password_hash=pending.password_hash,
    )

    assert "BIZPULSE_DEPLOY_OPENAI_API_KEY" not in captured["environment"]
    assert "must-not-reach-azure" not in repr(captured["command"])
    assert "must-not-reach-azure" not in repr(captured["environment"])


def test_inverse_stage_scopes_the_reverse_expected_hash_to_the_manual_job() -> None:
    package, forward, keychain = _package_and_keychain()
    inverse = build_inverse_rotation_authority(
        forward_authority=forward,
        current=keychain.current,
        pending=keychain.pending,
        app=_app(revision="bp-demo-app--rotate-0123456789ab"),
    )
    captured: dict[str, object] = {}

    def runner(command, **kwargs):
        captured["command"] = command
        captured["environment"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    operations = AzureRotationOperations(
        command_runner=runner,
        environment={
            "PATH": "/usr/bin:/bin",
            "HOME": "/tmp/test-home",
            "BIZPULSE_DEPLOY_POSTGRES_PASSWORD": "database-secret",
            "BIZPULSE_DEPLOY_SESSION_PEPPER": "session-pepper-secret",
        },
    )
    try:
        operations.stage_rotation_job(
            inverse,
            current_password_hash=keychain.current.password_hash,
            pending_password_hash=keychain.current.password_hash,
        )

        environment = captured["environment"]
        assert environment["BIZPULSE_DEPLOY_OPERATOR_PASSWORD_HASH"] == (
            keychain.current.password_hash
        )
        assert environment["BIZPULSE_DEPLOY_OPERATOR_ROTATION_PASSWORD_HASH"] == (
            keychain.current.password_hash
        )
        assert (
            environment["BIZPULSE_DEPLOY_OPERATOR_ROTATION_EXPECTED_HASH_SHA256"]
            == inverse["expected"]["old_hash_sha256"]
        )
        assert keychain.pending.password_hash not in repr(captured["command"])
    finally:
        package.unlink(missing_ok=True)


def test_cli_uses_the_real_executor_boundary_and_emits_only_redacted_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    package, authority, keychain = _package_and_keychain()
    receipt = PROJECT_ROOT / ".tmp" / f"rotation-cli-receipt-{uuid4().hex}.json"
    calls: dict[str, object] = {}
    try:
        monkeypatch.setattr(executor_module, "_default_keychain", lambda: keychain)
        monkeypatch.setattr(executor_module, "_default_operations", lambda: object())

        def fake_run(**kwargs):
            calls.update(kwargs)
            return RotationExecutionResult(
                rotation_id=authority["rotation_id"],
                job_status="rotated",
                receipt_path=receipt,
            )

        monkeypatch.setattr(executor_module, "run_operator_rotation", fake_run)

        assert (
            executor_module.main(
                [
                    "--package",
                    str(package),
                    "--approved-rotation-id",
                    authority["rotation_id"],
                ]
            )
            == 0
        )

        output = json.loads(capsys.readouterr().out)
        assert output == {
            "job_status": "rotated",
            "receipt": str(receipt),
            "rotation_id": authority["rotation_id"],
        }
        assert calls["keychain"] is keychain
        assert calls["operations"].__class__ is object
        assert "current-operator-password" not in repr(output)
        assert "replacement-operator-password" not in repr(output)
    finally:
        package.unlink(missing_ok=True)


def test_pending_smoke_uses_origin_bound_login_and_immediate_logout_without_outputting_tokens() -> (
    None
):
    _package, authority, _keychain = _package_and_keychain()
    requests = []

    class Response:
        def __init__(self, *, url: str, status: int, body: bytes = b"{}") -> None:
            self._url = url
            self.status = status
            self._body = body
            self.headers = Message()
            self.headers.add_header("Content-Type", "application/json")

        def geturl(self) -> str:
            return self._url

        def read(self, _limit: int) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    class Opener:
        def __init__(self, jar) -> None:
            self._jar = jar

        def open(self, request, *, timeout: int):
            assert timeout == 20
            requests.append(request)
            if request.full_url.endswith("/login"):
                self._jar.set_cookie(
                    Cookie(
                        version=0,
                        name="bp_operator_session",
                        value="opaque-session-token",
                        port=None,
                        port_specified=False,
                        domain="bp-demo-app.example.azurecontainerapps.io",
                        domain_specified=True,
                        domain_initial_dot=False,
                        path="/",
                        path_specified=True,
                        secure=True,
                        expires=None,
                        discard=True,
                        comment=None,
                        comment_url=None,
                        rest={"HttpOnly": None},
                        rfc2109=False,
                    )
                )
                return Response(
                    url=request.full_url,
                    status=201,
                    body=json.dumps({"csrf_token": "x" * 32}).encode(),
                )
            return Response(url=request.full_url, status=204, body=b"")

    try:
        smoke_operator_login_logout(
            authority,
            pending_password="replacement-operator-password",
            opener_factory=Opener,
        )

        assert [request.full_url for request in requests] == [
            "https://bp-demo-app.example.azurecontainerapps.io/api/operator/login",
            "https://bp-demo-app.example.azurecontainerapps.io/api/operator/logout",
        ]
        assert requests[0].get_header("Origin") == (
            "https://bp-demo-app.example.azurecontainerapps.io"
        )
        assert b"replacement-operator-password" in requests[0].data
        assert requests[1].get_header("Origin") == (
            "https://bp-demo-app.example.azurecontainerapps.io"
        )
        assert requests[1].get_header("X-csrf-token") == "x" * 32
    finally:
        _package.unlink(missing_ok=True)
