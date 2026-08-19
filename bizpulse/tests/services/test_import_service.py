from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.datasets import DatasetRepository
from src.repositories.imports import ImportRepository
from src.repositories.operators import OperatorRepository
from src.repositories.storage_objects import StorageObjectRepository

from src.services.import_service import (
    IdempotencyConflict,
    ImportDedupeConflict,
    ImportService,
    UploadInvalid,
    WorkflowNotReady,
    WorkflowRevisionConflict,
)
from src.storage.lifecycle import StorageLifecycle
from src.synthetic.manifest import load_bundle
from src.synthetic.seed import seed_demo
from tests.import_support import (
    FIXTURE_ROOT,
    WORKSPACE_ID,
    MemoryWorkflowStorage,
    fixture_bytes,
)


class SlowPromotionStorage(MemoryWorkflowStorage):
    def promote(self, staged_key, final_key, expected_sha256):
        time.sleep(0.1)
        return super().promote(staged_key, final_key, expected_sha256)


class OneShotCleanupFailureStorage(MemoryWorkflowStorage):
    def __init__(self, failed_key_fragment: str) -> None:
        super().__init__()
        self.failed_key_fragment = failed_key_fragment
        self.armed = False
        self.failed = False

    def delete(self, key, *, expected_etag=None) -> None:
        if self.armed and not self.failed and self.failed_key_fragment in key:
            self.failed = True
            raise RuntimeError("injected_blob_delete_failure")
        super().delete(key, expected_etag=expected_etag)


class InjectedCommitFailure(RuntimeError):
    pass


class FailingCommitImportService(ImportService):
    def _commit_database(self, *args, **kwargs):
        del args, kwargs
        raise InjectedCommitFailure


class CommitAcknowledgementLostUnitOfWork(PostgresUnitOfWork):
    def commit(self) -> None:
        super().commit()
        raise RuntimeError("injected_commit_acknowledgement_lost")


def build_service(engine: Engine, storage: MemoryWorkflowStorage) -> ImportService:
    return ImportService(
        engine=engine,
        storage=storage,
        workspace_id=WORKSPACE_ID,
        idempotency_pepper="test-import-idempotency-pepper",
    )


def _create_current_version(
    engine: Engine,
    *,
    content_sha256: str,
    base_version_id=None,
):
    with PostgresUnitOfWork(engine) as uow:
        repository = DatasetRepository(uow.connection)
        series = repository.get_series_by_name(WORKSPACE_ID, "synthetic-main")
        if series is None:
            series = repository.create_series(
                workspace_id=WORKSPACE_ID,
                name="synthetic-main",
                now=datetime.now(UTC),
            )
        version = repository.create_version(
            series_id=series.id,
            workspace_id=WORKSPACE_ID,
            source_workflow_id=None,
            base_version_id=base_version_id,
            version_number=repository.next_version_number(series.id),
            schema_version="canonical.import.v1",
            content_sha256=content_sha256,
            now=datetime.now(UTC),
        )
        repository.point_series_at(series.id, version.id)
        return version


def test_workflow_captures_current_dataset_version_once(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    first = _create_current_version(migrated_engine, content_sha256="a" * 64)
    service = build_service(migrated_engine, MemoryWorkflowStorage())

    workflow = service.create_workflow(True, "lineage-workflow").workflow
    _create_current_version(
        migrated_engine,
        content_sha256="b" * 64,
        base_version_id=first.id,
    )

    assert workflow.base_dataset_version_id == first.id


def test_commit_rejects_when_captured_base_is_no_longer_current(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    first = _create_current_version(migrated_engine, content_sha256="c" * 64)
    storage = MemoryWorkflowStorage()
    service = build_service(migrated_engine, storage)
    workflow, standardized = _prepared_advertising(service, "stale-base")
    _create_current_version(
        migrated_engine,
        content_sha256="d" * 64,
        base_version_id=first.id,
    )

    with pytest.raises(WorkflowNotReady, match="IMPORT_BASE_VERSION_CHANGED"):
        service.commit(
            workflow.id,
            expected_revision=standardized.workflow.revision,
            idempotency_key="stale-base-commit",
        )

    with migrated_engine.connect() as connection:
        imports = ImportRepository(connection)
        datasets = DatasetRepository(connection)
        unchanged = imports.get_workflow(workflow.id)
        committed = datasets.find_version_by_workflow(WORKSPACE_ID, workflow.id)
    assert unchanged is not None
    assert unchanged.status == "ready"
    assert committed is None
    assert all("/versions/" not in key for key in storage.objects)


def test_successful_commit_records_captured_base_lineage(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    first = _create_current_version(migrated_engine, content_sha256="e" * 64)
    storage = MemoryWorkflowStorage()
    service = build_service(migrated_engine, storage)
    workflow, standardized = _prepared_advertising(service, "record-base")

    committed = service.commit(
        workflow.id,
        expected_revision=standardized.workflow.revision,
        idempotency_key="record-base-commit",
    )

    with migrated_engine.connect() as connection:
        version = DatasetRepository(connection).get_version(
            committed.dataset_version_id
        )
    assert version is not None
    assert version.base_version_id == first.id


def test_commit_plan_reports_conflicts_without_mutating_workflow_or_objects(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryWorkflowStorage()
    service = build_service(migrated_engine, storage)
    workflow = service.create_workflow(
        source_confirmed_synthetic=None,
        idempotency_key="dedupe-conflict-workflow",
    ).workflow
    header = (
        "date,store_id,sku_id,spend_brl,impressions,clicks,"
        "attributed_orders\n"
    )
    standardized = None
    for index, spend in enumerate(("10.50", "11.50"), start=1):
        uploaded = service.upload(
            workflow.id,
            filename=f"advertising-{index}.csv",
            media_type="text/csv",
            content=(
                header
                + f"2026-07-01,BR-STORE-01,SKU-001,{spend},100,10,2\n"
            ).encode(),
            idempotency_key=f"dedupe-conflict-upload-{index}",
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
            expected_mapping_revision=recognized.upload.mapping_revision,
            mapping=recognized.upload.recognition["suggested_mapping"],
        )
        standardized = service.standardize(
            workflow.id,
            uploaded.upload.id,
            expected_revision=mapped.workflow.revision,
        )
    assert standardized is not None
    objects_before = dict(storage.objects)

    plan = service.commit_plan(workflow.id)

    assert plan.ready is False
    assert plan.content_sha256 is None
    assert plan.dedupe.rows_read == 2
    assert plan.dedupe.rows_retained == 1
    assert plan.dedupe.duplicates_removed == 0
    assert plan.dedupe.conflicts == 1
    assert len(plan.conflicts) == 1
    assert plan.conflicts_truncated is False
    assert plan.conflict_download_url.endswith(
        f"/{workflow.id}/conflicts.csv"
    )
    assert plan.conflicts[0].fields == ("spend_brl",)

    with pytest.raises(ImportDedupeConflict):
        service.commit(
            workflow.id,
            expected_revision=standardized.workflow.revision,
            idempotency_key="dedupe-conflict-commit",
        )

    with migrated_engine.connect() as connection:
        unchanged = ImportRepository(connection).get_workflow(workflow.id)
        version = DatasetRepository(connection).find_version_by_workflow(
            WORKSPACE_ID,
            workflow.id,
        )
    assert unchanged is not None
    assert unchanged.status == "ready"
    assert version is None
    assert storage.objects == objects_before


def test_explicit_store_assignment_is_catalog_bound_and_persisted(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryWorkflowStorage()
    base_content = (
        json.dumps(
            {
                "row_provenance": {},
                "schema_version": "canonical.import.v1",
                "store_catalog": [
                    {
                        "currency": "BRL",
                        "display_name_en": "Brazil Main Store",
                        "display_name_zh": "巴西主店",
                        "has_data": True,
                        "lifecycle": "established",
                        "opened_on": "2026-05-01",
                        "store_id": "BR-STORE-01",
                    }
                ],
                "tables": {},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    staged = storage.put_staging(
        BytesIO(base_content),
        max_bytes=len(base_content),
        media_type="application/json",
    )
    available = storage.promote(
        staged.key,
        "workspaces/base/catalog.json",
        staged.sha256,
    )
    storage.delete(staged.key, expected_etag=staged.etag)
    now = datetime.now(UTC)
    with PostgresUnitOfWork(migrated_engine) as uow:
        datasets = DatasetRepository(uow.connection)
        series = datasets.create_series(
            workspace_id=WORKSPACE_ID,
            name="synthetic-main",
            now=now,
        )
        version = datasets.create_version(
            series_id=series.id,
            workspace_id=WORKSPACE_ID,
            source_workflow_id=None,
            version_number=1,
            schema_version="canonical.import.v1",
            content_sha256=available.sha256,
            now=now,
        )
        storage_record = StorageObjectRepository(uow.connection).create_available(
            object_id=uuid4(),
            workspace_id=WORKSPACE_ID,
            available=available,
            purpose="normalized_dataset",
            media_type="application/json",
            now=now,
        )
        datasets.create_artifact(
            dataset_version_id=version.id,
            storage_object_id=storage_record.id,
            artifact_kind="canonical_dataset",
            sha256=available.sha256,
            now=now,
        )
        datasets.point_series_at(series.id, version.id)
    service = build_service(migrated_engine, storage)
    workflow = service.create_workflow(
        source_confirmed_synthetic=None,
        idempotency_key="assigned-store-workflow",
    ).workflow
    uploaded = service.upload(
        workflow.id,
        filename="storeless-advertising.csv",
        media_type="text/csv",
        content=(
            "date,sku_id,spend_brl,impressions,clicks,attributed_orders\n"
            "2026-07-01,SKU-001,10.50,100,10,2\n"
        ).encode(),
        idempotency_key="assigned-store-upload",
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
        expected_mapping_revision=recognized.upload.mapping_revision,
        mapping=recognized.upload.recognition["suggested_mapping"],
        assigned_store_id="BR-STORE-01",
    )
    standardized = service.standardize(
        workflow.id,
        uploaded.upload.id,
        expected_revision=mapped.workflow.revision,
    )

    assert mapped.upload.assigned_store_id == "BR-STORE-01"
    assert service.preview(workflow.id, uploaded.upload.id).records[0][
        "store_id"
    ] == "BR-STORE-01"
    assert standardized.upload.status == "accepted"


def test_operator_commit_extends_the_current_seeded_demo_base(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryWorkflowStorage()
    seeded = seed_demo(
        load_bundle(FIXTURE_ROOT),
        PostgresUnitOfWork(migrated_engine),
        storage,
    )
    service = build_service(migrated_engine, storage)
    workflow = service.create_workflow(
        source_confirmed_synthetic=None,
        idempotency_key="seeded-base-workflow",
    ).workflow
    uploaded = service.upload(
        workflow.id,
        filename="august-advertising.csv",
        media_type="text/csv",
        content=(
            "date,store_id,sku_id,spend_brl,impressions,clicks,"
            "attributed_orders\n"
            "2026-08-01,SYNTH-STORE-01,SYNTH-SKU-001,12.50,120,12,3\n"
        ).encode(),
        idempotency_key="seeded-base-upload",
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
        expected_mapping_revision=recognized.upload.mapping_revision,
        mapping=recognized.upload.recognition["suggested_mapping"],
    )
    standardized = service.standardize(
        workflow.id,
        uploaded.upload.id,
        expected_revision=mapped.workflow.revision,
    )

    plan = service.commit_plan(workflow.id)
    committed = service.commit(
        workflow.id,
        expected_revision=standardized.workflow.revision,
        idempotency_key="seeded-base-commit",
    )

    assert workflow.base_dataset_version_id == seeded.dataset_version_id
    assert plan.ready is True
    advertising = plan.dedupe.per_role["shopee_advertising"]
    assert advertising["rows_read"] > 1
    assert advertising["rows_retained"] == advertising["rows_read"]
    assert committed.version_number == 2


def test_operator_import_revisions_preview_and_exact_replay(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryWorkflowStorage()
    service = build_service(migrated_engine, storage)

    created = service.create_workflow(
        source_confirmed_synthetic=True,
        idempotency_key="workflow-1",
    )
    replay = service.create_workflow(
        source_confirmed_synthetic=True,
        idempotency_key="workflow-1",
    )
    uploaded = service.upload(
        created.workflow.id,
        filename="operator_import.xlsx",
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        content=fixture_bytes("operator_import.xlsx"),
        idempotency_key="upload-1",
    )
    recognized = service.recognize(
        created.workflow.id,
        uploaded.upload.id,
        expected_revision=uploaded.workflow.revision,
    )
    mapped = service.confirm_mapping(
        created.workflow.id,
        uploaded.upload.id,
        expected_revision=recognized.workflow.revision,
        expected_mapping_revision=recognized.upload.mapping_revision,
        mapping=recognized.upload.recognition["suggested_mapping"],
    )
    standardized = service.standardize(
        created.workflow.id,
        uploaded.upload.id,
        expected_revision=mapped.workflow.revision,
    )
    replayed_upload = service.upload(
        created.workflow.id,
        filename="operator_import.xlsx",
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        content=fixture_bytes("operator_import.xlsx"),
        idempotency_key="upload-1",
    )
    preview = service.preview(
        created.workflow.id,
        uploaded.upload.id,
        limit=3,
    )
    plan = service.commit_plan(created.workflow.id)
    with migrated_engine.connect() as connection:
        candidate = StorageObjectRepository(connection).get(
            standardized.upload.candidate_storage_object_id
        )
    assert candidate is not None
    candidate_payload = json.loads(storage.objects[candidate.object_key].content)
    committed = service.commit(
        created.workflow.id,
        expected_revision=standardized.workflow.revision,
        idempotency_key="commit-1",
    )
    replayed_commit = build_service(migrated_engine, storage).commit(
        created.workflow.id,
        expected_revision=standardized.workflow.revision,
        idempotency_key="commit-1",
    )

    assert replay == created
    assert replayed_upload == uploaded
    assert recognized.upload.adapter_id == "upseller_excel"
    assert mapped.upload.mapping_revision == 1
    assert standardized.upload.status == "accepted"
    assert set(candidate_payload["row_provenance"]) == set(
        candidate_payload["tables"]
    )
    assert all(
        len(candidate_payload["row_provenance"][role])
        == len(candidate_payload["tables"][role])
        for role in candidate_payload["tables"]
    )
    assert candidate_payload["row_provenance"]["daily_sales"][0] == {
        "row_number": 2,
        "sheet_name": "Daily Sales",
        "source_name": "operator_import.xlsx",
    }
    assert preview.candidate_sha256 == standardized.upload.quality_report["sha256"]
    assert len(preview.records) == 3
    assert plan.ready is True
    assert committed.created is True
    assert replayed_commit == committed
    assert all("staging" not in key for key in storage.objects)


def test_operator_workflow_accepts_supported_business_ids_without_synthetic_claim(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryWorkflowStorage()
    service = build_service(migrated_engine, storage)
    created = service.create_workflow(
        source_confirmed_synthetic=None,
        idempotency_key="operator-business-workflow",
    )
    content = (
        "date,store_id,sku_id,spend_brl,impressions,clicks,attributed_orders\n"
        "2026-07-01,BR-STORE-01,SKU-001,10.50,100,10,2\n"
    ).encode()

    uploaded = service.upload(
        created.workflow.id,
        filename="advertising.csv",
        media_type="text/csv",
        content=content,
        idempotency_key="operator-business-upload",
    )
    recognized = service.recognize(
        created.workflow.id,
        uploaded.upload.id,
        expected_revision=uploaded.workflow.revision,
    )
    mapped = service.confirm_mapping(
        created.workflow.id,
        uploaded.upload.id,
        expected_revision=recognized.workflow.revision,
        expected_mapping_revision=recognized.upload.mapping_revision,
        mapping=recognized.upload.recognition["suggested_mapping"],
    )
    standardized = service.standardize(
        created.workflow.id,
        uploaded.upload.id,
        expected_revision=mapped.workflow.revision,
    )
    preview = service.preview(created.workflow.id, uploaded.upload.id)
    with migrated_engine.connect() as connection:
        candidate = StorageObjectRepository(connection).get(
            standardized.upload.candidate_storage_object_id
        )
    assert candidate is not None
    candidate_payload = json.loads(storage.objects[candidate.object_key].content)

    assert created.workflow.source_kind == "operator_upload"
    assert created.workflow.source_confirmed_synthetic is False
    assert standardized.upload.status == "accepted"
    assert candidate_payload["row_provenance"]["shopee_advertising"] == [
        {
            "row_number": 2,
            "sheet_name": None,
            "source_name": "advertising.csv",
        }
    ]
    assert preview.records[0]["store_id"] == "BR-STORE-01"
    assert preview.records[0]["sku_id"] == "SKU-001"


def test_exact_upload_replay_does_not_reinvoke_adapter(
    migrated_engine: Engine,
    monkeypatch,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryWorkflowStorage()
    service = build_service(migrated_engine, storage)
    workflow = service.create_workflow(True, "parser-independent-workflow").workflow
    content = fixture_bytes("advertising.csv")
    uploaded = service.upload(
        workflow.id,
        filename="advertising.csv",
        media_type="text/csv",
        content=content,
        idempotency_key="parser-independent-upload",
    )
    monkeypatch.setattr(
        service._adapters,
        "inspect",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("parser_busy")),
    )

    replayed = service.upload(
        workflow.id,
        filename="advertising.csv",
        media_type="text/csv",
        content=content,
        idempotency_key="parser-independent-upload",
    )

    assert replayed == uploaded
    assert len(storage.objects) == 1


def test_duplicate_content_idempotency_conflict_and_stale_revision_fail_closed(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryWorkflowStorage()
    service = build_service(migrated_engine, storage)
    workflow = service.create_workflow(True, "workflow-conflicts").workflow
    content = fixture_bytes("advertising.csv")
    uploaded = service.upload(
        workflow.id,
        filename="advertising.csv",
        media_type="text/csv",
        content=content,
        idempotency_key="upload-conflicts",
    )

    with pytest.raises(IdempotencyConflict):
        service.upload(
            workflow.id,
            filename="advertising-copy.csv",
            media_type="text/csv",
            content=content,
            idempotency_key="upload-conflicts",
        )
    with pytest.raises(UploadInvalid, match="duplicate_upload"):
        service.upload(
            workflow.id,
            filename="advertising-copy.csv",
            media_type="text/csv",
            content=content,
            idempotency_key="upload-new-key",
        )
    with pytest.raises(WorkflowRevisionConflict):
        service.recognize(
            workflow.id,
            uploaded.upload.id,
            expected_revision=workflow.revision,
        )

    assert len(storage.objects) == 1


def test_concurrent_exact_commit_replay_cannot_delete_committed_blob(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = SlowPromotionStorage()
    service = build_service(migrated_engine, storage)
    workflow = service.create_workflow(True, "concurrent-workflow").workflow
    upload = service.upload(
        workflow.id,
        filename="advertising.csv",
        media_type="text/csv",
        content=fixture_bytes("advertising.csv"),
        idempotency_key="concurrent-upload",
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

    def commit_once():
        return service.commit(
            workflow.id,
            expected_revision=standardized.workflow.revision,
            idempotency_key="concurrent-commit",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _index: commit_once(), range(2)))

    assert results[0] == results[1]
    assert all(result.created for result in results)
    assert results[0].dataset_version_id == results[1].dataset_version_id
    assert len(storage.objects) == 1
    assert all("/versions/" in key for key in storage.objects)


def test_upload_recovers_authoritative_result_when_commit_ack_is_lost(
    migrated_engine: Engine,
    monkeypatch,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryWorkflowStorage()
    service = build_service(migrated_engine, storage)
    workflow = service.create_workflow(True, "ambiguous-upload-workflow").workflow
    monkeypatch.setattr(
        "src.services.import_service.PostgresUnitOfWork",
        CommitAcknowledgementLostUnitOfWork,
    )

    uploaded = service.upload(
        workflow.id,
        filename="advertising.csv",
        media_type="text/csv",
        content=fixture_bytes("advertising.csv"),
        idempotency_key="ambiguous-upload",
    )

    assert uploaded.upload.status == "staged"
    assert len(storage.objects) == 1
    assert next(iter(storage.objects)).startswith("workspaces/staging/")


def test_standardization_recovers_candidate_when_commit_ack_is_lost(
    migrated_engine: Engine,
    monkeypatch,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryWorkflowStorage()
    service = build_service(migrated_engine, storage)
    workflow = service.create_workflow(
        True,
        "ambiguous-standardization-workflow",
    ).workflow
    upload = service.upload(
        workflow.id,
        filename="advertising.csv",
        media_type="text/csv",
        content=fixture_bytes("advertising.csv"),
        idempotency_key="ambiguous-standardization-upload",
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
    monkeypatch.setattr(
        "src.services.import_service.PostgresUnitOfWork",
        CommitAcknowledgementLostUnitOfWork,
    )

    standardized = service.standardize(
        workflow.id,
        upload.upload.id,
        expected_revision=mapped.workflow.revision,
    )

    assert standardized.upload.status == "accepted"
    assert standardized.upload.candidate_storage_object_id is not None
    assert len(storage.objects) == 2


def test_failed_post_commit_staging_delete_is_expired_from_durable_ledger(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = OneShotCleanupFailureStorage("/staging/")
    service = build_service(migrated_engine, storage)
    workflow, standardized = _prepared_advertising(service, "cleanup-success")
    storage.armed = True

    service.commit(
        workflow.id,
        expected_revision=standardized.workflow.revision,
        idempotency_key="cleanup-success-commit",
    )

    with migrated_engine.connect() as connection:
        expired = StorageObjectRepository(connection).list_expired_temporary(
            WORKSPACE_ID,
            datetime.now(UTC) + timedelta(minutes=1),
        )
    assert len(expired) == 1
    assert expired[0].state == "quarantined"
    assert expired[0].object_key in storage.objects

    assert (
        StorageLifecycle(migrated_engine, storage, WORKSPACE_ID).expire(
            datetime.now(UTC) + timedelta(minutes=1)
        )
        == 1
    )
    assert expired[0].object_key not in storage.objects
    assert len(storage.objects) == 1
    assert all("/versions/" in key for key in storage.objects)


def test_failed_rollback_final_delete_is_expired_from_durable_ledger(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = OneShotCleanupFailureStorage("/versions/")
    service = FailingCommitImportService(
        engine=migrated_engine,
        storage=storage,
        workspace_id=WORKSPACE_ID,
        idempotency_pepper="test-import-idempotency-pepper",
    )
    workflow, standardized = _prepared_advertising(service, "cleanup-rollback")
    storage.armed = True

    with pytest.raises(InjectedCommitFailure) as captured:
        service.commit(
            workflow.id,
            expected_revision=standardized.workflow.revision,
            idempotency_key="cleanup-rollback-commit",
        )

    assert any("final_cleanup_pending" in note for note in captured.value.__notes__)
    with migrated_engine.connect() as connection:
        expired = StorageObjectRepository(connection).list_expired_temporary(
            WORKSPACE_ID,
            datetime.now(UTC) + timedelta(minutes=1),
        )
    final_cleanup = tuple(
        record for record in expired if "/versions/" in record.object_key
    )
    assert len(final_cleanup) == 1
    assert final_cleanup[0].state == "quarantined"

    assert (
        StorageLifecycle(migrated_engine, storage, WORKSPACE_ID).expire(
            datetime.now(UTC) + timedelta(minutes=1)
        )
        == 1
    )
    assert final_cleanup[0].object_key not in storage.objects

    committed = build_service(migrated_engine, storage).commit(
        workflow.id,
        expected_revision=standardized.workflow.revision,
        idempotency_key="cleanup-rollback-commit",
    )
    assert committed.created is True
    assert len(
        [key for key in storage.objects if "/versions/" in key]
    ) == 1


def _prepared_advertising(
    service: ImportService,
    scope: str,
):
    workflow = service.create_workflow(True, f"{scope}-workflow").workflow
    upload = service.upload(
        workflow.id,
        filename="advertising.csv",
        media_type="text/csv",
        content=fixture_bytes("advertising.csv"),
        idempotency_key=f"{scope}-upload",
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
    return workflow, standardized
