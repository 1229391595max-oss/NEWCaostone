from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

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

ORIGIN = "http://testserver"


class PreparationStub:
    def prepare(self, version_id):
        return SimpleNamespace(
            dataset_version_id=version_id,
            status="ready",
            domains=(
                SimpleNamespace(name="sales_ads", status="ready", limitation_code=None),
                SimpleNamespace(name="inventory", status="ready", limitation_code=None),
                SimpleNamespace(name="profit", status="ready", limitation_code=None),
                SimpleNamespace(name="forecast", status="ready", limitation_code=None),
                SimpleNamespace(name="actions", status="ready", limitation_code=None),
            ),
        )


def test_prepare_dataset_is_operator_only_and_returns_bounded_status(
    migrated_engine: Engine,
) -> None:
    clock = initial_clock()
    seed_operator(migrated_engine, fast_password_hasher())
    version_id = uuid4()
    container = replace(
        build_container(migrated_engine, clock),
        dataset_preparation_service=PreparationStub(),
    )

    with TestClient(create_app(container=container)) as client:
        assert client.post(f"/api/v1/datasets/versions/{version_id}/prepare").status_code == 401
        login = client.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        response = client.post(
            f"/api/v1/datasets/versions/{version_id}/prepare",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": login.json()["csrf_token"],
            },
        )

    assert response.status_code == 200
    assert response.json()["dataset_version_id"] == str(version_id)
    assert response.json()["status"] == "ready"
    assert [item["name"] for item in response.json()["domains"]] == [
        "sales_ads", "inventory", "profit", "forecast", "actions"
    ]
