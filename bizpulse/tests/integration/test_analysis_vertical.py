from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import json
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select

from src.db.schema import workspaces
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.analyses import AnalysisRepository
from src.repositories.datasets import DatasetRepository
from src.repositories.operators import OperatorRepository
from src.repositories.storage_objects import StorageObjectRepository
from src.services.analysis_service import (
    AnalysisAuthorityUnavailable,
    AnalysisBusy,
    AnalysisInvalid,
    AnalysisService,
)
from src.storage.lifecycle import StorageLifecycle
from src.storage.keys import dataset_object_key
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID


class ArmedPromotionFailureStorage(MemoryWorkflowStorage):
    fail_promote = False

    def promote(self, staged_key, final_key, expected_sha256):
        if self.fail_promote:
            raise RuntimeError("injected_analysis_promotion_failure")
        return super().promote(staged_key, final_key, expected_sha256)


class ArmedDeleteFailureStorage(MemoryWorkflowStorage):
    fail_staging_delete = False
    fail_final_delete = False

    def delete(self, key, *, expected_etag=None) -> None:
        if self.fail_staging_delete and "/staging/" in key:
            raise RuntimeError("injected_staging_delete_failure")
        if self.fail_final_delete and "/evidence/" in key:
            raise RuntimeError("injected_final_delete_failure")
        return super().delete(key, expected_etag=expected_etag)


class PublishAcknowledgementLostUnitOfWork(PostgresUnitOfWork):
    commit_count = 0

    def commit(self) -> None:
        super().commit()
        type(self).commit_count += 1
        if type(self).commit_count == 4:
            raise RuntimeError("injected_publish_acknowledgement_lost")


class StartAcknowledgementLostUnitOfWork(PostgresUnitOfWork):
    commit_count = 0

    def commit(self) -> None:
        super().commit()
        type(self).commit_count += 1
        if type(self).commit_count == 1:
            raise RuntimeError("injected_start_acknowledgement_lost")


def test_one_version_produces_five_immutable_evidenced_runs(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    version_id = _seed_version(migrated_engine, storage)
    service = AnalysisService(migrated_engine, storage, WORKSPACE_ID)
    scope = {
        "store_id": "SYNTH-STORE-01",
        "period_start": "2026-07-01",
        "period_end": "2026-07-30",
        "currency": "BRL",
    }

    results = {}
    for kind in (
        "sales_ads",
        "inventory_risk",
        "fifo_cost_aging",
        "operating_profit",
        "replenishment",
    ):
        plan = service.plan(kind, version_id, scope)
        result = service.run(plan, idempotency_key=f"run-{kind}")
        assert result.status == "completed"
        assert result.dataset_version_id == version_id
        assert result.artifact_sha256
        assert result.evidence_count > 0
        snapshot = service.get_snapshot(result.run_id)
        assert snapshot["dataset_version_id"] == str(version_id)
        assert snapshot["algorithm_version"] == plan.algorithm_version
        assert snapshot["input_hash"] == plan.input_hash
        if kind == "sales_ads":
            assert snapshot["result"]["gross_sales"]["value"] == "400.00"
            assert snapshot["result"]["ad_spend"]["value"] == "40.00"
            assert "scope_rows_excluded:shopee_advertising:2" in snapshot[
                "limitations"
            ]
        if kind == "operating_profit":
            assert snapshot["coverage"]["included_rows"]["operating_expense"] == 0
            assert "scope_rows_excluded:operating_expense:2" in snapshot[
                "limitations"
            ]
            assert snapshot["coverage"]["included_rows"]["tax"] == 1
            assert "scope_rows_excluded:tax:1" in snapshot["limitations"]
        if kind == "inventory_risk":
            assert snapshot["coverage"]["included_rows"][
                "product_inventory_sales"
            ] == 1
            assert snapshot["result"]["items"][0]["on_hand_units"] == 8
        if kind == "fifo_cost_aging":
            assert snapshot["result"]["cogs"]["value"] == "120.00"
            assert snapshot["result"]["ending_inventory_value"]["value"] == "330.00"
        results[kind] = result

    replay = service.run(
        service.plan("sales_ads", version_id, scope),
        idempotency_key="a-different-key",
    )
    assert replay.run_id == results["sales_ads"].run_id
    assert replay.artifact_sha256 == results["sales_ads"].artifact_sha256
    assert replay.disposition == "reused"


def test_generated_seeded_public_dataset_produces_all_five_analysis_runs(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    seeded = seed_demo(
        generate_demo(),
        PostgresUnitOfWork(migrated_engine),
        storage,
    )
    service = AnalysisService(migrated_engine, storage, WORKSPACE_ID)
    scope = {
        "store_id": "SYNTH-STORE-01",
        "period_start": "2026-07-01",
        "period_end": "2026-07-31",
        "currency": "BRL",
    }

    snapshots = {}
    for kind in (
        "sales_ads",
        "inventory_risk",
        "fifo_cost_aging",
        "operating_profit",
        "replenishment",
    ):
        result = service.run(
            service.plan(kind, seeded.dataset_version_id, scope),
            idempotency_key=f"seeded-{kind}",
        )
        assert result.status == "completed"
        assert result.evidence_count > 0
        snapshots[kind] = service.get_snapshot(result.run_id)

    assert snapshots["sales_ads"]["result"]["gross_sales"]["value"] is not None
    assert snapshots["inventory_risk"]["result"]["items"]
    assert snapshots["fifo_cost_aging"]["result"]["cogs"]["value"] is not None
    assert snapshots["fifo_cost_aging"]["result"]["ending_inventory_value"][
        "value"
    ] is not None
    assert snapshots["replenishment"]["result"]["items"][0][
        "recommended_quantity"
    ] is not None


def test_store_scopes_conserve_totals_recompute_ratios_and_mark_preopening(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    seeded = seed_demo(
        generate_demo(seed=20260816),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 16, tzinfo=UTC),
    )
    service = AnalysisService(migrated_engine, storage, WORKSPACE_ID)
    common = {
        "period_start": "2026-07-01",
        "period_end": "2026-07-31",
        "currency": "BRL",
    }
    snapshots = {}
    for label, scope in (
        ("all", common),
        ("main", {**common, "store_id": "SYNTH-STORE-01"}),
        ("launch", {**common, "store_id": "SYNTH-STORE-02"}),
    ):
        run = service.run(
            service.plan("sales_ads", seeded.dataset_version_id, scope),
            idempotency_key=f"three-scope-sales-{label}",
        )
        snapshots[label] = service.get_snapshot(run.run_id)

    def value(label, metric):
        return Decimal(snapshots[label]["result"][metric]["value"])

    assert value("all", "gross_sales") == (
        value("main", "gross_sales") + value("launch", "gross_sales")
    )
    assert value("all", "ad_spend") == (
        value("main", "ad_spend") + value("launch", "ad_spend")
    )
    assert value("all", "aov") == (
        value("all", "net_sales") / value("all", "orders")
    ).quantize(Decimal("0.01"))
    assert value("all", "aov") != (
        (value("main", "aov") + value("launch", "aov")) / Decimal(2)
    ).quantize(Decimal("0.01"))

    preopening = {
        "period_start": "2026-07-01",
        "period_end": "2026-07-07",
        "currency": "BRL",
        "store_id": "SYNTH-STORE-02",
    }
    run = service.run(
        service.plan("sales_ads", seeded.dataset_version_id, preopening),
        idempotency_key="launch-store-preopening",
    )

    assert service.get_snapshot(run.run_id)["state"] == "not_opened_yet"


def test_running_rows_are_recovered_before_exact_rerun(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    version_id = _seed_version(migrated_engine, storage)
    service = AnalysisService(migrated_engine, storage, WORKSPACE_ID)
    plan = service.plan("sales_ads", version_id, {"period_end": "2026-07-30", "currency": "BRL"})
    with PostgresUnitOfWork(migrated_engine) as uow:
        AnalysisRepository(uow.connection).insert_running(
            plan,
            datetime.now(UTC) - timedelta(minutes=10),
        )

    restarted = AnalysisService(migrated_engine, storage, WORKSPACE_ID)
    result = restarted.run(plan, idempotency_key="after-restart")

    assert result.status == "completed"
    assert result.disposition == "created"


def test_active_running_analysis_is_not_failed_by_second_service(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    version_id = _seed_version(migrated_engine, storage)
    service = AnalysisService(migrated_engine, storage, WORKSPACE_ID)
    plan = service.plan(
        "sales_ads",
        version_id,
        {"period_end": "2026-07-30", "currency": "BRL"},
    )
    with PostgresUnitOfWork(migrated_engine) as uow:
        AnalysisRepository(uow.connection).insert_running(plan, datetime.now(UTC))

    restarted = AnalysisService(migrated_engine, storage, WORKSPACE_ID)
    with pytest.raises(AnalysisBusy):
        restarted.run(plan, idempotency_key="still-active")

    with migrated_engine.connect() as connection:
        active = AnalysisRepository(connection).find_exact(plan)
    assert active is not None
    assert active.status == "running"


def test_expired_running_analysis_is_taken_over_without_service_restart(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    version_id = _seed_version(migrated_engine, storage)
    now = datetime.now(UTC)
    current_time = [now]
    service = AnalysisService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=lambda: current_time[0],
    )
    plan = service.plan(
        "sales_ads",
        version_id,
        {"period_end": "2026-07-30", "currency": "BRL"},
    )
    with PostgresUnitOfWork(migrated_engine) as uow:
        AnalysisRepository(uow.connection).insert_running(plan, now)
    current_time[0] = now + timedelta(minutes=6)

    result = service.run(plan, idempotency_key="same-service-takeover")

    assert result.status == "completed"
    assert result.disposition == "created"


def test_scope_rejects_non_brl_reversed_period_and_empty_sku_set(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    version_id = _seed_version(migrated_engine, storage)
    service = AnalysisService(migrated_engine, storage, WORKSPACE_ID)

    for scope in (
        {"period_end": "2026-07-30", "currency": "USD"},
        {"period_start": "2026-07-31", "period_end": "2026-07-30", "currency": "BRL"},
        {"period_end": "2026-07-30", "currency": "BRL", "sku_ids": []},
    ):
        with pytest.raises(AnalysisInvalid):
            service.plan("sales_ads", version_id, scope)


def test_failed_analysis_promotion_removes_staged_blob_and_records_failure(
    migrated_engine: Engine,
) -> None:
    storage = ArmedPromotionFailureStorage()
    version_id = _seed_version(migrated_engine, storage)
    service = AnalysisService(migrated_engine, storage, WORKSPACE_ID)
    plan = service.plan(
        "sales_ads",
        version_id,
        {"period_end": "2026-07-30", "currency": "BRL"},
    )
    dataset_keys = set(storage.objects)
    storage.fail_promote = True

    with pytest.raises(RuntimeError, match="injected_analysis_promotion_failure"):
        service.run(plan, idempotency_key="promotion-fails")

    assert set(storage.objects) == dataset_keys
    with migrated_engine.connect() as connection:
        failed = AnalysisRepository(connection).find_exact(plan)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.failure_code == "RuntimeError"


def test_staging_delete_failure_is_durable_and_lifecycle_retryable(
    migrated_engine: Engine,
) -> None:
    storage = ArmedDeleteFailureStorage()
    version_id = _seed_version(migrated_engine, storage)
    service = AnalysisService(migrated_engine, storage, WORKSPACE_ID)
    plan = service.plan(
        "sales_ads",
        version_id,
        {"period_end": "2026-07-30", "currency": "BRL"},
    )
    storage.fail_staging_delete = True

    result = service.run(plan, idempotency_key="staging-delete-fails")

    assert result.status == "completed"
    with migrated_engine.connect() as connection:
        expired = StorageObjectRepository(connection).list_expired_temporary(
            WORKSPACE_ID,
            datetime.now(UTC) + timedelta(minutes=1),
        )
    assert len(expired) == 1
    assert expired[0].state == "quarantined"
    assert "/staging/" in expired[0].object_key

    storage.fail_staging_delete = False
    assert (
        StorageLifecycle(migrated_engine, storage, WORKSPACE_ID).expire(
            datetime.now(UTC) + timedelta(minutes=1)
        )
        == 1
    )


def test_final_delete_failure_is_durable_and_lifecycle_retryable(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = ArmedDeleteFailureStorage()
    version_id = _seed_version(migrated_engine, storage)
    service = AnalysisService(migrated_engine, storage, WORKSPACE_ID)
    plan = service.plan(
        "sales_ads",
        version_id,
        {"period_end": "2026-07-30", "currency": "BRL"},
    )
    storage.fail_final_delete = True

    def fail_publication(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("injected_analysis_publish_failure")

    monkeypatch.setattr(AnalysisRepository, "complete", fail_publication)
    with pytest.raises(RuntimeError, match="injected_analysis_publish_failure"):
        service.run(plan, idempotency_key="final-delete-fails")

    with migrated_engine.connect() as connection:
        expired = StorageObjectRepository(connection).list_expired_temporary(
            WORKSPACE_ID,
            datetime.now(UTC) + timedelta(minutes=1),
        )
    assert len(expired) == 1
    assert expired[0].state == "quarantined"
    assert "/evidence/" in expired[0].object_key

    storage.fail_final_delete = False
    assert (
        StorageLifecycle(migrated_engine, storage, WORKSPACE_ID).expire(
            datetime.now(UTC) + timedelta(minutes=1)
        )
        == 1
    )


def test_publish_commit_ack_lost_uses_database_authority_and_keeps_artifact(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = MemoryWorkflowStorage()
    version_id = _seed_version(migrated_engine, storage)
    service = AnalysisService(migrated_engine, storage, WORKSPACE_ID)
    plan = service.plan(
        "sales_ads",
        version_id,
        {"period_end": "2026-07-30", "currency": "BRL"},
    )
    PublishAcknowledgementLostUnitOfWork.commit_count = 0
    monkeypatch.setattr(
        "src.services.analysis_service.PostgresUnitOfWork",
        PublishAcknowledgementLostUnitOfWork,
    )

    result = service.run(plan, idempotency_key="publish-ack-lost")

    assert result.status == "completed"
    assert result.disposition == "created"
    assert service.get_snapshot(result.run_id)["run_id"] == str(result.run_id)
    assert any("/evidence/" in key for key in storage.objects)


def test_start_commit_ack_lost_uses_database_authority_and_continues(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = MemoryWorkflowStorage()
    version_id = _seed_version(migrated_engine, storage)
    service = AnalysisService(migrated_engine, storage, WORKSPACE_ID)
    plan = service.plan(
        "sales_ads",
        version_id,
        {"period_end": "2026-07-30", "currency": "BRL"},
    )
    StartAcknowledgementLostUnitOfWork.commit_count = 0
    monkeypatch.setattr(
        "src.services.analysis_service.PostgresUnitOfWork",
        StartAcknowledgementLostUnitOfWork,
    )

    result = service.run(plan, idempotency_key="start-ack-lost")

    assert result.status == "completed"
    assert result.disposition == "created"
    assert service.get_snapshot(result.run_id)["run_id"] == str(result.run_id)


def test_active_publication_is_not_expired_between_final_ledger_and_commit(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = MemoryWorkflowStorage()
    version_id = _seed_version(migrated_engine, storage)
    now = datetime.now(UTC)
    service = AnalysisService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=lambda: now,
    )
    plan = service.plan(
        "sales_ads",
        version_id,
        {"period_end": "2026-07-30", "currency": "BRL"},
    )
    original_publish = service._publish

    def publish_after_concurrent_expiry(*args, **kwargs):
        assert (
            StorageLifecycle(
                migrated_engine,
                storage,
                WORKSPACE_ID,
                clock=lambda: now,
            ).expire(now)
            == 0
        )
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(service, "_publish", publish_after_concurrent_expiry)

    result = service.run(plan, idempotency_key="lifecycle-during-publication")

    assert result.status == "completed"
    assert service.get_snapshot(result.run_id)["run_id"] == str(result.run_id)


def test_read_projections_fail_closed_when_snapshot_blob_is_tampered(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    version_id = _seed_version(migrated_engine, storage)
    service = AnalysisService(migrated_engine, storage, WORKSPACE_ID)
    plan = service.plan(
        "sales_ads",
        version_id,
        {"period_end": "2026-07-30", "currency": "BRL"},
    )
    result = service.run(plan, idempotency_key="tamper-read")
    evidence_key = next(key for key in storage.objects if "/evidence/" in key)
    storage.objects[evidence_key].content = b'{"tampered":true}'

    with pytest.raises(AnalysisAuthorityUnavailable):
        service.get(result.run_id)
    with pytest.raises(AnalysisAuthorityUnavailable):
        service.get_evidence(result.run_id)


def _seed_version(engine: Engine, storage: MemoryWorkflowStorage):
    now = datetime.now(UTC)
    tables = {
        "daily_sales": [
            {"date": "2026-07-01", "order_id": "O-1", "store_id": "SYNTH-STORE-01", "sku_id": "SKU-A", "units": 2, "gross_sales_brl": "200.00", "discount_brl": "10.00"},
            {"date": "2026-07-02", "order_id": "O-2", "store_id": "SYNTH-STORE-01", "sku_id": "SKU-A", "units": 2, "gross_sales_brl": "200.00", "discount_brl": "0.00"},
            {"date": "2026-07-02", "order_id": "OTHER-1", "store_id": "SYNTH-STORE-OTHER", "sku_id": "SKU-Z", "units": 99, "gross_sales_brl": "9999.00", "discount_brl": "0.00"},
        ],
        "shopee_advertising": [
            {"date": "2026-07-01", "store_id": "SYNTH-STORE-01", "sku_id": "SKU-A", "spend_brl": "40.00", "impressions": 1000, "clicks": 50, "attributed_orders": 2},
            {"date": "2026-07-01", "sku_id": "SKU-A", "spend_brl": "900.00", "impressions": 1000, "clicks": 50, "attributed_orders": 2},
            {"store_id": "SYNTH-STORE-01", "sku_id": "SKU-A", "spend_brl": "800.00", "impressions": 1000, "clicks": 50, "attributed_orders": 2},
        ],
        "product_inventory_sales": [{"date": "2026-06-30", "store_id": "SYNTH-STORE-01", "sku_id": "SKU-A", "on_hand_units": 8, "inbound_units": 2}],
        "inventory_receipt_lot": [{"lot_id": "L-1", "receipt_date": "2026-06-01", "store_id": "SYNTH-STORE-01", "sku_id": "SKU-A", "quantity_received": 20, "unit_cost_brl": "30.00"}],
        "outbound_event": [
            {"outbound_id": "OUT-HISTORY", "date": "2026-06-15", "store_id": "SYNTH-STORE-01", "sku_id": "SKU-A", "quantity": 5},
            {"outbound_id": "OUT-1", "date": "2026-07-30", "store_id": "SYNTH-STORE-01", "sku_id": "SKU-A", "quantity": 4},
        ],
        "refund": [{"refund_id": "R-1", "store_id": "SYNTH-STORE-01", "refund_brl": "0.00"}],
        "settlement": [{"fee_id": "F-1", "store_id": "SYNTH-STORE-01", "fee_brl": "56.00"}],
        "fulfillment_cost": [{"fulfillment_id": "U-1", "store_id": "SYNTH-STORE-01", "cost_brl": "26.00"}],
        "operating_expense": [
            {"expense_id": "E-1", "amount_brl": "45.00"},
            {"expense_id": "E-2", "store_id": "SYNTH-STORE-01", "period_start": "2026-07-01", "period_end": "2026-07-31", "amount_brl": "500.00"},
        ],
        "tax": [
            {"tax_id": "T-1", "store_id": "SYNTH-STORE-01", "period_start": "2026-07-01", "period_end": "2026-07-30", "tax_brl": "20.00"},
            {"tax_id": "T-OLD", "store_id": "SYNTH-STORE-01", "period_start": "2026-06-01", "period_end": "2026-06-30", "tax_brl": "999.00"},
        ],
        "replenishment_policy": [{"policy_id": "P-1", "sku_id": "SKU-A", "lead_time_days": 10, "safety_stock_units": 5, "reorder_point_units": 40, "target_cover_days": 30, "unit_cost_brl": "30.00"}],
    }
    store_catalog = [
        {
            "currency": "BRL",
            "display_name_en": store_id,
            "display_name_zh": store_id,
            "has_data": True,
            "lifecycle": "established",
            "opened_on": None,
            "store_id": store_id,
        }
        for store_id in ("SYNTH-STORE-01", "SYNTH-STORE-OTHER")
    ]
    content = json.dumps(
        {
            "schema_version": "canonical.import.v1",
            "store_catalog": store_catalog,
            "tables": tables,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = sha256(content).hexdigest()
    staged = storage.put_staging(BytesIO(content), max_bytes=1_000_000, media_type="application/json")
    version_id = uuid4()
    available = storage.promote(staged.key, dataset_object_key(WORKSPACE_ID, str(version_id), digest), digest)
    with PostgresUnitOfWork(engine) as uow:
        if uow.connection.scalar(
            select(workspaces.c.id).where(workspaces.c.id == WORKSPACE_ID)
        ) is None:
            OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
        datasets = DatasetRepository(uow.connection)
        series = datasets.create_series(workspace_id=WORKSPACE_ID, name="synthetic-main", now=now)
        version = datasets.create_version(series_id=series.id, workspace_id=WORKSPACE_ID, source_workflow_id=None, version_number=1, schema_version="canonical.import.v1", content_sha256=digest, now=now, version_id=version_id)
        stored = StorageObjectRepository(uow.connection).create_available(object_id=uuid4(), workspace_id=WORKSPACE_ID, available=available, purpose="normalized_dataset", media_type="application/json", now=now)
        datasets.create_artifact(dataset_version_id=version.id, storage_object_id=stored.id, artifact_kind="synthetic_bundle_1", sha256=digest, now=now)
        datasets.point_series_at(series.id, version.id)
    storage.delete(staged.key, expected_etag=staged.etag)
    return version_id
