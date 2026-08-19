from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from api.main import create_app
from src.services.preferences_service import PreferencesService
from tests.auth_support import (
    WORKSPACE_ID,
    build_container,
    fast_password_hasher,
    initial_clock,
    seed_operator,
    seed_public_release,
)

ORIGIN = "http://testserver"


def test_viewer_settings_are_read_only_defaults_and_have_no_write_route(
    migrated_engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    seed_public_release(migrated_engine)
    base = build_container(migrated_engine, initial_clock())
    container = replace(
        base,
        preferences_service=PreferencesService(migrated_engine, WORKSPACE_ID),
    )
    with TestClient(create_app(container=container)) as client:
        created = client.post("/api/demo/sessions", headers={"Origin": ORIGIN})
        response = client.get("/api/demo/preferences")
        mutation = client.put(
            "/api/demo/preferences",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": created.json()["csrf_token"],
            },
            json={"reporting_currency": "USD"},
        )

    assert response.status_code == 200
    assert response.json()["preferences"]["reporting_currency"] == "BRL"
    assert response.json()["permissions"] == {
        "reporting_defaults": "read_only",
        "targets": "read_only",
        "persistence": "session",
    }
    assert mutation.status_code == 405
    assert "key" not in response.text.lower()
