"""Protected deterministic-analysis publication and immutable reads."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from api.dependencies.csrf import require_operator_csrf
from api.dependencies.operator import resolve_operator
from api.v1.schemas.analyses import (
    AnalysisRunRequest,
    AnalysisRunResponse,
    EvidenceResponse,
)
from src.services.analysis_service import (
    AnalysisBusy,
    AnalysisInputChanged,
    AnalysisInvalid,
    AnalysisNotFound,
)
from src.services.public_release_service import PUBLIC_ANALYSIS_SCOPE
from src.storage.postgres_entry_locks import StorageEntryBusy

router = APIRouter(prefix="/analyses", tags=["analyses"])
PRIVATE_NO_STORE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


def _service(request: Request):
    return request.app.state.container.analysis_service


def _unavailable() -> JSONResponse:
    return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})


def _error(error: Exception) -> JSONResponse:
    if isinstance(error, AnalysisNotFound):
        return JSONResponse(status_code=404, content={"code": error.code})
    if isinstance(error, AnalysisInputChanged):
        return JSONResponse(status_code=409, content={"code": error.code})
    if isinstance(error, (AnalysisBusy, StorageEntryBusy)):
        return JSONResponse(status_code=409, content={"code": "ANALYSIS_BUSY"})
    if isinstance(error, AnalysisInvalid):
        return JSONResponse(status_code=422, content={"code": error.code})
    raise error


@router.post(
    "/runs",
    status_code=201,
    dependencies=[Depends(require_operator_csrf)],
)
def run_analysis(
    payload: AnalysisRunRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    service = _service(request)
    if service is None:
        return _unavailable()
    try:
        plan = service.plan(payload.kind, payload.dataset_version_id, payload.scope)
        return AnalysisRunResponse.model_validate(
            service.run(plan, idempotency_key),
            from_attributes=True,
        )
    except Exception as error:
        return _error(error)


@router.get("/current/{kind}", dependencies=[Depends(resolve_operator)])
def get_current_public_analysis(
    kind: str,
    request: Request,
    response: Response,
    store_id: list[str] | None = Query(default=None),
):
    service = _service(request)
    release_service = request.app.state.container.public_release_service
    if service is None or release_service is None:
        return _unavailable()
    release = release_service.current()
    if release is None:
        return JSONResponse(
            status_code=404,
            content={"code": "PUBLIC_RELEASE_NOT_FOUND"},
        )
    return _exact_analysis(
        service,
        kind,
        release.dataset_version_id,
        response,
        store_id,
    )


@router.get(
    "/versions/{version_id}/{kind}",
    dependencies=[Depends(resolve_operator)],
)
def get_version_analysis(
    version_id: UUID,
    kind: str,
    request: Request,
    response: Response,
    store_id: list[str] | None = Query(default=None),
):
    service = _service(request)
    if service is None:
        return _unavailable()
    return _exact_analysis(service, kind, version_id, response, store_id)


def _exact_analysis(
    service,
    kind: str,
    version_id: UUID,
    response: Response,
    store_ids: list[str] | None,
):
    try:
        scope = _analysis_scope(store_ids)
        run, snapshot, evidence = service.get_exact_completed(
            kind,
            version_id,
            scope,
        )
    except Exception as error:
        if isinstance(error, (AnalysisNotFound, AnalysisInvalid)):
            result = _error(error)
            result.headers.update(PRIVATE_NO_STORE)
            return result
        return JSONResponse(
            status_code=503,
            content={"code": "ANALYSIS_UNAVAILABLE"},
            headers=PRIVATE_NO_STORE,
        )
    response.headers.update(PRIVATE_NO_STORE)
    return {
        "run": {
            "run_id": str(run.run_id),
            "dataset_version_id": str(run.dataset_version_id),
            "kind": run.kind,
            "algorithm_version": run.algorithm_version,
            "input_hash": run.input_hash,
            "artifact_sha256": run.artifact_sha256,
        },
        "snapshot": snapshot,
        "evidence": [
            {
                "evidence_id": str(item.id),
                "alias": item.alias,
                "evidence_state": item.evidence_state,
                "formula": item.formula,
                "source_refs": item.source_refs,
            }
            for item in evidence
        ],
    }


def _analysis_scope(store_ids: list[str] | None) -> dict[str, object]:
    if store_ids is not None and len(store_ids) > 1:
        raise AnalysisInvalid("analysis_store_scope_invalid")
    scope = dict(PUBLIC_ANALYSIS_SCOPE)
    scope.pop("store_id", None)
    if store_ids:
        scope["store_id"] = store_ids[0]
    return scope


@router.get("/{run_id}", dependencies=[Depends(resolve_operator)])
def get_analysis(run_id: UUID, request: Request):
    service = _service(request)
    if service is None:
        return _unavailable()
    try:
        return AnalysisRunResponse.model_validate(
            service.get(run_id),
            from_attributes=True,
        )
    except Exception as error:
        return _error(error)


@router.get("/{run_id}/snapshot", dependencies=[Depends(resolve_operator)])
def get_snapshot(run_id: UUID, request: Request):
    service = _service(request)
    if service is None:
        return _unavailable()
    try:
        return service.get_snapshot(run_id)
    except Exception as error:
        return _error(error)


@router.get(
    "/{run_id}/evidence/{evidence_id}",
    dependencies=[Depends(resolve_operator)],
)
def get_evidence(run_id: UUID, evidence_id: UUID, request: Request):
    service = _service(request)
    if service is None:
        return _unavailable()
    try:
        item = service.get_evidence(run_id, evidence_id)[0]
        return EvidenceResponse.model_validate(item, from_attributes=True)
    except Exception as error:
        return _error(error)
