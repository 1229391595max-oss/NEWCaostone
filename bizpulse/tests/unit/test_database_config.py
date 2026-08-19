from __future__ import annotations

import pytest

from src.config import BizPulseSettings, ConfigError
from src.db.engine import DatabaseConfigurationError, create_postgres_engine


def test_cloud_runtime_rejects_non_postgresql_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIZPULSE_RUNTIME_ENVIRONMENT", "cloud")
    monkeypatch.setenv("BIZPULSE_ALLOWED_ORIGIN", "https://demo.example.test")
    monkeypatch.setenv("BIZPULSE_DATABASE_URL", "sqlite:///forbidden.db")

    with pytest.raises(ConfigError, match="cloud_database_url_must_use_postgresql"):
        BizPulseSettings.from_env()


def test_engine_factory_rejects_non_postgresql_url() -> None:
    with pytest.raises(
        DatabaseConfigurationError,
        match="database_url_must_use_postgresql",
    ):
        create_postgres_engine("sqlite:///forbidden.db")


def test_engine_representation_hides_database_password() -> None:
    engine = create_postgres_engine(
        "postgresql+psycopg://operator:super-secret@localhost/bizpulse",
        null_pool=True,
    )
    try:
        assert "super-secret" not in str(engine.url)
        assert engine.hide_parameters is True
    finally:
        engine.dispose()
