from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from api.main import create_app
from src.services.preferences_service import PreferencesService
from tests.auth_support import (
    LOGIN_NAME,
    PASSWORD,
    WORKSPACE_ID,
    build_container,
    fast_password_hasher,
    initial_clock,
    seed_operator,
)

ORIGIN = "http://testserver"


def test_operator_settings_persist_without_exposing_or_accepting_ai_secrets(
    migrated_engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    base = build_container(migrated_engine, initial_clock())
    container = replace(
        base,
        preferences_service=PreferencesService(migrated_engine, WORKSPACE_ID),
    )
    with TestClient(create_app(container=container)) as client:
        assert client.get("/api/v1/preferences").status_code == 401
        login = client.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        csrf = login.json()["csrf_token"]
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        loaded = client.get("/api/v1/preferences")
        payload = loaded.json()["preferences"]
        payload.update({"locale": "zh", "sidebar_mode": "compact"})
        saved = client.put(
            "/api/v1/preferences",
            headers=headers,
            json={"expected_revision": 0, "preferences": payload},
        )
        stale = client.put(
            "/api/v1/preferences",
            headers=headers,
            json={"expected_revision": 0, "preferences": payload},
        )
        secret = client.put(
            "/api/v1/preferences",
            headers=headers,
            json={
                "expected_revision": 1,
                "preferences": payload,
                "api" + "_key": "must-not-be-accepted",
            },
        )

    assert saved.status_code == 200
    assert saved.json()["preferences"]["revision"] == 1
    assert stale.status_code == 409
    assert stale.json() == {"code": "PREFERENCE_REVISION_CONFLICT"}
    assert secret.status_code == 422
    assert "key" not in loaded.text.lower()
    assert loaded.json()["ai"]["status"] in {"available", "disabled", "unavailable"}
    assert "decimal" not in loaded.text.lower()


def test_operator_saved_view_and_target_commands_are_real_working_controls(
    migrated_engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    base = build_container(migrated_engine, initial_clock())
    container = replace(
        base,
        preferences_service=PreferencesService(migrated_engine, WORKSPACE_ID),
    )
    with TestClient(create_app(container=container)) as client:
        login = client.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": login.json()["csrf_token"],
        }
        view = client.post(
            "/api/v1/preferences/saved-views",
            headers=headers,
            json={"name": "My Today", "kind": "today", "config": {"route": "overview"}},
        )
        target = client.post(
            "/api/v1/preferences/targets",
            headers=headers,
            json={
                "period": "2026-08", "revenue_brl": "100000.00",
                "orders": 2400, "roas": "4.25", "profit_brl": "18000.00",
            },
        )
        archived = client.patch(
            f"/api/v1/preferences/targets/{target.json()['id']}",
            headers=headers,
            json={"expected_revision": 1, "status": "archived"},
        )
        final = client.get("/api/v1/preferences")

    assert view.status_code == 201
    assert target.status_code == 201
    assert archived.status_code == 200
    assert final.json()["saved_views"][0]["name"] == "My Today"
    assert final.json()["targets"][0]["status"] == "archived"
