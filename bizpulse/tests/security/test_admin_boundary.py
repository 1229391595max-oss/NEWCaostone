from __future__ import annotations

from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from api.dependencies.admin import require_admin_mutation, require_admin_operator
from src.services.operator_auth_service import OperatorPrincipal
from tests.auth_support import (
    LOGIN_NAME,
    PASSWORD,
    build_auth_app,
    fast_password_hasher,
    initial_clock,
    seed_operator,
    seed_public_release,
)


def admin_client(migrated_engine: Engine) -> TestClient:
    app = build_auth_app(migrated_engine, initial_clock())

    @app.get("/api/v1/admin/summary")
    def summary(
        _: OperatorPrincipal = Depends(require_admin_operator),
    ) -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/admin/mutations")
    def mutation(
        _: OperatorPrincipal = Depends(require_admin_mutation),
    ) -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


def operator_login(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/api/operator/login",
        headers={"Origin": "http://testserver"},
        json={"login_name": LOGIN_NAME, "password": PASSWORD},
    )
    assert response.status_code == 201
    return response.json()["csrf_token"], response.cookies["bp_operator_session"]


def test_demo_cookie_cannot_call_admin_summary(migrated_engine: Engine) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    seed_public_release(migrated_engine)
    with admin_client(migrated_engine) as client:
        created = client.post("/api/demo/sessions", headers={"Origin": "http://testserver"})
        assert created.status_code == 201
        client.cookies.clear()
        client.cookies.set("bp_demo_session", created.cookies["bp_demo_session"])

        response = client.get("/api/v1/admin/summary")

    assert response.status_code == 401
    assert response.json() == {"code": "AUTHENTICATION_REQUIRED"}


def test_admin_mutation_requires_operator_origin_and_csrf(migrated_engine: Engine) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    with admin_client(migrated_engine) as client:
        csrf_token, _ = operator_login(client)
        missing_origin = client.post("/api/v1/admin/mutations")
        wrong_token = client.post(
            "/api/v1/admin/mutations",
            headers={"Origin": "http://testserver", "X-CSRF-Token": "wrong"},
        )
        allowed = client.post(
            "/api/v1/admin/mutations",
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf_token},
        )

    assert missing_origin.status_code == 403
    assert wrong_token.status_code == 403
    assert allowed.status_code == 200
