from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select

from src.db.schema import (
    analysis_runs,
    dataset_series,
    dataset_versions,
    import_workflows,
    storage_objects,
    upload_records,
)
from tests.auth_support import (
    LOGIN_NAME,
    PASSWORD,
    activate_demo_data,
    build_auth_app,
    fast_password_hasher,
    initial_clock,
    seed_operator,
    seed_public_release,
)

ORIGIN = "http://testserver"
AUTHORITATIVE_TABLES = (
    dataset_series,
    dataset_versions,
    import_workflows,
    upload_records,
    analysis_runs,
    storage_objects,
)


def _counts(engine: Engine) -> tuple[int, ...]:
    with engine.connect() as connection:
        return tuple(
            int(connection.scalar(select(func.count()).select_from(table)) or 0)
            for table in AUTHORITATIVE_TABLES
        )


def test_viewer_activation_changes_no_authoritative_data_rows(
    migrated_engine: Engine,
) -> None:
    clock = initial_clock()
    seed_operator(migrated_engine, fast_password_hasher())
    seed_public_release(migrated_engine)

    with TestClient(build_auth_app(migrated_engine, clock)) as viewer:
        created = viewer.post("/api/demo/sessions", headers={"Origin": ORIGIN})
        before = _counts(migrated_engine)
        first = activate_demo_data(viewer, created)
        after_first = _counts(migrated_engine)
        second = activate_demo_data(viewer, created)
        after_second = _counts(migrated_engine)

    assert first.status_code == 200
    assert second.status_code == 200
    assert before == after_first == after_second


def test_unactivated_viewer_is_gated_without_restricting_operator_reads(
    migrated_engine: Engine,
) -> None:
    clock = initial_clock()
    seed_operator(migrated_engine, fast_password_hasher())
    seed_public_release(migrated_engine)
    app = build_auth_app(migrated_engine, clock)

    with TestClient(app) as viewer:
        viewer.post("/api/demo/sessions", headers={"Origin": ORIGIN})
        blocked = (
            viewer.get("/api/demo/release/current"),
            viewer.get("/api/demo/library/current"),
            viewer.get("/api/demo/library/current/tables/daily_sales"),
            viewer.get("/api/demo/release/actions"),
            viewer.get("/api/v1/ai-chat/turns"),
        )

    with TestClient(app) as operator:
        login = operator.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        release = operator.get("/api/v1/datasets/public-release")

    assert all(response.status_code == 409 for response in blocked)
    assert all(
        response.json() == {"code": "DEMO_DATA_NOT_IMPORTED"}
        for response in blocked
    )
    assert login.status_code == 201
    assert release.status_code == 200
