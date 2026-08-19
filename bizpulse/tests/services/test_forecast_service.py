from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from threading import Event

import pytest
from sqlalchemy import Engine, func, select

from src.db.unit_of_work import PostgresUnitOfWork
from src.db.schema import forecast_scenarios
from src.forecast.contracts import ForecastRequest, ProductCandidate
from src.forecast.new_product import ForecastBlocked
from src.repositories.operators import OperatorRepository
from src.services.forecast_service import (
    ForecastInvalid,
    ForecastService,
    _historical_catalog,
)
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID


class CommitAcknowledgementLostUnitOfWork(PostgresUnitOfWork):
    def commit(self) -> None:
        super().commit()
        raise RuntimeError("injected_forecast_commit_acknowledgement_lost")


def _seed(migrated_engine: Engine, storage: MemoryWorkflowStorage):
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    return seed_demo(
        generate_demo(),
        PostgresUnitOfWork(migrated_engine),
        storage,
    )


def _request(**overrides) -> ForecastRequest:
    values = {
        "candidate": ProductCandidate(
            product_name="Synthetic Portable Organizer",
            category="travel_bag",
            attributes=("portable", "zippered", "compact"),
            planned_launch_date=date(2026, 8, 20),
            planned_price_brl=Decimal("119.90"),
            expected_discount_brl=Decimal("5.00"),
            unit_cost_brl=Decimal("42.00"),
            opening_inventory_units=80,
            moq_units=24,
            lead_time_days=18,
            planned_daily_ad_brl=Decimal("12.00"),
        ),
        "safety_stock_units": 20,
        "assumptions": ("synthetic_launch_ramp",),
        "missing_fields": (),
    }
    values.update(overrides)
    return ForecastRequest(**values)


def test_service_requires_confirmation_and_persists_exact_completed_forecast(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    seeded = _seed(migrated_engine, storage)
    service = ForecastService(migrated_engine, storage, WORKSPACE_ID)

    created = service.create(
        seeded.dataset_version_id,
        _request(),
        idempotency_key="forecast-primary-001",
    )
    replayed_draft = service.create(
        seeded.dataset_version_id,
        _request(),
        idempotency_key="forecast-primary-001",
    )
    alternative_draft = service.create(
        seeded.dataset_version_id,
        _request(),
        idempotency_key="forecast-alternative-001",
    )

    assert created.status == "draft"
    assert replayed_draft == created
    assert alternative_draft.id != created.id
    assert alternative_draft.input_hash == created.input_hash
    conflicting_request = _request(
        candidate=ProductCandidate(
            **{
                **_request().candidate.as_dict(),
                "product_name": "Synthetic Conflicting Organizer",
            }
        )
    )
    with pytest.raises(ForecastInvalid) as conflict:
        service.create(
            seeded.dataset_version_id,
            conflicting_request,
            idempotency_key="forecast-primary-001",
        )
    assert conflict.value.code == "FORECAST_IDEMPOTENCY_CONFLICT"
    assert len(created.analogs) == 5
    assert all(not analog.confirmed for analog in created.analogs)
    first_history = created.analogs[0].historical_snapshot
    if first_history["sku_id"] == "SYNTH-SKU-001":
        assert Decimal(str(first_history["net_price_brl"])) < Decimal("129.90")
    with pytest.raises(ForecastBlocked, match="analogs_not_confirmed"):
        service.run(created.id)

    selected = tuple(analog.sku_id for analog in created.analogs[:2])
    confirmed = service.confirm_analogs(created.id, selected)
    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent = tuple(executor.map(service.run, (created.id, created.id)))
    completed = concurrent[0]
    replay = service.run(created.id)
    fetched = service.get(created.id)

    assert confirmed.status == "analogs_confirmed"
    assert [item.sku_id for item in confirmed.analogs if item.confirmed] == list(
        selected
    )
    assert completed.status == "completed"
    assert completed.confidence == "medium"
    assert completed.result["by_horizon"]["30"]["units"]["base"] > 0
    assert concurrent[0] == concurrent[1] == replay == fetched
    assert completed.input_hash == created.input_hash
    assert completed.result["evidence"]["analog_sku_ids"] == sorted(selected)
    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(forecast_scenarios).where(
                forecast_scenarios.c.forecast_id == created.id
            )
        ) == 9


def test_forecast_identity_and_latest_reads_are_exact_store_scoped(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    seeded = _seed(migrated_engine, storage)
    service = ForecastService(migrated_engine, storage, WORKSPACE_ID)
    all_scope = {"currency": "BRL"}
    launch_scope = {"currency": "BRL", "store_id": "SYNTH-STORE-02"}

    all_forecast = service.latest_completed(seeded.dataset_version_id, all_scope)
    launch = service.create(
        seeded.dataset_version_id,
        _request(),
        scope=launch_scope,
        idempotency_key="forecast-launch-store-001",
    )
    service.confirm_analogs(
        launch.id,
        tuple(item.sku_id for item in launch.analogs[:2]),
    )
    completed = service.run(launch.id)

    assert completed.input_snapshot["scope"] == launch_scope
    assert completed.input_hash != all_forecast.input_hash
    assert service.latest(seeded.dataset_version_id, launch_scope).id == completed.id
    assert service.latest_completed(
        seeded.dataset_version_id,
        launch_scope,
    ).id == completed.id
    assert service.completed_id_for_session(
        seeded.dataset_version_id,
        launch_scope,
    ) == completed.id
    assert service.latest_completed(
        seeded.dataset_version_id,
        all_scope,
    ).id == all_forecast.id


def test_service_backtest_is_persisted_and_labeled_synthetic_only(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    seeded = _seed(migrated_engine, storage)
    service = ForecastService(migrated_engine, storage, WORKSPACE_ID)
    created = service.create(
        seeded.dataset_version_id,
        _request(),
        idempotency_key="forecast-backtest-001",
    )
    selected = tuple(analog.sku_id for analog in created.analogs[:3])
    service.confirm_analogs(created.id, selected)

    first = service.backtest(created.id)
    completed = service.run(created.id)
    replay = service.backtest(created.id)

    assert first == replay == completed.backtest
    assert first["synthetic_demo_only"] is True
    assert first["exact_repeat"] is True
    assert first["evidence"]["claim_boundary"] == (
        "synthetic_demo_behavior_not_market_accuracy"
    )
    assert first["evidence"]["evaluation_scope"] == (
        "algorithm_hidden_window_not_candidate_actual"
    )
    assert first["evidence"]["window_ids"] == ["SYNTH-HIDDEN-LAUNCH-001"]


def test_missing_sales_fact_cannot_be_silently_zeroed() -> None:
    tables = {
        "product_catalog": (
            {
                "sku_id": "SYNTH-SKU-001",
                "category": "travel_bag",
                "attributes": "portable|compact",
                "unit_price_brl": "100.00",
                "unit_cost_brl": "40.00",
            },
        ),
        "daily_sales": (
            {
                "date": "2026-07-01",
                "sku_id": "SYNTH-SKU-001",
                "units": 2,
                "gross_sales_brl": "200.00",
            },
        ),
        "shopee_advertising": (
            {
                "date": "2026-07-01",
                "sku_id": "SYNTH-SKU-001",
                "spend_brl": "10.00",
            },
        ),
    }

    with pytest.raises(ForecastInvalid) as captured:
        _historical_catalog(tables, date(2026, 8, 1))

    assert captured.value.code == "FORECAST_HISTORY_INCOMPLETE"


@pytest.mark.parametrize("missing_dimension", ("category", "attributes"))
def test_complete_history_cannot_hide_missing_product_dimensions(
    missing_dimension: str,
) -> None:
    products: list[dict[str, object]] = []
    sales: list[dict[str, object]] = []
    advertising: list[dict[str, object]] = []
    first_day = date(2026, 5, 3)
    for sku_number in range(1, 4):
        sku_id = f"SYNTH-SKU-{sku_number:03d}"
        product: dict[str, object] = {
            "sku_id": sku_id,
            "category": "travel_bag",
            "attributes": "portable|compact",
            "unit_price_brl": "100.00",
            "unit_cost_brl": "40.00",
        }
        product.pop(missing_dimension)
        products.append(product)
        for offset in range(90):
            day = (first_day + timedelta(days=offset)).isoformat()
            sales.append(
                {
                    "date": day,
                    "sku_id": sku_id,
                    "units": 2,
                    "gross_sales_brl": "200.00",
                    "discount_brl": "0.00",
                }
            )
            advertising.append(
                {
                    "date": day,
                    "sku_id": sku_id,
                    "spend_brl": "10.00",
                }
            )

    with pytest.raises(ForecastInvalid) as captured:
        _historical_catalog(
            {
                "product_catalog": tuple(products),
                "daily_sales": tuple(sales),
                "shopee_advertising": tuple(advertising),
            },
            date(2026, 8, 1),
        )

    assert captured.value.code == "FORECAST_HISTORY_INCOMPLETE"


def test_create_uses_database_authority_when_commit_acknowledgement_is_lost(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = MemoryWorkflowStorage()
    seeded = _seed(migrated_engine, storage)
    service = ForecastService(migrated_engine, storage, WORKSPACE_ID)
    monkeypatch.setattr(
        "src.services.forecast_service.PostgresUnitOfWork",
        CommitAcknowledgementLostUnitOfWork,
    )

    created = service.create(
        seeded.dataset_version_id,
        _request(),
        idempotency_key="forecast-create-ack-lost-001",
    )
    replayed = service.create(
        seeded.dataset_version_id,
        _request(),
        idempotency_key="forecast-create-ack-lost-001",
    )

    assert replayed == created
    assert created.status == "draft"


def test_run_and_reconfirmation_share_one_authoritative_analog_revision(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = MemoryWorkflowStorage()
    seeded = _seed(migrated_engine, storage)
    service = ForecastService(migrated_engine, storage, WORKSPACE_ID)
    created = service.create(
        seeded.dataset_version_id,
        _request(),
        idempotency_key="forecast-run-race-001",
    )
    first_selection = tuple(item.sku_id for item in created.analogs[:2])
    second_selection = tuple(item.sku_id for item in created.analogs[2:4])
    service.confirm_analogs(created.id, first_selection)
    entered = Event()
    release = Event()
    from src.services import forecast_service as service_module

    original = service_module.forecast_new_product

    def paused_forecast(request, analogs):
        entered.set()
        assert release.wait(timeout=5)
        return original(request, analogs)

    monkeypatch.setattr(service_module, "forecast_new_product", paused_forecast)
    with ThreadPoolExecutor(max_workers=2) as executor:
        running = executor.submit(service.run, created.id)
        assert entered.wait(timeout=5)
        confirming = executor.submit(
            service.confirm_analogs,
            created.id,
            second_selection,
        )
        release.set()
        completed = running.result(timeout=10)
        with pytest.raises(ForecastInvalid, match="forecast_terminal"):
            confirming.result(timeout=10)

    persisted_ids = tuple(
        item.sku_id for item in completed.analogs if item.confirmed
    )
    assert persisted_ids == first_selection
    assert completed.result["evidence"]["analog_sku_ids"] == sorted(persisted_ids)
    assert service.get(created.id) == completed


def test_backtest_and_reconfirmation_share_one_authoritative_analog_revision(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = MemoryWorkflowStorage()
    seeded = _seed(migrated_engine, storage)
    service = ForecastService(migrated_engine, storage, WORKSPACE_ID)
    created = service.create(
        seeded.dataset_version_id,
        _request(),
        idempotency_key="forecast-backtest-race-001",
    )
    first_selection = tuple(item.sku_id for item in created.analogs[:2])
    second_selection = tuple(item.sku_id for item in created.analogs[2:4])
    service.confirm_analogs(created.id, first_selection)
    entered = Event()
    release = Event()
    original = service._build_backtest

    def paused_backtest(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_build_backtest", paused_backtest)
    with ThreadPoolExecutor(max_workers=2) as executor:
        testing = executor.submit(service.backtest, created.id)
        assert entered.wait(timeout=5)
        confirming = executor.submit(
            service.confirm_analogs,
            created.id,
            second_selection,
        )
        release.set()
        result = testing.result(timeout=10)
        confirmed_after_test = confirming.result(timeout=10)

    assert result["evidence"]["window_ids"] == ["SYNTH-HIDDEN-LAUNCH-001"]
    persisted_ids = tuple(
        item.sku_id for item in confirmed_after_test.analogs if item.confirmed
    )
    assert persisted_ids == second_selection
