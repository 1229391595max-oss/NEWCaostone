from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.adapters.validation import canonicalize_role_records
from src.services.business_keys import (
    BusinessKeyIncomplete,
    BusinessKeyUnsupported,
    business_key,
)


@pytest.mark.parametrize(
    ("role", "row", "expected"),
    [
        (
            "daily_sales",
            {"store_id": "S1", "order_id": "O1", "sku_id": "K1"},
            (("store_id", "S1"), ("order_id", "O1"), ("sku_id", "K1")),
        ),
        (
            "shopee_advertising",
            {"store_id": "S1", "date": "2026-07-01", "sku_id": "K1"},
            (("store_id", "S1"), ("date", "2026-07-01"), ("sku_id", "K1")),
        ),
        (
            "product_inventory_sales",
            {"store_id": "S1", "date": "2026-07-01", "sku_id": "K1"},
            (("store_id", "S1"), ("date", "2026-07-01"), ("sku_id", "K1")),
        ),
        (
            "inventory_movement",
            {"store_id": "S1", "movement_id": "M1"},
            (("store_id", "S1"), ("movement_id", "M1")),
        ),
        (
            "inventory_receipt_lot",
            {"store_id": "S1", "lot_id": "L1"},
            (("store_id", "S1"), ("lot_id", "L1")),
        ),
        (
            "outbound_event",
            {"store_id": "S1", "outbound_id": "OUT1"},
            (("store_id", "S1"), ("outbound_id", "OUT1")),
        ),
        (
            "refund",
            {"store_id": "S1", "refund_id": "R1"},
            (("store_id", "S1"), ("refund_id", "R1")),
        ),
        (
            "settlement",
            {"store_id": "S1", "fee_id": "F1"},
            (("store_id", "S1"), ("fee_id", "F1")),
        ),
        (
            "settlement",
            {"store_id": "S1", "settlement_id": "SET1"},
            (("store_id", "S1"), ("settlement_id", "SET1")),
        ),
        (
            "fulfillment_cost",
            {"store_id": "S1", "fulfillment_id": "FUL1"},
            (("store_id", "S1"), ("fulfillment_id", "FUL1")),
        ),
        (
            "operating_expense",
            {"store_id": "S1", "expense_id": "E1"},
            (("store_id", "S1"), ("expense_id", "E1")),
        ),
        (
            "operating_expense",
            {"scope": "shared", "expense_id": "E1"},
            (("expense_id", "E1"),),
        ),
        (
            "fx_effect",
            {"store_id": "S1", "fx_effect_id": "FXE1"},
            (("store_id", "S1"), ("fx_effect_id", "FXE1")),
        ),
        (
            "other_variable_cost",
            {"store_id": "S1", "cost_id": "C1"},
            (("store_id", "S1"), ("cost_id", "C1")),
        ),
        (
            "product_catalog",
            {"sku_id": "K1"},
            (("sku_id", "K1"),),
        ),
        (
            "replenishment_policy",
            {"store_id": "S1", "sku_id": "K1"},
            (("store_id", "S1"), ("sku_id", "K1")),
        ),
        (
            "fx_assumption",
            {
                "currency": "USD",
                "period_start": "2026-07-01",
                "period_end": "2026-07-31",
            },
            (
                ("currency", "USD"),
                ("period_start", "2026-07-01"),
                ("period_end", "2026-07-31"),
            ),
        ),
        (
            "new_product_benchmark",
            {"forecast_id": "FC1"},
            (("forecast_id", "FC1"),),
        ),
        (
            "new_product_backtest_window",
            {"window_id": "W1"},
            (("window_id", "W1"),),
        ),
    ],
)
def test_business_keys_are_explicit(role, row, expected) -> None:
    assert business_key(role, row) == expected


def test_business_key_normalizes_dates_and_numeric_identifiers_after_adapter() -> None:
    rows = [
        {
            "store_id": "S1",
            "date": date(2026, 7, 1),
            "sku_id": sku_id,
            "spend_brl": spend,
            "impressions": 100,
            "clicks": 10,
            "attributed_orders": 2,
        }
        for sku_id, spend in (
            (5, 5),
            (5.0, 5.0),
            (Decimal("5.00"), Decimal("5.00")),
        )
    ]

    keys = {
        business_key(
            "shopee_advertising",
            canonicalize_role_records("shopee_advertising", [row])[0],
        )
        for row in rows
    }

    assert keys == {
        (("store_id", "S1"), ("date", "2026-07-01"), ("sku_id", "5"))
    }


@pytest.mark.parametrize(
    ("role", "row", "fields"),
    [
        ("daily_sales", {"store_id": "S1", "order_id": "O1"}, ("sku_id",)),
        (
            "operating_expense",
            {"expense_id": "E1"},
            ("store_id", "scope"),
        ),
        (
            "settlement",
            {"store_id": "S1"},
            ("fee_id", "settlement_id"),
        ),
        (
            "settlement",
            {"store_id": "S1", "fee_id": "F1", "settlement_id": "SET1"},
            ("fee_id", "settlement_id"),
        ),
        ("product_catalog", {"sku_id": "  "}, ("sku_id",)),
    ],
)
def test_incomplete_or_ambiguous_business_keys_fail_closed(
    role,
    row,
    fields,
) -> None:
    with pytest.raises(BusinessKeyIncomplete) as captured:
        business_key(role, row)

    assert captured.value.code == "business_key_incomplete"
    assert captured.value.role == role
    assert captured.value.fields == fields


def test_unknown_role_has_no_whole_row_hash_fallback() -> None:
    with pytest.raises(BusinessKeyUnsupported, match="unsupported_role"):
        business_key("unknown", {"id": "1"})
