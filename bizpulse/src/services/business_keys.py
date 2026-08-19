"""Exhaustive business-key registry for normalized canonical rows."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping

BusinessKey = tuple[tuple[str, str], ...]

_KEY_FIELDS: dict[str, tuple[str, ...]] = {
    "daily_sales": ("store_id", "order_id", "sku_id"),
    "shopee_advertising": ("store_id", "date", "sku_id"),
    "product_inventory_sales": ("store_id", "date", "sku_id"),
    "inventory_movement": ("store_id", "movement_id"),
    "inventory_receipt_lot": ("store_id", "lot_id"),
    "outbound_event": ("store_id", "outbound_id"),
    "refund": ("store_id", "refund_id"),
    "fulfillment_cost": ("store_id", "fulfillment_id"),
    "fx_effect": ("store_id", "fx_effect_id"),
    "other_variable_cost": ("store_id", "cost_id"),
    "product_catalog": ("sku_id",),
    "replenishment_policy": ("store_id", "sku_id"),
    "fx_assumption": ("currency", "period_start", "period_end"),
    "new_product_benchmark": ("forecast_id",),
    "new_product_backtest_window": ("window_id",),
}


class BusinessKeyIncomplete(ValueError):
    code = "business_key_incomplete"

    def __init__(self, role: str, fields: tuple[str, ...]) -> None:
        self.role = role
        self.fields = fields
        super().__init__(f"{self.code}:{role}:{','.join(fields)}")


class BusinessKeyUnsupported(ValueError):
    code = "unsupported_role"

    def __init__(self, role: str) -> None:
        self.role = role
        super().__init__(f"{self.code}:{role}")


def business_key(role: str, row: Mapping[str, object]) -> BusinessKey:
    if role == "settlement":
        return _settlement_key(row)
    if role == "operating_expense":
        return _operating_expense_key(row)
    fields = _KEY_FIELDS.get(role)
    if fields is None:
        raise BusinessKeyUnsupported(role)
    return _key(role, row, fields)


def _settlement_key(row: Mapping[str, object]) -> BusinessKey:
    identifiers = tuple(
        field for field in ("fee_id", "settlement_id") if not _blank(row.get(field))
    )
    if len(identifiers) != 1:
        raise BusinessKeyIncomplete("settlement", ("fee_id", "settlement_id"))
    return _key("settlement", row, ("store_id", identifiers[0]))


def _operating_expense_key(row: Mapping[str, object]) -> BusinessKey:
    if not _blank(row.get("store_id")):
        return _key("operating_expense", row, ("store_id", "expense_id"))
    if row.get("scope") == "shared":
        return _key("operating_expense", row, ("expense_id",))
    if _blank(row.get("expense_id")):
        raise BusinessKeyIncomplete("operating_expense", ("expense_id",))
    raise BusinessKeyIncomplete("operating_expense", ("store_id", "scope"))


def _key(
    role: str,
    row: Mapping[str, object],
    fields: tuple[str, ...],
) -> BusinessKey:
    missing = tuple(field for field in fields if _blank(row.get(field)))
    if missing:
        raise BusinessKeyIncomplete(role, missing)
    try:
        return tuple((field, _canonical_string(row[field])) for field in fields)
    except (InvalidOperation, ValueError):
        raise BusinessKeyIncomplete(role, fields) from None


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _canonical_string(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, Decimal)):
        parsed = Decimal(str(value))
        if not parsed.is_finite():
            raise ValueError("business_key_number_invalid")
        return format(parsed.normalize(), "f")
    return str(value)
