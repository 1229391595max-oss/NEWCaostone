from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.auth_support import (
    build_auth_app,
    fast_password_hasher,
    initial_clock,
    seed_public_release,
    seed_operator,
)

ORIGIN = "http://testserver"


def test_demo_session_is_opaque_persisted_and_resumes_in_fresh_app(
    migrated_engine: Engine,
) -> None:
    clock = initial_clock()
    seed_operator(migrated_engine, fast_password_hasher())
    version_id = seed_public_release(migrated_engine)
    with TestClient(build_auth_app(migrated_engine, clock)) as client:
        response = client.post("/api/demo/sessions", headers={"Origin": ORIGIN})

    assert response.status_code == 201
    assert "HttpOnly" in response.headers["set-cookie"]
    assert response.json()["session"]["idle_expires_at"] == "2026-08-13T18:30:00Z"
    assert response.json()["session"]["absolute_expires_at"] == "2026-08-13T20:00:00Z"
    assert response.json()["session"]["dataset_version_id"] == str(version_id)
    cookie = response.cookies["bp_demo_session"]

    with TestClient(build_auth_app(migrated_engine, clock)) as fresh_client:
        fresh_client.cookies.set("bp_demo_session", cookie)
        resumed = fresh_client.get("/api/demo/sessions/current")

    assert resumed.status_code == 200
    assert resumed.json()["session"]["status"] == "active"
    assert resumed.headers["cache-control"] == "private, no-store"
    assert resumed.headers["vary"] == "Cookie"


def test_demo_session_end_requires_csrf_and_revokes_immediately(
    migrated_engine: Engine,
) -> None:
    clock = initial_clock()
    seed_operator(migrated_engine, fast_password_hasher())
    seed_public_release(migrated_engine)
    with TestClient(build_auth_app(migrated_engine, clock)) as client:
        created = client.post("/api/demo/sessions", headers={"Origin": ORIGIN})
        csrf_token = created.json()["csrf_token"]
        assert client.delete(
            "/api/demo/sessions",
            headers={"Origin": ORIGIN},
        ).status_code == 403
        ended = client.delete(
            "/api/demo/sessions",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_token},
        )
        resumed = client.get("/api/demo/sessions/current")

    assert ended.status_code == 204
    assert resumed.status_code == 401


def test_demo_data_must_be_imported_once_before_release_reads(
    migrated_engine: Engine,
) -> None:
    clock = initial_clock()
    seed_operator(migrated_engine, fast_password_hasher())
    version_id = seed_public_release(migrated_engine)
    with TestClient(build_auth_app(migrated_engine, clock)) as client:
        created = client.post("/api/demo/sessions", headers={"Origin": ORIGIN})
        csrf_token = created.json()["csrf_token"]
        blocked = client.get("/api/demo/release/current")
        missing_csrf = client.post(
            "/api/demo/sessions/current/import-demo-data",
            headers={"Origin": ORIGIN},
        )
        first = client.post(
            "/api/demo/sessions/current/import-demo-data",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_token},
        )
        clock.now += timedelta(minutes=1)
        second = client.post(
            "/api/demo/sessions/current/import-demo-data",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_token},
        )
        release = client.get("/api/demo/release/current")

    assert created.json()["session"]["demo_data_imported"] is False
    assert blocked.status_code == 409
    assert blocked.json() == {"code": "DEMO_DATA_NOT_IMPORTED"}
    assert missing_csrf.status_code == 403
    assert first.status_code == 200
    assert first.json()["session"]["demo_data_imported"] is True
    assert second.json()["session"]["demo_data_imported_at"] == first.json()[
        "session"
    ]["demo_data_imported_at"]
    assert release.status_code != 409
    assert release.json() != {"code": "DEMO_DATA_NOT_IMPORTED"}
    assert first.json()["session"]["dataset_version_id"] == str(version_id)
