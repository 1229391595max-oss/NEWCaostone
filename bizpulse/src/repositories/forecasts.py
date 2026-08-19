"""PostgreSQL authority for deterministic new-product forecasts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Connection, select, text, update

from src.db.schema import (
    forecast_analogs,
    forecast_scenarios,
    new_product_forecasts,
)


@dataclass(frozen=True, slots=True)
class ForecastAnalogProjection:
    id: UUID
    forecast_id: UUID
    sku_id: str
    rank: int
    score: Decimal
    components: dict[str, str]
    historical_snapshot: dict[str, object]
    confirmed: bool
    confirmed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ForecastProjection:
    id: UUID
    workspace_id: str
    dataset_version_id: UUID
    algorithm_version: str
    input_snapshot: dict[str, object]
    input_hash: str
    status: str
    confidence: str | None
    assumptions: list[str]
    evidence: dict[str, object]
    result: dict[str, object] | None
    backtest: dict[str, object] | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    analogs: tuple[ForecastAnalogProjection, ...]


class ForecastRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def lock_entry(self, workspace_id: str, forecast_id: UUID) -> None:
        self._connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:entry, 0))"),
            {"entry": f"forecast:{workspace_id}:{forecast_id}"},
        )

    def get(
        self,
        workspace_id: str,
        forecast_id: UUID,
        *,
        for_update: bool = False,
    ) -> ForecastProjection | None:
        statement = select(*new_product_forecasts.c).where(
                new_product_forecasts.c.workspace_id == workspace_id,
                new_product_forecasts.c.id == forecast_id,
        )
        if for_update:
            statement = statement.with_for_update()
        row = self._connection.execute(statement).mappings().one_or_none()
        if row is None:
            return None
        return self._projection(row)

    def latest_completed(
        self,
        workspace_id: str,
        dataset_version_id: UUID,
        scope: dict[str, object],
    ) -> ForecastProjection | None:
        row = self._connection.execute(
            select(*new_product_forecasts.c)
            .where(
                new_product_forecasts.c.workspace_id == workspace_id,
                new_product_forecasts.c.dataset_version_id == dataset_version_id,
                new_product_forecasts.c.status == "completed",
                new_product_forecasts.c.input_snapshot["scope"] == scope,
            )
            .order_by(
                new_product_forecasts.c.completed_at.desc(),
                new_product_forecasts.c.id.desc(),
            )
            .limit(1)
        ).mappings().one_or_none()
        return self._projection(row) if row is not None else None

    def latest(
        self,
        workspace_id: str,
        dataset_version_id: UUID,
        scope: dict[str, object],
    ) -> ForecastProjection | None:
        row = self._connection.execute(
            select(*new_product_forecasts.c)
            .where(
                new_product_forecasts.c.workspace_id == workspace_id,
                new_product_forecasts.c.dataset_version_id == dataset_version_id,
                new_product_forecasts.c.input_snapshot["scope"] == scope,
            )
            .order_by(
                new_product_forecasts.c.created_at.desc(),
                new_product_forecasts.c.id.desc(),
            )
            .limit(1)
        ).mappings().one_or_none()
        return self._projection(row) if row is not None else None

    def create_draft(
        self,
        *,
        forecast_id: UUID,
        workspace_id: str,
        dataset_version_id: UUID,
        algorithm_version: str,
        input_snapshot: dict[str, object],
        input_hash: str,
        assumptions: list[str],
        analogs: tuple[dict[str, object], ...],
        now: datetime,
    ) -> ForecastProjection:
        self._connection.execute(
            new_product_forecasts.insert().values(
                id=forecast_id,
                workspace_id=workspace_id,
                dataset_version_id=dataset_version_id,
                algorithm_version=algorithm_version,
                input_snapshot=input_snapshot,
                input_hash=input_hash,
                status="draft",
                confidence=None,
                assumptions=assumptions,
                evidence={
                    "source_classification": "pure_synthetic",
                    "analog_confirmation": "required",
                },
                result=None,
                backtest=None,
                created_at=now,
                updated_at=now,
                completed_at=None,
            )
        )
        for rank, analog in enumerate(analogs, start=1):
            self._connection.execute(
                forecast_analogs.insert().values(
                    id=uuid4(),
                    forecast_id=forecast_id,
                    sku_id=analog["sku_id"],
                    rank=rank,
                    score=analog["score"],
                    components=analog["components"],
                    historical_snapshot=analog["historical_snapshot"],
                    confirmed=False,
                    confirmed_at=None,
                    created_at=now,
                )
            )
        created = self.get(workspace_id, forecast_id)
        if created is None:
            raise RuntimeError("forecast_create_failed")
        return created

    def confirm_analogs(
        self,
        workspace_id: str,
        forecast_id: UUID,
        sku_ids: tuple[str, ...],
        now: datetime,
    ) -> ForecastProjection | None:
        current = self.get(workspace_id, forecast_id, for_update=True)
        if current is None:
            return None
        if current.status not in {"draft", "analogs_confirmed"}:
            return current
        selected = set(sku_ids)
        available = {item.sku_id for item in current.analogs}
        if not selected or not selected <= available:
            raise ValueError("forecast_analog_selection_invalid")
        for analog in current.analogs:
            confirmed = analog.sku_id in selected
            self._connection.execute(
                update(forecast_analogs)
                .where(forecast_analogs.c.id == analog.id)
                .values(
                    confirmed=confirmed,
                    confirmed_at=now if confirmed else None,
                )
            )
        self._connection.execute(
            update(new_product_forecasts)
            .where(new_product_forecasts.c.id == forecast_id)
            .values(status="analogs_confirmed", updated_at=now)
        )
        return self.get(workspace_id, forecast_id)

    def set_backtest(
        self,
        workspace_id: str,
        forecast_id: UUID,
        backtest: dict[str, object],
        now: datetime,
    ) -> ForecastProjection | None:
        current = self.get(workspace_id, forecast_id, for_update=True)
        if current is None or current.status in {"completed", "blocked"}:
            return current
        self._connection.execute(
            update(new_product_forecasts)
            .where(
                new_product_forecasts.c.id == forecast_id,
                new_product_forecasts.c.status == "analogs_confirmed",
            )
            .values(backtest=backtest, updated_at=now)
        )
        return self.get(workspace_id, forecast_id)

    def complete(
        self,
        *,
        workspace_id: str,
        forecast_id: UUID,
        confidence: str,
        evidence: dict[str, object],
        result: dict[str, object],
        backtest: dict[str, object] | None,
        scenarios: tuple[dict[str, object], ...],
        now: datetime,
    ) -> ForecastProjection | None:
        current = self.get(workspace_id, forecast_id, for_update=True)
        if current is None or current.status == "completed":
            return current
        if current.status != "analogs_confirmed":
            return current
        for scenario in scenarios:
            self._connection.execute(
                forecast_scenarios.insert().values(
                    id=uuid4(),
                    forecast_id=forecast_id,
                    created_at=now,
                    **scenario,
                )
            )
        self._connection.execute(
            update(new_product_forecasts)
            .where(
                new_product_forecasts.c.id == forecast_id,
                new_product_forecasts.c.status == "analogs_confirmed",
            )
            .values(
                status="completed",
                confidence=confidence,
                evidence=evidence,
                result=result,
                backtest=backtest,
                updated_at=now,
                completed_at=now,
            )
        )
        return self.get(workspace_id, forecast_id)

    def block(
        self,
        *,
        workspace_id: str,
        forecast_id: UUID,
        result: dict[str, object],
        evidence: dict[str, object],
        backtest: dict[str, object] | None,
        now: datetime,
    ) -> ForecastProjection | None:
        current = self.get(workspace_id, forecast_id, for_update=True)
        if current is None or current.status in {"completed", "blocked"}:
            return current
        self._connection.execute(
            update(new_product_forecasts)
            .where(new_product_forecasts.c.id == forecast_id)
            .values(
                status="blocked",
                confidence="low",
                result=result,
                evidence=evidence,
                backtest=backtest,
                updated_at=now,
                completed_at=now,
            )
        )
        return self.get(workspace_id, forecast_id)

    def _projection(self, row) -> ForecastProjection:
        analog_rows = self._connection.execute(
            select(*forecast_analogs.c)
            .where(forecast_analogs.c.forecast_id == row["id"])
            .order_by(forecast_analogs.c.rank)
        ).mappings()
        analogs = tuple(ForecastAnalogProjection(**item) for item in analog_rows)
        return ForecastProjection(**row, analogs=analogs)
