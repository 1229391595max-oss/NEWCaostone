"""Version 1 API root."""

from __future__ import annotations

from fastapi import APIRouter

from api.v1.routers.admin import router as admin_router
from api.v1.routers.analyses import router as analyses_router
from api.v1.routers.ai_chat import router as ai_chat_router
from api.v1.routers.datasets import router as datasets_router
from api.v1.routers.forecasts import router as forecasts_router
from api.v1.routers.imports import router as imports_router
from api.v1.routers.library import router as library_router
from api.v1.routers.profit_bridge import router as profit_bridge_router
from api.v1.routers.preferences import router as preferences_router

router = APIRouter(prefix="/api/v1", tags=["api-v1"])


@router.get("")
def api_root() -> dict[str, str]:
    """Expose a stable application-shell marker."""

    return {"name": "BizPulse API", "status": "shell"}


router.include_router(imports_router)
router.include_router(library_router)
router.include_router(datasets_router)
router.include_router(analyses_router)
router.include_router(forecasts_router)
router.include_router(profit_bridge_router)
router.include_router(ai_chat_router)
router.include_router(preferences_router)
router.include_router(admin_router)
