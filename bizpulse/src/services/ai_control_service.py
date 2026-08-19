"""Transactional runtime gates for the shared OpenAI credential binding."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import re
from typing import Literal, Protocol

from pydantic import SecretStr
from sqlalchemy import Engine

from src.ai.credential_validation import OpenAICredentialValidator
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.admin_ai import (
    AdminAuditProjection,
    AIControlKeyBindingError,
    AIControlProjection,
    AIControlRepository,
)
from src.repositories.idempotency import IdempotencyRepository
from src.secrets.azure_openai import OpenAISecretManager, OpenAISecretUnavailable
from src.services.admin_mutation_idempotency import (
    ADMIN_IDEMPOTENCY_TTL,
    control_projection,
    idempotency_key_hash,
    replay_control_projection,
    request_hash,
)
from src.services.operator_auth_service import (
    AuthenticationRateLimited,
    OperatorAuthService,
    OperatorPrincipal,
    RequestMeta,
)

ActorKind = Literal["operator", "demo"]
_FINGERPRINT = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class AICredentialBinding:
    """Safe immutable identity for one exact server-side credential selection."""

    version: str = field(repr=False)
    binding_id: str
    control_revision: int


class _StableAIControlError(RuntimeError):
    code: str

    def __init__(self) -> None:
        super().__init__(self.code)


class AIChannelDisabled(_StableAIControlError):
    code = "AI_CHAT_CHANNEL_DISABLED"


class AIControlUnavailable(_StableAIControlError):
    code = "AI_CHAT_UNAVAILABLE"


class AIReauthenticationFailed(_StableAIControlError):
    code = "ADMIN_REAUTHENTICATION_FAILED"


class AIStateConflict(_StableAIControlError):
    code = "ADMIN_AI_STATE_CONFLICT"


class AIControlAvailabilityFailed(RuntimeError):
    """A stable, secret-free exact-version qualification failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RepositoryFactory(Protocol):
    def __call__(self, connection: object) -> AIControlRepository: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self, engine: Engine) -> PostgresUnitOfWork: ...


class AIControlService:
    """Read and mutate one workspace's actor-specific AI gates."""

    def __init__(
        self,
        *,
        engine: Engine,
        workspace_id: str,
        operator_auth_service: OperatorAuthService,
        secret_manager: OpenAISecretManager,
        credential_validator: OpenAICredentialValidator,
        uow_factory: UnitOfWorkFactory = PostgresUnitOfWork,
        repository_factory: RepositoryFactory = AIControlRepository,
        session_pepper: bytes | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if session_pepper is not None and (
            not isinstance(session_pepper, bytes) or not session_pepper
        ):
            raise ValueError("session_pepper_missing")
        self._engine = engine
        self._workspace_id = workspace_id
        self._operator_auth_service = operator_auth_service
        self._secrets = secret_manager
        self._validator = credential_validator
        self._uow_factory = uow_factory
        self._repository_factory = repository_factory
        self._session_pepper = session_pepper
        self._clock = clock or (lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return f"AIControlService(workspace_id={self._workspace_id!r})"

    def get(self) -> AIControlProjection:
        with self._uow_factory(self._engine) as uow:
            return self._repository_factory(uow.connection).get_or_create(
                self._workspace_id,
                now=self._clock(),
            )

    def mutation_audit(
        self,
        request_ids: tuple[str, ...],
    ) -> tuple[AdminAuditProjection, ...]:
        with self._uow_factory(self._engine) as uow:
            return self._repository_factory(uow.connection).mutation_audit(
                self._workspace_id,
                request_ids,
            )

    def require_enabled(self, actor_kind: ActorKind) -> str:
        return self.select_binding(actor_kind).version

    def select_binding(self, actor_kind: ActorKind) -> AICredentialBinding:
        if actor_kind not in ("operator", "demo"):
            raise AIControlUnavailable
        state = self.get()
        enabled = (
            state.operator_enabled if actor_kind == "operator" else state.demo_enabled
        )
        if not enabled:
            raise AIChannelDisabled
        if not self._has_verified_binding(state):
            raise AIControlUnavailable
        assert state.key_version is not None
        assert state.key_reference is not None
        assert state.key_fingerprint is not None
        binding_id = hashlib.sha256(
            b"bizpulse-exact-credential-binding-v1\x00"
            + self._workspace_id.encode()
            + b"\x00"
            + state.key_reference.encode()
            + b"\x00"
            + state.key_fingerprint.encode()
        ).hexdigest()
        return AICredentialBinding(
            version=state.key_version,
            binding_id=binding_id,
            control_revision=state.revision,
        )

    def set_channels(
        self,
        *,
        principal: OperatorPrincipal,
        current_password: SecretStr,
        request_meta: RequestMeta,
        expected_revision: int,
        operator_enabled: bool,
        demo_enabled: bool,
        request_id: str,
        idempotency_key: str | None = None,
    ) -> AIControlProjection:
        password = current_password
        current_password = SecretStr("")
        try:
            self._reauthenticate(
                principal=principal,
                current_password=password,
                request_meta=request_meta,
            )
        finally:
            password = SecretStr("")
        key_hash: bytes | None = None
        mutation_hash: bytes | None = None
        deferred_failure: AIControlAvailabilityFailed | AIControlUnavailable | None = (
            None
        )
        changed: AIControlProjection | None = None
        if idempotency_key is not None:
            if self._session_pepper is None:
                raise AIStateConflict
            try:
                key_hash = idempotency_key_hash(
                    self._session_pepper,
                    idempotency_key,
                )
            except ValueError:
                raise AIStateConflict from None
            mutation_hash = request_hash(
                {
                    "expected_revision": expected_revision,
                    "operator_enabled": operator_enabled,
                    "demo_enabled": demo_enabled,
                }
            )
        self._ensure_control_state()
        with self._uow_factory(self._engine) as uow:
            repository = self._repository_factory(uow.connection)
            prior = repository.lock(self._workspace_id)
            receipts = (
                IdempotencyRepository(uow.connection)
                if key_hash is not None and mutation_hash is not None
                else None
            )
            if receipts is not None:
                disposition = receipts.check(
                    scope_type="workspace",
                    scope_id=self._workspace_id,
                    operation="admin_ai_channels",
                    key_hash=key_hash,
                    request_hash=mutation_hash,
                )
                if disposition in {"conflict", "in_progress"}:
                    raise AIStateConflict
                if disposition == "replay":
                    projection = receipts.replay_projection(
                        scope_type="workspace",
                        scope_id=self._workspace_id,
                        operation="admin_ai_channels",
                        key_hash=key_hash,
                        request_hash=mutation_hash,
                    )
                    if projection is None:
                        raise AIStateConflict
                    if projection.get("result") == "failed":
                        replay_code = projection.get("error_code")
                        if replay_code == "ADMIN_AI_SECRET_UNAVAILABLE":
                            raise AIControlUnavailable
                        if replay_code in {
                            "ADMIN_AI_KEY_REJECTED",
                            "ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN",
                        }:
                            raise AIControlAvailabilityFailed(replay_code)
                        raise AIStateConflict
                    replayed = replay_control_projection(prior, projection)
                    if replayed is None:
                        raise AIStateConflict
                    return replayed
            if prior.revision != expected_revision:
                raise AIStateConflict
            try:
                if (
                    operator_enabled or demo_enabled
                ) and not self._has_verified_binding(prior):
                    raise AIControlUnavailable
                if (
                    operator_enabled
                    and not prior.operator_enabled
                    or demo_enabled
                    and not prior.demo_enabled
                ):
                    self._qualify_exact_binding(prior)
                try:
                    changed = repository.set_channels(
                        workspace_id=self._workspace_id,
                        expected_revision=prior.revision,
                        operator_enabled=operator_enabled,
                        demo_enabled=demo_enabled,
                        updated_by_operator_id=principal.operator_id,
                        now=self._clock(),
                    )
                except AIControlKeyBindingError:
                    raise AIControlUnavailable from None
            except (AIControlAvailabilityFailed, AIControlUnavailable) as error:
                deferred_failure = error
            if deferred_failure is None:
                if changed is None:
                    raise AIStateConflict
                repository.append_audit(
                    workspace_id=self._workspace_id,
                    operator_id=principal.operator_id,
                    action="channels.update",
                    result="succeeded",
                    safe_error_code=None,
                    prior_revision=prior.revision,
                    resulting_revision=changed.revision,
                    requested_operator_enabled=operator_enabled,
                    requested_demo_enabled=demo_enabled,
                    request_id=request_id,
                    now=self._clock(),
                )
            if receipts is not None and deferred_failure is None:
                now = self._clock()
                assert changed is not None
                projection = control_projection(changed)
                receipts.record_succeeded(
                    scope_type="workspace",
                    scope_id=self._workspace_id,
                    operation="admin_ai_channels",
                    key_hash=key_hash,
                    request_hash=mutation_hash,
                    response_status=200,
                    response_body_hash=request_hash(projection),
                    response_projection=projection,
                    now=now,
                    expires_at=now + ADMIN_IDEMPOTENCY_TTL,
                )
            elif receipts is not None:
                now = self._clock()
                failure_code = (
                    deferred_failure.code
                    if isinstance(deferred_failure, AIControlAvailabilityFailed)
                    else "ADMIN_AI_SECRET_UNAVAILABLE"
                )
                projection = control_projection(
                    prior,
                    result="failed",
                    error_code=failure_code,
                )
                receipts.record_succeeded(
                    scope_type="workspace",
                    scope_id=self._workspace_id,
                    operation="admin_ai_channels",
                    key_hash=key_hash,
                    request_hash=mutation_hash,
                    response_status=(
                        422 if failure_code == "ADMIN_AI_KEY_REJECTED" else 503
                    ),
                    response_body_hash=request_hash(projection),
                    response_projection=projection,
                    now=now,
                    expires_at=now + ADMIN_IDEMPOTENCY_TTL,
                )
        if deferred_failure is not None:
            raise deferred_failure
        assert changed is not None
        return changed

    def _reauthenticate(
        self,
        *,
        principal: OperatorPrincipal,
        current_password: SecretStr,
        request_meta: RequestMeta,
    ) -> None:
        if principal.workspace_id != self._workspace_id:
            current_password = SecretStr("")
            raise AIReauthenticationFailed
        password = current_password
        current_password = SecretStr("")
        rate_limited = False
        unavailable = False
        accepted = False
        try:
            accepted = self._operator_auth_service.reauthenticate(
                principal,
                password,
                request_meta,
            )
        except AuthenticationRateLimited:
            rate_limited = True
        except Exception:
            unavailable = True
        finally:
            password = SecretStr("")
        if rate_limited:
            raise AuthenticationRateLimited from None
        if unavailable:
            raise AIControlUnavailable from None
        if not accepted:
            raise AIReauthenticationFailed

    def _qualify_exact_binding(self, state: AIControlProjection) -> None:
        if not self._has_verified_binding(state):
            raise AIControlUnavailable
        assert state.key_version is not None
        value = ""
        status = "unknown"
        try:
            secret = self._secrets.read(state.key_version)
            value = secret.value
            returned_version = secret.version
            secret = None
            if returned_version != state.key_version:
                raise AIControlAvailabilityFailed("ADMIN_AI_SECRET_UNAVAILABLE")
            try:
                status = self._validator.validate(value).status
            except Exception:
                status = "unknown"
        except OpenAISecretUnavailable:
            raise AIControlAvailabilityFailed("ADMIN_AI_SECRET_UNAVAILABLE") from None
        finally:
            value = ""
        if status == "unknown":
            raise AIControlAvailabilityFailed("ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN")
        if status != "verified":
            raise AIControlAvailabilityFailed("ADMIN_AI_KEY_REJECTED")

    def _ensure_control_state(self) -> None:
        with self._uow_factory(self._engine) as uow:
            self._repository_factory(uow.connection).get_or_create(
                self._workspace_id,
                now=self._clock(),
            )

    @staticmethod
    def _has_verified_binding(state: AIControlProjection) -> bool:
        return (
            isinstance(state.key_name, str)
            and bool(state.key_name)
            and isinstance(state.key_version, str)
            and bool(state.key_version)
            and state.key_reference == f"{state.key_name}/{state.key_version}"
            and isinstance(state.key_fingerprint, str)
            and _FINGERPRINT.fullmatch(state.key_fingerprint) is not None
            and state.verified_at is not None
            and state.key_validation_state == "verified"
        )
