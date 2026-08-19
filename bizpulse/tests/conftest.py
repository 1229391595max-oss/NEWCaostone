from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url

EPHEMERAL_MARKER = "managed-by-newcaostone-test-runner"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def alembic_config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def run_alembic(database_url: str, action: str, revision: str) -> None:
    config = alembic_config(database_url)
    getattr(command, action)(config, revision)


@pytest.fixture
def postgres_url() -> Iterator[str]:
    base_url = os.getenv("BIZPULSE_TEST_POSTGRES_URL")
    marker = os.getenv("BIZPULSE_TEST_POSTGRES_EPHEMERAL")
    if base_url is None or marker != EPHEMERAL_MARKER:
        pytest.skip("requires the guarded scripts/test_postgres.py runner")

    database_name = f"bizpulse_test_{uuid4().hex}"
    psycopg_url = make_url(base_url).set(drivername="postgresql")
    with psycopg.connect(psycopg_url.render_as_string(hide_password=False)) as connection:
        connection.autocommit = True
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))

    test_url = make_url(base_url).set(database=database_name).render_as_string(
        hide_password=False
    )
    try:
        yield test_url
    finally:
        with psycopg.connect(
            psycopg_url.render_as_string(hide_password=False)
        ) as connection:
            connection.autocommit = True
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            connection.execute(
                sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name))
            )


@pytest.fixture
def migrated_engine(postgres_url: str) -> Iterator[Engine]:
    run_alembic(postgres_url, "upgrade", "head")
    engine = create_engine(postgres_url)
    try:
        yield engine
    finally:
        engine.dispose()
