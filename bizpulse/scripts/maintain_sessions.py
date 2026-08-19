"""Expire elapsed Demo sessions and their ephemeral session-owned state."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DemoSessionMaintenance(Protocol):
    def expire_sessions(self, now: datetime) -> int: ...


def run_maintenance(
    service: DemoSessionMaintenance,
    *,
    now: datetime,
) -> dict[str, int]:
    return {"expired_demo_sessions": service.expire_sessions(now)}


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(arguments)
    sys.path.insert(0, str(PROJECT_ROOT))

    from api.container import ApiContainer  # noqa: PLC0415
    from src.config import BizPulseSettings  # noqa: PLC0415

    container = ApiContainer.build(BizPulseSettings.from_env())
    if container.demo_session_service is None:
        parser.error("demo_session_service_is_not_enabled")
    try:
        result = run_maintenance(
            container.demo_session_service,
            now=datetime.now(UTC),
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        if container.engine is not None:
            container.engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
