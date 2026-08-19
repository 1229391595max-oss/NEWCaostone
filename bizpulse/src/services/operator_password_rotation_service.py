"""Transactional, server-owned rotation of the synthetic Demo operator."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine, text

from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.repositories.sessions import SessionRepository
from src.storage.postgres_entry_locks import advisory_lock_id


ROTATION_LOCK = text("SELECT pg_advisory_xact_lock(:lock_id)")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class OperatorPasswordRotationAuthorityError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("operator_rotation_authority_missing")


class OperatorPasswordRotationConflict(RuntimeError):
    """Raised when a package's expected credential state no longer matches."""


class OperatorPasswordRotationInvalid(RuntimeError):
    """Raised before any transaction for malformed rotation input."""


@dataclass(frozen=True, slots=True)
class RotationResult:
    status: str
    revoked_session_count: int
    deleted_ephemeral_chat_count: int


class OperatorPasswordRotationService:
    """Rotate one named active operator under one PostgreSQL transaction lock."""

    def __init__(
        self,
        *,
        engine: Engine,
        workspace_id: str,
        login_name: str,
        uow_factory=PostgresUnitOfWork,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._engine = engine
        self._workspace_id = workspace_id
        self._login_name = login_name
        self._uow_factory = uow_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock_id = advisory_lock_id(
            f"operator/credential-rotation/{workspace_id}"
        )

    def rotate(
        self,
        *,
        expected_hash_fingerprint: str,
        replacement_password_hash: str,
    ) -> RotationResult:
        if _SHA256.fullmatch(expected_hash_fingerprint) is None:
            raise OperatorPasswordRotationInvalid("expected_hash_fingerprint_invalid")
        if not replacement_password_hash:
            raise OperatorPasswordRotationInvalid("replacement_password_hash_missing")
        with self._uow_factory(self._engine) as uow:
            uow.connection.execute(ROTATION_LOCK, {"lock_id": self._lock_id})
            attempt = OperatorRepository(
                uow.connection
            ).rotate_active_password_hash(
                workspace_id=self._workspace_id,
                login_name=self._login_name,
                expected_hash_fingerprint=expected_hash_fingerprint,
                replacement_password_hash=replacement_password_hash,
                now=self._clock(),
            )
            if attempt is None:
                raise OperatorPasswordRotationAuthorityError
            if attempt.status == "expected_hash_mismatch":
                raise OperatorPasswordRotationConflict("expected_hash_mismatch")
            if attempt.status == "already_rotated":
                return RotationResult(
                    status="already_rotated",
                    revoked_session_count=0,
                    deleted_ephemeral_chat_count=0,
                )
            revoked = SessionRepository(uow.connection).revoke_active_for_operator(
                attempt.operator_id,
                now=self._clock(),
            )
            return RotationResult(
                status="rotated",
                revoked_session_count=revoked.revoked_session_count,
                deleted_ephemeral_chat_count=revoked.deleted_ephemeral_chat_count,
            )
