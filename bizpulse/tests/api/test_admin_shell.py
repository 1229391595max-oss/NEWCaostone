from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from api.main import create_app
from tests.auth_support import (
    LOGIN_NAME,
    PASSWORD,
    build_container,
    fast_password_hasher,
    initial_clock,
    seed_operator,
)


@pytest.fixture
def client(migrated_engine: Engine) -> Iterator[TestClient]:
    with TestClient(
        create_app(container=build_container(migrated_engine, initial_clock()))
    ) as test_client:
        yield test_client


@pytest.fixture
def authenticated_client(client: TestClient, migrated_engine: Engine) -> TestClient:
    seed_operator(migrated_engine, fast_password_hasher())
    response = client.post(
        "/api/operator/login",
        headers={"Origin": "http://testserver"},
        json={"login_name": LOGIN_NAME, "password": PASSWORD},
    )
    assert response.status_code == 201
    return client


@pytest.mark.parametrize("path", ["/admin", "/admin/data", "/admin/status", "/admin/ai"])
def test_admin_document_requires_operator_and_returns_shell(
    authenticated_client: TestClient,
    path: str,
) -> None:
    response = authenticated_client.get(path)

    assert response.status_code == 200
    assert "BP Admin" in response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"


def test_unauthenticated_admin_navigation_redirects_to_allowlisted_login(
    client: TestClient,
) -> None:
    response = client.get("/admin/ai", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/admin/ai"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"


def test_demo_session_navigation_to_admin_is_private_and_redirected(
    client: TestClient,
) -> None:
    client.cookies.set("bp_demo_session", "demo-session-sentinel")

    response = client.get("/admin/status", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/admin/status"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"


def test_unknown_admin_child_404_is_private_and_cookie_variant(
    client: TestClient,
) -> None:
    response = client.get("/admin/future-child", follow_redirects=False)

    assert response.status_code == 404
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"
