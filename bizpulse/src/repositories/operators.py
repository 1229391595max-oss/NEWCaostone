"""Workspace and single-operator repository."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, func, insert, select, update

from src.db.schema import operator_accounts, workspaces


@dataclass(frozen=True, slots=True)
class OperatorProjection:
    id: UUID
    workspace_id: str
    login_name: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class FoundationAuthority:
    workspace_kind: str | None
    operator_count: int
    active_operator: OperatorProjection | None
    credential_matches: bool


@dataclass(frozen=True, slots=True)
class OperatorPasswordRotationAttempt:
    """Hash-free result of locking and changing one active operator row."""

    operator_id: UUID
    status: Literal["rotated", "already_rotated", "expected_hash_mismatch"]


class OperatorRepository:
    """Persist the one workspace and one operator without projecting secrets."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create_workspace(
        self,
        workspace_id: str,
        *,
        now: datetime | None = None,
    ) -> str:
        created_at = now or datetime.now(UTC)
        self._connection.execute(
            insert(workspaces).values(
                id=workspace_id,
                kind="single_operator_demo",
                created_at=created_at,
            )
        )
        return workspace_id

    def create_operator(
        self,
        *,
        workspace_id: str,
        login_name: str,
        password_hash: str,
        operator_id: UUID | None = None,
        now: datetime | None = None,
    ) -> OperatorProjection:
        resolved_id = operator_id or uuid4()
        timestamp = now or datetime.now(UTC)
        self._connection.execute(
            insert(operator_accounts).values(
                id=resolved_id,
                workspace_id=workspace_id,
                login_name=login_name,
                password_hash=password_hash,
                status="active",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        return OperatorProjection(
            id=resolved_id,
            workspace_id=workspace_id,
            login_name=login_name,
            status="active",
            created_at=timestamp,
            updated_at=timestamp,
        )

    def get_active(self, workspace_id: str) -> OperatorProjection | None:
        row = self._connection.execute(
            select(
                operator_accounts.c.id,
                operator_accounts.c.workspace_id,
                operator_accounts.c.login_name,
                operator_accounts.c.status,
                operator_accounts.c.created_at,
                operator_accounts.c.updated_at,
            ).where(
                operator_accounts.c.workspace_id == workspace_id,
                operator_accounts.c.status == "active",
            )
        ).mappings().one_or_none()
        return OperatorProjection(**row) if row is not None else None

    def foundation_authority(
        self,
        *,
        workspace_id: str,
        login_name: str,
        password_hash: str,
    ) -> FoundationAuthority:
        workspace_kind = self._connection.scalar(
            select(workspaces.c.kind).where(workspaces.c.id == workspace_id)
        )
        operator_count = int(
            self._connection.scalar(
                select(func.count())
                .select_from(operator_accounts)
                .where(operator_accounts.c.workspace_id == workspace_id)
            )
            or 0
        )
        row = self._connection.execute(
            select(
                operator_accounts.c.id,
                operator_accounts.c.workspace_id,
                operator_accounts.c.login_name,
                operator_accounts.c.password_hash,
                operator_accounts.c.status,
                operator_accounts.c.created_at,
                operator_accounts.c.updated_at,
            ).where(
                operator_accounts.c.workspace_id == workspace_id,
                operator_accounts.c.status == "active",
            )
        ).mappings().one_or_none()
        if row is None:
            return FoundationAuthority(
                workspace_kind=str(workspace_kind) if workspace_kind else None,
                operator_count=operator_count,
                active_operator=None,
                credential_matches=False,
            )
        return FoundationAuthority(
            workspace_kind=str(workspace_kind) if workspace_kind else None,
            operator_count=operator_count,
            active_operator=OperatorProjection(
                id=row["id"],
                workspace_id=row["workspace_id"],
                login_name=row["login_name"],
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            ),
            credential_matches=hmac.compare_digest(
                str(row["password_hash"]),
                password_hash,
            ),
        )

    def authenticate(
        self,
        *,
        workspace_id: str,
        login_name: str,
        verifier: Callable[[str], bool],
        fallback_hash: str,
    ) -> OperatorProjection | None:
        """Verify a stored credential without returning its hash."""

        row = self._connection.execute(
            select(
                operator_accounts.c.id,
                operator_accounts.c.workspace_id,
                operator_accounts.c.login_name,
                operator_accounts.c.password_hash,
                operator_accounts.c.status,
                operator_accounts.c.created_at,
                operator_accounts.c.updated_at,
            ).where(
                operator_accounts.c.workspace_id == workspace_id,
                operator_accounts.c.login_name == login_name,
                operator_accounts.c.status == "active",
            )
        ).mappings().one_or_none()
        credential_hash = row["password_hash"] if row is not None else fallback_hash
        verified = verifier(credential_hash)
        if row is None or not verified:
            return None
        return OperatorProjection(
            id=row["id"],
            workspace_id=row["workspace_id"],
            login_name=row["login_name"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def rotate_active_password_hash(
        self,
        *,
        workspace_id: str,
        login_name: str,
        expected_hash_fingerprint: str,
        replacement_password_hash: str,
        now: datetime,
    ) -> OperatorPasswordRotationAttempt | None:
        """Lock and change precisely the configured active operator credential.

        The raw stored hash is used only inside this method.  Callers receive a
        status and operator ID, never the credential material itself.
        """

        row = self._connection.execute(
            select(
                operator_accounts.c.id,
                operator_accounts.c.password_hash,
            )
            .where(
                operator_accounts.c.workspace_id == workspace_id,
                operator_accounts.c.login_name == login_name,
                operator_accounts.c.status == "active",
            )
            .with_for_update(of=operator_accounts)
        ).mappings().one_or_none()
        if row is None:
            return None
        stored_hash = str(row["password_hash"])
        if hmac.compare_digest(stored_hash, replacement_password_hash):
            return OperatorPasswordRotationAttempt(
                operator_id=row["id"],
                status="already_rotated",
            )
        stored_fingerprint = hashlib.sha256(stored_hash.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(stored_fingerprint, expected_hash_fingerprint):
            return OperatorPasswordRotationAttempt(
                operator_id=row["id"],
                status="expected_hash_mismatch",
            )
        changed = self._connection.execute(
            update(operator_accounts)
            .where(
                operator_accounts.c.id == row["id"],
                operator_accounts.c.status == "active",
            )
            .values(password_hash=replacement_password_hash, updated_at=now)
        )
        if changed.rowcount != 1:
            raise RuntimeError("operator_password_rotation_update_lost")
        return OperatorPasswordRotationAttempt(
            operator_id=row["id"],
            status="rotated",
        )
