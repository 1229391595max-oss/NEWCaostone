"""Plan, execute, publish, and verify immutable deterministic analyses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import json
from types import MappingProxyType
from uuid import UUID, uuid4, uuid5

from sqlalchemy import Connection, Engine

from src.analysis.evidence import canonical_json_bytes, canonical_value, stable_hash
from src.analysis.fifo_cost_aging_calculator import (
    ALGORITHM_VERSION as FIFO_VERSION,
    calculate_fifo_cost_aging,
)
from src.analysis.inventory_risk_calculator import (
    ALGORITHM_VERSION as INVENTORY_VERSION,
    calculate_inventory_risk,
)
from src.analysis.operating_profit_calculator import (
    ALGORITHM_VERSION as PROFIT_VERSION,
    calculate_operating_profit,
)
from src.analysis.replenishment_calculator import (
    ALGORITHM_VERSION as REPLENISHMENT_VERSION,
    calculate_replenishment,
)
from src.analysis.sales_ads_calculator import (
    ALGORITHM_VERSION as SALES_ADS_VERSION,
    calculate_sales_ads,
)
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.analyses import (
    ANALYSIS_LEASE,
    AnalysisRepository,
    AnalysisRunProjection,
)
from src.repositories.datasets import DatasetArtifactProjection, DatasetRepository
from src.repositories.storage_objects import (
    StorageObjectProjection,
    StorageObjectRepository,
)
from src.services.store_scope import StoreScopeError, StoreScopeResolver
from src.storage.keys import evidence_object_key, workspace_token
from src.storage.postgres_entry_locks import PostgresEntryLockManager
from src.storage.protocol import AvailableObject, StagedObject

ANALYSIS_NAMESPACE = UUID("652ba4fa-1e90-4a26-a13c-2f3bd7895769")
ALGORITHM_VERSIONS = MappingProxyType(
    {
        "sales_ads": SALES_ADS_VERSION,
        "inventory_risk": INVENTORY_VERSION,
        "fifo_cost_aging": FIFO_VERSION,
        "operating_profit": PROFIT_VERSION,
        "replenishment": REPLENISHMENT_VERSION,
    }
)
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
ALLOWED_SCOPE = frozenset(
    {"store_id", "period_start", "period_end", "currency", "sku_ids"}
)
CALCULATION_ROLES = frozenset(
    {
        "daily_sales",
        "shopee_advertising",
        "product_inventory_sales",
        "inventory_receipt_lot",
        "outbound_event",
        "refund",
        "settlement",
        "fulfillment_cost",
        "operating_expense",
        "fx_effect",
        "other_variable_cost",
        "replenishment_policy",
        "tax",
    }
)
STORE_REQUIRED_ROLES = CALCULATION_ROLES - {"replenishment_policy"}
PERIOD_DATED_ROLES = frozenset(
    {
        "daily_sales",
        "shopee_advertising",
        "refund",
    }
)
AS_OF_DATED_ROLES = frozenset({"product_inventory_sales", "outbound_event"})
PERIOD_ROLES = frozenset(
    {
        "settlement",
        "fulfillment_cost",
        "operating_expense",
        "fx_assumption",
        "fx_effect",
        "other_variable_cost",
        "tax",
    }
)


class AnalysisNotFound(RuntimeError):
    code = "ANALYSIS_NOT_FOUND"


class AnalysisAuthorityUnavailable(RuntimeError):
    code = "ANALYSIS_AUTHORITY_UNAVAILABLE"


class AnalysisInvalid(RuntimeError):
    code = "ANALYSIS_INVALID"


class AnalysisInputChanged(RuntimeError):
    code = "ANALYSIS_INPUT_CHANGED"


class AnalysisBusy(RuntimeError):
    code = "ANALYSIS_BUSY"


@dataclass(frozen=True, slots=True)
class AnalysisPlan:
    run_id: UUID
    workspace_id: str
    kind: str
    dataset_version_id: UUID
    scope: Mapping[str, object]
    scope_hash: str
    algorithm_version: str
    input_hash: str
    dependency_ids: tuple[tuple[UUID, str], ...]


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    run_id: UUID
    dataset_version_id: UUID
    kind: str
    algorithm_version: str
    input_hash: str
    status: str
    disposition: str
    artifact_sha256: str
    evidence_count: int


class AnalysisService:
    def __init__(
        self,
        engine: Engine,
        storage,
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
        self._locks = PostgresEntryLockManager(engine)
        with PostgresUnitOfWork(engine) as uow:
            AnalysisRepository(uow.connection).recover_running(
                workspace_id,
                self._clock(),
            )

    def plan(
        self,
        kind: str,
        dataset_version_id: UUID,
        scope: Mapping[str, object],
    ) -> AnalysisPlan:
        if kind not in ALGORITHM_VERSIONS:
            raise AnalysisInvalid("analysis_kind_invalid")
        normalized_scope = self._scope_for_version(dataset_version_id, scope)
        artifacts, tables, version_digest = self._load_inputs(dataset_version_id)
        scoped_tables, scope_limitations = _apply_scope(tables, normalized_scope)
        scope_hash = stable_hash(normalized_scope)
        input_hash = stable_hash(
            {
                "dataset_version_id": str(dataset_version_id),
                "version_digest": version_digest,
                "artifacts": [
                    {
                        "id": str(artifact.id),
                        "kind": artifact.artifact_kind,
                        "sha256": artifact.sha256,
                    }
                    for artifact in artifacts
                ],
                "tables": scoped_tables,
                "scope_limitations": scope_limitations,
                "scope": normalized_scope,
            }
        )
        algorithm_version = ALGORITHM_VERSIONS[kind]
        run_id = uuid5(
            ANALYSIS_NAMESPACE,
            f"{self._workspace_id}:{dataset_version_id}:{kind}:"
            f"{algorithm_version}:{input_hash}:{scope_hash}",
        )
        return AnalysisPlan(
            run_id,
            self._workspace_id,
            kind,
            dataset_version_id,
            MappingProxyType(normalized_scope),
            scope_hash,
            algorithm_version,
            input_hash,
            tuple((artifact.id, artifact.sha256) for artifact in artifacts),
        )

    def run(self, plan: AnalysisPlan, idempotency_key: str) -> AnalysisResult:
        if not isinstance(plan, AnalysisPlan) or plan.workspace_id != self._workspace_id:
            raise AnalysisInvalid("analysis_plan_invalid")
        if (
            not isinstance(idempotency_key, str)
            or not 1 <= len(idempotency_key) <= 128
            or any(
                ord(character) < 0x21 or ord(character) > 0x7E
                for character in idempotency_key
            )
        ):
            raise AnalysisInvalid("idempotency_key_invalid")
        current = self.plan(plan.kind, plan.dataset_version_id, plan.scope)
        if current != plan:
            raise AnalysisInputChanged("analysis_input_changed")
        lock_key = (
            f"workspaces/{workspace_token(self._workspace_id)}/runs/{plan.run_id}"
        )
        with self._locks.acquire((lock_key,)):
            now = self._clock()
            with self._engine.connect() as connection:
                repository = AnalysisRepository(connection)
                existing = repository.find_exact(plan)
                if existing is not None and existing.status == "completed":
                    return self._result(existing, "reused")
                if (
                    existing is not None
                    and existing.status == "running"
                    and (
                        existing.lease_expires_at is None
                        or existing.lease_expires_at > now
                    )
                ):
                    raise AnalysisBusy("analysis_still_running")
            try:
                with PostgresUnitOfWork(self._engine) as uow:
                    started = AnalysisRepository(uow.connection).insert_running(
                        plan,
                        now,
                    )
            except Exception:
                with self._engine.connect() as connection:
                    committed_start = AnalysisRepository(connection).find_exact(
                        plan
                    )
                if (
                    committed_start is None
                    or committed_start.status not in {"running", "completed"}
                    or (
                        committed_start.status == "running"
                        and (
                            committed_start.lease_expires_at is None
                            or committed_start.lease_expires_at <= now
                        )
                    )
                ):
                    raise
                started = committed_start
            if started.status == "completed":
                return self._result(started, "reused")
            staged = None
            staged_object_id = None
            available = None
            final_object_id = None
            try:
                _artifacts, tables, _version_digest = self._load_inputs(
                    plan.dataset_version_id
                )
                tables, scope_limitations = _apply_scope(tables, plan.scope)
                calculation = self._calculate(plan, tables)
                state = self._scope_state(plan.dataset_version_id, plan.scope)
                state_limitations = (
                    ("not_opened_yet",)
                    if state == "not_opened_yet"
                    else ()
                )
                payload = {
                    "run_id": str(plan.run_id),
                    "dataset_version_id": str(plan.dataset_version_id),
                    "analysis_kind": plan.kind,
                    "algorithm_version": plan.algorithm_version,
                    "input_hash": plan.input_hash,
                    "scope": dict(plan.scope),
                    "state": state,
                    "coverage": _coverage(tables, scope_limitations),
                    "limitations": list(
                        dict.fromkeys(
                            calculation.limitations
                            + scope_limitations
                            + state_limitations
                        )
                    ),
                    "result": canonical_value(calculation),
                }
                content = canonical_json_bytes(payload) + b"\n"
                digest = sha256(content).hexdigest()
                staged = self._storage.put_staging(
                    BytesIO(content),
                    max_bytes=MAX_ARTIFACT_BYTES,
                    media_type="application/json",
                )
                staged_object_id = self._record_staged_cleanup(staged)
                available = self._storage.promote(
                    staged.key,
                    evidence_object_key(
                        self._workspace_id,
                        str(plan.run_id),
                        digest,
                    ),
                    digest,
                )
                final_object_id = self._record_available_for_publish(available)
                result = self._publish(
                    plan,
                    calculation.evidence,
                    staged,
                    available,
                    final_object_id,
                    digest,
                )
            except Exception as error:
                if staged is not None:
                    self._cleanup_staged(staged, staged_object_id, error)
                if available is not None and final_object_id is None:
                    self._cleanup_available(available, None, error)
                try:
                    with self._engine.connect() as connection:
                        committed = AnalysisRepository(connection).find_exact(plan)
                    if committed is not None and committed.status == "completed":
                        return self._result(committed, "created")
                except Exception:
                    error.add_note("analysis_outcome_unknown_final_retained")
                    raise error
                with PostgresUnitOfWork(self._engine) as uow:
                    AnalysisRepository(uow.connection).fail(
                        plan.run_id,
                        _failure_code(error),
                        self._clock(),
                    )
                raise
            return result

    def get(self, run_id: UUID) -> AnalysisResult:
        with self._engine.connect() as connection:
            run = AnalysisRepository(connection).get(self._workspace_id, run_id)
        if run is None or run.status != "completed":
            raise AnalysisNotFound
        return self._result(run, "read")

    def get_exact_completed(
        self,
        kind: str,
        dataset_version_id: UUID,
        scope: Mapping[str, object],
    ) -> tuple[AnalysisResult, dict[str, object], tuple[object, ...]]:
        plan = self.plan(kind, dataset_version_id, scope)
        with self._engine.connect() as connection:
            run = AnalysisRepository(connection).find_exact(plan)
        if run is None or run.status != "completed":
            raise AnalysisNotFound
        result = self.get(run.id)
        snapshot = self.get_snapshot(run.id)
        evidence = self.get_evidence(run.id)
        return result, snapshot, evidence

    def default_scope(self, dataset_version_id: UUID) -> dict[str, object]:
        """Derive a bounded reporting scope from one immutable version."""

        _artifacts, tables, _digest = self._load_inputs(dataset_version_id)
        dates: list[date] = []
        primary_dates: list[date] = []
        currencies: set[str] = set()
        primary_currencies: set[str] = set()
        for role, rows in tables.items():
            for row in rows:
                currency = str(row.get("currency", "")).strip()
                if currency:
                    currencies.add(currency)
                    if role in {"daily_sales", "shopee_advertising"}:
                        primary_currencies.add(currency)
                for field in (
                    "date",
                    "period_start",
                    "period_end",
                    "receipt_date",
                    "as_of_date",
                ):
                    raw = str(row.get(field, "")).strip()
                    if not raw:
                        continue
                    try:
                        parsed = date.fromisoformat(raw[:10])
                        dates.append(parsed)
                        if role in {"daily_sales", "shopee_advertising"} and field == "date":
                            primary_dates.append(parsed)
                    except ValueError:
                        continue
        if primary_dates:
            dates = primary_dates
        if primary_currencies:
            currencies = primary_currencies
        if not dates or (currencies and currencies != {"BRL"}):
            raise AnalysisInvalid("analysis_scope_unavailable")
        period_end = max(dates)
        scope: dict[str, object] = {
            "period_start": period_end.replace(day=1).isoformat(),
            "period_end": period_end.isoformat(),
            "currency": "BRL",
        }
        try:
            catalog = self._store_scopes.catalog(dataset_version_id)
        except StoreScopeError as error:
            raise AnalysisInvalid("analysis_store_scope_invalid") from error
        catalog_stores = tuple(item.store_id for item in catalog if item.has_data)
        if len(catalog_stores) == 1:
            scope["store_id"] = catalog_stores[0]
        return scope

    def preparation_scopes(
        self,
        dataset_version_id: UUID,
    ) -> tuple[dict[str, object], ...]:
        """Return immutable all-store then catalog-order single-store scopes."""

        base = self.default_scope(dataset_version_id)
        base.pop("store_id", None)
        try:
            catalog = self._store_scopes.catalog(dataset_version_id)
        except StoreScopeError as error:
            raise AnalysisInvalid("analysis_store_scope_invalid") from error
        return (
            base,
            *(
                {**base, "store_id": item.store_id}
                for item in catalog
                if item.has_data
            ),
        )

    def read_exact_completed(
        self,
        connection: Connection,
        kind: str,
        dataset_version_id: UUID,
        scope: Mapping[str, object],
    ) -> tuple[AnalysisResult, dict[str, object], tuple[object, ...]]:
        """Read one immutable analysis through the caller's controlled transaction."""

        if kind not in ALGORITHM_VERSIONS:
            raise AnalysisNotFound
        normalized_scope = self._scope_for_version(dataset_version_id, scope)
        repository = AnalysisRepository(connection)
        runs = repository.completed_for_scope(
            self._workspace_id,
            dataset_version_id,
            kind,
            ALGORITHM_VERSIONS[kind],
            stable_hash(normalized_scope),
        )
        if len(runs) != 1 or runs[0].scope != normalized_scope:
            raise AnalysisNotFound
        run = runs[0]
        artifact = repository.get_artifact(run.id)
        storage = (
            StorageObjectRepository(connection).get(artifact.storage_object_id)
            if artifact is not None
            else None
        )
        evidence = repository.get_evidence(run.id)
        snapshot = self._verified_snapshot(run, artifact, storage)
        if artifact is None or not evidence:
            raise AnalysisAuthorityUnavailable
        result = AnalysisResult(
            run.id,
            run.dataset_version_id,
            run.analysis_kind,
            run.algorithm_version,
            run.input_hash,
            run.status,
            "read",
            artifact.snapshot_sha256,
            len(evidence),
        )
        return result, snapshot, evidence

    def load_scoped_inputs(
        self,
        dataset_version_id: UUID,
        scope: Mapping[str, object],
    ) -> tuple[
        dict[str, tuple[Mapping[str, object], ...]],
        tuple[str, ...],
    ]:
        """Return the exact verified/scoped source rows used by an analysis plan."""

        normalized_scope = self._scope_for_version(dataset_version_id, scope)
        _artifacts, tables, _version_digest = self._load_inputs(dataset_version_id)
        return _apply_scope(tables, normalized_scope)

    def _scope_for_version(
        self,
        dataset_version_id: UUID,
        scope: Mapping[str, object],
    ) -> dict[str, object]:
        normalized = _scope(scope)
        store_id = normalized.get("store_id")
        if store_id is None:
            return normalized
        try:
            self._store_scopes.resolve(dataset_version_id, (str(store_id),))
        except StoreScopeError as error:
            raise AnalysisInvalid("analysis_store_scope_invalid") from error
        return normalized

    def _scope_state(
        self,
        dataset_version_id: UUID,
        scope: Mapping[str, object],
    ) -> str:
        store_id = scope.get("store_id")
        if not isinstance(store_id, str):
            return "available"
        period_end = date.fromisoformat(str(scope["period_end"]))
        descriptor = next(
            (
                item
                for item in self._store_scopes.catalog(dataset_version_id)
                if item.store_id == store_id
            ),
            None,
        )
        if descriptor is None:
            raise AnalysisInvalid("analysis_store_scope_invalid")
        if descriptor.opened_on is not None and period_end < descriptor.opened_on:
            return "not_opened_yet"
        return "available"

    def get_snapshot(self, run_id: UUID) -> dict[str, object]:
        with self._engine.connect() as connection:
            repository = AnalysisRepository(connection)
            run = repository.get(self._workspace_id, run_id)
            artifact = repository.get_artifact(run_id)
            storage = (
                StorageObjectRepository(connection).get(artifact.storage_object_id)
                if artifact is not None
                else None
            )
        return self._verified_snapshot(run, artifact, storage)

    def _verified_snapshot(self, run, artifact, storage) -> dict[str, object]:
        if run is None or run.status != "completed":
            raise AnalysisNotFound
        if (
            artifact is None
            or storage is None
            or storage.workspace_id != self._workspace_id
            or storage.state != "available"
            or storage.purpose != "evidence"
            or storage.sha256 != artifact.snapshot_sha256
        ):
            raise AnalysisAuthorityUnavailable
        try:
            with self._storage.open_verified(
                storage.object_key,
                artifact.snapshot_sha256,
                storage.size_bytes,
            ) as opened:
                content = opened.read()
            if sha256(content).hexdigest() != artifact.snapshot_sha256:
                raise AnalysisAuthorityUnavailable
            payload = json.loads(content)
        except Exception as error:
            raise AnalysisAuthorityUnavailable from error
        if (
            not isinstance(payload, dict)
            or payload.get("run_id") != str(run.id)
            or payload.get("dataset_version_id") != str(run.dataset_version_id)
            or payload.get("analysis_kind") != run.analysis_kind
            or payload.get("algorithm_version") != run.algorithm_version
            or payload.get("input_hash") != run.input_hash
            or payload.get("scope") != run.scope
        ):
            raise AnalysisAuthorityUnavailable
        return payload

    def get_evidence(self, run_id: UUID, evidence_id: UUID | None = None):
        self.get_snapshot(run_id)
        with self._engine.connect() as connection:
            repository = AnalysisRepository(connection)
            run = repository.get(self._workspace_id, run_id)
            items = repository.get_evidence(run_id, evidence_id)
        if run is None or run.status != "completed" or not items:
            raise AnalysisNotFound
        return items

    def _publish(
        self,
        plan: AnalysisPlan,
        evidence: tuple[object, ...],
        staged,
        available,
        final_object_id: UUID,
        digest: str,
    ) -> AnalysisResult:
        now = self._clock()
        try:
            with PostgresUnitOfWork(self._engine) as uow:
                StorageObjectRepository(
                    uow.connection
                ).adopt_quarantined_available(
                    final_object_id,
                    object_key=available.key,
                    sha256=available.sha256,
                    etag=available.etag,
                    purpose="evidence",
                    now=now,
                )
                run, artifact = AnalysisRepository(uow.connection).complete(
                    plan=plan,
                    storage_object_id=final_object_id,
                    snapshot_sha256=digest,
                    dependency_ids=plan.dependency_ids,
                    evidence=evidence,
                    now=now,
                )
        except Exception as error:
            try:
                with self._engine.connect() as connection:
                    repository = AnalysisRepository(connection)
                    committed = repository.find_exact(plan)
                    committed_artifact = (
                        repository.get_artifact(plan.run_id)
                        if committed is not None and committed.status == "completed"
                        else None
                    )
                    committed_storage = (
                        StorageObjectRepository(connection).get(final_object_id)
                        if committed_artifact is not None
                        else None
                    )
            except Exception:
                error.add_note("analysis_commit_outcome_unknown_final_retained")
                raise
            if (
                committed is not None
                and committed.status == "completed"
                and committed_artifact is not None
                and committed_artifact.snapshot_sha256 == digest
                and committed_artifact.storage_object_id == final_object_id
                and committed_storage is not None
                and committed_storage.purpose == "evidence"
                and committed_storage.state == "available"
            ):
                self._cleanup_staged(staged, None, error)
                return self._result(committed, "created")
            self._cleanup_available(available, final_object_id, error)
            raise
        self._cleanup_staged(staged, None)
        return AnalysisResult(
            run.id,
            run.dataset_version_id,
            run.analysis_kind,
            run.algorithm_version,
            run.input_hash,
            run.status,
            "created",
            artifact.snapshot_sha256,
            len(evidence),
        )

    def _record_staged_cleanup(self, staged: StagedObject) -> UUID:
        with self._engine.connect() as connection:
            existing = StorageObjectRepository(connection).get_by_key(staged.key)
        if existing is not None:
            if not _matches_cleanup_record(existing, self._workspace_id, staged):
                raise RuntimeError("analysis_cleanup_ledger_authority_conflict")
            return existing.id
        object_id = uuid4()
        now = self._clock()
        try:
            with PostgresUnitOfWork(self._engine) as uow:
                StorageObjectRepository(uow.connection).create_staging(
                    workspace_id=self._workspace_id,
                    staged=staged,
                    purpose="temporary_upload",
                    now=now,
                    expires_at=now + ANALYSIS_LEASE,
                    object_id=object_id,
                )
        except Exception:
            with self._engine.connect() as connection:
                committed = StorageObjectRepository(connection).get_by_key(staged.key)
            if committed is None or not _matches_cleanup_record(
                committed,
                self._workspace_id,
                staged,
            ):
                raise
            return committed.id
        return object_id

    def _record_available_for_publish(self, available: AvailableObject) -> UUID:
        with self._engine.connect() as connection:
            existing = StorageObjectRepository(connection).get_by_key(available.key)
        if existing is not None:
            if not _matches_cleanup_record(existing, self._workspace_id, available):
                raise RuntimeError("analysis_cleanup_ledger_authority_conflict")
            return existing.id
        object_id = uuid4()
        now = self._clock()
        try:
            with PostgresUnitOfWork(self._engine) as uow:
                repository = StorageObjectRepository(uow.connection)
                repository.create_available(
                    object_id=object_id,
                    workspace_id=self._workspace_id,
                    available=available,
                    purpose="temporary_upload",
                    media_type="application/json",
                    now=now,
                    expires_at=now + ANALYSIS_LEASE,
                )
                repository.mark_quarantined(object_id, now=now)
        except Exception:
            with self._engine.connect() as connection:
                committed = StorageObjectRepository(connection).get_by_key(
                    available.key
                )
            if committed is None or not _matches_cleanup_record(
                committed,
                self._workspace_id,
                available,
            ):
                raise
            return committed.id
        return object_id

    def _cleanup_staged(
        self,
        staged: StagedObject,
        object_id: UUID | None,
        error: Exception | None = None,
    ) -> None:
        resolved_id = object_id or self._cleanup_record_id(staged.key)
        try:
            self._storage.delete(staged.key, expected_etag=staged.etag)
        except Exception as cleanup_error:
            try:
                resolved_id = resolved_id or self._record_staged_cleanup(staged)
                self._quarantine_cleanup(resolved_id)
            except Exception as ledger_error:
                _add_note(
                    error,
                    "analysis_staged_cleanup_ledger_failed:"
                    f"{type(ledger_error).__name__}",
                )
            _add_note(
                error,
                f"analysis_staged_cleanup_pending:{type(cleanup_error).__name__}",
            )
            return
        if resolved_id is not None:
            self._mark_cleanup_deleted(resolved_id, error)

    def _cleanup_available(
        self,
        available: AvailableObject,
        object_id: UUID | None,
        error: Exception | None = None,
    ) -> None:
        resolved_id = object_id or self._cleanup_record_id(available.key)
        if resolved_id is None:
            try:
                resolved_id = self._record_available_for_publish(available)
            except Exception as ledger_error:
                _add_note(
                    error,
                    "analysis_final_cleanup_ledger_failed:"
                    f"{type(ledger_error).__name__}",
                )
        try:
            self._storage.delete(available.key, expected_etag=available.etag)
        except Exception as cleanup_error:
            if resolved_id is not None:
                try:
                    self._quarantine_cleanup(resolved_id)
                except Exception as ledger_error:
                    _add_note(
                        error,
                        "analysis_final_quarantine_failed:"
                        f"{type(ledger_error).__name__}",
                    )
            _add_note(
                error,
                f"analysis_final_cleanup_pending:{type(cleanup_error).__name__}",
            )
            return
        if resolved_id is not None:
            self._mark_cleanup_deleted(resolved_id, error)

    def _cleanup_record_id(self, key: str) -> UUID | None:
        with self._engine.connect() as connection:
            record = StorageObjectRepository(connection).get_by_key(key)
        return record.id if record is not None else None

    def _quarantine_cleanup(self, object_id: UUID) -> None:
        with PostgresUnitOfWork(self._engine) as uow:
            StorageObjectRepository(uow.connection).mark_cleanup_pending(
                object_id,
                now=self._clock(),
            )

    def _mark_cleanup_deleted(
        self,
        object_id: UUID,
        error: Exception | None,
    ) -> None:
        try:
            with PostgresUnitOfWork(self._engine) as uow:
                StorageObjectRepository(uow.connection).mark_deleted(
                    object_id,
                    now=self._clock(),
                )
        except Exception as ledger_error:
            _add_note(
                error,
                "analysis_cleanup_tombstone_failed:"
                f"{type(ledger_error).__name__}",
            )

    def _result(self, run: AnalysisRunProjection, disposition: str) -> AnalysisResult:
        if run.status == "completed":
            self.get_snapshot(run.id)
        with self._engine.connect() as connection:
            repository = AnalysisRepository(connection)
            artifact = repository.get_artifact(run.id)
            evidence = repository.get_evidence(run.id)
        if artifact is None:
            raise AnalysisNotFound
        return AnalysisResult(
            run.id,
            run.dataset_version_id,
            run.analysis_kind,
            run.algorithm_version,
            run.input_hash,
            run.status,
            disposition,
            artifact.snapshot_sha256,
            len(evidence),
        )

    def _calculate(
        self,
        plan: AnalysisPlan,
        tables: Mapping[str, tuple[Mapping[str, object], ...]],
    ):
        calculation_tables = (
            _aggregate_all_store_inventory_inputs(tables)
            if "store_id" not in plan.scope
            else tables
        )
        as_of = _as_of(plan.scope)
        period_start = (
            date.fromisoformat(str(plan.scope["period_start"]))
            if "period_start" in plan.scope
            else None
        )
        if plan.kind == "sales_ads":
            return calculate_sales_ads(
                sales=tables.get("daily_sales", ()),
                advertising=tables.get("shopee_advertising", ()),
            )
        if plan.kind == "inventory_risk":
            return calculate_inventory_risk(
                sales=tables.get("daily_sales", ()),
                inventory=calculation_tables.get("product_inventory_sales", ()),
                as_of=as_of,
                period_start=period_start,
            )
        fifo = calculate_fifo_cost_aging(
            receipt_lots=tables.get("inventory_receipt_lot", ()),
            outbound_events=tables.get("outbound_event", ()),
            as_of=as_of,
            period_start=period_start,
        )
        if plan.kind == "fifo_cost_aging":
            return fifo
        if plan.kind == "operating_profit":
            profit_inputs = dict(tables)
            if fifo.cogs.value is not None:
                profit_inputs["fifo_cogs"] = ({"cogs_brl": fifo.cogs.value},)
            return calculate_operating_profit(profit_inputs)
        if plan.kind == "replenishment":
            return calculate_replenishment(
                sales=tables.get("daily_sales", ()),
                inventory=calculation_tables.get("product_inventory_sales", ()),
                policies=calculation_tables.get("replenishment_policy", ()),
                as_of=as_of,
                period_start=period_start,
            )
        raise AnalysisInvalid("analysis_kind_invalid")

    def _load_inputs(
        self,
        dataset_version_id: UUID,
    ) -> tuple[
        tuple[DatasetArtifactProjection, ...],
        dict[str, tuple[Mapping[str, object], ...]],
        str,
    ]:
        with self._engine.connect() as connection:
            datasets = DatasetRepository(connection)
            version = datasets.get_version(dataset_version_id)
            artifacts = datasets.list_artifacts(dataset_version_id)
            storage_repository = StorageObjectRepository(connection)
            storage_records = tuple(
                storage_repository.get(artifact.storage_object_id)
                for artifact in artifacts
            )
        if (
            version is None
            or version.workspace_id != self._workspace_id
            or version.status != "complete"
            or not artifacts
        ):
            raise AnalysisNotFound
        if version.schema_version == "synthetic.v1":
            selected_kinds = {"analysis_bundle"}
            expected_schema = "canonical.analysis.v1"
        elif version.schema_version == "canonical.import.v1":
            selected_kinds = {artifact.artifact_kind for artifact in artifacts}
            expected_schema = "canonical.import.v1"
        else:
            raise AnalysisInvalid("dataset_schema_unsupported")
        selected_count = sum(
            artifact.artifact_kind in selected_kinds for artifact in artifacts
        )
        if version.schema_version == "synthetic.v1" and selected_count != 1:
            raise AnalysisInvalid("synthetic_analysis_bundle_missing_or_duplicate")
        tables: dict[str, tuple[Mapping[str, object], ...]] = {}
        for artifact, storage in zip(artifacts, storage_records, strict=True):
            if (
                storage is None
                or storage.workspace_id != self._workspace_id
                or storage.state != "available"
                or storage.purpose != "normalized_dataset"
                or storage.sha256 != artifact.sha256
            ):
                raise AnalysisInvalid("dataset_artifact_authority_invalid")
            if artifact.artifact_kind not in selected_kinds:
                continue
            with self._storage.open_verified(
                storage.object_key,
                artifact.sha256,
                min(storage.size_bytes, MAX_ARTIFACT_BYTES),
            ) as opened:
                payload = json.load(opened)
            artifact_tables = payload.get("tables") if isinstance(payload, dict) else None
            if (
                not isinstance(payload, dict)
                or payload.get("schema_version") != expected_schema
                or not isinstance(artifact_tables, dict)
            ):
                raise AnalysisInvalid("dataset_artifact_schema_invalid")
            for role, rows in artifact_tables.items():
                if role in tables or not isinstance(role, str) or not isinstance(rows, list):
                    raise AnalysisInvalid("dataset_role_duplicate_or_invalid")
                if not all(isinstance(row, dict) for row in rows):
                    raise AnalysisInvalid("dataset_records_invalid")
                tables[role] = tuple(rows)
        return artifacts, tables, version.content_sha256


def _scope(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or not set(value) <= ALLOWED_SCOPE:
        raise AnalysisInvalid("analysis_scope_invalid")
    normalized: dict[str, object] = {}
    for key, item in sorted(value.items()):
        if key == "sku_ids":
            if not isinstance(item, (tuple, list)) or not all(
                isinstance(sku, str) and sku.strip() for sku in item
            ):
                raise AnalysisInvalid("analysis_scope_invalid")
            normalized[key] = sorted(set(sku.strip() for sku in item))
            if not normalized[key]:
                raise AnalysisInvalid("analysis_scope_invalid")
        elif not isinstance(item, str) or not item.strip():
            raise AnalysisInvalid("analysis_scope_invalid")
        else:
            normalized[key] = item.strip()
    if "period_end" not in normalized or "currency" not in normalized:
        raise AnalysisInvalid("analysis_scope_incomplete")
    if normalized["currency"] != "BRL":
        raise AnalysisInvalid("analysis_currency_unsupported")
    try:
        period_end = date.fromisoformat(str(normalized["period_end"]))
        period_start = (
            date.fromisoformat(str(normalized["period_start"]))
            if "period_start" in normalized
            else None
        )
    except ValueError as error:
        raise AnalysisInvalid("analysis_period_invalid") from error
    if period_start is not None and period_start > period_end:
        raise AnalysisInvalid("analysis_period_invalid")
    return normalized


def _as_of(scope: Mapping[str, object]) -> date:
    try:
        return date.fromisoformat(str(scope["period_end"]))
    except (KeyError, ValueError) as error:
        raise AnalysisInvalid("analysis_period_invalid") from error


def _coverage(
    tables: Mapping[str, Sequence[Mapping[str, object]]],
    limitations: tuple[str, ...],
) -> dict[str, object]:
    return {
        "included_rows": {role: len(rows) for role, rows in sorted(tables.items())},
        "scope_limitations": list(limitations),
    }


def _apply_scope(
    tables: Mapping[str, Sequence[Mapping[str, object]]],
    scope: Mapping[str, object],
) -> tuple[dict[str, tuple[Mapping[str, object], ...]], tuple[str, ...]]:
    store_id = scope.get("store_id")
    currency = scope.get("currency")
    sku_ids = set(scope.get("sku_ids", ()))
    period_start = (
        date.fromisoformat(str(scope["period_start"]))
        if "period_start" in scope
        else None
    )
    period_end = date.fromisoformat(str(scope["period_end"]))
    scoped: dict[str, tuple[Mapping[str, object], ...]] = {}
    limitations: list[str] = []
    for role, rows in tables.items():
        accepted: list[Mapping[str, object]] = []
        excluded = 0
        for row in rows:
            if (
                store_id is not None
                and role in STORE_REQUIRED_ROLES
                and "store_id" not in row
            ):
                excluded += 1
                continue
            if (
                store_id is not None
                and "store_id" in row
                and row["store_id"] != store_id
            ):
                excluded += 1
                continue
            if (
                currency is not None
                and role != "fx_assumption"
                and "currency" in row
                and row["currency"] != currency
            ):
                excluded += 1
                continue
            if sku_ids and role in CALCULATION_ROLES and "sku_id" not in row:
                excluded += 1
                continue
            if sku_ids and "sku_id" in row and row["sku_id"] not in sku_ids:
                excluded += 1
                continue
            row_date = row.get("date")
            if (
                role in PERIOD_DATED_ROLES | AS_OF_DATED_ROLES
                and not isinstance(row_date, str)
            ):
                excluded += 1
                continue
            if isinstance(row_date, str):
                try:
                    parsed_row_date = date.fromisoformat(row_date)
                except ValueError:
                    excluded += 1
                    continue
                if (
                    role in PERIOD_DATED_ROLES
                    and period_start is not None
                    and parsed_row_date < period_start
                ):
                    excluded += 1
                    continue
                if parsed_row_date > period_end:
                    excluded += 1
                    continue
            row_period_start = row.get("period_start")
            row_period_end = row.get("period_end")
            if role in PERIOD_ROLES and not (
                isinstance(row_period_start, str)
                and isinstance(row_period_end, str)
            ):
                excluded += 1
                continue
            if role in PERIOD_ROLES:
                try:
                    parsed_row_start = date.fromisoformat(str(row_period_start))
                    parsed_row_end = date.fromisoformat(str(row_period_end))
                except ValueError:
                    excluded += 1
                    continue
                if (
                    period_start is None
                    or parsed_row_start != period_start
                    or parsed_row_end != period_end
                ):
                    excluded += 1
                    continue
            accepted.append(row)
        scoped[role] = tuple(accepted)
        if excluded:
            limitations.append(f"scope_rows_excluded:{role}:{excluded}")
    return scoped, tuple(limitations)


def _aggregate_all_store_inventory_inputs(
    tables: Mapping[str, tuple[Mapping[str, object], ...]],
) -> dict[str, tuple[Mapping[str, object], ...]]:
    """Combine shared product SKUs across stores for all-store inventory math."""

    combined = dict(tables)
    inventory: dict[tuple[str, str], dict[str, object]] = {}
    for row in tables.get("product_inventory_sales", ()):
        key = (str(row.get("sku_id", "")), str(row.get("date", "")))
        current = inventory.get(key)
        if current is None:
            current = dict(row)
            current.pop("store_id", None)
            inventory[key] = current
            continue
        for field in ("on_hand_units", "inbound_units"):
            current[field] = int(current.get(field, 0)) + int(row.get(field, 0))
    if inventory:
        combined["product_inventory_sales"] = tuple(
            inventory[key] for key in sorted(inventory)
        )

    policies: dict[str, dict[str, object]] = {}
    for row in tables.get("replenishment_policy", ()):
        sku_id = str(row.get("sku_id", ""))
        current = policies.get(sku_id)
        if current is None:
            current = dict(row)
            current.pop("store_id", None)
            current["policy_id"] = f"all-stores:{sku_id}"
            policies[sku_id] = current
            continue
        if Decimal(str(current.get("unit_cost_brl"))) != Decimal(
            str(row.get("unit_cost_brl"))
        ):
            raise AnalysisInvalid("all_store_unit_cost_conflict")
        for field in ("reorder_point_units", "safety_stock_units"):
            current[field] = int(current.get(field, 0)) + int(row.get(field, 0))
        for field in ("lead_time_days", "target_cover_days"):
            current[field] = max(int(current.get(field, 0)), int(row.get(field, 0)))
    if policies:
        combined["replenishment_policy"] = tuple(
            policies[key] for key in sorted(policies)
        )
    return combined


def _failure_code(error: Exception) -> str:
    code = getattr(error, "code", error.__class__.__name__)
    return str(code)[:120]


def _matches_cleanup_record(
    record: StorageObjectProjection,
    workspace_id: str,
    stored: StagedObject | AvailableObject,
) -> bool:
    return (
        record.workspace_id == workspace_id
        and record.purpose == "temporary_upload"
        and record.state in {"staging", "quarantined"}
        and record.object_key == stored.key
        and record.sha256 == stored.sha256
        and record.etag == stored.etag
    )


def _add_note(error: Exception | None, note: str) -> None:
    if error is not None:
        error.add_note(note)
