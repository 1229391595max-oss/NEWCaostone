"""Protected immutable dataset-version and release routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse

from api.dependencies.csrf import require_operator_csrf
from api.dependencies.operator import resolve_operator
from api.v1.schemas.datasets import (
    DatasetExportRequest,
    DatasetExportResponse,
    DatasetPreparationResponse,
    DatasetVersionsResponse,
    PublishDatasetRequest,
    PublishDatasetResponse,
    PublicReleaseResponse,
)
from src.services.dataset_export_service import (
    DatasetExportIdempotencyConflict,
    DatasetExportInvalid,
    DatasetExportNotFound,
)
from src.services.dataset_preparation_service import DatasetPreparationNotFound
from src.services.public_release_service import (
    PublicReleaseConflict,
    PublicReleaseIdempotencyConflict,
    PublicReleaseIneligible,
    PublicReleaseNotFound,
)

router = APIRouter(prefix="/datasets", tags=["datasets"])
PRIVATE_NO_STORE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


def _service(request: Request):
    return request.app.state.container.dataset_service


@router.get("/versions", dependencies=[Depends(resolve_operator)])
def list_versions(request: Request, response: Response):
    service = _service(request)
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    response.headers.update(PRIVATE_NO_STORE)
    return DatasetVersionsResponse(versions=service.list_versions())


@router.post(
    "/versions/{version_id}/prepare",
    dependencies=[Depends(require_operator_csrf)],
)
def prepare(version_id: UUID, request: Request):
    service = request.app.state.container.dataset_preparation_service
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    try:
        return DatasetPreparationResponse.model_validate(
            service.prepare(version_id),
            from_attributes=True,
        )
    except DatasetPreparationNotFound as error:
        return JSONResponse(status_code=404, content={"code": error.code})


@router.post(
    "/versions/{version_id}/exports",
    dependencies=[Depends(require_operator_csrf)],
)
def generate_export(
    version_id: UUID,
    payload: DatasetExportRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    service = request.app.state.container.dataset_export_service
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    try:
        result = service.generate(
            version_id,
            idempotency_key=idempotency_key,
            format=payload.format,
        )
    except DatasetExportNotFound as error:
        return JSONResponse(status_code=404, content={"code": error.code})
    except DatasetExportInvalid as error:
        return JSONResponse(status_code=422, content={"code": error.code})
    except DatasetExportIdempotencyConflict as error:
        return JSONResponse(status_code=409, content={"code": error.code})
    return DatasetExportResponse.model_validate(result, from_attributes=True)


@router.get(
    "/versions/{version_id}/exports/{export_id}/download",
    dependencies=[Depends(resolve_operator)],
)
def download_export(version_id: UUID, export_id: UUID, request: Request):
    service = request.app.state.container.dataset_export_service
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    try:
        content = service.open(version_id, export_id)
    except DatasetExportNotFound as error:
        return JSONResponse(status_code=404, content={"code": error.code})
    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'attachment; filename="BizPulse-data.xlsx"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/public-release", dependencies=[Depends(resolve_operator)])
def current_public_release(request: Request, response: Response):
    service = request.app.state.container.public_release_service
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    current = service.current()
    if current is None:
        return JSONResponse(
            status_code=404,
            content={"code": "PUBLIC_RELEASE_NOT_FOUND"},
            headers=PRIVATE_NO_STORE,
        )
    try:
        release = service.for_operator(current.dataset_version_id)
    except PublicReleaseNotFound as error:
        return JSONResponse(
            status_code=404,
            content={"code": error.code},
            headers=PRIVATE_NO_STORE,
        )
    response.headers.update(PRIVATE_NO_STORE)
    return PublicReleaseResponse.model_validate(release)


@router.post(
    "/versions/{version_id}/publish",
    dependencies=[Depends(require_operator_csrf)],
)
def publish(
    version_id: UUID,
    payload: PublishDatasetRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    service = request.app.state.container.public_release_service
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    try:
        release = service.publish(
            version_id,
            expected_current_id=payload.expected_current_id,
            idempotency_key=idempotency_key,
        )
    except PublicReleaseNotFound as error:
        return JSONResponse(status_code=404, content={"code": error.code})
    except PublicReleaseIneligible as error:
        return JSONResponse(status_code=422, content={"code": error.code})
    except (PublicReleaseConflict, PublicReleaseIdempotencyConflict) as error:
        return JSONResponse(status_code=409, content={"code": error.code})
    return PublishDatasetResponse.model_validate(release)
