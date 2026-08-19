"""Migrate and idempotently bootstrap the private cloud PostgreSQL authority."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ID = "synthetic-demo"


def prepare_cloud_database(settings) -> dict[str, object]:
    from src.db.engine import create_postgres_engine  # noqa: PLC0415
    from src.db.readiness import (  # noqa: PLC0415
        EXPECTED_SCHEMA_REVISION,
        readiness,
    )
    from src.services.foundation_bootstrap_service import (  # noqa: PLC0415
        FoundationBootstrapService,
    )

    if settings.runtime_environment != "cloud":
        raise RuntimeError("cloud_prepare_requires_cloud_runtime")
    if settings.operator_password_hash is None:
        raise RuntimeError("cloud_operator_password_hash_invalid")
    configuration = Config(str(PROJECT_ROOT / "alembic.ini"))
    configuration.set_main_option(
        "script_location",
        str(PROJECT_ROOT / "alembic"),
    )
    configuration.set_main_option(
        "sqlalchemy.url",
        settings.database_url.replace("%", "%%"),
    )
    command.upgrade(configuration, "head")

    engine = create_postgres_engine(settings.database_url)
    try:
        bootstrap = FoundationBootstrapService(
            engine=engine,
            workspace_id=WORKSPACE_ID,
            login_name="operator",
            password_hash=settings.operator_password_hash,
        ).bootstrap()
        probe = readiness(engine)
        if not probe.writable or probe.revision != EXPECTED_SCHEMA_REVISION:
            raise RuntimeError("cloud_prepare_authority_not_ready")
        return {
            "migration_head": probe.revision,
            "operator_created": bootstrap.operator_created,
            "workspace_created": bootstrap.workspace_created,
        }
    finally:
        engine.dispose()


def main() -> int:
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.config import BizPulseSettings  # noqa: PLC0415

    result = prepare_cloud_database(BizPulseSettings.from_env())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
