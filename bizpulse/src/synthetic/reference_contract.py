"""Metadata-only decisions for the user-provided Demo reference files."""

from __future__ import annotations

from dataclasses import dataclass

from src.synthetic.contracts import SyntheticBundle


@dataclass(frozen=True, slots=True)
class ReferenceDecision:
    filename: str
    expected_columns: tuple[str, ...]
    currency_decision: str
    sku_namespace_decision: str
    included: bool
    reason: str
    canonical_runtime_role: str | None


_REFERENCE_DECISIONS = {
    "bizpulse_demo_daily_sales_performance_20260701-20260731.xlsx": ReferenceDecision(
        filename="bizpulse_demo_daily_sales_performance_20260701-20260731.xlsx",
        expected_columns=(
            "日期",
            "总订单量",
            "总销售额",
            "有效订单量",
            "有效销售额",
            "取消订单量",
            "取消订单销售额",
            "客户数",
            "客单价",
        ),
        currency_decision="BRL_compatible",
        sku_namespace_decision="aggregate_no_sku",
        included=True,
        reason="validation_reference_only",
        canonical_runtime_role=None,
    ),
    "bizpulse_demo_inventory_reported_velocity_20260702-20260731.xlsx": ReferenceDecision(
        filename="bizpulse_demo_inventory_reported_velocity_20260702-20260731.xlsx",
        expected_columns=(
            "SKU",
            "Item Title",
            "销售出库",
            "日均销售出库",
            "低库存",
            "在途中",
            "可用库存",
            "Stock on Hand",
            "发售日",
            "发售至今天数",
            "待发货",
            "次品库存",
        ),
        currency_decision="not_applicable",
        sku_namespace_decision="reference_only",
        included=True,
        reason="replenishment_input_reference",
        canonical_runtime_role="replenishment_policy",
    ),
    "bizpulse_demo_inventory_snapshot_20260731.xlsx": ReferenceDecision(
        filename="bizpulse_demo_inventory_snapshot_20260731.xlsx",
        expected_columns=(
            "SKU",
            "Product Name",
            "Available Stock",
            "Current Stock",
            "In Transit",
            "Reserved Stock",
            "Defective Stock",
        ),
        currency_decision="not_applicable",
        sku_namespace_decision="reference_only",
        included=True,
        reason="inventory_field_reference",
        canonical_runtime_role="product_inventory_sales",
    ),
    "bizpulse_demo_operations.xlsx": ReferenceDecision(
        filename="bizpulse_demo_operations.xlsx",
        expected_columns=(
            "SKU",
            "Product Name",
            "Available Stock",
            "Current Stock",
            "In Transit",
            "Reserved Stock",
            "Defective Stock",
            "Scenario",
            "Period",
            "Cost Category",
            "Amount",
            "Currency",
            "Business Unit",
            "Batch Name",
            "Notes",
            "Shipment Batch ID",
            "Container Batch Name",
            "Shipment Batch Type",
            "Arrival Batch Date",
            "Freight Batch Cost",
            "Unloading Batch Cost",
            "Goods Batch Cost",
            "Warehouse Provider",
            "Remaining Units",
        ),
        currency_decision="BRL_compatible",
        sku_namespace_decision="reference_only",
        included=True,
        reason="cost_receipt_inventory_concept_reference",
        canonical_runtime_role="cost_inputs",
    ),
    "bizpulse_demo_overall_advertising_20260701-20260731.csv": ReferenceDecision(
        filename="bizpulse_demo_overall_advertising_20260701-20260731.csv",
        expected_columns=(
            "Date",
            "Impressions",
            "Clicks",
            "Expense",
            "Sales",
            "Orders",
            "Items Sold",
            "ROAS",
            "ACOS",
            "Currency",
        ),
        currency_decision="BRL_compatible",
        sku_namespace_decision="aggregate_no_sku",
        included=True,
        reason="advertising_field_reference",
        canonical_runtime_role="shopee_advertising",
    ),
    "bizpulse_demo_sales_by_variant_20260701-20260731.xlsx": ReferenceDecision(
        filename="bizpulse_demo_sales_by_variant_20260701-20260731.xlsx",
        expected_columns=(
            "产品",
            "店铺",
            "SKU",
            "多变种",
            "变种ID",
            "父SKU",
            "产品 ID",
            "有效订单量",
            "销量",
            "销售额",
            "平均售价",
        ),
        currency_decision="BRL_compatible",
        sku_namespace_decision="reference_only",
        included=True,
        reason="sku_coverage_reference",
        canonical_runtime_role=None,
    ),
    "bizpulse_demo_sales.csv": ReferenceDecision(
        filename="bizpulse_demo_sales.csv",
        expected_columns=(
            "Date",
            "SKU",
            "Product Name",
            "Units Sold",
            "Revenue",
            "Currency",
            "Platform",
            "Region",
        ),
        currency_decision="USD_incompatible",
        sku_namespace_decision="BP_incompatible",
        included=False,
        reason="currency_and_sku_namespace_mismatch",
        canonical_runtime_role=None,
    ),
}

_CANONICAL_ROLE_FILES = {
    "sales_authority": ("sales.csv",),
    "cost_authority": ("products.csv", "receipt_lots.csv", "platform_fees.csv"),
}


def classify_reference(filename: str) -> ReferenceDecision:
    try:
        return _REFERENCE_DECISIONS[filename]
    except KeyError as error:
        raise ValueError("reference_file_unknown") from error


def canonical_role_count(bundle: SyntheticBundle, role: str) -> int:
    try:
        expected_paths = _CANONICAL_ROLE_FILES[role]
    except KeyError as error:
        raise ValueError("canonical_role_unknown") from error
    actual_paths = {item.relative_path for item in bundle.files}
    return sum(path in actual_paths for path in expected_paths)
