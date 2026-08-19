from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select
from azure.storage.blob import ContainerClient

from src.db.schema import dataset_artifacts, dataset_versions
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.services.import_service import ImportService, WorkflowNotReady
from src.storage.azure_blob_workflow_storage import AzureBlobWorkflowStorage
from src.storage.postgres_entry_locks import PostgresEntryLockManager
from tests.import_support import WORKSPACE_ID, MemoryWorkflowStorage, fixture_bytes


def test_two_file_commit_is_atomic_and_succeeds_only_when_both_are_ready(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryWorkflowStorage()
    service = ImportService(
        engine=migrated_engine,
        storage=storage,
        workspace_id=WORKSPACE_ID,
        idempotency_pepper="test-import-idempotency-pepper",
    )
    workflow = service.create_workflow(True, "atomic-workflow").workflow
    sales = service.upload(
        workflow.id,
        filename="sales.csv",
        media_type="text/csv",
        content=fixture_bytes("sales.csv"),
        idempotency_key="atomic-sales",
    )
    recognized = service.recognize(
        workflow.id,
        sales.upload.id,
        expected_revision=sales.workflow.revision,
    )
    mapped = service.confirm_mapping(
        workflow.id,
        sales.upload.id,
        expected_revision=recognized.workflow.revision,
        expected_mapping_revision=0,
        mapping=recognized.upload.recognition["suggested_mapping"],
    )
    prepared = service.standardize(
        workflow.id,
        sales.upload.id,
        expected_revision=mapped.workflow.revision,
    )
    advertising = service.upload(
        workflow.id,
        filename="advertising.csv",
        media_type="text/csv",
        content=fixture_bytes("advertising.csv"),
        idempotency_key="atomic-advertising",
    )

    with pytest.raises(WorkflowNotReady):
        service.commit(
            workflow.id,
            expected_revision=advertising.workflow.revision,
            idempotency_key="atomic-commit",
        )

    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(dataset_versions)) == 0
    assert prepared.upload.status == "accepted"

    recognized_advertising = service.recognize(
        workflow.id,
        advertising.upload.id,
        expected_revision=advertising.workflow.revision,
    )
    mapped_advertising = service.confirm_mapping(
        workflow.id,
        advertising.upload.id,
        expected_revision=recognized_advertising.workflow.revision,
        expected_mapping_revision=0,
        mapping=recognized_advertising.upload.recognition["suggested_mapping"],
    )
    standardized_advertising = service.standardize(
        workflow.id,
        advertising.upload.id,
        expected_revision=mapped_advertising.workflow.revision,
    )
    committed = service.commit(
        workflow.id,
        expected_revision=standardized_advertising.workflow.revision,
        idempotency_key="atomic-commit-ready",
    )

    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(dataset_versions)) == 1
    assert committed.created is True
    assert len(storage.objects) == 1
    assert all("/versions/" in key for key in storage.objects)
    assert all("/staging/" not in key for key in storage.objects)


def test_workbook_and_standalone_ads_exact_duplicates_commit_once(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryWorkflowStorage()
    service = ImportService(
        engine=migrated_engine,
        storage=storage,
        workspace_id=WORKSPACE_ID,
        idempotency_pepper="test-import-idempotency-pepper",
    )
    workflow = service.create_workflow(True, "semantic-duplicate-workflow").workflow
    standardized = None
    sources = (
        (
            "operator_import.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        ("advertising.csv", "text/csv"),
    )
    for filename, media_type in sources:
        uploaded = service.upload(
            workflow.id,
            filename=filename,
            media_type=media_type,
            content=fixture_bytes(filename),
            idempotency_key=f"semantic-duplicate-{filename}",
        )
        recognized = service.recognize(
            workflow.id,
            uploaded.upload.id,
            expected_revision=uploaded.workflow.revision,
        )
        mapped = service.confirm_mapping(
            workflow.id,
            uploaded.upload.id,
            expected_revision=recognized.workflow.revision,
            expected_mapping_revision=0,
            mapping=recognized.upload.recognition["suggested_mapping"],
        )
        standardized = service.standardize(
            workflow.id,
            uploaded.upload.id,
            expected_revision=mapped.workflow.revision,
        )
    assert standardized is not None

    plan = service.commit_plan(workflow.id)
    committed = service.commit(
        workflow.id,
        expected_revision=standardized.workflow.revision,
        idempotency_key="semantic-duplicate-commit",
    )

    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(dataset_versions)) == 1
        assert connection.scalar(select(func.count()).select_from(dataset_artifacts)) == 1
    assert plan.ready is True
    assert plan.dedupe.duplicates_removed > 0
    assert committed.created is True
    assert len(storage.objects) == 1
    assert all("/versions/" in key for key in storage.objects)


def test_postgres_and_azurite_commit_one_replay_safe_version(
    migrated_engine: Engine,
) -> None:
    connection_string = os.getenv("BIZPULSE_TEST_AZURITE_CONNECTION_STRING")
    if connection_string is None:
        pytest.skip("requires the controlled Azurite test process")
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    container = ContainerClient.from_connection_string(
        connection_string,
        container_name=f"newcaostone-import-{uuid4().hex}",
    )
    container.create_container()
    try:
        storage = AzureBlobWorkflowStorage(
            container_client=container,
            workspace_id=WORKSPACE_ID,
            staging_scope="operator-import",
            entry_locks=PostgresEntryLockManager(migrated_engine),
        )
        service = ImportService(
            engine=migrated_engine,
            storage=storage,
            workspace_id=WORKSPACE_ID,
            idempotency_pepper="test-import-idempotency-pepper",
        )
        workflow = service.create_workflow(True, "azurite-workflow").workflow
        standardized = None
        for filename in ("advertising.csv", "sales.csv"):
            upload = service.upload(
                workflow.id,
                filename=filename,
                media_type="text/csv",
                content=fixture_bytes(filename),
                idempotency_key=f"azurite-upload-{filename}",
            )
            recognized = service.recognize(
                workflow.id,
                upload.upload.id,
                expected_revision=upload.workflow.revision,
            )
            mapped = service.confirm_mapping(
                workflow.id,
                upload.upload.id,
                expected_revision=recognized.workflow.revision,
                expected_mapping_revision=0,
                mapping=recognized.upload.recognition["suggested_mapping"],
            )
            standardized = service.standardize(
                workflow.id,
                upload.upload.id,
                expected_revision=mapped.workflow.revision,
            )
        assert standardized is not None
        committed = service.commit(
            workflow.id,
            expected_revision=standardized.workflow.revision,
            idempotency_key="azurite-commit",
        )
        replay = ImportService(
            engine=migrated_engine,
            storage=storage,
            workspace_id=WORKSPACE_ID,
            idempotency_pepper="test-import-idempotency-pepper",
        ).commit(
            workflow.id,
            expected_revision=standardized.workflow.revision,
            idempotency_key="azurite-commit",
        )

        inventory = storage.inventory("workspaces")
        assert replay == committed
        assert len(inventory) == 1
        assert all("/versions/" in item.key for item in inventory)
        assert all("/staging/" not in item.key for item in inventory)
    finally:
        container.delete_container()
