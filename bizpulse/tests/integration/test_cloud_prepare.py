from __future__ import annotations

from sqlalchemy import create_engine, func, select, text

from scripts.prepare_cloud import prepare_cloud_database
from src.config import BizPulseSettings
from src.db.schema import operator_accounts, workspaces

PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$"
    "dspPsWevmFQvVX8T5BXmFA$"
    "ayB1yKL+3347+SAAe59WoJsD4u1eZvHySBBiSx1jfIk"
)


def _settings(postgres_url: str) -> BizPulseSettings:
    return BizPulseSettings(
        runtime_environment="cloud",
        database_url=postgres_url,
        blob_endpoint="https://blob.test",
        blob_container="synthetic-demo",
        allowed_origin="https://demo.test",
        cookie_secure=True,
        operator_password_hash=PASSWORD_HASH,
    )


def test_cloud_prepare_migrates_fresh_database_and_bootstraps_once(
    postgres_url: str,
) -> None:
    first = prepare_cloud_database(_settings(postgres_url))
    second = prepare_cloud_database(_settings(postgres_url))

    assert first == {
        "migration_head": "0014_import_base_lineage",
        "operator_created": True,
        "workspace_created": True,
    }
    assert second == {
        "migration_head": "0014_import_base_lineage",
        "operator_created": False,
        "workspace_created": False,
    }
    engine = create_engine(postgres_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0014_import_base_lineage"
            )
            assert connection.scalar(select(func.count()).select_from(workspaces)) == 1
            assert (
                connection.scalar(select(func.count()).select_from(operator_accounts))
                == 1
            )
    finally:
        engine.dispose()
