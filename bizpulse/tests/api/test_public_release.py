from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from api.main import create_app
from src.db.unit_of_work import PostgresUnitOfWork
from src.services.analysis_service import AnalysisService
from src.services.public_release_service import (
    PUBLIC_ANALYSIS_KINDS,
    PUBLIC_ANALYSIS_SCOPE,
    PublicReleaseService,
)
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.auth_support import (
    LOGIN_NAME,
    PASSWORD,
    activate_demo_data,
    build_container,
    fast_password_hasher,
    initial_clock,
    seed_public_release,
    seed_operator,
)
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID

ORIGIN = "http://testserver"
PEPPER = "test-public-release-idempotency-pepper"


def test_operator_can_inspect_a_current_release_before_analysis_repair(
    migrated_engine: Engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    version_id = seed_public_release(migrated_engine)
    clock = initial_clock()
    with TestClient(
        create_app(container=build_container(migrated_engine, clock))
    ) as client:
        login = client.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        current = client.get("/api/v1/datasets/public-release")

    assert login.status_code == 201
    assert current.status_code == 200
    assert current.json()["dataset_version_id"] == str(version_id)
    assert current.headers["cache-control"] == "private, no-store"


def test_public_release_describes_the_shared_three_month_authority(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    seed_operator(migrated_engine, fast_password_hasher())
    seeded = seed_demo(
        generate_demo(seed=20260813),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 13, 18, tzinfo=UTC),
    )
    clock = initial_clock()
    analyses = AnalysisService(migrated_engine, storage, WORKSPACE_ID, clock=clock)
    releases = PublicReleaseService(
        migrated_engine,
        WORKSPACE_ID,
        idempotency_pepper=PEPPER,
        clock=clock,
        analysis_service=analyses,
    )
    container = replace(
        build_container(migrated_engine, clock),
        workflow_storage=storage,
        analysis_service=analyses,
        public_release_service=releases,
    )

    with TestClient(create_app(container=container)) as client:
        login = client.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        response = client.get("/api/v1/datasets/public-release")
        created = client.post("/api/demo/sessions", headers={"Origin": ORIGIN})
        activate_demo_data(client, created)
        viewer_response = client.get("/api/demo/release/current")

    assert login.status_code == 201
    assert response.status_code == 200
    payload = response.json()
    assert datetime.fromisoformat(payload.pop("released_at")) == datetime(
        2026,
        8,
        13,
        18,
        tzinfo=UTC,
    )
    assert payload == {
        "release_id": str(seeded.public_release_id),
        "dataset_version_id": str(seeded.dataset_version_id),
        "version_number": 1,
        "schema_version": "synthetic.v1",
        "content_sha256": seeded.manifest_sha256,
        "source_classification": "pure_synthetic",
        "reporting_period": ["2026-05-01", "2026-07-31"],
        "current_period": ["2026-07-01", "2026-07-31"],
        "comparison_period": ["2026-06-01", "2026-06-30"],
        "currency": "BRL",
        "source_roles": [
            "daily_sales",
            "shopee_advertising",
            "product_inventory_sales",
            "inventory_movement",
            "inventory_receipt_lot",
            "outbound_event",
            "refund",
            "settlement",
            "fulfillment_cost",
            "operating_expense",
            "fx_assumption",
            "fx_effect",
            "other_variable_cost",
            "replenishment_policy",
            "product_catalog",
            "new_product_benchmark",
            "new_product_backtest_window",
        ],
    }
    assert created.status_code == 201
    assert viewer_response.status_code == 200
    assert viewer_response.json()["precomputed_analyses"] == list(
        PUBLIC_ANALYSIS_KINDS
    )
    assert viewer_response.json()["evidence_states"] == [
        "measured",
        "derived",
        "assumed",
        "unknown",
    ]


def test_viewer_release_fails_closed_when_required_metadata_is_incomplete(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    seed_operator(migrated_engine, fast_password_hasher())
    seed_demo(
        generate_demo(seed=20260813),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 13, 18, tzinfo=UTC),
    )
    clock = initial_clock()
    analyses = AnalysisService(migrated_engine, storage, WORKSPACE_ID, clock=clock)
    releases = PublicReleaseService(
        migrated_engine,
        WORKSPACE_ID,
        idempotency_pepper=PEPPER,
        clock=clock,
        analysis_service=analyses,
    )
    container = replace(
        build_container(migrated_engine, clock),
        workflow_storage=storage,
        analysis_service=analyses,
        public_release_service=releases,
    )

    with TestClient(create_app(container=container)) as client:
        created = client.post("/api/demo/sessions", headers={"Origin": ORIGIN})
        assert created.status_code == 201
        activate_demo_data(client, created)
        original = releases.for_session

        def incomplete_release(dataset_version_id):
            return replace(original(dataset_version_id), currency="")

        releases.for_session = incomplete_release
        response = client.get("/api/demo/release/current")

    assert response.status_code == 503
    assert response.json() == {"code": "PUBLIC_RELEASE_METADATA_INCOMPLETE"}
    assert response.headers["cache-control"] == "private, no-store"


def test_operator_publish_requires_auth_csrf_cas_and_idempotency(
    migrated_engine: Engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    storage = MemoryWorkflowStorage()
    clock = initial_clock()
    analyses = AnalysisService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=clock,
    )
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
    second = seed_demo(
        generate_demo(seed=20260814),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 14, 18, tzinfo=UTC),
    )
    container = replace(
        build_container(migrated_engine, clock),
        workflow_storage=storage,
        analysis_service=analyses,
        public_release_service=releases,
    )
    with TestClient(create_app(container=container)) as client:
        unauthenticated = client.post(
            f"/api/v1/datasets/versions/{first.dataset_version_id}/publish",
            headers={"Idempotency-Key": "publish-api"},
            json={"expected_current_id": str(second.dataset_version_id)},
        )
        login = client.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        published = client.post(
            f"/api/v1/datasets/versions/{first.dataset_version_id}/publish",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": login.json()["csrf_token"],
                "Idempotency-Key": "publish-api",
            },
            json={"expected_current_id": str(second.dataset_version_id)},
        )
        replay = client.post(
            f"/api/v1/datasets/versions/{first.dataset_version_id}/publish",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": login.json()["csrf_token"],
                "Idempotency-Key": "publish-api",
            },
            json={"expected_current_id": str(second.dataset_version_id)},
        )
        current = client.get("/api/v1/datasets/public-release")

    assert unauthenticated.status_code == 401
    assert published.status_code == 200
    assert published.json()["dataset_version_id"] == str(first.dataset_version_id)
    assert published.json()["previous_dataset_version_id"] == str(
        second.dataset_version_id
    )
    assert published.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert current.status_code == 200
    assert current.json()["dataset_version_id"] == str(first.dataset_version_id)
    assert current.json()["version_number"] == 1
    assert current.json()["source_classification"] == "pure_synthetic"
    assert current.headers["cache-control"] == "private, no-store"
    assert current.headers["vary"] == "Cookie"


def test_viewer_reads_only_completed_analysis_for_session_pinned_version(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    seed_operator(migrated_engine, fast_password_hasher())
    clock = initial_clock()
    analyses = AnalysisService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=clock,
    )
    releases = PublicReleaseService(
        migrated_engine,
        WORKSPACE_ID,
        idempotency_pepper=PEPPER,
        clock=clock,
        analysis_service=analyses,
    )
    seeded = seed_demo(
        generate_demo(seed=20260813),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 13, 18, tzinfo=UTC),
    )
    main_scope = {
        "store_id": "SYNTH-STORE-01",
        "period_start": "2026-07-01",
        "period_end": "2026-07-31",
        "currency": "BRL",
    }
    analyses.run(
        analyses.plan("sales_ads", seeded.dataset_version_id, main_scope),
        idempotency_key="prepare-public-sales",
    )
    all_scope = {
        key: value for key, value in main_scope.items() if key != "store_id"
    }
    launch_scope = {**all_scope, "store_id": "SYNTH-STORE-02"}

    def viewer_must_not_run(*_args, **_kwargs):
        raise AssertionError("viewer_read_triggered_analysis_run")

    analyses.run = viewer_must_not_run
    container = replace(
        build_container(migrated_engine, clock),
        workflow_storage=storage,
        analysis_service=analyses,
        public_release_service=releases,
    )

    with TestClient(create_app(container=container)) as client:
        created = client.post(
            "/api/demo/sessions",
            headers={"Origin": ORIGIN},
        )
        assert created.status_code == 201
        activate_demo_data(client, created)
        response = client.get(
            "/api/demo/release/analyses/sales_ads",
            params={"dataset_version_id": "00000000-0000-0000-0000-000000000000"},
        )
        main_response = client.get(
            "/api/demo/release/analyses/sales_ads",
            params={"store_id": "SYNTH-STORE-01"},
        )
        launch_response = client.get(
            "/api/demo/release/analyses/sales_ads",
            params={"store_id": "SYNTH-STORE-02"},
        )
        multiple_response = client.get(
            "/api/demo/release/analyses/sales_ads",
            params=[("store_id", "SYNTH-STORE-01"), ("store_id", "SYNTH-STORE-02")],
        )
        unknown_response = client.get(
            "/api/demo/release/analyses/sales_ads",
            params={"store_id": "SYNTH-STORE-404"},
        )
        login = client.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        operator_response = client.get("/api/v1/analyses/current/sales_ads")
        original_open = storage.open_verified

        def fail_closed_read(*_args, **_kwargs):
            raise RuntimeError("https://secret-account.invalid/private-object")

        storage.open_verified = fail_closed_read
        failed_read = client.get("/api/demo/release/analyses/sales_ads")
        storage.open_verified = original_open

    assert response.status_code == 200
    assert response.json()["run"]["dataset_version_id"] == str(
        seeded.dataset_version_id
    )
    assert response.json()["snapshot"]["scope"] == all_scope
    assert main_response.status_code == 200
    assert main_response.json()["snapshot"]["scope"] == main_scope
    assert launch_response.status_code == 200
    assert launch_response.json()["snapshot"]["scope"] == launch_scope
    assert multiple_response.status_code == 422
    assert unknown_response.status_code == 422
    assert response.json()["evidence"]
    assert "object_key" not in response.text
    assert login.status_code == 201
    assert operator_response.status_code == 200
    assert operator_response.json()["run"]["dataset_version_id"] == str(
        seeded.dataset_version_id
    )
    assert "object_key" not in operator_response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"
    assert operator_response.headers["cache-control"] == "private, no-store"
    assert failed_read.status_code == 503
    assert failed_read.json() == {"code": "ANALYSIS_UNAVAILABLE"}
    assert "secret-account" not in failed_read.text


def test_seed_publishes_only_with_exact_verified_analyses(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    seed_operator(migrated_engine, fast_password_hasher())
    seeded = seed_demo(
        generate_demo(seed=20260813),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 13, 18, tzinfo=UTC),
    )
    assert seeded.public_release_id is not None
    clock = initial_clock()
    analyses = AnalysisService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=clock,
    )
    releases = PublicReleaseService(
        migrated_engine,
        WORKSPACE_ID,
        idempotency_pepper=PEPPER,
        clock=clock,
        analysis_service=analyses,
    )
    container = replace(
        build_container(migrated_engine, clock),
        workflow_storage=storage,
        analysis_service=analyses,
        public_release_service=releases,
    )

    with TestClient(create_app(container=container)) as client:
        created = client.post("/api/demo/sessions", headers={"Origin": ORIGIN})

    assert created.status_code == 201
    assert created.json()["session"]["dataset_version_id"] == str(
        seeded.dataset_version_id
    )
    for kind in PUBLIC_ANALYSIS_KINDS:
        run, snapshot, evidence = analyses.get_exact_completed(
            kind,
            seeded.dataset_version_id,
            PUBLIC_ANALYSIS_SCOPE,
        )
        assert run.status == "completed"
        assert snapshot["dataset_version_id"] == str(seeded.dataset_version_id)
        assert evidence
