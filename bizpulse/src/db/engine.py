"""PostgreSQL engine creation with safe diagnostics."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.pool import NullPool


class DatabaseConfigurationError(ValueError):
    """Raised when the database connection contract is invalid."""


def create_postgres_engine(
    database_url: str,
    *,
    null_pool: bool = False,
) -> Engine:
    """Create an engine only for PostgreSQL and hide parameter values."""

    try:
        parsed_url = make_url(database_url)
    except ArgumentError as error:
        raise DatabaseConfigurationError("database_url_is_invalid") from error
    if parsed_url.get_backend_name() != "postgresql":
        raise DatabaseConfigurationError("database_url_must_use_postgresql")

    options: dict[str, object] = {
        "hide_parameters": True,
        "pool_pre_ping": True,
    }
    if null_pool:
        options["poolclass"] = NullPool
    else:
        options["pool_timeout"] = 1
    return create_engine(parsed_url, **options)
