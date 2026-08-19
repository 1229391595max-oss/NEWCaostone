from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import Engine

from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.datasets import DatasetRepository
from src.repositories.operators import OperatorRepository
from src.services.analysis_service import AnalysisService
from src.services.public_release_service import (
    PUBLIC_ANALYSIS_SCOPE,
    PublicReleaseConflict,
    PublicReleaseIdempotencyConflict,
    PublicReleaseIneligible,
    PublicReleaseService,
)
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID

PEPPER = "test-public-release-idempotency-pepper"


class PublishAcknowledgementLostUnitOfWork(PostgresUnitOfWork):
    def commit(self) -> None:
        super().commit()
        raise RuntimeError("injected_publish_acknowledgement_lost")


def _seed_two_versions(engine: Engine):
    storage = MemoryWorkflowStorage()
    with PostgresUnitOfWork(engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    analyses = AnalysisService(engine, storage, WORKSPACE_ID)
    first = seed_demo(
        generate_demo(seed=20260813),
        PostgresUnitOfWork(engine),
        storage,
        now=datetime(2026, 8, 13, 18, tzinfo=UTC),
    )
    second = seed_demo(
        generate_demo(seed=20260814),
        PostgresUnitOfWork(engine),
        storage,
        now=datetime(2026, 8, 14, 18, tzinfo=UTC),
    )
    return storage, first, second, analyses


def test_publish_is_cas_guarded_request_bound_and_replay_safe(
    migrated_engine: Engine,
) -> None:
    _storage, first, second, analyses = _seed_two_versions(migrated_engine)
    service = PublicReleaseService(
        migrated_engine,
        WORKSPACE_ID,
        idempotency_pepper=PEPPER,
        clock=lambda: datetime(2026, 8, 14, 19, tzinfo=UTC),
        analysis_service=analyses,
    )

    published = service.publish(
        first.dataset_version_id,
        expected_current_id=second.dataset_version_id,
        idempotency_key="publish-v1-again",
    )
    replay = service.publish(
        first.dataset_version_id,
        expected_current_id=second.dataset_version_id,
        idempotency_key="publish-v1-again",
    )

    assert published.created is True
    assert published.replayed is False
    assert published.dataset_version_id == first.dataset_version_id
    assert published.previous_dataset_version_id == second.dataset_version_id
    assert replay == replace(published, replayed=True)
    assert service.current().dataset_version_id == first.dataset_version_id

    with pytest.raises(PublicReleaseConflict):
        service.publish(
            second.dataset_version_id,
            expected_current_id=second.dataset_version_id,
            idempotency_key="stale-current",
        )
    with pytest.raises(PublicReleaseIdempotencyConflict):
        service.publish(
            second.dataset_version_id,
            expected_current_id=first.dataset_version_id,
            idempotency_key="publish-v1-again",
        )


def test_publish_with_explicit_preparation_only_switches_a_ready_version(
    migrated_engine: Engine,
) -> None:
    _storage, first, second, analyses = _seed_two_versions(migrated_engine)

    class Preparation:
        status = "partial"
        calls = []

        def readiness(self, version_id):
            self.calls.append(version_id)
            return SimpleNamespace(status=self.status)

    preparation = Preparation()
    service = PublicReleaseService(
        migrated_engine,
        WORKSPACE_ID,
        idempotency_pepper=PEPPER,
        analysis_service=analyses,
        preparation_service=preparation,
    )

    with pytest.raises(PublicReleaseIneligible):
        service.publish(
            first.dataset_version_id,
            expected_current_id=second.dataset_version_id,
            idempotency_key="publish-before-calculate",
        )
    assert service.current().dataset_version_id == second.dataset_version_id

    preparation.status = "ready"
    published = service.publish(
        first.dataset_version_id,
        expected_current_id=second.dataset_version_id,
        idempotency_key="publish-after-calculate",
    )
    assert published.dataset_version_id == first.dataset_version_id
    assert preparation.calls == [first.dataset_version_id, first.dataset_version_id]


def test_publish_rejects_unproved_version_even_when_marked_complete(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        operators = OperatorRepository(uow.connection)
        operators.create_workspace(WORKSPACE_ID)
        datasets = DatasetRepository(uow.connection)
        series = datasets.create_series(
            workspace_id=WORKSPACE_ID,
            name="unproved",
            now=datetime(2026, 8, 14, tzinfo=UTC),
        )
        version = datasets.create_version(
            series_id=series.id,
            workspace_id=WORKSPACE_ID,
            source_workflow_id=None,
            version_number=1,
            schema_version="canonical.import.v1",
            content_sha256="a" * 64,
            now=datetime(2026, 8, 14, tzinfo=UTC),
        )

    service = PublicReleaseService(
        migrated_engine,
        WORKSPACE_ID,
        idempotency_pepper=PEPPER,
    )
    with pytest.raises(PublicReleaseIneligible):
        service.publish(
            version.id,
            expected_current_id=None,
            idempotency_key="unproved-version",
        )


def test_publish_uses_database_authority_when_commit_acknowledgement_is_lost(
    migrated_engine: Engine,
) -> None:
    _storage, first, second, analyses = _seed_two_versions(migrated_engine)
    service = PublicReleaseService(
        migrated_engine,
        WORKSPACE_ID,
        idempotency_pepper=PEPPER,
        clock=lambda: datetime(2026, 8, 14, 19, tzinfo=UTC),
        uow_factory=PublishAcknowledgementLostUnitOfWork,
        analysis_service=analyses,
    )

    result = service.publish(
        first.dataset_version_id,
        expected_current_id=second.dataset_version_id,
        idempotency_key="publish-ack-lost",
    )

    assert result.dataset_version_id == first.dataset_version_id
    assert result.created is True
    assert result.replayed is True
    assert service.current().dataset_version_id == first.dataset_version_id


def test_publish_prepares_and_requires_the_default_profit_bridge(
    migrated_engine: Engine,
) -> None:
    _storage, first, second, analyses = _seed_two_versions(migrated_engine)

    class RecordingProfitBridgeService:
        def __init__(self) -> None:
            self.calls = []
            self.available = set()

        def run(
            self,
            dataset_version_id,
            current_period,
            comparison_period,
            scope,
        ):
            self.calls.append(
                (dataset_version_id, current_period, comparison_period, scope)
            )
            self.available.add(
                (dataset_version_id, tuple(sorted(scope.items())))
            )
            return SimpleNamespace(dataset_version_id=dataset_version_id)

        def latest(self, dataset_version_id):
            if dataset_version_id not in self.available:
                raise RuntimeError("bridge_missing")
            return SimpleNamespace(dataset_version_id=dataset_version_id)

        def completed_id_for_session(self, dataset_version_id, scope=None):
            key = (dataset_version_id, tuple(sorted((scope or {}).items())))
            return dataset_version_id if key in self.available else None

        def get_for_session(self, dataset_version_id, bridge_id):
            if bridge_id != dataset_version_id:
                raise RuntimeError("bridge_mismatch")
            return SimpleNamespace(dataset_version_id=dataset_version_id)

    bridges = RecordingProfitBridgeService()
    service = PublicReleaseService(
        migrated_engine,
        WORKSPACE_ID,
        idempotency_pepper=PEPPER,
        clock=lambda: datetime(2026, 8, 14, 19, tzinfo=UTC),
        analysis_service=analyses,
        profit_bridge_service=bridges,
    )

    assert service.release_ready(first.dataset_version_id) is False
    service.publish(
        first.dataset_version_id,
        expected_current_id=second.dataset_version_id,
        idempotency_key="publish-with-profit-bridge",
    )

    assert service.release_ready(first.dataset_version_id) is True
    assert len(bridges.calls) == 3
    assert {call[3].get("store_id") for call in bridges.calls} == {
        None,
        "SYNTH-STORE-01",
        "SYNTH-STORE-02",
    }
    assert PUBLIC_ANALYSIS_SCOPE == {
        "store_id": "SYNTH-STORE-01",
        "period_start": "2026-07-01",
        "period_end": "2026-07-31",
        "currency": "BRL",
    }


def test_publish_prepares_and_requires_the_public_action_authority(
    migrated_engine: Engine,
) -> None:
    _storage, first, second, analyses = _seed_two_versions(migrated_engine)

    class RecordingActionAuthority:
        def __init__(self) -> None:
            self.calls = []
            self.available = set()

        def ensure(self, dataset_version_id, scope=None):
            key = (dataset_version_id, tuple(sorted((scope or {}).items())))
            self.calls.append(key)
            self.available.add(key)

        def ready(self, dataset_version_id, scope=None):
            return (
                dataset_version_id,
                tuple(sorted((scope or {}).items())),
            ) in self.available

    actions = RecordingActionAuthority()
    service = PublicReleaseService(
        migrated_engine,
        WORKSPACE_ID,
        idempotency_pepper=PEPPER,
        clock=lambda: datetime(2026, 8, 14, 19, tzinfo=UTC),
        analysis_service=analyses,
        action_authority=actions,
    )

    assert service.release_ready(first.dataset_version_id) is False
    service.publish(
        first.dataset_version_id,
        expected_current_id=second.dataset_version_id,
        idempotency_key="publish-with-action-authority",
    )

    assert service.release_ready(first.dataset_version_id) is True
    assert len(actions.calls) == 3
    assert {dict(scope).get("store_id") for _version, scope in actions.calls} == {
        None,
        "SYNTH-STORE-01",
        "SYNTH-STORE-02",
    }
