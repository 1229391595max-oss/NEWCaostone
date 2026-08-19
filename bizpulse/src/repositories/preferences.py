"""Bounded persistence for Operator workspace settings."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection, delete, select, update

from src.db.schema import saved_views, workspace_preferences, workspace_targets


class PreferencesRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    @staticmethod
    def _dict(row):
        return dict(row) if row is not None else None

    def get_preferences(self, workspace_id: str, operator_id: UUID):
        row = self._connection.execute(
            select(*workspace_preferences.c).where(
                workspace_preferences.c.workspace_id == workspace_id,
                workspace_preferences.c.operator_id == operator_id,
            )
        ).mappings().one_or_none()
        return self._dict(row)

    def insert_preferences(self, values: dict[str, object]):
        row = self._connection.execute(
            workspace_preferences.insert().values(**values).returning(*workspace_preferences.c)
        ).mappings().one()
        return self._dict(row)

    def update_preferences(
        self,
        workspace_id: str,
        operator_id: UUID,
        expected_revision: int,
        values: dict[str, object],
    ):
        row = self._connection.execute(
            update(workspace_preferences)
            .where(
                workspace_preferences.c.workspace_id == workspace_id,
                workspace_preferences.c.operator_id == operator_id,
                workspace_preferences.c.revision == expected_revision,
            )
            .values(**values, revision=expected_revision + 1)
            .returning(*workspace_preferences.c)
        ).mappings().one_or_none()
        return self._dict(row)

    def list_saved_views(self, workspace_id: str, operator_id: UUID):
        rows = self._connection.execute(
            select(*saved_views.c)
            .where(
                saved_views.c.workspace_id == workspace_id,
                saved_views.c.operator_id == operator_id,
            )
            .order_by(saved_views.c.updated_at.desc(), saved_views.c.id)
            .limit(40)
        ).mappings()
        return tuple(dict(row) for row in rows)

    def insert_saved_view(self, values: dict[str, object]):
        row = self._connection.execute(
            saved_views.insert().values(**values).returning(*saved_views.c)
        ).mappings().one()
        return self._dict(row)

    def update_saved_view(
        self,
        workspace_id: str,
        operator_id: UUID,
        view_id: UUID,
        expected_revision: int,
        values: dict[str, object],
    ):
        row = self._connection.execute(
            update(saved_views)
            .where(
                saved_views.c.id == view_id,
                saved_views.c.workspace_id == workspace_id,
                saved_views.c.operator_id == operator_id,
                saved_views.c.revision == expected_revision,
            )
            .values(**values, revision=expected_revision + 1)
            .returning(*saved_views.c)
        ).mappings().one_or_none()
        return self._dict(row)

    def delete_saved_view(
        self,
        workspace_id: str,
        operator_id: UUID,
        view_id: UUID,
        expected_revision: int,
    ) -> bool:
        result = self._connection.execute(
            delete(saved_views).where(
                saved_views.c.id == view_id,
                saved_views.c.workspace_id == workspace_id,
                saved_views.c.operator_id == operator_id,
                saved_views.c.revision == expected_revision,
            )
        )
        return result.rowcount == 1

    def list_targets(self, workspace_id: str, operator_id: UUID):
        rows = self._connection.execute(
            select(*workspace_targets.c)
            .where(
                workspace_targets.c.workspace_id == workspace_id,
                workspace_targets.c.operator_id == operator_id,
            )
            .order_by(workspace_targets.c.period.desc(), workspace_targets.c.id)
            .limit(36)
        ).mappings()
        return tuple(dict(row) for row in rows)

    def insert_target(self, values: dict[str, object]):
        row = self._connection.execute(
            workspace_targets.insert().values(**values).returning(*workspace_targets.c)
        ).mappings().one()
        return self._dict(row)

    def update_target(
        self,
        workspace_id: str,
        operator_id: UUID,
        target_id: UUID,
        expected_revision: int,
        values: dict[str, object],
    ):
        row = self._connection.execute(
            update(workspace_targets)
            .where(
                workspace_targets.c.id == target_id,
                workspace_targets.c.workspace_id == workspace_id,
                workspace_targets.c.operator_id == operator_id,
                workspace_targets.c.revision == expected_revision,
            )
            .values(**values, revision=expected_revision + 1)
            .returning(*workspace_targets.c)
        ).mappings().one_or_none()
        return self._dict(row)
