"""Permission-aware workspace preference application service."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Engine

from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.repositories.preferences import PreferencesRepository

DEFAULT_KPIS = [
    "net_sales", "orders", "roas", "ad_spend",
    "contribution_profit", "stockout_skus",
]
DEFAULT_PREFERENCES = {
    "locale": "en",
    "sidebar_mode": "full",
    "default_store": "all",
    "period_preset": "current_month",
    "comparison_preset": "previous_period",
    "overview_kpis": DEFAULT_KPIS,
    "reporting_currency": "BRL",
    "timezone": "America/Sao_Paulo",
}


class PreferenceRevisionConflict(RuntimeError):
    code = "PREFERENCE_REVISION_CONFLICT"


class PreferenceNotFound(RuntimeError):
    code = "PREFERENCE_NOT_FOUND"


class PreferencesService:
    def __init__(self, engine: Engine, workspace_id: str, *, clock=None) -> None:
        self._engine = engine
        self._workspace_id = workspace_id
        self._clock = clock or (lambda: datetime.now(UTC))

    def operator_id(self) -> UUID:
        with self._engine.connect() as connection:
            operator = OperatorRepository(connection).get_active(self._workspace_id)
        if operator is None:
            raise PreferenceNotFound
        return operator.id

    def get_preferences(self, operator_id: UUID) -> dict[str, object]:
        with self._engine.connect() as connection:
            row = PreferencesRepository(connection).get_preferences(
                self._workspace_id, operator_id,
            )
        if row is None:
            return {**DEFAULT_PREFERENCES, "overview_kpis": list(DEFAULT_KPIS), "revision": 0}
        return self._preference_projection(row)

    def save_preferences(
        self,
        operator_id: UUID,
        *,
        expected_revision: int,
        document: dict[str, object],
    ) -> dict[str, object]:
        values = {key: document[key] for key in DEFAULT_PREFERENCES}
        values["overview_kpis"] = list(values["overview_kpis"])
        now = self._clock()
        with PostgresUnitOfWork(self._engine) as uow:
            repository = PreferencesRepository(uow.connection)
            current = repository.get_preferences(self._workspace_id, operator_id)
            if current is None:
                if expected_revision != 0:
                    raise PreferenceRevisionConflict
                row = repository.insert_preferences(
                    {
                        "id": uuid4(),
                        "workspace_id": self._workspace_id,
                        "operator_id": operator_id,
                        **values,
                        "revision": 1,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
            else:
                row = repository.update_preferences(
                    self._workspace_id,
                    operator_id,
                    expected_revision,
                    {**values, "updated_at": now},
                )
                if row is None:
                    raise PreferenceRevisionConflict
        return self._preference_projection(row)

    def list_saved_views(self, operator_id: UUID):
        with self._engine.connect() as connection:
            rows = PreferencesRepository(connection).list_saved_views(
                self._workspace_id, operator_id,
            )
        return tuple(self._saved_view_projection(row) for row in rows)

    def create_saved_view(
        self,
        operator_id: UUID,
        *,
        name: str,
        kind: str,
        config: dict[str, object],
    ) -> dict[str, object]:
        now = self._clock()
        with PostgresUnitOfWork(self._engine) as uow:
            row = PreferencesRepository(uow.connection).insert_saved_view(
                {
                    "id": uuid4(),
                    "workspace_id": self._workspace_id,
                    "operator_id": operator_id,
                    "name": name,
                    "kind": kind,
                    "config": config,
                    "revision": 1,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        return self._saved_view_projection(row)

    def update_saved_view(
        self,
        operator_id: UUID,
        view_id: UUID,
        *,
        expected_revision: int,
        name: str,
        config: dict[str, object],
    ) -> dict[str, object]:
        with PostgresUnitOfWork(self._engine) as uow:
            row = PreferencesRepository(uow.connection).update_saved_view(
                self._workspace_id,
                operator_id,
                view_id,
                expected_revision,
                {"name": name, "config": config, "updated_at": self._clock()},
            )
            if row is None:
                raise PreferenceRevisionConflict
        return self._saved_view_projection(row)

    def delete_saved_view(
        self, operator_id: UUID, view_id: UUID, *, expected_revision: int,
    ) -> None:
        with PostgresUnitOfWork(self._engine) as uow:
            deleted = PreferencesRepository(uow.connection).delete_saved_view(
                self._workspace_id, operator_id, view_id, expected_revision,
            )
            if not deleted:
                raise PreferenceRevisionConflict

    def list_targets(self, operator_id: UUID):
        with self._engine.connect() as connection:
            rows = PreferencesRepository(connection).list_targets(
                self._workspace_id, operator_id,
            )
        return tuple(self._target_projection(row) for row in rows)

    def create_target(
        self,
        operator_id: UUID,
        *,
        period: str,
        revenue_brl: Decimal | str,
        orders: int,
        roas: Decimal | str,
        profit_brl: Decimal | str,
    ) -> dict[str, object]:
        now = self._clock()
        with PostgresUnitOfWork(self._engine) as uow:
            row = PreferencesRepository(uow.connection).insert_target(
                {
                    "id": uuid4(),
                    "workspace_id": self._workspace_id,
                    "operator_id": operator_id,
                    "period": period,
                    "revenue_brl": Decimal(revenue_brl),
                    "orders": orders,
                    "roas": Decimal(roas),
                    "profit_brl": Decimal(profit_brl),
                    "status": "active",
                    "revision": 1,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        return self._target_projection(row)

    def set_target_status(
        self,
        operator_id: UUID,
        target_id: UUID,
        *,
        expected_revision: int,
        status: str,
    ) -> dict[str, object]:
        with PostgresUnitOfWork(self._engine) as uow:
            row = PreferencesRepository(uow.connection).update_target(
                self._workspace_id,
                operator_id,
                target_id,
                expected_revision,
                {"status": status, "updated_at": self._clock()},
            )
            if row is None:
                raise PreferenceRevisionConflict
        return self._target_projection(row)

    @staticmethod
    def _preference_projection(row: dict[str, object]) -> dict[str, object]:
        return {
            key: list(row[key]) if key == "overview_kpis" else row[key]
            for key in (*DEFAULT_PREFERENCES, "revision")
        }

    @staticmethod
    def _saved_view_projection(row: dict[str, object]) -> dict[str, object]:
        return {
            key: row[key]
            for key in ("id", "name", "kind", "config", "revision", "updated_at")
        }

    @staticmethod
    def _target_projection(row: dict[str, object]) -> dict[str, object]:
        return {
            key: row[key]
            for key in (
                "id", "period", "revenue_brl", "orders", "roas",
                "profit_brl", "status", "revision", "updated_at",
            )
        }
