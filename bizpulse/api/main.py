"""FastAPI application factory for the BizPulse service."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from api.container import ApiContainer
from api.dependencies.operator import resolve_operator
from api.dependencies.session import resolve_demo_session
from api.errors import (
    AuthenticationRequiredError,
    CsrfValidationError,
    DemoDataNotImportedError,
    authentication_required,
)
from api.routers.demo_sessions import router as demo_sessions_router
from api.routers.demo_library import router as demo_library_router
from api.routers.demo_preferences import router as demo_preferences_router
from api.routers.health import ReadinessGate
from api.routers.health import router as health_router
from api.routers.operator_auth import router as operator_auth_router
from api.routers.public_release import router as public_release_router
from api.request_context import (
    RequestContextMiddleware,
    request_id,
    set_safe_error_code,
)
from api.security_policy import SecurityPolicy
from api.v1.router import router as v1_router
from api.v1.routers.actions import router as actions_router
from src.config import BizPulseSettings
from src.observability import configure_observability_logging, log_ai_turn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
ASSET_ROOT = FRONTEND_ROOT / "assets"
ADMIN_PRIVATE_NO_STORE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


class RevalidatingStaticFiles(StaticFiles):
    """Prevent a mixed frontend module graph after an incremental deployment."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _shell(path: Path) -> FileResponse:
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


def create_app(
    settings: BizPulseSettings | None = None,
    container: ApiContainer | None = None,
) -> FastAPI:
    """Create the HTTP application without relying on the process directory."""

    configure_observability_logging()

    resolved_settings = settings or (
        container.settings if container is not None else BizPulseSettings.from_env()
    )
    resolved_container = container or ApiContainer.build(resolved_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.container = resolved_container
        application.state.readiness_gate = ReadinessGate()
        try:
            yield
        finally:
            resolved_container.close()

    application = FastAPI(
        title="BizPulse",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.add_middleware(
        RequestContextMiddleware,
        policy=SecurityPolicy(
            cloud=resolved_settings.runtime_environment == "cloud",
            request_body_limit_bytes=resolved_settings.request_body_limit_bytes,
        ),
    )
    application.mount(
        "/assets",
        RevalidatingStaticFiles(directory=ASSET_ROOT),
        name="assets",
    )
    application.include_router(health_router)
    application.include_router(operator_auth_router)
    application.include_router(demo_sessions_router)
    application.include_router(demo_library_router)
    application.include_router(demo_preferences_router)
    application.include_router(public_release_router)
    application.include_router(v1_router)
    application.include_router(actions_router)

    @application.exception_handler(AuthenticationRequiredError)
    def handle_authentication_required(
        request: Request,
        error: AuthenticationRequiredError,
    ) -> JSONResponse:
        del error
        set_safe_error_code(request.scope, "AUTHENTICATION_REQUIRED")
        return authentication_required()

    @application.exception_handler(CsrfValidationError)
    def handle_csrf_validation_error(
        request: Request,
        error: CsrfValidationError,
    ) -> JSONResponse:
        del error
        set_safe_error_code(request.scope, "CSRF_VALIDATION_FAILED")
        return JSONResponse(
            status_code=403,
            content={"code": "CSRF_VALIDATION_FAILED"},
        )

    @application.exception_handler(DemoDataNotImportedError)
    def handle_demo_data_not_imported(
        request: Request,
        error: DemoDataNotImportedError,
    ) -> JSONResponse:
        del error
        set_safe_error_code(request.scope, "DEMO_DATA_NOT_IMPORTED")
        return JSONResponse(
            status_code=409,
            content={"code": "DEMO_DATA_NOT_IMPORTED"},
            headers={"Cache-Control": "private, no-store", "Vary": "Cookie"},
        )

    @application.exception_handler(RequestValidationError)
    def handle_request_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        del error
        is_chat_submission = (
            request.method == "POST"
            and request.url.path == "/api/v1/ai-chat/turns"
        )
        code = "AI_CHAT_INVALID" if is_chat_submission else "REQUEST_VALIDATION_FAILED"
        set_safe_error_code(request.scope, code)
        if is_chat_submission:
            try:
                log_ai_turn(
                    {
                        "dataset_version_hash_prefix": None,
                        "error_code": code,
                        "event": "ai_turn",
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "replayed": False,
                        "request_id": request_id(request.scope),
                        "status": "rejected",
                        "tool_name": None,
                    }
                )
            except Exception:
                pass
        return JSONResponse(
            status_code=422,
            content={"code": code},
        )

    @application.get("/", include_in_schema=False)
    def welcome() -> FileResponse:
        return _shell(FRONTEND_ROOT / "welcome.html")

    @application.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204, headers={"Cache-Control": "public, max-age=86400"})

    @application.get("/login", include_in_schema=False)
    def login() -> FileResponse:
        return _shell(FRONTEND_ROOT / "login.html")

    @application.get("/app", include_in_schema=False)
    def protected_application(request: Request) -> Response:
        try:
            resolve_operator(request)
        except AuthenticationRequiredError:
            set_safe_error_code(request.scope, "AUTHENTICATION_REQUIRED")
            return authentication_required()
        return _shell(FRONTEND_ROOT / "index.html")

    def admin_shell(request: Request) -> Response:
        try:
            resolve_operator(request)
        except AuthenticationRequiredError:
            target = quote(request.url.path, safe="/")
            return RedirectResponse(
                url=f"/login?next={target}",
                status_code=303,
                headers=ADMIN_PRIVATE_NO_STORE,
            )
        return FileResponse(
            FRONTEND_ROOT / "admin.html",
            headers=ADMIN_PRIVATE_NO_STORE,
        )

    for path in ("/admin", "/admin/data", "/admin/status", "/admin/ai"):
        application.add_api_route(
            path,
            admin_shell,
            methods=["GET"],
            include_in_schema=False,
        )

    @application.get("/demo", include_in_schema=False)
    def public_demo(request: Request) -> Response:
        try:
            resolve_demo_session(request)
        except AuthenticationRequiredError:
            set_safe_error_code(request.scope, "AUTHENTICATION_REQUIRED")
            return authentication_required()
        return _shell(FRONTEND_ROOT / "index.html")

    @application.get("/real", include_in_schema=False)
    def legacy_application_entry() -> RedirectResponse:
        return RedirectResponse(url="/app", status_code=307)

    return application


app = create_app()
