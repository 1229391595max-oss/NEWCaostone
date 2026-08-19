"""Hashed idempotency receipt checks without projecting raw keys or bodies."""

from __future__ import annotations

import hmac
from datetime import datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import Connection, select

from src.db.schema import idempotency_receipts

IdempotencyDisposition = Literal["missing", "replay", "conflict", "in_progress"]


class IdempotencyRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def check(
        self,
        *,
        scope_type: str,
        scope_id: str,
        operation: str,
        key_hash: bytes,
        request_hash: bytes,
    ) -> IdempotencyDisposition:
        row = self._connection.execute(
            select(
                idempotency_receipts.c.request_hash,
                idempotency_receipts.c.outcome,
            ).where(
                idempotency_receipts.c.scope_type == scope_type,
                idempotency_receipts.c.scope_id == scope_id,
                idempotency_receipts.c.operation == operation,
                idempotency_receipts.c.key_hash == key_hash,
            )
        ).one_or_none()
        if row is None:
            return "missing"
        if not hmac.compare_digest(bytes(row.request_hash), request_hash):
            return "conflict"
        return "replay" if row.outcome == "succeeded" else "in_progress"

    def replay_projection(
        self,
        *,
        scope_type: str,
        scope_id: str,
        operation: str,
        key_hash: bytes,
        request_hash: bytes,
    ) -> dict[str, object] | None:
        row = self._connection.execute(
            select(
                idempotency_receipts.c.request_hash,
                idempotency_receipts.c.outcome,
                idempotency_receipts.c.response_projection,
            ).where(
                idempotency_receipts.c.scope_type == scope_type,
                idempotency_receipts.c.scope_id == scope_id,
                idempotency_receipts.c.operation == operation,
                idempotency_receipts.c.key_hash == key_hash,
            )
        ).mappings().one_or_none()
        if (
            row is None
            or row["outcome"] != "succeeded"
            or not hmac.compare_digest(bytes(row["request_hash"]), request_hash)
            or row["response_projection"] is None
        ):
            return None
        return dict(row["response_projection"])

    def record_succeeded(
        self,
        *,
        scope_type: str,
        scope_id: str,
        operation: str,
        key_hash: bytes,
        request_hash: bytes,
        response_status: int,
        response_body_hash: bytes,
        response_projection: dict[str, object],
        now: datetime,
        expires_at: datetime,
    ) -> None:
        self._connection.execute(
            idempotency_receipts.insert().values(
                id=uuid4(),
                scope_type=scope_type,
                scope_id=scope_id,
                operation=operation,
                key_hash=key_hash,
                request_hash=request_hash,
                response_status=response_status,
                response_body_hash=response_body_hash,
                response_projection=response_projection,
                outcome="succeeded",
                created_at=now,
                expires_at=expires_at,
            )
        )
