from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from src.db.schema import operator_sessions
from src.config import BizPulseSettings
from tests.auth_support import (
    LOGIN_NAME,
    PASSWORD,
    build_auth_app,
    fast_password_hasher,
    initial_clock,
    seed_operator,
)


def login(client: TestClient, origin: str) -> tuple[str, str]:
    response = client.post(
        "/api/operator/login",
        headers={"Origin": origin},
        json={"login_name": LOGIN_NAME, "password": PASSWORD},
    )
    assert response.status_code == 201
    return response.json()["csrf_token"], response.cookies["bp_operator_session"]


def test_cloud_cookie_is_http_only_secure_lax_and_root_scoped(
    migrated_engine: Engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    with TestClient(
        build_auth_app(migrated_engine, initial_clock(), secure=True),
        base_url="https://demo.test",
    ) as client:
        response = client.post(
            "/api/operator/login",
            headers={"Origin": "https://demo.test"},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )

    cookie = response.headers["set-cookie"]
    assert response.status_code == 201
    assert "bp_operator_session=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie


def test_state_change_requires_origin_and_matching_csrf(
    migrated_engine: Engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    with TestClient(build_auth_app(migrated_engine, initial_clock())) as client:
        missing_origin = client.post(
            "/api/operator/login",
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        wrong_origin = client.post(
            "/api/operator/login",
            headers={"Origin": "https://attacker.test"},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        csrf_token, _ = login(client, "http://testserver")

        assert missing_origin.status_code == 403
        assert wrong_origin.status_code == 403
        assert client.post(
            "/api/operator/logout",
            headers={"Origin": "http://testserver"},
        ).status_code == 403
        assert client.post(
            "/api/operator/logout",
            headers={
                "Origin": "http://testserver",
                "X-CSRF-Token": "wrong-token",
            },
        ).status_code == 403
        assert client.post(
            "/api/operator/logout",
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf_token},
        ).status_code == 204


def test_raw_session_and_csrf_tokens_are_never_persisted(
    migrated_engine: Engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    with TestClient(build_auth_app(migrated_engine, initial_clock())) as client:
        csrf_token, session_token = login(client, "http://testserver")

    with migrated_engine.connect() as connection:
        row = connection.execute(
            select(operator_sessions.c.token_hash, operator_sessions.c.csrf_hash)
        ).one()

    assert len(row.token_hash) == 32
    assert len(row.csrf_hash) == 32
    assert row.token_hash != session_token.encode()
    assert row.csrf_hash != csrf_token.encode()


def test_settings_representation_redacts_server_secrets() -> None:
    settings = BizPulseSettings(
        runtime_environment="cloud",
        database_url="postgresql+psycopg://operator:database-secret@db/bizpulse",
        blob_endpoint="https://blob.test/container?sig=blob-secret",
        blob_container="synthetic-demo",
        allowed_origin="https://demo.test",
        cookie_secure=True,
        operator_password_hash="$argon2id$operator-secret",
        session_pepper="session-pepper-secret-value",
    )

    representation = repr(settings)
    assert "database-secret" not in representation
    assert "blob-secret" not in representation
    assert "operator-secret" not in representation
    assert "session-pepper-secret-value" not in representation
