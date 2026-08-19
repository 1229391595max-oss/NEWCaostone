"""Exact-version deterministic calculation preparation for operators."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import Engine

from src.repositories.datasets import DatasetRepository
from src.services.public_release_service import (
    PUBLIC_ANALYSIS_SCOPE,
)

DOMAIN_ORDER = ("sales_ads", "inventory", "profit", "forecast", "actions")
ANALYSES_BY_DOMAIN = {
    "sales_ads": ("sales_ads",),
    "inventory": ("inventory_risk", "fifo_cost_aging", "replenishment"),
    "profit": ("operating_profit",),
}


class DatasetPreparationError(RuntimeError):
    code = "DATASET_PREPARATION_ERROR"


class DatasetPreparationNotFound(DatasetPreparationError):
    code = "DATASET_VERSION_NOT_FOUND"


@dataclass(frozen=True, slots=True)
class PreparationDomain:
    name: str
    status: str
    limitation_code: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetPreparationResult:
    dataset_version_id: UUID
    status: str
    domains: tuple[PreparationDomain, ...]


class DatasetPreparationService:
    """Run only missing/stale immutable calculations for one dataset version."""

    def __init__(
        self,
        engine: Engine,
        workspace_id: str,
        *,
        analysis_service,
        profit_bridge_service=None,
        forecast_service=None,
        action_authority=None,
    ) -> None:
        self._engine = engine
        self._workspace_id = workspace_id
        self._analyses = analysis_service
        self._bridges = profit_bridge_service
        self._forecasts = forecast_service
        self._actions = action_authority

    def prepare(self, dataset_version_id: UUID) -> DatasetPreparationResult:
        self._require_version(dataset_version_id)
        try:
            scopes = self._scopes(dataset_version_id)
        except Exception as error:
            return self._scope_failure(dataset_version_id, error)
        domains = tuple(
            self._for_scopes(
                name,
                tuple(
                    self._run_domain(name, dataset_version_id, scope)
                    for scope in scopes
                ),
            )
            for name in DOMAIN_ORDER
        )
        return self._result(dataset_version_id, domains)

    def readiness(self, dataset_version_id: UUID) -> DatasetPreparationResult:
        self._require_version(dataset_version_id)
        try:
            scopes = self._scopes(dataset_version_id)
        except Exception as error:
            return self._scope_failure(dataset_version_id, error)
        domains = tuple(
            self._for_scopes(
                name,
                tuple(
                    self._read_domain(name, dataset_version_id, scope)
                    for scope in scopes
                ),
            )
            for name in DOMAIN_ORDER
        )
        return self._result(dataset_version_id, domains)

    def _require_version(self, version_id: UUID) -> None:
        with self._engine.connect() as connection:
            version = DatasetRepository(connection).get_version(version_id)
        if (
            version is None
            or version.workspace_id != self._workspace_id
            or version.status != "complete"
        ):
            raise DatasetPreparationNotFound

    def _run_domain(
        self,
        name: str,
        version_id: UUID,
        scope: dict[str, object],
    ) -> PreparationDomain:
        try:
            for kind in ANALYSES_BY_DOMAIN.get(name, ()):
                self._ensure_analysis(kind, version_id, scope)
            if name == "profit":
                self._ensure_bridge(version_id, scope)
            elif name == "forecast":
                self._require_forecast(version_id, scope)
            elif name == "actions":
                self._ensure_actions(version_id, scope)
            return PreparationDomain(name, "ready")
        except Exception as error:
            code = _limitation_code(error)
            status = "unavailable" if name == "forecast" else "failed"
            return PreparationDomain(name, status, code)

    def _read_domain(
        self,
        name: str,
        version_id: UUID,
        scope: dict[str, object],
    ) -> PreparationDomain:
        try:
            for kind in ANALYSES_BY_DOMAIN.get(name, ()):
                self._analyses.get_exact_completed(
                    kind,
                    version_id,
                    scope,
                )
            if name == "profit":
                self._read_bridge(version_id, scope)
            elif name == "forecast":
                self._require_forecast(version_id, scope)
            elif name == "actions":
                if self._actions is None or not self._actions.ready(
                    version_id,
                    _identity_scope(scope),
                ):
                    raise RuntimeError("ACTION_PREPARATION_REQUIRED")
            return PreparationDomain(name, "ready")
        except Exception as error:
            code = _limitation_code(error)
            status = "unavailable" if name == "forecast" else "failed"
            return PreparationDomain(name, status, code)

    def _ensure_analysis(
        self,
        kind: str,
        version_id: UUID,
        scope: dict[str, object],
    ) -> None:
        try:
            self._analyses.get_exact_completed(
                kind,
                version_id,
                scope,
            )
            return
        except Exception:
            pass
        plan = self._analyses.plan(kind, version_id, scope)
        self._analyses.run(
            plan,
            idempotency_key=(
                f"prepare-{version_id}-{kind}-"
                f"{scope.get('store_id', 'all')}"
            ),
        )
        self._analyses.get_exact_completed(
            kind,
            version_id,
            scope,
        )

    def _ensure_bridge(
        self,
        version_id: UUID,
        analysis_scope: dict[str, object],
    ) -> None:
        try:
            self._read_bridge(version_id, analysis_scope)
            return
        except Exception:
            pass
        if self._bridges is None:
            raise RuntimeError("PROFIT_BRIDGE_SERVICE_UNAVAILABLE")
        current_period, comparison_period = _periods(analysis_scope)
        bridge_scope = {
            key: analysis_scope[key]
            for key in ("store_id", "currency")
            if key in analysis_scope
        }
        bridge = self._bridges.run(
            version_id,
            current_period=current_period,
            comparison_period=comparison_period,
            scope=bridge_scope,
        )
        if bridge.dataset_version_id != version_id:
            raise RuntimeError("PROFIT_BRIDGE_VERSION_MISMATCH")
        self._read_bridge(version_id, analysis_scope)

    def _read_bridge(
        self,
        version_id: UUID,
        analysis_scope: dict[str, object],
    ) -> None:
        if self._bridges is None:
            raise RuntimeError("PROFIT_BRIDGE_SERVICE_UNAVAILABLE")
        bridge_id = self._bridges.completed_id_for_session(
            version_id,
            _identity_scope(analysis_scope),
        )
        if bridge_id is None:
            raise RuntimeError("PROFIT_BRIDGE_PREPARATION_REQUIRED")
        bridge = self._bridges.get_for_session(version_id, bridge_id)
        if bridge.dataset_version_id != version_id:
            raise RuntimeError("PROFIT_BRIDGE_VERSION_MISMATCH")

    def _require_forecast(
        self,
        version_id: UUID,
        analysis_scope: dict[str, object],
    ) -> None:
        if self._forecasts is None:
            raise RuntimeError("FORECAST_SERVICE_UNAVAILABLE")
        if self._forecasts.completed_id_for_session(
            version_id,
            _identity_scope(analysis_scope),
        ) is None:
            raise RuntimeError("FORECAST_INPUT_REQUIRED")

    def _ensure_actions(
        self,
        version_id: UUID,
        analysis_scope: dict[str, object],
    ) -> None:
        if self._actions is None:
            raise RuntimeError("ACTION_SERVICE_UNAVAILABLE")
        scope = _identity_scope(analysis_scope)
        if not self._actions.ready(version_id, scope):
            self._actions.ensure(version_id, scope)
        if not self._actions.ready(version_id, scope):
            raise RuntimeError("ACTION_PREPARATION_REQUIRED")

    def _scopes(self, version_id: UUID) -> tuple[dict[str, object], ...]:
        resolver = getattr(self._analyses, "preparation_scopes", None)
        if callable(resolver):
            resolved = tuple(dict(scope) for scope in resolver(version_id))
            if resolved:
                return resolved
        return (dict(PUBLIC_ANALYSIS_SCOPE),)

    @staticmethod
    def _for_scopes(
        name: str,
        results: tuple[PreparationDomain, ...],
    ) -> PreparationDomain:
        if all(item.status == "ready" for item in results):
            return PreparationDomain(name, "ready")
        failure = next(item for item in results if item.status != "ready")
        return PreparationDomain(name, failure.status, failure.limitation_code)

    @staticmethod
    def _scope_failure(
        version_id: UUID,
        error: Exception,
    ) -> DatasetPreparationResult:
        code = _limitation_code(error)
        domains = tuple(
            PreparationDomain(
                name,
                "unavailable" if name == "forecast" else "failed",
                code,
            )
            for name in DOMAIN_ORDER
        )
        return DatasetPreparationResult(version_id, "failed", domains)

    @staticmethod
    def _result(
        version_id: UUID,
        domains: tuple[PreparationDomain, ...],
    ) -> DatasetPreparationResult:
        blocking = tuple(item for item in domains if item.name != "forecast")
        if all(item.status == "ready" for item in blocking):
            status = "ready"
        elif any(item.status == "ready" for item in domains):
            status = "partial"
        else:
            status = "failed"
        return DatasetPreparationResult(version_id, status, domains)


def _limitation_code(error: Exception) -> str:
    value = getattr(error, "code", None) or str(error) or type(error).__name__
    normalized = str(value).strip().upper().replace(" ", "_")
    return normalized[:120] or "CALCULATION_UNAVAILABLE"


def _identity_scope(scope: dict[str, object]) -> dict[str, object]:
    return {
        key: scope[key]
        for key in ("currency", "store_id")
        if key in scope
    }


def _periods(scope: dict[str, object]) -> tuple[tuple[date, date], tuple[date, date]]:
    end = date.fromisoformat(str(scope["period_end"]))
    start = date.fromisoformat(str(scope.get("period_start", end.replace(day=1))))
    baseline_end = start - timedelta(days=1)
    baseline_start = baseline_end.replace(day=1)
    return (start, end), (baseline_start, baseline_end)
