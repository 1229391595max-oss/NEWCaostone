"""Database readiness probe without connection disclosure."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import Engine, text

EXPECTED_SCHEMA_REVISION = "0017_ai_turn_credential_binding"
FORWARD_COMPATIBLE_SCHEMA_REVISIONS = frozenset(
    {
        "0014_import_base_lineage",
        "0015_admin_ai_control",
        "0016_admin_ai_control_integrity",
        EXPECTED_SCHEMA_REVISION,
    }
)


@dataclass(frozen=True, slots=True)
class DatabaseReadiness:
    revision: str | None
    writable: bool
    latency_ms: float


def readiness(engine: Engine) -> DatabaseReadiness:
    """Verify connectivity, temporary writes, and the installed revision."""

    started_at = perf_counter()
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL statement_timeout = '1s'"))
        connection.execute(text("SET LOCAL lock_timeout = '1s'"))
        connection.execute(
            text(
                "CREATE TEMPORARY TABLE bizpulse_readiness_probe "
                "(probe INTEGER NOT NULL) ON COMMIT DROP"
            )
        )
        connection.execute(
            text("INSERT INTO bizpulse_readiness_probe (probe) VALUES (1)")
        )
        has_revision_table = connection.scalar(
            text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        )
        revision = (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            if has_revision_table
            else None
        )
    return DatabaseReadiness(
        revision=str(revision) if revision is not None else None,
        writable=True,
        latency_ms=round((perf_counter() - started_at) * 1_000, 3),
    )
