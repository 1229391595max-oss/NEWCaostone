"""Viewer read-only BP Library pinned to the activated shared release."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from api.dependencies.session import require_demo_data_imported
from api.v1.schemas.library import (
    LibraryTablePageResponse,
    LibraryVersionDetailResponse,
)
from src.services.demo_session_service import DemoPrincipal
from src.services.library_service import (
    LibraryNotFound,
    LibraryTableNotFound,
    LibraryUnavailable,
)
from src.services.store_scope import StoreCatalogUnavailable, StoreScopeInvalid

router = APIRouter(prefix="/api/demo/library", tags=["demo-library"])
PRIVATE_NO_STORE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


@router.get("/current")
def current_library(
    request: Request,
    response: Response,
    store_id: Annotated[list[str] | None, Query()] = None,
    principal: DemoPrincipal = Depends(require_demo_data_imported),
):
    service = request.app.state.container.library_service
    if service is None or principal.dataset_version_id is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    try:
        detail = service.get_version(
            principal.dataset_version_id,
            preview_limit=5,
            store_ids=tuple(store_id) if store_id is not None else None,
        )
    except LibraryNotFound as error:
        return JSONResponse(status_code=404, content={"code": error.code})
    except LibraryUnavailable as error:
        return JSONResponse(status_code=503, content={"code": error.code})
    except StoreScopeInvalid as error:
        return JSONResponse(status_code=400, content={"code": error.code})
    except StoreCatalogUnavailable as error:
        return JSONResponse(status_code=503, content={"code": error.code})
    response.headers.update(PRIVATE_NO_STORE)
    return LibraryVersionDetailResponse.model_validate(detail, from_attributes=True)


@router.get("/current/tables/{role}")
def current_library_table_page(
    role: str,
    request: Request,
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: Literal["25", "50", "100"] = Query(default="50"),
    store_id: Annotated[list[str] | None, Query()] = None,
    principal: DemoPrincipal = Depends(require_demo_data_imported),
):
    service = request.app.state.container.library_service
    if service is None or principal.dataset_version_id is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    try:
        result = service.get_table_page(
            principal.dataset_version_id,
            role,
            page=page,
            page_size=int(page_size),
            store_ids=tuple(store_id) if store_id is not None else None,
        )
    except LibraryNotFound as error:
        return JSONResponse(status_code=404, content={"code": error.code})
    except LibraryTableNotFound as error:
        return JSONResponse(status_code=404, content={"code": error.code})
    except ValueError as error:
        return JSONResponse(status_code=400, content={"code": str(error)})
    except LibraryUnavailable as error:
        return JSONResponse(status_code=503, content={"code": error.code})
    except StoreScopeInvalid as error:
        return JSONResponse(status_code=400, content={"code": error.code})
    except StoreCatalogUnavailable as error:
        return JSONResponse(status_code=503, content={"code": error.code})
    response.headers.update(PRIVATE_NO_STORE)
    return LibraryTablePageResponse.model_validate(result, from_attributes=True)
