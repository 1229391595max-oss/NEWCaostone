"""Persist exact deterministic contribution-profit bridges."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid5

from sqlalchemy import Connection, Engine

from src.analysis.evidence import stable_hash
from src.db.unit_of_work import PostgresUnitOfWork
from src.profit.bridge import DRIVER_ORDER, FORMULA_VERSION, build_profit_bridge
from src.profit.contracts import ProfitBridgeItem, ProfitPeriod, ProfitSku
from src.repositories.profit_bridges import (
    ProfitBridgeProjection,
    ProfitBridgeRepository,
)
from src.services.analysis_service import AnalysisNotFound, AnalysisService
from src.services.store_scope import StoreScopeError, StoreScopeResolver
from src.storage.keys import workspace_token
from src.storage.postgres_entry_locks import PostgresEntryLockManager
from src.synthetic.release_profile import PUBLIC_RELEASE_PROFILE

BRIDGE_NAMESPACE = UUID("7de9fe62-e538-47ea-87c0-a8f2d321fb8f")
PUBLIC_BASELINE_PERIOD = PUBLIC_RELEASE_PROFILE.comparison_period
PUBLIC_CURRENT_PERIOD = PUBLIC_RELEASE_PROFILE.current_period
PUBLIC_SCOPE = PUBLIC_RELEASE_PROFILE.scope()


class ProfitBridgeNotFound(RuntimeError):
    code = "PROFIT_BRIDGE_NOT_FOUND"


class ProfitBridgeInvalid(RuntimeError):
    code = "PROFIT_BRIDGE_INVALID"


@dataclass(frozen=True, slots=True)
class StoredProfitBridge:
    id: UUID
    workspace_id: str
    dataset_version_id: UUID
    baseline_analysis_id: UUID
    current_analysis_id: UUID
    formula_version: str
    scope: dict[str, object]
    baseline_period: tuple[date, date]
    current_period: tuple[date, date]
    baseline_contribution_profit_brl: Decimal | None
    current_contribution_profit_brl: Decimal | None
    total_delta_brl: Decimal | None
    residual_brl: Decimal | None
    reconciled: bool
    shared_costs_unallocated: bool
    limitations: tuple[str, ...]
    items: tuple[ProfitBridgeItem, ...]
    created_at: datetime


class ProfitBridgeService:
    def __init__(
        self,
        engine: Engine,
        storage,
        workspace_id: str,
        *,
        analysis_service: AnalysisService | None = None,
        clock=None,
        uow_factory=PostgresUnitOfWork,
    ) -> None:
        self._engine = engine
        self._storage = storage
        self._workspace_id = workspace_id
        self._analyses = analysis_service or AnalysisService(
            engine,
            storage,
            workspace_id,
        )
        self._store_scopes = StoreScopeResolver(engine, storage, workspace_id)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._uow_factory = uow_factory
        self._locks = PostgresEntryLockManager(engine)

    def run(
        self,
        dataset_version_id: UUID,
        current_period: tuple[date, date],
        comparison_period: tuple[date, date],
        scope: Mapping[str, object],
    ) -> StoredProfitBridge:
        if not isinstance(dataset_version_id, UUID):
            raise ProfitBridgeInvalid("dataset_version_invalid")
        normalized_scope = self._scope_for_version(dataset_version_id, scope)
        current_dates = _period(current_period)
        baseline_dates = _period(comparison_period)
        same_duration = (
            (current_dates[1] - current_dates[0]).days
            == (baseline_dates[1] - baseline_dates[0]).days
        )
        complete_months = _is_complete_month(current_dates) and _is_complete_month(
            baseline_dates
        )
        if (
            not same_duration and not complete_months
        ) or baseline_dates[1] >= current_dates[0]:
            raise ProfitBridgeInvalid("profit_bridge_periods_invalid")

        baseline_run, baseline_snapshot, baseline_tables = self._period_authority(
            dataset_version_id,
            baseline_dates,
            normalized_scope,
        )
        current_run, current_snapshot, current_tables = self._period_authority(
            dataset_version_id,
            current_dates,
            normalized_scope,
        )
        baseline = _profit_period(
            baseline_dates,
            baseline_snapshot,
            baseline_tables,
        )
        current = _profit_period(
            current_dates,
            current_snapshot,
            current_tables,
        )
        bridge = build_profit_bridge(current, baseline)
        stored_scope = _stored_scope(
            normalized_scope,
            baseline_dates,
            current_dates,
        )
        bridge_id = uuid5(
            BRIDGE_NAMESPACE,
            f"{self._workspace_id}:{dataset_version_id}:"
            f"{baseline_run.run_id}:{current_run.run_id}:{FORMULA_VERSION}:"
            f"{stable_hash(stored_scope)}",
        )
        lock_key = (
            f"workspaces/{workspace_token(self._workspace_id)}/"
            f"profit-bridges/{bridge_id}"
        )
        with self._locks.acquire((lock_key,)):
            with self._engine.connect() as connection:
                repository = ProfitBridgeRepository(connection)
                existing = repository.find_exact(
                    self._workspace_id,
                    baseline_run.run_id,
                    current_run.run_id,
                    FORMULA_VERSION,
                )
                if existing is not None:
                    return self._stored(repository, existing)
            try:
                with self._uow_factory(self._engine) as uow:
                    projection = ProfitBridgeRepository(uow.connection).insert(
                        bridge_id=bridge_id,
                        workspace_id=self._workspace_id,
                        dataset_version_id=dataset_version_id,
                        baseline_analysis_id=baseline_run.run_id,
                        current_analysis_id=current_run.run_id,
                        scope=stored_scope,
                        bridge=bridge,
                        now=self._clock(),
                    )
            except Exception:
                with self._engine.connect() as connection:
                    repository = ProfitBridgeRepository(connection)
                    committed = repository.find_exact(
                        self._workspace_id,
                        baseline_run.run_id,
                        current_run.run_id,
                        FORMULA_VERSION,
                    )
                    if committed is not None:
                        return self._stored(repository, committed)
                raise
            with self._engine.connect() as connection:
                repository = ProfitBridgeRepository(connection)
                committed = repository.get(self._workspace_id, projection.id)
                if committed is None:
                    raise ProfitBridgeNotFound
                return self._stored(repository, committed)

    def get(self, bridge_id: UUID) -> StoredProfitBridge:
        with self._engine.connect() as connection:
            repository = ProfitBridgeRepository(connection)
            projection = repository.get(self._workspace_id, bridge_id)
            if projection is None:
                raise ProfitBridgeNotFound
            return self._stored(repository, projection)

    def latest(
        self,
        dataset_version_id: UUID,
        scope: Mapping[str, object] | None = None,
    ) -> StoredProfitBridge:
        normalized_scope = self._scope_for_version(
            dataset_version_id,
            scope or {"currency": "BRL"},
        )
        with self._engine.connect() as connection:
            repository = ProfitBridgeRepository(connection)
            projection = repository.find_for_scope(
                self._workspace_id,
                dataset_version_id,
                FORMULA_VERSION,
                _stored_scope(
                    normalized_scope,
                    PUBLIC_BASELINE_PERIOD,
                    PUBLIC_CURRENT_PERIOD,
                ),
            )
            if projection is None:
                raise ProfitBridgeNotFound
            return self._stored(repository, projection)

    def default(
        self,
        dataset_version_id: UUID,
        scope: Mapping[str, object] | None = None,
    ) -> StoredProfitBridge:
        bridge_id = self.completed_id_for_session(dataset_version_id, scope)
        if bridge_id is None:
            raise ProfitBridgeNotFound
        return self.get_for_session(dataset_version_id, bridge_id)

    def completed_id_for_session(
        self,
        dataset_version_id: UUID,
        scope: Mapping[str, object] | None = None,
    ) -> UUID | None:
        normalized_scope = self._scope_for_version(
            dataset_version_id,
            scope or {"currency": "BRL"},
        )
        stored_scope = _stored_scope(
            normalized_scope,
            PUBLIC_BASELINE_PERIOD,
            PUBLIC_CURRENT_PERIOD,
        )
        with self._engine.connect() as connection:
            projection = ProfitBridgeRepository(connection).find_for_scope(
                self._workspace_id,
                dataset_version_id,
                FORMULA_VERSION,
                stored_scope,
            )
        return projection.id if projection is not None else None

    def get_for_session(
        self,
        dataset_version_id: UUID,
        bridge_id: UUID,
    ) -> StoredProfitBridge:
        bridge = self.get(bridge_id)
        if bridge.dataset_version_id != dataset_version_id:
            raise ProfitBridgeNotFound
        return bridge

    def read_for_query(
        self,
        connection: Connection,
        dataset_version_id: UUID,
        bridge_id: UUID | None = None,
        scope: Mapping[str, object] | None = None,
    ) -> StoredProfitBridge:
        """Read an exact bridge through the caller's controlled transaction."""

        repository = ProfitBridgeRepository(connection)
        projection = (
            repository.get(self._workspace_id, bridge_id)
            if bridge_id is not None
            else repository.find_for_scope(
                self._workspace_id,
                dataset_version_id,
                FORMULA_VERSION,
                _stored_scope(
                    self._scope_for_version(
                        dataset_version_id,
                        scope or {"currency": "BRL"},
                    ),
                    PUBLIC_BASELINE_PERIOD,
                    PUBLIC_CURRENT_PERIOD,
                ),
            )
        )
        if (
            projection is None
            or projection.dataset_version_id != dataset_version_id
            or projection.formula_version != FORMULA_VERSION
        ):
            raise ProfitBridgeNotFound
        return self._stored(repository, projection)

    def _scope_for_version(
        self,
        dataset_version_id: UUID,
        value: Mapping[str, object],
    ) -> dict[str, object]:
        normalized = _scope(value)
        store_id = normalized.get("store_id")
        try:
            self._store_scopes.resolve(
                dataset_version_id,
                [str(store_id)] if store_id is not None else None,
            )
        except StoreScopeError as error:
            raise ProfitBridgeInvalid("profit_bridge_scope_invalid") from error
        return normalized

    def _period_authority(
        self,
        dataset_version_id: UUID,
        period: tuple[date, date],
        scope: dict[str, object],
    ):
        analysis_scope = {
            **scope,
            "period_start": period[0].isoformat(),
            "period_end": period[1].isoformat(),
        }
        plan = self._analyses.plan(
            "operating_profit",
            dataset_version_id,
            analysis_scope,
        )
        try:
            run, snapshot, _evidence = self._analyses.get_exact_completed(
                "operating_profit",
                dataset_version_id,
                analysis_scope,
            )
        except AnalysisNotFound:
            self._analyses.run(
                plan,
                idempotency_key=f"profit-bridge-{plan.run_id}",
            )
            run, snapshot, _evidence = self._analyses.get_exact_completed(
                "operating_profit",
                dataset_version_id,
                analysis_scope,
            )
        tables, _limitations = self._analyses.load_scoped_inputs(
            dataset_version_id,
            analysis_scope,
        )
        return run, snapshot, tables

    def _stored(
        self,
        repository: ProfitBridgeRepository,
        projection: ProfitBridgeProjection,
    ) -> StoredProfitBridge:
        rows = repository.items(projection.id)
        if (
            len(rows) != len(DRIVER_ORDER)
            or tuple(row.driver for row in rows) != DRIVER_ORDER
            or tuple(row.ordinal for row in rows)
            != tuple(range(1, len(DRIVER_ORDER) + 1))
        ):
            raise ProfitBridgeNotFound
        evidence = projection.evidence
        try:
            baseline_period = tuple(
                date.fromisoformat(str(value))
                for value in evidence["baseline_period"]
            )
            current_period = tuple(
                date.fromisoformat(str(value))
                for value in evidence["current_period"]
            )
            limitations = tuple(str(value) for value in evidence["limitations"])
            if len(baseline_period) != 2 or len(current_period) != 2:
                raise ValueError("period_shape")
        except (KeyError, TypeError, ValueError) as error:
            raise ProfitBridgeNotFound from error
        return StoredProfitBridge(
            id=projection.id,
            workspace_id=projection.workspace_id,
            dataset_version_id=projection.dataset_version_id,
            baseline_analysis_id=projection.baseline_analysis_id,
            current_analysis_id=projection.current_analysis_id,
            formula_version=projection.formula_version,
            scope=projection.scope,
            baseline_period=(baseline_period[0], baseline_period[1]),
            current_period=(current_period[0], current_period[1]),
            baseline_contribution_profit_brl=_optional_decimal(
                evidence.get("baseline_contribution_profit_brl")
            ),
            current_contribution_profit_brl=_optional_decimal(
                evidence.get("current_contribution_profit_brl")
            ),
            total_delta_brl=projection.total_delta_brl,
            residual_brl=projection.residual_brl,
            reconciled=projection.reconciled,
            shared_costs_unallocated="store_id" in projection.scope,
            limitations=limitations,
            items=tuple(
                ProfitBridgeItem(
                    driver=row.driver,
                    ordinal=row.ordinal,
                    amount_brl=row.amount_brl,
                    evidence_state=row.evidence_state,
                    formula=row.formula,
                    source_refs=tuple(row.source_refs),
                )
                for row in rows
            ),
            created_at=projection.created_at,
        )


def _scope(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or not set(value) <= {
        "store_id",
        "currency",
        "sku_ids",
    }:
        raise ProfitBridgeInvalid("profit_bridge_scope_invalid")
    currency = value.get("currency")
    if currency != "BRL":
        raise ProfitBridgeInvalid("profit_bridge_currency_invalid")
    normalized: dict[str, object] = {"currency": "BRL"}
    store_id = value.get("store_id")
    if store_id is not None:
        if not isinstance(store_id, str) or not store_id.strip():
            raise ProfitBridgeInvalid("profit_bridge_scope_invalid")
        normalized["store_id"] = store_id.strip()
    sku_ids = value.get("sku_ids")
    if sku_ids is not None:
        if not isinstance(sku_ids, (list, tuple)) or not all(
            isinstance(item, str) and item.strip() for item in sku_ids
        ):
            raise ProfitBridgeInvalid("profit_bridge_scope_invalid")
        normalized["sku_ids"] = sorted({item.strip() for item in sku_ids})
        if not normalized["sku_ids"]:
            raise ProfitBridgeInvalid("profit_bridge_scope_invalid")
    return normalized


def _period(value: tuple[date, date]) -> tuple[date, date]:
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or not all(isinstance(item, date) for item in value)
        or value[0] > value[1]
    ):
        raise ProfitBridgeInvalid("profit_bridge_period_invalid")
    return value


def _is_complete_month(value: tuple[date, date]) -> bool:
    start, end = value
    if start.day != 1:
        return False
    next_month = (
        date(start.year + 1, 1, 1)
        if start.month == 12
        else date(start.year, start.month + 1, 1)
    )
    return end == next_month - timedelta(days=1)


def _profit_period(
    period: tuple[date, date],
    snapshot: Mapping[str, object],
    tables: Mapping[str, Sequence[Mapping[str, object]]],
) -> ProfitPeriod:
    result = snapshot.get("result")
    if not isinstance(result, Mapping):
        raise ProfitBridgeInvalid("profit_analysis_snapshot_invalid")
    contribution = result.get("contribution_profit")
    if not isinstance(contribution, Mapping):
        raise ProfitBridgeInvalid("profit_analysis_snapshot_invalid")
    contribution_value = _optional_decimal(contribution.get("value"))
    sales_by_sku: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in tables.get("daily_sales", ()):
        sku_id = row.get("sku_id")
        if not isinstance(sku_id, str) or not sku_id:
            raise ProfitBridgeInvalid("profit_sales_sku_invalid")
        sales_by_sku[sku_id].append(row)
    fifo = _fifo_period_costs(
        tables.get("inventory_receipt_lot", ()),
        tables.get("outbound_event", ()),
        period,
    )
    skus: list[ProfitSku] = []
    for sku_id, rows in sorted(sales_by_sku.items()):
        try:
            quantity = sum((_integer(row["units"], "units") for row in rows), 0)
            gross = sum(
                (_nonnegative(row["gross_sales_brl"], "gross_sales_brl") for row in rows),
                Decimal(0),
            )
            discount = sum(
                (_nonnegative(row["discount_brl"], "discount_brl") for row in rows),
                Decimal(0),
            )
        except KeyError as error:
            raise ProfitBridgeInvalid("profit_sales_fact_missing") from error
        if discount > gross:
            raise ProfitBridgeInvalid("profit_sales_discount_invalid")
        period_cogs = fifo.get(sku_id)
        net_unit = (gross - discount) / Decimal(quantity) if quantity else None
        unit_cogs = (
            period_cogs[1] / Decimal(quantity)
            if quantity
            and period_cogs is not None
            and period_cogs[0] == quantity
            and period_cogs[2]
            else None
        )
        skus.append(ProfitSku(sku_id, quantity, net_unit, unit_cogs))
    return ProfitPeriod(
        period_start=period[0],
        period_end=period[1],
        skus=tuple(skus),
        contribution_profit_brl=contribution_value,
        platform_fee_brl=_sum_rows(tables, "settlement", "fee_brl"),
        advertising_brl=_sum_rows(
            tables,
            "shopee_advertising",
            "spend_brl",
        ),
        refund_loss_brl=_sum_rows(tables, "refund", "refund_brl"),
        fulfillment_brl=_sum_rows(tables, "fulfillment_cost", "cost_brl"),
        tax_brl=_sum_rows(tables, "tax", "tax_brl", optional=True),
        fx_effect_brl=_sum_rows(
            tables,
            "fx_effect",
            "effect_brl",
            signed=True,
        ),
        other_mapped_brl=_sum_rows(
            tables,
            "other_variable_cost",
            "cost_brl",
        ),
    )


def _fifo_period_costs(
    receipt_lots: Sequence[Mapping[str, object]],
    outbound_events: Sequence[Mapping[str, object]],
    period: tuple[date, date],
) -> dict[str, tuple[int, Decimal, bool]]:
    lots_by_sku: dict[str, list[list[object]]] = defaultdict(list)
    for row in receipt_lots:
        try:
            sku_id = str(row["sku_id"])
            receipt_date = date.fromisoformat(str(row["receipt_date"]))
            quantity = _integer(row["quantity_received"], "quantity_received")
            cost = _nonnegative(row["unit_cost_brl"], "unit_cost_brl")
            lot_id = str(row["lot_id"])
        except (KeyError, ValueError) as error:
            raise ProfitBridgeInvalid("profit_fifo_lot_invalid") from error
        lots_by_sku[sku_id].append([receipt_date, lot_id, quantity, cost])
    for lots in lots_by_sku.values():
        lots.sort(key=lambda item: (item[0], item[1]))
    events = sorted(
        outbound_events,
        key=lambda row: (str(row.get("date", "")), str(row.get("outbound_id", ""))),
    )
    results: dict[str, list[object]] = {}
    uncovered_by_sku: set[str] = set()
    for row in events:
        try:
            event_date = date.fromisoformat(str(row["date"]))
            sku_id = str(row["sku_id"])
            remaining = _integer(row["quantity"], "quantity")
        except (KeyError, ValueError) as error:
            raise ProfitBridgeInvalid("profit_fifo_event_invalid") from error
        if event_date > period[1]:
            continue
        event_cost = Decimal(0)
        allocated = 0
        for lot in lots_by_sku.get(sku_id, []):
            if remaining == 0:
                break
            if lot[0] > event_date or lot[2] == 0:
                continue
            quantity = min(remaining, int(lot[2]))
            lot[2] = int(lot[2]) - quantity
            remaining -= quantity
            allocated += quantity
            event_cost += Decimal(quantity) * Decimal(lot[3])
        if remaining:
            uncovered_by_sku.add(sku_id)
        if period[0] <= event_date <= period[1]:
            current = results.setdefault(sku_id, [0, Decimal(0), True])
            current[0] = int(current[0]) + allocated
            current[1] = Decimal(current[1]) + event_cost
            current[2] = bool(current[2]) and remaining == 0
    for sku_id in uncovered_by_sku:
        if sku_id in results:
            results[sku_id][2] = False
    return {
        sku_id: (int(value[0]), Decimal(value[1]), bool(value[2]))
        for sku_id, value in results.items()
    }


def _sum_rows(
    tables: Mapping[str, Sequence[Mapping[str, object]]],
    role: str,
    field: str,
    *,
    optional: bool = False,
    signed: bool = False,
) -> Decimal | None:
    rows = tables.get(role, ())
    if not rows:
        return Decimal(0) if optional else None
    values: list[Decimal] = []
    for row in rows:
        if field not in row or row[field] is None:
            return None
        value = _decimal(row[field], field)
        if not signed and value < 0:
            raise ProfitBridgeInvalid(f"{field}_negative")
        values.append(value)
    return sum(values, Decimal(0))


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, "decimal")


def _nonnegative(value: object, field: str) -> Decimal:
    number = _decimal(value, field)
    if number < 0:
        raise ProfitBridgeInvalid(f"{field}_negative")
    return number


def _decimal(value: object, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except Exception as error:
        raise ProfitBridgeInvalid(f"{field}_invalid") from error
    if not number.is_finite():
        raise ProfitBridgeInvalid(f"{field}_invalid")
    return number


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ProfitBridgeInvalid(f"{field}_invalid")
    try:
        number = int(value)
        exact = Decimal(str(value))
    except Exception as error:
        raise ProfitBridgeInvalid(f"{field}_invalid") from error
    if not exact.is_finite() or number < 0 or exact != Decimal(number):
        raise ProfitBridgeInvalid(f"{field}_invalid")
    return number


def _stored_scope(
    scope: Mapping[str, object],
    baseline_period: tuple[date, date],
    current_period: tuple[date, date],
) -> dict[str, object]:
    return {
        **_scope(scope),
        "comparison_period": [value.isoformat() for value in baseline_period],
        "current_period": [value.isoformat() for value in current_period],
    }
