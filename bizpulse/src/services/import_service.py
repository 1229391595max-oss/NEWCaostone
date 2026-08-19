"""Revisioned, bounded, PostgreSQL/Blob-backed synthetic import workflow."""

from __future__ import annotations

import hashlib
import hmac
import json
import csv
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from io import BytesIO, StringIO
from pathlib import PurePath
from time import monotonic, sleep
from uuid import UUID, uuid5

from sqlalchemy import Engine, text

from src.adapters import AdapterRegistry
from src.adapters.protocol import StandardizedArtifact
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.datasets import DatasetRepository
from src.repositories.idempotency import IdempotencyRepository
from src.repositories.imports import (
    ImportRepository,
    ImportWorkflowProjection,
    UploadRecordProjection,
)
from src.repositories.storage_objects import (
    StorageObjectProjection,
    StorageObjectRepository,
)
from src.services.canonical_contracts import (
    DedupeConflict,
    DedupeSummary,
    StoreDescriptor,
)
from src.services.canonical_dataset_assembler import (
    AssemblyResult,
    CanonicalDatasetAssembler,
    CanonicalSource,
    CanonicalSourceInvalid,
)
from src.storage.keys import dataset_object_key
from src.storage.protocol import AvailableObject, StagedObject, WorkflowStorage
from src.synthetic.boundary import (
    SyntheticSourceBoundaryError,
    validate_safe_import_records,
)

IMPORT_NAMESPACE = UUID("db1beaf0-3c53-57fb-ac4b-42f9c993ea02")
SERIES_NAME = "synthetic-main"
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_CANONICAL_BYTES = 16 * 1024 * 1024
UPLOAD_TTL = timedelta(hours=2)
IDEMPOTENCY_TTL = timedelta(days=30)
CANONICAL_MEDIA_TYPE = "application/json"
OPERATION_LOCK_TIMEOUT_SECONDS = 5.0
TRY_ADVISORY_LOCK = text("SELECT pg_try_advisory_lock(:lock_id)")
RELEASE_ADVISORY_LOCK = text("SELECT pg_advisory_unlock(:lock_id)")


class ImportServiceError(RuntimeError):
    code = "IMPORT_SERVICE_ERROR"


class ImportNotFound(ImportServiceError):
    code = "RESOURCE_NOT_FOUND"


class WorkflowRevisionConflict(ImportServiceError):
    code = "WORKFLOW_REVISION_CONFLICT"


class IdempotencyConflict(ImportServiceError):
    code = "IDEMPOTENCY_CONFLICT"


class WorkflowNotReady(ImportServiceError):
    code = "WORKFLOW_NOT_READY"


class ImportDedupeConflict(WorkflowNotReady):
    code = "IMPORT_DEDUPE_CONFLICT"


class WorkflowCommitBusy(ImportServiceError):
    code = "WORKFLOW_COMMIT_BUSY"


class UploadTooLarge(ImportServiceError):
    code = "UPLOAD_TOO_LARGE"


class UploadInvalid(ImportServiceError):
    code = "UPLOAD_INVALID"


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    workflow: ImportWorkflowProjection
    replayed: bool


@dataclass(frozen=True, slots=True)
class UploadMutationResult:
    workflow: ImportWorkflowProjection
    upload: UploadRecordProjection
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class PreviewResult:
    workflow_id: UUID
    upload_id: UUID
    candidate_sha256: str
    records: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class CommitPlan:
    workflow_id: UUID
    expected_revision: int
    ready: bool
    candidate_sha256s: tuple[str, ...]
    content_sha256: str | None
    dedupe: DedupeSummary
    conflicts: tuple[DedupeConflict, ...]
    conflicts_truncated: bool
    conflict_download_url: str


@dataclass(frozen=True, slots=True)
class CommitResult:
    workflow_id: UUID
    dataset_version_id: UUID
    version_number: int
    content_sha256: str
    created: bool


@dataclass(frozen=True, slots=True)
class WorkflowAssembly:
    workflow: ImportWorkflowProjection
    uploads: tuple[UploadRecordProjection, ...]
    candidate_records: tuple[StorageObjectProjection, ...]
    result: AssemblyResult


@dataclass(frozen=True, slots=True)
class MergedForCommit:
    storage_object_id: UUID
    staged: StagedObject
    available: AvailableObject


def _workflow_projection(workflow: ImportWorkflowProjection) -> dict[str, object]:
    return {
        "id": str(workflow.id),
        "workspace_id": workflow.workspace_id,
        "status": workflow.status,
        "revision": workflow.revision,
        "source_confirmed_synthetic": workflow.source_confirmed_synthetic,
        "source_kind": workflow.source_kind,
        "base_dataset_version_id": (
            str(workflow.base_dataset_version_id)
            if workflow.base_dataset_version_id is not None
            else None
        ),
        "failure_code": workflow.failure_code,
        "created_at": workflow.created_at.isoformat(),
        "updated_at": workflow.updated_at.isoformat(),
        "committed_at": (
            workflow.committed_at.isoformat()
            if workflow.committed_at is not None
            else None
        ),
    }


def _upload_projection(upload: UploadRecordProjection) -> dict[str, object]:
    return {
        "id": str(upload.id),
        "workflow_id": str(upload.workflow_id),
        "storage_object_id": str(upload.storage_object_id),
        "source_filename": upload.source_filename,
        "media_type": upload.media_type,
        "size_bytes": upload.size_bytes,
        "sha256": upload.sha256,
        "status": upload.status,
        "adapter_id": upload.adapter_id,
        "adapter_version": upload.adapter_version,
        "source_role": upload.source_role,
        "recognition": upload.recognition,
        "mapping": upload.mapping,
        "mapping_revision": upload.mapping_revision,
        "assigned_store_id": upload.assigned_store_id,
        "quality_report": upload.quality_report,
        "candidate_storage_object_id": (
            str(upload.candidate_storage_object_id)
            if upload.candidate_storage_object_id is not None
            else None
        ),
        "standardized_at": (
            upload.standardized_at.isoformat()
            if upload.standardized_at is not None
            else None
        ),
        "created_at": upload.created_at.isoformat(),
    }


def _workflow_from_projection(payload: dict[str, object]) -> ImportWorkflowProjection:
    return ImportWorkflowProjection(
        id=UUID(str(payload["id"])),
        workspace_id=str(payload["workspace_id"]),
        status=str(payload["status"]),
        revision=int(payload["revision"]),
        source_confirmed_synthetic=bool(payload["source_confirmed_synthetic"]),
        source_kind=str(payload.get("source_kind", "legacy_synthetic")),
        base_dataset_version_id=(
            UUID(str(payload["base_dataset_version_id"]))
            if payload.get("base_dataset_version_id") is not None
            else None
        ),
        failure_code=(
            str(payload["failure_code"])
            if payload["failure_code"] is not None
            else None
        ),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        updated_at=datetime.fromisoformat(str(payload["updated_at"])),
        committed_at=(
            datetime.fromisoformat(str(payload["committed_at"]))
            if payload["committed_at"] is not None
            else None
        ),
    )


def _upload_from_projection(payload: dict[str, object]) -> UploadRecordProjection:
    return UploadRecordProjection(
        id=UUID(str(payload["id"])),
        workflow_id=UUID(str(payload["workflow_id"])),
        storage_object_id=UUID(str(payload["storage_object_id"])),
        source_filename=str(payload["source_filename"]),
        media_type=str(payload["media_type"]),
        size_bytes=int(payload["size_bytes"]),
        sha256=str(payload["sha256"]),
        status=str(payload["status"]),
        adapter_id=(
            str(payload["adapter_id"])
            if payload["adapter_id"] is not None
            else None
        ),
        adapter_version=(
            str(payload["adapter_version"])
            if payload["adapter_version"] is not None
            else None
        ),
        source_role=(
            str(payload["source_role"])
            if payload["source_role"] is not None
            else None
        ),
        recognition=(
            dict(payload["recognition"])
            if isinstance(payload["recognition"], dict)
            else None
        ),
        mapping=(
            dict(payload["mapping"])
            if isinstance(payload["mapping"], dict)
            else None
        ),
        mapping_revision=int(payload["mapping_revision"]),
        assigned_store_id=(
            str(payload["assigned_store_id"])
            if payload.get("assigned_store_id") is not None
            else None
        ),
        quality_report=(
            dict(payload["quality_report"])
            if isinstance(payload["quality_report"], dict)
            else None
        ),
        candidate_storage_object_id=(
            UUID(str(payload["candidate_storage_object_id"]))
            if payload["candidate_storage_object_id"] is not None
            else None
        ),
        standardized_at=(
            datetime.fromisoformat(str(payload["standardized_at"]))
            if payload["standardized_at"] is not None
            else None
        ),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
    )


class ImportService:
    def __init__(
        self,
        *,
        engine: Engine,
        storage: WorkflowStorage,
        workspace_id: str,
        idempotency_pepper: str,
        adapter_registry: AdapterRegistry | None = None,
        clock=None,
        max_upload_bytes: int = MAX_UPLOAD_BYTES,
    ) -> None:
        self._engine = engine
        self._storage = storage
        self._workspace_id = workspace_id
        self._pepper = idempotency_pepper.encode()
        self._adapters = adapter_registry or AdapterRegistry()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_upload_bytes = max_upload_bytes

    def create_workflow(
        self,
        source_confirmed_synthetic: bool | None = None,
        idempotency_key: str | None = None,
    ) -> WorkflowResult:
        if source_confirmed_synthetic is False:
            raise SyntheticSourceBoundaryError(
                field="source_confirmed_synthetic",
                rule="invalid_legacy_confirmation",
            )
        if idempotency_key is None:
            raise IdempotencyConflict
        source_kind = (
            "legacy_synthetic"
            if source_confirmed_synthetic is True
            else "operator_upload"
        )
        key_hash = self._key_hash(idempotency_key)
        with self._operation_lock(
            f"{self._workspace_id}:create-workflow:{key_hash.hex()}",
            IdempotencyConflict,
        ):
            return self._create_workflow_serialized(key_hash, source_kind)

    def _create_workflow_serialized(
        self,
        key_hash: bytes,
        source_kind: str,
    ) -> WorkflowResult:
        request_hash = hashlib.sha256(f"source_kind={source_kind}".encode()).digest()
        workflow_id = uuid5(IMPORT_NAMESPACE, f"workflow:{key_hash.hex()}")
        now = self._clock()
        with PostgresUnitOfWork(self._engine) as uow:
            imports = ImportRepository(uow.connection)
            datasets = DatasetRepository(uow.connection)
            receipts = IdempotencyRepository(uow.connection)
            disposition = receipts.check(
                scope_type="workspace",
                scope_id=self._workspace_id,
                operation="create_import_workflow",
                key_hash=key_hash,
                request_hash=request_hash,
            )
            if disposition == "conflict":
                raise IdempotencyConflict
            if disposition == "in_progress":
                raise IdempotencyConflict
            if disposition == "replay":
                projection = receipts.replay_projection(
                    scope_type="workspace",
                    scope_id=self._workspace_id,
                    operation="create_import_workflow",
                    key_hash=key_hash,
                    request_hash=request_hash,
                )
                if projection is None or not isinstance(
                    projection.get("workflow"),
                    dict,
                ):
                    raise IdempotencyConflict
                return WorkflowResult(
                    _workflow_from_projection(projection["workflow"]),
                    replayed=bool(projection.get("replayed", False)),
                )
            series = datasets.get_series_by_name(self._workspace_id, SERIES_NAME)
            workflow = imports.create_workflow(
                workspace_id=self._workspace_id,
                source_confirmed_synthetic=source_kind == "legacy_synthetic",
                source_kind=source_kind,
                base_dataset_version_id=(
                    series.current_version_id if series is not None else None
                ),
                now=now,
                workflow_id=workflow_id,
            )
            response_projection = {
                "workflow": _workflow_projection(workflow),
                "replayed": False,
            }
            receipts.record_succeeded(
                scope_type="workspace",
                scope_id=self._workspace_id,
                operation="create_import_workflow",
                key_hash=key_hash,
                request_hash=request_hash,
                response_status=201,
                response_body_hash=self._request_hash(response_projection),
                response_projection=response_projection,
                now=now,
                expires_at=now + IDEMPOTENCY_TTL,
            )
        return WorkflowResult(workflow, replayed=False)

    def upload(
        self,
        workflow_id: UUID,
        *,
        filename: str,
        media_type: str,
        content: bytes,
        idempotency_key: str,
    ) -> UploadMutationResult:
        self._validate_upload(filename, media_type, content)
        key_hash = self._key_hash(idempotency_key)
        with self._operation_lock(
            f"{self._workspace_id}:upload:{workflow_id}:{key_hash.hex()}",
            IdempotencyConflict,
        ):
            return self._upload_serialized(
                workflow_id,
                filename=filename,
                media_type=media_type,
                content=content,
                key_hash=key_hash,
            )

    def _upload_serialized(
        self,
        workflow_id: UUID,
        *,
        filename: str,
        media_type: str,
        content: bytes,
        key_hash: bytes,
    ) -> UploadMutationResult:
        content_sha256 = hashlib.sha256(content).hexdigest()
        request_hash = self._request_hash(
            {
                "filename": filename,
                "media_type": media_type,
                "size_bytes": len(content),
                "sha256": content_sha256,
            }
        )
        upload_id = uuid5(
            IMPORT_NAMESPACE,
            f"upload:{workflow_id}:{key_hash.hex()}",
        )
        object_id = uuid5(IMPORT_NAMESPACE, f"original:{upload_id}")
        with self._engine.connect() as connection:
            imports = ImportRepository(connection)
            workflow = self._workflow(imports, workflow_id)
            disposition = IdempotencyRepository(connection).check(
                scope_type="workflow",
                scope_id=str(workflow_id),
                operation="upload",
                key_hash=key_hash,
                request_hash=request_hash,
            )
            if disposition == "conflict":
                raise IdempotencyConflict
            if disposition == "in_progress":
                raise IdempotencyConflict
            if disposition == "replay":
                projection = IdempotencyRepository(connection).replay_projection(
                    scope_type="workflow",
                    scope_id=str(workflow_id),
                    operation="upload",
                    key_hash=key_hash,
                    request_hash=request_hash,
                )
                if (
                    projection is None
                    or not isinstance(projection.get("workflow"), dict)
                    or not isinstance(projection.get("upload"), dict)
                ):
                    raise IdempotencyConflict
                return UploadMutationResult(
                    _workflow_from_projection(projection["workflow"]),
                    _upload_from_projection(projection["upload"]),
                    replayed=bool(projection.get("replayed", False)),
                )
            if workflow.status in {"committing", "committed", "rejected", "cancelled"}:
                raise WorkflowNotReady
            if imports.find_upload_by_sha256(workflow_id, content_sha256) is not None:
                raise UploadInvalid("duplicate_upload")

        self._adapters.inspect(
            filename,
            media_type,
            content,
            source_kind=workflow.source_kind,
        )
        staged = self._storage.put_staging(
            BytesIO(content),
            max_bytes=self._max_upload_bytes,
            media_type=media_type,
        )
        now = self._clock()
        try:
            with PostgresUnitOfWork(self._engine) as uow:
                imports = ImportRepository(uow.connection)
                workflow = self._workflow(imports, workflow_id)
                receipts = IdempotencyRepository(uow.connection)
                if (
                    receipts.check(
                        scope_type="workflow",
                        scope_id=str(workflow_id),
                        operation="upload",
                        key_hash=key_hash,
                        request_hash=request_hash,
                    )
                    != "missing"
                ):
                    raise IdempotencyConflict
                storage_record = StorageObjectRepository(
                    uow.connection
                ).create_staging(
                    workspace_id=self._workspace_id,
                    staged=staged,
                    purpose="temporary_upload",
                    now=now,
                    expires_at=now + UPLOAD_TTL,
                    object_id=object_id,
                )
                upload = imports.create_upload(
                    workflow_id=workflow_id,
                    storage_object_id=storage_record.id,
                    source_filename=filename,
                    media_type=media_type,
                    size_bytes=len(content),
                    sha256=content_sha256,
                    now=now,
                    upload_id=upload_id,
                )
                updated = imports.transition_workflow(
                    workflow_id,
                    expected_revision=workflow.revision,
                    status="uploading",
                    now=now,
                )
                if updated is None:
                    raise WorkflowRevisionConflict
                response_projection = {
                    "workflow": _workflow_projection(updated),
                    "upload": _upload_projection(upload),
                    "replayed": False,
                }
                receipts.record_succeeded(
                    scope_type="workflow",
                    scope_id=str(workflow_id),
                    operation="upload",
                    key_hash=key_hash,
                    request_hash=request_hash,
                    response_status=201,
                    response_body_hash=self._request_hash(response_projection),
                    response_projection=response_projection,
                    now=now,
                    expires_at=now + IDEMPOTENCY_TTL,
                )
        except BaseException as primary_error:
            try:
                committed = self._committed_upload(
                    workflow_id=workflow_id,
                    upload_id=upload_id,
                    object_id=object_id,
                    key_hash=key_hash,
                    request_hash=request_hash,
                    staged=staged,
                )
            except Exception:
                primary_error.add_note(
                    "upload_outcome_unknown_staged_object_retained"
                )
                raise primary_error
            if committed is not None:
                return committed
            self._delete_or_schedule_staged(
                staged,
                cleanup_scope=f"failed-upload:{workflow_id}:{upload_id}",
                now=now,
            )
            raise
        return UploadMutationResult(updated, upload)

    def recognize(
        self,
        workflow_id: UUID,
        upload_id: UUID,
        *,
        expected_revision: int,
    ) -> UploadMutationResult:
        workflow, upload, storage_record = self._load_original(
            workflow_id,
            upload_id,
        )
        self._require_revision(workflow, expected_revision)
        with self._storage.open_verified(
            storage_record.object_key,
            storage_record.sha256,
            storage_record.size_bytes,
        ) as opened:
            recognition = self._adapters.inspect(
                upload.source_filename,
                upload.media_type,
                opened.read(),
                source_kind=workflow.source_kind,
            )
        now = self._clock()
        with PostgresUnitOfWork(self._engine) as uow:
            imports = ImportRepository(uow.connection)
            current = self._workflow(imports, workflow_id)
            self._require_revision(current, expected_revision)
            updated_upload = imports.set_recognition(
                workflow_id,
                upload_id,
                adapter_id=recognition.adapter_id,
                adapter_version=recognition.adapter_version,
                source_role=recognition.source_role,
                recognition=recognition.projection(),
            )
            if updated_upload is None:
                raise WorkflowNotReady
            updated_workflow = imports.transition_workflow(
                workflow_id,
                expected_revision=expected_revision,
                status="recognized",
                now=now,
            )
            if updated_workflow is None:
                raise WorkflowRevisionConflict
        return UploadMutationResult(updated_workflow, updated_upload)

    def confirm_mapping(
        self,
        workflow_id: UUID,
        upload_id: UUID,
        *,
        expected_revision: int,
        expected_mapping_revision: int,
        mapping: dict[str, str],
        assigned_store_id: str | None = None,
    ) -> UploadMutationResult:
        workflow, upload, storage_record = self._load_original(
            workflow_id,
            upload_id,
        )
        self._require_revision(workflow, expected_revision)
        if upload.adapter_id is None:
            raise WorkflowNotReady
        with self._storage.open_verified(
            storage_record.object_key,
            storage_record.sha256,
            storage_record.size_bytes,
        ) as opened:
            artifact = self._adapters.standardize(
                upload.adapter_id,
                opened.read(),
                mapping,
                source_kind=workflow.source_kind,
                source_name=upload.source_filename,
            )
        self._validate_store_assignment(
            workflow,
            artifact,
            assigned_store_id=assigned_store_id,
        )
        now = self._clock()
        with PostgresUnitOfWork(self._engine) as uow:
            imports = ImportRepository(uow.connection)
            current = self._workflow(imports, workflow_id)
            self._require_revision(current, expected_revision)
            updated_upload = imports.set_mapping(
                workflow_id,
                upload_id,
                expected_mapping_revision=expected_mapping_revision,
                mapping=mapping,
                assigned_store_id=assigned_store_id,
            )
            if updated_upload is None:
                raise WorkflowRevisionConflict
            updated_workflow = imports.transition_workflow(
                workflow_id,
                expected_revision=expected_revision,
                status="recognized",
                now=now,
            )
            if updated_workflow is None:
                raise WorkflowRevisionConflict
        return UploadMutationResult(updated_workflow, updated_upload)

    def standardize(
        self,
        workflow_id: UUID,
        upload_id: UUID,
        *,
        expected_revision: int,
    ) -> UploadMutationResult:
        workflow, upload, storage_record = self._load_original(
            workflow_id,
            upload_id,
        )
        self._require_revision(workflow, expected_revision)
        if upload.adapter_id is None or upload.mapping is None:
            raise WorkflowNotReady
        with self._storage.open_verified(
            storage_record.object_key,
            storage_record.sha256,
            storage_record.size_bytes,
        ) as opened:
            artifact = self._adapters.standardize(
                upload.adapter_id,
                opened.read(),
                {str(key): str(value) for key, value in upload.mapping.items()},
                source_kind=workflow.source_kind,
                source_name=upload.source_filename,
            )
        if upload.assigned_store_id is not None:
            artifact = self._apply_store_assignment(
                artifact,
                upload.assigned_store_id,
            )
        staged = self._storage.put_staging(
            BytesIO(artifact.content),
            max_bytes=self._max_upload_bytes,
            media_type=CANONICAL_MEDIA_TYPE,
        )
        now = self._clock()
        candidate_id = uuid5(
            IMPORT_NAMESPACE,
            f"candidate:{upload.id}:{upload.mapping_revision}:{staged.sha256}",
        )
        quality = dict(artifact.quality_report)
        quality["sha256"] = staged.sha256
        try:
            with PostgresUnitOfWork(self._engine) as uow:
                imports = ImportRepository(uow.connection)
                current = self._workflow(imports, workflow_id)
                self._require_revision(current, expected_revision)
                StorageObjectRepository(uow.connection).create_staging(
                    workspace_id=self._workspace_id,
                    staged=staged,
                    purpose="temporary_upload",
                    now=now,
                    expires_at=now + UPLOAD_TTL,
                    object_id=candidate_id,
                )
                updated_upload = imports.set_candidate(
                    workflow_id,
                    upload_id,
                    candidate_storage_object_id=candidate_id,
                    quality_report=quality,
                    standardized_at=now,
                )
                if updated_upload is None:
                    raise WorkflowNotReady
                all_ready = all(
                    item.status == "accepted"
                    for item in imports.list_uploads(workflow_id)
                )
                updated_workflow = imports.transition_workflow(
                    workflow_id,
                    expected_revision=expected_revision,
                    status="ready" if all_ready else "recognized",
                    now=now,
                )
                if updated_workflow is None:
                    raise WorkflowRevisionConflict
        except BaseException as primary_error:
            try:
                committed, staged_is_referenced = self._committed_standardization(
                    workflow_id=workflow_id,
                    upload_id=upload_id,
                    candidate_id=candidate_id,
                    staged=staged,
                )
            except Exception:
                primary_error.add_note(
                    "standardization_outcome_unknown_staged_object_retained"
                )
                raise primary_error
            if committed is not None:
                if not staged_is_referenced:
                    self._delete_or_schedule_staged(
                        staged,
                        cleanup_scope=(
                            f"redundant-standardization:{workflow_id}:{upload_id}"
                        ),
                        now=now,
                    )
                return committed
            self._delete_or_schedule_staged(
                staged,
                cleanup_scope=f"failed-standardization:{workflow_id}:{upload_id}",
                now=now,
            )
            raise
        return UploadMutationResult(updated_workflow, updated_upload)

    def preview(
        self,
        workflow_id: UUID,
        upload_id: UUID,
        *,
        limit: int = 10,
    ) -> PreviewResult:
        if type(limit) is not int or not 1 <= limit <= 25:
            raise UploadInvalid("preview_limit_invalid")
        with self._engine.connect() as connection:
            imports = ImportRepository(connection)
            self._workflow(imports, workflow_id)
            upload = imports.get_upload(workflow_id, upload_id)
            if upload is None or upload.candidate_storage_object_id is None:
                raise ImportNotFound
            candidate = StorageObjectRepository(connection).get(
                upload.candidate_storage_object_id
            )
        if candidate is None or upload.quality_report is None:
            raise ImportNotFound
        digest = str(upload.quality_report["sha256"])
        with self._storage.open_verified(
            candidate.object_key,
            digest,
            candidate.size_bytes,
        ) as opened:
            payload = json.load(opened)
        records = tuple(
            record
            for table_records in payload["tables"].values()
            for record in table_records
        )[:limit]
        return PreviewResult(workflow_id, upload_id, digest, records)

    def commit_plan(self, workflow_id: UUID) -> CommitPlan:
        with self._engine.connect() as connection:
            imports = ImportRepository(connection)
            workflow = self._workflow(imports, workflow_id)
            uploads = imports.list_uploads(workflow_id)
        digests = tuple(
            str(upload.quality_report["sha256"])
            for upload in uploads
            if upload.quality_report is not None
        )
        ready = bool(uploads) and all(
            upload.status == "accepted" and upload.candidate_storage_object_id
            for upload in uploads
        )
        if not ready:
            return CommitPlan(
                workflow_id=workflow.id,
                expected_revision=workflow.revision,
                ready=False,
                candidate_sha256s=digests,
                content_sha256=None,
                dedupe=self._empty_dedupe_summary(),
                conflicts=(),
                conflicts_truncated=False,
                conflict_download_url=(
                    f"/api/v1/import-workflows/{workflow.id}/conflicts.csv"
                ),
            )
        assembly = self._assembly_for(workflow_id)
        conflicts = assembly.result.conflicts[:50]
        return CommitPlan(
            workflow_id=workflow.id,
            expected_revision=workflow.revision,
            ready=not assembly.result.conflicts,
            candidate_sha256s=digests,
            content_sha256=(
                assembly.result.sha256 if not assembly.result.conflicts else None
            ),
            dedupe=assembly.result.summary,
            conflicts=conflicts,
            conflicts_truncated=len(assembly.result.conflicts) > len(conflicts),
            conflict_download_url=(
                f"/api/v1/import-workflows/{workflow.id}/conflicts.csv"
            ),
        )

    def conflict_csv(self, workflow_id: UUID) -> bytes:
        assembly = self._assembly_for(workflow_id)
        output = StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(
            (
                "role",
                "business_key",
                "conflicting_fields",
                "existing_source_kind",
                "existing_source_name",
                "existing_sheet_name",
                "existing_row_number",
                "incoming_source_kind",
                "incoming_source_name",
                "incoming_sheet_name",
                "incoming_row_number",
            )
        )
        for conflict in assembly.result.conflicts:
            writer.writerow(
                tuple(
                    self._escape_csv_cell(value)
                    for value in (
                        conflict.role,
                        ";".join(
                            f"{field}={value}"
                            for field, value in conflict.business_key
                        ),
                        ";".join(conflict.fields),
                        conflict.existing.source_kind,
                        conflict.existing.source_name,
                        conflict.existing.sheet_name,
                        conflict.existing.row_number,
                        conflict.incoming.source_kind,
                        conflict.incoming.source_name,
                        conflict.incoming.sheet_name,
                        conflict.incoming.row_number,
                    )
                )
            )
        return output.getvalue().encode("utf-8-sig")

    def commit(
        self,
        workflow_id: UUID,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> CommitResult:
        with self._operation_lock(
            f"{self._workspace_id}:import-commit:{SERIES_NAME}",
            WorkflowCommitBusy,
        ):
            return self._commit_serialized(
                workflow_id,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
            )

    def _commit_serialized(
        self,
        workflow_id: UUID,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> CommitResult:
        key_hash = self._key_hash(idempotency_key)
        with self._engine.connect() as connection:
            imports = ImportRepository(connection)
            workflow = self._workflow(imports, workflow_id)
            committed_version = DatasetRepository(connection).find_version_by_workflow(
                self._workspace_id,
                workflow_id,
            )
        assembly = None
        if committed_version is None:
            self._require_revision(workflow, expected_revision)
            assembly = self._assembly_for(workflow_id)
            if assembly.result.conflicts:
                raise ImportDedupeConflict
            content_sha256 = assembly.result.sha256
        else:
            content_sha256 = committed_version.content_sha256
        request_hash = self._request_hash(
            {
                "expected_revision": expected_revision,
                "base_dataset_version_id": (
                    str(workflow.base_dataset_version_id)
                    if workflow.base_dataset_version_id is not None
                    else None
                ),
                "merged_content_sha256": content_sha256,
            }
        )
        with self._engine.connect() as connection:
            disposition = IdempotencyRepository(connection).check(
                scope_type="workflow",
                scope_id=str(workflow_id),
                operation="commit",
                key_hash=key_hash,
                request_hash=request_hash,
            )
            if disposition == "conflict":
                raise IdempotencyConflict
            if disposition == "in_progress":
                raise IdempotencyConflict
            if disposition == "replay":
                projection = IdempotencyRepository(connection).replay_projection(
                    scope_type="workflow",
                    scope_id=str(workflow_id),
                    operation="commit",
                    key_hash=key_hash,
                    request_hash=request_hash,
                )
                if projection is None:
                    raise IdempotencyConflict
                return CommitResult(
                    UUID(str(projection["workflow_id"])),
                    UUID(str(projection["dataset_version_id"])),
                    int(projection["version_number"]),
                    str(projection["content_sha256"]),
                    created=bool(projection["created"]),
                )
            self._require_revision(workflow, expected_revision)
            self._require_current_base(
                DatasetRepository(connection),
                workflow,
            )
        if assembly is None:
            raise WorkflowRevisionConflict
        with self._engine.connect() as connection:
            if (
                DatasetRepository(connection).find_version_by_content(
                    self._workspace_id,
                    content_sha256,
                )
                is not None
            ):
                raise WorkflowNotReady("duplicate_dataset_content")
        version_id = uuid5(
            IMPORT_NAMESPACE,
            f"version:{workflow_id}:{key_hash.hex()}",
        )
        staged = self._storage.put_staging(
            BytesIO(assembly.result.content),
            max_bytes=MAX_CANONICAL_BYTES,
            media_type=CANONICAL_MEDIA_TYPE,
        )
        if staged.sha256 != content_sha256:
            self._delete_or_schedule_staged(
                staged,
                cleanup_scope=f"merged-sha-mismatch:{workflow_id}",
                now=self._clock(),
            )
            raise WorkflowNotReady("merged_content_sha_invalid")
        merged: MergedForCommit | None = None
        try:
            available = self._storage.promote(
                staged.key,
                dataset_object_key(
                    self._workspace_id,
                    str(version_id),
                    content_sha256,
                ),
                content_sha256,
            )
            merged = MergedForCommit(
                storage_object_id=uuid5(
                    IMPORT_NAMESPACE,
                    f"merged:{version_id}:{content_sha256}",
                ),
                staged=staged,
                available=available,
            )
            result = self._commit_database(
                workflow_id,
                expected_revision,
                key_hash,
                request_hash,
                content_sha256,
                version_id,
                merged,
            )
        except Exception as primary_error:
            try:
                committed = self._committed_version(
                    workflow_id,
                    version_id,
                    content_sha256,
                )
            except Exception:
                primary_error.add_note(
                    "commit_outcome_unknown_final_objects_retained"
                )
                raise primary_error
            if committed is None:
                if merged is not None:
                    self._compensate_merged(merged, primary_error)
                self._delete_or_schedule_staged(
                    staged,
                    cleanup_scope=f"failed-merged:{workflow_id}",
                    now=self._clock(),
                )
                raise
            result = CommitResult(
                workflow_id,
                committed.id,
                committed.version_number,
                committed.content_sha256,
                created=True,
            )
        self._cleanup_committed_originals(workflow_id, assembly, staged)
        return result

    def _commit_database(
        self,
        workflow_id: UUID,
        expected_revision: int,
        key_hash: bytes,
        request_hash: bytes,
        content_sha256: str,
        version_id: UUID,
        merged: MergedForCommit,
    ) -> CommitResult:
        now = self._clock()
        with PostgresUnitOfWork(self._engine) as uow:
            imports = ImportRepository(uow.connection)
            current = self._workflow(imports, workflow_id)
            self._require_revision(current, expected_revision)
            datasets = DatasetRepository(uow.connection)
            series = self._require_current_base(
                datasets,
                current,
                for_update=True,
            )
            if series is None:
                series = datasets.create_series(
                    workspace_id=self._workspace_id,
                    name=SERIES_NAME,
                    now=now,
                    series_id=uuid5(
                        IMPORT_NAMESPACE,
                        f"series:{self._workspace_id}:{SERIES_NAME}",
                    ),
                )
            version = datasets.create_version(
                series_id=series.id,
                workspace_id=self._workspace_id,
                source_workflow_id=workflow_id,
                base_version_id=current.base_dataset_version_id,
                version_number=datasets.next_version_number(series.id),
                schema_version="canonical.import.v1",
                content_sha256=content_sha256,
                now=now,
                version_id=version_id,
            )
            storage_repository = StorageObjectRepository(uow.connection)
            storage_repository.create_available(
                object_id=merged.storage_object_id,
                workspace_id=self._workspace_id,
                available=merged.available,
                purpose="normalized_dataset",
                media_type=CANONICAL_MEDIA_TYPE,
                now=now,
            )
            datasets.create_artifact(
                dataset_version_id=version.id,
                storage_object_id=merged.storage_object_id,
                artifact_kind="canonical_dataset",
                sha256=merged.available.sha256,
                now=now,
                artifact_id=uuid5(
                    IMPORT_NAMESPACE,
                    f"artifact:{version.id}:canonical_dataset",
                ),
            )
            datasets.point_series_at(series.id, version.id)
            updated = imports.transition_workflow(
                workflow_id,
                expected_revision=expected_revision,
                status="committed",
                now=now,
                committed_at=now,
            )
            if updated is None:
                raise WorkflowRevisionConflict
            response_projection = {
                "workflow_id": str(workflow_id),
                "dataset_version_id": str(version.id),
                "version_number": version.version_number,
                "content_sha256": version.content_sha256,
                "created": True,
            }
            IdempotencyRepository(uow.connection).record_succeeded(
                scope_type="workflow",
                scope_id=str(workflow_id),
                operation="commit",
                key_hash=key_hash,
                request_hash=request_hash,
                response_status=201,
                response_body_hash=self._request_hash(response_projection),
                response_projection=response_projection,
                now=now,
                expires_at=now + IDEMPOTENCY_TTL,
            )
        return CommitResult(
            workflow_id,
            version.id,
            version.version_number,
            version.content_sha256,
            created=True,
        )

    def _cleanup_committed_originals(
        self,
        workflow_id: UUID,
        assembly: WorkflowAssembly,
        merged_staged: StagedObject,
    ) -> None:
        now = self._clock()
        self._delete_or_schedule_staged(
            merged_staged,
            cleanup_scope=f"committed-merged:{workflow_id}",
            now=now,
        )
        for upload, candidate in zip(
            assembly.uploads,
            assembly.candidate_records,
            strict=True,
        ):
            try:
                self._storage.delete(
                    candidate.object_key,
                    expected_etag=candidate.etag,
                )
            except Exception:
                with PostgresUnitOfWork(self._engine) as uow:
                    StorageObjectRepository(uow.connection).mark_cleanup_pending(
                        candidate.id,
                        now=now,
                    )
            else:
                with PostgresUnitOfWork(self._engine) as uow:
                    StorageObjectRepository(uow.connection).mark_deleted(
                        candidate.id,
                        now=now,
                    )
            with self._engine.connect() as connection:
                original = StorageObjectRepository(connection).get(
                    upload.storage_object_id
                )
            if original is None:
                continue
            try:
                self._storage.delete(original.object_key, expected_etag=original.etag)
            except Exception:
                with PostgresUnitOfWork(self._engine) as uow:
                    StorageObjectRepository(uow.connection).mark_quarantined(
                        original.id,
                        now=now,
                    )
                continue
            with PostgresUnitOfWork(self._engine) as uow:
                StorageObjectRepository(uow.connection).mark_deleted(
                    original.id,
                    now=now,
                )
                ImportRepository(uow.connection).mark_upload_deleted(
                    workflow_id,
                    upload.id,
                )

    def _assembly_for(self, workflow_id: UUID) -> WorkflowAssembly:
        with self._engine.connect() as connection:
            imports = ImportRepository(connection)
            workflow = self._workflow(imports, workflow_id)
            uploads = imports.list_uploads(workflow_id)
            if not uploads or not all(
                upload.status == "accepted"
                and upload.candidate_storage_object_id is not None
                and upload.quality_report is not None
                for upload in uploads
            ):
                raise WorkflowNotReady
            storage_repository = StorageObjectRepository(connection)
            candidate_records = tuple(
                storage_repository.get(upload.candidate_storage_object_id)
                for upload in uploads
            )
            base_source = self._load_base_source(connection, workflow)
        if any(record is None for record in candidate_records):
            raise WorkflowNotReady("candidate_authority_invalid")
        verified_candidates = tuple(
            record for record in candidate_records if record is not None
        )
        upload_sources = []
        upload_row_count = 0
        for upload, record in zip(uploads, verified_candidates, strict=True):
            if (
                record.workspace_id != self._workspace_id
                or record.state != "staging"
                or record.purpose != "temporary_upload"
                or record.sha256 != upload.quality_report.get("sha256")
            ):
                raise WorkflowNotReady("candidate_authority_invalid")
            payload = self._open_json_object(record)
            source = self._source_from_payload(
                payload,
                source_kind="upload",
                source_name=upload.source_filename,
                created_at=upload.created_at,
                allow_missing_provenance=False,
            )
            upload_sources.append(source)
            upload_row_count += sum(len(rows) for rows in source.tables.values())
        try:
            result = CanonicalDatasetAssembler().assemble(
                base=base_source,
                uploads=tuple(upload_sources),
            )
        except (CanonicalSourceInvalid, ValueError) as error:
            raise WorkflowNotReady("candidate_schema_invalid") from error
        if (
            workflow.base_dataset_version_id is not None
            and not result.conflicts
            and result.summary.duplicates_removed == upload_row_count
        ):
            with self._engine.connect() as connection:
                base_version = DatasetRepository(connection).get_version(
                    workflow.base_dataset_version_id
                )
            if (
                base_version is not None
                and base_version.schema_version == "canonical.import.v1"
            ):
                result = AssemblyResult(
                    content=b"",
                    sha256=base_version.content_sha256,
                    summary=result.summary,
                    conflicts=(),
                )
        if result.content and len(result.content) > MAX_CANONICAL_BYTES:
            raise WorkflowNotReady("canonical_dataset_too_large")
        return WorkflowAssembly(
            workflow=workflow,
            uploads=uploads,
            candidate_records=verified_candidates,
            result=result,
        )

    def _load_base_source(
        self,
        connection,
        workflow: ImportWorkflowProjection,
    ) -> CanonicalSource | None:
        if workflow.base_dataset_version_id is None:
            return None
        datasets = DatasetRepository(connection)
        version = datasets.get_version(workflow.base_dataset_version_id)
        if version is None or version.workspace_id != self._workspace_id:
            raise WorkflowNotReady("base_dataset_authority_invalid")
        artifacts = datasets.list_artifacts(version.id)
        if not artifacts:
            return None
        storage_repository = StorageObjectRepository(connection)
        pairs = tuple(
            (artifact, storage_repository.get(artifact.storage_object_id))
            for artifact in artifacts
        )
        if any(storage is None for _artifact, storage in pairs):
            raise WorkflowNotReady("base_dataset_authority_invalid")
        preferred_kind = (
            "canonical_dataset"
            if any(item.artifact_kind == "canonical_dataset" for item in artifacts)
            else "analysis_bundle"
            if any(item.artifact_kind == "analysis_bundle" for item in artifacts)
            else None
        )
        selected = tuple(
            (artifact, storage)
            for artifact, storage in pairs
            if storage is not None
            and (preferred_kind is None or artifact.artifact_kind == preferred_kind)
        )
        if preferred_kind is not None and len(selected) != 1:
            raise WorkflowNotReady("base_dataset_artifact_ambiguous")
        tables: dict[str, list[dict[str, object]]] = {}
        provenance: dict[str, list[dict[str, object]]] = {}
        catalog: dict[str, StoreDescriptor] = {}
        for artifact, storage in selected:
            if (
                storage.workspace_id != self._workspace_id
                or storage.state != "available"
                or storage.purpose != "normalized_dataset"
                or storage.sha256 != artifact.sha256
            ):
                raise WorkflowNotReady("base_dataset_authority_invalid")
            payload = self._open_json_object(storage)
            source = self._source_from_payload(
                payload,
                source_kind="base",
                source_name=f"base-v{version.version_number}.json",
                created_at=None,
                allow_missing_provenance=True,
            )
            for role, rows in source.tables.items():
                if role in tables:
                    raise WorkflowNotReady("base_dataset_role_duplicate")
                tables[role] = [dict(row) for row in rows]
                provenance[role] = [
                    dict(origin) for origin in source.row_provenance[role]
                ]
            for store in source.store_catalog:
                existing = catalog.get(store.store_id)
                if existing is not None and existing != store:
                    raise WorkflowNotReady("base_store_catalog_conflict")
                catalog[store.store_id] = store
        return CanonicalSource(
            source_kind="base",
            source_name=f"base-v{version.version_number}.json",
            tables=tables,
            row_provenance=provenance,
            store_catalog=tuple(catalog[key] for key in sorted(catalog)),
        )

    def _open_json_object(
        self,
        storage: StorageObjectProjection,
    ) -> dict[str, object]:
        if storage.size_bytes > MAX_CANONICAL_BYTES:
            raise WorkflowNotReady("canonical_artifact_too_large")
        with self._storage.open_verified(
            storage.object_key,
            storage.sha256,
            storage.size_bytes,
        ) as opened:
            try:
                payload = json.load(opened)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise WorkflowNotReady("canonical_artifact_invalid") from error
        if not isinstance(payload, dict):
            raise WorkflowNotReady("canonical_artifact_invalid")
        return payload

    def _source_from_payload(
        self,
        payload: dict[str, object],
        *,
        source_kind: str,
        source_name: str,
        created_at: datetime | None,
        allow_missing_provenance: bool,
    ) -> CanonicalSource:
        raw_tables = payload.get("tables")
        if not isinstance(raw_tables, dict):
            raise WorkflowNotReady("canonical_tables_invalid")
        tables: dict[str, list[dict[str, object]]] = {}
        for role, rows in raw_tables.items():
            if (
                not isinstance(role, str)
                or not isinstance(rows, list)
                or not all(isinstance(row, dict) for row in rows)
            ):
                raise WorkflowNotReady("canonical_tables_invalid")
            tables[role] = [dict(row) for row in rows]
        if (
            payload.get("schema_version") == "canonical.analysis.v1"
            and "operating_expense" in tables
        ):
            tables["operating_expense"] = [
                (
                    {**row, "scope": "shared"}
                    if not row.get("store_id") and not row.get("scope")
                    else row
                )
                for row in tables.get("operating_expense", [])
            ]
        if payload.get("schema_version") == "canonical.analysis.v1":
            explicit_store_ids = {
                str(row["store_id"])
                for rows in tables.values()
                for row in rows
                if row.get("store_id")
            }
            if len(explicit_store_ids) == 1 and "replenishment_policy" in tables:
                store_id = next(iter(explicit_store_ids))
                tables["replenishment_policy"] = [
                    (
                        {**row, "store_id": store_id}
                        if not row.get("store_id")
                        else row
                    )
                    for row in tables.get("replenishment_policy", [])
                ]
        raw_provenance = payload.get("row_provenance")
        provenance: dict[str, list[dict[str, object]]] = {}
        if raw_provenance is None and allow_missing_provenance:
            provenance = {
                role: [
                    {
                        "source_name": source_name,
                        "sheet_name": None,
                        "row_number": index,
                    }
                    for index in range(1, len(rows) + 1)
                ]
                for role, rows in tables.items()
            }
        elif isinstance(raw_provenance, dict):
            for role, origins in raw_provenance.items():
                if (
                    not isinstance(role, str)
                    or not isinstance(origins, list)
                    or not all(isinstance(origin, dict) for origin in origins)
                ):
                    raise WorkflowNotReady("row_provenance_invalid")
                provenance[role] = [dict(origin) for origin in origins]
        else:
            raise WorkflowNotReady("row_provenance_invalid")
        return CanonicalSource(
            source_kind=source_kind,
            source_name=source_name,
            created_at=created_at,
            tables=tables,
            row_provenance=provenance,
            store_catalog=self._catalog_from_payload(payload),
        )

    @staticmethod
    def _catalog_from_payload(
        payload: dict[str, object],
    ) -> tuple[StoreDescriptor, ...]:
        raw_catalog = payload.get("store_catalog", [])
        if raw_catalog is None:
            return ()
        if not isinstance(raw_catalog, list):
            raise WorkflowNotReady("store_catalog_invalid")
        stores = []
        for item in raw_catalog:
            if not isinstance(item, dict):
                raise WorkflowNotReady("store_catalog_invalid")
            opened_on = item.get("opened_on")
            try:
                stores.append(
                    StoreDescriptor(
                        store_id=str(item["store_id"]),
                        display_name_en=str(item["display_name_en"]),
                        display_name_zh=str(item["display_name_zh"]),
                        currency=str(item["currency"]),
                        opened_on=(
                            date.fromisoformat(opened_on)
                            if isinstance(opened_on, str)
                            else opened_on
                        ),
                        lifecycle=str(item["lifecycle"]),
                        has_data=bool(item["has_data"]),
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                raise WorkflowNotReady("store_catalog_invalid") from error
        return tuple(stores)

    def _validate_store_assignment(
        self,
        workflow: ImportWorkflowProjection,
        artifact: StandardizedArtifact,
        *,
        assigned_store_id: str | None,
    ) -> None:
        payload = json.loads(artifact.content)
        if not isinstance(payload, dict):
            raise UploadInvalid("canonical_artifact_invalid")
        scoped_rows = self._store_scoped_rows(payload)
        populated = tuple(
            row
            for row in scoped_rows
            if isinstance(row.get("store_id"), str) and row["store_id"].strip()
        )
        missing = tuple(row for row in scoped_rows if row not in populated)
        if populated and missing:
            raise UploadInvalid("mixed_store_assignment_invalid")
        if assigned_store_id is None:
            if missing:
                raise UploadInvalid("assigned_store_id_required")
            return
        validate_safe_import_records(({"assigned_store_id": assigned_store_id},))
        if not scoped_rows or populated:
            raise UploadInvalid("assigned_store_id_not_allowed")
        with self._engine.connect() as connection:
            base = self._load_base_source(connection, workflow)
        allowed = {
            store.store_id
            for store in (
                *(base.store_catalog if base is not None else ()),
                *self._catalog_from_payload(payload),
            )
        }
        if assigned_store_id not in allowed:
            raise UploadInvalid("assigned_store_id_unknown")

    @classmethod
    def _apply_store_assignment(
        cls,
        artifact: StandardizedArtifact,
        assigned_store_id: str,
    ) -> StandardizedArtifact:
        payload = json.loads(artifact.content)
        if not isinstance(payload, dict):
            raise UploadInvalid("canonical_artifact_invalid")
        for row in cls._store_scoped_rows(payload):
            row["store_id"] = assigned_store_id
        content = (
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        preview = tuple(
            row for rows in payload["tables"].values() for row in rows
        )[:25]
        return StandardizedArtifact(
            content=content,
            record_count=artifact.record_count,
            preview_records=preview,
            quality_report=dict(artifact.quality_report),
        )

    @staticmethod
    def _store_scoped_rows(
        payload: dict[str, object],
    ) -> tuple[dict[str, object], ...]:
        store_scoped_roles = {
            "daily_sales",
            "fulfillment_cost",
            "fx_effect",
            "inventory_movement",
            "inventory_receipt_lot",
            "operating_expense",
            "other_variable_cost",
            "outbound_event",
            "product_inventory_sales",
            "refund",
            "replenishment_policy",
            "settlement",
            "shopee_advertising",
        }
        tables = payload.get("tables")
        if not isinstance(tables, dict):
            raise UploadInvalid("canonical_tables_invalid")
        rows: list[dict[str, object]] = []
        for role, records in tables.items():
            if role not in store_scoped_roles:
                continue
            if not isinstance(records, list) or not all(
                isinstance(record, dict) for record in records
            ):
                raise UploadInvalid("canonical_tables_invalid")
            rows.extend(
                record
                for record in records
                if role != "operating_expense" or record.get("scope") != "shared"
            )
        return tuple(rows)

    @staticmethod
    def _empty_dedupe_summary() -> DedupeSummary:
        return DedupeSummary(0, 0, 0, 0, {})

    @staticmethod
    def _escape_csv_cell(value: object) -> str:
        rendered = "" if value is None else str(value)
        if rendered.startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + rendered
        return rendered

    def _load_original(
        self,
        workflow_id: UUID,
        upload_id: UUID,
    ) -> tuple[
        ImportWorkflowProjection,
        UploadRecordProjection,
        StorageObjectProjection,
    ]:
        with self._engine.connect() as connection:
            imports = ImportRepository(connection)
            workflow = self._workflow(imports, workflow_id)
            upload = imports.get_upload(workflow_id, upload_id)
            if upload is None:
                raise ImportNotFound
            storage_record = StorageObjectRepository(connection).get(
                upload.storage_object_id
            )
            if storage_record is None:
                raise ImportNotFound
            return workflow, upload, storage_record

    def _workflow(
        self,
        imports: ImportRepository,
        workflow_id: UUID,
    ) -> ImportWorkflowProjection:
        workflow = imports.get_workspace_workflow(self._workspace_id, workflow_id)
        if workflow is None:
            raise ImportNotFound
        return workflow

    def _require_current_base(
        self,
        datasets: DatasetRepository,
        workflow: ImportWorkflowProjection,
        *,
        for_update: bool = False,
    ):
        series = datasets.get_series_by_name(
            self._workspace_id,
            SERIES_NAME,
            for_update=for_update,
        )
        current_version_id = series.current_version_id if series is not None else None
        if current_version_id != workflow.base_dataset_version_id:
            raise WorkflowNotReady("IMPORT_BASE_VERSION_CHANGED")
        return series

    @staticmethod
    def _require_revision(
        workflow: ImportWorkflowProjection,
        expected_revision: int,
    ) -> None:
        if workflow.revision != expected_revision:
            raise WorkflowRevisionConflict

    def _key_hash(self, idempotency_key: str) -> bytes:
        normalized = idempotency_key.strip()
        if not 1 <= len(normalized) <= 128 or any(
            ord(character) < 0x21 or ord(character) > 0x7E
            for character in normalized
        ):
            raise IdempotencyConflict
        return hmac.new(self._pepper, normalized.encode(), hashlib.sha256).digest()

    @staticmethod
    def _request_hash(payload: dict[str, object]) -> bytes:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).digest()

    def _validate_upload(
        self,
        filename: str,
        media_type: str,
        content: bytes,
    ) -> None:
        if (
            not isinstance(filename, str)
            or PurePath(filename).name != filename
            or filename.startswith(".")
            or not filename.lower().endswith((".csv", ".xlsx"))
        ):
            raise UploadInvalid("filename_invalid")
        validate_safe_import_records(({"source_filename": filename},))
        expected_media = (
            "text/csv"
            if filename.lower().endswith(".csv")
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        if media_type != expected_media:
            raise UploadInvalid("media_type_invalid")
        if not content:
            raise UploadInvalid("upload_empty")
        if len(content) > self._max_upload_bytes:
            raise UploadTooLarge

    def _committed_version(
        self,
        workflow_id: UUID,
        version_id: UUID,
        content_sha256: str,
    ):
        with self._engine.connect() as connection:
            version = DatasetRepository(connection).find_version_by_workflow(
                self._workspace_id,
                workflow_id,
            )
        if version is None:
            return None
        if version.id != version_id or version.content_sha256 != content_sha256:
            raise WorkflowNotReady("commit_authority_mismatch")
        return version

    def _committed_upload(
        self,
        *,
        workflow_id: UUID,
        upload_id: UUID,
        object_id: UUID,
        key_hash: bytes,
        request_hash: bytes,
        staged: StagedObject,
    ) -> UploadMutationResult | None:
        with self._engine.connect() as connection:
            imports = ImportRepository(connection)
            upload = imports.get_upload(workflow_id, upload_id)
            storage_record = StorageObjectRepository(connection).get(object_id)
            receipts = IdempotencyRepository(connection)
            disposition = receipts.check(
                scope_type="workflow",
                scope_id=str(workflow_id),
                operation="upload",
                key_hash=key_hash,
                request_hash=request_hash,
            )
            projection = (
                receipts.replay_projection(
                    scope_type="workflow",
                    scope_id=str(workflow_id),
                    operation="upload",
                    key_hash=key_hash,
                    request_hash=request_hash,
                )
                if disposition == "replay"
                else None
            )
        if upload is None and storage_record is None and disposition == "missing":
            return None
        if (
            upload is None
            or upload.storage_object_id != object_id
            or storage_record is None
            or storage_record.object_key != staged.key
            or storage_record.sha256 != staged.sha256
            or storage_record.etag != staged.etag
            or projection is None
            or not isinstance(projection.get("workflow"), dict)
            or not isinstance(projection.get("upload"), dict)
        ):
            raise RuntimeError("upload_commit_authority_mismatch")
        return UploadMutationResult(
            _workflow_from_projection(projection["workflow"]),
            _upload_from_projection(projection["upload"]),
            replayed=bool(projection.get("replayed", False)),
        )

    def _committed_standardization(
        self,
        *,
        workflow_id: UUID,
        upload_id: UUID,
        candidate_id: UUID,
        staged: StagedObject,
    ) -> tuple[UploadMutationResult | None, bool]:
        with self._engine.connect() as connection:
            imports = ImportRepository(connection)
            workflow = imports.get_workspace_workflow(
                self._workspace_id,
                workflow_id,
            )
            upload = imports.get_upload(workflow_id, upload_id)
            candidate = StorageObjectRepository(connection).get(candidate_id)
        if (
            upload is not None
            and upload.status == "recognized"
            and upload.candidate_storage_object_id is None
            and candidate is None
        ):
            return None, False
        if (
            workflow is None
            or upload is None
            or upload.status != "accepted"
            or upload.candidate_storage_object_id != candidate_id
            or upload.quality_report is None
            or upload.quality_report.get("sha256") != staged.sha256
            or candidate is None
            or candidate.workspace_id != self._workspace_id
            or candidate.purpose != "temporary_upload"
            or candidate.state != "staging"
            or candidate.sha256 != staged.sha256
        ):
            raise RuntimeError("standardization_commit_authority_mismatch")
        return (
            UploadMutationResult(workflow, upload),
            candidate.object_key == staged.key and candidate.etag == staged.etag,
        )

    def _delete_or_schedule_staged(
        self,
        staged: StagedObject,
        *,
        cleanup_scope: str,
        now: datetime,
    ) -> None:
        try:
            self._storage.delete(staged.key, expected_etag=staged.etag)
        except Exception:
            self._schedule_staged_cleanup(
                staged,
                cleanup_scope=cleanup_scope,
                now=now,
            )

    def _compensate_merged(
        self,
        merged: MergedForCommit,
        primary_error: Exception,
    ) -> None:
        if not merged.available.created:
            return
        try:
            self._storage.delete(
                merged.available.key,
                expected_etag=merged.available.etag,
            )
        except Exception:
            try:
                self._schedule_available_cleanup(
                    merged.available,
                    media_type=CANONICAL_MEDIA_TYPE,
                    cleanup_scope=f"compensation:{merged.storage_object_id}",
                    now=self._clock(),
                )
            except Exception as schedule_error:
                primary_error.add_note(
                    "final_cleanup_schedule_failed:"
                    f"{type(schedule_error).__name__}"
                )
            primary_error.add_note(
                f"final_cleanup_pending:{merged.available.key}"
            )

    def _schedule_staged_cleanup(
        self,
        staged: StagedObject,
        *,
        cleanup_scope: str,
        now: datetime,
    ) -> None:
        object_id = uuid5(
            IMPORT_NAMESPACE,
            f"cleanup-staged:{cleanup_scope}:{staged.key}",
        )
        with PostgresUnitOfWork(self._engine) as uow:
            repository = StorageObjectRepository(uow.connection)
            existing = repository.get_by_key(staged.key)
            if existing is None:
                repository.create_staging(
                    workspace_id=self._workspace_id,
                    staged=staged,
                    purpose="temporary_upload",
                    now=now,
                    expires_at=now,
                    object_id=object_id,
                )
                repository.mark_quarantined(object_id, now=now)
            elif (
                existing.workspace_id != self._workspace_id
                or existing.purpose != "temporary_upload"
                or existing.sha256 != staged.sha256
            ):
                raise RuntimeError("cleanup_ledger_authority_conflict")

    def _schedule_available_cleanup(
        self,
        available: AvailableObject,
        *,
        media_type: str,
        cleanup_scope: str,
        now: datetime,
    ) -> None:
        object_id = uuid5(
            IMPORT_NAMESPACE,
            f"cleanup-available:{cleanup_scope}:{available.key}",
        )
        with PostgresUnitOfWork(self._engine) as uow:
            repository = StorageObjectRepository(uow.connection)
            existing = repository.get_by_key(available.key)
            if existing is None:
                repository.create_available(
                    object_id=object_id,
                    workspace_id=self._workspace_id,
                    available=available,
                    purpose="temporary_upload",
                    media_type=media_type,
                    now=now,
                    expires_at=now,
                )
                repository.mark_quarantined(object_id, now=now)
            elif (
                existing.workspace_id != self._workspace_id
                or existing.purpose != "temporary_upload"
                or existing.sha256 != available.sha256
            ):
                raise RuntimeError("cleanup_ledger_authority_conflict")

    @contextmanager
    def _operation_lock(
        self,
        lock_name: str,
        busy_error: type[ImportServiceError],
    ) -> Iterator[None]:
        material = lock_name.encode()
        lock_id = int.from_bytes(
            hashlib.sha256(material).digest()[:8],
            byteorder="big",
            signed=True,
        )
        connection = self._engine.connect()
        acquired = False
        deadline = monotonic() + OPERATION_LOCK_TIMEOUT_SECONDS
        try:
            while monotonic() < deadline:
                acquired = bool(
                    connection.execute(
                        TRY_ADVISORY_LOCK,
                        {"lock_id": lock_id},
                    ).scalar_one()
                )
                if acquired:
                    break
                sleep(0.05)
            if not acquired:
                raise busy_error
            yield
        finally:
            if acquired:
                try:
                    released = bool(
                        connection.execute(
                            RELEASE_ADVISORY_LOCK,
                            {"lock_id": lock_id},
                        ).scalar_one()
                    )
                    if not released:
                        connection.invalidate()
                except Exception:
                    connection.invalidate()
            connection.close()
