"""Single-operator credential and opaque-session service."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from pydantic import SecretStr
from sqlalchemy import Engine

from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.repositories.sessions import OperatorSessionProjection, SessionRepository

IDLE_TTL = timedelta(minutes=30)
ABSOLUTE_TTL = timedelta(hours=2)
FAILED_ATTEMPT_WINDOW = timedelta(minutes=5)
MAX_FAILED_ATTEMPTS = 5


class AuthenticationFailed(Exception):
    """Raised for every invalid login without revealing the reason."""


class AuthenticationRateLimited(Exception):
    """Raised when one source exceeds the fixed failed-login budget."""


@dataclass(frozen=True, slots=True)
class RequestMeta:
    source_address_hash: str
    now: datetime


@dataclass(frozen=True, slots=True)
class OperatorPrincipal:
    session_id: UUID
    operator_id: UUID
    workspace_id: str
    login_name: str
    idle_expires_at: datetime
    absolute_expires_at: datetime


@dataclass(frozen=True, slots=True)
class IssuedSession:
    session_token: str
    csrf_token: str
    principal: OperatorPrincipal


def token_hash(session_pepper: bytes, token: str) -> bytes:
    return hmac.new(session_pepper, token.encode(), hashlib.sha256).digest()


class OperatorAuthService:
    """Authenticate one server-configured operator and manage its sessions."""

    def __init__(
        self,
        *,
        engine: Engine,
        workspace_id: str,
        session_pepper: str,
        password_hasher: PasswordHasher | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._engine = engine
        self._workspace_id = workspace_id
        self._pepper = session_pepper.encode()
        self._password_hasher = password_hasher or PasswordHasher()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._fallback_hash = self._password_hasher.hash(
            secrets.token_urlsafe(24)
        )
        self._failed_attempts: dict[str, list[datetime]] = {}
        self._attempt_lock = Lock()

    def current_time(self) -> datetime:
        return self._clock()

    def source_address_fingerprint(self, source_address: str) -> str:
        digest = hmac.new(
            self._pepper,
            f"source:{source_address}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return digest

    def login(
        self,
        login_name: str,
        password: SecretStr,
        request_meta: RequestMeta,
    ) -> IssuedSession:
        self._ensure_attempt_allowed(request_meta.source_address_hash, request_meta.now)
        password_value = password.get_secret_value()

        with PostgresUnitOfWork(self._engine) as uow:
            operator = OperatorRepository(uow.connection).authenticate(
                workspace_id=self._workspace_id,
                login_name=login_name,
                verifier=lambda stored: self._verify(stored, password_value),
                fallback_hash=self._fallback_hash,
            )
            if operator is None:
                self._record_failed_attempt(
                    request_meta.source_address_hash,
                    request_meta.now,
                )
                raise AuthenticationFailed

            session_token = secrets.token_urlsafe(32)
            csrf_token = secrets.token_urlsafe(32)
            session = SessionRepository(uow.connection).create_operator_session(
                session_id=uuid4(),
                workspace_id=operator.workspace_id,
                operator_id=operator.id,
                token_hash=token_hash(self._pepper, session_token),
                csrf_hash=token_hash(self._pepper, csrf_token),
                now=request_meta.now,
                idle_expires_at=request_meta.now + IDLE_TTL,
                absolute_expires_at=request_meta.now + ABSOLUTE_TTL,
            )

        self._clear_failed_attempts(request_meta.source_address_hash)
        return IssuedSession(
            session_token=session_token,
            csrf_token=csrf_token,
            principal=self._principal(session, operator.login_name),
        )

    def reauthenticate(
        self,
        principal: OperatorPrincipal,
        password: SecretStr,
        request_meta: RequestMeta,
    ) -> bool:
        """Verify the current Operator password without changing session state."""

        self._ensure_attempt_allowed(request_meta.source_address_hash, request_meta.now)
        candidate = password.get_secret_value()
        try:
            with PostgresUnitOfWork(self._engine) as uow:
                operator = OperatorRepository(uow.connection).authenticate(
                    workspace_id=principal.workspace_id,
                    login_name=principal.login_name,
                    verifier=lambda stored: self._verify(stored, candidate),
                    fallback_hash=self._fallback_hash,
                )
        finally:
            candidate = ""
        if operator is None or operator.id != principal.operator_id:
            self._record_failed_attempt(
                request_meta.source_address_hash,
                request_meta.now,
            )
            return False
        self._clear_failed_attempts(request_meta.source_address_hash)
        return True

    def resolve(self, session_token: str, now: datetime) -> OperatorPrincipal | None:
        hashed_token = token_hash(self._pepper, session_token)
        with PostgresUnitOfWork(self._engine) as uow:
            sessions = SessionRepository(uow.connection)
            session = sessions.get_active_operator_session(hashed_token, now)
            if session is None:
                return None
            operator = OperatorRepository(uow.connection).get_active(session.workspace_id)
            if operator is None or operator.id != session.operator_id:
                return None
            next_idle_expiry = min(now + IDLE_TTL, session.absolute_expires_at)
            touched = sessions.touch_operator_session(
                session.id,
                now=now,
                idle_expires_at=next_idle_expiry,
            )
            if touched is None:
                return None
            return self._principal(touched, operator.login_name)

    def csrf_matches(self, session_id: UUID, csrf_token: str) -> bool:
        candidate_hash = token_hash(self._pepper, csrf_token)
        with self._engine.connect() as connection:
            return SessionRepository(connection).operator_csrf_matches(
                session_id,
                candidate_hash,
            )

    def logout(self, session_id: UUID, now: datetime) -> None:
        with PostgresUnitOfWork(self._engine) as uow:
            SessionRepository(uow.connection).revoke_operator_session(session_id, now)

    def _principal(
        self,
        session: OperatorSessionProjection,
        login_name: str,
    ) -> OperatorPrincipal:
        return OperatorPrincipal(
            session_id=session.id,
            operator_id=session.operator_id,
            workspace_id=session.workspace_id,
            login_name=login_name,
            idle_expires_at=session.idle_expires_at,
            absolute_expires_at=session.absolute_expires_at,
        )

    def _verify(self, stored_hash: str, candidate: str) -> bool:
        try:
            return self._password_hasher.verify(stored_hash, candidate)
        except VerificationError:
            return False

    def _ensure_attempt_allowed(self, source_hash: str, now: datetime) -> None:
        with self._attempt_lock:
            cutoff = now - FAILED_ATTEMPT_WINDOW
            attempts = [
                attempt for attempt in self._failed_attempts.get(source_hash, [])
                if attempt > cutoff
            ]
            self._failed_attempts[source_hash] = attempts
            if len(attempts) >= MAX_FAILED_ATTEMPTS:
                raise AuthenticationRateLimited

    def _record_failed_attempt(self, source_hash: str, now: datetime) -> None:
        with self._attempt_lock:
            self._failed_attempts.setdefault(source_hash, []).append(now)

    def _clear_failed_attempts(self, source_hash: str) -> None:
        with self._attempt_lock:
            self._failed_attempts.pop(source_hash, None)
