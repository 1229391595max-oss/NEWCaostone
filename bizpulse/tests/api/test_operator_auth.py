from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.auth_support import (
    LOGIN_NAME,
    PASSWORD,
    build_auth_app,
    fast_password_hasher,
    initial_clock,
    seed_operator,
)

ORIGIN = "http://testserver"


def test_login_has_generic_failure_and_no_registration_route(
    migrated_engine: Engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    with TestClient(build_auth_app(migrated_engine, initial_clock())) as client:
        unknown = client.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": "unknown", "password": "wrong"},
        )
        wrong = client.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": "wrong"},
        )
        registration = client.post("/api/operator/register")

    assert unknown.status_code == 401
    assert wrong.status_code == 401
    assert unknown.json() == wrong.json() == {"code": "AUTHENTICATION_FAILED"}
    assert registration.status_code == 404
    assert PASSWORD not in unknown.text + wrong.text
    assert "argon2" not in unknown.text.lower() + wrong.text.lower()


def test_login_rate_limit_fails_closed_by_source(migrated_engine: Engine) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    with TestClient(build_auth_app(migrated_engine, initial_clock())) as client:
        responses = [
            client.post(
                "/api/operator/login",
                headers={"Origin": ORIGIN},
                json={"login_name": LOGIN_NAME, "password": "wrong"},
            )
            for _ in range(6)
        ]

    assert [response.status_code for response in responses[:5]] == [401] * 5
    assert responses[5].status_code == 429
    assert responses[5].json() == {"code": "RATE_LIMITED"}


def test_operator_cookie_resumes_in_fresh_app_and_unlocks_app_shell(
    migrated_engine: Engine,
) -> None:
    clock = initial_clock()
    seed_operator(migrated_engine, fast_password_hasher())
    with TestClient(build_auth_app(migrated_engine, clock)) as first_client:
        response = first_client.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        cookie = response.cookies["bp_operator_session"]

    with TestClient(build_auth_app(migrated_engine, clock)) as fresh_client:
        fresh_client.cookies.set("bp_operator_session", cookie)
        protected = fresh_client.get("/app")

    assert protected.status_code == 200
    assert "data-primary-route=\"workspace\"" in protected.text
