"""Bounded read queries for the version-aware BP data library."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection, select

from src.db.schema import (
    analysis_runs,
    dataset_artifacts,
    dataset_versions,
    import_workflows,
    public_releases,
    upload_records,
)


class LibraryRepository:
    def __init__(self, connection: Connection, workspace_id: str) -> None:
        self._connection = connection
        self._workspace_id = workspace_id

    def list_versions(self, *, limit: int = 50):
        return tuple(
            self._connection.execute(
                select(*dataset_versions.c)
                .where(dataset_versions.c.workspace_id == self._workspace_id)
                .order_by(
                    dataset_versions.c.created_at.desc(),
                    dataset_versions.c.id,
                )
                .limit(limit)
            ).mappings()
        )

    def get_version(self, version_id: UUID):
        return self._connection.execute(
            select(*dataset_versions.c).where(
                dataset_versions.c.workspace_id == self._workspace_id,
                dataset_versions.c.id == version_id,
            )
        ).mappings().one_or_none()

    def current_release_version_id(self) -> UUID | None:
        return self._connection.scalar(
            select(public_releases.c.dataset_version_id).where(
                public_releases.c.workspace_id == self._workspace_id,
                public_releases.c.is_active.is_(True),
            )
        )

    def released_version_ids(self) -> frozenset[UUID]:
        return frozenset(
            self._connection.scalars(
                select(public_releases.c.dataset_version_id).where(
                    public_releases.c.workspace_id == self._workspace_id
                )
            )
        )

    def artifacts(self, version_id: UUID, *, limit: int = 32):
        return tuple(
            self._connection.execute(
                select(*dataset_artifacts.c)
                .where(dataset_artifacts.c.dataset_version_id == version_id)
                .order_by(dataset_artifacts.c.artifact_kind, dataset_artifacts.c.id)
                .limit(limit)
            ).mappings()
        )

    def uploads(self, workflow_id: UUID | None, *, limit: int = 20):
        if workflow_id is None:
            return ()
        return tuple(
            self._connection.execute(
                select(
                    upload_records.c.source_filename,
                    upload_records.c.source_role,
                    upload_records.c.status,
                    upload_records.c.adapter_id,
                    upload_records.c.quality_report,
                    import_workflows.c.source_kind,
                )
                .join(
                    import_workflows,
                    import_workflows.c.id == upload_records.c.workflow_id,
                )
                .where(
                    import_workflows.c.workspace_id == self._workspace_id,
                    upload_records.c.workflow_id == workflow_id,
                )
                .order_by(upload_records.c.created_at, upload_records.c.id)
                .limit(limit)
            ).mappings()
        )

    def completed_analysis_kinds(self, version_id: UUID) -> tuple[str, ...]:
        return tuple(
            self._connection.scalars(
                select(analysis_runs.c.analysis_kind)
                .where(
                    analysis_runs.c.workspace_id == self._workspace_id,
                    analysis_runs.c.dataset_version_id == version_id,
                    analysis_runs.c.status == "completed",
                )
                .distinct()
                .order_by(analysis_runs.c.analysis_kind)
            )
        )
