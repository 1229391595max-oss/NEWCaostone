"""Immutable contracts for deterministic contribution-profit decomposition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ProfitSku:
    sku_id: str
    quantity: int
    net_unit_revenue_brl: Decimal | None
    unit_cogs_brl: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.sku_id, str) or not self.sku_id.strip():
            raise ValueError("profit_sku_id_invalid")
        if type(self.quantity) is not int or self.quantity < 0:
            raise ValueError("profit_sku_quantity_invalid")
        _optional_decimal(
            self.net_unit_revenue_brl,
            "profit_sku_net_unit_revenue_invalid",
            nonnegative=True,
        )
        _optional_decimal(
            self.unit_cogs_brl,
            "profit_sku_unit_cogs_invalid",
            nonnegative=True,
        )


@dataclass(frozen=True, slots=True)
class ProfitPeriod:
    period_start: date
    period_end: date
    skus: tuple[ProfitSku, ...]
    contribution_profit_brl: Decimal | None
    platform_fee_brl: Decimal | None
    advertising_brl: Decimal | None
    refund_loss_brl: Decimal | None
    fulfillment_brl: Decimal | None
    tax_brl: Decimal | None
    fx_effect_brl: Decimal | None
    other_mapped_brl: Decimal | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.period_start, date)
            or not isinstance(self.period_end, date)
            or self.period_start > self.period_end
        ):
            raise ValueError("profit_period_invalid")
        if not isinstance(self.skus, tuple) or not all(
            isinstance(item, ProfitSku) for item in self.skus
        ):
            raise ValueError("profit_period_skus_invalid")
        sku_ids = tuple(item.sku_id for item in self.skus)
        if len(set(sku_ids)) != len(sku_ids):
            raise ValueError("profit_period_sku_duplicate")
        _optional_decimal(
            self.contribution_profit_brl,
            "profit_contribution_invalid",
        )
        for field_name in (
            "platform_fee_brl",
            "advertising_brl",
            "refund_loss_brl",
            "fulfillment_brl",
            "tax_brl",
            "other_mapped_brl",
        ):
            _optional_decimal(
                getattr(self, field_name),
                f"{field_name}_invalid",
                nonnegative=True,
            )
        _optional_decimal(self.fx_effect_brl, "fx_effect_brl_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "period_start": self.period_start,
            "period_end": self.period_end,
            "skus": self.skus,
            "contribution_profit_brl": self.contribution_profit_brl,
            "platform_fee_brl": self.platform_fee_brl,
            "advertising_brl": self.advertising_brl,
            "refund_loss_brl": self.refund_loss_brl,
            "fulfillment_brl": self.fulfillment_brl,
            "tax_brl": self.tax_brl,
            "fx_effect_brl": self.fx_effect_brl,
            "other_mapped_brl": self.other_mapped_brl,
        }


@dataclass(frozen=True, slots=True)
class ProfitBridgeItem:
    driver: str
    ordinal: int
    amount_brl: Decimal | None
    evidence_state: str
    formula: str
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProfitBridge:
    formula_version: str
    baseline_period: tuple[date, date]
    current_period: tuple[date, date]
    baseline_contribution_profit_brl: Decimal | None
    current_contribution_profit_brl: Decimal | None
    total_change_brl: Decimal | None
    items: tuple[ProfitBridgeItem, ...]
    residual_brl: Decimal | None
    reconciled: bool
    limitations: tuple[str, ...]

    def item(self, driver: str) -> ProfitBridgeItem:
        for item in self.items:
            if item.driver == driver:
                return item
        raise KeyError(driver)


def _optional_decimal(
    value: Decimal | None,
    code: str,
    *,
    nonnegative: bool = False,
) -> None:
    if value is None:
        return
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(code)
    if nonnegative and value < 0:
        raise ValueError(code)
