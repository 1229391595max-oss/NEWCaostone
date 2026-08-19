"""Inventory Blob/ledger drift; expire temporary objects only when requested."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ID = "synthetic-demo"


class InventoryReport(Protocol):
    blob_orphan_keys: tuple[str, ...]
    database_missing_keys: tuple[str, ...]


class LifecycleMaintenance(Protocol):
    def expire(self, now: datetime) -> int: ...

    def orphan_inventory(self, prefix: str) -> InventoryReport: ...


def run_maintenance(
    lifecycle: LifecycleMaintenance,
    *,
    prefix: str,
    expire_temporary: bool,
    now: datetime,
) -> dict[str, int]:
    """Return bounded counts and never delete permanent or orphan objects."""

    expired = lifecycle.expire(now) if expire_temporary else 0
    inventory = lifecycle.orphan_inventory(prefix)
    return {
        "expired_temporary": expired,
        "blob_orphan_count": len(inventory.blob_orphan_keys),
        "database_missing_count": len(inventory.database_missing_keys),
    }


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expire-temporary",
        action="store_true",
        help="delete only expired temporary uploads recorded in PostgreSQL",
    )
    parser.add_argument(
        "--prefix",
        help="override the validated workspace inventory prefix",
    )
    options = parser.parse_args(arguments)

    sys.path.insert(0, str(PROJECT_ROOT))
    from api.container import ApiContainer  # noqa: PLC0415
    from src.config import BizPulseSettings  # noqa: PLC0415
    from src.storage.keys import workspace_token  # noqa: PLC0415

    settings = BizPulseSettings.from_env()
    container = ApiContainer.build(settings)
    if container.storage_lifecycle is None:
        parser.error("blob_storage_is_not_enabled")
    prefix = options.prefix or f"workspaces/{workspace_token(WORKSPACE_ID)}"
    try:
        result = run_maintenance(
            container.storage_lifecycle,
            prefix=prefix,
            expire_temporary=options.expire_temporary,
            now=datetime.now(UTC),
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        if container.engine is not None:
            container.engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
