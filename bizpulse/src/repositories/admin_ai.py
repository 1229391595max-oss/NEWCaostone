"""PostgreSQL authority for administrator AI configuration and safe audit events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import re
from uuid import UUID, uuid4

from sqlalchemy import Connection, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import OperationalError

from src.db.schema import admin_audit_events, ai_control_state


class AIControlBusy(RuntimeError):
    code = "ADMIN_AI_OPERATION_BUSY"


class AIControlKeyBindingError(RuntimeError):
    code = "ADMIN_AI_KEY_UNVERIFIED"


@dataclass(frozen=True, slots=True)
class AIControlProjection:
    workspace_id: str
    operator_enabled: bool
    demo_enabled: bool
    key_name: str | None
    key_version: str | None
    key_reference: str | None
    key_fingerprint: str | None
    verified_at: datetime | None
    key_validation_state: str
    revision: int
    updated_by_operator_id: UUID | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AdminAuditProjection:
    id: UUID
    workspace_id: str
    operator_id: UUID
    action: str
    result: str
    safe_error_code: str | None
    prior_revision: int
    resulting_revision: int
    requested_operator_enabled: bool | None
    requested_demo_enabled: bool | None
    request_id: str
    created_at: datetime = field(repr=False)


class AIControlRepository:
    """Persist per-workspace AI authority without projecting secret material."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get_or_create(
        self,
        workspace_id: str,
        *,
        now: datetime | None = None,
    ) -> AIControlProjection:
        timestamp = now or datetime.now(UTC)
        created = self._connection.execute(
            insert(ai_control_state)
            .values(
                workspace_id=workspace_id,
                operator_enabled=False,
                demo_enabled=False,
                key_name=None,
                key_version=None,
                key_reference=None,
                key_fingerprint=None,
                verified_at=None,
                key_validation_state="unconfigured",
                revision=0,
                updated_by_operator_id=None,
                updated_at=timestamp,
            )
            .on_conflict_do_nothing(index_elements=["workspace_id"])
            .returning(*ai_control_state.c)
        ).mappings().one_or_none()
        if created is not None:
            return AIControlProjection(**created)
        return self._projection_for_workspace(workspace_id)

    def lock(self, workspace_id: str) -> AIControlProjection:
        try:
            row = self._connection.execute(
                select(*ai_control_state.c)
                .where(ai_control_state.c.workspace_id == workspace_id)
                .with_for_update(of=ai_control_state, nowait=True)
            ).mappings().one()
        except OperationalError as error:
            if getattr(error.orig, "sqlstate", None) == "55P03":
                raise AIControlBusy(AIControlBusy.code) from error
            raise
        return AIControlProjection(**row)

    def activate_key(
        self,
        *,
        workspace_id: str,
        expected_revision: int,
        key_name: str,
        key_version: str,
        key_reference: str,
        key_fingerprint: str,
        verified_at: datetime,
        updated_by_operator_id: UUID,
        now: datetime,
    ) -> AIControlProjection | None:
        row = self._connection.execute(
            update(ai_control_state)
            .where(
                ai_control_state.c.workspace_id == workspace_id,
                ai_control_state.c.revision == expected_revision,
            )
            .values(
                key_name=key_name,
                key_version=key_version,
                key_reference=key_reference,
                key_fingerprint=key_fingerprint,
                verified_at=verified_at,
                key_validation_state="verified",
                revision=ai_control_state.c.revision + 1,
                updated_by_operator_id=updated_by_operator_id,
                updated_at=now,
            )
            .returning(*ai_control_state.c)
        ).mappings().one_or_none()
        return AIControlProjection(**row) if row is not None else None

    def set_channels(
        self,
        *,
        workspace_id: str,
        expected_revision: int,
        operator_enabled: bool,
        demo_enabled: bool,
        updated_by_operator_id: UUID,
        now: datetime,
    ) -> AIControlProjection | None:
        if operator_enabled or demo_enabled:
            current = self._connection.execute(
                select(*ai_control_state.c).where(
                    ai_control_state.c.workspace_id == workspace_id,
                    ai_control_state.c.revision == expected_revision,
                )
            ).mappings().one_or_none()
            if current is not None and not self._has_verified_key_binding(current):
                raise AIControlKeyBindingError(AIControlKeyBindingError.code)
        row = self._connection.execute(
            update(ai_control_state)
            .where(
                ai_control_state.c.workspace_id == workspace_id,
                ai_control_state.c.revision == expected_revision,
            )
            .values(
                operator_enabled=operator_enabled,
                demo_enabled=demo_enabled,
                revision=ai_control_state.c.revision + 1,
                updated_by_operator_id=updated_by_operator_id,
                updated_at=now,
            )
            .returning(*ai_control_state.c)
        ).mappings().one_or_none()
        return AIControlProjection(**row) if row is not None else None

    def append_audit(
        self,
        *,
        workspace_id: str,
        operator_id: UUID,
        action: str,
        result: str,
        safe_error_code: str | None,
        prior_revision: int,
        resulting_revision: int,
        request_id: str,
        now: datetime,
        requested_operator_enabled: bool | None = None,
        requested_demo_enabled: bool | None = None,
    ) -> AdminAuditProjection:
        row = self._connection.execute(
            admin_audit_events.insert()
            .values(
                id=uuid4(),
                workspace_id=workspace_id,
                operator_id=operator_id,
                action=action,
                result=result,
                safe_error_code=safe_error_code,
                prior_revision=prior_revision,
                resulting_revision=resulting_revision,
                requested_operator_enabled=requested_operator_enabled,
                requested_demo_enabled=requested_demo_enabled,
                request_id=request_id,
                created_at=now,
            )
            .returning(*admin_audit_events.c)
        ).mappings().one()
        return AdminAuditProjection(**row)

    def mutation_audit(
        self,
        workspace_id: str,
        request_ids: tuple[str, ...],
    ) -> tuple[AdminAuditProjection, ...]:
        if (
            not 1 <= len(request_ids) <= 16
            or len(set(request_ids)) != len(request_ids)
            or any(
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,127}", value)
                is None
                for value in request_ids
            )
        ):
            raise ValueError("admin_audit_request_ids_invalid")
        rows = self._connection.execute(
            select(*admin_audit_events.c).where(
                admin_audit_events.c.workspace_id == workspace_id,
                admin_audit_events.c.request_id.in_(request_ids),
            )
        ).mappings()
        by_request = {
            row["request_id"]: AdminAuditProjection(**row) for row in rows
        }
        if set(by_request) != set(request_ids):
            return ()
        return tuple(by_request[request_id] for request_id in request_ids)

    def _projection_for_workspace(self, workspace_id: str) -> AIControlProjection:
        row = self._connection.execute(
            select(*ai_control_state.c).where(
                ai_control_state.c.workspace_id == workspace_id
            )
        ).mappings().one()
        return AIControlProjection(**row)

    @staticmethod
    def _has_verified_key_binding(row: dict[str, object]) -> bool:
        key_name = row["key_name"]
        key_version = row["key_version"]
        key_reference = row["key_reference"]
        key_fingerprint = row["key_fingerprint"]
        return (
            isinstance(key_name, str)
            and isinstance(key_version, str)
            and isinstance(key_reference, str)
            and key_reference == f"{key_name}/{key_version}"
            and isinstance(key_fingerprint, str)
            and re.fullmatch(r"[0-9a-f]{64}", key_fingerprint) is not None
            and row["verified_at"] is not None
            and row["key_validation_state"] == "verified"
        )
