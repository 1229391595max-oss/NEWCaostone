from __future__ import annotations

import json

import pytest

from src.adapters import AdapterRegistry
from src.adapters.shopee_advertising_csv import ShopeeAdvertisingCsvAdapter
from src.adapters.upseller_excel import (
    UpsellerCsvAdapter,
    UpsellerExcelAdapter,
    validate_safe_xlsx_package,
)
from tests.import_support import fixture_bytes


@pytest.mark.parametrize(
    ("filename", "source_role", "adapter_id"),
    [
        ("sales.csv", "daily_sales", "upseller_csv"),
        ("products.csv", "product_sales", "upseller_csv"),
        ("inventory_snapshots.csv", "product_inventory_sales", "upseller_csv"),
        ("inventory_movements.csv", "inventory_movement", "upseller_csv"),
        ("receipt_lots.csv", "inventory_receipt_lot", "upseller_csv"),
        ("outbound_events.csv", "outbound_event", "upseller_csv"),
        ("expenses.csv", "operating_expense", "upseller_csv"),
        ("platform_fees.csv", "settlement", "upseller_csv"),
        ("fx_assumptions.csv", "fx_assumption", "upseller_csv"),
        ("advertising.csv", "shopee_advertising", "shopee_advertising_csv"),
    ],
)
def test_generated_first_release_sources_are_recognized_by_content(
    filename: str,
    source_role: str,
    adapter_id: str,
) -> None:
    result = AdapterRegistry().inspect(filename, "text/csv", fixture_bytes(filename))

    assert result.source_role == source_role
    assert result.adapter_id == adapter_id
    assert result.adapter_version == "1.0.0"
    assert result.details["canonical_schema"] == "canonical.import.v1"


def test_adapters_expose_enforced_parser_limits() -> None:
    adapters = (
        UpsellerExcelAdapter(),
        ShopeeAdvertisingCsvAdapter(),
        UpsellerCsvAdapter(),
    )

    assert all(adapter.limits.max_rows > 0 for adapter in adapters)
    assert all(adapter.limits.max_parse_seconds > 0 for adapter in adapters)


def test_generated_cost_workbook_is_a_safe_passive_xlsx() -> None:
    validate_safe_xlsx_package(fixture_bytes("bizpulse_demo_costs.xlsx"))


def test_declared_replenishment_policy_shape_is_supported() -> None:
    payload = (
        "policy_id,sku_id,lead_time_days,safety_stock_units,"
        "reorder_point_units,target_cover_days,source_classification\n"
        "SYNTH-POLICY-001,SYNTH-SKU-001,14,20,40,30,pure_synthetic\n"
    ).encode()

    result = AdapterRegistry().inspect("replenishment.csv", "text/csv", payload)

    assert result.source_role == "replenishment_policy"


def test_generated_fx_assumption_standardizes_as_usd_exposure_to_brl() -> None:
    content = fixture_bytes("fx_assumptions.csv")
    adapter = UpsellerCsvAdapter()
    recognized = adapter.recognize(content)

    standardized = adapter.standardize(
        content,
        {field: field for field in recognized.source_fields},
    )
    payload = json.loads(standardized.content)

    assert recognized.source_role == "fx_assumption"
    assert {
        row["currency"] for row in payload["tables"]["fx_assumption"]
    } == {"USD"}


def test_generated_expenses_preserve_shared_and_store_scopes() -> None:
    content = fixture_bytes("expenses.csv")
    adapter = UpsellerCsvAdapter()
    recognized = adapter.recognize(content)

    standardized = adapter.standardize(
        content,
        {field: field for field in recognized.source_fields},
    )
    rows = json.loads(standardized.content)["tables"]["operating_expense"]

    assert {row["scope"] for row in rows if not row.get("store_id")} == {"shared"}
    launch = next(row for row in rows if row.get("store_id") == "SYNTH-STORE-02")
    assert launch["scope"] == "store"
