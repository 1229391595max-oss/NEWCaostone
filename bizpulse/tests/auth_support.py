from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from argon2 import PasswordHasher
from sqlalchemy import Engine

from api.container import ApiContainer
from api.main import create_app
from src.config import BizPulseSettings
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.datasets import DatasetRepository
from src.repositories.operators import OperatorRepository
from src.services.demo_session_service import DemoSessionService
from src.services.operator_auth_service import OperatorAuthService
from src.services.public_release_service import PublicReleaseService
from src.services.preferences_service import PreferencesService

WORKSPACE_ID = "synthetic-demo"
LOGIN_NAME = "operator"
PASSWORD = "correct horse demo battery"
SESSION_PEPPER = "test-session-pepper-with-enough-entropy"


@dataclass
class MutableClock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


def fast_password_hasher() -> PasswordHasher:
    return PasswordHasher(time_cost=1, memory_cost=1_024, parallelism=1)


def seed_operator(engine: Engine, password_hasher: PasswordHasher) -> None:
    with PostgresUnitOfWork(engine) as uow:
        operators = OperatorRepository(uow.connection)
        operators.create_workspace(WORKSPACE_ID)
        operators.create_operator(
            workspace_id=WORKSPACE_ID,
            login_name=LOGIN_NAME,
            password_hash=password_hasher.hash(PASSWORD),
        )


def build_container(
    engine: Engine,
    clock: MutableClock,
    *,
    secure: bool = False,
) -> ApiContainer:
    origin = "https://demo.test" if secure else "http://testserver"
    settings = BizPulseSettings(
        runtime_environment="cloud" if secure else "local",
        database_url=str(engine.url),
        blob_endpoint="http://127.0.0.1:10000/devstoreaccount1",
        blob_container="synthetic-demo",
        allowed_origin=origin,
        cookie_secure=secure,
        operator_password_hash=None,
        session_pepper=SESSION_PEPPER,
    )
    password_hasher = fast_password_hasher()
    return ApiContainer(
        settings=settings,
        engine=engine,
        operator_auth_service=OperatorAuthService(
            engine=engine,
            workspace_id=WORKSPACE_ID,
            session_pepper=SESSION_PEPPER,
            password_hasher=password_hasher,
            clock=clock,
        ),
        demo_session_service=DemoSessionService(
            engine=engine,
            workspace_id=WORKSPACE_ID,
            session_pepper=SESSION_PEPPER,
            clock=clock,
        ),
        public_release_service=PublicReleaseService(
            engine,
            WORKSPACE_ID,
            idempotency_pepper=SESSION_PEPPER,
            clock=clock,
        ),
        preferences_service=PreferencesService(engine, WORKSPACE_ID, clock=clock),
    )


def build_auth_app(
    engine: Engine,
    clock: MutableClock,
    *,
    secure: bool = False,
):
    container = build_container(engine, clock, secure=secure)
    return create_app(settings=container.settings, container=container)


def initial_clock() -> MutableClock:
    return MutableClock(datetime(2026, 8, 13, 18, 0, tzinfo=UTC))


def seed_public_release(engine: Engine) -> UUID:
    now = datetime(2026, 8, 13, 17, 0, tzinfo=UTC)
    with PostgresUnitOfWork(engine) as uow:
        datasets = DatasetRepository(uow.connection)
        series = datasets.create_series(
            workspace_id=WORKSPACE_ID,
            name="session-test-series",
            now=now,
        )
        version = datasets.create_version(
            series_id=series.id,
            workspace_id=WORKSPACE_ID,
            source_workflow_id=None,
            version_number=1,
            schema_version="synthetic.v1",
            content_sha256="f" * 64,
            now=now,
        )
        datasets.point_series_at(series.id, version.id)
        datasets.activate_release(
            workspace_id=WORKSPACE_ID,
            dataset_version_id=version.id,
            now=now,
        )
    return version.id


def activate_demo_data(client, created_response):
    """Activate the prepared Viewer data using the issued synchronizer token."""

    return client.post(
        "/api/demo/sessions/current/import-demo-data",
        headers={
            "Origin": str(client.base_url).rstrip("/"),
            "X-CSRF-Token": created_response.json()["csrf_token"],
        },
    )
