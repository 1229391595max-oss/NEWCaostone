from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine

from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.datasets import DatasetRepository
from src.repositories.imports import ImportRepository
from src.repositories.operators import OperatorRepository

WORKSPACE_ID = "synthetic-demo"


def seed_workspace(engine: Engine) -> None:
    with PostgresUnitOfWork(engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)


def test_import_workflow_revision_compare_and_swap(migrated_engine: Engine) -> None:
    seed_workspace(migrated_engine)
    now = datetime.now(UTC)
    with PostgresUnitOfWork(migrated_engine) as uow:
        repository = ImportRepository(uow.connection)
        created = repository.create_workflow(
            workspace_id=WORKSPACE_ID,
            source_confirmed_synthetic=True,
            now=now,
        )
        updated = repository.transition_workflow(
            created.id,
            expected_revision=0,
            status="uploading",
            now=now,
        )

    assert created.revision == 0
    assert updated.revision == 1
    with PostgresUnitOfWork(migrated_engine) as uow:
        assert (
            ImportRepository(uow.connection).transition_workflow(
                created.id,
                expected_revision=0,
                status="ready",
                now=now,
            )
            is None
        )


def test_workflow_and_dataset_version_record_base_lineage(
    migrated_engine: Engine,
) -> None:
    seed_workspace(migrated_engine)
    now = datetime.now(UTC)
    with PostgresUnitOfWork(migrated_engine) as uow:
        datasets = DatasetRepository(uow.connection)
        series = datasets.create_series(
            workspace_id=WORKSPACE_ID,
            name="synthetic-main",
            now=now,
        )
        first = datasets.create_version(
            series_id=series.id,
            workspace_id=WORKSPACE_ID,
            source_workflow_id=None,
            base_version_id=None,
            version_number=1,
            schema_version="canonical.import.v1",
            content_sha256="a" * 64,
            now=now,
        )
        datasets.point_series_at(series.id, first.id)
        workflow = ImportRepository(uow.connection).create_workflow(
            workspace_id=WORKSPACE_ID,
            source_confirmed_synthetic=True,
            base_dataset_version_id=first.id,
            now=now,
        )
        second = datasets.create_version(
            series_id=series.id,
            workspace_id=WORKSPACE_ID,
            source_workflow_id=workflow.id,
            base_version_id=first.id,
            version_number=2,
            schema_version="canonical.import.v1",
            content_sha256="b" * 64,
            now=now,
        )

    assert workflow.base_dataset_version_id == first.id
    assert second.base_version_id == first.id


def test_dataset_versions_are_append_only_and_release_history_is_retained(
    migrated_engine: Engine,
) -> None:
    seed_workspace(migrated_engine)
    now = datetime.now(UTC)
    with PostgresUnitOfWork(migrated_engine) as uow:
        repository = DatasetRepository(uow.connection)
        series = repository.create_series(
            workspace_id=WORKSPACE_ID,
            name="synthetic-main",
            now=now,
        )
        first = repository.create_version(
            series_id=series.id,
            workspace_id=WORKSPACE_ID,
            source_workflow_id=None,
            version_number=1,
            schema_version="synthetic.v1",
            content_sha256="1" * 64,
            now=now,
        )
        second = repository.create_version(
            series_id=series.id,
            workspace_id=WORKSPACE_ID,
            source_workflow_id=None,
            version_number=2,
            schema_version="synthetic.v1",
            content_sha256="2" * 64,
            now=now,
        )
        repository.point_series_at(series.id, second.id)
        repository.activate_release(
            workspace_id=WORKSPACE_ID,
            dataset_version_id=first.id,
            now=now,
        )
        active = repository.activate_release(
            workspace_id=WORKSPACE_ID,
            dataset_version_id=second.id,
            now=now,
        )

    with migrated_engine.connect() as connection:
        repository = DatasetRepository(connection)
        releases = repository.list_releases(WORKSPACE_ID)
        current = repository.get_series(series.id)

    assert current is not None
    assert current.current_version_id == second.id
    assert active.dataset_version_id == second.id
    assert [release.is_active for release in releases] == [False, True]
    assert releases[0].retired_at == now
    assert {release.id for release in releases} == {
        releases[0].id,
        active.id,
    }
    assert releases[0].id != active.id
