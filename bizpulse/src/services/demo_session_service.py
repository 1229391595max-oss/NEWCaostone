"""Persisted anonymous viewer-session lifecycle."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Engine

from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.datasets import DatasetRepository
from src.repositories.sessions import DemoSessionProjection, SessionRepository
from src.services.operator_auth_service import token_hash

IDLE_TTL = timedelta(minutes=30)
ABSOLUTE_TTL = timedelta(hours=2)


class PublicReleaseUnavailable(RuntimeError):
    code = "PUBLIC_RELEASE_UNAVAILABLE"


class DemoSessionRateLimited(RuntimeError):
    code = "DEMO_SESSION_RATE_LIMITED"


@dataclass(frozen=True, slots=True)
class DemoPrincipal:
    session_id: UUID
    workspace_id: str
    dataset_version_id: UUID | None
    forecast_id: UUID | None
    profit_bridge_id: UUID | None
    demo_data_imported_at: datetime | None
    chat_epoch: int
    status: str
    created_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime


@dataclass(frozen=True, slots=True)
class IssuedSession:
    session_token: str
    csrf_token: str
    principal: DemoPrincipal


class DemoSessionService:
    """Create and resume isolated, time-bounded anonymous sessions."""

    def __init__(
        self,
        *,
        engine: Engine,
        workspace_id: str,
        session_pepper: str,
        clock: Callable[[], datetime] | None = None,
        release_validator: Callable[[UUID], bool] | None = None,
        forecast_resolver: Callable[[UUID], UUID | None] | None = None,
        profit_bridge_resolver: Callable[[UUID], UUID | None] | None = None,
        source_session_limit_per_hour: int = 50,
    ) -> None:
        self._engine = engine
        self._workspace_id = workspace_id
        self._pepper = session_pepper.encode()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._release_validator = release_validator
        self._forecast_resolver = forecast_resolver
        self._profit_bridge_resolver = profit_bridge_resolver
        if source_session_limit_per_hour < 15:
            raise ValueError("source_session_limit_must_allow_15")
        self._source_session_limit_per_hour = source_session_limit_per_hour

    def current_time(self) -> datetime:
        return self._clock()

    def source_address_fingerprint(self, source_address: str) -> str:
        return hmac.new(
            self._pepper,
            f"viewer-source:{source_address}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def create(self, source_address_hash: str, now: datetime) -> IssuedSession:
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        with self._engine.connect() as connection:
            release = DatasetRepository(connection).current_release(
                self._workspace_id
            )
        if release is None:
            raise PublicReleaseUnavailable
        if (
            self._release_validator is not None
            and not self._release_validator(release.dataset_version_id)
        ):
            raise PublicReleaseUnavailable
        forecast_id = (
            self._forecast_resolver(release.dataset_version_id)
            if self._forecast_resolver is not None
            else None
        )
        profit_bridge_id = (
            self._profit_bridge_resolver(release.dataset_version_id)
            if self._profit_bridge_resolver is not None
            else None
        )
        stored_source_hash = token_hash(self._pepper, source_address_hash)
        with PostgresUnitOfWork(self._engine) as uow:
            sessions = SessionRepository(uow.connection)
            sessions.lock_demo_session_source(stored_source_hash)
            admitted = sessions.count_demo_sessions_for_source_since(
                stored_source_hash,
                now - timedelta(hours=1),
            )
            if admitted >= self._source_session_limit_per_hour:
                raise DemoSessionRateLimited
            session = sessions.create_demo_session(
                session_id=uuid4(),
                workspace_id=self._workspace_id,
                token_hash=token_hash(self._pepper, session_token),
                csrf_hash=token_hash(self._pepper, csrf_token),
                source_address_hash=stored_source_hash,
                now=now,
                idle_expires_at=now + IDLE_TTL,
                absolute_expires_at=now + ABSOLUTE_TTL,
                dataset_version_id=release.dataset_version_id,
                forecast_id=forecast_id,
                profit_bridge_id=profit_bridge_id,
            )
        return IssuedSession(
            session_token=session_token,
            csrf_token=csrf_token,
            principal=self._principal(session),
        )

    def resolve(self, session_token: str, now: datetime) -> DemoPrincipal | None:
        hashed_token = token_hash(self._pepper, session_token)
        with PostgresUnitOfWork(self._engine) as uow:
            sessions = SessionRepository(uow.connection)
            session = sessions.get_active_demo_session(hashed_token, now)
            if session is None:
                return None
            next_idle_expiry = min(now + IDLE_TTL, session.absolute_expires_at)
            touched = sessions.touch_demo_session(
                session.id,
                now=now,
                idle_expires_at=next_idle_expiry,
            )
            return self._principal(touched) if touched is not None else None

    def csrf_matches(self, session_id: UUID, csrf_token: str) -> bool:
        candidate_hash = token_hash(self._pepper, csrf_token)
        with self._engine.connect() as connection:
            return SessionRepository(connection).demo_csrf_matches(
                session_id,
                candidate_hash,
            )

    def end(self, session_id: UUID, now: datetime) -> bool:
        with PostgresUnitOfWork(self._engine) as uow:
            return SessionRepository(uow.connection).end_demo_session(session_id, now)

    def import_demo_data(
        self,
        session_id: UUID,
        now: datetime,
    ) -> DemoPrincipal | None:
        with PostgresUnitOfWork(self._engine) as uow:
            session = SessionRepository(uow.connection).import_demo_data(
                session_id,
                now=now,
            )
            return self._principal(session) if session is not None else None

    def expire_sessions(self, now: datetime) -> int:
        with PostgresUnitOfWork(self._engine) as uow:
            return SessionRepository(uow.connection).expire_demo_sessions(now)

    @staticmethod
    def _principal(session: DemoSessionProjection) -> DemoPrincipal:
        return DemoPrincipal(
            session_id=session.id,
            workspace_id=session.workspace_id,
            dataset_version_id=session.dataset_version_id,
            forecast_id=session.forecast_id,
            profit_bridge_id=session.profit_bridge_id,
            demo_data_imported_at=session.demo_data_imported_at,
            chat_epoch=session.chat_epoch,
            status=session.status,
            created_at=session.created_at,
            idle_expires_at=session.idle_expires_at,
            absolute_expires_at=session.absolute_expires_at,
        )
