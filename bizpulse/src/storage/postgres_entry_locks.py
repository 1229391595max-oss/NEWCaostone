"""Deterministic PostgreSQL advisory locks for Blob entry operations."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import local

from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

from src.storage.keys import normalize_storage_key

TRY_LOCK = text("SELECT pg_try_advisory_lock(:lock_id)")
UNLOCK = text("SELECT pg_advisory_unlock(:lock_id)")
class StorageEntryBusy(RuntimeError):
    def __init__(self) -> None:
        super().__init__("storage_entry_busy")


class StorageEntryLockUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("storage_entry_lock_unavailable")


@dataclass(frozen=True, slots=True)
class OrderedLockKey:
    normalized_key: str
    advisory_id: int


def advisory_lock_id(key: str) -> int:
    normalized = normalize_storage_key(key)
    return int.from_bytes(
        hashlib.sha256(normalized.encode()).digest()[:8],
        byteorder="big",
        signed=True,
    )


def ordered_lock_keys(keys: Iterable[str]) -> tuple[OrderedLockKey, ...]:
    unique = {normalize_storage_key(key) for key in keys}
    return tuple(
        sorted(
            (OrderedLockKey(key, advisory_lock_id(key)) for key in unique),
            key=lambda item: (item.advisory_id, item.normalized_key),
        )
    )


class PostgresEntryLockManager:
    def __init__(
        self,
        engine: Engine,
        *,
        timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.05,
        monotonic_clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], object] = time.sleep,
    ) -> None:
        self._engine = engine
        self._timeout = timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._clock = monotonic_clock
        self._sleeper = sleeper
        self._active = local()

    @contextmanager
    def acquire(
        self,
        keys: Iterable[str],
        *,
        blocking: bool = True,
    ) -> Iterator[tuple[str, ...]]:
        ordered = ordered_lock_keys(keys)
        normalized = tuple(item.normalized_key for item in ordered)
        lock_ids = tuple(dict.fromkeys(item.advisory_id for item in ordered))
        if not lock_ids:
            yield normalized
            return
        if getattr(self._active, "depth", 0):
            raise StorageEntryLockUnavailable

        deadline = self._clock() + self._timeout if blocking else None
        self._active.depth = 1
        connection: Connection | None = None
        acquired: list[int] = []
        try:
            try:
                connection = self._engine.connect()
                for lock_id in lock_ids:
                    if not self._acquire_one(
                        connection,
                        lock_id,
                        blocking=blocking,
                        deadline=deadline,
                    ):
                        if not _release(connection, acquired):
                            raise StorageEntryLockUnavailable
                        acquired.clear()
                        raise StorageEntryBusy
                    acquired.append(lock_id)
            except (StorageEntryBusy, StorageEntryLockUnavailable):
                raise
            except BaseException as error:
                _invalidate(connection)
                raise StorageEntryLockUnavailable from error

            try:
                yield normalized
            finally:
                if acquired and not _release(connection, acquired):
                    raise StorageEntryLockUnavailable
                acquired.clear()
        finally:
            _close(connection)
            self._active.depth = 0

    def _acquire_one(
        self,
        connection: Connection,
        lock_id: int,
        *,
        blocking: bool,
        deadline: float | None,
    ) -> bool:
        if not blocking:
            acquired = bool(
                connection.execute(TRY_LOCK, {"lock_id": lock_id}).scalar_one()
            )
            if acquired:
                return True
            return False
        assert deadline is not None
        while self._clock() < deadline:
            acquired = bool(
                connection.execute(TRY_LOCK, {"lock_id": lock_id}).scalar_one()
            )
            if acquired:
                return True
            remaining = deadline - self._clock()
            if remaining > 0:
                self._sleeper(min(self._poll_interval, remaining))
        return False


def _release(connection: Connection, lock_ids: Iterable[int]) -> bool:
    try:
        for lock_id in reversed(tuple(lock_ids)):
            if not connection.execute(
                UNLOCK,
                {"lock_id": lock_id},
            ).scalar_one():
                raise RuntimeError("advisory_unlock_failed")
        return True
    except BaseException:
        _invalidate(connection)
        return False


def _invalidate(connection: Connection | None) -> None:
    if connection is not None:
        try:
            connection.invalidate()
        except BaseException:
            pass


def _close(connection: Connection | None) -> None:
    if connection is not None:
        try:
            connection.close()
        except BaseException:
            _invalidate(connection)
