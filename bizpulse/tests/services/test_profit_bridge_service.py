from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError

from src.db.schema import profit_bridge_items, profit_bridges
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.services.analysis_service import AnalysisService
from src.profit.bridge import build_profit_bridge
from src.profit.contracts import ProfitPeriod, ProfitSku
from src.services.profit_bridge_service import ProfitBridgeService, _profit_period
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID


def test_service_persists_and_reuses_exact_reconciling_bridge(
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
    analyses = AnalysisService(migrated_engine, storage, WORKSPACE_ID)
    service = ProfitBridgeService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        analysis_service=analyses,
    )

    first = service.run(
        seeded.dataset_version_id,
        current_period=(date(2026, 7, 1), date(2026, 7, 31)),
        comparison_period=(date(2026, 6, 1), date(2026, 6, 30)),
        scope={"store_id": "SYNTH-STORE-01", "currency": "BRL"},
    )
    replay = service.run(
        seeded.dataset_version_id,
        current_period=(date(2026, 7, 1), date(2026, 7, 31)),
        comparison_period=(date(2026, 6, 1), date(2026, 6, 30)),
        scope={"currency": "BRL", "store_id": "SYNTH-STORE-01"},
    )

    assert replay == first
    assert first.reconciled is True
    assert first.dataset_version_id == seeded.dataset_version_id
    assert first.baseline_analysis_id != first.current_analysis_id
    assert tuple(item.driver for item in first.items) == (
        "volume",
        "price_discount",
        "mix",
        "advertising",
        "refunds",
        "fulfillment",
        "platform_fees",
        "cogs",
        "fx",
        "tax",
        "other_mapped",
        "residual",
    )
    assert first.items[-1].amount_brl == first.residual_brl
    assert service.get(first.id) == first

    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(profit_bridges)) == 3
        assert (
            connection.scalar(select(func.count()).select_from(profit_bridge_items))
            == 36
        )

    with pytest.raises(DBAPIError):
        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE profit_bridges SET reconciled = false WHERE id = :id"
                ),
                {"id": first.id},
            )
    with pytest.raises(DBAPIError):
        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM profit_bridge_items "
                    "WHERE bridge_id = :id AND ordinal = 1"
                ),
                {"id": first.id},
            )


def test_default_bridge_is_exact_scope_and_marks_unallocated_shared_costs(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    seeded = seed_demo(
        generate_demo(seed=20260816),
        PostgresUnitOfWork(migrated_engine),
        storage,
    )
    analyses = AnalysisService(migrated_engine, storage, WORKSPACE_ID)
    service = ProfitBridgeService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        analysis_service=analyses,
    )
    periods = {
        "current_period": (date(2026, 7, 1), date(2026, 7, 31)),
        "comparison_period": (date(2026, 6, 1), date(2026, 6, 30)),
    }
    all_scope = {"currency": "BRL"}
    launch_scope = {"currency": "BRL", "store_id": "SYNTH-STORE-02"}
    all_bridge = service.run(
        seeded.dataset_version_id,
        scope=all_scope,
        **periods,
    )
    launch_bridge = service.run(
        seeded.dataset_version_id,
        scope=launch_scope,
        **periods,
    )

    assert service.default(seeded.dataset_version_id, all_scope).id == all_bridge.id
    assert service.default(
        seeded.dataset_version_id,
        launch_scope,
    ).id == launch_bridge.id
    assert all_bridge.shared_costs_unallocated is False
    assert launch_bridge.shared_costs_unallocated is True


def test_prior_uncovered_fifo_makes_period_cogs_driver_unknown() -> None:
    current = _profit_period(
        (date(2026, 6, 1), date(2026, 6, 30)),
        {"result": {"contribution_profit": {"value": "50.00"}}},
        {
            "daily_sales": (
                {
                    "sku_id": "SYNTH-SKU-001",
                    "units": 5,
                    "gross_sales_brl": "200.00",
                    "discount_brl": "0.00",
                },
            ),
            "inventory_receipt_lot": (
                {
                    "lot_id": "LOT-OLD",
                    "sku_id": "SYNTH-SKU-001",
                    "receipt_date": "2026-05-01",
                    "quantity_received": 5,
                    "unit_cost_brl": "10.00",
                },
                {
                    "lot_id": "LOT-LATE",
                    "sku_id": "SYNTH-SKU-001",
                    "receipt_date": "2026-06-15",
                    "quantity_received": 5,
                    "unit_cost_brl": "20.00",
                },
            ),
            "outbound_event": (
                {
                    "outbound_id": "OUT-PRIOR",
                    "sku_id": "SYNTH-SKU-001",
                    "date": "2026-05-31",
                    "quantity": 10,
                },
                {
                    "outbound_id": "OUT-CURRENT",
                    "sku_id": "SYNTH-SKU-001",
                    "date": "2026-06-30",
                    "quantity": 5,
                },
            ),
            "settlement": ({"fee_brl": "10.00"},),
            "shopee_advertising": ({"spend_brl": "10.00"},),
            "refund": ({"refund_brl": "0.00"},),
            "fulfillment_cost": ({"cost_brl": "10.00"},),
            "fx_effect": ({"effect_brl": "0.00"},),
            "other_variable_cost": ({"cost_brl": "10.00"},),
        },
    )
    baseline = ProfitPeriod(
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 30),
        skus=(ProfitSku("SYNTH-SKU-001", 5, Decimal("40"), Decimal("10")),),
        contribution_profit_brl=Decimal("50"),
        platform_fee_brl=Decimal("10"),
        advertising_brl=Decimal("10"),
        refund_loss_brl=Decimal("0"),
        fulfillment_brl=Decimal("10"),
        tax_brl=Decimal("0"),
        fx_effect_brl=Decimal("0"),
        other_mapped_brl=Decimal("10"),
    )

    bridge = build_profit_bridge(current, baseline)

    assert current.skus[0].unit_cogs_brl is None
    assert bridge.item("cogs").evidence_state == "unknown"
    assert bridge.reconciled is False
