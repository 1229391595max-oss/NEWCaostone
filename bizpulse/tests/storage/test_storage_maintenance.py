from __future__ import annotations

from datetime import UTC, datetime

from src.storage.lifecycle import OrphanInventory
from scripts.maintain_storage import run_maintenance


class RecordingLifecycle:
    def __init__(self) -> None:
        self.expire_calls = 0
        self.inventory_prefixes: list[str] = []

    def expire(self, now: datetime) -> int:
        del now
        self.expire_calls += 1
        return 2

    def orphan_inventory(self, prefix: str) -> OrphanInventory:
        self.inventory_prefixes.append(prefix)
        return OrphanInventory(
            blob_orphan_keys=("workspaces/orphan",),
            database_missing_keys=("workspaces/missing",),
        )


def test_maintenance_defaults_to_inventory_without_deleting_temporary() -> None:
    lifecycle = RecordingLifecycle()

    report = run_maintenance(
        lifecycle,
        prefix="workspaces/demo",
        expire_temporary=False,
        now=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert lifecycle.expire_calls == 0
    assert report == {
        "expired_temporary": 0,
        "blob_orphan_count": 1,
        "database_missing_count": 1,
    }


def test_temporary_expiry_requires_explicit_switch() -> None:
    lifecycle = RecordingLifecycle()

    report = run_maintenance(
        lifecycle,
        prefix="workspaces/demo",
        expire_temporary=True,
        now=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert lifecycle.expire_calls == 1
    assert report["expired_temporary"] == 2
