"""Human-controlled action-card lifecycle with append-only authority."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import BytesIO
import json
import re
from collections.abc import Mapping, Sequence
from uuid import UUID, uuid4, uuid5

from sqlalchemy import Connection, Engine, select

from src.actions.contracts import (
    ActionAdjustment,
    ActionCard,
    ActionExport,
    ActionOutcome,
    ActionSource,
    DemoActionOverlay,
    FactRef,
)
from src.actions.exports import MAX_EXPORT_BYTES, build_action_xlsx
from src.actions.simulation import project_simulation_inputs
from src.actions.state_machine import ActionTransitionInvalid, apply_command
from src.analysis.evidence import canonical_value, stable_hash
from src.ai.contracts import ToolResult
from src.db.schema import ai_chat_evidence, ai_chat_tool_runs, ai_chat_turns
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.actions import ActionRepository
from src.repositories.analyses import AnalysisRepository
from src.repositories.datasets import DatasetRepository
from src.repositories.forecasts import ForecastRepository
from src.repositories.profit_bridges import ProfitBridgeRepository
from src.repositories.sessions import SessionRepository
from src.repositories.storage_objects import StorageObjectRepository
from src.storage.keys import export_object_key, workspace_token
from src.storage.postgres_entry_locks import PostgresEntryLockManager
from src.storage.protocol import AvailableObject
from src.services.store_scope import StoreScopeError, StoreScopeResolver
from src.synthetic.boundary import (
    SyntheticSourceBoundaryError,
    validate_synthetic_records,
)

ACTION_NAMESPACE = UUID("5e872615-c165-4fab-bb24-dfe03c3f4fa6")
ACTION_STORAGE_LEASE = timedelta(minutes=5)
FORECAST_ACTION_STORE_ID = "SYNTH-STORE-01"
SAFE_TEXT = re.compile(r"[\w .,:;/()'&+%-]{1,1000}\Z", re.UNICODE)


class ActionNotFound(RuntimeError):
    code = "ACTION_NOT_FOUND"


class ActionInvalid(ValueError):
    code = "ACTION_INVALID"


class ActionRevisionConflict(RuntimeError):
    code = "ACTION_REVISION_CONFLICT"


class ActionScopeConflict(RuntimeError):
    code = "ACTION_SCOPE_CONFLICT"


class ActionIdempotencyConflict(RuntimeError):
    code = "ACTION_IDEMPOTENCY_CONFLICT"


class ActionUnavailable(RuntimeError):
    code = "ACTION_UNAVAILABLE"


class ActionService:
    def __init__(
        self,
        engine: Engine,
        storage,
        workspace_id: str,
        *,
        clock=None,
        uow_factory=PostgresUnitOfWork,
    ) -> None:
        self._engine = engine
        self._storage = storage
        self._workspace_id = workspace_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._uow_factory = uow_factory
        self._locks = PostgresEntryLockManager(engine)
        self._store_scopes = StoreScopeResolver(engine, storage, workspace_id)

    def create_draft(
        self,
        source: ActionSource,
        facts: tuple[FactRef, ...],
        idempotency_key: str,
    ) -> ActionCard:
        _validate_source(source, facts)
        key_hash = _key_hash(idempotency_key)
        payload = {"source": canonical_value(source), "facts": canonical_value(facts)}
        request_hash = _digest_bytes(payload)
        action_id = uuid5(
            ACTION_NAMESPACE,
            f"{self._workspace_id}:create:{key_hash.hex()}",
        )
        with self._locks.acquire((_lock_key(self._workspace_id, action_id),)):
            try:
                with self._uow_factory(self._engine) as uow:
                    repository = ActionRepository(uow.connection)
                    replay = repository.find_create(self._workspace_id, key_hash)
                    if replay is not None:
                        if (
                            repository.find_create_request_hash(
                                self._workspace_id,
                                key_hash,
                            )
                            != request_hash
                        ):
                            raise ActionIdempotencyConflict
                        return _create_response(replay)
                    version = DatasetRepository(uow.connection).get_version(
                        source.dataset_version_id
                    )
                    if (
                        version is None
                        or version.workspace_id != self._workspace_id
                        or version.status != "complete"
                    ):
                        raise ActionInvalid("dataset_version_invalid")
                    _validate_source_authority(
                        uow.connection,
                        self._storage,
                        self._workspace_id,
                        source,
                        facts,
                    )
                    repository.create(
                        action_id=action_id,
                        workspace_id=self._workspace_id,
                        dataset_version_id=source.dataset_version_id,
                        source_type=source.source_type,
                        key_hash=key_hash,
                        request_hash=request_hash,
                        revision=_revision_from_source(action_id, source, facts),
                        now=self._clock(),
                    )
                return self.get(action_id)
            except (ActionIdempotencyConflict, ActionInvalid):
                raise
            except Exception:
                replay = self._create_authority(key_hash, request_hash)
                if replay is not None:
                    return replay
                raise

    def review(
        self,
        action_id: UUID,
        revision: int,
        reason: str,
        idempotency_key: str,
    ) -> ActionCard:
        return self._decision(
            action_id,
            revision,
            "review",
            reason,
            idempotency_key,
        )

    def adjust(
        self,
        action_id: UUID,
        revision: int,
        adjustment: ActionAdjustment,
        reason: str,
        idempotency_key: str,
    ) -> ActionCard:
        if not any(value is not None for value in asdict(adjustment).values()):
            raise ActionInvalid("adjustment_empty")
        return self._decision(
            action_id,
            revision,
            "adjust",
            reason,
            idempotency_key,
            adjustment=adjustment,
        )

    def approve(
        self,
        action_id: UUID,
        revision: int,
        reason: str,
        idempotency_key: str,
    ) -> ActionCard:
        return self._decision(
            action_id,
            revision,
            "approve",
            reason,
            idempotency_key,
        )

    def dismiss(
        self,
        action_id: UUID,
        revision: int,
        reason: str,
        idempotency_key: str,
    ) -> ActionCard:
        return self._decision(
            action_id,
            revision,
            "dismiss",
            reason,
            idempotency_key,
        )

    def _decision(
        self,
        action_id: UUID,
        revision: int,
        command: str,
        reason: str,
        idempotency_key: str,
        *,
        adjustment: ActionAdjustment | None = None,
    ) -> ActionCard:
        _validate_reason(reason)
        if adjustment is not None:
            _validate_adjustment(adjustment)
        if not isinstance(action_id, UUID) or type(revision) is not int or revision < 1:
            raise ActionInvalid("action_authority_invalid")
        key_hash = _key_hash(idempotency_key)
        payload = {
            "action_id": str(action_id),
            "revision": revision,
            "command": command,
            "reason": reason,
            "adjustment": canonical_value(adjustment),
        }
        request_hash = _digest_bytes(payload)
        with self._locks.acquire((_lock_key(self._workspace_id, action_id),)):
            try:
                with self._uow_factory(self._engine) as uow:
                    repository = ActionRepository(uow.connection)
                    card = repository.get(
                        self._workspace_id,
                        action_id,
                        for_update=True,
                    )
                    if card is None:
                        raise ActionNotFound
                    replay = repository.find_decision(action_id, key_hash)
                    if replay is not None:
                        if bytes(replay["request_hash"]) != request_hash:
                            raise ActionIdempotencyConflict
                        return _decision_response(card, replay["id"])
                    if card.current_revision != revision:
                        raise ActionRevisionConflict
                    next_status = apply_command(card.status, command)
                    new_revision = None
                    if adjustment is not None:
                        new_revision = _adjusted_revision(
                            action_id,
                            card.revisions[-1],
                            adjustment,
                        )
                    changed = repository.apply_decision(
                        action_id=action_id,
                        expected_revision=revision,
                        command=command,
                        next_status=next_status,
                        reason=reason,
                        decision_id=uuid5(
                            ACTION_NAMESPACE,
                            f"decision:{action_id}:{key_hash.hex()}",
                        ),
                        decision_ordinal=len(card.decisions) + 1,
                        key_hash=key_hash,
                        request_hash=request_hash,
                        now=self._clock(),
                        new_revision=new_revision,
                    )
                    if not changed:
                        raise ActionRevisionConflict
                return self.get(action_id)
            except (
                ActionNotFound,
                ActionInvalid,
                ActionRevisionConflict,
                ActionIdempotencyConflict,
                ActionTransitionInvalid,
            ):
                raise
            except Exception:
                replay = self._decision_authority(action_id, key_hash, request_hash)
                if replay is not None:
                    return replay
                raise

    def export(
        self,
        action_id: UUID,
        revision: int,
        idempotency_key: str,
        format: str = "xlsx",
    ) -> ActionExport:
        if format != "xlsx":
            raise ActionInvalid("export_format_invalid")
        key_hash = _key_hash(idempotency_key)
        request_hash = _digest_bytes(
            {"action_id": str(action_id), "revision": revision, "format": format}
        )
        with self._locks.acquire((_lock_key(self._workspace_id, action_id),)):
            with self._engine.connect() as connection:
                repository = ActionRepository(connection)
                replay_record = repository.find_export_record(action_id, key_hash)
                if replay_record is not None:
                    if bytes(replay_record["request_hash"]) != request_hash:
                        raise ActionIdempotencyConflict
                    return repository.find_export(action_id, key_hash)
                card = repository.get(self._workspace_id, action_id)
            if card is None:
                raise ActionNotFound
            if card.current_revision != revision:
                raise ActionRevisionConflict
            apply_command(card.status, "export")
            content = build_action_xlsx(card)
            staged = None
            staged_id = None
            available = None
            final_id = None
            adopt_final = False
            cleanup_final = False
            try:
                staged = self._storage.put_staging(
                    BytesIO(content),
                    max_bytes=MAX_EXPORT_BYTES,
                    media_type=(
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"
                    ),
                )
                staged_id = uuid5(ACTION_NAMESPACE, f"staging:{staged.key}")
                staged_id = self._record_staging(staged)
                final_key = export_object_key(
                    self._workspace_id,
                    str(action_id),
                    staged.sha256,
                )
                final_id = self._record_promotion_reservation(final_key, staged)
                available = self._promote_export(staged, final_key)
                cleanup_final = available.created
                final_id, adopt_final, cleanup_final = self._record_quarantined(
                    available
                )
                with self._uow_factory(self._engine) as uow:
                    storage_repository = StorageObjectRepository(uow.connection)
                    if adopt_final:
                        storage_repository.adopt_quarantined_available(
                            final_id,
                            object_key=available.key,
                            sha256=available.sha256,
                            etag=available.etag,
                            purpose="export",
                            now=self._clock(),
                        )
                    exported = ActionRepository(uow.connection).add_export(
                        {
                            "id": uuid5(
                                ACTION_NAMESPACE,
                                f"export:{action_id}:{key_hash.hex()}",
                            ),
                            "action_id": action_id,
                            "action_revision": revision,
                            "format": "xlsx",
                            "status": "available",
                            "storage_object_id": final_id,
                            "sha256": available.sha256,
                            "note": "Not sent to an external platform",
                            "exported_by": "single_operator",
                            "idempotency_key_hash": key_hash,
                            "request_hash": request_hash,
                            "created_at": self._clock(),
                        }
                    )
            except Exception as error:
                try:
                    authority = self._export_authority(action_id, key_hash, revision)
                except Exception as authority_error:
                    error.add_note(
                        "action_export_authority_unavailable:"
                        f"{type(authority_error).__name__}"
                    )
                    authority = None
                if authority is not None:
                    if staged is not None:
                        self._cleanup_temporary(staged, staged_id, error)
                    return authority
                if available is not None and cleanup_final:
                    self._cleanup_temporary(available, final_id, error)
                if staged is not None:
                    self._cleanup_temporary(staged, staged_id, error)
                raise
            assert staged is not None
            self._cleanup_temporary(staged, staged_id)
            return exported

    def record_outcome(
        self,
        action_id: UUID,
        revision: int,
        *,
        review_date: date,
        synthetic_result: dict[str, str],
        evidence: tuple[FactRef, ...],
        conclusion: str,
        reason: str,
        idempotency_key: str,
    ) -> ActionOutcome:
        _validate_reason(reason)
        if conclusion not in {
            "achieved",
            "partially_achieved",
            "not_achieved",
            "inconclusive",
        }:
            raise ActionInvalid("outcome_conclusion_invalid")
        _validate_facts(evidence)
        _validate_synthetic((synthetic_result,))
        key_hash = _key_hash(idempotency_key)
        payload = {
            "action_id": str(action_id),
            "revision": revision,
            "review_date": review_date,
            "synthetic_result": synthetic_result,
            "evidence": canonical_value(evidence),
            "conclusion": conclusion,
            "reason": reason,
        }
        request_hash = _digest_bytes(payload)
        with self._locks.acquire((_lock_key(self._workspace_id, action_id),)):
            try:
                with self._uow_factory(self._engine) as uow:
                    repository = ActionRepository(uow.connection)
                    card = repository.get(self._workspace_id, action_id, for_update=True)
                    if card is None:
                        raise ActionNotFound
                    replay_record = repository.find_outcome_record(action_id, key_hash)
                    if replay_record is not None:
                        if bytes(replay_record["request_hash"]) != request_hash:
                            raise ActionIdempotencyConflict
                        replay = repository.find_outcome(action_id, key_hash)
                        assert replay is not None
                        return replay
                    if card.current_revision != revision:
                        raise ActionRevisionConflict
                    if evidence != card.revisions[-1].facts:
                        raise ActionInvalid("outcome_evidence_invalid")
                    _validate_source_authority(
                        uow.connection,
                        self._storage,
                        self._workspace_id,
                        _original_source(card),
                        evidence,
                    )
                    apply_command(card.status, "record_outcome")
                    stored = repository.add_outcome(
                        {
                            "id": uuid5(
                                ACTION_NAMESPACE,
                                f"outcome:{action_id}:{key_hash.hex()}",
                            ),
                            "action_id": action_id,
                            "action_revision": revision,
                            "outcome_revision": repository.next_outcome_revision(action_id),
                            "review_date": review_date,
                            "synthetic_result": synthetic_result,
                            "evidence": _fact_payload(evidence),
                            "conclusion": conclusion,
                            "reason": reason,
                            "reviewed_by": "single_operator",
                            "idempotency_key_hash": key_hash,
                            "request_hash": request_hash,
                            "created_at": self._clock(),
                        }
                    )
                return stored
            except (
                ActionNotFound,
                ActionInvalid,
                ActionRevisionConflict,
                ActionIdempotencyConflict,
                ActionTransitionInvalid,
            ):
                raise
            except Exception:
                authority = self._outcome_authority(
                    action_id,
                    key_hash,
                    request_hash,
                )
                if authority is not None:
                    return authority
                raise

    def open_export(self, action_id: UUID, export_id: UUID) -> bytes:
        with self._engine.connect() as connection:
            repository = ActionRepository(connection)
            card = repository.get(self._workspace_id, action_id)
            exported = repository.get_export(action_id, export_id)
            storage = (
                StorageObjectRepository(connection).get(exported.storage_object_id)
                if exported is not None and exported.storage_object_id is not None
                else None
            )
        if (
            card is None
            or exported is None
            or storage is None
            or card.status != "approved"
            or storage.workspace_id != self._workspace_id
            or storage.purpose != "export"
            or storage.state != "available"
            or storage.sha256 != exported.sha256
        ):
            raise ActionNotFound
        try:
            with self._storage.open_verified(
                storage.object_key,
                exported.sha256,
                storage.size_bytes,
            ) as opened:
                return opened.read()
        except Exception as error:
            raise ActionUnavailable("action_export_unavailable") from error

    def get(self, action_id: UUID) -> ActionCard:
        with self._engine.connect() as connection:
            card = ActionRepository(connection).get(self._workspace_id, action_id)
        if card is None:
            raise ActionNotFound
        return card

    def require_scope(
        self,
        action_id: UUID,
        dataset_version_id: UUID,
        scope: Mapping[str, object] | None,
    ) -> ActionCard:
        normalized_scope = self._scope_for_version(dataset_version_id, scope)
        card = self.get(action_id)
        if (
            card.dataset_version_id != dataset_version_id
            or not _card_matches_scope(card, normalized_scope)
        ):
            raise ActionScopeConflict
        return card

    def list(
        self,
        dataset_version_id: UUID,
        scope: Mapping[str, object] | None = None,
    ) -> tuple[ActionCard, ...]:
        normalized_scope = self._scope_for_version(dataset_version_id, scope)
        with self._engine.connect() as connection:
            cards = ActionRepository(connection).list_for_version(
                self._workspace_id,
                dataset_version_id,
            )
        return tuple(
            card for card in cards if _card_matches_scope(card, normalized_scope)
        )

    def list_public(
        self,
        dataset_version_id: UUID,
        session_created_at: datetime,
        scope: Mapping[str, object] | None = None,
    ) -> tuple[ActionCard, ...]:
        normalized_scope = self._scope_for_version(dataset_version_id, scope)
        with self._engine.connect() as connection:
            cards = ActionRepository(connection).list_public_for_session(
                self._workspace_id,
                dataset_version_id,
                session_created_at,
            )
        return tuple(
            self._with_simulation_inputs(card)
            for card in cards
            if _card_matches_scope(card, normalized_scope)
        )

    def _with_simulation_inputs(self, card: ActionCard) -> ActionCard:
        revision = next(
            (
                item
                for item in card.revisions
                if item.revision == card.current_revision
            ),
            None,
        )
        if revision is None:
            raise ActionUnavailable("action_revision_unavailable")
        if revision.analysis_run_id is None:
            return replace(
                card,
                simulation_inputs=project_simulation_inputs(revision, None),
            )
        with self._engine.connect() as connection:
            analyses = AnalysisRepository(connection)
            run = analyses.get(self._workspace_id, revision.analysis_run_id)
            artifact = analyses.get_artifact(revision.analysis_run_id)
            stored = (
                StorageObjectRepository(connection).get(artifact.storage_object_id)
                if artifact is not None
                else None
            )
        if (
            run is None
            or run.status != "completed"
            or run.analysis_kind != "replenishment"
            or run.dataset_version_id != card.dataset_version_id
        ):
            raise ActionUnavailable("action_simulation_inputs_unavailable")
        try:
            snapshot = _verified_analysis_snapshot(
                self._storage,
                run,
                artifact,
                stored,
            )
        except ActionInvalid as error:
            raise ActionUnavailable("action_simulation_inputs_unavailable") from error
        return replace(
            card,
            simulation_inputs=project_simulation_inputs(revision, snapshot),
        )

    def read_for_query(
        self,
        connection: Connection,
        dataset_version_id: UUID,
        session_created_at: datetime | None = None,
        scope: Mapping[str, object] | None = None,
    ) -> tuple[ActionCard, ...]:
        """Read action cards through the caller's controlled transaction."""

        repository = ActionRepository(connection)
        normalized_scope = self._scope_for_version(dataset_version_id, scope)
        if session_created_at is not None:
            cards = repository.list_public_for_session(
                self._workspace_id,
                dataset_version_id,
                session_created_at,
            )
        else:
            cards = repository.list_for_version(
                self._workspace_id,
                dataset_version_id,
            )
        return tuple(
            card for card in cards if _card_matches_scope(card, normalized_scope)
        )

    def _scope_for_version(
        self,
        dataset_version_id: UUID,
        scope: Mapping[str, object] | None,
    ) -> dict[str, object]:
        value = dict(scope or {"currency": "BRL"})
        if value.get("currency") != "BRL":
            raise ActionInvalid("scope_currency_invalid")
        store_id = value.get("store_id")
        if store_id is not None and (
            not isinstance(store_id, str) or not store_id.strip()
        ):
            raise ActionInvalid("scope_store_invalid")
        try:
            self._store_scopes.resolve(
                dataset_version_id,
                [store_id] if isinstance(store_id, str) else None,
            )
        except StoreScopeError as error:
            raise ActionInvalid("scope_store_invalid") from error
        return {
            "currency": "BRL",
            **({"store_id": store_id} if store_id is not None else {}),
        }

    def simulate(
        self,
        *,
        session_id: UUID,
        expected_chat_epoch: int,
        dataset_version_id: UUID,
        action_id: UUID,
        base_revision: int,
        command: str,
        adjustment: dict[str, object],
        reason: str,
        idempotency_key: str,
    ) -> DemoActionOverlay:
        _validate_reason(reason)
        if command not in {"review", "adjust", "approve", "dismiss"}:
            raise ActionInvalid("overlay_command_invalid")
        if command != "adjust" and adjustment:
            raise ActionInvalid("overlay_adjustment_invalid")
        if command == "adjust":
            _validate_overlay_adjustment(adjustment)
        key_hash = _key_hash(idempotency_key)
        request_hash = _digest_bytes(
            {
                "session_id": str(session_id),
                "chat_epoch": expected_chat_epoch,
                "action_id": str(action_id),
                "base_revision": base_revision,
                "command": command,
                "adjustment": adjustment,
                "reason": reason,
            }
        )
        with self._locks.acquire(
            (
                _sandbox_lock_key(self._workspace_id, session_id),
                _lock_key(self._workspace_id, action_id, session_id=session_id),
            )
        ):
            try:
                with self._uow_factory(self._engine) as uow:
                    now = self._clock()
                    if not SessionRepository(uow.connection).lock_demo_chat_epoch(
                        session_id,
                        self._workspace_id,
                        dataset_version_id,
                        expected_chat_epoch,
                        now,
                    ):
                        raise ActionNotFound
                    repository = ActionRepository(uow.connection)
                    card = repository.get(self._workspace_id, action_id)
                    if (
                        card is None
                        or card.dataset_version_id != dataset_version_id
                        or card.current_revision != base_revision
                        or not repository.viewer_template_eligible(
                            session_id,
                            action_id,
                            now,
                        )
                    ):
                        raise ActionNotFound
                    replay_record = repository.find_overlay_record(
                        session_id,
                        key_hash,
                    )
                    if replay_record is not None:
                        if bytes(replay_record["request_hash"]) != request_hash:
                            raise ActionIdempotencyConflict
                        replay = repository.find_overlay(session_id, key_hash)
                        assert replay is not None
                        return replay
                    history = repository.list_overlays(session_id, action_id)
                    current_status = history[-1].status if history else "new"
                    next_status = apply_command(current_status, command)
                    stored = repository.add_overlay(
                        {
                            "id": uuid5(
                                ACTION_NAMESPACE,
                                f"overlay:{session_id}:{key_hash.hex()}",
                            ),
                            "demo_session_id": session_id,
                            "action_id": action_id,
                            "base_revision": base_revision,
                            "overlay_revision": len(history) + 1,
                            "command": command,
                            "status": next_status,
                            "adjustment": adjustment,
                            "reason": reason,
                            "idempotency_key_hash": key_hash,
                            "request_hash": request_hash,
                            "created_at": now,
                        }
                    )
                return stored
            except (
                ActionNotFound,
                ActionInvalid,
                ActionIdempotencyConflict,
                ActionTransitionInvalid,
            ):
                raise
            except Exception:
                replay = self._overlay_authority(
                    session_id,
                    key_hash,
                    request_hash,
                )
                if replay is not None:
                    return replay
                raise

    def overlays(self, session_id: UUID, action_id: UUID) -> tuple[DemoActionOverlay, ...]:
        with self._engine.connect() as connection:
            return ActionRepository(connection).list_overlays(session_id, action_id)

    def reset_simulation(
        self,
        *,
        session_id: UUID,
        expected_chat_epoch: int,
        dataset_version_id: UUID,
        scope: Mapping[str, object] | None = None,
    ) -> int:
        with self._locks.acquire(
            (_sandbox_lock_key(self._workspace_id, session_id),)
        ):
            with self._uow_factory(self._engine) as uow:
                if not SessionRepository(uow.connection).lock_demo_chat_epoch(
                    session_id,
                    self._workspace_id,
                    dataset_version_id,
                    expected_chat_epoch,
                    self._clock(),
                ):
                    raise ActionNotFound
                repository = ActionRepository(uow.connection)
                if scope is None:
                    return repository.delete_overlays(session_id)
                normalized_scope = self._scope_for_version(
                    dataset_version_id,
                    scope,
                )
                action_ids = tuple(
                    card.id
                    for card in repository.list_for_version(
                        self._workspace_id,
                        dataset_version_id,
                    )
                    if _card_matches_scope(card, normalized_scope)
                )
                return repository.delete_overlays(session_id, action_ids)

    def _create_authority(
        self,
        key_hash: bytes,
        request_hash: bytes,
    ) -> ActionCard | None:
        with self._engine.connect() as connection:
            repository = ActionRepository(connection)
            card = repository.find_create(self._workspace_id, key_hash)
            stored_hash = repository.find_create_request_hash(
                self._workspace_id,
                key_hash,
            )
        if card is None:
            return None
        if stored_hash != request_hash:
            raise ActionIdempotencyConflict
        return _create_response(card)

    def _decision_authority(
        self,
        action_id: UUID,
        key_hash: bytes,
        request_hash: bytes,
    ) -> ActionCard | None:
        with self._engine.connect() as connection:
            repository = ActionRepository(connection)
            record = repository.find_decision(action_id, key_hash)
            card = repository.get(self._workspace_id, action_id)
        if record is None or card is None:
            return None
        if bytes(record["request_hash"]) != request_hash:
            raise ActionIdempotencyConflict
        return _decision_response(card, record["id"])

    def _overlay_authority(
        self,
        session_id: UUID,
        key_hash: bytes,
        request_hash: bytes,
    ) -> DemoActionOverlay | None:
        with self._engine.connect() as connection:
            repository = ActionRepository(connection)
            record = repository.find_overlay_record(session_id, key_hash)
            overlay = repository.find_overlay(session_id, key_hash)
        if record is None or overlay is None:
            return None
        if bytes(record["request_hash"]) != request_hash:
            raise ActionIdempotencyConflict
        return overlay

    def _export_authority(
        self,
        action_id: UUID,
        key_hash: bytes,
        revision: int,
    ) -> ActionExport | None:
        with self._engine.connect() as connection:
            exported = ActionRepository(connection).find_export(action_id, key_hash)
            storage = (
                StorageObjectRepository(connection).get(exported.storage_object_id)
                if exported is not None and exported.storage_object_id is not None
                else None
            )
        if exported is None:
            return None
        if (
            exported.action_revision != revision
            or storage is None
            or storage.state != "available"
            or storage.purpose != "export"
            or storage.sha256 != exported.sha256
        ):
            raise ActionUnavailable("export_authority_invalid")
        return exported

    def _outcome_authority(
        self,
        action_id: UUID,
        key_hash: bytes,
        request_hash: bytes,
    ) -> ActionOutcome | None:
        with self._engine.connect() as connection:
            repository = ActionRepository(connection)
            record = repository.find_outcome_record(action_id, key_hash)
            outcome = repository.find_outcome(action_id, key_hash)
        if record is None or outcome is None:
            return None
        if bytes(record["request_hash"]) != request_hash:
            raise ActionIdempotencyConflict
        return outcome

    def _record_staging(self, staged) -> UUID:
        object_id = uuid5(ACTION_NAMESPACE, f"staging:{staged.key}")
        try:
            with self._uow_factory(self._engine) as uow:
                StorageObjectRepository(uow.connection).create_staging(
                    object_id=object_id,
                    workspace_id=self._workspace_id,
                    staged=staged,
                    purpose="temporary_upload",
                    now=self._clock(),
                    expires_at=self._clock() + ACTION_STORAGE_LEASE,
                )
        except Exception:
            with self._engine.connect() as connection:
                existing = StorageObjectRepository(connection).get_by_key(staged.key)
            if not _matches_temporary(existing, self._workspace_id, staged):
                raise
            assert existing is not None
            return existing.id
        return object_id

    def _record_promotion_reservation(self, final_key: str, staged) -> UUID:
        object_id = uuid4()
        with self._engine.connect() as connection:
            existing = StorageObjectRepository(connection).get_by_key(final_key)
        if _matches_final_reservation(existing, self._workspace_id, final_key, staged):
            assert existing is not None
            return existing.id
        try:
            with self._uow_factory(self._engine) as uow:
                StorageObjectRepository(
                    uow.connection
                ).create_promotion_reservation(
                    object_id=object_id,
                    workspace_id=self._workspace_id,
                    object_key=final_key,
                    size_bytes=staged.size_bytes,
                    sha256=staged.sha256,
                    media_type=(
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"
                    ),
                    now=self._clock(),
                    expires_at=self._clock() + ACTION_STORAGE_LEASE,
                )
        except Exception:
            with self._engine.connect() as connection:
                existing = StorageObjectRepository(connection).get_by_key(final_key)
            if not _matches_final_reservation(
                existing,
                self._workspace_id,
                final_key,
                staged,
            ):
                raise
            assert existing is not None
            return existing.id
        return object_id

    def _promote_export(self, staged, final_key: str) -> AvailableObject:
        failures: list[Exception] = []
        for _attempt in range(2):
            try:
                return self._storage.promote(
                    staged.key,
                    final_key,
                    staged.sha256,
                )
            except Exception as error:
                failures.append(error)
        try:
            inventory = tuple(
                item
                for item in self._storage.inventory(final_key)
                if item.key == final_key
            )
            if len(inventory) != 1:
                raise ActionUnavailable("export_promotion_authority_missing")
            with self._storage.open_verified(
                final_key,
                staged.sha256,
                staged.size_bytes,
            ) as opened:
                content = opened.read()
            if len(content) != staged.size_bytes or sha256(content).hexdigest() != (
                staged.sha256
            ):
                raise ActionUnavailable("export_promotion_authority_invalid")
            return AvailableObject(
                key=final_key,
                size_bytes=staged.size_bytes,
                sha256=staged.sha256,
                etag=inventory[0].etag,
                created=False,
            )
        except Exception as recovery_error:
            failures[0].add_note(
                "action_export_promotion_recovery_failed:"
                f"{type(recovery_error).__name__}"
            )
            raise failures[0]

    def _record_quarantined(self, available) -> tuple[UUID, bool, bool]:
        object_id = uuid4()
        with self._engine.connect() as connection:
            existing = StorageObjectRepository(connection).get_by_key(available.key)
        if _matches_available_export(existing, self._workspace_id, available):
            assert existing is not None
            return existing.id, False, False
        if _matches_promotion_reservation(existing, self._workspace_id, available):
            assert existing is not None
            try:
                with self._uow_factory(self._engine) as uow:
                    StorageObjectRepository(
                        uow.connection
                    ).record_promoted_quarantined(
                        existing.id,
                        object_key=available.key,
                        sha256=available.sha256,
                        size_bytes=available.size_bytes,
                        etag=available.etag,
                        now=self._clock(),
                        expires_at=self._clock() + ACTION_STORAGE_LEASE,
                    )
            except Exception:
                with self._engine.connect() as connection:
                    current = StorageObjectRepository(connection).get_by_key(
                        available.key
                    )
                if not _matches_temporary(
                    current,
                    self._workspace_id,
                    available,
                ):
                    raise
            return existing.id, True, True
        if _matches_temporary(existing, self._workspace_id, available):
            assert existing is not None
            return existing.id, True, True
        try:
            with self._uow_factory(self._engine) as uow:
                repository = StorageObjectRepository(uow.connection)
                repository.create_available(
                    object_id=object_id,
                    workspace_id=self._workspace_id,
                    available=available,
                    purpose="temporary_upload",
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    now=self._clock(),
                    expires_at=self._clock() + ACTION_STORAGE_LEASE,
                )
                repository.mark_quarantined(object_id, now=self._clock())
        except Exception:
            with self._engine.connect() as connection:
                existing = StorageObjectRepository(connection).get_by_key(available.key)
            if _matches_available_export(existing, self._workspace_id, available):
                assert existing is not None
                return existing.id, False, False
            if not _matches_temporary(existing, self._workspace_id, available):
                raise
            assert existing is not None
            return existing.id, True, True
        return object_id, True, True

    def _cleanup_temporary(self, item, object_id: UUID | None, error=None) -> None:
        try:
            self._storage.delete(item.key, expected_etag=item.etag)
        except Exception as cleanup_error:
            if object_id is not None:
                try:
                    with self._uow_factory(self._engine) as uow:
                        StorageObjectRepository(uow.connection).mark_cleanup_pending(
                            object_id,
                            now=self._clock(),
                        )
                except Exception as ledger_error:
                    if error is not None:
                        error.add_note(
                            f"action_cleanup_ledger_failed:{type(ledger_error).__name__}"
                        )
            if error is not None:
                error.add_note(
                    f"action_cleanup_pending:{type(cleanup_error).__name__}"
                )
            return
        if object_id is not None:
            try:
                with self._uow_factory(self._engine) as uow:
                    StorageObjectRepository(uow.connection).mark_deleted(
                        object_id,
                        now=self._clock(),
                    )
            except Exception as ledger_error:
                if error is not None:
                    error.add_note(
                        f"action_cleanup_tombstone_failed:{type(ledger_error).__name__}"
                    )


def _create_response(card: ActionCard) -> ActionCard:
    return replace(
        card,
        status="new",
        current_revision=1,
        revisions=card.revisions[:1],
        decisions=(),
        exports=(),
        outcomes=(),
        updated_at=card.created_at,
        terminal_at=None,
    )


def _card_matches_scope(
    card: ActionCard,
    scope: Mapping[str, object],
) -> bool:
    revision = next(
        (
            item
            for item in card.revisions
            if item.revision == card.current_revision
        ),
        None,
    )
    if revision is None:
        return False
    return (
        revision.scope.get("currency") == scope.get("currency")
        and revision.scope.get("store_id") == scope.get("store_id")
    )


def _original_source(card: ActionCard) -> ActionSource:
    revision = card.revisions[0]
    return ActionSource(
        source_type=card.source_type,
        dataset_version_id=card.dataset_version_id,
        suggestion=revision.suggestion,
        target=revision.target,
        period_start=revision.period_start,
        period_end=revision.period_end,
        scope=revision.scope,
        quantity=revision.quantity,
        budget_brl=revision.budget_brl,
        action_date=revision.action_date,
        threshold=revision.threshold,
        expected_impact=revision.expected_impact,
        confidence=revision.confidence,
        limitations=revision.limitations,
        analysis_run_id=revision.analysis_run_id,
        forecast_id=revision.forecast_id,
        bridge_id=revision.bridge_id,
        chat_turn_id=revision.chat_turn_id,
        chat_tool=revision.chat_tool,
        answer_version=revision.answer_version,
    )


def _decision_response(card: ActionCard, decision_id: UUID) -> ActionCard:
    index = next(
        (
            offset
            for offset, decision in enumerate(card.decisions)
            if decision.id == decision_id
        ),
        None,
    )
    if index is None:
        raise ActionUnavailable("decision_response_missing")
    decision = card.decisions[index]
    status = {
        "review": "reviewed",
        "adjust": "reviewed",
        "approve": "approved",
        "dismiss": "dismissed",
    }[decision.command]
    return replace(
        card,
        status=status,
        current_revision=decision.action_revision,
        revisions=tuple(
            revision
            for revision in card.revisions
            if revision.revision <= decision.action_revision
        ),
        decisions=card.decisions[: index + 1],
        exports=(),
        outcomes=(),
        updated_at=decision.created_at,
        terminal_at=(
            decision.created_at if status in {"approved", "dismissed"} else None
        ),
    )


def _revision_from_source(
    action_id: UUID,
    source: ActionSource,
    facts: tuple[FactRef, ...],
) -> dict[str, object]:
    return {
        "id": uuid5(ACTION_NAMESPACE, f"revision:{action_id}:1"),
        "suggestion": source.suggestion,
        "target": source.target,
        "period_start": source.period_start,
        "period_end": source.period_end,
        "scope": dict(source.scope),
        "quantity": source.quantity,
        "budget_brl": source.budget_brl,
        "action_date": source.action_date,
        "threshold": source.threshold,
        "expected_impact": dict(source.expected_impact),
        "confidence": source.confidence,
        "limitations": list(source.limitations),
        "facts": _fact_payload(facts),
        "analysis_run_id": source.analysis_run_id,
        "forecast_id": source.forecast_id,
        "bridge_id": source.bridge_id,
        "chat_turn_id": source.chat_turn_id,
        "chat_tool": source.chat_tool,
        "answer_version": source.answer_version,
    }


def _adjusted_revision(action_id: UUID, current, patch: ActionAdjustment):
    next_revision = current.revision + 1
    return {
        "id": uuid5(ACTION_NAMESPACE, f"revision:{action_id}:{next_revision}"),
        "suggestion": patch.suggestion or current.suggestion,
        "target": patch.target or current.target,
        "period_start": current.period_start,
        "period_end": current.period_end,
        "scope": current.scope,
        "quantity": patch.quantity if patch.quantity is not None else current.quantity,
        "budget_brl": (
            patch.budget_brl if patch.budget_brl is not None else current.budget_brl
        ),
        "action_date": (
            patch.action_date if patch.action_date is not None else current.action_date
        ),
        "threshold": (
            patch.threshold if patch.threshold is not None else current.threshold
        ),
        "expected_impact": (
            dict(patch.expected_impact)
            if patch.expected_impact is not None
            else current.expected_impact
        ),
        "confidence": patch.confidence or current.confidence,
        "limitations": (
            list(patch.limitations)
            if patch.limitations is not None
            else list(current.limitations)
        ),
        "facts": _fact_payload(current.facts),
        "analysis_run_id": current.analysis_run_id,
        "forecast_id": current.forecast_id,
        "bridge_id": current.bridge_id,
        "chat_turn_id": current.chat_turn_id,
        "chat_tool": current.chat_tool,
        "answer_version": current.answer_version,
    }


def _validate_source(source: ActionSource, facts: tuple[FactRef, ...]) -> None:
    if not isinstance(source, ActionSource):
        raise ActionInvalid("source_invalid")
    if source.period_start > source.period_end:
        raise ActionInvalid("period_invalid")
    if source.scope.get("currency") != "BRL":
        raise ActionInvalid("scope_currency_invalid")
    if not source.target.startswith("SYNTH-"):
        raise ActionInvalid("target_invalid")
    if source.source_type not in {
        "deterministic_rule",
        "new_product_forecast",
        "profit_bridge",
        "operating_advice",
        "chat_box_draft",
    }:
        raise ActionInvalid("source_type_invalid")
    if source.confidence not in {"low", "medium", "high"}:
        raise ActionInvalid("confidence_invalid")
    if source.quantity is not None and (
        not source.quantity.is_finite() or source.quantity < 0
    ):
        raise ActionInvalid("quantity_invalid")
    if source.budget_brl is not None and (
        not source.budget_brl.is_finite() or source.budget_brl < 0
    ):
        raise ActionInvalid("budget_invalid")
    if source.threshold is not None and not source.threshold.is_finite():
        raise ActionInvalid("threshold_invalid")
    if not SAFE_TEXT.fullmatch(source.suggestion) or not SAFE_TEXT.fullmatch(source.target):
        raise ActionInvalid("source_text_invalid")
    _validate_synthetic(
        (
            {
                "suggestion": source.suggestion,
                "target": source.target,
                "scope": dict(source.scope),
                "expected_impact": dict(source.expected_impact),
                "limitations": ";".join(source.limitations),
            },
        )
    )
    _validate_facts(facts)


def _validate_source_authority(
    connection,
    storage,
    workspace_id: str,
    source: ActionSource,
    facts: tuple[FactRef, ...],
) -> None:
    if source.source_type in {"deterministic_rule", "operating_advice"}:
        if (
            source.analysis_run_id is None
            or source.forecast_id is not None
            or source.bridge_id is not None
            or any(
                value is not None
                for value in (
                    source.chat_turn_id,
                    source.chat_tool,
                    source.answer_version,
                )
            )
        ):
            raise ActionInvalid("analysis_source_required")
    elif source.source_type == "new_product_forecast":
        if (
            source.forecast_id is None
            or source.analysis_run_id is not None
            or source.bridge_id is not None
            or any(
                value is not None
                for value in (
                    source.chat_turn_id,
                    source.chat_tool,
                    source.answer_version,
                )
            )
        ):
            raise ActionInvalid("forecast_source_required")
    elif source.source_type == "profit_bridge":
        if (
            source.bridge_id is None
            or source.analysis_run_id is not None
            or source.forecast_id is not None
            or any(
                value is not None
                for value in (
                    source.chat_turn_id,
                    source.chat_tool,
                    source.answer_version,
                )
            )
        ):
            raise ActionInvalid("bridge_source_required")
    elif source.source_type == "chat_box_draft":
        if (
            source.analysis_run_id is not None
            or source.forecast_id is not None
            or source.bridge_id is not None
            or any(
                value is None
                for value in (
                    source.chat_turn_id,
                    source.chat_tool,
                    source.answer_version,
                )
            )
        ):
            raise ActionInvalid("chat_source_required")
        turn = connection.execute(
            select(*ai_chat_turns.c).where(
                ai_chat_turns.c.id == source.chat_turn_id,
                ai_chat_turns.c.workspace_id == workspace_id,
            )
        ).mappings().one_or_none()
        tool_run = connection.execute(
            select(*ai_chat_tool_runs.c).where(
                ai_chat_tool_runs.c.turn_id == source.chat_turn_id
            )
        ).mappings().one_or_none()
        evidence_rows = connection.execute(
            select(*ai_chat_evidence.c)
            .where(ai_chat_evidence.c.turn_id == source.chat_turn_id)
            .order_by(ai_chat_evidence.c.fact_ref)
        ).mappings().all()
        if (
            turn is None
            or turn["actor_kind"] != "operator"
            or turn["dataset_version_id"] != source.dataset_version_id
            or turn["status"] != "answered"
            or turn["tool_name"] != source.chat_tool
            or turn["output_schema_version"] != source.answer_version
            or tool_run is None
            or tool_run["status"] != "succeeded"
            or tool_run["tool_name"] != source.chat_tool
            or tool_run["result_hash"] != turn["result_hash"]
            or not isinstance(tool_run["result_summary"], dict)
        ):
            raise ActionInvalid("chat_source_invalid")
        result_payload = dict(tool_run["result_summary"])
        result_payload["scope"] = dict(turn["scope"])
        try:
            result = ToolResult.model_validate(result_payload)
        except Exception as error:
            raise ActionInvalid("chat_result_invalid") from error
        spec = result.action_card_draft
        if spec is None:
            raise ActionInvalid("chat_action_not_eligible")
        expected_scope = {
            "period_start": result.scope.period_start.isoformat(),
            "period_end": result.scope.period_end.isoformat(),
            "currency": result.scope.currency,
            **(
                {"store_id": result.scope.store_ids[0]}
                if len(result.scope.store_ids) == 1
                else {}
            ),
        }
        if (
            source.suggestion != spec.suggestion
            or source.target != spec.target
            or source.period_start != result.scope.period_start
            or source.period_end != result.scope.period_end
            or canonical_value(source.scope) != canonical_value(expected_scope)
            or source.quantity != spec.quantity
            or source.budget_brl != spec.budget_brl
            or source.action_date is not None
            or source.threshold is not None
            or canonical_value(source.expected_impact)
            != canonical_value(spec.expected_impact)
            or source.confidence != spec.confidence
            or tuple(source.limitations) != tuple(spec.limitations)
        ):
            raise ActionInvalid("chat_action_authority_mismatch")
        authority_facts = {
            item.fact_ref: item
            for item in result.facts
            if item.fact_ref in spec.fact_refs
        }
        persisted_evidence = {item["fact_ref"]: item for item in evidence_rows}
        if set(authority_facts) != set(spec.fact_refs) or len(facts) != len(
            spec.fact_refs
        ):
            raise ActionInvalid("chat_fact_set_invalid")
        for fact in facts:
            authority = authority_facts.get(fact.alias)
            persisted = persisted_evidence.get(fact.alias)
            if (
                authority is None
                or persisted is None
                or not authority.evidence_refs
                or fact.evidence_state != authority.evidence_state
                or fact.source_ref != authority.evidence_refs[0]
                or fact.value != authority.value
                or persisted["evidence_state"] != authority.evidence_state
                or persisted["source_ref"] != authority.evidence_refs[0]
            ):
                raise ActionInvalid("chat_evidence_invalid")

    if source.analysis_run_id is not None:
        analyses = AnalysisRepository(connection)
        run = analyses.get(workspace_id, source.analysis_run_id)
        if (
            run is None
            or run.dataset_version_id != source.dataset_version_id
            or run.status != "completed"
        ):
            raise ActionInvalid("analysis_source_invalid")
        if canonical_value(source.scope) != canonical_value(run.scope):
            raise ActionInvalid("analysis_scope_invalid")
        if (
            run.scope.get("period_start") != source.period_start.isoformat()
            or run.scope.get("period_end") != source.period_end.isoformat()
        ):
            raise ActionInvalid("analysis_period_invalid")
        artifact = analyses.get_artifact(run.id)
        stored = (
            StorageObjectRepository(connection).get(artifact.storage_object_id)
            if artifact is not None
            else None
        )
        snapshot = _verified_analysis_snapshot(storage, run, artifact, stored)
        evidence = {item.alias: item for item in analyses.get_evidence(run.id)}
        resolved: dict[str, str | None] = {}
        for fact in facts:
            if "|" not in fact.alias:
                raise ActionInvalid("analysis_fact_path_invalid")
            evidence_alias, path = fact.alias.split("|", 1)
            _validate_analysis_fact_binding(evidence_alias, path)
            authority = evidence.get(evidence_alias)
            expected = _fact_value(_resolve_authority_path(snapshot, path))
            if (
                authority is None
                or authority.evidence_state != fact.evidence_state
                or fact.source_ref != f"analysis:{run.id}:{fact.alias}"
                or fact.value != expected
            ):
                raise ActionInvalid("analysis_evidence_invalid")
            resolved[fact.alias] = expected
        _validate_action_value_links(source, resolved, require_target=True)
    if source.forecast_id is not None:
        forecast = ForecastRepository(connection).get(workspace_id, source.forecast_id)
        if (
            forecast is None
            or forecast.dataset_version_id != source.dataset_version_id
            or forecast.status != "completed"
        ):
            raise ActionInvalid("forecast_source_invalid")
        resolved = {}
        forecast_authority = {
            "input_snapshot": forecast.input_snapshot,
            "evidence": forecast.evidence,
            "result": forecast.result,
            "backtest": forecast.backtest,
        }
        for fact in facts:
            expected = _fact_value(
                _resolve_authority_path(forecast_authority, fact.alias)
            )
            expected_state = (
                "unknown"
                if expected is None
                else (
                    "assumed"
                    if fact.alias.startswith("input_snapshot.")
                    else "derived"
                )
            )
            if (
                fact.source_ref != f"forecast:{forecast.id}:{fact.alias}"
                or fact.evidence_state != expected_state
                or fact.value != expected
            ):
                raise ActionInvalid("forecast_evidence_invalid")
            resolved[fact.alias] = expected
        candidate = forecast.input_snapshot.get("candidate")
        result = forecast.result
        if not isinstance(candidate, dict) or not isinstance(result, dict):
            raise ActionInvalid("forecast_input_invalid")
        launch_date = date.fromisoformat(str(candidate.get("planned_launch_date")))
        expected_scope = {
            "store_id": FORECAST_ACTION_STORE_ID,
            "currency": "BRL",
            "period_start": source.period_start.isoformat(),
            "period_end": source.period_end.isoformat(),
        }
        result_limitations = result.get("limitations")
        missing_fields = result.get("missing_fields")
        if not isinstance(result_limitations, list) or not isinstance(
            missing_fields, list
        ):
            raise ActionInvalid("forecast_limitations_invalid")
        authoritative_limitations = tuple(
            sorted(
                {
                    "synthetic_demo_only",
                    *(str(item) for item in result_limitations),
                    *(f"missing_field:{item}" for item in missing_fields),
                }
            )
        )
        if (
            source.target != f"SYNTH-FORECAST-{forecast.id}"
            or canonical_value(source.scope) != canonical_value(expected_scope)
            or source.confidence != forecast.confidence
            or tuple(sorted(set(source.limitations))) != authoritative_limitations
            or source.period_start != launch_date
            or source.period_end < launch_date
            or source.period_end > launch_date + timedelta(days=89)
        ):
            raise ActionInvalid("forecast_action_scope_invalid")
        _validate_action_value_links(source, resolved, require_target=False)
    if source.bridge_id is not None:
        bridges = ProfitBridgeRepository(connection)
        bridge = bridges.get(workspace_id, source.bridge_id)
        if bridge is None or bridge.dataset_version_id != source.dataset_version_id:
            raise ActionInvalid("bridge_source_invalid")
        if canonical_value(source.scope) != canonical_value(bridge.scope):
            raise ActionInvalid("bridge_scope_invalid")
        current_period = bridge.evidence.get("current_period")
        if current_period != [
            source.period_start.isoformat(),
            source.period_end.isoformat(),
        ]:
            raise ActionInvalid("bridge_period_invalid")
        items = {item.driver: item for item in bridges.items(bridge.id)}
        resolved = {}
        for fact in facts:
            parts = fact.alias.split(".")
            if len(parts) != 3 or parts[0] != "items" or parts[2] != "amount_brl":
                raise ActionInvalid("bridge_fact_path_invalid")
            item = items.get(parts[1])
            expected = _fact_value(item.amount_brl if item is not None else None)
            if (
                item is None
                or fact.source_ref != f"profit_bridge:{bridge.id}:{fact.alias}"
                or fact.evidence_state != item.evidence_state
                or fact.value != expected
            ):
                raise ActionInvalid("bridge_evidence_invalid")
            resolved[fact.alias] = expected
        _validate_action_value_links(source, resolved, require_target=False)


def _verified_analysis_snapshot(storage, run, artifact, stored) -> dict[str, object]:
    if (
        artifact is None
        or stored is None
        or stored.workspace_id != run.workspace_id
        or stored.state != "available"
        or stored.purpose != "evidence"
        or stored.sha256 != artifact.snapshot_sha256
    ):
        raise ActionInvalid("analysis_snapshot_invalid")
    try:
        with storage.open_verified(
            stored.object_key,
            artifact.snapshot_sha256,
            stored.size_bytes,
        ) as opened:
            content = opened.read()
        payload = json.loads(content)
    except Exception as error:
        raise ActionInvalid("analysis_snapshot_invalid") from error
    if (
        sha256(content).hexdigest() != artifact.snapshot_sha256
        or not isinstance(payload, dict)
        or payload.get("run_id") != str(run.id)
        or payload.get("dataset_version_id") != str(run.dataset_version_id)
        or payload.get("analysis_kind") != run.analysis_kind
        or payload.get("algorithm_version") != run.algorithm_version
        or payload.get("input_hash") != run.input_hash
        or payload.get("scope") != run.scope
    ):
        raise ActionInvalid("analysis_snapshot_invalid")
    return payload


def _resolve_authority_path(value: object, path: str) -> object:
    current = value
    for segment in path.split("."):
        if isinstance(current, Mapping):
            if segment not in current:
                raise ActionInvalid("fact_path_invalid")
            current = current[segment]
            continue
        if isinstance(current, Sequence) and not isinstance(
            current,
            (str, bytes, bytearray),
        ):
            matches = [
                item
                for item in current
                if isinstance(item, Mapping)
                and str(
                    item.get("sku_id", item.get("driver", item.get("horizon_days")))
                )
                == segment
            ]
            if len(matches) != 1:
                raise ActionInvalid("fact_path_invalid")
            current = matches[0]
            continue
        raise ActionInvalid("fact_path_invalid")
    return current


def _fact_value(value: object) -> str | None:
    if value is None:
        return None
    normalized = canonical_value(value)
    if isinstance(normalized, (dict, list)):
        raise ActionInvalid("fact_value_not_scalar")
    return str(normalized)


def _validate_action_value_links(
    source: ActionSource,
    resolved: Mapping[str, str | None],
    *,
    require_target: bool,
) -> None:
    if require_target and source.target not in {
        identifier
        for alias in resolved
        for identifier in _authority_identifiers(alias)
    }:
        raise ActionInvalid("action_target_unproven")
    _require_linked_value(
        "quantity",
        source.quantity,
        resolved,
        ("recommended_quantity", "recommended_first_order_units", "quantity"),
    )
    _require_linked_value(
        "budget",
        source.budget_brl,
        resolved,
        ("budget_brl", "amount_brl", "planned_daily_ad_brl", "cash_required.value"),
    )
    _require_linked_value(
        "action_date",
        source.action_date,
        resolved,
        ("latest_order_date", "planned_launch_date", "action_date"),
    )
    _require_linked_value(
        "threshold",
        source.threshold,
        resolved,
        ("threshold", "reorder_point_units"),
    )
    for key, value in source.expected_impact.items():
        _require_linked_value(key, value, resolved, (key,))


def _require_linked_value(
    field: str,
    value: object,
    resolved: Mapping[str, str | None],
    suffixes: tuple[str, ...],
) -> None:
    if value is None:
        return
    expected = _fact_value(value)
    if any(
        _linked_values_equal(fact_value, expected)
        and any(alias.endswith(f".{suffix}") for suffix in suffixes)
        for alias, fact_value in resolved.items()
    ):
        return
    raise ActionInvalid(f"action_{field}_unproven")


def _linked_values_equal(left: str | None, right: str | None) -> bool:
    if left == right:
        return True
    if left is None or right is None:
        return False
    try:
        left_decimal = Decimal(left)
        right_decimal = Decimal(right)
    except InvalidOperation:
        return False
    return (
        left_decimal.is_finite()
        and right_decimal.is_finite()
        and left_decimal == right_decimal
    )


def _validate_analysis_fact_binding(evidence_alias: str, path: str) -> None:
    alias_identifier = (
        evidence_alias.split(":", 1)[1] if ":" in evidence_alias else None
    )
    path_parts = path.split(".")
    path_identifiers = {
        path_parts[index + 1]
        for index, part in enumerate(path_parts[:-1])
        if part in {"items", "skus"}
    }
    if path_identifiers and (
        alias_identifier is None or path_identifiers != {alias_identifier}
    ):
        raise ActionInvalid("analysis_fact_authority_mismatch")


def _authority_identifiers(alias: str) -> set[str]:
    evidence_alias, separator, path = alias.partition("|")
    identifiers: set[str] = set()
    if ":" in evidence_alias:
        identifiers.add(evidence_alias.split(":", 1)[1])
    if separator:
        parts = path.split(".")
        identifiers.update(
            parts[index + 1]
            for index, part in enumerate(parts[:-1])
            if part in {"items", "skus"}
        )
    return identifiers


def _validate_facts(facts: tuple[FactRef, ...]) -> None:
    if not facts or len(facts) > 100:
        raise ActionInvalid("facts_invalid")
    aliases: set[str] = set()
    for fact in facts:
        if fact.alias in aliases or not fact.alias or len(fact.alias) > 200:
            raise ActionInvalid("fact_alias_invalid")
        aliases.add(fact.alias)
        if not fact.source_ref or len(fact.source_ref) > 500:
            raise ActionInvalid("fact_source_invalid")
        if fact.evidence_state not in {"measured", "derived", "assumed", "unknown"}:
            raise ActionInvalid("fact_evidence_state_invalid")
        _validate_synthetic(
            (
                {
                    "alias": fact.alias,
                    "source_ref": fact.source_ref,
                    "value": fact.value,
                },
            )
        )


def _validate_reason(reason: str) -> None:
    if not isinstance(reason, str) or not SAFE_TEXT.fullmatch(reason):
        raise ActionInvalid("reason_invalid")
    _validate_synthetic(({"reason": reason},))


def _validate_adjustment(adjustment: ActionAdjustment) -> None:
    if adjustment.suggestion is not None and (
        not adjustment.suggestion
        or not SAFE_TEXT.fullmatch(adjustment.suggestion)
    ):
        raise ActionInvalid("adjustment_suggestion_invalid")
    if adjustment.target is not None and (
        not adjustment.target.startswith("SYNTH-")
        or not SAFE_TEXT.fullmatch(adjustment.target)
    ):
        raise ActionInvalid("adjustment_target_invalid")
    for field, value in (
        ("quantity", adjustment.quantity),
        ("budget_brl", adjustment.budget_brl),
    ):
        if value is not None and (not value.is_finite() or value < 0):
            raise ActionInvalid(f"adjustment_{field}_invalid")
    if adjustment.threshold is not None and not adjustment.threshold.is_finite():
        raise ActionInvalid("adjustment_threshold_invalid")
    if adjustment.confidence is not None and adjustment.confidence not in {
        "low",
        "medium",
        "high",
    }:
        raise ActionInvalid("adjustment_confidence_invalid")
    _validate_synthetic(
        (
            {
                "suggestion": adjustment.suggestion,
                "target": adjustment.target,
                "expected_impact": adjustment.expected_impact,
                "limitations": adjustment.limitations,
            },
        )
    )


def _validate_overlay_adjustment(adjustment: dict[str, object]) -> None:
    allowed = {"quantity", "budget_brl"}
    if (
        not adjustment
        or len(adjustment) > len(allowed)
        or not set(adjustment) <= allowed
        or len(json.dumps(adjustment, separators=(",", ":")).encode()) > 16_384
    ):
        raise ActionInvalid("overlay_adjustment_invalid")
    for field in ("quantity", "budget_brl"):
        value = adjustment.get(field)
        if value is None:
            continue
        if len(str(value)) > 64:
            raise ActionInvalid(f"overlay_{field}_invalid")
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            raise ActionInvalid(f"overlay_{field}_invalid") from error
        if not number.is_finite() or number < 0:
            raise ActionInvalid(f"overlay_{field}_invalid")
    _validate_synthetic(({"adjustment": adjustment},))


def _validate_synthetic(records) -> None:
    try:
        flattened = []
        for record in records:
            values: dict[str, object] = {}
            _flatten_synthetic_values(record, "", values)
            flattened.append(values)
        validate_synthetic_records(flattened)
    except SyntheticSourceBoundaryError as error:
        raise ActionInvalid("synthetic_boundary_invalid") from error


def _flatten_synthetic_values(
    value: object,
    prefix: str,
    result: dict[str, object],
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            field = f"{prefix}.{key}" if prefix else str(key)
            _flatten_synthetic_values(item, field, result)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            field = f"{prefix}.{index}" if prefix else str(index)
            _flatten_synthetic_values(item, field, result)
        return
    field = prefix or "value"
    identifier_container = next(
        (
            part[:-1]
            for part in reversed(field.split("."))
            if part.lower().endswith("_ids")
        ),
        None,
    )
    if identifier_container is not None:
        field = f"{field}.{identifier_container}"
    result[field] = value


def _fact_payload(facts) -> list[dict[str, object]]:
    return [asdict(fact) for fact in facts]


def _key_hash(key: str) -> bytes:
    if not isinstance(key, str) or not 1 <= len(key) <= 128 or not key.isascii():
        raise ActionInvalid("idempotency_key_invalid")
    return bytes.fromhex(stable_hash(key))


def _digest_bytes(payload: object) -> bytes:
    return bytes.fromhex(stable_hash(_hashable(payload)))


def _hashable(value: object) -> object:
    value = canonical_value(value)
    if isinstance(value, dict):
        return {str(key): _hashable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_hashable(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    return value


def _lock_key(workspace_id: str, action_id: UUID, session_id: UUID | None = None) -> str:
    suffix = f"/{session_id}" if session_id is not None else ""
    return f"actions/{workspace_token(workspace_id)}/{action_id}{suffix}"


def _sandbox_lock_key(workspace_id: str, session_id: UUID) -> str:
    return f"actions/{workspace_token(workspace_id)}/sandbox/{session_id}"


def _matches_temporary(record, workspace_id: str, item) -> bool:
    return bool(
        record is not None
        and record.workspace_id == workspace_id
        and record.purpose == "temporary_upload"
        and record.state in {"staging", "quarantined"}
        and record.sha256 == item.sha256
        and record.size_bytes == item.size_bytes
        and record.etag == item.etag
    )


def _matches_available_export(record, workspace_id: str, item) -> bool:
    return bool(
        record is not None
        and record.workspace_id == workspace_id
        and record.purpose == "export"
        and record.state == "available"
        and record.sha256 == item.sha256
        and record.size_bytes == item.size_bytes
        and record.etag == item.etag
    )


def _matches_final_reservation(
    record,
    workspace_id: str,
    final_key: str,
    staged,
) -> bool:
    return bool(
        record is not None
        and record.workspace_id == workspace_id
        and record.object_key == final_key
        and record.sha256 == staged.sha256
        and record.size_bytes == staged.size_bytes
        and (
            (
                record.purpose == "temporary_upload"
                and record.state in {"staging", "quarantined"}
            )
            or (record.purpose == "export" and record.state == "available")
        )
    )


def _matches_promotion_reservation(record, workspace_id: str, item) -> bool:
    return bool(
        record is not None
        and record.workspace_id == workspace_id
        and record.object_key == item.key
        and record.purpose == "temporary_upload"
        and record.state == "staging"
        and record.sha256 == item.sha256
        and record.size_bytes == item.size_bytes
        and record.etag is None
    )
