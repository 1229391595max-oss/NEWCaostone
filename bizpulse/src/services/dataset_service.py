"""Operator reads for immutable dataset versions and the current release."""

from __future__ import annotations

from sqlalchemy import Engine

from src.repositories.datasets import (
    DatasetRepository,
    DatasetVersionProjection,
    PublicReleaseProjection,
)


class DatasetService:
    def __init__(self, engine: Engine, workspace_id: str) -> None:
        self._engine = engine
        self._workspace_id = workspace_id

    def list_versions(self) -> tuple[DatasetVersionProjection, ...]:
        with self._engine.connect() as connection:
            return DatasetRepository(connection).list_versions(self._workspace_id)

    def current_public_release(self) -> PublicReleaseProjection | None:
        with self._engine.connect() as connection:
            return DatasetRepository(connection).current_release(self._workspace_id)
