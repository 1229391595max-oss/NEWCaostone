"""Version-bound deterministic new-product forecast orchestration."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid5

from sqlalchemy import Connection, Engine

from src.db.unit_of_work import PostgresUnitOfWork
from src.forecast.analogs import select_analogs
from src.forecast.backtest import backtest_hidden_windows
from src.forecast.contracts import (
    Analog,
    BacktestWindow,
    ForecastRequest,
    ForecastResult,
    HistoricalSku,
    ProductCandidate,
)
from src.forecast.new_product import ALGORITHM_VERSION, ForecastBlocked, forecast_new_product
from src.repositories.datasets import DatasetRepository
from src.repositories.forecasts import ForecastProjection, ForecastRepository
from src.repositories.storage_objects import StorageObjectRepository
from src.services.store_scope import StoreScopeError, StoreScopeResolver
from src.storage.protocol import WorkflowStorage
from src.synthetic.boundary import (
    SyntheticSourceBoundaryError,
    validate_synthetic_records,
)

MAX_BUNDLE_BYTES = 16 * 1024 * 1024
FORECAST_IDEMPOTENCY_NAMESPACE = UUID("c697959e-a384-5e87-92ec-a3ca3567ec43")
IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9._:-]{8,128}")


class ForecastNotFound(LookupError):
    code = "FORECAST_NOT_FOUND"


class ForecastInvalid(ValueError):
    code = "FORECAST_INVALID"

    def __init__(self, code: str = "FORECAST_INVALID") -> None:
        super().__init__(code.lower())
        self.code = code.upper()


class ForecastService:
    def __init__(
        self,
        engine: Engine,
        storage: WorkflowStorage,
        workspace_id: str,
        *,
        clock=None,
        store_scope_resolver=None,
    ) -> None:
        self._engine = engine
        self._storage = storage
        self._workspace_id = workspace_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._store_scopes = store_scope_resolver or StoreScopeResolver(
            engine,
            storage,
            workspace_id,
        )

    def create(
        self,
        dataset_version_id: UUID,
        request: ForecastRequest,
        *,
        scope: Mapping[str, object] | None = None,
        idempotency_key: str,
    ) -> ForecastProjection:
        _validate_candidate(request)
        if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise ForecastInvalid("FORECAST_IDEMPOTENCY_KEY_INVALID")
        normalized_scope = self._scope(dataset_version_id, scope)
        input_snapshot = _request_payload(request, normalized_scope)
        input_hash = _digest(input_snapshot)
        key_hash = sha256(idempotency_key.encode()).hexdigest()
        forecast_id = uuid5(
            FORECAST_IDEMPOTENCY_NAMESPACE,
            f"{self._workspace_id}:{key_hash}",
        )
        existing = self._get_optional(forecast_id)
        if existing is not None:
            return _idempotent_create_authority(
                existing,
                dataset_version_id,
                input_hash,
            )
        tables = self._load_tables(dataset_version_id)
        catalog = _historical_catalog(tables, request.candidate.planned_launch_date)
        analogs = select_analogs(request.candidate, catalog)
        if not analogs:
            raise ForecastInvalid("FORECAST_ANALOGS_UNAVAILABLE")
        timestamp = self._clock()
        try:
            with PostgresUnitOfWork(self._engine) as uow:
                repository = ForecastRepository(uow.connection)
                repository.lock_entry(self._workspace_id, forecast_id)
                existing = repository.get(self._workspace_id, forecast_id)
                if existing is not None:
                    return _idempotent_create_authority(
                        existing,
                        dataset_version_id,
                        input_hash,
                    )
                return repository.create_draft(
                    forecast_id=forecast_id,
                    workspace_id=self._workspace_id,
                    dataset_version_id=dataset_version_id,
                    algorithm_version=ALGORITHM_VERSION,
                    input_snapshot=input_snapshot,
                    input_hash=input_hash,
                    assumptions=list(request.assumptions),
                    analogs=tuple(_analog_payload(item) for item in analogs),
                    now=timestamp,
                )
        except Exception:
            authority = self._get_optional(forecast_id)
            if authority is not None:
                return _idempotent_create_authority(
                    authority,
                    dataset_version_id,
                    input_hash,
                )
            raise

    def confirm_analogs(
        self,
        forecast_id: UUID,
        sku_ids: tuple[str, ...],
    ) -> ForecastProjection:
        normalized = tuple(sorted(set(sku_ids)))
        if not normalized:
            raise ForecastInvalid("FORECAST_ANALOG_SELECTION_INVALID")
        with PostgresUnitOfWork(self._engine) as uow:
            try:
                forecast = ForecastRepository(uow.connection).confirm_analogs(
                    self._workspace_id,
                    forecast_id,
                    normalized,
                    self._clock(),
                )
            except ValueError as error:
                raise ForecastInvalid("FORECAST_ANALOG_SELECTION_INVALID") from error
            if forecast is None:
                raise ForecastNotFound
            if forecast.status in {"completed", "blocked"}:
                raise ForecastInvalid("FORECAST_TERMINAL")
            return forecast

    def run(self, forecast_id: UUID) -> ForecastProjection:
        preview = self.get(forecast_id)
        if preview.status in {"completed", "blocked"}:
            return preview
        if preview.status != "analogs_confirmed":
            raise ForecastBlocked("analogs_not_confirmed")
        tables = self._load_tables(preview.dataset_version_id)
        timestamp = self._clock()
        with PostgresUnitOfWork(self._engine) as uow:
            repository = ForecastRepository(uow.connection)
            current = repository.get(
                self._workspace_id,
                forecast_id,
                for_update=True,
            )
            if current is None:
                raise ForecastNotFound
            if current.status in {"completed", "blocked"}:
                return current
            if current.status != "analogs_confirmed":
                raise ForecastBlocked("analogs_not_confirmed")
            request = _request_from_payload(current.input_snapshot)
            confirmed = tuple(
                _analog_from_projection(item)
                for item in current.analogs
                if item.confirmed
            )
            result = forecast_new_product(request, confirmed)
            backtest = current.backtest or self._build_backtest(tables)
            result_payload = _result_payload(result)
            if result.confidence == "low":
                stored = repository.block(
                    workspace_id=self._workspace_id,
                    forecast_id=forecast_id,
                    result=result_payload,
                    evidence=result_payload["evidence"],
                    backtest=backtest,
                    now=timestamp,
                )
            else:
                stored = repository.complete(
                    workspace_id=self._workspace_id,
                    forecast_id=forecast_id,
                    confidence=result.confidence,
                    evidence=result_payload["evidence"],
                    result=result_payload,
                    backtest=backtest,
                    scenarios=_scenario_rows(result),
                    now=timestamp,
                )
            if stored is None:
                raise ForecastNotFound
            return stored

    def get(self, forecast_id: UUID) -> ForecastProjection:
        forecast = self._get_optional(forecast_id)
        if forecast is None:
            raise ForecastNotFound
        return forecast

    def _get_optional(self, forecast_id: UUID) -> ForecastProjection | None:
        with self._engine.connect() as connection:
            forecast = ForecastRepository(connection).get(
                self._workspace_id,
                forecast_id,
            )
        return forecast

    def latest_completed(
        self,
        dataset_version_id: UUID,
        scope: Mapping[str, object] | None = None,
    ) -> ForecastProjection:
        normalized_scope = self._scope(dataset_version_id, scope)
        with self._engine.connect() as connection:
            forecast = ForecastRepository(connection).latest_completed(
                self._workspace_id,
                dataset_version_id,
                normalized_scope,
            )
        if forecast is None:
            raise ForecastNotFound
        return forecast

    def read_completed(
        self,
        connection: Connection,
        dataset_version_id: UUID,
        forecast_id: UUID | None = None,
        scope: Mapping[str, object] | None = None,
    ) -> ForecastProjection:
        """Read a completed forecast through the caller's controlled transaction."""

        normalized_scope = self._scope(dataset_version_id, scope)
        repository = ForecastRepository(connection)
        forecast = (
            repository.get(self._workspace_id, forecast_id)
            if forecast_id is not None
            else repository.latest_completed(
                self._workspace_id,
                dataset_version_id,
                normalized_scope,
            )
        )
        if (
            forecast is None
            or forecast.dataset_version_id != dataset_version_id
            or forecast.algorithm_version != ALGORITHM_VERSION
            or forecast.status != "completed"
            or forecast.input_snapshot.get("scope") != normalized_scope
        ):
            raise ForecastNotFound
        return forecast

    def completed_id_for_session(
        self,
        dataset_version_id: UUID,
        scope: Mapping[str, object] | None = None,
    ) -> UUID | None:
        try:
            return self.latest_completed(dataset_version_id, scope).id
        except ForecastNotFound:
            return None

    def get_completed_for_session(
        self,
        dataset_version_id: UUID,
        forecast_id: UUID,
        scope: Mapping[str, object] | None = None,
    ) -> ForecastProjection:
        normalized_scope = self._scope(dataset_version_id, scope)
        forecast = self.get(forecast_id)
        if (
            forecast.dataset_version_id != dataset_version_id
            or forecast.algorithm_version != ALGORITHM_VERSION
            or forecast.status != "completed"
            or forecast.input_snapshot.get("scope") != normalized_scope
        ):
            raise ForecastNotFound
        return forecast

    def latest(
        self,
        dataset_version_id: UUID,
        scope: Mapping[str, object] | None = None,
    ) -> ForecastProjection:
        normalized_scope = self._scope(dataset_version_id, scope)
        with self._engine.connect() as connection:
            forecast = ForecastRepository(connection).latest(
                self._workspace_id,
                dataset_version_id,
                normalized_scope,
            )
        if forecast is None:
            raise ForecastNotFound
        return forecast

    def _scope(
        self,
        dataset_version_id: UUID,
        value: Mapping[str, object] | None,
    ) -> dict[str, object]:
        if value is None:
            value = {"currency": "BRL"}
        if not isinstance(value, Mapping) or not set(value) <= {
            "currency",
            "store_id",
        }:
            raise ForecastInvalid("FORECAST_SCOPE_INVALID")
        if value.get("currency") != "BRL":
            raise ForecastInvalid("FORECAST_SCOPE_INVALID")
        store_id = value.get("store_id")
        requested = None if store_id is None else (store_id,)
        try:
            resolved = self._store_scopes.resolve(dataset_version_id, requested)
        except StoreScopeError as error:
            raise ForecastInvalid("FORECAST_SCOPE_INVALID") from error
        return {
            "currency": "BRL",
            **(
                {"store_id": resolved.store_ids[0]}
                if resolved.kind == "single"
                else {}
            ),
        }

    def backtest(self, forecast_id: UUID) -> dict[str, object]:
        preview = self.get(forecast_id)
        if preview.backtest is not None:
            return preview.backtest
        if preview.status != "analogs_confirmed":
            raise ForecastBlocked("analogs_not_confirmed")
        tables = self._load_tables(preview.dataset_version_id)
        with PostgresUnitOfWork(self._engine) as uow:
            repository = ForecastRepository(uow.connection)
            current = repository.get(
                self._workspace_id,
                forecast_id,
                for_update=True,
            )
            if current is None:
                raise ForecastNotFound
            if current.backtest is not None:
                return current.backtest
            if current.status != "analogs_confirmed":
                raise ForecastBlocked("analogs_not_confirmed")
            result = self._build_backtest(tables)
            stored = repository.set_backtest(
                self._workspace_id,
                forecast_id,
                result,
                self._clock(),
            )
            if stored is None:
                raise ForecastNotFound
            return stored.backtest or result

    def _build_backtest(
        self,
        tables: dict[str, tuple[dict[str, object], ...]],
    ) -> dict[str, object]:
        windows = tuple(
            _backtest_window(row)
            for row in tables.get("new_product_backtest_window", ())
        )
        if not windows:
            raise ForecastInvalid("FORECAST_BACKTEST_BENCHMARK_MISSING")
        evaluated = _json_safe(asdict(backtest_hidden_windows(windows)))
        evaluated["evidence"].update(
            {
                "evaluation_scope": "algorithm_hidden_window_not_candidate_actual",
                "window_ids": sorted(window.window_id for window in windows),
            }
        )
        return evaluated

    def _load_tables(
        self,
        dataset_version_id: UUID,
    ) -> dict[str, tuple[dict[str, object], ...]]:
        with self._engine.connect() as connection:
            datasets = DatasetRepository(connection)
            version = datasets.get_version(dataset_version_id)
            artifacts = datasets.list_artifacts(dataset_version_id)
            selected = [item for item in artifacts if item.artifact_kind == "analysis_bundle"]
            if (
                version is None
                or version.workspace_id != self._workspace_id
                or version.status != "complete"
                or version.schema_version != "synthetic.v1"
                or len(selected) != 1
            ):
                raise ForecastInvalid("FORECAST_DATASET_INVALID")
            artifact = selected[0]
            storage = StorageObjectRepository(connection).get(artifact.storage_object_id)
        if (
            storage is None
            or storage.workspace_id != self._workspace_id
            or storage.state != "available"
            or storage.purpose != "normalized_dataset"
            or storage.sha256 != artifact.sha256
            or storage.size_bytes > MAX_BUNDLE_BYTES
        ):
            raise ForecastInvalid("FORECAST_DATASET_INVALID")
        try:
            with self._storage.open_verified(
                storage.object_key,
                artifact.sha256,
                storage.size_bytes,
            ) as opened:
                payload = json.load(opened)
        except Exception as error:
            raise ForecastInvalid("FORECAST_DATASET_UNAVAILABLE") from error
        raw_tables = payload.get("tables") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or payload.get(
            "schema_version"
        ) != "canonical.analysis.v1" or not isinstance(
            raw_tables,
            dict,
        ):
            raise ForecastInvalid("FORECAST_DATASET_INVALID")
        tables: dict[str, tuple[dict[str, object], ...]] = {}
        for role, rows in raw_tables.items():
            if (
                not isinstance(role, str)
                or not isinstance(rows, list)
                or not all(
                    isinstance(row, dict)
                    and row.get("source_classification") == "pure_synthetic"
                    for row in rows
                )
            ):
                raise ForecastInvalid("FORECAST_DATASET_INVALID")
            tables[role] = tuple(rows)
        return tables


def _historical_catalog(
    tables: dict[str, tuple[dict[str, object], ...]],
    cutoff: date,
) -> tuple[HistoricalSku, ...]:
    products = tables.get("product_catalog", ())
    sales = tables.get("daily_sales", ())
    advertising = tables.get("shopee_advertising", ())
    catalog: list[HistoricalSku] = []
    for product in products:
        sku_id = str(product.get("sku_id", ""))
        sku_sales = tuple(
            row
            for row in sales
            if row.get("sku_id") == sku_id and _row_date(row) < cutoff
        )
        if not sku_id or not sku_sales:
            continue
        try:
            raw_category = product["category"]
            raw_attributes = product["attributes"]
            if not isinstance(raw_category, str) or not raw_category.strip():
                raise ValueError("product_category_missing")
            if not isinstance(raw_attributes, str):
                raise ValueError("product_attributes_missing")
            category = raw_category.strip()
            attributes = tuple(
                item.strip()
                for item in raw_attributes.split("|")
                if item.strip()
            )
            if not attributes:
                raise ValueError("product_attributes_missing")
            sales_values = tuple(
                (
                    int(row["units"]),
                    Decimal(str(row["gross_sales_brl"])),
                    Decimal(str(row["discount_brl"])),
                )
                for row in sku_sales
            )
            if any(
                units < 0 or gross < 0 or discount < 0 or discount > gross
                for units, gross, discount in sales_values
            ):
                raise ValueError("negative_or_inverted_sales_fact")
            catalog_price = Decimal(str(product["unit_price_brl"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ForecastInvalid("FORECAST_HISTORY_INCOMPLETE") from error
        dates = {_row_date(row) for row in sku_sales}
        span = (max(dates) - min(dates)).days + 1
        unknown: list[str] = []
        history_days = span if len(dates) == span else 0
        if history_days == 0:
            unknown.append("sales_history_gaps")
        total_units = sum(units for units, _gross, _discount in sales_values)
        positive_units = total_units
        if positive_units > 0:
            net_revenue = sum(
                (
                    gross - discount
                    for _units, gross, discount in sales_values
                ),
                Decimal("0"),
            )
            price = net_revenue / Decimal(positive_units)
        else:
            price = catalog_price
            unknown.append("net_price_history_missing")
            history_days = 0
        sku_ads = tuple(
            row
            for row in advertising
            if row.get("sku_id") == sku_id and _row_date(row) < cutoff
        )
        ad_dates = {_row_date(row) for row in sku_ads}
        if not sku_ads or ad_dates != dates or history_days == 0:
            daily_ad = None
            unknown.append("advertising_history_missing_or_incomplete")
        else:
            try:
                ad_values = tuple(
                    Decimal(str(row["spend_brl"])) for row in sku_ads
                )
                if any(value < 0 for value in ad_values):
                    raise ValueError("negative_ad_fact")
            except (KeyError, TypeError, ValueError) as error:
                raise ForecastInvalid("FORECAST_HISTORY_INCOMPLETE") from error
            daily_ad = sum(ad_values, Decimal("0")) / Decimal(history_days)
        catalog.append(
            HistoricalSku(
                sku_id=sku_id,
                category=category,
                attributes=attributes,
                net_price_brl=price,
                daily_ad_spend_brl=daily_ad,
                history_days=history_days,
                total_units=total_units,
                unit_cost_brl=(
                    Decimal(str(product["unit_cost_brl"]))
                    if product.get("unit_cost_brl") not in (None, "")
                    else None
                ),
                unknown_evidence=tuple(sorted(set(unknown))),
            )
        )
    return tuple(sorted(catalog, key=lambda item: item.sku_id))


def _backtest_window(row: dict[str, object]) -> BacktestWindow:
    try:
        window_id = str(row["window_id"])
        candidate_payload = row["candidate"]
        analog_payloads = row["analogs"]
        actual_daily = row["actual_daily_units"]
        if (
            not window_id.startswith("SYNTH-")
            or not isinstance(candidate_payload, dict)
            or not isinstance(analog_payloads, list)
            or not isinstance(actual_daily, list)
        ):
            raise ValueError("backtest_shape_invalid")
        candidate = ProductCandidate(
            product_name=str(candidate_payload["product_name"]),
            category=str(candidate_payload["category"]),
            attributes=tuple(str(item) for item in candidate_payload["attributes"]),
            planned_launch_date=date.fromisoformat(
                str(candidate_payload["planned_launch_date"])
            ),
            planned_price_brl=Decimal(str(candidate_payload["planned_price_brl"])),
            expected_discount_brl=Decimal(
                str(candidate_payload["expected_discount_brl"])
            ),
            unit_cost_brl=Decimal(str(candidate_payload["unit_cost_brl"])),
            opening_inventory_units=int(candidate_payload["opening_inventory_units"]),
            moq_units=int(candidate_payload["moq_units"]),
            lead_time_days=int(candidate_payload["lead_time_days"]),
            planned_daily_ad_brl=Decimal(
                str(candidate_payload["planned_daily_ad_brl"])
            ),
        )
        request = ForecastRequest(
            candidate=candidate,
            safety_stock_units=int(row["safety_stock_units"]),
            assumptions=("synthetic_hidden_history_cutoff",),
            missing_fields=(),
        )
        _validate_candidate(request)
        cutoff = date.fromisoformat(str(row["training_cutoff"]))
        actual_start = date.fromisoformat(str(row["actual_start"]))
        actual_end = date.fromisoformat(str(row["actual_end"]))
        if (
            cutoff >= candidate.planned_launch_date
            or actual_start != candidate.planned_launch_date
        ):
            raise ValueError("backtest_cutoff_invalid")
        expected_end = actual_start.fromordinal(actual_start.toordinal() + 89)
        if actual_end != expected_end or len(actual_daily) != 90:
            raise ValueError("backtest_actual_window_invalid")
        actual_values = tuple(int(value) for value in actual_daily)
        if any(isinstance(value, bool) for value in actual_daily) or any(
            value < 0 for value in actual_values
        ):
            raise ValueError("backtest_actual_invalid")
        catalog: list[HistoricalSku] = []
        for payload in analog_payloads:
            if not isinstance(payload, dict):
                raise ValueError("backtest_analog_invalid")
            history_start = date.fromisoformat(str(payload["history_start"]))
            history_end = date.fromisoformat(str(payload["history_end"]))
            history_days = int(payload["history_days"])
            if (
                history_end > cutoff
                or history_end >= candidate.planned_launch_date
                or (history_end - history_start).days + 1 != history_days
            ):
                raise ValueError("backtest_history_leakage")
            catalog.append(
                HistoricalSku(
                    sku_id=str(payload["sku_id"]),
                    category=str(payload["category"]),
                    attributes=tuple(str(item) for item in payload["attributes"]),
                    net_price_brl=Decimal(str(payload["net_price_brl"])),
                    daily_ad_spend_brl=Decimal(
                        str(payload["daily_ad_spend_brl"])
                    ),
                    history_days=history_days,
                    total_units=int(payload["total_units"]),
                    unit_cost_brl=Decimal(str(payload["unit_cost_brl"])),
                    unknown_evidence=tuple(
                        str(item) for item in payload["unknown_evidence"]
                    ),
                )
            )
        analogs = select_analogs(candidate, catalog)
        if len(analogs) < 2:
            raise ValueError("backtest_analogs_insufficient")
        actual = {
            horizon: sum(actual_values[:horizon])
            for horizon in (7, 30, 90)
        }
    except ForecastInvalid:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise ForecastInvalid("FORECAST_BACKTEST_BENCHMARK_INVALID") from error
    return BacktestWindow(
        window_id=window_id,
        request=request,
        confirmed_analogs=analogs,
        actual_units=actual,
    )


def _row_date(row: dict[str, object]) -> date:
    try:
        return date.fromisoformat(str(row["date"]))
    except (KeyError, ValueError) as error:
        raise ForecastInvalid("FORECAST_HISTORY_DATE_INVALID") from error


def _request_payload(
    request: ForecastRequest,
    scope: Mapping[str, object],
) -> dict[str, object]:
    return {
        "scope": dict(scope),
        "candidate": {
            "product_name": request.candidate.product_name,
            "category": request.candidate.category,
            "attributes": list(request.candidate.attributes),
            "planned_launch_date": request.candidate.planned_launch_date.isoformat(),
            "planned_price_brl": str(request.candidate.planned_price_brl),
            "expected_discount_brl": str(request.candidate.expected_discount_brl),
            "unit_cost_brl": (
                str(request.candidate.unit_cost_brl)
                if request.candidate.unit_cost_brl is not None
                else None
            ),
            "opening_inventory_units": request.candidate.opening_inventory_units,
            "moq_units": request.candidate.moq_units,
            "lead_time_days": request.candidate.lead_time_days,
            "planned_daily_ad_brl": str(request.candidate.planned_daily_ad_brl),
        },
        "safety_stock_units": request.safety_stock_units,
        "assumptions": sorted(set(request.assumptions)),
        "missing_fields": sorted(set(request.missing_fields)),
    }


def _request_from_payload(payload: dict[str, object]) -> ForecastRequest:
    candidate = payload["candidate"]
    if not isinstance(candidate, dict):
        raise ForecastInvalid("FORECAST_INPUT_INVALID")
    return ForecastRequest(
        candidate=ProductCandidate(
            product_name=str(candidate["product_name"]),
            category=str(candidate["category"]),
            attributes=tuple(str(item) for item in candidate["attributes"]),
            planned_launch_date=date.fromisoformat(str(candidate["planned_launch_date"])),
            planned_price_brl=Decimal(str(candidate["planned_price_brl"])),
            expected_discount_brl=Decimal(str(candidate["expected_discount_brl"])),
            unit_cost_brl=(
                Decimal(str(candidate["unit_cost_brl"]))
                if candidate.get("unit_cost_brl") is not None
                else None
            ),
            opening_inventory_units=int(candidate["opening_inventory_units"]),
            moq_units=int(candidate["moq_units"]),
            lead_time_days=int(candidate["lead_time_days"]),
            planned_daily_ad_brl=Decimal(str(candidate["planned_daily_ad_brl"])),
        ),
        safety_stock_units=int(payload["safety_stock_units"]),
        assumptions=tuple(str(item) for item in payload["assumptions"]),
        missing_fields=tuple(str(item) for item in payload["missing_fields"]),
    )


def _analog_payload(analog: Analog) -> dict[str, object]:
    historical = analog.historical
    return {
        "sku_id": analog.sku_id,
        "score": analog.score,
        "components": {key: str(value) for key, value in analog.components.items()},
        "historical_snapshot": {
            "sku_id": historical.sku_id,
            "category": historical.category,
            "attributes": list(historical.attributes),
            "net_price_brl": str(historical.net_price_brl),
            "daily_ad_spend_brl": (
                str(historical.daily_ad_spend_brl)
                if historical.daily_ad_spend_brl is not None
                else None
            ),
            "history_days": historical.history_days,
            "total_units": historical.total_units,
            "unit_cost_brl": (
                str(historical.unit_cost_brl)
                if historical.unit_cost_brl is not None
                else None
            ),
            "unknown_evidence": list(historical.unknown_evidence),
        },
    }


def _analog_from_projection(projection) -> Analog:
    historical = projection.historical_snapshot
    return Analog(
        historical=HistoricalSku(
            sku_id=str(historical["sku_id"]),
            category=str(historical["category"]),
            attributes=tuple(str(item) for item in historical["attributes"]),
            net_price_brl=Decimal(str(historical["net_price_brl"])),
            daily_ad_spend_brl=(
                Decimal(str(historical["daily_ad_spend_brl"]))
                if historical.get("daily_ad_spend_brl") is not None
                else None
            ),
            history_days=int(historical["history_days"]),
            total_units=int(historical["total_units"]),
            unit_cost_brl=(
                Decimal(str(historical["unit_cost_brl"]))
                if historical.get("unit_cost_brl") is not None
                else None
            ),
            unknown_evidence=tuple(
                str(item) for item in historical["unknown_evidence"]
            ),
        ),
        score=Decimal(str(projection.score)),
        components={
            key: Decimal(str(value)) for key, value in projection.components.items()
        },
    )


def _result_payload(result: ForecastResult) -> dict[str, object]:
    return _json_safe(asdict(result))


def _scenario_rows(result: ForecastResult) -> tuple[dict[str, object], ...]:
    rows = []
    for horizon, projection in sorted(result.by_horizon.items()):
        for scenario in ("low", "base", "high"):
            rows.append(
                {
                    "horizon_days": horizon,
                    "scenario": scenario,
                    "units": projection.units[scenario],
                    "revenue_brl": projection.revenue_brl[scenario],
                    "contribution_profit_brl": projection.contribution_profit_brl[
                        scenario
                    ],
                    "stock_cover_days": projection.stock_cover_days[scenario],
                }
            )
    return tuple(rows)


def _json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return sha256(encoded).hexdigest()


def _validate_candidate(request: ForecastRequest) -> None:
    candidate = request.candidate
    try:
        validate_synthetic_records(
            (
                {
                    "product_name": candidate.product_name,
                    "category": candidate.category,
                    **{
                        f"attribute_{index}": value
                        for index, value in enumerate(candidate.attributes, start=1)
                    },
                    **{
                        f"assumption_{index}": value
                        for index, value in enumerate(request.assumptions, start=1)
                    },
                    **{
                        f"missing_field_{index}": value
                        for index, value in enumerate(request.missing_fields, start=1)
                    },
                },
            )
        )
    except SyntheticSourceBoundaryError as error:
        raise ForecastInvalid("FORECAST_SOURCE_BOUNDARY_FAILED") from error
    if (
        not candidate.product_name.strip()
        or not candidate.product_name.startswith("Synthetic ")
        or not candidate.category.strip()
        or not candidate.attributes
        or not re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", candidate.category)
        or any(
            not re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", value)
            for value in (
                *candidate.attributes,
                *request.assumptions,
                *request.missing_fields,
            )
        )
        or candidate.planned_price_brl <= 0
        or candidate.expected_discount_brl < 0
        or candidate.planned_net_price_brl <= 0
        or (candidate.unit_cost_brl is not None and candidate.unit_cost_brl <= 0)
        or candidate.opening_inventory_units < 0
        or candidate.moq_units <= 0
        or candidate.lead_time_days <= 0
        or candidate.planned_daily_ad_brl < 0
        or request.safety_stock_units < 0
    ):
        raise ForecastInvalid("FORECAST_INPUT_INVALID")


def _idempotent_create_authority(
    forecast: ForecastProjection,
    dataset_version_id: UUID,
    input_hash: str,
) -> ForecastProjection:
    if (
        forecast.dataset_version_id != dataset_version_id
        or forecast.algorithm_version != ALGORITHM_VERSION
        or forecast.input_hash != input_hash
    ):
        raise ForecastInvalid("FORECAST_IDEMPOTENCY_CONFLICT")
    return forecast
