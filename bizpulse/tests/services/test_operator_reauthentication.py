from __future__ import annotations

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, func, select

from src.db.schema import operator_sessions
from src.repositories.operators import OperatorRepository
from src.services.operator_auth_service import (
    AuthenticationRateLimited,
    OperatorAuthService,
    OperatorPrincipal,
    RequestMeta,
)
from tests.auth_support import (
    LOGIN_NAME,
    PASSWORD,
    SESSION_PEPPER,
    WORKSPACE_ID,
    fast_password_hasher,
    initial_clock,
    seed_operator,
)


def count_operator_sessions(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.scalar(select(func.count()).select_from(operator_sessions)))


def request_meta(service: OperatorAuthService) -> RequestMeta:
    return RequestMeta(
        source_address_hash=service.source_address_fingerprint("127.0.0.1"),
        now=service.current_time(),
    )


def authenticated_service(
    migrated_engine: Engine,
) -> tuple[OperatorAuthService, OperatorPrincipal]:
    clock = initial_clock()
    seed_operator(migrated_engine, fast_password_hasher())
    service = OperatorAuthService(
        engine=migrated_engine,
        workspace_id=WORKSPACE_ID,
        session_pepper=SESSION_PEPPER,
        password_hasher=fast_password_hasher(),
        clock=clock,
    )
    issued = service.login(LOGIN_NAME, SecretStr(PASSWORD), request_meta(service))
    return service, issued.principal


def test_reauthenticate_checks_current_operator_without_issuing_session(
    migrated_engine: Engine,
) -> None:
    service, principal = authenticated_service(migrated_engine)
    before = count_operator_sessions(migrated_engine)

    assert service.reauthenticate(principal, SecretStr(PASSWORD), request_meta(service)) is True
    assert service.reauthenticate(principal, SecretStr("wrong"), request_meta(service)) is False
    assert count_operator_sessions(migrated_engine) == before


def test_reauthenticate_uses_the_existing_failed_attempt_limit(
    migrated_engine: Engine,
) -> None:
    service, principal = authenticated_service(migrated_engine)

    for _ in range(5):
        assert service.reauthenticate(principal, SecretStr("wrong"), request_meta(service)) is False

    with pytest.raises(AuthenticationRateLimited):
        service.reauthenticate(principal, SecretStr(PASSWORD), request_meta(service))


def test_reauthenticate_clears_candidate_when_repository_authentication_raises(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, principal = authenticated_service(migrated_engine)
    candidate = "candidate-must-not-survive-a-repository-error"

    def fail_authenticate(*_args, **_kwargs):
        raise RuntimeError("repository unavailable")

    monkeypatch.setattr(OperatorRepository, "authenticate", fail_authenticate)

    with pytest.raises(RuntimeError, match="repository unavailable") as failure:
        service.reauthenticate(principal, SecretStr(candidate), request_meta(service))

    traceback = failure.value.__traceback__
    while traceback is not None and traceback.tb_frame.f_code.co_name != "reauthenticate":
        traceback = traceback.tb_next
    assert traceback is not None
    assert traceback.tb_frame.f_locals["candidate"] == ""
