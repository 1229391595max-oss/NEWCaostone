"""Single source of truth for the deterministic public Demo release."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from src.services.canonical_contracts import StoreDescriptor


@dataclass(frozen=True, slots=True)
class DemoStoreProfile:
    store_id: str
    display_name_en: str
    display_name_zh: str
    opened_on: date
    lifecycle: Literal["established", "new"]
    listed_sku_ids: tuple[str, ...]

    def descriptor(self, currency: str) -> StoreDescriptor:
        return StoreDescriptor(
            store_id=self.store_id,
            display_name_en=self.display_name_en,
            display_name_zh=self.display_name_zh,
            currency=currency,
            opened_on=self.opened_on,
            lifecycle=self.lifecycle,
            has_data=True,
        )


@dataclass(frozen=True, slots=True)
class PublicReleaseProfile:
    store_id: str
    currency: str
    reporting_period: tuple[date, date]
    comparison_period: tuple[date, date]
    current_period: tuple[date, date]
    supporting_history_start: date

    def scope(self) -> dict[str, str]:
        return {"store_id": self.store_id, "currency": self.currency}

    def analysis_scope(self) -> dict[str, str]:
        return {
            **self.scope(),
            "period_start": self.current_period[0].isoformat(),
            "period_end": self.current_period[1].isoformat(),
        }

    def monthly_periods(self) -> tuple[tuple[date, date], ...]:
        periods = []
        current = self.reporting_period[0]
        while current <= self.reporting_period[1]:
            next_month = (
                date(current.year + 1, 1, 1)
                if current.month == 12
                else date(current.year, current.month + 1, 1)
            )
            periods.append((current, min(next_month - timedelta(days=1), self.reporting_period[1])))
            current = next_month
        return tuple(periods)


PUBLIC_RELEASE_PROFILE = PublicReleaseProfile(
    store_id="SYNTH-STORE-01",
    currency="BRL",
    reporting_period=(date(2026, 5, 1), date(2026, 7, 31)),
    comparison_period=(date(2026, 6, 1), date(2026, 6, 30)),
    current_period=(date(2026, 7, 1), date(2026, 7, 31)),
    supporting_history_start=date(2026, 3, 15),
)

MAIN_STORE_PROFILE = DemoStoreProfile(
    store_id="SYNTH-STORE-01",
    display_name_en="Brazil Main Store",
    display_name_zh="巴西主店",
    opened_on=date(2026, 5, 1),
    lifecycle="established",
    listed_sku_ids=(
        "SYNTH-SKU-001",
        "SYNTH-SKU-002",
        "SYNTH-SKU-003",
        "SYNTH-SKU-004",
        "SYNTH-SKU-005",
        "SYNTH-SKU-006",
    ),
)

LAUNCH_STORE_PROFILE = DemoStoreProfile(
    store_id="SYNTH-STORE-02",
    display_name_en="Brazil Launch Store",
    display_name_zh="巴西新店",
    opened_on=date(2026, 7, 8),
    lifecycle="new",
    listed_sku_ids=(
        "SYNTH-SKU-001",
        "SYNTH-SKU-003",
        "SYNTH-SKU-006",
    ),
)

DEMO_STORE_PROFILES = (MAIN_STORE_PROFILE, LAUNCH_STORE_PROFILE)
DEMO_STORE_CATALOG = tuple(
    profile.descriptor(PUBLIC_RELEASE_PROFILE.currency)
    for profile in DEMO_STORE_PROFILES
)

PUBLIC_SOURCE_ROLES = (
    "daily_sales",
    "shopee_advertising",
    "product_inventory_sales",
    "inventory_movement",
    "inventory_receipt_lot",
    "outbound_event",
    "refund",
    "settlement",
    "fulfillment_cost",
    "operating_expense",
    "fx_assumption",
    "fx_effect",
    "other_variable_cost",
    "replenishment_policy",
    "product_catalog",
    "new_product_benchmark",
    "new_product_backtest_window",
)
