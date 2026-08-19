from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

import api.routers.health as health_module
from api.container import ApiContainer
from api.main import create_app
from src.config import BizPulseSettings
from src.db.readiness import (
    DatabaseReadiness,
    EXPECTED_SCHEMA_REVISION,
    FORWARD_COMPATIBLE_SCHEMA_REVISIONS,
)
from src.services.foundation_bootstrap_service import FoundationBootstrapService

VALID_OPERATOR_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$"
    "dspPsWevmFQvVX8T5BXmFA$"
    "ayB1yKL+3347+SAAe59WoJsD4u1eZvHySBBiSx1jfIk"
)


def local_settings() -> BizPulseSettings:
    return BizPulseSettings(
        runtime_environment="local",
        database_url="postgresql+psycopg://localhost/bizpulse_test",
        blob_endpoint="http://127.0.0.1:10000/devstoreaccount1",
        blob_container="synthetic-demo",
        allowed_origin="http://127.0.0.1:8000",
        cookie_secure=False,
    )


def test_public_and_protected_shell_routes() -> None:
    with TestClient(create_app(settings=local_settings())) as client:
        assert client.get("/").status_code == 200
        assert client.get("/login").status_code == 200
        protected = client.get("/app")
        assert protected.status_code == 401
        assert protected.json() == {"code": "AUTHENTICATION_REQUIRED"}
        demo = client.get("/demo")
        assert demo.status_code == 401
        assert demo.json() == {"code": "AUTHENTICATION_REQUIRED"}
        redirect = client.get("/real", follow_redirects=False)
        assert redirect.status_code == 307
        assert redirect.headers["location"] == "/app"
        assert client.get("/health/live").json() == {"status": "ok"}
        assert client.get("/health/ready").json() == {
            "status": "ready",
            "checks": {"configuration": "ok"},
        }
        assert client.get("/api/v1").json() == {
            "name": "BizPulse API",
            "status": "shell",
        }


def test_static_assets_are_local_and_available() -> None:
    with TestClient(create_app(settings=local_settings())) as client:
        welcome = client.get("/")
        login = client.get("/login")
        app_script = client.get("/assets/app.mjs")
        styles = client.get("/assets/styles.css")

    assert app_script.status_code == 200
    assert styles.status_code == 200
    assert "https://" not in welcome.text
    assert "http://" not in welcome.text
    assert "https://" not in login.text
    assert "http://" not in login.text
    assert welcome.headers["cache-control"] == "no-cache"
    assert login.headers["cache-control"] == "no-cache"
    assert app_script.headers["cache-control"] == "no-cache"
    assert styles.headers["cache-control"] == "no-cache"


def test_application_paths_do_not_depend_on_process_cwd(monkeypatch) -> None:
    monkeypatch.chdir(Path("/"))

    with TestClient(create_app(settings=local_settings())) as client:
        assert client.get("/").status_code == 200
        assert client.get("/assets/app.mjs").status_code == 200


def test_explicit_dependency_container_is_preserved() -> None:
    settings = local_settings()
    container = ApiContainer(settings=settings)

    with TestClient(create_app(settings=settings, container=container)) as client:
        assert client.app.state.container is container


def test_application_lifespan_closes_the_ai_provider_once() -> None:
    class Provider:
        def __init__(self) -> None:
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    provider = Provider()
    settings = local_settings()
    container = ApiContainer(
        settings=settings,
        ai_client_provider=provider,
    )

    with TestClient(create_app(container=container)) as client:
        assert client.get("/health/live").status_code == 200

    assert provider.close_calls == 1


def test_application_lifespan_closes_the_ai_provider_after_request_failure() -> None:
    class Provider:
        def __init__(self) -> None:
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    provider = Provider()
    container = ApiContainer(
        settings=local_settings(),
        ai_client_provider=provider,
    )
    application = create_app(container=container)

    @application.get("/_test/failure")
    def fail_request() -> None:
        raise RuntimeError("injected_request_failure")

    with TestClient(application) as client:
        response = client.get("/_test/failure")
        assert response.status_code == 500
        assert response.json()["code"] == "INTERNAL_ERROR"
        assert len(response.json()["request_id"]) == 32

    assert provider.close_calls == 1


class ReadyStorage:
    def check_readiness(self) -> None:
        return None


def cloud_settings() -> BizPulseSettings:
    return BizPulseSettings(
        runtime_environment="cloud",
        database_url="postgresql+psycopg://db/bizpulse",
        blob_endpoint="https://blob.test",
        blob_container="synthetic-demo",
        allowed_origin="https://demo.test",
        cookie_secure=True,
        operator_password_hash=VALID_OPERATOR_HASH,
    )


def test_cloud_readiness_probes_database_migration_and_blob(
    migrated_engine: Engine,
) -> None:
    settings = cloud_settings()
    FoundationBootstrapService(
        engine=migrated_engine,
        workspace_id="synthetic-demo",
        login_name="operator",
        password_hash=VALID_OPERATOR_HASH,
    ).bootstrap()
    container = ApiContainer(
        settings=settings,
        engine=migrated_engine,
        workflow_storage=ReadyStorage(),
    )

    with TestClient(create_app(container=container)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "blob": "ok",
            "configuration": "ok",
            "database": "ok",
            "foundation": "ok",
            "migration": EXPECTED_SCHEMA_REVISION,
        },
    }


@pytest.mark.parametrize(
    "forward_compatible_revision",
    (
        "0014_import_base_lineage",
        "0015_admin_ai_control",
        "0016_admin_ai_control_integrity",
    ),
)
def test_candidate_readiness_accepts_only_bounded_pre_migration_heads(
    forward_compatible_revision: str,
    monkeypatch: pytest.MonkeyPatch,
    migrated_engine: Engine,
) -> None:
    FoundationBootstrapService(
        engine=migrated_engine,
        workspace_id="synthetic-demo",
        login_name="operator",
        password_hash=VALID_OPERATOR_HASH,
    ).bootstrap()
    monkeypatch.setattr(
        health_module,
        "database_readiness",
        lambda _engine: DatabaseReadiness(
            revision=forward_compatible_revision,
            writable=True,
            latency_ms=1.0,
        ),
    )
    container = ApiContainer(
        settings=cloud_settings(),
        engine=migrated_engine,
        workflow_storage=ReadyStorage(),
    )

    with TestClient(create_app(container=container)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["migration"] == forward_compatible_revision


def test_candidate_readiness_has_one_exact_additive_transition_set() -> None:
    assert FORWARD_COMPATIBLE_SCHEMA_REVISIONS == {
        "0014_import_base_lineage",
        "0015_admin_ai_control",
        "0016_admin_ai_control_integrity",
        "0017_ai_turn_credential_binding",
    }


@pytest.mark.parametrize(
    "unsupported_revision",
    ("0008_ai_budget_ledger", "0013_workspace_preferences", "0018_unknown"),
)
def test_candidate_readiness_rejects_heads_outside_additive_transition(
    unsupported_revision: str,
    monkeypatch: pytest.MonkeyPatch,
    migrated_engine: Engine,
) -> None:
    monkeypatch.setattr(
        health_module,
        "database_readiness",
        lambda _engine: DatabaseReadiness(
            revision=unsupported_revision,
            writable=True,
            latency_ms=1.0,
        ),
    )
    container = ApiContainer(
        settings=cloud_settings(),
        engine=migrated_engine,
        workflow_storage=ReadyStorage(),
    )

    with TestClient(create_app(container=container)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"configuration": "ok", "migration": "failed"},
    }


def test_cloud_readiness_caches_the_deep_authority_probe(
    monkeypatch: pytest.MonkeyPatch,
    migrated_engine: Engine,
) -> None:
    settings = cloud_settings()
    FoundationBootstrapService(
        engine=migrated_engine,
        workspace_id="synthetic-demo",
        login_name="operator",
        password_hash=VALID_OPERATOR_HASH,
    ).bootstrap()
    calls = 0
    original = health_module.database_readiness

    def counted(engine):
        nonlocal calls
        calls += 1
        return original(engine)

    monkeypatch.setattr(health_module, "database_readiness", counted)
    container = ApiContainer(
        settings=settings,
        engine=migrated_engine,
        workflow_storage=ReadyStorage(),
    )

    with TestClient(create_app(container=container)) as client:
        assert client.get("/health/ready").status_code == 200
        assert client.get("/health/ready").status_code == 200

    assert calls == 1


def test_readiness_gate_rejects_a_concurrent_deep_probe() -> None:
    entered = Event()
    release = Event()
    calls = 0
    gate = health_module.ReadinessGate()
    ready = health_module.ReadinessResult(
        status_code=200,
        content={"status": "ready", "checks": {"configuration": "ok"}},
    )

    def slow_probe():
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=2)
        return ready

    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(gate.check, slow_probe)
        assert entered.wait(timeout=1)
        concurrent = gate.check(slow_probe)
        release.set()
        assert first.result(timeout=2) == ready

    assert concurrent.status_code == 503
    assert concurrent.content["checks"]["probe"] == "failed"
    assert calls == 1


@pytest.mark.parametrize("failure", ["database", "migration", "foundation", "blob"])
def test_cloud_readiness_fails_closed_without_exception_details(
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
    migrated_engine: Engine,
) -> None:
    class FailingStorage(ReadyStorage):
        def check_readiness(self) -> None:
            if failure == "blob":
                raise RuntimeError("credential-and-endpoint-must-not-escape")

    if failure == "database":
        monkeypatch.setattr(
            health_module,
            "database_readiness",
            lambda engine: (_ for _ in ()).throw(
                RuntimeError("postgres-password-must-not-escape")
            ),
        )
    elif failure == "migration":
        monkeypatch.setattr(
            health_module,
            "database_readiness",
            lambda engine: DatabaseReadiness(
                revision="0006_ai_chat",
                writable=True,
                latency_ms=1.0,
            ),
        )
    settings = cloud_settings()
    if failure != "foundation":
        FoundationBootstrapService(
            engine=migrated_engine,
            workspace_id="synthetic-demo",
            login_name="operator",
            password_hash=VALID_OPERATOR_HASH,
        ).bootstrap()
    container = ApiContainer(
        settings=settings,
        engine=migrated_engine,
        workflow_storage=FailingStorage(),
    )

    with TestClient(create_app(container=container)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    serialized = response.text.lower()
    assert "password" not in serialized
    assert "credential" not in serialized
    assert "endpoint" not in serialized
