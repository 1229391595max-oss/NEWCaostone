from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr

from src.ai.credential_validation import CredentialValidationResult
from src.repositories.admin_ai import (
    AIControlBusy,
    AIControlKeyBindingError,
    AIControlProjection,
)
from src.secrets.azure_openai import OpenAISecretUnavailable, SecretVersion
from src.services.ai_control_service import (
    AIControlAvailabilityFailed,
    AIChannelDisabled,
    AIControlService,
    AIControlUnavailable,
    AIReauthenticationFailed,
    AIStateConflict,
)
from src.services.operator_auth_service import (
    AuthenticationRateLimited,
    OperatorPrincipal,
    RequestMeta,
)

WORKSPACE_ID = "synthetic-demo"
NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
PASSWORD = "operator-password-sentinel"


class FakeStore:
    def __init__(self, state: AIControlProjection) -> None:
        self.state = state
        self.audits: list[dict[str, object]] = []
        self.busy = False
        self.fail_audit = False
        self.initialized = True
        self.initialized_on_entry = True


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
        return self

    def __exit__(self, exception_type, _exception, _traceback) -> bool:
        if exception_type is None:
            self._store.state = self.connection.state
            self._store.audits = self.connection.audits
            self._store.initialized = self.connection.initialized
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
        return self._connection.state

    def set_channels(self, **values):
        state = self._connection.state
        if values["expected_revision"] != state.revision:
            return None
        if (values["operator_enabled"] or values["demo_enabled"]) and (
            state.key_version is None or state.verified_at is None
        ):
            raise AIControlKeyBindingError(AIControlKeyBindingError.code)
        changed = replace(
            state,
            operator_enabled=values["operator_enabled"],
            demo_enabled=values["demo_enabled"],
            revision=state.revision + 1,
            updated_by_operator_id=values["updated_by_operator_id"],
            updated_at=values["now"],
        )
        self._connection.state = changed
        return changed

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

    def reauthenticate(
        self,
        _principal: OperatorPrincipal,
        password: SecretStr,
        _request_meta: RequestMeta,
    ) -> bool:
        self.calls += 1
        value = password.get_secret_value()
        try:
            if self.error is not None:
                raise self.error
            return self.accepted and value == PASSWORD
        finally:
            value = ""


class FakeSecretManager:
    def __init__(self, value: str = "active-key") -> None:
        self.value = value
        self.reads: list[str] = []
        self.unavailable = False

    def read(self, version: str) -> SecretVersion:
        self.reads.append(version)
        if self.unavailable:
            raise OpenAISecretUnavailable("openai_secret_unavailable")
        return SecretVersion(value=self.value, version=version)


class FakeValidator:
    def __init__(self, status: str = "verified") -> None:
        self.status = status
        self.calls = 0

    def validate(self, candidate: str) -> CredentialValidationResult:
        assert candidate == "active-key"
        self.calls += 1
        return CredentialValidationResult(self.status, None)


def control_state(*, configured: bool = True) -> AIControlProjection:
    return AIControlProjection(
        workspace_id=WORKSPACE_ID,
        operator_enabled=False,
        demo_enabled=False,
        key_name="openai-api-key" if configured else None,
        key_version="old-version" if configured else None,
        key_reference="openai-api-key/old-version" if configured else None,
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
    auth: FakeAuthService | None = None,
    secrets: FakeSecretManager | None = None,
    validator: FakeValidator | None = None,
) -> AIControlService:
    return AIControlService(
        engine=store,
        workspace_id=WORKSPACE_ID,
        operator_auth_service=auth or FakeAuthService(),
        secret_manager=secrets or FakeSecretManager(),
        credential_validator=validator or FakeValidator(),
        uow_factory=FakeUnitOfWork,
        repository_factory=FakeRepository,
        clock=lambda: NOW,
    )


def change_arguments(**overrides):
    values = {
        "principal": principal(),
        "current_password": SecretStr(PASSWORD),
        "request_meta": request_meta(),
        "expected_revision": 0,
        "operator_enabled": True,
        "demo_enabled": False,
        "request_id": "request-1",
    }
    values.update(overrides)
    return values


def test_operator_and_demo_flags_are_independent_and_share_one_binding() -> None:
    store = FakeStore(control_state())
    service = service_for(store)

    changed = service.set_channels(**change_arguments())

    assert service.require_enabled("operator") == "old-version"
    with pytest.raises(AIChannelDisabled, match="AI_CHAT_CHANNEL_DISABLED"):
        service.require_enabled("demo")
    assert changed.demo_enabled is False
    assert changed.key_version == store.state.key_version
    assert store.audits == [
        {
            "workspace_id": WORKSPACE_ID,
            "operator_id": changed.updated_by_operator_id,
            "action": "channels.update",
            "result": "succeeded",
            "safe_error_code": None,
            "prior_revision": 0,
            "resulting_revision": 1,
            "requested_operator_enabled": True,
            "requested_demo_enabled": False,
            "request_id": "request-1",
            "now": NOW,
        }
    ]


def test_enabling_qualifies_the_exact_active_version_without_retry() -> None:
    store = FakeStore(control_state())
    secrets = FakeSecretManager()
    validator = FakeValidator("verified")
    service = service_for(store, secrets=secrets, validator=validator)

    service.set_channels(**change_arguments())

    assert secrets.reads == ["old-version"]
    assert validator.calls == 1


@pytest.mark.parametrize(
    ("status", "code"),
    [
        ("rejected", "ADMIN_AI_KEY_REJECTED"),
        ("unknown", "ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN"),
    ],
)
def test_failed_enablement_qualification_leaves_both_channels_unchanged(
    status: str,
    code: str,
) -> None:
    store = FakeStore(control_state())
    validator = FakeValidator(status)
    service = service_for(store, validator=validator)

    with pytest.raises(AIControlAvailabilityFailed) as failure:
        service.set_channels(**change_arguments())

    assert str(failure.value) == code
    assert validator.calls == 1
    assert store.state.revision == 0
    assert store.audits == []


def test_disabling_channels_does_not_contact_secret_or_provider() -> None:
    store = FakeStore(
        replace(
            control_state(),
            operator_enabled=True,
            demo_enabled=True,
        )
    )
    secrets = FakeSecretManager()
    validator = FakeValidator()
    service = service_for(store, secrets=secrets, validator=validator)

    service.set_channels(**change_arguments(operator_enabled=False, demo_enabled=False))

    assert secrets.reads == []
    assert validator.calls == 0


def test_first_channel_mutation_initializes_fail_closed_row_before_lock() -> None:
    store = FakeStore(control_state())
    store.initialized = False
    service = service_for(store)

    changed = service.set_channels(
        **change_arguments(operator_enabled=False, demo_enabled=False)
    )

    assert store.initialized is True
    assert changed.revision == 1


def test_failed_reauthentication_drops_password_from_service_traceback() -> None:
    store = FakeStore(control_state())
    service = service_for(store, FakeAuthService(False))

    with pytest.raises(AIReauthenticationFailed) as failure:
        service.set_channels(**change_arguments(current_password=SecretStr(PASSWORD)))

    traceback = failure.value.__traceback__
    while traceback is not None:
        if traceback.tb_frame.f_code.co_name in {"set_channels", "_reauthenticate"}:
            for value in traceback.tb_frame.f_locals.values():
                if isinstance(value, SecretStr):
                    assert value.get_secret_value() != PASSWORD
                elif isinstance(value, str):
                    assert value != PASSWORD
        traceback = traceback.tb_next


def test_channel_reauthentication_rate_limit_has_no_password_traceback_chain() -> None:
    store = FakeStore(control_state())
    auth = FakeAuthService(error=AuthenticationRateLimited())
    service = service_for(store, auth)

    with pytest.raises(AuthenticationRateLimited) as failure:
        service.set_channels(**change_arguments())

    assert failure.value.__context__ is None
    traceback = failure.value.__traceback__
    while traceback is not None:
        for value in traceback.tb_frame.f_locals.values():
            if isinstance(value, SecretStr):
                assert value.get_secret_value() != PASSWORD
            elif isinstance(value, str):
                assert value != PASSWORD
        traceback = traceback.tb_next


def test_channel_mutation_requires_current_password_before_locking() -> None:
    store = FakeStore(control_state())
    store.busy = True
    service = service_for(store, FakeAuthService(accepted=False))

    with pytest.raises(
        AIReauthenticationFailed,
        match="ADMIN_REAUTHENTICATION_FAILED",
    ):
        service.set_channels(
            **change_arguments(current_password=SecretStr("wrong-password"))
        )

    assert store.state.revision == 0
    assert store.audits == []


def test_cross_workspace_principal_is_rejected_without_reauthentication() -> None:
    store = FakeStore(control_state())
    auth = FakeAuthService()
    service = service_for(store, auth)

    with pytest.raises(AIReauthenticationFailed):
        service.set_channels(
            **change_arguments(principal=principal(workspace_id="other-workspace"))
        )

    assert auth.calls == 0
    assert store.state.revision == 0


def test_stale_revision_rolls_back_without_audit() -> None:
    store = FakeStore(control_state())
    service = service_for(store)

    with pytest.raises(AIStateConflict, match="ADMIN_AI_STATE_CONFLICT"):
        service.set_channels(**change_arguments(expected_revision=7))

    assert store.state.revision == 0
    assert store.audits == []


def test_concurrent_mutation_returns_busy_without_changing_state() -> None:
    store = FakeStore(control_state())
    store.busy = True
    service = service_for(store)

    with pytest.raises(AIControlBusy, match="ADMIN_AI_OPERATION_BUSY"):
        service.set_channels(**change_arguments())

    assert store.state.revision == 0
    assert store.audits == []


def test_enabling_without_a_verified_binding_fails_closed() -> None:
    store = FakeStore(control_state(configured=False))
    service = service_for(store)

    with pytest.raises(AIControlUnavailable, match="AI_CHAT_UNAVAILABLE"):
        service.set_channels(**change_arguments())

    assert store.state.operator_enabled is False
    assert store.state.demo_enabled is False
    assert store.audits == []


def test_audit_failure_rolls_back_channel_state_atomically() -> None:
    store = FakeStore(control_state())
    store.fail_audit = True
    service = service_for(store)

    with pytest.raises(RuntimeError, match="audit persistence failed"):
        service.set_channels(**change_arguments())

    assert store.state.revision == 0
    assert store.state.operator_enabled is False
    assert store.audits == []


def test_enabled_channel_with_incomplete_binding_fails_closed_on_read() -> None:
    state = replace(
        control_state(),
        operator_enabled=True,
        key_reference=None,
    )
    service = service_for(FakeStore(state))

    with pytest.raises(AIControlUnavailable, match="AI_CHAT_UNAVAILABLE"):
        service.require_enabled("operator")


def test_unknown_actor_kind_fails_closed() -> None:
    service = service_for(FakeStore(control_state()))

    with pytest.raises(AIControlUnavailable, match="AI_CHAT_UNAVAILABLE"):
        service.require_enabled("system")
