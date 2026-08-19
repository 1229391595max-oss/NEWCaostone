from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import Engine

from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.services.dataset_preparation_service import DatasetPreparationService
from src.services.analysis_service import AnalysisService
from src.services.demo_action_authority import DemoActionAuthority
from src.services.forecast_service import ForecastService
from src.services.profit_bridge_service import ProfitBridgeService
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID


class RecordingAnalyses:
    def __init__(self) -> None:
        self.ready = set()
        self.runs = []

    def get_exact_completed(self, kind, version_id, scope):
        key = (version_id, kind, _scope_key(scope))
        if key not in self.ready:
            raise LookupError("missing")
        return SimpleNamespace(dataset_version_id=version_id), {}, ()

    def plan(self, kind, version_id, scope):
        return SimpleNamespace(
            kind=kind,
            dataset_version_id=version_id,
            scope=dict(scope),
        )

    def run(self, plan, idempotency_key):
        key = (plan.dataset_version_id, plan.kind, _scope_key(plan.scope))
        self.runs.append((*key, idempotency_key))
        self.ready.add(key)
        return SimpleNamespace(status="completed", dataset_version_id=plan.dataset_version_id)

    def preparation_scopes(self, version_id):
        del version_id
        common = {
            "period_start": "2026-07-01",
            "period_end": "2026-07-31",
            "currency": "BRL",
        }
        return (
            common,
            {**common, "store_id": "SYNTH-STORE-01"},
            {**common, "store_id": "SYNTH-STORE-02"},
        )


class FlakyBridge:
    def __init__(self) -> None:
        self.fail = True
        self.ready = set()
        self.calls = []

    def completed_id_for_session(self, version_id, scope=None):
        key = (version_id, _scope_key(scope or {}))
        return version_id if key in self.ready else None

    def get_for_session(self, version_id, bridge_id):
        if bridge_id != version_id:
            raise LookupError("missing")
        return SimpleNamespace(dataset_version_id=version_id)

    def run(self, version_id, **kwargs):
        key = (version_id, _scope_key(kwargs["scope"]))
        self.calls.append(key)
        if self.fail:
            raise RuntimeError("bridge_failed")
        self.ready.add(key)
        return SimpleNamespace(dataset_version_id=version_id)


class ReadyForecasts:
    def completed_id_for_session(self, version_id, scope=None):
        del scope
        return version_id


class RecordingActions:
    def __init__(self) -> None:
        self.ready_versions = set()
        self.calls = []

    def ready(self, version_id, scope=None):
        return (version_id, _scope_key(scope or {})) in self.ready_versions

    def ensure(self, version_id, scope=None):
        key = (version_id, _scope_key(scope or {}))
        self.calls.append(key)
        self.ready_versions.add(key)


class UnscopedAnalyses(RecordingAnalyses):
    def preparation_scopes(self, version_id):
        raise ValueError("ANALYSIS_SCOPE_UNAVAILABLE")


def _scope_key(scope):
    return tuple(sorted((key, str(value)) for key, value in scope.items()))


def test_preparation_is_exact_idempotent_and_retries_only_missing_domains(
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    candidate = seed_demo(
        generate_demo(seed=20260815),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 15, tzinfo=UTC),
    )
    current = seed_demo(
        generate_demo(seed=20260816),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 16, tzinfo=UTC),
    )
    analyses = RecordingAnalyses()
    bridges = FlakyBridge()
    actions = RecordingActions()
    service = DatasetPreparationService(
        migrated_engine,
        WORKSPACE_ID,
        analysis_service=analyses,
        profit_bridge_service=bridges,
        forecast_service=ReadyForecasts(),
        action_authority=actions,
    )

    first = service.prepare(candidate.dataset_version_id)
    assert first.dataset_version_id == candidate.dataset_version_id
    assert first.status == "partial"
    assert {item.name: item.status for item in first.domains}["profit"] == "failed"
    assert all(call[0] == candidate.dataset_version_id for call in analyses.runs)
    assert all(call[0] != current.dataset_version_id for call in analyses.runs)
    assert {
        dict(call[2]).get("store_id") for call in analyses.runs
    } == {None, "SYNTH-STORE-01", "SYNTH-STORE-02"}
    completed_calls = tuple(analyses.runs)

    bridges.fail = False
    retried = service.prepare(candidate.dataset_version_id)
    replay = service.prepare(candidate.dataset_version_id)

    assert retried.status == "ready"
    assert replay == retried
    assert tuple(analyses.runs) == completed_calls
    assert len(bridges.calls) == 6
    assert {dict(scope).get("store_id") for _version, scope in bridges.calls} == {
        None,
        "SYNTH-STORE-01",
        "SYNTH-STORE-02",
    }
    assert len(actions.calls) == 3


def test_seeded_release_readiness_matches_existing_immutable_authority(
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
    analyses = AnalysisService(migrated_engine, storage, WORKSPACE_ID)
    bridges = ProfitBridgeService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        analysis_service=analyses,
    )
    service = DatasetPreparationService(
        migrated_engine,
        WORKSPACE_ID,
        analysis_service=analyses,
        profit_bridge_service=bridges,
        forecast_service=ForecastService(migrated_engine, storage, WORKSPACE_ID),
        action_authority=DemoActionAuthority(
            migrated_engine,
            storage,
            WORKSPACE_ID,
            profit_bridge_service=bridges,
        ),
    )

    readiness = service.readiness(seeded.dataset_version_id)
    assert readiness.status == "ready", readiness.domains


def test_missing_analysis_scope_returns_bounded_domain_failures(
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
    service = DatasetPreparationService(
        migrated_engine,
        WORKSPACE_ID,
        analysis_service=UnscopedAnalyses(),
    )

    result = service.prepare(seeded.dataset_version_id)

    assert result.status == "failed"
    assert len(result.domains) == 5
    assert {item.limitation_code for item in result.domains} == {
        "ANALYSIS_SCOPE_UNAVAILABLE"
    }
    assert next(item for item in result.domains if item.name == "forecast").status == (
        "unavailable"
    )
