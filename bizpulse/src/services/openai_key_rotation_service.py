"""Compensating exact-version rotation for the shared OpenAI credential."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
import hmac
import re
from typing import Protocol

from pydantic import SecretStr
from sqlalchemy import Engine

from src.ai.credential_validation import OpenAICredentialValidator
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.admin_ai import (
    AIControlBusy,
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
from src.services.ai_control_service import (
    AIControlUnavailable,
    AIReauthenticationFailed,
    AIStateConflict,
)
from src.services.operator_auth_service import (
    AuthenticationRateLimited,
    OperatorAuthService,
    OperatorPrincipal,
    RequestMeta,
)

_KEY_NAME = re.compile(r"[0-9A-Za-z-]{1,127}")


class AIKeyRotationFailed(RuntimeError):
    """A stable, value-free rotation failure suitable for API mapping."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RepositoryFactory(Protocol):
    def __call__(self, connection: object) -> AIControlRepository: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self, engine: Engine) -> PostgresUnitOfWork: ...


class OpenAIKeyRotationService:
    """Qualify, write, read back, and atomically bind one shared key."""

    def __init__(
        self,
        *,
        engine: Engine,
        workspace_id: str,
        key_name: str,
        operator_auth_service: OperatorAuthService,
        secret_manager: OpenAISecretManager,
        credential_validator: OpenAICredentialValidator,
        session_pepper: bytes,
        uow_factory: UnitOfWorkFactory = PostgresUnitOfWork,
        repository_factory: RepositoryFactory = AIControlRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if _KEY_NAME.fullmatch(key_name) is None:
            raise ValueError("openai_key_name_invalid")
        if not isinstance(session_pepper, bytes) or not session_pepper:
            raise ValueError("session_pepper_missing")
        self._engine = engine
        self._workspace_id = workspace_id
        self._key_name = key_name
        self._operator_auth_service = operator_auth_service
        self._secrets = secret_manager
        self._validator = credential_validator
        self._session_pepper = session_pepper
        self._uow_factory = uow_factory
        self._repository_factory = repository_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return f"OpenAIKeyRotationService(workspace_id={self._workspace_id!r})"

    def rotate(
        self,
        *,
        principal: OperatorPrincipal,
        current_password: SecretStr,
        request_meta: RequestMeta,
        candidate: SecretStr,
        expected_revision: int,
        request_id: str,
        idempotency_key: str | None = None,
    ) -> AIControlProjection:
        candidate_value = ""
        previous_value = ""
        readback_value = ""
        written_version: str | None = None
        write_attempted = False
        compensation_attempted = False
        compensation_complete = False
        activated: AIControlProjection | None = None
        prior: AIControlProjection | None = None
        activation_fingerprint: str | None = None
        failure_code: str | None = None
        transaction_body_complete = False
        transaction_failure_code: str | None = None
        key_hash: bytes | None = None
        mutation_hash: bytes | None = None
        password = current_password
        current_password = SecretStr("")
        candidate_secret = candidate
        candidate = SecretStr("")
        try:
            self._reauthenticate(principal, password, request_meta)
            password = SecretStr("")
            candidate_value = candidate_secret.get_secret_value()
            candidate_secret = SecretStr("")
            if idempotency_key is not None:
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
                        "candidate_fingerprint": self._fingerprint(candidate_value),
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
                        operation="admin_ai_key_rotation",
                        key_hash=key_hash,
                        request_hash=mutation_hash,
                    )
                    if disposition in {"conflict", "in_progress"}:
                        raise AIStateConflict
                    if disposition == "replay":
                        projection = receipts.replay_projection(
                            scope_type="workspace",
                            scope_id=self._workspace_id,
                            operation="admin_ai_key_rotation",
                            key_hash=key_hash,
                            request_hash=mutation_hash,
                        )
                        if projection is None:
                            raise AIStateConflict
                        if projection.get("result") == "failed":
                            replay_code = projection.get("error_code")
                            if not isinstance(replay_code, str):
                                raise AIStateConflict
                            raise AIKeyRotationFailed(replay_code)
                        replayed = (
                            replay_control_projection(prior, projection)
                            if projection.get("result") == "succeeded"
                            else None
                        )
                        if replayed is None:
                            raise AIStateConflict
                        return replayed
                if prior.revision != expected_revision:
                    raise AIStateConflict

                if prior.key_version is not None:
                    try:
                        previous = self._secrets.read(prior.key_version)
                        previous_value = previous.value
                        previous = None
                    except OpenAISecretUnavailable:
                        failure_code = "ADMIN_AI_SECRET_UNAVAILABLE"

                if failure_code is None:
                    first_status = self._validate(candidate_value)
                    if first_status != "verified":
                        failure_code = self._validation_code(first_status)

                if failure_code is None:
                    try:
                        write_attempted = True
                        written = self._secrets.write(candidate_value)
                        written_version = written.version
                        written = None
                        readback = self._secrets.read(written_version)
                        readback_value = readback.value
                        readback_version = readback.version
                        readback = None
                        if (
                            readback_version != written_version
                            or not hmac.compare_digest(
                                readback_value,
                                candidate_value,
                            )
                        ):
                            failure_code = "ADMIN_AI_SECRET_UNAVAILABLE"
                        else:
                            second_status = self._validate(readback_value)
                            if second_status != "verified":
                                failure_code = self._validation_code(second_status)
                    except OpenAISecretUnavailable:
                        failure_code = "ADMIN_AI_SECRET_UNAVAILABLE"

                if failure_code is not None:
                    if write_attempted:
                        compensation_attempted = True
                        compensation_complete = self._compensate(previous_value)
                        if not compensation_complete:
                            failure_code = (
                                "ADMIN_AI_SECRET_UNAVAILABLE"
                                if previous_value
                                else "ADMIN_AI_RECONCILIATION_REQUIRED"
                            )
                    repository.append_audit(
                        workspace_id=self._workspace_id,
                        operator_id=principal.operator_id,
                        action="key.rotate",
                        result="failed",
                        safe_error_code=failure_code,
                        prior_revision=prior.revision,
                        resulting_revision=prior.revision,
                        request_id=request_id,
                        now=self._clock(),
                    )
                    if receipts is not None:
                        now = self._clock()
                        projection = control_projection(
                            prior,
                            result="failed",
                            error_code=failure_code,
                        )
                        receipts.record_succeeded(
                            scope_type="workspace",
                            scope_id=self._workspace_id,
                            operation="admin_ai_key_rotation",
                            key_hash=key_hash,
                            request_hash=mutation_hash,
                            response_status=(
                                422
                                if failure_code == "ADMIN_AI_KEY_REJECTED"
                                else 503
                            ),
                            response_body_hash=request_hash(projection),
                            response_projection=projection,
                            now=now,
                            expires_at=now + ADMIN_IDEMPOTENCY_TTL,
                        )
                else:
                    assert written_version is not None
                    activation_fingerprint = self._fingerprint(candidate_value)
                    activated = repository.activate_key(
                        workspace_id=self._workspace_id,
                        expected_revision=prior.revision,
                        key_name=self._key_name,
                        key_version=written_version,
                        key_reference=f"{self._key_name}/{written_version}",
                        key_fingerprint=activation_fingerprint,
                        verified_at=self._clock(),
                        updated_by_operator_id=principal.operator_id,
                        now=self._clock(),
                    )
                    if activated is None:
                        raise AIStateConflict
                    repository.append_audit(
                        workspace_id=self._workspace_id,
                        operator_id=principal.operator_id,
                        action="key.rotate",
                        result="succeeded",
                        safe_error_code=None,
                        prior_revision=prior.revision,
                        resulting_revision=activated.revision,
                        request_id=request_id,
                        now=self._clock(),
                    )
                    if receipts is not None:
                        now = self._clock()
                        projection = control_projection(activated)
                        receipts.record_succeeded(
                            scope_type="workspace",
                            scope_id=self._workspace_id,
                            operation="admin_ai_key_rotation",
                            key_hash=key_hash,
                            request_hash=mutation_hash,
                            response_status=200,
                            response_body_hash=request_hash(projection),
                            response_projection=projection,
                            now=now,
                            expires_at=now + ADMIN_IDEMPOTENCY_TTL,
                        )
                transaction_body_complete = True
        except (
            AIControlBusy,
            AIControlUnavailable,
            AIKeyRotationFailed,
            AIReauthenticationFailed,
            AIStateConflict,
            AuthenticationRateLimited,
        ):
            if write_attempted and not compensation_attempted:
                compensation_attempted = True
                self._compensate(previous_value)
            raise
        except Exception:
            if failure_code is not None and compensation_attempted:
                transaction_failure_code = failure_code
            elif write_attempted and not compensation_attempted:
                reconciliation = "rolled_back"
                reconciled = None
                if (
                    transaction_body_complete
                    and prior is not None
                    and activation_fingerprint is not None
                ):
                    reconciliation, reconciled = self._reconcile_binding(
                        prior=prior,
                        written_version=written_version,
                        activation_fingerprint=activation_fingerprint,
                    )
                if reconciliation == "activated":
                    activated = reconciled
                    failure_code = None
                elif reconciliation == "rolled_back":
                    compensation_attempted = True
                    compensation_complete = self._compensate(previous_value)
                    transaction_failure_code = (
                        "ADMIN_AI_SECRET_UNAVAILABLE"
                        if previous_value or compensation_complete
                        else "ADMIN_AI_RECONCILIATION_REQUIRED"
                    )
                else:
                    transaction_failure_code = "ADMIN_AI_SECRET_UNAVAILABLE"
            else:
                transaction_failure_code = "ADMIN_AI_SECRET_UNAVAILABLE"
        finally:
            password = SecretStr("")
            current_password = SecretStr("")
            candidate_secret = SecretStr("")
            candidate = SecretStr("")
            candidate_value = ""
            previous_value = ""
            readback_value = ""

        if failure_code is not None:
            raise AIKeyRotationFailed(failure_code) from None
        if transaction_failure_code is not None:
            raise AIKeyRotationFailed(transaction_failure_code) from None
        if activated is None:
            raise AIKeyRotationFailed("ADMIN_AI_SECRET_UNAVAILABLE")
        return activated

    def _reauthenticate(
        self,
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

    def _validate(self, value: str) -> str:
        try:
            return self._validator.validate(value).status
        except Exception:
            return "unknown"

    def _compensate(self, previous_value: str) -> bool:
        if not previous_value:
            return False
        try:
            restored = self._secrets.write(previous_value)
            del restored
            return True
        except OpenAISecretUnavailable:
            return False

    def _reconcile_binding(
        self,
        *,
        prior: AIControlProjection,
        written_version: str,
        activation_fingerprint: str,
    ) -> tuple[str, AIControlProjection | None]:
        try:
            with self._uow_factory(self._engine) as uow:
                current = self._repository_factory(uow.connection).get_or_create(
                    self._workspace_id, now=self._clock()
                )
        except Exception:
            return "unknown", None
        if (
            current.revision == prior.revision + 1
            and current.key_name == self._key_name
            and current.key_version == written_version
            and current.key_reference == f"{self._key_name}/{written_version}"
            and current.key_fingerprint == activation_fingerprint
            and current.key_validation_state == "verified"
            and current.verified_at is not None
            and current.operator_enabled == prior.operator_enabled
            and current.demo_enabled == prior.demo_enabled
        ):
            return "activated", current
        if (
            current.revision == prior.revision
            and current.key_name == prior.key_name
            and current.key_version == prior.key_version
            and current.key_reference == prior.key_reference
            and current.key_fingerprint == prior.key_fingerprint
            and current.key_validation_state == prior.key_validation_state
            and current.operator_enabled == prior.operator_enabled
            and current.demo_enabled == prior.demo_enabled
        ):
            return "rolled_back", current
        return "unknown", current

    def _ensure_control_state(self) -> None:
        with self._uow_factory(self._engine) as uow:
            self._repository_factory(uow.connection).get_or_create(
                self._workspace_id,
                now=self._clock(),
            )

    def _fingerprint(self, candidate_value: str) -> str:
        return hmac.new(
            self._session_pepper,
            b"openai-key-fingerprint\x00" + candidate_value.encode(),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _validation_code(status: str) -> str:
        if status == "unknown":
            return "ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN"
        return "ADMIN_AI_KEY_REJECTED"
