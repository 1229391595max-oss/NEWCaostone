"""Opaque operator, viewer-session, and idempotency repositories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hmac
from uuid import UUID, uuid4

from sqlalchemy import Connection, delete, exists, func, insert, or_, select, update

from src.db.schema import (
    action_card_revisions,
    ai_chat_saved_records,
    ai_chat_turns,
    demo_action_overlays,
    demo_sessions,
    idempotency_receipts,
    operator_sessions,
)


@dataclass(frozen=True, slots=True)
class OperatorSessionProjection:
    id: UUID
    workspace_id: str
    operator_id: UUID
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class OperatorSessionRevocationResult:
    revoked_session_count: int
    deleted_ephemeral_chat_count: int


@dataclass(frozen=True, slots=True)
class DemoSessionProjection:
    id: UUID
    workspace_id: str
    dataset_version_id: UUID | None
    forecast_id: UUID | None
    profit_bridge_id: UUID | None
    demo_data_imported_at: datetime | None
    chat_epoch: int
    status: str
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    ended_at: datetime | None


@dataclass(frozen=True, slots=True)
class IdempotencyReceiptProjection:
    id: UUID
    scope_type: str
    scope_id: str
    operation: str
    response_status: int | None
    outcome: str
    created_at: datetime
    expires_at: datetime


class SessionRepository:
    """Lookup sessions by hashes while returning hash-free projections."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create_operator_session(
        self,
        *,
        session_id: UUID,
        workspace_id: str,
        operator_id: UUID,
        token_hash: bytes,
        csrf_hash: bytes,
        now: datetime,
        idle_expires_at: datetime,
        absolute_expires_at: datetime,
    ) -> OperatorSessionProjection:
        self._connection.execute(
            insert(operator_sessions).values(
                id=session_id,
                workspace_id=workspace_id,
                operator_id=operator_id,
                token_hash=token_hash,
                csrf_hash=csrf_hash,
                created_at=now,
                last_seen_at=now,
                idle_expires_at=idle_expires_at,
                absolute_expires_at=absolute_expires_at,
                revoked_at=None,
            )
        )
        return OperatorSessionProjection(
            id=session_id,
            workspace_id=workspace_id,
            operator_id=operator_id,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
            revoked_at=None,
        )

    def create_demo_session(
        self,
        *,
        session_id: UUID,
        workspace_id: str,
        token_hash: bytes,
        csrf_hash: bytes,
        source_address_hash: bytes,
        now: datetime,
        idle_expires_at: datetime,
        absolute_expires_at: datetime,
        dataset_version_id: UUID | None = None,
        forecast_id: UUID | None = None,
        profit_bridge_id: UUID | None = None,
    ) -> DemoSessionProjection:
        self._connection.execute(
            insert(demo_sessions).values(
                id=session_id,
                workspace_id=workspace_id,
                token_hash=token_hash,
                csrf_hash=csrf_hash,
                source_address_hash=source_address_hash,
                dataset_version_id=dataset_version_id,
                forecast_id=forecast_id,
                profit_bridge_id=profit_bridge_id,
                chat_epoch=0,
                status="active",
                created_at=now,
                last_seen_at=now,
                idle_expires_at=idle_expires_at,
                absolute_expires_at=absolute_expires_at,
                ended_at=None,
            )
        )
        return DemoSessionProjection(
            id=session_id,
            workspace_id=workspace_id,
            dataset_version_id=dataset_version_id,
            forecast_id=forecast_id,
            profit_bridge_id=profit_bridge_id,
            demo_data_imported_at=None,
            chat_epoch=0,
            status="active",
            created_at=now,
            last_seen_at=now,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
            ended_at=None,
        )

    def lock_demo_session_source(self, source_address_hash: bytes) -> None:
        """Serialize admissions for one opaque source fingerprint."""

        advisory_key = int.from_bytes(
            bytes(source_address_hash)[:8],
            byteorder="big",
            signed=True,
        )
        self._connection.execute(select(func.pg_advisory_xact_lock(advisory_key)))

    def count_demo_sessions_for_source_since(
        self,
        source_address_hash: bytes,
        since: datetime,
    ) -> int:
        """Count all admissions in the rolling window, including ended sessions."""

        return int(
            self._connection.scalar(
                select(func.count())
                .select_from(demo_sessions)
                .where(
                    demo_sessions.c.source_address_hash == source_address_hash,
                    demo_sessions.c.created_at >= since,
                )
            )
            or 0
        )

    def get_active_operator_session(
        self,
        token_hash: bytes,
        now: datetime,
    ) -> OperatorSessionProjection | None:
        row = self._connection.execute(
            select(
                operator_sessions.c.id,
                operator_sessions.c.workspace_id,
                operator_sessions.c.operator_id,
                operator_sessions.c.created_at,
                operator_sessions.c.last_seen_at,
                operator_sessions.c.idle_expires_at,
                operator_sessions.c.absolute_expires_at,
                operator_sessions.c.revoked_at,
            ).where(
                operator_sessions.c.token_hash == token_hash,
                operator_sessions.c.revoked_at.is_(None),
                operator_sessions.c.idle_expires_at > now,
                operator_sessions.c.absolute_expires_at > now,
            )
        ).mappings().one_or_none()
        return OperatorSessionProjection(**row) if row is not None else None

    def get_active_demo_session(
        self,
        token_hash: bytes,
        now: datetime,
    ) -> DemoSessionProjection | None:
        row = self._connection.execute(
            select(
                demo_sessions.c.id,
                demo_sessions.c.workspace_id,
                demo_sessions.c.dataset_version_id,
                demo_sessions.c.forecast_id,
                demo_sessions.c.profit_bridge_id,
                demo_sessions.c.demo_data_imported_at,
                demo_sessions.c.chat_epoch,
                demo_sessions.c.status,
                demo_sessions.c.created_at,
                demo_sessions.c.last_seen_at,
                demo_sessions.c.idle_expires_at,
                demo_sessions.c.absolute_expires_at,
                demo_sessions.c.ended_at,
            ).where(
                demo_sessions.c.token_hash == token_hash,
                demo_sessions.c.status == "active",
                demo_sessions.c.ended_at.is_(None),
                demo_sessions.c.idle_expires_at > now,
                demo_sessions.c.absolute_expires_at > now,
            )
        ).mappings().one_or_none()
        return DemoSessionProjection(**row) if row is not None else None

    def create_idempotency_receipt(
        self,
        *,
        scope_type: str,
        scope_id: str,
        operation: str,
        key_hash: bytes,
        request_hash: bytes,
        created_at: datetime,
        expires_at: datetime,
    ) -> IdempotencyReceiptProjection:
        receipt_id = uuid4()
        self._connection.execute(
            insert(idempotency_receipts).values(
                id=receipt_id,
                scope_type=scope_type,
                scope_id=scope_id,
                operation=operation,
                key_hash=key_hash,
                request_hash=request_hash,
                response_status=None,
                response_body_hash=None,
                outcome="in_progress",
                created_at=created_at,
                expires_at=expires_at,
            )
        )
        return IdempotencyReceiptProjection(
            id=receipt_id,
            scope_type=scope_type,
            scope_id=scope_id,
            operation=operation,
            response_status=None,
            outcome="in_progress",
            created_at=created_at,
            expires_at=expires_at,
        )

    def operator_csrf_matches(self, session_id: UUID, candidate_hash: bytes) -> bool:
        stored_hash = self._connection.scalar(
            select(operator_sessions.c.csrf_hash).where(
                operator_sessions.c.id == session_id,
                operator_sessions.c.revoked_at.is_(None),
            )
        )
        return stored_hash is not None and hmac.compare_digest(
            bytes(stored_hash), candidate_hash
        )

    def demo_csrf_matches(self, session_id: UUID, candidate_hash: bytes) -> bool:
        stored_hash = self._connection.scalar(
            select(demo_sessions.c.csrf_hash).where(
                demo_sessions.c.id == session_id,
                demo_sessions.c.status == "active",
                demo_sessions.c.ended_at.is_(None),
            )
        )
        return stored_hash is not None and hmac.compare_digest(
            bytes(stored_hash), candidate_hash
        )

    def touch_operator_session(
        self,
        session_id: UUID,
        *,
        now: datetime,
        idle_expires_at: datetime,
    ) -> OperatorSessionProjection | None:
        row = self._connection.execute(
            update(operator_sessions)
            .where(
                operator_sessions.c.id == session_id,
                operator_sessions.c.revoked_at.is_(None),
                operator_sessions.c.idle_expires_at > now,
                operator_sessions.c.absolute_expires_at > now,
            )
            .values(last_seen_at=now, idle_expires_at=idle_expires_at)
            .returning(
                operator_sessions.c.id,
                operator_sessions.c.workspace_id,
                operator_sessions.c.operator_id,
                operator_sessions.c.created_at,
                operator_sessions.c.last_seen_at,
                operator_sessions.c.idle_expires_at,
                operator_sessions.c.absolute_expires_at,
                operator_sessions.c.revoked_at,
            )
        ).mappings().one_or_none()
        return OperatorSessionProjection(**row) if row is not None else None

    def touch_demo_session(
        self,
        session_id: UUID,
        *,
        now: datetime,
        idle_expires_at: datetime,
    ) -> DemoSessionProjection | None:
        row = self._connection.execute(
            update(demo_sessions)
            .where(
                demo_sessions.c.id == session_id,
                demo_sessions.c.status == "active",
                demo_sessions.c.ended_at.is_(None),
                demo_sessions.c.idle_expires_at > now,
                demo_sessions.c.absolute_expires_at > now,
            )
            .values(last_seen_at=now, idle_expires_at=idle_expires_at)
            .returning(
                demo_sessions.c.id,
                demo_sessions.c.workspace_id,
                demo_sessions.c.dataset_version_id,
                demo_sessions.c.forecast_id,
                demo_sessions.c.profit_bridge_id,
                demo_sessions.c.demo_data_imported_at,
                demo_sessions.c.chat_epoch,
                demo_sessions.c.status,
                demo_sessions.c.created_at,
                demo_sessions.c.last_seen_at,
                demo_sessions.c.idle_expires_at,
                demo_sessions.c.absolute_expires_at,
                demo_sessions.c.ended_at,
            )
        ).mappings().one_or_none()
        return DemoSessionProjection(**row) if row is not None else None

    def import_demo_data(
        self,
        session_id: UUID,
        *,
        now: datetime,
    ) -> DemoSessionProjection | None:
        """Set only the session activation marker, preserving the pinned release."""

        row = self._connection.execute(
            update(demo_sessions)
            .where(
                demo_sessions.c.id == session_id,
                demo_sessions.c.status == "active",
                demo_sessions.c.ended_at.is_(None),
                demo_sessions.c.idle_expires_at > now,
                demo_sessions.c.absolute_expires_at > now,
            )
            .values(
                demo_data_imported_at=func.coalesce(
                    demo_sessions.c.demo_data_imported_at,
                    now,
                )
            )
            .returning(
                demo_sessions.c.id,
                demo_sessions.c.workspace_id,
                demo_sessions.c.dataset_version_id,
                demo_sessions.c.forecast_id,
                demo_sessions.c.profit_bridge_id,
                demo_sessions.c.demo_data_imported_at,
                demo_sessions.c.chat_epoch,
                demo_sessions.c.status,
                demo_sessions.c.created_at,
                demo_sessions.c.last_seen_at,
                demo_sessions.c.idle_expires_at,
                demo_sessions.c.absolute_expires_at,
                demo_sessions.c.ended_at,
            )
        ).mappings().one_or_none()
        return DemoSessionProjection(**row) if row is not None else None

    def revoke_operator_session(self, session_id: UUID, now: datetime) -> bool:
        result = self._connection.execute(
            update(operator_sessions)
            .where(
                operator_sessions.c.id == session_id,
                operator_sessions.c.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        changed = bool(result.rowcount)
        if changed:
            self._delete_ephemeral_chat("operator", (session_id,))
        return changed

    def revoke_active_for_operator(
        self,
        operator_id: UUID,
        *,
        now: datetime,
    ) -> OperatorSessionRevocationResult:
        """Revoke every live session for one locked operator in this transaction."""

        active_ids = tuple(
            self._connection.scalars(
                select(operator_sessions.c.id)
                .where(
                    operator_sessions.c.operator_id == operator_id,
                    operator_sessions.c.revoked_at.is_(None),
                )
                .with_for_update(of=operator_sessions)
            )
        )
        if not active_ids:
            return OperatorSessionRevocationResult(
                revoked_session_count=0,
                deleted_ephemeral_chat_count=0,
            )
        revoked_ids = tuple(
            self._connection.scalars(
                update(operator_sessions)
                .where(
                    operator_sessions.c.id.in_(active_ids),
                    operator_sessions.c.revoked_at.is_(None),
                )
                .values(revoked_at=now)
                .returning(operator_sessions.c.id)
            )
        )
        deleted_count = self._delete_ephemeral_chat("operator", revoked_ids)
        return OperatorSessionRevocationResult(
            revoked_session_count=len(revoked_ids),
            deleted_ephemeral_chat_count=deleted_count,
        )

    def end_demo_session(self, session_id: UUID, now: datetime) -> bool:
        result = self._connection.execute(
            update(demo_sessions)
            .where(
                demo_sessions.c.id == session_id,
                demo_sessions.c.status == "active",
                demo_sessions.c.ended_at.is_(None),
            )
            .values(status="ended", ended_at=now)
        )
        changed = bool(result.rowcount)
        if changed:
            self._connection.execute(
                delete(demo_action_overlays).where(
                    demo_action_overlays.c.demo_session_id == session_id
                )
            )
            self._delete_ephemeral_chat("demo", (session_id,))
        return changed

    def lock_demo_chat_epoch(
        self,
        session_id: UUID,
        workspace_id: str,
        dataset_version_id: UUID,
        expected_epoch: int,
        now: datetime,
    ) -> bool:
        return self._connection.scalar(
            select(demo_sessions.c.id)
            .where(
                demo_sessions.c.id == session_id,
                demo_sessions.c.workspace_id == workspace_id,
                demo_sessions.c.dataset_version_id == dataset_version_id,
                demo_sessions.c.chat_epoch == expected_epoch,
                demo_sessions.c.status == "active",
                demo_sessions.c.ended_at.is_(None),
                demo_sessions.c.idle_expires_at > now,
                demo_sessions.c.absolute_expires_at > now,
            )
            .with_for_update(of=demo_sessions)
        ) is not None

    def advance_demo_chat_epoch(
        self,
        session_id: UUID,
        workspace_id: str,
        dataset_version_id: UUID,
        expected_epoch: int,
        now: datetime,
    ) -> int | None:
        return self._connection.scalar(
            update(demo_sessions)
            .where(
                demo_sessions.c.id == session_id,
                demo_sessions.c.workspace_id == workspace_id,
                demo_sessions.c.dataset_version_id == dataset_version_id,
                demo_sessions.c.chat_epoch == expected_epoch,
                demo_sessions.c.status == "active",
                demo_sessions.c.ended_at.is_(None),
                demo_sessions.c.idle_expires_at > now,
                demo_sessions.c.absolute_expires_at > now,
            )
            .values(chat_epoch=demo_sessions.c.chat_epoch + 1)
            .returning(demo_sessions.c.chat_epoch)
        )

    def clear_demo_action_overlays(self, session_id: UUID) -> int:
        return int(
            self._connection.execute(
                delete(demo_action_overlays).where(
                    demo_action_overlays.c.demo_session_id == session_id
                )
            ).rowcount
        )

    def expire_demo_sessions(self, now: datetime) -> int:
        expiring_ids = tuple(
            self._connection.scalars(
                update(demo_sessions)
                .where(
                    demo_sessions.c.status == "active",
                    demo_sessions.c.ended_at.is_(None),
                    or_(
                        demo_sessions.c.idle_expires_at <= now,
                        demo_sessions.c.absolute_expires_at <= now,
                    ),
                )
                .values(status="expired", ended_at=now)
                .returning(demo_sessions.c.id)
            )
        )
        if not expiring_ids:
            return 0
        self._connection.execute(
            delete(demo_action_overlays).where(
                demo_action_overlays.c.demo_session_id.in_(expiring_ids)
            )
        )
        self._delete_ephemeral_chat("demo", expiring_ids)
        return len(expiring_ids)

    def _delete_ephemeral_chat(
        self,
        actor_kind: str,
        session_ids: tuple[UUID, ...],
    ) -> int:
        if not session_ids:
            return 0
        session_column = (
            ai_chat_turns.c.operator_session_id
            if actor_kind == "operator"
            else ai_chat_turns.c.demo_session_id
        )
        saved = exists(
            select(ai_chat_saved_records.c.id).where(
                ai_chat_saved_records.c.turn_id == ai_chat_turns.c.id
            )
        )
        action_authority = exists(
            select(action_card_revisions.c.id).where(
                action_card_revisions.c.chat_turn_id == ai_chat_turns.c.id
            )
        )
        result = self._connection.execute(
            delete(ai_chat_turns).where(
                ai_chat_turns.c.actor_kind == actor_kind,
                session_column.in_(session_ids),
                ~saved,
                ~action_authority,
            )
        )
        return int(result.rowcount or 0)
