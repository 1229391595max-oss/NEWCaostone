"""Viewer Settings defaults; browser preferences remain session-local."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from api.dependencies.session import resolve_demo_session
from api.v1.schemas.preferences import (
    AiConnectionStatus,
    PreferencePermissions,
    SettingsResponse,
)
from src.services.preferences_service import DEFAULT_PREFERENCES

router = APIRouter(prefix="/api/demo/preferences", tags=["demo-preferences"])


@router.get("")
def demo_preferences(
    request: Request,
    response: Response,
    _principal=Depends(resolve_demo_session),
):
    container = request.app.state.container
    if container.ai_chat_service is not None:
        ai = AiConnectionStatus(status="available")
    elif not container.settings.ai_chat_enabled:
        ai = AiConnectionStatus(status="disabled", limitation_code="ai_not_configured")
    else:
        ai = AiConnectionStatus(
            status="unavailable", limitation_code="ai_temporarily_unavailable",
        )
    response.headers.update({"Cache-Control": "private, no-store", "Vary": "Cookie"})
    return SettingsResponse(
        preferences={
            **DEFAULT_PREFERENCES,
            "overview_kpis": list(DEFAULT_PREFERENCES["overview_kpis"]),
            "revision": 0,
        },
        saved_views=(),
        targets=(
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "period": "2026-08",
                "revenue_brl": "100000.00",
                "orders": 2400,
                "roas": "4.25",
                "profit_brl": "18000.00",
                "status": "active",
                "revision": 1,
                "updated_at": "2026-08-01T00:00:00Z",
            },
        ),
        ai=ai,
        permissions=PreferencePermissions(
            reporting_defaults="read_only", targets="read_only", persistence="session",
        ),
    )
