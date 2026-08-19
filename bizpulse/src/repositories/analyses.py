"""PostgreSQL authority for immutable deterministic analysis publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Connection, select, update

from src.db.schema import (
    analysis_artifacts,
    analysis_dependencies,
    analysis_runs,
    evidence_items,
)

ANALYSIS_LEASE = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class AnalysisRunProjection:
    id: UUID
    workspace_id: str
    dataset_version_id: UUID
    analysis_kind: str
    algorithm_version: str
    input_hash: str
    scope: dict[str, object]
    scope_hash: str
    status: str
    failure_code: str | None
    created_at: datetime
    lease_expires_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class AnalysisArtifactProjection:
    id: UUID
    run_id: UUID
    storage_object_id: UUID
    snapshot_sha256: str
    media_type: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EvidenceProjection:
    id: UUID
    run_id: UUID
    alias: str
    evidence_state: str
    formula: str
    source_refs: list[str]
    created_at: datetime


class AnalysisRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def recover_running(self, workspace_id: str, now: datetime) -> int:
        return int(
            self._connection.execute(
                update(analysis_runs)
                .where(
                    analysis_runs.c.workspace_id == workspace_id,
                    analysis_runs.c.status == "running",
                    analysis_runs.c.lease_expires_at <= now,
                )
                .values(
                    status="failed",
                    failure_code="restart_interrupted",
                    lease_expires_at=None,
                    completed_at=now,
                )
            ).rowcount
        )

    def get(self, workspace_id: str, run_id: UUID) -> AnalysisRunProjection | None:
        row = self._connection.execute(
            select(*analysis_runs.c).where(
                analysis_runs.c.workspace_id == workspace_id,
                analysis_runs.c.id == run_id,
            )
        ).mappings().one_or_none()
        return AnalysisRunProjection(**row) if row is not None else None

    def find_exact(self, plan) -> AnalysisRunProjection | None:
        row = self._connection.execute(
            select(*analysis_runs.c).where(
                analysis_runs.c.workspace_id == plan.workspace_id,
                analysis_runs.c.dataset_version_id == plan.dataset_version_id,
                analysis_runs.c.analysis_kind == plan.kind,
                analysis_runs.c.algorithm_version == plan.algorithm_version,
                analysis_runs.c.input_hash == plan.input_hash,
                analysis_runs.c.scope_hash == plan.scope_hash,
            )
        ).mappings().one_or_none()
        return AnalysisRunProjection(**row) if row is not None else None

    def completed_for_scope(
        self,
        workspace_id: str,
        dataset_version_id: UUID,
        analysis_kind: str,
        algorithm_version: str,
        scope_hash: str,
    ) -> tuple[AnalysisRunProjection, ...]:
        rows = self._connection.execute(
            select(*analysis_runs.c)
            .where(
                analysis_runs.c.workspace_id == workspace_id,
                analysis_runs.c.dataset_version_id == dataset_version_id,
                analysis_runs.c.analysis_kind == analysis_kind,
                analysis_runs.c.algorithm_version == algorithm_version,
                analysis_runs.c.scope_hash == scope_hash,
                analysis_runs.c.status == "completed",
            )
            .order_by(analysis_runs.c.completed_at.desc(), analysis_runs.c.id.desc())
            .limit(2)
        ).mappings()
        return tuple(AnalysisRunProjection(**row) for row in rows)

    def insert_running(self, plan, now: datetime) -> AnalysisRunProjection:
        current = self.find_exact(plan)
        if current is not None:
            if current.status == "completed":
                return current
            if current.status == "running":
                if (
                    current.lease_expires_at is None
                    or current.lease_expires_at > now
                ):
                    return current
                row = self._connection.execute(
                    update(analysis_runs)
                    .where(
                        analysis_runs.c.id == current.id,
                        analysis_runs.c.status == "running",
                        analysis_runs.c.lease_expires_at <= now,
                    )
                    .values(
                        created_at=now,
                        lease_expires_at=now + ANALYSIS_LEASE,
                    )
                    .returning(*analysis_runs.c)
                ).mappings().one()
                return AnalysisRunProjection(**row)
            row = self._connection.execute(
                update(analysis_runs)
                .where(
                    analysis_runs.c.id == current.id,
                    analysis_runs.c.status == "failed",
                )
                .values(
                    status="running",
                    failure_code=None,
                    completed_at=None,
                    created_at=now,
                    lease_expires_at=now + ANALYSIS_LEASE,
                )
                .returning(*analysis_runs.c)
            ).mappings().one()
            return AnalysisRunProjection(**row)
        row = self._connection.execute(
            analysis_runs.insert()
            .values(
                id=plan.run_id,
                workspace_id=plan.workspace_id,
                dataset_version_id=plan.dataset_version_id,
                analysis_kind=plan.kind,
                algorithm_version=plan.algorithm_version,
                input_hash=plan.input_hash,
                scope=dict(plan.scope),
                scope_hash=plan.scope_hash,
                status="running",
                failure_code=None,
                created_at=now,
                lease_expires_at=now + ANALYSIS_LEASE,
                completed_at=None,
            )
            .returning(*analysis_runs.c)
        ).mappings().one()
        return AnalysisRunProjection(**row)

    def fail(self, run_id: UUID, failure_code: str, now: datetime) -> None:
        self._connection.execute(
            update(analysis_runs)
            .where(
                analysis_runs.c.id == run_id,
                analysis_runs.c.status == "running",
            )
            .values(
                status="failed",
                failure_code=failure_code,
                lease_expires_at=None,
                completed_at=now,
            )
        )

    def complete(
        self,
        *,
        plan,
        storage_object_id: UUID,
        snapshot_sha256: str,
        dependency_ids: tuple[tuple[UUID, str], ...],
        evidence: tuple[object, ...],
        now: datetime,
    ) -> tuple[AnalysisRunProjection, AnalysisArtifactProjection]:
        for dataset_artifact_id, artifact_sha256 in dependency_ids:
            self._connection.execute(
                analysis_dependencies.insert().values(
                    id=uuid4(),
                    run_id=plan.run_id,
                    dataset_artifact_id=dataset_artifact_id,
                    artifact_sha256=artifact_sha256,
                    created_at=now,
                )
            )
        artifact_row = self._connection.execute(
            analysis_artifacts.insert()
            .values(
                id=uuid4(),
                run_id=plan.run_id,
                storage_object_id=storage_object_id,
                snapshot_sha256=snapshot_sha256,
                media_type="application/json",
                created_at=now,
            )
            .returning(*analysis_artifacts.c)
        ).mappings().one()
        for item in evidence:
            self._connection.execute(
                evidence_items.insert().values(
                    id=uuid4(),
                    run_id=plan.run_id,
                    alias=item.alias,
                    evidence_state=item.evidence_state,
                    formula=item.formula,
                    source_refs=list(item.source_roles),
                    created_at=now,
                )
            )
        run_row = self._connection.execute(
            update(analysis_runs)
            .where(
                analysis_runs.c.id == plan.run_id,
                analysis_runs.c.status == "running",
            )
            .values(
                status="completed",
                completed_at=now,
                lease_expires_at=None,
            )
            .returning(*analysis_runs.c)
        ).mappings().one()
        return AnalysisRunProjection(**run_row), AnalysisArtifactProjection(**artifact_row)

    def get_artifact(self, run_id: UUID) -> AnalysisArtifactProjection | None:
        row = self._connection.execute(
            select(*analysis_artifacts.c).where(analysis_artifacts.c.run_id == run_id)
        ).mappings().one_or_none()
        return AnalysisArtifactProjection(**row) if row is not None else None

    def get_evidence(
        self,
        run_id: UUID,
        evidence_id: UUID | None = None,
    ) -> tuple[EvidenceProjection, ...]:
        statement = select(*evidence_items.c).where(evidence_items.c.run_id == run_id)
        if evidence_id is not None:
            statement = statement.where(evidence_items.c.id == evidence_id)
        rows = self._connection.execute(
            statement.order_by(evidence_items.c.alias, evidence_items.c.id)
        ).mappings()
        return tuple(EvidenceProjection(**row) for row in rows)
