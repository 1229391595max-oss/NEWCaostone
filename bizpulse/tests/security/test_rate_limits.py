from __future__ import annotations

import pytest

from src.config import BizPulseSettings, ConfigError
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.services.demo_session_service import (
    DemoSessionRateLimited,
    DemoSessionService,
)
from tests.auth_support import SESSION_PEPPER, seed_public_release


def test_session_admission_limit_allows_classroom_15_and_has_safe_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIZPULSE_DEMO_SESSION_RATE_LIMIT_PER_HOUR", "50")
    settings = BizPulseSettings.from_env()
    assert settings.demo_session_rate_limit_per_hour >= 15
    assert settings.demo_session_rate_limit_per_hour == 50


@pytest.mark.parametrize("value", ("0", "14", "not-an-integer"))
def test_session_admission_limit_rejects_unsafe_configuration(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("BIZPULSE_DEMO_SESSION_RATE_LIMIT_PER_HOUR", value)
    with pytest.raises(ConfigError, match="demo_session_rate_limit"):
        BizPulseSettings.from_env()


def test_session_admission_limit_cannot_disable_the_safe_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIZPULSE_DEMO_SESSION_RATE_LIMIT_PER_HOUR", "51")

    with pytest.raises(ConfigError, match="demo_session_rate_limit"):
        BizPulseSettings.from_env()


def test_request_body_limit_cannot_exceed_the_import_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "BIZPULSE_REQUEST_BODY_LIMIT_BYTES",
        str(9 * 1024 * 1024 + 1),
    )

    with pytest.raises(ConfigError, match="request_body_limit"):
        BizPulseSettings.from_env()


def test_persisted_same_source_window_allows_15_then_rejects_more(
    migrated_engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace("synthetic-demo")
    seed_public_release(migrated_engine)
    service = DemoSessionService(
        engine=migrated_engine,
        workspace_id="synthetic-demo",
        session_pepper=SESSION_PEPPER,
        source_session_limit_per_hour=15,
    )
    now = service.current_time()
    source = service.source_address_fingerprint("203.0.113.10")

    sessions = [service.create(source, now) for _ in range(15)]

    assert len({item.principal.session_id for item in sessions}) == 15
    with pytest.raises(DemoSessionRateLimited):
        service.create(source, now)
