from __future__ import annotations

from uuid import uuid4

import pytest

from src.services.preferences_service import (
    PreferenceRevisionConflict,
    PreferencesService,
)
from tests.auth_support import WORKSPACE_ID, fast_password_hasher, seed_operator


def test_operator_preferences_views_and_targets_are_revisioned(migrated_engine) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    service = PreferencesService(migrated_engine, WORKSPACE_ID)
    operator_id = service.operator_id()

    initial = service.get_preferences(operator_id)
    assert initial["revision"] == 0
    assert initial["overview_kpis"] == [
        "net_sales", "orders", "roas", "ad_spend",
        "contribution_profit", "stockout_skus",
    ]

    saved = service.save_preferences(
        operator_id,
        expected_revision=0,
        document={
            **initial,
            "locale": "zh",
            "sidebar_mode": "compact",
            "reporting_currency": "BRL",
            "timezone": "America/Sao_Paulo",
        },
    )
    assert saved["revision"] == 1
    assert service.get_preferences(operator_id)["locale"] == "zh"
    with pytest.raises(PreferenceRevisionConflict):
        service.save_preferences(operator_id, expected_revision=0, document=saved)

    view = service.create_saved_view(
        operator_id,
        name="Urgent inventory",
        kind="today",
        config={"route": "inventory", "priority": "P0"},
    )
    renamed = service.update_saved_view(
        operator_id,
        view["id"],
        expected_revision=1,
        name="P0 inventory",
        config=view["config"],
    )
    assert renamed["revision"] == 2
    assert service.list_saved_views(operator_id)[0]["name"] == "P0 inventory"

    target = service.create_target(
        operator_id,
        period="2026-08",
        revenue_brl="100000.00",
        orders=2400,
        roas="4.25",
        profit_brl="18000.00",
    )
    archived = service.set_target_status(
        operator_id,
        target["id"],
        expected_revision=1,
        status="archived",
    )
    restored = service.set_target_status(
        operator_id,
        target["id"],
        expected_revision=2,
        status="active",
    )
    assert archived["status"] == "archived"
    assert restored["status"] == "active"
    assert restored["revision"] == 3


def test_preferences_are_scoped_to_the_authenticated_operator(migrated_engine) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    service = PreferencesService(migrated_engine, WORKSPACE_ID)
    assert service.get_preferences(uuid4())["revision"] == 0
    assert service.list_saved_views(uuid4()) == ()
    assert service.list_targets(uuid4()) == ()
