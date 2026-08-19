from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import run_alembic


FORECAST_PROFIT_TABLES = {
    "new_product_forecasts",
    "forecast_analogs",
    "forecast_scenarios",
    "profit_bridges",
    "profit_bridge_items",
}


def test_0004_creates_forecast_profit_tables_and_head(postgres_url: str) -> None:
    run_alembic(postgres_url, "upgrade", "0004_forecast_profit")
    engine = create_engine(postgres_url)
    try:
        inspector = inspect(engine)
        assert FORECAST_PROFIT_TABLES <= set(inspector.get_table_names())
        assert {
            "dataset_version_id",
            "algorithm_version",
            "input_snapshot",
            "input_hash",
            "status",
            "confidence",
            "assumptions",
            "evidence",
            "backtest",
        } <= {
            column["name"]
            for column in inspector.get_columns("new_product_forecasts")
        }
        assert {"horizon_days", "scenario", "units", "revenue_brl"} <= {
            column["name"] for column in inspector.get_columns("forecast_scenarios")
        }
        assert {"forecast_id", "profit_bridge_id"} <= {
            column["name"] for column in inspector.get_columns("demo_sessions")
        }
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0004_forecast_profit"
            )
    finally:
        engine.dispose()


def test_completed_forecast_and_children_are_database_immutable(
    postgres_url: str,
) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    engine = create_engine(postgres_url)
    now = datetime.now(UTC)
    workspace_id = "synthetic-demo"
    series_id = uuid4()
    version_id = uuid4()
    forecast_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO workspaces (id, kind, created_at) "
                    "VALUES (:id, 'single_operator_demo', :now)"
                ),
                {"id": workspace_id, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO dataset_series (id, workspace_id, name, created_at) "
                    "VALUES (:id, :workspace, 'main', :now)"
                ),
                {"id": series_id, "workspace": workspace_id, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO dataset_versions "
                    "(id, series_id, workspace_id, version_number, status, "
                    "schema_version, content_sha256, created_at) VALUES "
                    "(:id, :series, :workspace, 1, 'complete', 'synthetic.v1', "
                    ":digest, :now)"
                ),
                {
                    "id": version_id,
                    "series": series_id,
                    "workspace": workspace_id,
                    "digest": "1" * 64,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO new_product_forecasts "
                    "(id, workspace_id, dataset_version_id, algorithm_version, "
                    "input_snapshot, input_hash, status, confidence, assumptions, "
                    "evidence, result, backtest, created_at, updated_at, completed_at) "
                    "VALUES (:id, :workspace, :version, 'new_product_forecast.v1', "
                    "'{}'::jsonb, :digest, 'completed', 'medium', '[]'::jsonb, "
                    "'{}'::jsonb, '{}'::jsonb, NULL, :now, :now, :now)"
                ),
                {
                    "id": forecast_id,
                    "workspace": workspace_id,
                    "version": version_id,
                    "digest": "2" * 64,
                    "now": now,
                },
            )
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE new_product_forecasts SET confidence = 'high' "
                        "WHERE id = :id"
                    ),
                    {"id": forecast_id},
                )
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO forecast_scenarios "
                        "(id, forecast_id, horizon_days, scenario, units, revenue_brl, "
                        "contribution_profit_brl, stock_cover_days, created_at) VALUES "
                        "(:id, :forecast, 7, 'base', 1, 1, 1, 1, :now)"
                    ),
                    {"id": uuid4(), "forecast": forecast_id, "now": now},
                )
        draft_id = uuid4()
        analog_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO new_product_forecasts "
                    "(id, workspace_id, dataset_version_id, algorithm_version, "
                    "input_snapshot, input_hash, status, confidence, assumptions, "
                    "evidence, result, backtest, created_at, updated_at, completed_at) "
                    "VALUES (:id, :workspace, :version, 'new_product_forecast.v1', "
                    "'{}'::jsonb, :digest, 'draft', NULL, '[]'::jsonb, "
                    "'{}'::jsonb, NULL, NULL, :now, :now, NULL)"
                ),
                {
                    "id": draft_id,
                    "workspace": workspace_id,
                    "version": version_id,
                    "digest": "3" * 64,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO forecast_analogs "
                    "(id, forecast_id, sku_id, rank, score, components, "
                    "historical_snapshot, confirmed, confirmed_at, created_at) "
                    "VALUES (:id, :forecast, 'SYNTH-SKU-001', 1, 1, '{}'::jsonb, "
                    "'{}'::jsonb, false, NULL, :now)"
                ),
                {"id": analog_id, "forecast": draft_id, "now": now},
            )
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE forecast_analogs SET forecast_id = :completed "
                        "WHERE id = :id"
                    ),
                    {"completed": forecast_id, "id": analog_id},
                )
    finally:
        engine.dispose()
