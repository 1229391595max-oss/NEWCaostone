"""Protected deterministic Profit Bridge workflow."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from api.dependencies.csrf import require_operator_csrf
from api.dependencies.operator import resolve_operator
from api.v1.schemas.profit_bridge import (
    ProfitBridgeResponse,
    ProfitBridgeRunRequest,
)
from src.services.profit_bridge_service import (
    ProfitBridgeInvalid,
    ProfitBridgeNotFound,
)

router = APIRouter(prefix="/profit-bridges", tags=["profit-bridges"])
PRIVATE_NO_STORE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


def _service(request: Request):
    return request.app.state.container.profit_bridge_service


def _error(error: Exception) -> JSONResponse:
    if isinstance(error, ProfitBridgeNotFound):
        return JSONResponse(status_code=404, content={"code": error.code})
    if isinstance(error, ProfitBridgeInvalid):
        return JSONResponse(status_code=422, content={"code": error.code})
    return JSONResponse(status_code=503, content={"code": "PROFIT_BRIDGE_UNAVAILABLE"})


@router.post("", dependencies=[Depends(require_operator_csrf)])
def run_profit_bridge(payload: ProfitBridgeRunRequest, request: Request):
    service = _service(request)
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    scope = payload.scope.model_dump(exclude_none=True)
    try:
        bridge = service.run(
            payload.dataset_version_id,
            current_period=(
                payload.current_period.period_start,
                payload.current_period.period_end,
            ),
            comparison_period=(
                payload.comparison_period.period_start,
                payload.comparison_period.period_end,
            ),
            scope=scope,
        )
    except Exception as error:
        return _error(error)
    return ProfitBridgeResponse.model_validate(bridge, from_attributes=True)


@router.get("/latest", dependencies=[Depends(resolve_operator)])
def latest_profit_bridge(
    request: Request,
    response: Response,
    dataset_version_id: UUID = Query(),
    store_id: list[str] | None = Query(default=None),
):
    service = _service(request)
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    try:
        bridge = service.latest(dataset_version_id, _scope(store_id))
    except Exception as error:
        result = _error(error)
        result.headers.update(PRIVATE_NO_STORE)
        return result
    response.headers.update(PRIVATE_NO_STORE)
    return ProfitBridgeResponse.model_validate(bridge, from_attributes=True)


@router.get("/default", dependencies=[Depends(resolve_operator)])
def default_profit_bridge(
    request: Request,
    response: Response,
    dataset_version_id: UUID = Query(),
    store_id: list[str] | None = Query(default=None),
):
    service = _service(request)
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    try:
        bridge = service.default(dataset_version_id, _scope(store_id))
    except Exception as error:
        result = _error(error)
        result.headers.update(PRIVATE_NO_STORE)
        return result
    response.headers.update(PRIVATE_NO_STORE)
    return ProfitBridgeResponse.model_validate(bridge, from_attributes=True)


def _scope(store_ids: list[str] | None) -> dict[str, object]:
    if store_ids is not None and len(store_ids) > 1:
        raise ProfitBridgeInvalid("profit_bridge_scope_invalid")
    return {
        "currency": "BRL",
        **({"store_id": store_ids[0]} if store_ids else {}),
    }


@router.get("/{bridge_id}", dependencies=[Depends(resolve_operator)])
def get_profit_bridge(bridge_id: UUID, request: Request, response: Response):
    service = _service(request)
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    try:
        bridge = service.get(bridge_id)
    except Exception as error:
        result = _error(error)
        result.headers.update(PRIVATE_NO_STORE)
        return result
    response.headers.update(PRIVATE_NO_STORE)
    return ProfitBridgeResponse.model_validate(bridge, from_attributes=True)
