from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient
import pytest

from api.container import ApiContainer
from api.main import create_app
from src.config import BizPulseSettings


def _app():
    settings = BizPulseSettings(
        runtime_environment="local",
        database_url="postgresql+psycopg://localhost/bizpulse",
        blob_endpoint="http://127.0.0.1:10000/devstoreaccount1",
        blob_container="synthetic-demo",
        allowed_origin="http://testserver",
        cookie_secure=False,
    )
    application = create_app(container=ApiContainer(settings=settings))

    @application.get("/__test/failure/{item_id}")
    def failure(item_id: str) -> None:
        raise RuntimeError(
            f"internal failure for {item_id} at /Users/maxli/private "
            "postgresql://operator:password@db/bizpulse"
        )

    return application


def test_internal_error_is_stable_request_correlated_and_path_free(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="bizpulse.request")
    with TestClient(_app(), raise_server_exceptions=False) as client:
        response = client.get("/__test/failure/sensitive-raw-id")

    assert response.status_code == 500
    assert response.json() == {
        "code": "INTERNAL_ERROR",
        "request_id": response.headers["x-request-id"],
    }
    assert len(response.json()["request_id"]) == 32
    assert "/Users/" not in response.text
    assert "postgresql" not in response.text.lower()
    assert "sensitive-raw-id" not in response.text
    event = json.loads(
        next(record.message for record in caplog.records if record.name == "bizpulse.request")
    )
    assert event["error_code"] == "INTERNAL_ERROR"
    assert "/Users/" not in caplog.text
    assert "postgresql" not in caplog.text.lower()


def test_validation_error_log_uses_stable_business_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="bizpulse.request")
    with TestClient(_app(), raise_server_exceptions=False) as client:
        response = client.post(
            "/api/operator/login",
            headers={"Origin": "http://testserver"},
            json={},
        )

    assert response.status_code == 422
    event = json.loads(
        [
            record.message
            for record in caplog.records
            if record.name == "bizpulse.request"
        ][-1]
    )
    assert event["error_code"] == "REQUEST_VALIDATION_FAILED"
