from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import re
from uuid import uuid4

import pytest
from pydantic import SecretStr

from src.ai.credential_validation import CredentialValidationResult
from src.repositories.admin_ai import AIControlBusy, AIControlProjection
from src.secrets.azure_openai import OpenAISecretUnavailable, SecretVersion
from src.services.openai_key_rotation_service import (
    AIKeyRotationFailed,
    OpenAIKeyRotationService,
)
from src.services.ai_control_service import (
    AIReauthenticationFailed,
    AIStateConflict,
)
from src.services.operator_auth_service import OperatorPrincipal, RequestMeta
from src.services.operator_auth_service import AuthenticationRateLimited

WORKSPACE_ID = "synthetic-demo"
KEY_NAME = "openai-api-key"
NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
PASSWORD = "operator-password-sentinel"
OLD_KEY = "old-api-key-sentinel"
NEW_KEY = "new-api-key-sentinel"


class FakeStore:
    def __init__(self, state: AIControlProjection) -> None:
        self.state = state
        self.audits: list[dict[str, object]] = []
        self.busy = False
        self.fail_audit = False
        self.initialized = True
        self.initialized_on_entry = True
        self.ambiguous_commit_count = 0


class FakeUnitOfWork:
    def __init__(self, store: FakeStore) -> None:
        self._store = store
        self.connection = None

    def __enter__(self):
        self.connection = FakeStore(deepcopy(self._store.state))
        self.connection.audits = deepcopy(self._store.audits)
        self.connection.busy = self._store.busy
        self.connection.fail_audit = self._store.fail_audit
        self.connection.initialized = self._store.initialized
        self.connection.initialized_on_entry = self._store.initialized
        self.connection.locked = False
        return self

    def __exit__(self, exception_type, _exception, _traceback) -> bool:
        if exception_type is None:
            self._store.state = self.connection.state
            self._store.audits = self.connection.audits
            self._store.initialized = self.connection.initialized
            if self._store.ambiguous_commit_count and self.connection.locked:
                self._store.ambiguous_commit_count -= 1
                raise RuntimeError("commit acknowledgement lost")
        return False


class FakeRepository:
    def __init__(self, connection: FakeStore) -> None:
        self._connection = connection

    def get_or_create(self, _workspace_id: str, *, now: datetime):
        del now
        self._connection.initialized = True
        return self._connection.state

    def lock(self, _workspace_id: str):
        if not self._connection.initialized_on_entry:
            raise RuntimeError("initialization must commit before row lock")
        if not self._connection.initialized:
            raise RuntimeError("control row missing")
        if self._connection.busy:
            raise AIControlBusy(AIControlBusy.code)
        self._connection.locked = True
        return self._connection.state

    def activate_key(self, **values):
        state = self._connection.state
        if values["expected_revision"] != state.revision:
            return None
        activated = replace(
            state,
            key_name=values["key_name"],
            key_version=values["key_version"],
            key_reference=values["key_reference"],
            key_fingerprint=values["key_fingerprint"],
            verified_at=values["verified_at"],
            key_validation_state="verified",
            revision=state.revision + 1,
            updated_by_operator_id=values["updated_by_operator_id"],
            updated_at=values["now"],
        )
        self._connection.state = activated
        return activated

    def append_audit(self, **values):
        if self._connection.fail_audit:
            raise RuntimeError("audit persistence failed")
        self._connection.audits.append(values)
        return values


class FakeAuthService:
    def __init__(
        self,
        accepted: bool = True,
        error: Exception | None = None,
    ) -> None:
        self.accepted = accepted
        self.error = error
        self.calls = 0

    def reauthenticate(self, _principal, password: SecretStr, _request_meta) -> bool:
        self.calls += 1
        value = password.get_secret_value()
        try:
            if self.error is not None:
                raise self.error
            return self.accepted and value == PASSWORD
        finally:
            value = ""


class FakeValidator:
    def __init__(self, *statuses: str) -> None:
        self._statuses = list(statuses)
        self.calls = 0

    def validate(self, candidate: str) -> CredentialValidationResult:
        assert candidate in {OLD_KEY, NEW_KEY}
        self.calls += 1
        status = self._statuses.pop(0)
        return CredentialValidationResult(status, None)


class FakeSecretManager:
    def __init__(self, *, configured: bool = True) -> None:
        self.values = {"old-version": OLD_KEY} if configured else {}
        self.latest_value = OLD_KEY if configured else None
        self.reads: list[str] = []
        self.write_count = 0
        self.fail_write_number: int | None = None
        self.mutate_then_raise_number: int | None = None
        self.readback_value: str | None = None

    def read(self, version: str) -> SecretVersion:
        self.reads.append(version)
        try:
            value = self.values[version]
        except KeyError:
            raise OpenAISecretUnavailable("openai_secret_unavailable") from None
        if version.startswith("written-") and self.readback_value is not None:
            value = self.readback_value
        return SecretVersion(value=value, version=version)

    def write(self, value: str) -> SecretVersion:
        self.write_count += 1
        if self.fail_write_number == self.write_count:
            raise OpenAISecretUnavailable("openai_secret_unavailable")
        version = f"written-{self.write_count}"
        self.values[version] = value
        self.latest_value = value
        if self.mutate_then_raise_number == self.write_count:
            raise OpenAISecretUnavailable("openai_secret_unavailable")
        return SecretVersion(value=value, version=version)


def control_state(*, configured: bool = True) -> AIControlProjection:
    return AIControlProjection(
        workspace_id=WORKSPACE_ID,
        operator_enabled=configured,
        demo_enabled=False,
        key_name=KEY_NAME if configured else None,
        key_version="old-version" if configured else None,
        key_reference=f"{KEY_NAME}/old-version" if configured else None,
        key_fingerprint="a" * 64 if configured else None,
        verified_at=NOW if configured else None,
        key_validation_state="verified" if configured else "unconfigured",
        revision=0,
        updated_by_operator_id=None,
        updated_at=NOW,
    )


def principal(*, workspace_id: str = WORKSPACE_ID) -> OperatorPrincipal:
    return OperatorPrincipal(
        session_id=uuid4(),
        operator_id=uuid4(),
        workspace_id=workspace_id,
        login_name="operator",
        idle_expires_at=NOW + timedelta(minutes=30),
        absolute_expires_at=NOW + timedelta(hours=2),
    )


def request_meta() -> RequestMeta:
    return RequestMeta(source_address_hash="source-hash", now=NOW)


def service_for(
    store: FakeStore,
    secrets: FakeSecretManager,
    validator: FakeValidator,
    auth: FakeAuthService | None = None,
) -> OpenAIKeyRotationService:
    return OpenAIKeyRotationService(
        engine=store,
        workspace_id=WORKSPACE_ID,
        key_name=KEY_NAME,
        operator_auth_service=auth or FakeAuthService(),
        secret_manager=secrets,
        credential_validator=validator,
        session_pepper=b"session-pepper-for-key-fingerprint",
        uow_factory=FakeUnitOfWork,
        repository_factory=FakeRepository,
        clock=lambda: NOW,
    )


def rotation_arguments(**overrides):
    values = {
        "principal": principal(),
        "current_password": SecretStr(PASSWORD),
        "request_meta": request_meta(),
        "candidate": SecretStr(NEW_KEY),
        "expected_revision": 0,
        "request_id": "request-rotation-1",
    }
    values.update(overrides)
    return values


def test_rotation_activates_exact_readback_and_preserves_channel_flags() -> None:
    store = FakeStore(control_state())
    secrets = FakeSecretManager()
    validator = FakeValidator("verified", "verified")
    service = service_for(store, secrets, validator)

    activated = service.rotate(**rotation_arguments())

    assert validator.calls == 2
    assert secrets.reads == ["old-version", "written-1"]
    assert secrets.latest_value == NEW_KEY
    assert activated.key_name == KEY_NAME
    assert activated.key_version == "written-1"
    assert activated.key_reference == f"{KEY_NAME}/written-1"
    assert re.fullmatch(r"[0-9a-f]{64}", activated.key_fingerprint or "")
    assert NEW_KEY not in (activated.key_fingerprint or "")
    assert activated.operator_enabled is True
    assert activated.demo_enabled is False
    assert store.audits[0]["action"] == "key.rotate"
    assert store.audits[0]["result"] == "succeeded"
    assert NEW_KEY not in repr(store.audits)
    assert OLD_KEY not in repr(store.audits)


def test_first_rotation_initializes_fail_closed_row_before_lock() -> None:
    store = FakeStore(control_state(configured=False))
    store.initialized = False
    secrets = FakeSecretManager(configured=False)
    validator = FakeValidator("verified", "verified")
    service = service_for(store, secrets, validator)

    activated = service.rotate(**rotation_arguments())

    assert store.initialized is True
    assert activated.key_version == "written-1"
    assert activated.operator_enabled is False
    assert activated.demo_enabled is False


def test_ambiguous_commit_reconciles_activated_binding_without_compensation() -> None:
    store = FakeStore(control_state())
    store.ambiguous_commit_count = 1
    secrets = FakeSecretManager()
    validator = FakeValidator("verified", "verified")
    service = service_for(store, secrets, validator)

    activated = service.rotate(**rotation_arguments())

    assert activated.key_version == "written-1"
    assert store.state.key_version == "written-1"
    assert secrets.latest_value == NEW_KEY
    assert secrets.write_count == 1
    assert store.audits[0]["result"] == "succeeded"


def test_rejected_candidate_never_reaches_key_vault_and_is_not_retried() -> None:
    store = FakeStore(control_state())
    secrets = FakeSecretManager()
    validator = FakeValidator("rejected")
    service = service_for(store, secrets, validator)

    with pytest.raises(AIKeyRotationFailed) as failure:
        service.rotate(**rotation_arguments())

    assert str(failure.value) == "ADMIN_AI_KEY_REJECTED"
    assert NEW_KEY not in repr(failure.value)
    assert validator.calls == 1
    assert secrets.reads == ["old-version"]
    assert secrets.write_count == 0
    assert store.state.key_version == "old-version"
    assert store.audits[0]["safe_error_code"] == "ADMIN_AI_KEY_REJECTED"


def test_post_write_validation_failure_restores_old_secret() -> None:
    store = FakeStore(control_state())
    secrets = FakeSecretManager()
    validator = FakeValidator("verified", "rejected")
    service = service_for(store, secrets, validator)

    with pytest.raises(AIKeyRotationFailed) as failure:
        service.rotate(**rotation_arguments())

    assert str(failure.value) == "ADMIN_AI_KEY_REJECTED"
    assert secrets.latest_value == OLD_KEY
    assert secrets.write_count == 2
    assert store.state.key_version == "old-version"
    assert store.state.operator_enabled is True
    assert store.audits[0]["result"] == "failed"


def test_unknown_readback_is_not_retried_and_restores_prior_value() -> None:
    store = FakeStore(control_state())
    secrets = FakeSecretManager()
    validator = FakeValidator("verified", "unknown")
    service = service_for(store, secrets, validator)

    with pytest.raises(AIKeyRotationFailed) as failure:
        service.rotate(**rotation_arguments())

    assert str(failure.value) == "ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN"
    assert validator.calls == 2
    assert secrets.latest_value == OLD_KEY
    assert store.state.key_version == "old-version"


def test_different_value_at_written_version_is_never_activated() -> None:
    store = FakeStore(control_state())
    secrets = FakeSecretManager()
    secrets.readback_value = OLD_KEY
    validator = FakeValidator("verified", "verified")
    service = service_for(store, secrets, validator)

    with pytest.raises(AIKeyRotationFailed) as failure:
        service.rotate(**rotation_arguments())

    assert str(failure.value) == "ADMIN_AI_SECRET_UNAVAILABLE"
    assert validator.calls == 1
    assert store.state.key_version == "old-version"
    assert secrets.latest_value == OLD_KEY


def test_initial_configuration_failure_remains_unconfigured_and_disabled() -> None:
    store = FakeStore(control_state(configured=False))
    secrets = FakeSecretManager(configured=False)
    validator = FakeValidator("verified", "rejected")
    service = service_for(store, secrets, validator)

    with pytest.raises(
        AIKeyRotationFailed,
        match="ADMIN_AI_RECONCILIATION_REQUIRED",
    ):
        service.rotate(**rotation_arguments())

    assert secrets.write_count == 1
    assert store.state.key_validation_state == "unconfigured"
    assert store.state.key_version is None
    assert store.state.operator_enabled is False
    assert store.state.demo_enabled is False


def test_stale_revision_stops_before_validation_or_secret_access() -> None:
    store = FakeStore(control_state())
    secrets = FakeSecretManager()
    validator = FakeValidator("verified")
    service = service_for(store, secrets, validator)

    with pytest.raises(AIStateConflict, match="ADMIN_AI_STATE_CONFLICT"):
        service.rotate(**rotation_arguments(expected_revision=99))

    assert validator.calls == 0
    assert secrets.reads == []
    assert secrets.write_count == 0


def test_busy_lock_stops_before_validation_or_secret_access() -> None:
    store = FakeStore(control_state())
    store.busy = True
    secrets = FakeSecretManager()
    validator = FakeValidator("verified")
    service = service_for(store, secrets, validator)

    with pytest.raises(AIControlBusy, match="ADMIN_AI_OPERATION_BUSY"):
        service.rotate(**rotation_arguments())

    assert validator.calls == 0
    assert secrets.reads == []
    assert secrets.write_count == 0


def test_reauthentication_failure_stops_before_database_and_provider_work() -> None:
    store = FakeStore(control_state())
    store.busy = True
    secrets = FakeSecretManager()
    validator = FakeValidator("verified")
    service = service_for(store, secrets, validator, FakeAuthService(False))

    with pytest.raises(AIReauthenticationFailed):
        service.rotate(
            **rotation_arguments(current_password=SecretStr("wrong-password"))
        )

    assert validator.calls == 0
    assert secrets.reads == []
    assert secrets.write_count == 0


def test_reauthentication_rate_limit_is_not_misreported_as_key_vault_failure() -> None:
    store = FakeStore(control_state())
    secrets = FakeSecretManager()
    validator = FakeValidator("verified")
    auth = FakeAuthService(error=AuthenticationRateLimited())
    service = service_for(store, secrets, validator, auth)

    with pytest.raises(AuthenticationRateLimited) as failure:
        service.rotate(**rotation_arguments())

    assert validator.calls == 0
    assert secrets.reads == []
    assert secrets.write_count == 0
    assert failure.value.__context__ is None
    traceback = failure.value.__traceback__
    while traceback is not None:
        for value in traceback.tb_frame.f_locals.values():
            if isinstance(value, SecretStr):
                assert value.get_secret_value() != PASSWORD
            elif isinstance(value, str):
                assert value != PASSWORD
        traceback = traceback.tb_next


def test_audit_failure_rolls_back_activation_and_compensates_latest_secret() -> None:
    store = FakeStore(control_state())
    store.fail_audit = True
    secrets = FakeSecretManager()
    validator = FakeValidator("verified", "verified")
    service = service_for(store, secrets, validator)

    with pytest.raises(AIKeyRotationFailed) as failure:
        service.rotate(**rotation_arguments())

    assert str(failure.value) == "ADMIN_AI_SECRET_UNAVAILABLE"
    assert store.state.key_version == "old-version"
    assert store.state.revision == 0
    assert store.audits == []
    assert secrets.latest_value == OLD_KEY


def test_failed_compensation_keeps_old_exact_binding_and_returns_safe_error() -> None:
    store = FakeStore(control_state())
    secrets = FakeSecretManager()
    secrets.fail_write_number = 2
    validator = FakeValidator("verified", "rejected")
    service = service_for(store, secrets, validator)

    with pytest.raises(AIKeyRotationFailed) as failure:
        service.rotate(**rotation_arguments())

    assert str(failure.value) == "ADMIN_AI_SECRET_UNAVAILABLE"
    assert NEW_KEY not in repr(failure.value)
    assert store.state.key_version == "old-version"
    assert store.state.revision == 0
    assert store.audits[0]["safe_error_code"] == "ADMIN_AI_SECRET_UNAVAILABLE"


def test_failed_compensation_is_not_retried_when_failure_audit_also_fails() -> None:
    store = FakeStore(control_state())
    store.fail_audit = True
    secrets = FakeSecretManager()
    secrets.fail_write_number = 2
    validator = FakeValidator("verified", "rejected")
    service = service_for(store, secrets, validator)

    with pytest.raises(AIKeyRotationFailed, match="ADMIN_AI_SECRET_UNAVAILABLE"):
        service.rotate(**rotation_arguments())

    assert secrets.write_count == 2
    assert store.state.key_version == "old-version"
    assert store.audits == []


def test_secret_manager_failure_is_sanitized_and_does_not_change_binding() -> None:
    store = FakeStore(control_state())
    secrets = FakeSecretManager()
    secrets.fail_write_number = 1
    validator = FakeValidator("verified")
    service = service_for(store, secrets, validator)

    with pytest.raises(AIKeyRotationFailed) as failure:
        service.rotate(**rotation_arguments())

    assert str(failure.value) == "ADMIN_AI_SECRET_UNAVAILABLE"
    assert NEW_KEY not in repr(failure.value)
    assert store.state.key_version == "old-version"
    assert store.audits[0]["safe_error_code"] == "ADMIN_AI_SECRET_UNAVAILABLE"


def test_ambiguous_candidate_write_restores_prior_latest_exactly_once() -> None:
    store = FakeStore(control_state())
    secrets = FakeSecretManager()
    secrets.mutate_then_raise_number = 1
    validator = FakeValidator("verified")
    service = service_for(store, secrets, validator)

    with pytest.raises(AIKeyRotationFailed, match="ADMIN_AI_SECRET_UNAVAILABLE") as failure:
        service.rotate(**rotation_arguments())

    assert secrets.latest_value == OLD_KEY
    assert secrets.write_count == 2
    assert store.state.key_version == "old-version"
    assert NEW_KEY not in repr(failure.value)
    traceback = failure.value.__traceback__
    while traceback is not None:
        assert NEW_KEY not in repr(traceback.tb_frame.f_locals)
        assert OLD_KEY not in repr(traceback.tb_frame.f_locals)
        traceback = traceback.tb_next
