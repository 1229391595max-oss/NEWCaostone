"""Secret-free administrator projections over existing application authorities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Literal
from uuid import UUID

from sqlalchemy import Engine, func, select

from src.db.readiness import readiness as database_readiness
from src.db.schema import import_workflows
from src.repositories.admin_ai import AIControlProjection
from src.repositories.imports import ImportRepository

ComponentState = Literal["ready", "unavailable"]
AIProjectionState = Literal["ready", "unavailable"]
_SAFE_FAILURE_CODE = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
_ACTIONABLE_IMPORT_STATUSES = ("rejected", "failed")


@dataclass(frozen=True, slots=True)
class AdminSystemProjection:
    database: ComponentState
    blob: ComponentState
    configuration: Literal["valid", "invalid"]
    migration: str | None


@dataclass(frozen=True, slots=True)
class AdminPublishedDatasetProjection:
    dataset_version_id: UUID
    version_number: int
    released_at: datetime


@dataclass(frozen=True, slots=True)
class AdminImportProjection:
    workflow_id: UUID
    status: str
    failure_code: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AdminActivityProjection:
    kind: Literal["import", "publish"]
    status: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class AdminCredentialProjection:
    configured: bool
    fingerprint: str | None
    verified_at: datetime | None


@dataclass(frozen=True, slots=True)
class AdminAIProjection:
    status: AIProjectionState
    revision: int | None
    operator_enabled: bool
    demo_enabled: bool
    credential: AdminCredentialProjection


@dataclass(frozen=True, slots=True)
class AdminSummaryProjection:
    system: AdminSystemProjection
    published_dataset: AdminPublishedDatasetProjection | None
    latest_import: AdminImportProjection | None
    actionable_failure_count: int
    recent_activity: tuple[AdminActivityProjection, ...]
    ai: AdminAIProjection | None


def project_ai_control(state: AIControlProjection) -> AdminAIProjection:
    """Drop every secret-locating field from the database control projection."""

    fingerprint = state.key_fingerprint
    configured = (
        isinstance(state.key_name, str)
        and bool(state.key_name)
        and isinstance(state.key_version, str)
        and bool(state.key_version)
        and state.key_reference == f"{state.key_name}/{state.key_version}"
        and isinstance(fingerprint, str)
        and re.fullmatch(r"[0-9a-f]{64}", fingerprint) is not None
        and state.verified_at is not None
        and state.key_validation_state == "verified"
    )
    return AdminAIProjection(
        status="ready",
        revision=state.revision,
        operator_enabled=state.operator_enabled,
        demo_enabled=state.demo_enabled,
        credential=AdminCredentialProjection(
            configured=configured,
            fingerprint=fingerprint[:8] if configured else None,
            verified_at=state.verified_at if configured else None,
        ),
    )


def unavailable_ai_projection() -> AdminAIProjection:
    return AdminAIProjection(
        status="unavailable",
        revision=None,
        operator_enabled=False,
        demo_enabled=False,
        credential=AdminCredentialProjection(
            configured=False,
            fingerprint=None,
            verified_at=None,
        ),
    )


class AdminSummaryService:
    """Compose a bounded cockpit view without adding data-workflow authority."""

    def __init__(
        self,
        *,
        engine: Engine,
        workspace_id: str,
        dataset_service,
        public_release_service,
        ai_control_service,
        workflow_storage,
        database_probe=database_readiness,
    ) -> None:
        self._engine = engine
        self._workspace_id = workspace_id
        self._datasets = dataset_service
        self._releases = public_release_service
        self._ai_control = ai_control_service
        self._storage = workflow_storage
        self._database_probe = database_probe

    def get(self) -> AdminSummaryProjection:
        system = self._system_projection()
        published = self._published_dataset()
        imports, failure_count = self._imports()
        ai = self._ai_projection()
        activity = [
            AdminActivityProjection(
                kind="import",
                status=item.status,
                occurred_at=item.updated_at,
            )
            for item in imports[:9]
        ]
        if published is not None:
            activity.append(
                AdminActivityProjection(
                    kind="publish",
                    status="published",
                    occurred_at=published.released_at,
                )
            )
        activity.sort(key=lambda item: item.occurred_at, reverse=True)
        return AdminSummaryProjection(
            system=system,
            published_dataset=published,
            latest_import=imports[0] if imports else None,
            actionable_failure_count=failure_count,
            recent_activity=tuple(activity[:10]),
            ai=ai,
        )

    def _system_projection(self) -> AdminSystemProjection:
        database = "unavailable"
        migration = None
        try:
            result = self._database_probe(self._engine)
            if result.writable:
                database = "ready"
                migration = result.revision
        except Exception:
            pass

        blob = "unavailable"
        try:
            if self._storage is not None:
                self._storage.check_readiness()
                blob = "ready"
        except Exception:
            pass
        return AdminSystemProjection(
            database=database,
            blob=blob,
            configuration="valid",
            migration=migration,
        )

    def _published_dataset(self) -> AdminPublishedDatasetProjection | None:
        if self._datasets is None or self._releases is None:
            return None
        try:
            release = self._releases.current()
            if release is None:
                return None
            version = next(
                (
                    item
                    for item in self._datasets.list_versions()
                    if item.id == release.dataset_version_id
                ),
                None,
            )
            if version is None:
                return None
            return AdminPublishedDatasetProjection(
                dataset_version_id=version.id,
                version_number=version.version_number,
                released_at=release.released_at,
            )
        except Exception:
            return None

    def _imports(self) -> tuple[tuple[AdminImportProjection, ...], int]:
        try:
            with self._engine.connect() as connection:
                workflow_ids = tuple(
                    connection.scalars(
                        select(import_workflows.c.id)
                        .where(import_workflows.c.workspace_id == self._workspace_id)
                        .order_by(
                            import_workflows.c.updated_at.desc(),
                            import_workflows.c.id,
                        )
                        .limit(10)
                    )
                )
                failure_count = int(
                    connection.scalar(
                        select(func.count())
                        .select_from(import_workflows)
                        .where(
                            import_workflows.c.workspace_id == self._workspace_id,
                            (
                                import_workflows.c.failure_code.is_not(None)
                                | import_workflows.c.status.in_(
                                    _ACTIONABLE_IMPORT_STATUSES
                                )
                            ),
                        )
                    )
                    or 0
                )
                repository = ImportRepository(connection)
                workflows = tuple(
                    workflow
                    for workflow_id in workflow_ids
                    if (
                        workflow := repository.get_workspace_workflow(
                            self._workspace_id,
                            workflow_id,
                        )
                    )
                    is not None
                )
        except Exception:
            return (), 0
        return (
            tuple(
                AdminImportProjection(
                    workflow_id=workflow.id,
                    status=workflow.status,
                    failure_code=self._safe_failure_code(workflow.failure_code),
                    updated_at=workflow.updated_at,
                )
                for workflow in workflows
            ),
            failure_count,
        )

    def _ai_projection(self) -> AdminAIProjection:
        if self._ai_control is None:
            return unavailable_ai_projection()
        try:
            return project_ai_control(self._ai_control.get())
        except Exception:
            return unavailable_ai_projection()

    @staticmethod
    def _safe_failure_code(code: str | None) -> str | None:
        if code is None:
            return None
        if _SAFE_FAILURE_CODE.fullmatch(code) is None:
            return "IMPORT_FAILED"
        return code
