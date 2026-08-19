"""Role-specific canonical field and value validation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from src.adapters.protocol import MappingInvalid, SourceShapeInvalid

ROLE_REQUIRED_OPTIONS = {
    "daily_sales": (
        frozenset(
            {"date", "order_id", "store_id", "sku_id", "units", "gross_sales_brl"}
        ),
    ),
    "product_sales": (
        frozenset({"sku_id", "product_name", "category", "unit_price_brl"}),
    ),
    "product_inventory_sales": (
        frozenset({"date", "store_id", "sku_id", "on_hand_units", "inbound_units"}),
    ),
    "inventory_movement": (
        frozenset(
            {"movement_id", "date", "store_id", "sku_id", "movement_type", "quantity"}
        ),
    ),
    "inventory_receipt_lot": (
        frozenset(
            {
                "lot_id",
                "receipt_date",
                "store_id",
                "sku_id",
                "quantity_received",
                "unit_cost_brl",
            }
        ),
    ),
    "outbound_event": (
        frozenset({"outbound_id", "date", "store_id", "sku_id", "quantity"}),
    ),
    "operating_expense": (
        frozenset(
            {"expense_id", "period_start", "period_end", "expense_type", "amount_brl"}
        ),
    ),
    "settlement": (
        frozenset(
            {"fee_id", "period_start", "period_end", "store_id", "fee_brl"}
        ),
        frozenset(
            {
                "settlement_id",
                "period_start",
                "period_end",
                "store_id",
                "payout_brl",
            }
        ),
    ),
    "fx_assumption": (
        frozenset(
            {"fx_id", "period_start", "period_end", "currency", "brl_per_usd"}
        ),
    ),
    "replenishment_policy": (
        frozenset(
            {
                "policy_id",
                "sku_id",
                "lead_time_days",
                "safety_stock_units",
                "reorder_point_units",
                "target_cover_days",
            }
        ),
    ),
    "shopee_advertising": (
        frozenset(
            {
                "date",
                "sku_id",
                "spend_brl",
                "impressions",
                "clicks",
                "attributed_orders",
            }
        ),
    ),
}
DATE_FIELDS = {"date", "receipt_date", "settlement_date", "period_start", "period_end"}
INTEGER_FIELDS = {
    "units",
    "impressions",
    "clicks",
    "attributed_orders",
    "on_hand_units",
    "inbound_units",
    "quantity",
    "quantity_received",
    "lead_time_days",
    "safety_stock_units",
    "reorder_point_units",
    "target_cover_days",
}
DECIMAL_FIELDS = {
    "unit_price_brl",
    "discount_brl",
    "gross_sales_brl",
    "net_sales_brl",
    "spend_brl",
    "unit_cost_brl",
    "amount_brl",
    "fee_rate",
    "fee_brl",
    "payout_brl",
    "brl_per_usd",
}


def role_has_required_fields(role: str, fields: set[str]) -> bool:
    options = ROLE_REQUIRED_OPTIONS.get(role)
    return options is not None and any(required <= fields for required in options)


def validate_mapping(
    source_fields: set[str],
    mapping: dict[str, str],
    *,
    allowed_fields: set[str],
    roles: tuple[str, ...],
) -> None:
    if set(mapping) != source_fields or not set(mapping.values()) <= allowed_fields:
        raise MappingInvalid("mapping_fields_invalid")
    if len(set(mapping.values())) != len(mapping):
        raise MappingInvalid("mapping_targets_must_be_unique")
    if any(source != target for source, target in mapping.items()):
        raise MappingInvalid("mapping_semantic_mismatch")
    canonical_fields = set(mapping.values())
    if any(not role_has_required_fields(role, canonical_fields) for role in roles):
        raise MappingInvalid("mapping_required_field_missing")


def validate_role_records(
    role: str,
    records: list[dict[str, object]],
) -> None:
    canonicalize_role_records(role, records)


def canonicalize_role_records(
    role: str,
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not records or not role_has_required_fields(role, set(records[0])):
        raise SourceShapeInvalid("canonical_required_fields_missing")
    normalized_records = []
    for record in records:
        if set(record) != set(records[0]):
            raise SourceShapeInvalid("canonical_fields_inconsistent")
        required = next(
            option
            for option in ROLE_REQUIRED_OPTIONS[role]
            if option <= set(record)
        )
        if any(_is_blank(record[field]) for field in required):
            raise SourceShapeInvalid("canonical_required_value_missing")
        parsed_dates = {
            field: _date(record[field])
            for field in DATE_FIELDS & set(record)
            if not _is_blank(record[field])
        }
        integers = {
            field: _nonnegative_integer(record[field])
            for field in INTEGER_FIELDS & set(record)
            if not _is_blank(record[field])
        }
        decimals = {
            field: _nonnegative_decimal(record[field])
            for field in DECIMAL_FIELDS & set(record)
            if not _is_blank(record[field])
        }
        if (
            "period_start" in parsed_dates
            and "period_end" in parsed_dates
            and parsed_dates["period_start"] > parsed_dates["period_end"]
        ):
            raise SourceShapeInvalid("canonical_period_invalid")
        if integers.get("clicks", 0) > integers.get("impressions", 0):
            raise SourceShapeInvalid("canonical_clicks_exceed_impressions")
        if integers.get("attributed_orders", 0) > integers.get("clicks", 0):
            raise SourceShapeInvalid("canonical_orders_exceed_clicks")
        if decimals.get("discount_brl", Decimal(0)) > decimals.get(
            "gross_sales_brl",
            Decimal(0),
        ):
            raise SourceShapeInvalid("canonical_discount_exceeds_gross")
        if "fee_rate" in decimals and decimals["fee_rate"] > Decimal(1):
            raise SourceShapeInvalid("canonical_fee_rate_invalid")
        if "currency" in record:
            expected_currency = "USD" if role == "fx_assumption" else "BRL"
            if record["currency"] != expected_currency:
                raise SourceShapeInvalid("canonical_currency_invalid")
        normalized = dict(record)
        normalized.update(
            {field: value.isoformat() for field, value in parsed_dates.items()}
        )
        normalized.update(integers)
        normalized.update(
            {
                field: format(value.normalize(), "f")
                for field, value in decimals.items()
            }
        )
        normalized_records.append(normalized)
    return normalized_records


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _date(value: object) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise SourceShapeInvalid("canonical_date_invalid") from error


def _nonnegative_integer(value: object) -> int:
    if isinstance(value, bool):
        raise SourceShapeInvalid("canonical_integer_invalid")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as error:
        raise SourceShapeInvalid("canonical_integer_invalid") from error
    if not parsed.is_finite() or parsed < 0 or parsed != parsed.to_integral_value():
        raise SourceShapeInvalid("canonical_integer_invalid")
    return int(parsed)


def _nonnegative_decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise SourceShapeInvalid("canonical_decimal_invalid")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as error:
        raise SourceShapeInvalid("canonical_decimal_invalid") from error
    if not parsed.is_finite() or parsed < 0:
        raise SourceShapeInvalid("canonical_decimal_invalid")
    return parsed
