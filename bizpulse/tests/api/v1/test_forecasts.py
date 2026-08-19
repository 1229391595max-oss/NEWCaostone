from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from api.main import create_app
from src.db.unit_of_work import PostgresUnitOfWork
from src.services.demo_session_service import DemoSessionService
from src.services.forecast_service import ForecastService
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.auth_support import (
    LOGIN_NAME,
    PASSWORD,
    SESSION_PEPPER,
    activate_demo_data,
    build_container,
    fast_password_hasher,
    initial_clock,
    seed_operator,
)
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID

ORIGIN = "http://testserver"


def _payload(dataset_version_id: str) -> dict[str, object]:
    return {
        "dataset_version_id": dataset_version_id,
        "candidate": {
            "product_name": "Synthetic Portable Organizer",
            "category": "travel_bag",
            "attributes": ["portable", "zippered", "compact"],
            "planned_launch_date": "2026-08-20",
            "planned_price_brl": "119.90",
            "expected_discount_brl": "5.00",
            "unit_cost_brl": "42.00",
            "opening_inventory_units": 80,
            "moq_units": 24,
            "lead_time_days": 18,
            "planned_daily_ad_brl": "12.00",
        },
        "safety_stock_units": 20,
        "assumptions": ["synthetic_launch_ramp"],
        "missing_fields": [],
    }


def test_operator_forecast_flow_and_pinned_viewer_read(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    seed_operator(migrated_engine, fast_password_hasher())
    seeded = seed_demo(
        generate_demo(),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 13, 17, tzinfo=UTC),
    )
    clock = initial_clock()
    forecasts = ForecastService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=clock,
    )
    container = replace(
        build_container(migrated_engine, clock),
        workflow_storage=storage,
        forecast_service=forecasts,
        demo_session_service=DemoSessionService(
            engine=migrated_engine,
            workspace_id=WORKSPACE_ID,
            session_pepper=SESSION_PEPPER,
            clock=clock,
            forecast_resolver=lambda version_id: forecasts.latest_completed(
                version_id
            ).id,
        ),
    )
    with TestClient(create_app(container=container)) as client:
        unauthenticated = client.post(
            "/api/v1/forecasts",
            json=_payload(str(seeded.dataset_version_id)),
        )
        login = client.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": login.json()["csrf_token"],
        }
        created = client.post(
            "/api/v1/forecasts",
            headers={**headers, "Idempotency-Key": "api-forecast-primary-001"},
            json=_payload(str(seeded.dataset_version_id)),
        )
        replayed_create = client.post(
            "/api/v1/forecasts",
            headers={**headers, "Idempotency-Key": "api-forecast-primary-001"},
            json=_payload(str(seeded.dataset_version_id)),
        )
        forecast_id = created.json()["id"]
        blocked = client.post(
            f"/api/v1/forecasts/{forecast_id}/run",
            headers=headers,
        )
        analog_ids = [item["sku_id"] for item in created.json()["analogs"][:2]]
        confirmed = client.post(
            f"/api/v1/forecasts/{forecast_id}/analogs/confirm",
            headers=headers,
            json={"sku_ids": analog_ids},
        )
        completed = client.post(
            f"/api/v1/forecasts/{forecast_id}/run",
            headers=headers,
        )
        latest_operator = client.get(
            "/api/v1/forecasts/latest",
            params={"dataset_version_id": str(seeded.dataset_version_id)},
        )
        viewer = client.post("/api/demo/sessions", headers={"Origin": ORIGIN})
        activate_demo_data(client, viewer)
        latest_viewer = client.get("/api/demo/release/forecasts/latest")
        clock.now += timedelta(seconds=1)
        second_payload = _payload(str(seeded.dataset_version_id))
        second_payload["candidate"]["product_name"] = "Synthetic Second Organizer"
        second = client.post(
            "/api/v1/forecasts",
            headers={**headers, "Idempotency-Key": "api-forecast-second-001"},
            json=second_payload,
        )
        second_analogs = [
            item["sku_id"] for item in second.json()["analogs"][:2]
        ]
        client.post(
            f"/api/v1/forecasts/{second.json()['id']}/analogs/confirm",
            headers=headers,
            json={"sku_ids": second_analogs},
        )
        second_completed = client.post(
            f"/api/v1/forecasts/{second.json()['id']}/run",
            headers=headers,
        )
        pinned_replay = client.get("/api/demo/release/forecasts/latest")

    assert unauthenticated.status_code == 401
    assert created.status_code == 201, created.text
    assert replayed_create.json() == created.json()
    assert blocked.status_code == 409
    assert blocked.json() == {"code": "ANALOGS_NOT_CONFIRMED"}
    assert confirmed.status_code == 200
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert completed.json()["confidence"] == "medium"
    assert latest_operator.json() == completed.json()
    assert viewer.status_code == 201
    assert latest_viewer.status_code == 200
    assert latest_viewer.json() == completed.json()
    assert pinned_replay.json() == second_completed.json()
    assert latest_viewer.headers["cache-control"] == "private, no-store"
    assert latest_viewer.json()["dataset_version_id"] == str(
        seeded.dataset_version_id
    )
    assert "google" not in latest_viewer.text.lower()
    assert "object_key" not in latest_viewer.text


@pytest.mark.parametrize(
    "product_name",
    (
        "Max Li",
        "Synthetic Max Li 12293915950",
        "Synthetic Casa 123 Main Street",
        "Synthetic max@example.test",
    ),
)
def test_forecast_input_rejects_non_synthetic_or_sensitive_names(
    migrated_engine: Engine,
    product_name: str,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    clock = initial_clock()
    container = build_container(migrated_engine, clock)
    with TestClient(create_app(container=container)) as client:
        login = client.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        payload = _payload("00000000-0000-0000-0000-000000000001")
        payload["candidate"]["product_name"] = product_name
        response = client.post(
            "/api/v1/forecasts",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": login.json()["csrf_token"],
                "Idempotency-Key": "api-forecast-sensitive-001",
            },
            json=payload,
        )

    assert response.status_code == 422
    assert product_name not in response.text
    assert response.json() == {"code": "REQUEST_VALIDATION_FAILED"}
