"""Liveness and readiness endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.db.readiness import FORWARD_COMPATIBLE_SCHEMA_REVISIONS
from src.db.readiness import readiness as database_readiness
from src.services.foundation_bootstrap_service import FoundationBootstrapService

router = APIRouter(prefix="/health", tags=["health"])
SUCCESS_CACHE_SECONDS = 5.0
FAILURE_CACHE_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    status_code: int
    content: dict[str, str | dict[str, str]]


class ReadinessGate:
    """Serialize and briefly cache the bounded deep authority probe."""

    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._cache_lock = Lock()
        self._probe_lock = Lock()
        self._cached: ReadinessResult | None = None
        self._expires_at = 0.0

    def check(self, probe: Callable[[], ReadinessResult]) -> ReadinessResult:
        cached = self._fresh()
        if cached is not None:
            return cached
        if not self._probe_lock.acquire(blocking=False):
            return _not_ready_result("probe")
        try:
            cached = self._fresh()
            if cached is not None:
                return cached
            result = probe()
            ttl = (
                SUCCESS_CACHE_SECONDS
                if result.status_code == 200
                else FAILURE_CACHE_SECONDS
            )
            with self._cache_lock:
                self._cached = result
                self._expires_at = self._clock() + ttl
            return result
        finally:
            self._probe_lock.release()

    def _fresh(self) -> ReadinessResult | None:
        with self._cache_lock:
            if self._cached is not None and self._clock() < self._expires_at:
                return self._cached
        return None


@router.get("/live")
def liveness() -> dict[str, str]:
    """Report that the HTTP process can serve requests."""

    return {"status": "ok"}


@router.get("/ready", response_model=None)
def readiness(request: Request) -> dict[str, str | dict[str, str]] | JSONResponse:
    """Probe the cloud authorities without returning provider diagnostics."""

    container = request.app.state.container
    if container.settings.runtime_environment == "cloud":
        gate = getattr(request.app.state, "readiness_gate", None)
        if gate is None:
            gate = ReadinessGate()
            request.app.state.readiness_gate = gate
        result = gate.check(lambda: _cloud_readiness(container))
        if result.status_code == 200:
            return result.content
        return JSONResponse(status_code=result.status_code, content=result.content)

    return {
        "status": "ready",
        "checks": {"configuration": "ok"},
    }


def _cloud_readiness(container) -> ReadinessResult:
    """Run one bounded cloud authority probe behind the readiness gate."""

    try:
        if container.engine is None:
            raise RuntimeError("database_unavailable")
        database = database_readiness(container.engine)
    except Exception:
        return _not_ready_result("database")
    if (
        not database.writable
        or database.revision not in FORWARD_COMPATIBLE_SCHEMA_REVISIONS
    ):
        return _not_ready_result("migration")
    password_hash = container.settings.operator_password_hash
    if password_hash is None:
        return _not_ready_result("foundation")
    try:
        foundation_ready = FoundationBootstrapService(
            engine=container.engine,
            workspace_id="synthetic-demo",
            login_name="operator",
            password_hash=password_hash,
        ).ready()
    except Exception:
        return _not_ready_result("foundation")
    if not foundation_ready:
        return _not_ready_result("foundation")
    try:
        storage_probe = getattr(container.workflow_storage, "check_readiness")
        storage_probe()
    except Exception:
        return _not_ready_result("blob")
    return ReadinessResult(
        status_code=200,
        content={
            "status": "ready",
            "checks": {
                "blob": "ok",
                "configuration": "ok",
                "database": "ok",
                "foundation": "ok",
                "migration": str(database.revision),
            },
        },
    )


def _not_ready_result(component: str) -> ReadinessResult:
    return ReadinessResult(
        status_code=503,
        content={
            "status": "not_ready",
            "checks": {"configuration": "ok", component: "failed"},
        },
    )
