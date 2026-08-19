"""Protected deterministic new-product forecast workflow."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from api.dependencies.csrf import require_operator_csrf
from api.dependencies.operator import resolve_operator
from api.v1.schemas.forecasts import (
    AnalogConfirmationRequest,
    ForecastCreateRequest,
    ForecastResponse,
)
from src.forecast.contracts import ForecastRequest, ProductCandidate
from src.forecast.new_product import ForecastBlocked
from src.services.forecast_service import ForecastInvalid, ForecastNotFound

router = APIRouter(prefix="/forecasts", tags=["forecasts"])
PRIVATE_NO_STORE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


def _service(request: Request):
    return request.app.state.container.forecast_service


def _error(error: Exception) -> JSONResponse:
    if isinstance(error, ForecastNotFound):
        return JSONResponse(status_code=404, content={"code": error.code})
    if isinstance(error, ForecastInvalid):
        return JSONResponse(status_code=422, content={"code": error.code})
    if isinstance(error, ForecastBlocked):
        code = str(error).upper()
        status = 409 if code == "ANALOGS_NOT_CONFIRMED" else 422
        return JSONResponse(status_code=status, content={"code": code})
    return JSONResponse(status_code=503, content={"code": "FORECAST_UNAVAILABLE"})


@router.post("", status_code=201, dependencies=[Depends(require_operator_csrf)])
def create_forecast(
    payload: ForecastCreateRequest,
    request: Request,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
    ),
):
    service = _service(request)
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    candidate = payload.candidate
    domain_request = ForecastRequest(
        candidate=ProductCandidate(
            product_name=candidate.product_name,
            category=candidate.category,
            attributes=tuple(candidate.attributes),
            planned_launch_date=candidate.planned_launch_date,
            planned_price_brl=candidate.planned_price_brl,
            expected_discount_brl=candidate.expected_discount_brl,
            unit_cost_brl=candidate.unit_cost_brl,
            opening_inventory_units=candidate.opening_inventory_units,
            moq_units=candidate.moq_units,
            lead_time_days=candidate.lead_time_days,
            planned_daily_ad_brl=candidate.planned_daily_ad_brl,
        ),
        safety_stock_units=payload.safety_stock_units,
        assumptions=tuple(payload.assumptions),
        missing_fields=tuple(payload.missing_fields),
    )
    try:
        return ForecastResponse.model_validate(
            service.create(
                payload.dataset_version_id,
                domain_request,
                scope=payload.scope,
                idempotency_key=idempotency_key,
            ),
            from_attributes=True,
        )
    except Exception as error:
        return _error(error)


@router.get("/latest", dependencies=[Depends(resolve_operator)])
def latest_forecast(
    request: Request,
    response: Response,
    dataset_version_id: UUID = Query(),
    store_id: list[str] | None = Query(default=None),
):
    service = _service(request)
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    try:
        forecast = service.latest(dataset_version_id, _scope(store_id))
    except Exception as error:
        result = _error(error)
        result.headers.update(PRIVATE_NO_STORE)
        return result
    response.headers.update(PRIVATE_NO_STORE)
    return ForecastResponse.model_validate(forecast, from_attributes=True)


def _scope(store_ids: list[str] | None) -> dict[str, object]:
    if store_ids is not None and len(store_ids) > 1:
        raise ForecastInvalid("FORECAST_SCOPE_INVALID")
    return {
        "currency": "BRL",
        **({"store_id": store_ids[0]} if store_ids else {}),
    }


@router.get("/{forecast_id}", dependencies=[Depends(resolve_operator)])
def get_forecast(forecast_id: UUID, request: Request, response: Response):
    service = _service(request)
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    try:
        forecast = service.get(forecast_id)
    except Exception as error:
        result = _error(error)
        result.headers.update(PRIVATE_NO_STORE)
        return result
    response.headers.update(PRIVATE_NO_STORE)
    return ForecastResponse.model_validate(forecast, from_attributes=True)


@router.post(
    "/{forecast_id}/analogs/confirm",
    dependencies=[Depends(require_operator_csrf)],
)
def confirm_analogs(
    forecast_id: UUID,
    payload: AnalogConfirmationRequest,
    request: Request,
):
    service = _service(request)
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    try:
        return ForecastResponse.model_validate(
            service.confirm_analogs(forecast_id, tuple(payload.sku_ids)),
            from_attributes=True,
        )
    except Exception as error:
        return _error(error)


@router.post(
    "/{forecast_id}/backtest",
    dependencies=[Depends(require_operator_csrf)],
)
def backtest_forecast(forecast_id: UUID, request: Request):
    service = _service(request)
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    try:
        return service.backtest(forecast_id)
    except Exception as error:
        return _error(error)


@router.post("/{forecast_id}/run", dependencies=[Depends(require_operator_csrf)])
def run_forecast(forecast_id: UUID, request: Request):
    service = _service(request)
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    try:
        return ForecastResponse.model_validate(
            service.run(forecast_id),
            from_attributes=True,
        )
    except Exception as error:
        return _error(error)
