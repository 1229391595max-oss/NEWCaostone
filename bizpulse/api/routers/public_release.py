"""Anonymous reads for the exact public release pinned to a viewer session."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from api.dependencies.session import require_demo_data_imported
from src.services.demo_session_service import DemoPrincipal
from src.services.analysis_service import AnalysisInvalid, AnalysisNotFound
from src.services.public_release_service import (
    PUBLIC_ANALYSIS_KINDS,
    PUBLIC_ANALYSIS_SCOPE,
    PublicReleaseNotFound,
)
from api.v1.schemas.forecasts import ForecastResponse
from api.v1.schemas.profit_bridge import ProfitBridgeResponse
from src.services.forecast_service import ForecastInvalid, ForecastNotFound
from src.services.profit_bridge_service import (
    ProfitBridgeInvalid,
    ProfitBridgeNotFound,
)

router = APIRouter(prefix="/api/demo/release", tags=["public-release"])
PRIVATE_NO_STORE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


def _unavailable(status_code: int, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code},
        headers=PRIVATE_NO_STORE,
    )


def _metadata_complete(release) -> bool:
    periods = (
        release.reporting_period,
        release.current_period,
        release.comparison_period,
    )
    return (
        isinstance(release.version_number, int)
        and release.version_number > 0
        and bool(release.dataset_version_id)
        and bool(release.schema_version)
        and bool(release.content_sha256)
        and bool(release.currency)
        and bool(release.source_roles)
        and all(
            isinstance(period, (tuple, list))
            and len(period) == 2
            and all(isinstance(value, str) and value for value in period)
            for period in periods
        )
    )


@router.get("/current")
def current_session_release(
    request: Request,
    response: Response,
    principal: DemoPrincipal = Depends(require_demo_data_imported),
):
    service = request.app.state.container.public_release_service
    if service is None or principal.dataset_version_id is None:
        return _unavailable(503, "SERVICE_UNAVAILABLE")
    try:
        release = service.for_session(principal.dataset_version_id)
    except PublicReleaseNotFound as error:
        return _unavailable(404, error.code)
    if not _metadata_complete(release):
        return _unavailable(503, "PUBLIC_RELEASE_METADATA_INCOMPLETE")
    response.headers.update(PRIVATE_NO_STORE)
    return {
        "release_id": str(release.release_id),
        "dataset_version_id": str(release.dataset_version_id),
        "version_number": release.version_number,
        "schema_version": release.schema_version,
        "content_sha256": release.content_sha256,
        "released_at": release.released_at,
        "session_pinned": release.session_pinned,
        "source_classification": release.source_classification,
        "reporting_period": release.reporting_period,
        "current_period": release.current_period,
        "comparison_period": release.comparison_period,
        "currency": release.currency,
        "source_roles": release.source_roles,
        "precomputed_analyses": PUBLIC_ANALYSIS_KINDS,
        "evidence_states": ("measured", "derived", "assumed", "unknown"),
    }


@router.get("/analyses/{kind}")
def current_session_analysis(
    kind: str,
    request: Request,
    response: Response,
    principal: DemoPrincipal = Depends(require_demo_data_imported),
    store_id: list[str] | None = Query(default=None),
):
    service = request.app.state.container.analysis_service
    if service is None or principal.dataset_version_id is None:
        return _unavailable(503, "SERVICE_UNAVAILABLE")
    try:
        run, snapshot, evidence = service.get_exact_completed(
            kind,
            principal.dataset_version_id,
            _analysis_scope(store_id),
        )
    except AnalysisNotFound as error:
        return _unavailable(404, error.code)
    except AnalysisInvalid as error:
        return _unavailable(422, error.code)
    except ValueError:
        return _unavailable(422, "STORE_SCOPE_INVALID")
    except Exception:
        return _unavailable(503, "ANALYSIS_UNAVAILABLE")
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


@router.get("/forecasts/latest")
def current_session_forecast(
    request: Request,
    response: Response,
    principal: DemoPrincipal = Depends(require_demo_data_imported),
    store_id: list[str] | None = Query(default=None),
):
    service = request.app.state.container.forecast_service
    if service is None or principal.dataset_version_id is None:
        return _unavailable(503, "SERVICE_UNAVAILABLE")
    try:
        forecast = service.latest_completed(
            principal.dataset_version_id,
            _identity_scope(store_id),
        )
    except ForecastNotFound as error:
        return _unavailable(404, error.code)
    except ForecastInvalid as error:
        return _unavailable(422, error.code)
    except ValueError:
        return _unavailable(422, "STORE_SCOPE_INVALID")
    except Exception:
        return _unavailable(503, "FORECAST_UNAVAILABLE")
    response.headers.update(PRIVATE_NO_STORE)
    return ForecastResponse.model_validate(forecast, from_attributes=True)


@router.get("/profit-bridge/current")
def current_session_profit_bridge(
    request: Request,
    response: Response,
    principal: DemoPrincipal = Depends(require_demo_data_imported),
    store_id: list[str] | None = Query(default=None),
):
    service = request.app.state.container.profit_bridge_service
    if service is None or principal.dataset_version_id is None:
        return _unavailable(503, "SERVICE_UNAVAILABLE")
    try:
        bridge = service.default(
            principal.dataset_version_id,
            _identity_scope(store_id),
        )
    except ProfitBridgeNotFound as error:
        return _unavailable(404, error.code)
    except ProfitBridgeInvalid as error:
        return _unavailable(422, error.code)
    except ValueError:
        return _unavailable(422, "STORE_SCOPE_INVALID")
    except Exception:
        return _unavailable(503, "PROFIT_BRIDGE_UNAVAILABLE")
    response.headers.update(PRIVATE_NO_STORE)
    return ProfitBridgeResponse.model_validate(bridge, from_attributes=True)


def _identity_scope(store_ids: list[str] | None) -> dict[str, object]:
    if store_ids is not None and len(store_ids) > 1:
        raise ValueError("STORE_SCOPE_INVALID")
    return {
        "currency": "BRL",
        **({"store_id": store_ids[0]} if store_ids else {}),
    }


def _analysis_scope(store_ids: list[str] | None) -> dict[str, object]:
    scope = dict(PUBLIC_ANALYSIS_SCOPE)
    scope.pop("store_id", None)
    scope.update(_identity_scope(store_ids))
    return scope
