from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select

from src.db.schema import (
    analysis_runs,
    dataset_artifacts,
    dataset_series,
    dataset_versions,
    public_releases,
)
from tests.auth_support import (
    activate_demo_data,
    build_auth_app,
    fast_password_hasher,
    initial_clock,
    seed_operator,
    seed_public_release,
)


AUTHORITATIVE_TABLES = (
    dataset_series,
    dataset_versions,
    dataset_artifacts,
    analysis_runs,
    public_releases,
)


def _authoritative_counts(engine: Engine) -> tuple[int, ...]:
    with engine.connect() as connection:
        return tuple(
            int(connection.scalar(select(func.count()).select_from(table)) or 0)
            for table in AUTHORITATIVE_TABLES
        )


def test_fifteen_viewers_activate_one_shared_dataset_without_recalculation(
    migrated_engine: Engine,
) -> None:
    clock = initial_clock()
    seed_operator(migrated_engine, fast_password_hasher())
    version_id = seed_public_release(migrated_engine)
    app = build_auth_app(migrated_engine, clock)
    before = _authoritative_counts(migrated_engine)
    session_ids: set[str] = set()
    version_ids: set[str] = set()

    for _index in range(15):
        with TestClient(app) as viewer:
            created = viewer.post(
                "/api/demo/sessions",
                headers={"Origin": "http://testserver"},
            )
            activated = activate_demo_data(viewer, created)
            current = viewer.get("/api/demo/sessions/current")

        assert created.status_code == 201
        assert activated.status_code == 200
        assert current.status_code == 200
        session_ids.add(current.json()["session"]["session_id"])
        version_ids.add(current.json()["session"]["dataset_version_id"])

    assert len(session_ids) == 15
    assert version_ids == {str(version_id)}
    assert _authoritative_counts(migrated_engine) == before
