"""Operator-only version history and BP Library details."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from api.dependencies.operator import resolve_operator
from api.v1.schemas.library import (
    LibraryVersionDetailResponse,
    LibraryTablePageResponse,
    LibraryVersionsResponse,
)
from src.services.library_service import (
    LibraryNotFound,
    LibraryTableNotFound,
    LibraryUnavailable,
)
from src.services.store_scope import StoreCatalogUnavailable, StoreScopeInvalid

router = APIRouter(prefix="/library", tags=["library"])
PRIVATE_NO_STORE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


@router.get("", dependencies=[Depends(resolve_operator)])
def list_library(request: Request, response: Response):
    service = request.app.state.container.library_service
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    response.headers.update(PRIVATE_NO_STORE)
    return LibraryVersionsResponse(versions=service.list_versions())


@router.get("/{version_id}", dependencies=[Depends(resolve_operator)])
def library_detail(
    version_id: UUID,
    request: Request,
    response: Response,
    preview_limit: int = Query(default=5, ge=1, le=10),
    store_id: Annotated[list[str] | None, Query()] = None,
):
    service = request.app.state.container.library_service
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    try:
        detail = service.get_version(
            version_id,
            preview_limit=preview_limit,
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


@router.get(
    "/{version_id}/tables/{role}",
    dependencies=[Depends(resolve_operator)],
)
def library_table_page(
    version_id: UUID,
    role: str,
    request: Request,
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: Literal["25", "50", "100"] = Query(default="50"),
    store_id: Annotated[list[str] | None, Query()] = None,
):
    service = request.app.state.container.library_service
    if service is None:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})
    try:
        result = service.get_table_page(
            version_id,
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
