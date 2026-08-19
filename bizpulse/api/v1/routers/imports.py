"""Protected synthetic import-workflow routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from api.dependencies.csrf import require_operator_csrf
from api.dependencies.operator import resolve_operator
from api.v1.schemas.imports import (
    CommitPlanResponse,
    CommitResponse,
    CreateWorkflowRequest,
    MappingRequest,
    PreviewResponse,
    RevisionRequest,
    UploadResponse,
    WorkflowResponse,
)
from src.adapters.protocol import AdapterError, ParserBusy
from src.services.import_service import (
    ImportNotFound,
    ImportServiceError,
    IdempotencyConflict,
    UploadInvalid,
    UploadTooLarge,
    WorkflowNotReady,
    WorkflowCommitBusy,
    WorkflowRevisionConflict,
)
from src.storage.protocol import (
    StorageConcurrency,
    StorageError,
    StorageTooLarge,
)
from src.synthetic.boundary import SyntheticSourceBoundaryError

router = APIRouter(prefix="/import-workflows", tags=["imports"])
MAX_HTTP_UPLOAD_BYTES = 8 * 1024 * 1024


def _service(request: Request):
    service = request.app.state.container.import_service
    if service is None:
        return None
    return service


def _error(error: Exception) -> JSONResponse:
    if isinstance(error, SyntheticSourceBoundaryError):
        return JSONResponse(status_code=422, content={"code": error.code})
    if isinstance(error, (UploadTooLarge, StorageTooLarge)):
        return JSONResponse(status_code=413, content={"code": "UPLOAD_TOO_LARGE"})
    if isinstance(error, ImportNotFound):
        return JSONResponse(status_code=404, content={"code": error.code})
    if isinstance(
        error,
        (
            WorkflowRevisionConflict,
            IdempotencyConflict,
            WorkflowNotReady,
            WorkflowCommitBusy,
        ),
    ):
        return JSONResponse(status_code=409, content={"code": error.code})
    if isinstance(error, StorageConcurrency):
        return JSONResponse(
            status_code=409,
            content={"code": "STORAGE_STATE_CHANGED"},
        )
    if isinstance(error, ParserBusy):
        return JSONResponse(status_code=503, content={"code": error.code})
    if isinstance(error, (UploadInvalid, AdapterError)):
        return JSONResponse(status_code=422, content={"code": error.code})
    if isinstance(error, StorageError):
        return JSONResponse(
            status_code=503,
            content={"code": "STORAGE_UNAVAILABLE"},
        )
    if isinstance(error, ImportServiceError):
        return JSONResponse(status_code=400, content={"code": error.code})
    raise error


def _unavailable() -> JSONResponse:
    return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})


@router.post("", status_code=201, dependencies=[Depends(require_operator_csrf)])
def create_workflow(
    payload: CreateWorkflowRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    service = _service(request)
    if service is None:
        return _unavailable()
    try:
        result = service.create_workflow(
            idempotency_key=idempotency_key,
        )
        return WorkflowResponse(
            workflow=result.workflow,
            replayed=result.replayed,
        )
    except Exception as error:
        return _error(error)


@router.post(
    "/{workflow_id}/uploads",
    status_code=201,
    dependencies=[Depends(require_operator_csrf)],
)
async def upload(
    workflow_id: UUID,
    request: Request,
    filename: str = Query(min_length=1, max_length=255),
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    service = _service(request)
    if service is None:
        return _unavailable()
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_HTTP_UPLOAD_BYTES:
            return JSONResponse(
                status_code=413,
                content={"code": "UPLOAD_TOO_LARGE"},
            )
    try:
        result = await run_in_threadpool(
            service.upload,
            workflow_id,
            filename=filename,
            media_type=media_type,
            content=bytes(content),
            idempotency_key=idempotency_key,
        )
        return UploadResponse(
            workflow=result.workflow,
            upload=result.upload,
            replayed=result.replayed,
        )
    except Exception as error:
        return _error(error)


@router.post(
    "/{workflow_id}/uploads/{upload_id}/recognition",
    dependencies=[Depends(require_operator_csrf)],
)
def recognize(
    workflow_id: UUID,
    upload_id: UUID,
    payload: RevisionRequest,
    request: Request,
):
    service = _service(request)
    if service is None:
        return _unavailable()
    try:
        result = service.recognize(
            workflow_id,
            upload_id,
            expected_revision=payload.expected_revision,
        )
        return UploadResponse(
            workflow=result.workflow,
            upload=result.upload,
            replayed=result.replayed,
        )
    except Exception as error:
        return _error(error)


@router.put(
    "/{workflow_id}/uploads/{upload_id}/mapping",
    dependencies=[Depends(require_operator_csrf)],
)
def confirm_mapping(
    workflow_id: UUID,
    upload_id: UUID,
    payload: MappingRequest,
    request: Request,
):
    service = _service(request)
    if service is None:
        return _unavailable()
    try:
        result = service.confirm_mapping(
            workflow_id,
            upload_id,
            expected_revision=payload.expected_revision,
            expected_mapping_revision=payload.expected_mapping_revision,
            mapping=payload.mapping,
            assigned_store_id=payload.assigned_store_id,
        )
        return UploadResponse(
            workflow=result.workflow,
            upload=result.upload,
            replayed=result.replayed,
        )
    except Exception as error:
        return _error(error)


@router.post(
    "/{workflow_id}/uploads/{upload_id}/standardization",
    dependencies=[Depends(require_operator_csrf)],
)
def standardize(
    workflow_id: UUID,
    upload_id: UUID,
    payload: RevisionRequest,
    request: Request,
):
    service = _service(request)
    if service is None:
        return _unavailable()
    try:
        result = service.standardize(
            workflow_id,
            upload_id,
            expected_revision=payload.expected_revision,
        )
        return UploadResponse(
            workflow=result.workflow,
            upload=result.upload,
            replayed=result.replayed,
        )
    except Exception as error:
        return _error(error)


@router.get(
    "/{workflow_id}/uploads/{upload_id}/preview",
    dependencies=[Depends(resolve_operator)],
)
def preview(
    workflow_id: UUID,
    upload_id: UUID,
    request: Request,
    limit: int = Query(default=10, ge=1, le=25),
):
    service = _service(request)
    if service is None:
        return _unavailable()
    try:
        result = service.preview(workflow_id, upload_id, limit=limit)
        return PreviewResponse.model_validate(result, from_attributes=True)
    except Exception as error:
        return _error(error)


@router.get(
    "/{workflow_id}/commit-plan",
    dependencies=[Depends(resolve_operator)],
)
def commit_plan(workflow_id: UUID, request: Request):
    service = _service(request)
    if service is None:
        return _unavailable()
    try:
        result = service.commit_plan(workflow_id)
        return CommitPlanResponse.model_validate(result, from_attributes=True)
    except Exception as error:
        return _error(error)


@router.get(
    "/{workflow_id}/conflicts.csv",
    dependencies=[Depends(resolve_operator)],
)
def conflict_csv(workflow_id: UUID, request: Request):
    service = _service(request)
    if service is None:
        return _unavailable()
    try:
        content = service.conflict_csv(workflow_id)
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": (
                    f'attachment; filename="import-conflicts-{workflow_id}.csv"'
                ),
                "X-Content-Type-Options": "nosniff",
            },
        )
    except Exception as error:
        return _error(error)


@router.post(
    "/{workflow_id}/commit",
    status_code=201,
    dependencies=[Depends(require_operator_csrf)],
)
def commit(
    workflow_id: UUID,
    payload: RevisionRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    service = _service(request)
    if service is None:
        return _unavailable()
    try:
        result = service.commit(
            workflow_id,
            expected_revision=payload.expected_revision,
            idempotency_key=idempotency_key,
        )
        return CommitResponse.model_validate(result, from_attributes=True)
    except Exception as error:
        return _error(error)
