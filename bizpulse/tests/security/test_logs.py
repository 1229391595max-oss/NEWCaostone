from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import Engine

from api.container import ApiContainer
from api.main import create_app
from src.config import BizPulseSettings
from src.observability import log_ai_turn


def test_migrations_preserve_application_loggers(migrated_engine: Engine) -> None:
    del migrated_engine

    assert logging.getLogger("bizpulse.request").disabled is False
    assert logging.getLogger("bizpulse.ai").disabled is False


def _app():
    settings = BizPulseSettings(
        runtime_environment="local",
        database_url="postgresql+psycopg://operator:database-secret@db/bizpulse",
        blob_endpoint="http://127.0.0.1:10000/devstoreaccount1",
        blob_container="synthetic-demo",
        allowed_origin="http://testserver",
        cookie_secure=False,
    )
    application = create_app(container=ApiContainer(settings=settings))

    @application.post("/__test/log-safety")
    async def log_safety(payload: dict[str, object]) -> dict[str, bool]:
        del payload
        return {"ok": True}

    return application


def test_logs_allowlist_metadata_and_never_include_payload_or_config(caplog) -> None:
    sentinel = "synthetic-secret-sentinel"
    caplog.set_level(logging.INFO, logger="bizpulse.request")
    with TestClient(_app()) as client:
        response = client.post(
            "/__test/log-safety",
            json={"question": sentinel, "database_url": "do-not-log"},
        )

    assert response.status_code == 200
    assert sentinel not in caplog.text
    assert "database-secret" not in caplog.text
    assert "do-not-log" not in caplog.text
    records = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "bizpulse.request"
    ]
    assert len(records) == 1
    assert records[0]["event"] == "http_request"
    assert records[0]["error_code"] is None
    assert records[0]["route"] == "/__test/log-safety"
    assert set(records[0]) == {
        "duration_ms",
        "error_code",
        "event",
        "method",
        "request_id",
        "route",
        "status",
    }


def test_ai_telemetry_is_bounded_allowlisted_and_value_free(caplog) -> None:
    caplog.set_level(logging.INFO, logger="bizpulse.ai")

    log_ai_turn(
        {
            "dataset_version_hash_prefix": "0123456789ab",
            "error_code": None,
            "event": "ai_turn",
            "input_tokens": 30,
            "output_tokens": 10,
            "replayed": False,
            "request_id": "a" * 32,
            "status": "answered",
            "tool_name": "data_quality",
        }
    )

    event = json.loads(
        next(record.message for record in caplog.records if record.name == "bizpulse.ai")
    )
    assert event["dataset_version_hash_prefix"] == "0123456789ab"
    assert event["input_tokens"] == 30
    assert event["output_tokens"] == 10
    assert set(event) == {
        "dataset_version_hash_prefix",
        "error_code",
        "event",
        "input_tokens",
        "output_tokens",
        "replayed",
        "request_id",
        "status",
        "tool_name",
    }


def test_ai_telemetry_rejects_raw_or_unbounded_fields() -> None:
    with pytest.raises(ValueError, match="ai_log_fields_invalid"):
        log_ai_turn(
            {
                "dataset_version_hash_prefix": "0123456789ab",
                "error_code": None,
                "event": "ai_turn",
                "input_tokens": 30,
                "output_tokens": 10,
                "question": "raw question must never be logged",
                "replayed": False,
                "request_id": "a" * 32,
                "status": "answered",
                "tool_name": "data_quality",
            }
        )


def test_uvicorn_production_logging_emits_safe_http_and_ai_json() -> None:
    project_root = Path(__file__).resolve().parents[2]
    code = """
import logging
from uvicorn import Config
from src.observability import configure_observability_logging, log_ai_turn

Config('api.main:app').configure_logging()
configure_observability_logging()
logging.getLogger('bizpulse.request').info('{\"event\":\"http_probe\"}')
log_ai_turn({
    'dataset_version_hash_prefix': '0123456789ab',
    'error_code': None,
    'event': 'ai_turn',
    'input_tokens': 3,
    'output_tokens': 1,
    'replayed': False,
    'request_id': 'a' * 32,
    'status': 'answered',
    'tool_name': 'data_quality',
})
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )

    events = [json.loads(line) for line in completed.stdout.splitlines()]
    assert events[0] == {"event": "http_probe"}
    assert events[1]["event"] == "ai_turn"
    assert events[1]["tool_name"] == "data_quality"
    assert completed.stderr == ""


def test_real_uvicorn_disables_raw_access_log_and_emits_route_json() -> None:
    project_root = Path(__file__).resolve().parents[2]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = os.environ.copy()
    environment.update(
        {
            "BIZPULSE_RUNTIME_ENVIRONMENT": "local",
            "PYTHONUNBUFFERED": "1",
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            "1",
            "--no-access-log",
        ],
        cwd=project_root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            if process.poll() is not None:
                raise AssertionError("uvicorn_start_failed")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise AssertionError("uvicorn_start_timeout")
                time.sleep(0.05)
        with urlopen(
            f"http://127.0.0.1:{port}/health/live?secret-sentinel=forbidden",
            timeout=5,
        ) as response:
            assert response.status == 200
    finally:
        process.terminate()
        stdout, stderr = process.communicate(timeout=10)

    output = stdout + stderr
    assert "secret-sentinel" not in output
    assert '"route":"/health/live"' in stdout
    assert 'GET /health/live?' not in output
