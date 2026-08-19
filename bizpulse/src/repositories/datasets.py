"""Append-only dataset versions and historical public release pointers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Connection, func, select, update

from src.db.schema import (
    dataset_artifacts,
    dataset_series,
    dataset_versions,
    import_workflows,
    public_releases,
    upload_records,
)


@dataclass(frozen=True, slots=True)
class DatasetSeriesProjection:
    id: UUID
    workspace_id: str
    name: str
    current_version_id: UUID | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DatasetVersionProjection:
    id: UUID
    series_id: UUID
    workspace_id: str
    source_workflow_id: UUID | None
    base_version_id: UUID | None
    version_number: int
    status: str
    schema_version: str
    content_sha256: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PublicReleaseProjection:
    id: UUID
    workspace_id: str
    dataset_version_id: UUID
    is_active: bool
    released_at: datetime
    retired_at: datetime | None


@dataclass(frozen=True, slots=True)
class DatasetArtifactProjection:
    id: UUID
    dataset_version_id: UUID
    storage_object_id: UUID
    artifact_kind: str
    sha256: str
    created_at: datetime


class DatasetRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create_series(
        self,
        *,
        workspace_id: str,
        name: str,
        now: datetime,
        series_id: UUID | None = None,
    ) -> DatasetSeriesProjection:
        row = self._connection.execute(
            dataset_series.insert()
            .values(
                id=series_id or uuid4(),
                workspace_id=workspace_id,
                name=name,
                current_version_id=None,
                created_at=now,
            )
            .returning(*dataset_series.c)
        ).mappings().one()
        return DatasetSeriesProjection(**row)

    def get_series(self, series_id: UUID) -> DatasetSeriesProjection | None:
        row = self._connection.execute(
            select(*dataset_series.c).where(dataset_series.c.id == series_id)
        ).mappings().one_or_none()
        return DatasetSeriesProjection(**row) if row is not None else None

    def get_series_by_name(
        self,
        workspace_id: str,
        name: str,
        *,
        for_update: bool = False,
    ) -> DatasetSeriesProjection | None:
        statement = select(*dataset_series.c).where(
            dataset_series.c.workspace_id == workspace_id,
            dataset_series.c.name == name,
        )
        if for_update:
            statement = statement.with_for_update()
        row = self._connection.execute(statement).mappings().one_or_none()
        return DatasetSeriesProjection(**row) if row is not None else None

    def next_version_number(self, series_id: UUID) -> int:
        self._connection.execute(
            select(dataset_series.c.id)
            .where(dataset_series.c.id == series_id)
            .with_for_update()
        ).scalar_one()
        current = self._connection.scalar(
            select(func.max(dataset_versions.c.version_number)).where(
                dataset_versions.c.series_id == series_id
            )
        )
        return int(current or 0) + 1

    def create_version(
        self,
        *,
        series_id: UUID,
        workspace_id: str,
        source_workflow_id: UUID | None,
        version_number: int,
        schema_version: str,
        content_sha256: str,
        now: datetime,
        version_id: UUID | None = None,
        base_version_id: UUID | None = None,
    ) -> DatasetVersionProjection:
        row = self._connection.execute(
            dataset_versions.insert()
            .values(
                id=version_id or uuid4(),
                series_id=series_id,
                workspace_id=workspace_id,
                source_workflow_id=source_workflow_id,
                base_version_id=base_version_id,
                version_number=version_number,
                status="complete",
                schema_version=schema_version,
                content_sha256=content_sha256,
                created_at=now,
            )
            .returning(*dataset_versions.c)
        ).mappings().one()
        return DatasetVersionProjection(**row)

    def find_version_by_content(
        self,
        workspace_id: str,
        content_sha256: str,
    ) -> DatasetVersionProjection | None:
        row = self._connection.execute(
            select(*dataset_versions.c).where(
                dataset_versions.c.workspace_id == workspace_id,
                dataset_versions.c.content_sha256 == content_sha256,
            )
        ).mappings().one_or_none()
        return DatasetVersionProjection(**row) if row is not None else None

    def get_version(self, version_id: UUID) -> DatasetVersionProjection | None:
        row = self._connection.execute(
            select(*dataset_versions.c).where(dataset_versions.c.id == version_id)
        ).mappings().one_or_none()
        return DatasetVersionProjection(**row) if row is not None else None

    def find_version_by_workflow(
        self,
        workspace_id: str,
        workflow_id: UUID,
    ) -> DatasetVersionProjection | None:
        row = self._connection.execute(
            select(*dataset_versions.c).where(
                dataset_versions.c.workspace_id == workspace_id,
                dataset_versions.c.source_workflow_id == workflow_id,
            )
        ).mappings().one_or_none()
        return DatasetVersionProjection(**row) if row is not None else None

    def list_versions(
        self,
        workspace_id: str,
    ) -> tuple[DatasetVersionProjection, ...]:
        rows = self._connection.execute(
            select(*dataset_versions.c)
            .where(dataset_versions.c.workspace_id == workspace_id)
            .order_by(dataset_versions.c.created_at.desc(), dataset_versions.c.id)
        ).mappings()
        return tuple(DatasetVersionProjection(**row) for row in rows)

    def create_artifact(
        self,
        *,
        dataset_version_id: UUID,
        storage_object_id: UUID,
        artifact_kind: str,
        sha256: str,
        now: datetime,
        artifact_id: UUID | None = None,
    ) -> DatasetArtifactProjection:
        row = self._connection.execute(
            dataset_artifacts.insert()
            .values(
                id=artifact_id or uuid4(),
                dataset_version_id=dataset_version_id,
                storage_object_id=storage_object_id,
                artifact_kind=artifact_kind,
                sha256=sha256,
                created_at=now,
            )
            .returning(*dataset_artifacts.c)
        ).mappings().one()
        return DatasetArtifactProjection(**row)

    def list_artifacts(
        self,
        dataset_version_id: UUID,
    ) -> tuple[DatasetArtifactProjection, ...]:
        rows = self._connection.execute(
            select(*dataset_artifacts.c)
            .where(dataset_artifacts.c.dataset_version_id == dataset_version_id)
            .order_by(dataset_artifacts.c.artifact_kind, dataset_artifacts.c.id)
        ).mappings()
        return tuple(DatasetArtifactProjection(**row) for row in rows)

    def point_series_at(self, series_id: UUID, version_id: UUID) -> None:
        changed = self._connection.execute(
            update(dataset_series)
            .where(dataset_series.c.id == series_id)
            .values(current_version_id=version_id)
        ).rowcount
        if changed != 1:
            raise RuntimeError("dataset_series_not_found")

    def activate_release(
        self,
        *,
        workspace_id: str,
        dataset_version_id: UUID,
        now: datetime,
        release_id: UUID | None = None,
    ) -> PublicReleaseProjection:
        self._connection.execute(
            update(public_releases)
            .where(
                public_releases.c.workspace_id == workspace_id,
                public_releases.c.is_active.is_(True),
            )
            .values(is_active=False, retired_at=now)
        )
        row = self._connection.execute(
            public_releases.insert()
            .values(
                id=release_id or uuid4(),
                workspace_id=workspace_id,
                dataset_version_id=dataset_version_id,
                is_active=True,
                released_at=now,
                retired_at=None,
            )
            .returning(*public_releases.c)
        ).mappings().one()
        return PublicReleaseProjection(**row)

    def list_releases(
        self,
        workspace_id: str,
    ) -> tuple[PublicReleaseProjection, ...]:
        rows = self._connection.execute(
            select(*public_releases.c)
            .where(public_releases.c.workspace_id == workspace_id)
            .order_by(
                public_releases.c.released_at,
                public_releases.c.is_active,
                public_releases.c.id,
            )
        ).mappings()
        return tuple(PublicReleaseProjection(**row) for row in rows)

    def find_release_for_version(
        self,
        workspace_id: str,
        dataset_version_id: UUID,
    ) -> PublicReleaseProjection | None:
        row = self._connection.execute(
            select(*public_releases.c)
            .where(
                public_releases.c.workspace_id == workspace_id,
                public_releases.c.dataset_version_id == dataset_version_id,
            )
            .order_by(public_releases.c.released_at.desc(), public_releases.c.id)
            .limit(1)
        ).mappings().one_or_none()
        return PublicReleaseProjection(**row) if row is not None else None

    def current_release(
        self,
        workspace_id: str,
        *,
        for_update: bool = False,
    ) -> PublicReleaseProjection | None:
        statement = select(*public_releases.c).where(
                public_releases.c.workspace_id == workspace_id,
                public_releases.c.is_active.is_(True),
            )
        if for_update:
            statement = statement.with_for_update()
        row = self._connection.execute(statement).mappings().one_or_none()
        return PublicReleaseProjection(**row) if row is not None else None

    def is_release_eligible(self, version: DatasetVersionProjection) -> bool:
        if version.status != "complete":
            return False
        artifact_kinds = set(
            self._connection.scalars(
                select(dataset_artifacts.c.artifact_kind).where(
                    dataset_artifacts.c.dataset_version_id == version.id
                )
            )
        )
        if version.source_workflow_id is None:
            return (
                version.schema_version == "synthetic.v1"
                and {"manifest", "analysis_bundle"} <= artifact_kinds
            )
        if version.schema_version != "canonical.import.v1" or not artifact_kinds:
            return False
        workflow = self._connection.execute(
            select(
                import_workflows.c.status,
                import_workflows.c.source_confirmed_synthetic,
                import_workflows.c.source_kind,
            ).where(
                import_workflows.c.id == version.source_workflow_id,
                import_workflows.c.workspace_id == version.workspace_id,
            )
        ).one_or_none()
        if (
            workflow is None
            or workflow.status != "committed"
        ):
            return False
        valid_source = (
            workflow.source_kind == "legacy_synthetic"
            and workflow.source_confirmed_synthetic is True
        ) or (
            workflow.source_kind == "operator_upload"
            and workflow.source_confirmed_synthetic is False
        )
        if not valid_source:
            return False
        upload_counts = self._connection.execute(
            select(
                func.count(upload_records.c.id),
                func.count(upload_records.c.id).filter(
                    upload_records.c.status.in_(("accepted", "deleted")),
                    upload_records.c.quality_report.is_not(None),
                    upload_records.c.candidate_storage_object_id.is_not(None),
                ),
            ).where(upload_records.c.workflow_id == version.source_workflow_id)
        ).one()
        return int(upload_counts[0]) > 0 and upload_counts[0] == upload_counts[1]
