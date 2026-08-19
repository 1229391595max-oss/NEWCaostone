"""PostgreSQL authority for action cards and append-only child records."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection, delete, func, insert, select, update

from src.actions.contracts import (
    ActionCard,
    ActionDecision,
    ActionExport,
    ActionOutcome,
    ActionRevision,
    DemoActionOverlay,
    FactRef,
)
from src.db.schema import (
    action_card_revisions,
    action_cards,
    action_decisions,
    action_exports,
    action_outcomes,
    demo_action_overlays,
    demo_sessions,
)


class ActionRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def find_create(self, workspace_id: str, key_hash: bytes) -> ActionCard | None:
        action_id = self._connection.scalar(
            select(action_cards.c.id).where(
                action_cards.c.workspace_id == workspace_id,
                action_cards.c.idempotency_key_hash == key_hash,
            )
        )
        return self.get(workspace_id, action_id) if action_id is not None else None

    def find_create_request_hash(
        self,
        workspace_id: str,
        key_hash: bytes,
    ) -> bytes | None:
        value = self._connection.scalar(
            select(action_cards.c.request_hash).where(
                action_cards.c.workspace_id == workspace_id,
                action_cards.c.idempotency_key_hash == key_hash,
            )
        )
        return bytes(value) if value is not None else None

    def create(
        self,
        *,
        action_id: UUID,
        workspace_id: str,
        dataset_version_id: UUID,
        source_type: str,
        key_hash: bytes,
        request_hash: bytes,
        revision: dict[str, object],
        now: datetime,
    ) -> None:
        revision_values = dict(revision)
        self._connection.execute(
            insert(action_cards).values(
                id=action_id,
                workspace_id=workspace_id,
                dataset_version_id=dataset_version_id,
                source_type=source_type,
                status="new",
                current_revision=1,
                idempotency_key_hash=key_hash,
                request_hash=request_hash,
                created_at=now,
                updated_at=now,
                terminal_at=None,
            )
        )
        self._connection.execute(
            insert(action_card_revisions).values(
                id=revision_values.pop("id"),
                action_id=action_id,
                revision=1,
                created_at=now,
                **revision_values,
            )
        )

    def get(
        self,
        workspace_id: str,
        action_id: UUID,
        *,
        for_update: bool = False,
        child_before: datetime | None = None,
    ) -> ActionCard | None:
        statement = select(*action_cards.c).where(
            action_cards.c.workspace_id == workspace_id,
            action_cards.c.id == action_id,
        )
        if for_update:
            statement = statement.with_for_update()
        row = self._connection.execute(statement).mappings().one_or_none()
        if row is None:
            return None
        revision_rows = self._connection.execute(
            select(*action_card_revisions.c)
            .where(action_card_revisions.c.action_id == action_id)
            .order_by(action_card_revisions.c.revision)
        ).mappings()
        decision_rows = self._connection.execute(
            select(*action_decisions.c)
            .where(action_decisions.c.action_id == action_id)
            .order_by(action_decisions.c.decision_ordinal)
        ).mappings()
        export_statement = select(*action_exports.c).where(
            action_exports.c.action_id == action_id
        )
        outcome_statement = select(*action_outcomes.c).where(
            action_outcomes.c.action_id == action_id
        )
        if child_before is not None:
            export_statement = export_statement.where(
                action_exports.c.created_at < child_before
            )
            outcome_statement = outcome_statement.where(
                action_outcomes.c.created_at < child_before
            )
        export_rows = self._connection.execute(
            export_statement.order_by(action_exports.c.created_at, action_exports.c.id)
        ).mappings()
        outcome_rows = self._connection.execute(
            outcome_statement.order_by(action_outcomes.c.outcome_revision)
        ).mappings()
        return ActionCard(
            id=row["id"],
            workspace_id=row["workspace_id"],
            dataset_version_id=row["dataset_version_id"],
            source_type=row["source_type"],
            status=row["status"],
            current_revision=row["current_revision"],
            revisions=tuple(_revision(item) for item in revision_rows),
            decisions=tuple(
                ActionDecision(
                    id=item["id"],
                    decision_ordinal=item["decision_ordinal"],
                    command=item["command"],
                    action_revision=item["action_revision"],
                    reason=item["reason"],
                    decided_by=item["decided_by"],
                    created_at=item["created_at"],
                )
                for item in decision_rows
            ),
            exports=tuple(_export(item) for item in export_rows),
            outcomes=tuple(_outcome(item) for item in outcome_rows),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            terminal_at=row["terminal_at"],
        )

    def list_for_version(
        self,
        workspace_id: str,
        dataset_version_id: UUID,
    ) -> tuple[ActionCard, ...]:
        ids = self._connection.scalars(
            select(action_cards.c.id)
            .where(
                action_cards.c.workspace_id == workspace_id,
                action_cards.c.dataset_version_id == dataset_version_id,
            )
            .order_by(action_cards.c.created_at, action_cards.c.id)
        )
        return tuple(
            card
            for action_id in ids
            if (card := self.get(workspace_id, action_id)) is not None
        )

    def list_public_for_session(
        self,
        workspace_id: str,
        dataset_version_id: UUID,
        session_created_at: datetime,
    ) -> tuple[ActionCard, ...]:
        ids = self._connection.scalars(
            select(action_cards.c.id)
            .where(
                action_cards.c.workspace_id == workspace_id,
                action_cards.c.dataset_version_id == dataset_version_id,
                action_cards.c.status == "approved",
                action_cards.c.terminal_at < session_created_at,
            )
            .order_by(action_cards.c.created_at, action_cards.c.id)
        )
        return tuple(
            card
            for action_id in ids
            if (
                card := self.get(
                    workspace_id,
                    action_id,
                    child_before=session_created_at,
                )
            )
            is not None
        )

    def find_decision(self, action_id: UUID, key_hash: bytes):
        return self._connection.execute(
            select(*action_decisions.c).where(
                action_decisions.c.action_id == action_id,
                action_decisions.c.idempotency_key_hash == key_hash,
            )
        ).mappings().one_or_none()

    def apply_decision(
        self,
        *,
        action_id: UUID,
        expected_revision: int,
        command: str,
        next_status: str,
        reason: str,
        decision_id: UUID,
        decision_ordinal: int,
        key_hash: bytes,
        request_hash: bytes,
        now: datetime,
        new_revision: dict[str, object] | None = None,
    ) -> bool:
        next_revision = expected_revision + (1 if new_revision is not None else 0)
        terminal_at = now if next_status in {"approved", "dismissed"} else None
        changed = self._connection.execute(
            update(action_cards)
            .where(
                action_cards.c.id == action_id,
                action_cards.c.current_revision == expected_revision,
            )
            .values(
                status=next_status,
                current_revision=next_revision,
                updated_at=now,
                terminal_at=terminal_at,
            )
            .returning(action_cards.c.id)
        ).scalar_one_or_none()
        if changed is None:
            return False
        if new_revision is not None:
            revision_values = dict(new_revision)
            self._connection.execute(
                insert(action_card_revisions).values(
                    id=revision_values.pop("id"),
                    action_id=action_id,
                    revision=next_revision,
                    created_at=now,
                    **revision_values,
                )
            )
        self._connection.execute(
            insert(action_decisions).values(
                id=decision_id,
                action_id=action_id,
                action_revision=next_revision,
                decision_ordinal=decision_ordinal,
                command=command,
                reason=reason,
                decided_by="single_operator",
                idempotency_key_hash=key_hash,
                request_hash=request_hash,
                created_at=now,
            )
        )
        return True

    def find_export(self, action_id: UUID, key_hash: bytes) -> ActionExport | None:
        row = self.find_export_record(action_id, key_hash)
        return _export(row) if row is not None else None

    def find_export_record(self, action_id: UUID, key_hash: bytes):
        return self._connection.execute(
            select(*action_exports.c).where(
                action_exports.c.action_id == action_id,
                action_exports.c.idempotency_key_hash == key_hash,
            )
        ).mappings().one_or_none()

    def add_export(self, values: dict[str, object]) -> ActionExport:
        row = self._connection.execute(
            insert(action_exports).values(**values).returning(*action_exports.c)
        ).mappings().one()
        return _export(row)

    def get_export(self, action_id: UUID, export_id: UUID) -> ActionExport | None:
        row = self._connection.execute(
            select(*action_exports.c).where(
                action_exports.c.action_id == action_id,
                action_exports.c.id == export_id,
            )
        ).mappings().one_or_none()
        return _export(row) if row is not None else None

    def find_outcome(self, action_id: UUID, key_hash: bytes) -> ActionOutcome | None:
        row = self.find_outcome_record(action_id, key_hash)
        return _outcome(row) if row is not None else None

    def find_outcome_record(self, action_id: UUID, key_hash: bytes):
        return self._connection.execute(
            select(*action_outcomes.c).where(
                action_outcomes.c.action_id == action_id,
                action_outcomes.c.idempotency_key_hash == key_hash,
            )
        ).mappings().one_or_none()

    def next_outcome_revision(self, action_id: UUID) -> int:
        current = self._connection.scalar(
            select(func.max(action_outcomes.c.outcome_revision)).where(
                action_outcomes.c.action_id == action_id
            )
        )
        return int(current or 0) + 1

    def add_outcome(self, values: dict[str, object]) -> ActionOutcome:
        row = self._connection.execute(
            insert(action_outcomes).values(**values).returning(*action_outcomes.c)
        ).mappings().one()
        return _outcome(row)

    def list_overlays(
        self,
        session_id: UUID,
        action_id: UUID,
    ) -> tuple[DemoActionOverlay, ...]:
        rows = self._connection.execute(
            select(*demo_action_overlays.c)
            .where(
                demo_action_overlays.c.demo_session_id == session_id,
                demo_action_overlays.c.action_id == action_id,
            )
            .order_by(demo_action_overlays.c.overlay_revision)
        ).mappings()
        return tuple(_overlay(row) for row in rows)

    def find_overlay(self, session_id: UUID, key_hash: bytes):
        row = self.find_overlay_record(session_id, key_hash)
        return _overlay(row) if row is not None else None

    def viewer_template_eligible(
        self,
        session_id: UUID,
        action_id: UUID,
        now: datetime,
    ) -> bool:
        eligible = self._connection.scalar(
            select(demo_sessions.c.id)
            .select_from(
                demo_sessions.join(
                    action_cards,
                    (action_cards.c.workspace_id == demo_sessions.c.workspace_id)
                    & (
                        action_cards.c.dataset_version_id
                        == demo_sessions.c.dataset_version_id
                    ),
                )
            )
            .where(
                demo_sessions.c.id == session_id,
                demo_sessions.c.status == "active",
                demo_sessions.c.ended_at.is_(None),
                demo_sessions.c.idle_expires_at > now,
                demo_sessions.c.absolute_expires_at > now,
                action_cards.c.id == action_id,
                action_cards.c.status == "approved",
                action_cards.c.terminal_at < demo_sessions.c.created_at,
            )
            .with_for_update(of=demo_sessions)
        )
        return eligible is not None

    def find_overlay_record(self, session_id: UUID, key_hash: bytes):
        return self._connection.execute(
            select(*demo_action_overlays.c).where(
                demo_action_overlays.c.demo_session_id == session_id,
                demo_action_overlays.c.idempotency_key_hash == key_hash,
            )
        ).mappings().one_or_none()

    def add_overlay(self, values: dict[str, object]) -> DemoActionOverlay:
        row = self._connection.execute(
            insert(demo_action_overlays)
            .values(**values)
            .returning(*demo_action_overlays.c)
        ).mappings().one()
        return _overlay(row)

    def delete_overlays(
        self,
        session_id: UUID,
        action_ids: tuple[UUID, ...] | None = None,
    ) -> int:
        conditions = [demo_action_overlays.c.demo_session_id == session_id]
        if action_ids is not None:
            if not action_ids:
                return 0
            conditions.append(demo_action_overlays.c.action_id.in_(action_ids))
        result = self._connection.execute(
            delete(demo_action_overlays).where(*conditions)
        )
        return int(result.rowcount or 0)


def _facts(payload: list[dict[str, object]]) -> tuple[FactRef, ...]:
    return tuple(FactRef(**item) for item in payload)  # type: ignore[arg-type]


def _revision(row) -> ActionRevision:
    return ActionRevision(
        revision=row["revision"],
        suggestion=row["suggestion"],
        target=row["target"],
        period_start=row["period_start"],
        period_end=row["period_end"],
        scope=dict(row["scope"]),
        quantity=row["quantity"],
        budget_brl=row["budget_brl"],
        action_date=row["action_date"],
        threshold=row["threshold"],
        expected_impact=dict(row["expected_impact"]),
        confidence=row["confidence"],
        limitations=tuple(row["limitations"]),
        facts=_facts(row["facts"]),
        analysis_run_id=row["analysis_run_id"],
        forecast_id=row["forecast_id"],
        bridge_id=row["bridge_id"],
        chat_turn_id=row["chat_turn_id"],
        chat_tool=row["chat_tool"],
        answer_version=row["answer_version"],
        created_at=row["created_at"],
    )


def _export(row) -> ActionExport:
    return ActionExport(
        id=row["id"],
        action_id=row["action_id"],
        action_revision=row["action_revision"],
        status=row["status"],
        format=row["format"],
        storage_object_id=row["storage_object_id"],
        sha256=row["sha256"],
        note=row["note"],
        exported_by=row["exported_by"],
        created_at=row["created_at"],
    )


def _outcome(row) -> ActionOutcome:
    return ActionOutcome(
        id=row["id"],
        action_id=row["action_id"],
        action_revision=row["action_revision"],
        outcome_revision=row["outcome_revision"],
        review_date=row["review_date"],
        synthetic_result=dict(row["synthetic_result"]),
        evidence=_facts(row["evidence"]),
        conclusion=row["conclusion"],
        reason=row["reason"],
        reviewed_by=row["reviewed_by"],
        created_at=row["created_at"],
    )


def _overlay(row) -> DemoActionOverlay:
    return DemoActionOverlay(
        id=row["id"],
        demo_session_id=row["demo_session_id"],
        action_id=row["action_id"],
        base_revision=row["base_revision"],
        overlay_revision=row["overlay_revision"],
        command=row["command"],
        status=row["status"],
        adjustment=dict(row["adjustment"]),
        reason=row["reason"],
        created_at=row["created_at"],
    )
