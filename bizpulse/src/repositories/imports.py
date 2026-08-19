"""Revisioned PostgreSQL import-workflow authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Connection, select, update

from src.db.schema import import_workflows, upload_records


@dataclass(frozen=True, slots=True)
class ImportWorkflowProjection:
    id: UUID
    workspace_id: str
    status: str
    revision: int
    source_confirmed_synthetic: bool
    source_kind: str
    base_dataset_version_id: UUID | None
    failure_code: str | None
    created_at: datetime
    updated_at: datetime
    committed_at: datetime | None


@dataclass(frozen=True, slots=True)
class UploadRecordProjection:
    id: UUID
    workflow_id: UUID
    storage_object_id: UUID
    source_filename: str
    media_type: str
    size_bytes: int
    sha256: str
    status: str
    adapter_id: str | None
    adapter_version: str | None
    source_role: str | None
    recognition: dict[str, object] | None
    mapping: dict[str, object] | None
    mapping_revision: int
    assigned_store_id: str | None
    quality_report: dict[str, object] | None
    candidate_storage_object_id: UUID | None
    standardized_at: datetime | None
    created_at: datetime


class ImportRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create_workflow(
        self,
        *,
        workspace_id: str,
        source_confirmed_synthetic: bool,
        source_kind: str = "legacy_synthetic",
        base_dataset_version_id: UUID | None = None,
        now: datetime,
        workflow_id: UUID | None = None,
    ) -> ImportWorkflowProjection:
        row = self._connection.execute(
            import_workflows.insert()
            .values(
                id=workflow_id or uuid4(),
                workspace_id=workspace_id,
                status="created",
                revision=0,
                source_confirmed_synthetic=source_confirmed_synthetic,
                source_kind=source_kind,
                base_dataset_version_id=base_dataset_version_id,
                failure_code=None,
                created_at=now,
                updated_at=now,
                committed_at=None,
            )
            .returning(*import_workflows.c)
        ).mappings().one()
        return ImportWorkflowProjection(**row)

    def get_workflow(self, workflow_id: UUID) -> ImportWorkflowProjection | None:
        row = self._connection.execute(
            select(*import_workflows.c).where(import_workflows.c.id == workflow_id)
        ).mappings().one_or_none()
        return ImportWorkflowProjection(**row) if row is not None else None

    def get_workspace_workflow(
        self,
        workspace_id: str,
        workflow_id: UUID,
    ) -> ImportWorkflowProjection | None:
        row = self._connection.execute(
            select(*import_workflows.c).where(
                import_workflows.c.id == workflow_id,
                import_workflows.c.workspace_id == workspace_id,
            )
        ).mappings().one_or_none()
        return ImportWorkflowProjection(**row) if row is not None else None

    def transition_workflow(
        self,
        workflow_id: UUID,
        *,
        expected_revision: int,
        status: str,
        now: datetime,
        failure_code: str | None = None,
        committed_at: datetime | None = None,
    ) -> ImportWorkflowProjection | None:
        row = self._connection.execute(
            update(import_workflows)
            .where(
                import_workflows.c.id == workflow_id,
                import_workflows.c.revision == expected_revision,
            )
            .values(
                status=status,
                revision=import_workflows.c.revision + 1,
                failure_code=failure_code,
                updated_at=now,
                committed_at=committed_at,
            )
            .returning(*import_workflows.c)
        ).mappings().one_or_none()
        return ImportWorkflowProjection(**row) if row is not None else None

    def create_upload(
        self,
        *,
        workflow_id: UUID,
        storage_object_id: UUID,
        source_filename: str,
        media_type: str,
        size_bytes: int,
        sha256: str,
        now: datetime,
        upload_id: UUID | None = None,
    ) -> UploadRecordProjection:
        row = self._connection.execute(
            upload_records.insert()
            .values(
                id=upload_id or uuid4(),
                workflow_id=workflow_id,
                storage_object_id=storage_object_id,
                source_filename=source_filename,
                media_type=media_type,
                size_bytes=size_bytes,
                sha256=sha256,
                status="staged",
                mapping_revision=0,
                assigned_store_id=None,
                created_at=now,
            )
            .returning(*upload_records.c)
        ).mappings().one()
        return UploadRecordProjection(**row)

    def list_uploads(self, workflow_id: UUID) -> tuple[UploadRecordProjection, ...]:
        rows = self._connection.execute(
            select(*upload_records.c)
            .where(upload_records.c.workflow_id == workflow_id)
            .order_by(upload_records.c.created_at, upload_records.c.id)
        ).mappings()
        return tuple(UploadRecordProjection(**row) for row in rows)

    def get_upload(
        self,
        workflow_id: UUID,
        upload_id: UUID,
    ) -> UploadRecordProjection | None:
        row = self._connection.execute(
            select(*upload_records.c).where(
                upload_records.c.id == upload_id,
                upload_records.c.workflow_id == workflow_id,
            )
        ).mappings().one_or_none()
        return UploadRecordProjection(**row) if row is not None else None

    def find_upload_by_sha256(
        self,
        workflow_id: UUID,
        sha256: str,
    ) -> UploadRecordProjection | None:
        row = self._connection.execute(
            select(*upload_records.c).where(
                upload_records.c.workflow_id == workflow_id,
                upload_records.c.sha256 == sha256,
            )
        ).mappings().one_or_none()
        return UploadRecordProjection(**row) if row is not None else None

    def set_recognition(
        self,
        workflow_id: UUID,
        upload_id: UUID,
        *,
        adapter_id: str,
        adapter_version: str,
        source_role: str,
        recognition: dict[str, object],
    ) -> UploadRecordProjection | None:
        row = self._connection.execute(
            update(upload_records)
            .where(
                upload_records.c.id == upload_id,
                upload_records.c.workflow_id == workflow_id,
                upload_records.c.status == "staged",
            )
            .values(
                status="recognized",
                adapter_id=adapter_id,
                adapter_version=adapter_version,
                source_role=source_role,
                recognition=recognition,
            )
            .returning(*upload_records.c)
        ).mappings().one_or_none()
        return UploadRecordProjection(**row) if row is not None else None

    def set_mapping(
        self,
        workflow_id: UUID,
        upload_id: UUID,
        *,
        expected_mapping_revision: int,
        mapping: dict[str, str],
        assigned_store_id: str | None = None,
    ) -> UploadRecordProjection | None:
        row = self._connection.execute(
            update(upload_records)
            .where(
                upload_records.c.id == upload_id,
                upload_records.c.workflow_id == workflow_id,
                upload_records.c.status == "recognized",
                upload_records.c.mapping_revision == expected_mapping_revision,
            )
            .values(
                mapping=mapping,
                mapping_revision=upload_records.c.mapping_revision + 1,
                assigned_store_id=assigned_store_id,
            )
            .returning(*upload_records.c)
        ).mappings().one_or_none()
        return UploadRecordProjection(**row) if row is not None else None

    def set_candidate(
        self,
        workflow_id: UUID,
        upload_id: UUID,
        *,
        candidate_storage_object_id: UUID,
        quality_report: dict[str, object],
        standardized_at: datetime,
    ) -> UploadRecordProjection | None:
        row = self._connection.execute(
            update(upload_records)
            .where(
                upload_records.c.id == upload_id,
                upload_records.c.workflow_id == workflow_id,
                upload_records.c.status == "recognized",
                upload_records.c.mapping.is_not(None),
            )
            .values(
                status="accepted",
                candidate_storage_object_id=candidate_storage_object_id,
                quality_report=quality_report,
                standardized_at=standardized_at,
            )
            .returning(*upload_records.c)
        ).mappings().one_or_none()
        return UploadRecordProjection(**row) if row is not None else None

    def mark_upload_deleted(
        self,
        workflow_id: UUID,
        upload_id: UUID,
    ) -> None:
        changed = self._connection.execute(
            update(upload_records)
            .where(
                upload_records.c.id == upload_id,
                upload_records.c.workflow_id == workflow_id,
                upload_records.c.status == "accepted",
            )
            .values(status="deleted")
        ).rowcount
        if changed != 1:
            raise RuntimeError("upload_not_accepted")
