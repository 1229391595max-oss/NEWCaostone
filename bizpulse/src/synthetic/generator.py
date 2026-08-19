"""Deterministically generate the source-level pure-synthetic Demo fixture."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import Path
from random import Random

import xlsxwriter

from src.synthetic.contracts import SyntheticBundle, SyntheticFile, SyntheticManifest
from src.services.canonical_contracts import StoreDescriptor
from src.synthetic.release_profile import (
    DEMO_STORE_CATALOG,
    LAUNCH_STORE_PROFILE,
    MAIN_STORE_PROFILE,
    PUBLIC_RELEASE_PROFILE,
)

GENERATOR_VERSION = "1.5.0"
DEFAULT_SEED = 20260813
SCHEMA_VERSION = "synthetic.v1"
SOURCE_CLASSIFICATION = "pure_synthetic"
CURRENCY = PUBLIC_RELEASE_PROFILE.currency
START_DATE = PUBLIC_RELEASE_PROFILE.reporting_period[0]
CURRENT_PERIOD_START = PUBLIC_RELEASE_PROFILE.current_period[0]
END_DATE = PUBLIC_RELEASE_PROFILE.reporting_period[1]
MANIFEST_START_DATE = PUBLIC_RELEASE_PROFILE.supporting_history_start
SCENARIO_IDS = (
    "sales_ads_growth",
    "inventory_stockout",
    "fifo_aging",
    "profit_decline_ad_spend",
    "new_product_low_base_high",
    "profit_bridge_residual",
    "chat_clarification",
    "action_outcome",
)
CSV_MEDIA_TYPE = "text/csv"
JSON_MEDIA_TYPE = "application/json"
XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

PRODUCTS = (
    ("SYNTH-SKU-001", "travel_bag", Decimal("129.90"), Decimal("48.00")),
    ("SYNTH-SKU-002", "desk_accessory", Decimal("79.90"), Decimal("24.00")),
    ("SYNTH-SKU-003", "home_storage", Decimal("99.90"), Decimal("37.00")),
    ("SYNTH-SKU-004", "fitness_accessory", Decimal("149.90"), Decimal("58.00")),
    ("SYNTH-SKU-005", "kitchen_accessory", Decimal("59.90"), Decimal("18.00")),
    ("SYNTH-SKU-006", "pet_accessory", Decimal("89.90"), Decimal("31.00")),
)
PRODUCT_ATTRIBUTES = {
    "SYNTH-SKU-001": "portable|zippered|nylon|compact",
    "SYNTH-SKU-002": "compact|desktop|adjustable",
    "SYNTH-SKU-003": "stackable|modular|durable",
    "SYNTH-SKU-004": "portable|durable|adjustable",
    "SYNTH-SKU-005": "compact|washable|lightweight",
    "SYNTH-SKU-006": "portable|durable|compact",
}


def generate_demo(
    seed: int = DEFAULT_SEED,
    schema_version: str = SCHEMA_VERSION,
) -> SyntheticBundle:
    if type(seed) is not int or seed < 0:
        raise ValueError("synthetic_seed_invalid")
    if schema_version != SCHEMA_VERSION:
        raise ValueError("synthetic_schema_version_unsupported")

    rng = Random(seed)
    tables = _build_tables(rng)
    files = [
        _csv_file(f"{name}.csv", rows)
        for name, rows in sorted(tables.items())
    ]
    files.append(_analysis_bundle_file(tables, DEMO_STORE_CATALOG))
    workbook_tables = {
        "Daily Sales": tables["sales"],
        "Advertising": tables["advertising"],
        "Inventory": tables["inventory_snapshots"],
        "Receipt Lots": tables["receipt_lots"],
        "Expenses": tables["expenses"],
    }
    files.append(_xlsx_file("operator_import.xlsx", workbook_tables))
    files.append(
        _xlsx_file(
            "bizpulse_demo_costs.xlsx",
            {
                "sku_costs": _sku_cost_rows(tables["products"]),
                "inventory_receipts": tables["receipt_lots"],
                "platform_fees": tables["platform_fees"],
            },
        )
    )
    ordered_files = tuple(sorted(files, key=lambda item: item.relative_path))
    manifest = SyntheticManifest(
        schema_version=schema_version,
        generator_version=GENERATOR_VERSION,
        generator_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        seed=seed,
        source_classification=SOURCE_CLASSIFICATION,
        currency=CURRENCY,
        date_range=(MANIFEST_START_DATE.isoformat(), END_DATE.isoformat()),
        reporting_period=(START_DATE.isoformat(), END_DATE.isoformat()),
        scenario_ids=SCENARIO_IDS,
        store_catalog=DEMO_STORE_CATALOG,
        files=ordered_files,
    )
    manifest_bytes = _manifest_bytes(manifest)
    return SyntheticBundle(manifest, manifest_bytes, ordered_files)


def generate_and_write(
    target: Path,
    *,
    seed: int = DEFAULT_SEED,
    schema_version: str = SCHEMA_VERSION,
) -> SyntheticBundle:
    bundle = generate_demo(seed=seed, schema_version=schema_version)
    target.mkdir(parents=True, exist_ok=True)
    for file in bundle.files:
        destination = target / file.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(file.content)
    (target / "manifest.json").write_bytes(bundle.manifest_bytes)
    return bundle


def _build_tables(rng: Random) -> dict[str, list[dict[str, object]]]:
    stores = [
        {
            **_store_projection(descriptor),
            "source_classification": SOURCE_CLASSIFICATION,
        }
        for descriptor in DEMO_STORE_CATALOG
    ]
    products = [
        {
            "sku_id": sku,
            "product_name": f"Synthetic Product {index:02d}",
            "category": category,
            "unit_price_brl": _money(price),
            "unit_cost_brl": _money(cost),
            "source_classification": SOURCE_CLASSIFICATION,
        }
        for index, (sku, category, price, cost) in enumerate(PRODUCTS, start=1)
    ]
    scenarios = [
        {
            "scenario_id": scenario_id,
            "scenario_name": scenario_id.replace("_", " "),
            "source_classification": SOURCE_CLASSIFICATION,
        }
        for scenario_id in SCENARIO_IDS
    ]

    sales: list[dict[str, object]] = []
    advertising: list[dict[str, object]] = []
    period_bounds = PUBLIC_RELEASE_PROFILE.monthly_periods()
    outbound_totals = {
        period_start: {sku: 0 for sku, *_rest in PRODUCTS}
        for period_start, _period_end in period_bounds
    }
    order_number = 1
    for offset in range((END_DATE - START_DATE).days + 1):
        current_date = START_DATE + timedelta(days=offset)
        current_period_start = date(current_date.year, current_date.month, 1)
        period_offset = (current_date - current_period_start).days
        for index, (sku, _category, price, _cost) in enumerate(PRODUCTS):
            units = 2 + index + rng.randint(0, 4)
            scenario_id = ""
            if (
                current_period_start == CURRENT_PERIOD_START
                and sku == "SYNTH-SKU-001"
                and period_offset >= 15
            ):
                units += 5
                scenario_id = "sales_ads_growth"
            if (
                current_period_start == CURRENT_PERIOD_START
                and sku == "SYNTH-SKU-002"
                and period_offset >= 22
            ):
                units = 0
                scenario_id = "inventory_stockout"
            if (
                current_period_start == CURRENT_PERIOD_START
                and sku == "SYNTH-SKU-004"
                and period_offset >= 15
            ):
                units = max(1, units - 2)
                scenario_id = "profit_decline_ad_spend"
            discount = (
                Decimal("5.00")
                if period_offset % 7 == 0 and units
                else Decimal("0")
            )
            gross = price * units
            sales.append(
                {
                    "date": current_date.isoformat(),
                    "order_id": f"SYNTH-ORDER-{order_number:06d}",
                    "store_id": "SYNTH-STORE-01",
                    "sku_id": sku,
                    "units": units,
                    "unit_price_brl": _money(price),
                    "discount_brl": _money(discount),
                    "gross_sales_brl": _money(gross),
                    "currency": CURRENCY,
                    "scenario_id": scenario_id,
                    "source_classification": SOURCE_CLASSIFICATION,
                }
            )
            order_number += 1
            outbound_totals[current_period_start][sku] += units
            spend = Decimal(7 + index * 2 + rng.randint(0, 5))
            if (
                current_period_start == CURRENT_PERIOD_START
                and sku == "SYNTH-SKU-001"
                and period_offset >= 15
            ):
                spend += Decimal("6")
            if (
                current_period_start == CURRENT_PERIOD_START
                and sku == "SYNTH-SKU-004"
                and period_offset >= 15
            ):
                spend += Decimal("24")
            advertising.append(
                {
                    "date": current_date.isoformat(),
                    "store_id": "SYNTH-STORE-01",
                    "sku_id": sku,
                    "spend_brl": _money(spend),
                    "impressions": 400 + index * 70 + rng.randint(0, 80),
                    "clicks": 20 + index * 3 + rng.randint(0, 8),
                    "attributed_orders": max(0, units - 1),
                    "scenario_id": scenario_id,
                    "source_classification": SOURCE_CLASSIFICATION,
                }
            )

    launch_rng = Random(rng.getrandbits(64))
    product_by_sku = {sku: (category, price, cost) for sku, category, price, cost in PRODUCTS}
    launch_outbound_totals = {
        sku: 0 for sku in LAUNCH_STORE_PROFILE.listed_sku_ids
    }
    launch_order_number = 1
    for offset in range((END_DATE - LAUNCH_STORE_PROFILE.opened_on).days + 1):
        current_date = LAUNCH_STORE_PROFILE.opened_on + timedelta(days=offset)
        forced_zero_day = offset % 7 == 0
        for sku_index, sku in enumerate(LAUNCH_STORE_PROFILE.listed_sku_ids):
            _category, price, _cost = product_by_sku[sku]
            demand_roll = launch_rng.random()
            units = (
                0
                if forced_zero_day or demand_roll < 0.42
                else 1
                if demand_roll < 0.84
                else 2
            )
            discount = (
                Decimal("3.00")
                if units and launch_rng.random() < 0.18
                else Decimal("0")
            )
            sales.append(
                {
                    "date": current_date.isoformat(),
                    "order_id": f"SYNTH-LAUNCH-ORDER-{launch_order_number:06d}",
                    "store_id": LAUNCH_STORE_PROFILE.store_id,
                    "sku_id": sku,
                    "units": units,
                    "unit_price_brl": _money(price),
                    "discount_brl": _money(discount),
                    "gross_sales_brl": _money(price * units),
                    "currency": CURRENCY,
                    "scenario_id": "",
                    "source_classification": SOURCE_CLASSIFICATION,
                }
            )
            launch_order_number += 1
            launch_outbound_totals[sku] += units
            impression_ranges = ((48, 80), (65, 100), (85, 140))
            click_ranges = ((3, 4), (3, 5), (4, 7))
            advertising.append(
                {
                    "date": current_date.isoformat(),
                    "store_id": LAUNCH_STORE_PROFILE.store_id,
                    "sku_id": sku,
                    "spend_brl": _money(Decimal(launch_rng.randint(1, 4))),
                    "impressions": launch_rng.randint(*impression_ranges[sku_index]),
                    "clicks": launch_rng.randint(*click_ranges[sku_index]),
                    "attributed_orders": (
                        1
                        if units and launch_rng.random() < 0.45
                        else 0
                    ),
                    "scenario_id": "",
                    "source_classification": SOURCE_CLASSIFICATION,
                }
            )

    inventory_snapshots = []
    inventory_movements = []
    receipt_lots = []
    outbound_events = []
    platform_fees = []
    fulfillment = []
    refunds = []
    for index, (sku, _category, price, cost) in enumerate(PRODUCTS, start=1):
        total_outbound = sum(
            period_totals[sku] for period_totals in outbound_totals.values()
        )
        on_hand = max(0, 300 + index * 30 - total_outbound)
        scenario_id = "inventory_stockout" if sku == "SYNTH-SKU-002" else ""
        inventory_snapshots.append(
            {
                "date": END_DATE.isoformat(),
                "store_id": "SYNTH-STORE-01",
                "sku_id": sku,
                "on_hand_units": on_hand,
                "inbound_units": 60 if sku == "SYNTH-SKU-002" else 20,
                "scenario_id": scenario_id,
                "source_classification": SOURCE_CLASSIFICATION,
            }
        )
        for movement_index, quantity in enumerate((90 + index * 5, 60 + index * 3), 1):
            inventory_movements.append(
                {
                    "movement_id": f"SYNTH-MOVE-{index:02d}-{movement_index:02d}",
                    "date": (START_DATE + timedelta(days=movement_index * 8)).isoformat(),
                    "store_id": "SYNTH-STORE-01",
                    "sku_id": sku,
                    "movement_type": "receipt",
                    "quantity": quantity,
                    "source_classification": SOURCE_CLASSIFICATION,
                }
            )
        receipt_lots.append(
            {
                "lot_id": f"SYNTH-LOT-{index:02d}-01",
                "receipt_date": (
                    date(2026, 3, 15)
                    if sku == "SYNTH-SKU-003"
                    else date(2026, 5, 31)
                ).isoformat(),
                "store_id": "SYNTH-STORE-01",
                "sku_id": sku,
                "quantity_received": total_outbound + on_hand,
                "unit_cost_brl": _money(cost),
                "scenario_id": "fifo_aging" if sku == "SYNTH-SKU-003" else "",
                "source_classification": SOURCE_CLASSIFICATION,
            }
        )
        for period_number, (period_start, period_end) in enumerate(
            period_bounds,
            start=1,
        ):
            period_units = outbound_totals[period_start][sku]
            outbound_events.append(
                {
                    "outbound_id": f"SYNTH-OUT-{period_number:02d}-{index:04d}",
                    "date": period_end.isoformat(),
                    "store_id": "SYNTH-STORE-01",
                    "sku_id": sku,
                    "quantity": period_units,
                    "source_classification": SOURCE_CLASSIFICATION,
                }
            )
            platform_fees.append(
                {
                    "fee_id": f"SYNTH-FEE-{period_number:02d}-{index:04d}",
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "store_id": "SYNTH-STORE-01",
                    "sku_id": sku,
                    "fee_rate": "0.14",
                    "fee_brl": _money(price * period_units * Decimal("0.14")),
                    "source_classification": SOURCE_CLASSIFICATION,
                }
            )
            fulfillment.append(
                {
                    "fulfillment_id": f"SYNTH-FUL-{period_number:02d}-{index:04d}",
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "store_id": "SYNTH-STORE-01",
                    "sku_id": sku,
                    "fulfilled_units": period_units,
                    "cost_brl": _money(
                        Decimal(period_units) * Decimal("6.50")
                    ),
                    "source_classification": SOURCE_CLASSIFICATION,
                }
            )
            refund_units = (
                index % 3
                if period_start == CURRENT_PERIOD_START
                else (index + 1) % 3
            )
            refunds.append(
                {
                    "refund_id": f"SYNTH-REFUND-{period_number:02d}-{index:04d}",
                    "date": period_end.isoformat(),
                    "store_id": "SYNTH-STORE-01",
                    "sku_id": sku,
                    "units": refund_units,
                    "refund_brl": _money(price * refund_units),
                    "source_classification": SOURCE_CLASSIFICATION,
                }
            )

    for index, sku in enumerate(LAUNCH_STORE_PROFILE.listed_sku_ids, start=1):
        _category, price, cost = product_by_sku[sku]
        total_outbound = launch_outbound_totals[sku]
        on_hand = max(8, 48 + index * 9 - total_outbound)
        inventory_snapshots.append(
            {
                "date": END_DATE.isoformat(),
                "store_id": LAUNCH_STORE_PROFILE.store_id,
                "sku_id": sku,
                "on_hand_units": on_hand,
                "inbound_units": 12 + index * 3,
                "scenario_id": "",
                "source_classification": SOURCE_CLASSIFICATION,
            }
        )
        movement_quantities = (
            28 + index * 4 + launch_rng.randint(0, 5),
            18 + index * 3 + launch_rng.randint(0, 4),
        )
        for movement_index, quantity in enumerate(movement_quantities, start=1):
            inventory_movements.append(
                {
                    "movement_id": f"SYNTH-LAUNCH-MOVE-{index:02d}-{movement_index:02d}",
                    "date": (
                        LAUNCH_STORE_PROFILE.opened_on
                        + timedelta(days=movement_index - 1)
                    ).isoformat(),
                    "store_id": LAUNCH_STORE_PROFILE.store_id,
                    "sku_id": sku,
                    "movement_type": "receipt",
                    "quantity": quantity,
                    "source_classification": SOURCE_CLASSIFICATION,
                }
            )
        receipt_lots.append(
            {
                "lot_id": f"SYNTH-LAUNCH-LOT-{index:02d}-01",
                "receipt_date": LAUNCH_STORE_PROFILE.opened_on.isoformat(),
                "store_id": LAUNCH_STORE_PROFILE.store_id,
                "sku_id": sku,
                "quantity_received": total_outbound + on_hand,
                "unit_cost_brl": _money(cost),
                "scenario_id": "",
                "source_classification": SOURCE_CLASSIFICATION,
            }
        )
        outbound_events.append(
            {
                "outbound_id": f"SYNTH-LAUNCH-OUT-03-{index:04d}",
                "date": END_DATE.isoformat(),
                "store_id": LAUNCH_STORE_PROFILE.store_id,
                "sku_id": sku,
                "quantity": total_outbound,
                "source_classification": SOURCE_CLASSIFICATION,
            }
        )
        platform_fees.append(
            {
                "fee_id": f"SYNTH-LAUNCH-FEE-03-{index:04d}",
                "period_start": CURRENT_PERIOD_START.isoformat(),
                "period_end": END_DATE.isoformat(),
                "store_id": LAUNCH_STORE_PROFILE.store_id,
                "sku_id": sku,
                "fee_rate": "0.14",
                "fee_brl": _money(price * total_outbound * Decimal("0.14")),
                "source_classification": SOURCE_CLASSIFICATION,
            }
        )
        fulfillment.append(
            {
                "fulfillment_id": f"SYNTH-LAUNCH-FUL-03-{index:04d}",
                "period_start": CURRENT_PERIOD_START.isoformat(),
                "period_end": END_DATE.isoformat(),
                "store_id": LAUNCH_STORE_PROFILE.store_id,
                "sku_id": sku,
                "fulfilled_units": total_outbound,
                "cost_brl": _money(Decimal(total_outbound) * Decimal("6.80")),
                "source_classification": SOURCE_CLASSIFICATION,
            }
        )
        refund_units = 1 if index == 2 and total_outbound else 0
        refunds.append(
            {
                "refund_id": f"SYNTH-LAUNCH-REFUND-03-{index:04d}",
                "date": END_DATE.isoformat(),
                "store_id": LAUNCH_STORE_PROFILE.store_id,
                "sku_id": sku,
                "units": refund_units,
                "refund_brl": _money(price * refund_units),
                "source_classification": SOURCE_CLASSIFICATION,
            }
        )

    month_labels = ("MAY", "JUNE", "JULY")
    expenses = [
        {
            "expense_id": f"SYNTH-EXP-{index:04d}-{label}",
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "store_id": "",
            "scope": "shared",
            "expense_type": "software",
            "amount_brl": amount,
            "scenario_id": "profit_bridge_residual" if index > 1 else "",
            "source_classification": SOURCE_CLASSIFICATION,
        }
        for index, ((period_start, period_end), label, amount) in enumerate(
            zip(
                period_bounds,
                month_labels,
                ("430.00", "450.00", "480.00"),
                strict=True,
            ),
            start=1,
        )
    ]
    expenses.append(
        {
            "expense_id": "SYNTH-LAUNCH-EXP-0001-JULY",
            "period_start": CURRENT_PERIOD_START.isoformat(),
            "period_end": END_DATE.isoformat(),
            "store_id": LAUNCH_STORE_PROFILE.store_id,
            "scope": "store",
            "expense_type": "launch_operations",
            "amount_brl": "120.00",
            "scenario_id": "",
            "source_classification": SOURCE_CLASSIFICATION,
        }
    )
    fx_assumptions = [
        {
            "fx_id": f"SYNTH-FX-{index:04d}",
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "currency": "USD",
            "brl_per_usd": rate,
            "source_classification": SOURCE_CLASSIFICATION,
        }
        for index, ((period_start, period_end), rate) in enumerate(
            zip(period_bounds, ("5.25", "5.20", "5.15"), strict=True),
            start=1,
        )
    ]
    fx_effects = [
        {
            "fx_effect_id": f"SYNTH-FX-EFFECT-{label}",
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "store_id": PUBLIC_RELEASE_PROFILE.store_id,
            "effect_brl": effect,
            "source_classification": SOURCE_CLASSIFICATION,
        }
        for (period_start, period_end), label, effect in zip(
            period_bounds,
            month_labels,
            ("3.00", "5.00", "-2.00"),
            strict=True,
        )
    ]
    fx_effects.append(
        {
            "fx_effect_id": "SYNTH-LAUNCH-FX-EFFECT-JULY",
            "period_start": CURRENT_PERIOD_START.isoformat(),
            "period_end": END_DATE.isoformat(),
            "store_id": LAUNCH_STORE_PROFILE.store_id,
            "effect_brl": "1.25",
            "source_classification": SOURCE_CLASSIFICATION,
        }
    )
    other_variable_costs = [
        {
            "cost_id": f"SYNTH-VARIABLE-COST-{label}",
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "store_id": PUBLIC_RELEASE_PROFILE.store_id,
            "cost_brl": amount,
            "scenario_id": "profit_bridge_residual" if label != "MAY" else "",
            "source_classification": SOURCE_CLASSIFICATION,
        }
        for (period_start, period_end), label, amount in zip(
            period_bounds,
            month_labels,
            ("600.00", "650.00", "725.00"),
            strict=True,
        )
    ]
    other_variable_costs.append(
        {
            "cost_id": "SYNTH-LAUNCH-VARIABLE-COST-JULY",
            "period_start": CURRENT_PERIOD_START.isoformat(),
            "period_end": END_DATE.isoformat(),
            "store_id": LAUNCH_STORE_PROFILE.store_id,
            "cost_brl": "95.00",
            "scenario_id": "",
            "source_classification": SOURCE_CLASSIFICATION,
        }
    )
    forecasts = [
        {
            "forecast_id": f"SYNTH-FORECAST-{horizon:03d}-{scenario.upper()}",
            "new_product_id": "SYNTH-NEW-001",
            "horizon_days": horizon,
            "forecast_scenario": scenario,
            "units": round(horizon * multiplier),
            "similar_sku_ids": "SYNTH-SKU-001|SYNTH-SKU-006",
            "scenario_id": "new_product_low_base_high",
            "source_classification": SOURCE_CLASSIFICATION,
        }
        for horizon in (7, 30, 90)
        for scenario, multiplier in (("low", 1.1), ("base", 1.6), ("high", 2.2))
    ]
    action_outcomes = [
        {
            "action_id": "SYNTH-ACTION-0001",
            "outcome_id": "SYNTH-OUTCOME-0001",
            "decision": "approved",
            "result": "synthetic_positive",
            "scenario_id": "action_outcome",
            "source_classification": SOURCE_CLASSIFICATION,
        },
        {
            "action_id": "SYNTH-ACTION-0002",
            "outcome_id": "SYNTH-OUTCOME-0002",
            "decision": "reviewed",
            "result": "needs_clarification",
            "scenario_id": "chat_clarification",
            "source_classification": SOURCE_CLASSIFICATION,
        },
    ]
    replenishment_policies = [
        {
            "policy_id": f"SYNTH-POLICY-{index:03d}",
            "store_id": MAIN_STORE_PROFILE.store_id,
            "sku_id": sku,
            "lead_time_days": 10 + index,
            "safety_stock_units": 15 + index,
            "reorder_point_units": 35 + index * 2,
            "target_cover_days": 30,
            "unit_cost_brl": _money(cost),
            "source_classification": SOURCE_CLASSIFICATION,
        }
        for index, (sku, _category, _price, cost) in enumerate(PRODUCTS, start=1)
    ]
    replenishment_policies.extend(
        {
            "policy_id": f"SYNTH-LAUNCH-POLICY-{index:03d}",
            "store_id": LAUNCH_STORE_PROFILE.store_id,
            "sku_id": sku,
            "lead_time_days": 14 + index,
            "safety_stock_units": 6 + index,
            "reorder_point_units": 14 + index * 2,
            "target_cover_days": 24,
            "unit_cost_brl": _money(product_by_sku[sku][2]),
            "source_classification": SOURCE_CLASSIFICATION,
        }
        for index, sku in enumerate(
            LAUNCH_STORE_PROFILE.listed_sku_ids,
            start=1,
        )
    )
    return {
        "action_outcomes": action_outcomes,
        "advertising": advertising,
        "expenses": expenses,
        "forecasts": forecasts,
        "fulfillment": fulfillment,
        "fx_assumptions": fx_assumptions,
        "fx_effects": fx_effects,
        "inventory_movements": inventory_movements,
        "inventory_snapshots": inventory_snapshots,
        "outbound_events": outbound_events,
        "other_variable_costs": other_variable_costs,
        "platform_fees": platform_fees,
        "products": products,
        "receipt_lots": receipt_lots,
        "replenishment_policies": replenishment_policies,
        "refunds": refunds,
        "sales": sales,
        "scenarios": scenarios,
        "stores": stores,
    }


def _analysis_bundle_file(
    tables: dict[str, list[dict[str, object]]],
    store_catalog: tuple[StoreDescriptor, ...],
) -> SyntheticFile:
    role_map = {
        "daily_sales": "sales",
        "shopee_advertising": "advertising",
        "product_inventory_sales": "inventory_snapshots",
        "inventory_movement": "inventory_movements",
        "inventory_receipt_lot": "receipt_lots",
        "outbound_event": "outbound_events",
        "refund": "refunds",
        "settlement": "platform_fees",
        "fulfillment_cost": "fulfillment",
        "operating_expense": "expenses",
        "fx_assumption": "fx_assumptions",
        "fx_effect": "fx_effects",
        "other_variable_cost": "other_variable_costs",
        "replenishment_policy": "replenishment_policies",
        "product_catalog": "products",
        "new_product_benchmark": "forecasts",
    }
    canonical_tables = {}
    for role, source_name in sorted(role_map.items()):
        rows = tables[source_name]
        if role == "product_catalog":
            canonical_tables[role] = [
                {**row, "attributes": PRODUCT_ATTRIBUTES[str(row["sku_id"])]}
                for row in rows
            ]
        else:
            canonical_tables[role] = rows
    canonical_tables["new_product_backtest_window"] = _forecast_backtest_windows()
    content = (
        json.dumps(
            {
                "schema_version": "canonical.analysis.v1",
                "store_catalog": [
                    _store_projection(descriptor)
                    for descriptor in store_catalog
                ],
                "tables": canonical_tables,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode()
    return SyntheticFile(
        "analysis_bundle.json",
        content,
        JSON_MEDIA_TYPE,
        sum(len(rows) for rows in canonical_tables.values()),
    )


def _forecast_backtest_windows() -> list[dict[str, object]]:
    """Provide actual post-launch outcomes separated from pre-launch evidence."""

    launch_date = date(2026, 5, 1)
    actual_daily_units = [
        4 + (offset % 4) + (1 if offset >= 30 else 0) + (1 if offset >= 60 else 0)
        for offset in range(90)
    ]
    analogs = []
    for index, (net_price, daily_ad, daily_units) in enumerate(
        (
            ("104.90", "10.00", 6),
            ("112.90", "13.00", 7),
            ("99.90", "9.00", 5),
        ),
        start=1,
    ):
        analogs.append(
            {
                "sku_id": f"SYNTH-HIDDEN-ANALOG-{index:03d}",
                "category": "travel_bag",
                "attributes": ["portable", "zippered", "compact"],
                "net_price_brl": net_price,
                "daily_ad_spend_brl": daily_ad,
                "history_start": "2026-03-15",
                "history_end": "2026-04-30",
                "history_days": 47,
                "total_units": daily_units * 47,
                "unit_cost_brl": "38.00",
                "unknown_evidence": [],
            }
        )
    return [
        {
            "window_id": "SYNTH-HIDDEN-LAUNCH-001",
            "training_cutoff": "2026-04-30",
            "actual_start": launch_date.isoformat(),
            "actual_end": (launch_date + timedelta(days=89)).isoformat(),
            "candidate": {
                "product_name": "Synthetic Hidden Launch Organizer",
                "category": "travel_bag",
                "attributes": ["portable", "zippered", "compact"],
                "planned_launch_date": launch_date.isoformat(),
                "planned_price_brl": "109.90",
                "expected_discount_brl": "4.00",
                "unit_cost_brl": "38.00",
                "opening_inventory_units": 60,
                "moq_units": 20,
                "lead_time_days": 18,
                "planned_daily_ad_brl": "12.00",
            },
            "safety_stock_units": 20,
            "analogs": analogs,
            "actual_daily_units": actual_daily_units,
            "source_classification": SOURCE_CLASSIFICATION,
        }
    ]


def _csv_file(path: str, rows: list[dict[str, object]]) -> SyntheticFile:
    if not rows:
        raise ValueError("synthetic_table_must_not_be_empty")
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=tuple(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return SyntheticFile(path, output.getvalue().encode(), CSV_MEDIA_TYPE, len(rows))


def _xlsx_file(
    path: str,
    tables: dict[str, list[dict[str, object]]],
) -> SyntheticFile:
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    workbook.set_properties(
        {
            "title": (
                "BizPulse Pure Synthetic Cost Inputs"
                if path == "bizpulse_demo_costs.xlsx"
                else "BizPulse Pure Synthetic Operator Import"
            ),
            "author": "NEWCaostone generator",
            "company": "NEWCaostone",
            "created": datetime(2026, 8, 13, 0, 0, 0),
        }
    )
    total_rows = 0
    for sheet_name, rows in tables.items():
        worksheet = workbook.add_worksheet(sheet_name)
        headers = tuple(rows[0])
        header_format = workbook.add_format(
            {
                "bold": True,
                "font_color": "#FFFFFF",
                "bg_color": "#0F766E",
                "bottom": 1,
                "bottom_color": "#115E59",
            }
        )
        worksheet.hide_gridlines(2)
        worksheet.freeze_panes(1, 0)
        worksheet.write_row(0, 0, headers, header_format)
        for row_index, row in enumerate(rows, start=1):
            worksheet.write_row(row_index, 0, [row[header] for header in headers])
        for column_index, header in enumerate(headers):
            width = max(
                len(str(header)),
                *(len(str(row[header])) for row in rows),
            )
            worksheet.set_column(column_index, column_index, min(width + 2, 28))
        total_rows += len(rows)
    workbook.close()
    return SyntheticFile(path, output.getvalue(), XLSX_MEDIA_TYPE, total_rows)


def _manifest_bytes(manifest: SyntheticManifest) -> bytes:
    payload = {
        "schema_version": manifest.schema_version,
        "generator": {
            "version": manifest.generator_version,
            "source_sha256": manifest.generator_source_sha256,
        },
        "seed": manifest.seed,
        "source_classification": manifest.source_classification,
        "currency": manifest.currency,
        "date_range": {
            "start": manifest.date_range[0],
            "end": manifest.date_range[1],
        },
        "reporting_period": {
            "start": manifest.reporting_period[0],
            "end": manifest.reporting_period[1],
        },
        "scenario_ids": list(manifest.scenario_ids),
        "store_catalog": [
            _store_projection(descriptor)
            for descriptor in manifest.store_catalog
        ],
        "files": [
            {
                "path": file.relative_path,
                "media_type": file.media_type,
                "sha256": file.sha256,
                "row_count": file.row_count,
            }
            for file in manifest.files
        ],
    }
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode()


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def _store_projection(descriptor: StoreDescriptor) -> dict[str, object]:
    return {
        "store_id": descriptor.store_id,
        "display_name_en": descriptor.display_name_en,
        "display_name_zh": descriptor.display_name_zh,
        "currency": descriptor.currency,
        "opened_on": (
            descriptor.opened_on.isoformat()
            if descriptor.opened_on is not None
            else None
        ),
        "lifecycle": descriptor.lifecycle,
        "has_data": descriptor.has_data,
    }


def _sku_cost_rows(
    products: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "sku_id": row["sku_id"],
            "product_name": row["product_name"],
            "currency": CURRENCY,
            "valid_from": START_DATE.isoformat(),
            "unit_cost_brl": row["unit_cost_brl"],
            "source_classification": row["source_classification"],
        }
        for row in products
    ]
