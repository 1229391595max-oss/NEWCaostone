from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine

from src.storage.postgres_entry_locks import (
    PostgresEntryLockManager,
    StorageEntryBusy,
    StorageEntryLockUnavailable,
    advisory_lock_id,
    ordered_lock_keys,
)


def test_reversed_requests_have_identical_deterministic_order() -> None:
    forward = ordered_lock_keys(["workspace/z", "workspace/a", "workspace/m"])
    reverse = ordered_lock_keys(["workspace/m", "workspace/a", "workspace/z"])

    assert forward == reverse
    assert [item.advisory_id for item in forward] == sorted(
        {advisory_lock_id(key) for key in ["workspace/z", "workspace/a", "workspace/m"]}
    )


def test_real_nonblocking_contention_and_release(migrated_engine: Engine) -> None:
    first = PostgresEntryLockManager(migrated_engine)
    second = PostgresEntryLockManager(migrated_engine)

    def try_second_session() -> str:
        try:
            with second.acquire(
                ["workspace/synthetic-demo/import/run-1"],
                blocking=False,
            ):
                return "acquired"
        except StorageEntryBusy:
            return "busy"

    with first.acquire(["workspace/synthetic-demo/import/run-1"]):
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(try_second_session).result() == "busy"

    with second.acquire(
        ["workspace/synthetic-demo/import/run-1"],
        blocking=False,
    ) as acquired:
        assert acquired == ("workspace/synthetic-demo/import/run-1",)


def test_distinct_lock_domains_can_nest_on_same_thread(
    migrated_engine: Engine,
) -> None:
    workflow = PostgresEntryLockManager(migrated_engine)
    storage = PostgresEntryLockManager(migrated_engine)

    with workflow.acquire(["workspaces/demo/runs/run-1"]):
        with storage.acquire(["workspaces/demo/objects/blob-1"]):
            pass


def test_same_lock_manager_rejects_nested_acquisition(
    migrated_engine: Engine,
) -> None:
    storage = PostgresEntryLockManager(migrated_engine)

    with storage.acquire(["workspaces/demo/objects/blob-1"]):
        with pytest.raises(StorageEntryLockUnavailable):
            with storage.acquire(["workspaces/demo/objects/blob-2"]):
                raise AssertionError("same-domain nested lock must not enter")


@dataclass
class FakeClock:
    value: float = 10.0

    def __call__(self) -> float:
        return self.value


class FakeResult:
    def __init__(self, value: bool) -> None:
        self._value = value

    def scalar_one(self) -> bool:
        return self._value


class FakeConnection:
    def __init__(self, results: list[bool]) -> None:
        self.results = iter(results)
        self.operations: list[tuple[str, int]] = []
        self.invalidated = False
        self.closed = False

    def execute(self, statement, parameters):
        operation = "unlock" if "unlock" in str(statement) else "lock"
        self.operations.append((operation, parameters["lock_id"]))
        return FakeResult(next(self.results))

    def invalidate(self) -> None:
        self.invalidated = True

    def close(self) -> None:
        self.closed = True


class FakeEngine:
    def __init__(self, connection: FakeConnection, clock: FakeClock) -> None:
        self.connection = connection
        self.clock = clock

    def connect(self) -> FakeConnection:
        self.clock.value += 0.6
        return self.connection


def test_one_deadline_includes_connection_checkout() -> None:
    clock = FakeClock()
    connection = FakeConnection([])
    manager = PostgresEntryLockManager(
        FakeEngine(connection, clock),
        timeout_seconds=0.5,
        poll_interval_seconds=0.1,
        monotonic_clock=clock,
        sleeper=lambda _seconds: None,
    )

    with pytest.raises(StorageEntryBusy):
        with manager.acquire(["workspace/a", "workspace/b"]):
            raise AssertionError("expired deadline must not enter")

    assert connection.operations == []
    assert connection.closed is True


def test_nonblocking_partial_acquisition_releases_in_reverse_order() -> None:
    clock = FakeClock()
    connection = FakeConnection([True, True, False, True, True])
    manager = PostgresEntryLockManager(
        FakeEngine(connection, clock),
        monotonic_clock=clock,
    )
    lock_ids = [
        item.advisory_id
        for item in ordered_lock_keys(["workspace/a", "workspace/b", "workspace/c"])
    ]

    with pytest.raises(StorageEntryBusy):
        with manager.acquire(
            ["workspace/a", "workspace/b", "workspace/c"],
            blocking=False,
        ):
            raise AssertionError("partial acquisition must not enter")

    assert connection.operations == [
        ("lock", lock_ids[0]),
        ("lock", lock_ids[1]),
        ("lock", lock_ids[2]),
        ("unlock", lock_ids[1]),
        ("unlock", lock_ids[0]),
    ]
    assert connection.closed is True
