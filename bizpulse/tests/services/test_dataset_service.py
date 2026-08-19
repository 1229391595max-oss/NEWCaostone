from __future__ import annotations

import pytest
from sqlalchemy import Engine

from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.services.dataset_service import DatasetService
from src.services.analysis_service import AnalysisService
from src.services.import_service import ImportService, WorkflowNotReady
from src.services.public_release_service import PublicReleaseService
from tests.import_support import WORKSPACE_ID, MemoryWorkflowStorage, fixture_bytes


def test_committed_version_can_be_published_without_overwriting_history(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryWorkflowStorage()
    imports = ImportService(
        engine=migrated_engine,
        storage=storage,
        workspace_id=WORKSPACE_ID,
        idempotency_pepper="test-import-idempotency-pepper",
    )
    workflow = imports.create_workflow(True, "workflow-publish").workflow
    upload = imports.upload(
        workflow.id,
        filename="advertising.csv",
        media_type="text/csv",
        content=fixture_bytes("advertising.csv"),
        idempotency_key="upload-publish",
    )
    recognized = imports.recognize(
        workflow.id,
        upload.upload.id,
        expected_revision=upload.workflow.revision,
    )
    mapped = imports.confirm_mapping(
        workflow.id,
        upload.upload.id,
        expected_revision=recognized.workflow.revision,
        expected_mapping_revision=0,
        mapping=recognized.upload.recognition["suggested_mapping"],
    )
    standardized = imports.standardize(
        workflow.id,
        upload.upload.id,
        expected_revision=mapped.workflow.revision,
    )
    committed = imports.commit(
        workflow.id,
        expected_revision=standardized.workflow.revision,
        idempotency_key="commit-publish",
    )
    datasets = DatasetService(migrated_engine, WORKSPACE_ID)
    releases = PublicReleaseService(
        migrated_engine,
        WORKSPACE_ID,
        idempotency_pepper="test-release-idempotency-pepper",
        analysis_service=AnalysisService(
            migrated_engine,
            storage,
            WORKSPACE_ID,
        ),
    )

    first = releases.publish(
        committed.dataset_version_id,
        expected_current_id=None,
        idempotency_key="publish-committed-version",
    )
    replay = releases.publish(
        committed.dataset_version_id,
        expected_current_id=None,
        idempotency_key="publish-committed-version",
    )

    assert first.dataset_version_id == committed.dataset_version_id
    assert replay.release_id == first.release_id
    assert replay.replayed is True
    assert datasets.current_public_release().id == first.release_id
    assert datasets.list_versions()[0].id == committed.dataset_version_id


def test_identical_dataset_content_cannot_create_a_second_version(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryWorkflowStorage()
    imports = ImportService(
        engine=migrated_engine,
        storage=storage,
        workspace_id=WORKSPACE_ID,
        idempotency_pepper="test-import-idempotency-pepper",
    )

    def prepare(prefix: str):
        workflow = imports.create_workflow(True, f"{prefix}-workflow").workflow
        upload = imports.upload(
            workflow.id,
            filename="advertising.csv",
            media_type="text/csv",
            content=fixture_bytes("advertising.csv"),
            idempotency_key=f"{prefix}-upload",
        )
        recognized = imports.recognize(
            workflow.id,
            upload.upload.id,
            expected_revision=upload.workflow.revision,
        )
        mapped = imports.confirm_mapping(
            workflow.id,
            upload.upload.id,
            expected_revision=recognized.workflow.revision,
            expected_mapping_revision=0,
            mapping=recognized.upload.recognition["suggested_mapping"],
        )
        standardized = imports.standardize(
            workflow.id,
            upload.upload.id,
            expected_revision=mapped.workflow.revision,
        )
        return workflow.id, standardized.workflow.revision

    first_id, first_revision = prepare("first")
    imports.commit(
        first_id,
        expected_revision=first_revision,
        idempotency_key="first-commit",
    )
    second_id, second_revision = prepare("second")

    with pytest.raises(WorkflowNotReady, match="duplicate_dataset_content"):
        imports.commit(
            second_id,
            expected_revision=second_revision,
            idempotency_key="second-commit",
        )

    assert len(DatasetService(migrated_engine, WORKSPACE_ID).list_versions()) == 1
