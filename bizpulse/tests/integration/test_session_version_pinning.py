from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from api.main import create_app
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.services.analysis_service import AnalysisService
from src.services.public_release_service import PublicReleaseService
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.auth_support import activate_demo_data, build_container, initial_clock
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID

ORIGIN = "http://testserver"
PEPPER = "test-public-release-idempotency-pepper"


def test_existing_viewer_stays_pinned_while_new_viewer_gets_new_release(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    clock = initial_clock()
    analyses = AnalysisService(migrated_engine, storage, WORKSPACE_ID, clock=clock)
    releases = PublicReleaseService(
        migrated_engine,
        WORKSPACE_ID,
        idempotency_pepper=PEPPER,
        clock=clock,
        analysis_service=analyses,
    )
    first = seed_demo(
        generate_demo(seed=20260813),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 13, 18, tzinfo=UTC),
    )
    container = replace(
        build_container(migrated_engine, clock),
        workflow_storage=storage,
        public_release_service=releases,
    )

    with TestClient(create_app(container=container)) as first_viewer:
        created = first_viewer.post(
            "/api/demo/sessions",
            headers={"Origin": ORIGIN},
        )
        assert created.status_code == 201
        assert created.json()["session"]["dataset_version_id"] == str(
            first.dataset_version_id
        )
        assert activate_demo_data(first_viewer, created).status_code == 200

        second = seed_demo(
            generate_demo(seed=20260814),
            PostgresUnitOfWork(migrated_engine),
            storage,
            now=datetime(2026, 8, 14, 18, tzinfo=UTC),
        )
        replayed_first = seed_demo(
            generate_demo(seed=20260813),
            PostgresUnitOfWork(migrated_engine),
            storage,
            now=datetime(2026, 8, 14, 19, tzinfo=UTC),
        )
        pinned = first_viewer.get("/api/demo/release/current")

        with TestClient(create_app(container=container)) as second_viewer:
            latest_created = second_viewer.post(
                "/api/demo/sessions",
                headers={"Origin": ORIGIN},
            )
            assert activate_demo_data(
                second_viewer, latest_created
            ).status_code == 200
            latest = second_viewer.get("/api/demo/release/current")

    assert pinned.status_code == 200
    assert replayed_first.dataset_version_id == first.dataset_version_id
    assert replayed_first.public_release_id == first.public_release_id
    assert replayed_first.created is False
    assert pinned.json()["dataset_version_id"] == str(first.dataset_version_id)
    assert latest_created.json()["session"]["dataset_version_id"] == str(
        second.dataset_version_id
    )
    assert latest.json()["dataset_version_id"] == str(second.dataset_version_id)


def test_viewer_session_creation_fails_closed_without_public_release(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    clock = initial_clock()
    container = replace(
        build_container(migrated_engine, clock),
        public_release_service=PublicReleaseService(
            migrated_engine,
            WORKSPACE_ID,
            idempotency_pepper=PEPPER,
            clock=clock,
        ),
    )

    with TestClient(create_app(container=container)) as client:
        response = client.post(
            "/api/demo/sessions",
            headers={"Origin": ORIGIN},
        )

    assert response.status_code == 503
    assert response.json() == {"code": "PUBLIC_RELEASE_UNAVAILABLE"}
