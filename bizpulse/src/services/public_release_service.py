"""CAS-guarded public release publication and session-pinned reads."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from sqlalchemy import Engine, text

from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.datasets import DatasetRepository, PublicReleaseProjection
from src.repositories.idempotency import IdempotencyRepository
from src.services.profit_bridge_service import (
    PUBLIC_BASELINE_PERIOD,
    PUBLIC_CURRENT_PERIOD,
)
from src.synthetic.release_profile import PUBLIC_RELEASE_PROFILE, PUBLIC_SOURCE_ROLES

IDEMPOTENCY_TTL = timedelta(days=30)
RELEASE_NAMESPACE = UUID("4d24491e-7337-5c9c-a0de-83e630a41a38")
PUBLIC_ANALYSIS_SCOPE = PUBLIC_RELEASE_PROFILE.analysis_scope()
PUBLIC_ANALYSIS_KINDS = (
    "sales_ads",
    "inventory_risk",
    "fifo_cost_aging",
    "operating_profit",
    "replenishment",
)


class PublicReleaseError(RuntimeError):
    code = "PUBLIC_RELEASE_ERROR"


class PublicReleaseNotFound(PublicReleaseError):
    code = "DATASET_VERSION_NOT_FOUND"


class PublicReleaseIneligible(PublicReleaseError):
    code = "PUBLIC_RELEASE_INELIGIBLE"


class PublicReleaseConflict(PublicReleaseError):
    code = "PUBLIC_RELEASE_CONFLICT"


class PublicReleaseIdempotencyConflict(PublicReleaseError):
    code = "IDEMPOTENCY_CONFLICT"


@dataclass(frozen=True, slots=True)
class ReleaseResult:
    release_id: UUID
    dataset_version_id: UUID
    previous_dataset_version_id: UUID | None
    released_at: datetime
    created: bool
    replayed: bool


@dataclass(frozen=True, slots=True)
class SessionRelease:
    release_id: UUID
    dataset_version_id: UUID
    version_number: int
    schema_version: str
    content_sha256: str
    released_at: datetime
    session_pinned: bool = True
    source_classification: str = "pure_synthetic"
    reporting_period: tuple[str, str] = tuple(
        value.isoformat() for value in PUBLIC_RELEASE_PROFILE.reporting_period
    )
    current_period: tuple[str, str] = tuple(
        value.isoformat() for value in PUBLIC_RELEASE_PROFILE.current_period
    )
    comparison_period: tuple[str, str] = tuple(
        value.isoformat() for value in PUBLIC_RELEASE_PROFILE.comparison_period
    )
    currency: str = PUBLIC_RELEASE_PROFILE.currency
    source_roles: tuple[str, ...] = PUBLIC_SOURCE_ROLES


class PublicReleaseService:
    def __init__(
        self,
        engine: Engine,
        workspace_id: str,
        *,
        idempotency_pepper: str,
        clock: Callable[[], datetime] | None = None,
        uow_factory=PostgresUnitOfWork,
        analysis_service=None,
        profit_bridge_service=None,
        action_authority=None,
        forecast_service=None,
        preparation_service=None,
    ) -> None:
        self._engine = engine
        self._workspace_id = workspace_id
        self._pepper = idempotency_pepper.encode()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._uow_factory = uow_factory
        self._analysis_service = analysis_service
        self._profit_bridge_service = profit_bridge_service
        self._action_authority = action_authority
        self._forecast_service = forecast_service
        self._preparation_service = preparation_service

    def current(self) -> PublicReleaseProjection | None:
        with self._engine.connect() as connection:
            return DatasetRepository(connection).current_release(self._workspace_id)

    def for_session(self, dataset_version_id: UUID) -> SessionRelease:
        return self._describe_release(dataset_version_id, require_ready=True)

    def for_operator(self, dataset_version_id: UUID) -> SessionRelease:
        return self._describe_release(dataset_version_id, require_ready=False)

    def _describe_release(
        self,
        dataset_version_id: UUID,
        *,
        require_ready: bool,
    ) -> SessionRelease:
        with self._engine.connect() as connection:
            repository = DatasetRepository(connection)
            version = repository.get_version(dataset_version_id)
            release = repository.find_release_for_version(
                self._workspace_id,
                dataset_version_id,
            )
        if (
            version is None
            or version.workspace_id != self._workspace_id
            or version.status != "complete"
            or release is None
            or (require_ready and not self.release_ready(dataset_version_id))
        ):
            raise PublicReleaseNotFound
        return SessionRelease(
            release_id=release.id,
            dataset_version_id=version.id,
            version_number=version.version_number,
            schema_version=version.schema_version,
            content_sha256=version.content_sha256,
            released_at=release.released_at,
        )

    def publish(
        self,
        dataset_version_id: UUID,
        *,
        expected_current_id: UUID | None,
        idempotency_key: str,
    ) -> ReleaseResult:
        key_hash = self._key_hash(idempotency_key)
        request_hash = self._request_hash(
            {
                "dataset_version_id": str(dataset_version_id),
                "expected_current_id": (
                    str(expected_current_id)
                    if expected_current_id is not None
                    else None
                ),
            }
        )
        replay = self._replay(key_hash, request_hash)
        if replay is not None:
            return replay
        with self._engine.connect() as connection:
            repository = DatasetRepository(connection)
            version = repository.get_version(dataset_version_id)
            if (
                version is None
                or version.workspace_id != self._workspace_id
            ):
                raise PublicReleaseNotFound
            if not repository.is_release_eligible(version):
                raise PublicReleaseIneligible
        if self._preparation_service is not None:
            if self._preparation_service.readiness(dataset_version_id).status != "ready":
                raise PublicReleaseIneligible
        else:
            self._prepare_and_verify_analyses(dataset_version_id)
        now = self._clock()
        release_id = uuid5(
            RELEASE_NAMESPACE,
            f"{self._workspace_id}:{key_hash.hex()}:{request_hash.hex()}",
        )
        try:
            with self._uow_factory(self._engine) as uow:
                uow.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_id)"),
                    {"lock_id": self._lock_id()},
                )
                receipts = IdempotencyRepository(uow.connection)
                disposition = receipts.check(
                    scope_type="workspace",
                    scope_id=self._workspace_id,
                    operation="public_release_publish",
                    key_hash=key_hash,
                    request_hash=request_hash,
                )
                if disposition == "conflict" or disposition == "in_progress":
                    raise PublicReleaseIdempotencyConflict
                if disposition == "replay":
                    projection = receipts.replay_projection(
                        scope_type="workspace",
                        scope_id=self._workspace_id,
                        operation="public_release_publish",
                        key_hash=key_hash,
                        request_hash=request_hash,
                    )
                    if projection is None:
                        raise PublicReleaseIdempotencyConflict
                    return self._result(projection, replayed=True)

                repository = DatasetRepository(uow.connection)
                version = repository.get_version(dataset_version_id)
                if version is None or version.workspace_id != self._workspace_id:
                    raise PublicReleaseNotFound
                if not repository.is_release_eligible(version):
                    raise PublicReleaseIneligible
                current = repository.current_release(
                    self._workspace_id,
                    for_update=True,
                )
                current_version_id = (
                    current.dataset_version_id if current is not None else None
                )
                if current_version_id != expected_current_id:
                    raise PublicReleaseConflict
                if current_version_id == dataset_version_id and current is not None:
                    release = current
                    created = False
                else:
                    release = repository.activate_release(
                        workspace_id=self._workspace_id,
                        dataset_version_id=dataset_version_id,
                        now=now,
                        release_id=release_id,
                    )
                    created = True
                projection = {
                    "release_id": str(release.id),
                    "dataset_version_id": str(release.dataset_version_id),
                    "previous_dataset_version_id": (
                        str(current_version_id)
                        if current_version_id is not None
                        else None
                    ),
                    "released_at": release.released_at.isoformat(),
                    "created": created,
                }
                receipts.record_succeeded(
                    scope_type="workspace",
                    scope_id=self._workspace_id,
                    operation="public_release_publish",
                    key_hash=key_hash,
                    request_hash=request_hash,
                    response_status=200,
                    response_body_hash=self._request_hash(projection),
                    response_projection=projection,
                    now=now,
                    expires_at=now + IDEMPOTENCY_TTL,
                )
        except Exception as error:
            authority = self._replay(key_hash, request_hash)
            if authority is not None:
                return authority
            raise error
        return self._result(projection, replayed=False)

    def release_ready(self, dataset_version_id: UUID) -> bool:
        if self._preparation_service is not None:
            try:
                return (
                    self._preparation_service.readiness(dataset_version_id).status
                    == "ready"
                )
            except Exception:
                return False
        if self._analysis_service is None:
            return False
        try:
            for analysis_scope in self._analysis_service.preparation_scopes(
                dataset_version_id
            ):
                identity_scope = _identity_scope(analysis_scope)
                for kind in PUBLIC_ANALYSIS_KINDS:
                    self._analysis_service.get_exact_completed(
                        kind,
                        dataset_version_id,
                        analysis_scope,
                    )
                if self._profit_bridge_service is not None:
                    bridge_id = self._profit_bridge_service.completed_id_for_session(
                        dataset_version_id,
                        identity_scope,
                    )
                    if bridge_id is None:
                        return False
                    self._profit_bridge_service.get_for_session(
                        dataset_version_id,
                        bridge_id,
                    )
                if (
                    self._action_authority is not None
                    and not self._action_authority.ready(
                        dataset_version_id,
                        identity_scope,
                    )
                ):
                    return False
                if (
                    self._forecast_service is not None
                    and self._forecast_service.completed_id_for_session(
                        dataset_version_id,
                        identity_scope,
                    )
                    is None
                ):
                    return False
        except Exception:
            return False
        return True

    def _prepare_and_verify_analyses(self, dataset_version_id: UUID) -> None:
        if self._analysis_service is None:
            raise PublicReleaseIneligible
        try:
            for analysis_scope in self._analysis_service.preparation_scopes(
                dataset_version_id
            ):
                identity_scope = _identity_scope(analysis_scope)
                scope_token = identity_scope.get("store_id", "all")
                for kind in PUBLIC_ANALYSIS_KINDS:
                    plan = self._analysis_service.plan(
                        kind,
                        dataset_version_id,
                        analysis_scope,
                    )
                    self._analysis_service.run(
                        plan,
                        idempotency_key=(
                            f"release-{dataset_version_id}-{scope_token}-{kind}"
                        ),
                    )
                    self._analysis_service.get_exact_completed(
                        kind,
                        dataset_version_id,
                        analysis_scope,
                    )
                if self._profit_bridge_service is not None:
                    bridge = self._profit_bridge_service.run(
                        dataset_version_id,
                        current_period=PUBLIC_CURRENT_PERIOD,
                        comparison_period=PUBLIC_BASELINE_PERIOD,
                        scope=identity_scope,
                    )
                    if bridge.dataset_version_id != dataset_version_id:
                        raise PublicReleaseIneligible
                if self._action_authority is not None:
                    self._action_authority.ensure(dataset_version_id, identity_scope)
                    if not self._action_authority.ready(
                        dataset_version_id,
                        identity_scope,
                    ):
                        raise PublicReleaseIneligible
                if (
                    self._forecast_service is not None
                    and self._forecast_service.completed_id_for_session(
                        dataset_version_id,
                        identity_scope,
                    )
                    is None
                ):
                    raise PublicReleaseIneligible
        except Exception:
            raise PublicReleaseIneligible from None

    def _replay(self, key_hash: bytes, request_hash: bytes) -> ReleaseResult | None:
        with self._engine.connect() as connection:
            repository = IdempotencyRepository(connection)
            disposition = repository.check(
                scope_type="workspace",
                scope_id=self._workspace_id,
                operation="public_release_publish",
                key_hash=key_hash,
                request_hash=request_hash,
            )
            if disposition == "conflict" or disposition == "in_progress":
                raise PublicReleaseIdempotencyConflict
            projection = (
                repository.replay_projection(
                    scope_type="workspace",
                    scope_id=self._workspace_id,
                    operation="public_release_publish",
                    key_hash=key_hash,
                    request_hash=request_hash,
                )
                if disposition == "replay"
                else None
            )
        return self._result(projection, replayed=True) if projection else None

    def _key_hash(self, idempotency_key: str) -> bytes:
        normalized = idempotency_key.strip()
        if not 1 <= len(normalized) <= 128 or any(
            ord(character) < 0x21 or ord(character) > 0x7E
            for character in normalized
        ):
            raise PublicReleaseIdempotencyConflict
        return hmac.new(self._pepper, normalized.encode(), hashlib.sha256).digest()

    @staticmethod
    def _request_hash(payload: dict[str, object]) -> bytes:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).digest()

    def _lock_id(self) -> int:
        value = int.from_bytes(
            hashlib.sha256(
                f"public-release:{self._workspace_id}".encode()
            ).digest()[:8],
            "big",
        )
        return value - (1 << 64) if value >= (1 << 63) else value

    @staticmethod
    def _result(payload: dict[str, object], *, replayed: bool) -> ReleaseResult:
        return ReleaseResult(
            release_id=UUID(str(payload["release_id"])),
            dataset_version_id=UUID(str(payload["dataset_version_id"])),
            previous_dataset_version_id=(
                UUID(str(payload["previous_dataset_version_id"]))
                if payload["previous_dataset_version_id"] is not None
                else None
            ),
            released_at=datetime.fromisoformat(str(payload["released_at"])),
            created=bool(payload["created"]),
            replayed=replayed,
        )


def _identity_scope(scope: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in scope.items()
        if key in {"currency", "store_id"}
    }
